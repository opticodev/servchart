"""Background jobs next to the web server: scheduled report emails (Settings -> Reports),
certificate and image update checks, and history clean-up.

Checks once a minute; a report is sent when its slot (daily / Mondays / the 1st, at
SERVCHART_REPORT_HOUR local time) has passed since the last one. If the hub was down
at that time, the report goes out when it comes back - once, not once per missed slot.
"""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from inventory.models import AuditEvent, SiteSettings
from inventory.reports_api import email_configured, is_due, parse_recipients, send_report

log = logging.getLogger("servchart.reports")


def run_once(now=None) -> bool:
    """Send the report if it's due. Returns True when one was sent."""
    site = SiteSettings.load()
    if site.report_schedule == "off" or not email_configured():
        return False
    now = now or timezone.localtime()
    if not is_due(site.report_schedule, site.report_last_sent, now, settings.SERVCHART_REPORT_HOUR):
        return False
    recipients, error = parse_recipients(site.report_recipients)
    if error or not recipients:
        return False
    # mark first, so a failing SMTP server doesn't get hammered every minute
    site.report_last_sent = now
    site.save(update_fields=["report_last_sent", "updated_at"])
    try:
        send_report(recipients, site)
    except Exception as exc:
        log.warning("scheduled report failed: %s", exc)
        AuditEvent.objects.create(action="report.scheduled.failed", target=", ".join(recipients), detail={"error": str(exc)[:300]})
        return False
    AuditEvent.objects.create(action="report.scheduled", target=", ".join(recipients), detail={"schedule": site.report_schedule})
    log.info("sent %s report to %s", site.report_schedule, ", ".join(recipients))
    return True


def background_checks(state: dict, now=None) -> None:
    """Certificates, image updates and history clean-up; each at its own pace."""
    import time as _t

    from inventory import checks, history

    t = now or _t.time()
    if t - state.get("certs", 0) >= 600:  # each certificate itself is re-checked every SERVCHART_CERT_CHECK_HOURS
        state["certs"] = t
        checks.run_cert_checks()
    if t - state.get("images", 0) >= 900:
        state["images"] = t
        checks.run_image_checks()
    if t - state.get("purge", 0) >= 3600:
        state["purge"] = t
        history.purge()


class Command(BaseCommand):
    help = "Email the infrastructure report on the schedule set in Settings -> Reports."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, once=False, **options):
        state: dict = {}
        while True:
            close_old_connections()
            try:
                run_once()
            except Exception:
                log.exception("report scheduler error")
            try:
                background_checks(state)
            except Exception:
                log.exception("background checks error")
            if once:
                return
            time.sleep(60)
