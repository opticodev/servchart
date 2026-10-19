"""Send scheduled report emails (Settings -> Reports). Runs next to the web server.

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


class Command(BaseCommand):
    help = "Email the infrastructure report on the schedule set in Settings -> Reports."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, once=False, **options):
        while True:
            close_old_connections()
            try:
                run_once()
            except Exception:
                log.exception("report scheduler error")
            if once:
                return
            time.sleep(60)
