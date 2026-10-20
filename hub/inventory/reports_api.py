"""Report endpoints: printable page, JSON/CSV exports, email (now or on a schedule),
and the activity log."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMultiAlternatives
from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .audit import audit
from .graph import build_graph
from .models import AuditEvent, SiteSettings
from .report import CSV_KINDS, build_report, to_csv
from .report_html import logo_data_uri, render

log = logging.getLogger(__name__)

SCHEDULES = ("off", "daily", "weekly", "monthly")
EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
MAX_RECIPIENTS = 20


def current_report(site: SiteSettings | None = None) -> dict:
    from .checks import cert_payload
    from .history import changes
    from .models import CertCheck, Host

    site = site or SiteSettings.load()
    hosts = list(Host.objects.filter(enabled=True))
    return build_report(
        build_graph(hosts),
        site.app_name or "ServChart",
        certs=[cert_payload(c) for c in CertCheck.objects.all()],
        changes={h.name: changes(h, h.snapshot or {}) for h in hosts},
        limits={
            "disk_warn": settings.SERVCHART_DISK_WARN,
            "disk_critical": settings.SERVCHART_DISK_CRITICAL,
            "cert_warn_days": settings.SERVCHART_CERT_WARN_DAYS,
        },
    )


def render_html(report: dict, site: SiteSettings, printable: bool = True) -> str:
    from servchart import __version__

    return render(
        report,
        app_name=site.app_name or "ServChart",
        accent=site.accent_color or None,
        logo_uri=logo_data_uri(site.logo, site.logo_type),
        version=__version__,
        printable=printable,
        base_url=settings.SERVCHART_PUBLIC_URL,
    )


def _stamp() -> str:
    return timezone.now().strftime("%Y-%m-%d")


@login_required
def report_page(request):
    site = SiteSettings.load()
    resp = HttpResponse(render_html(current_report(site), site), content_type="text/html; charset=utf-8")
    resp["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'"
    return resp


@api_view(["GET"])
def report_json(request):
    resp = Response(current_report())
    if request.GET.get("download"):
        resp["Content-Disposition"] = f'attachment; filename="servchart-report-{_stamp()}.json"'
    return resp


@api_view(["GET"])
def report_csv(request, kind: str):
    if kind not in CSV_KINDS:
        raise Http404
    resp = HttpResponse(to_csv(current_report(), kind), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="servchart-{kind}-{_stamp()}.csv"'
    return resp


# --- email ---------------------------------------------------------------------------------


def email_configured() -> bool:
    return bool(settings.EMAIL_HOST)


def parse_recipients(value) -> tuple[list[str], str | None]:
    items = value if isinstance(value, list) else re.split(r"[,;\s]+", str(value or ""))
    out = []
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        if not EMAIL_RE.match(item) or len(item) > 254:
            return [], f"{item!r} isn't an email address."
        if item.lower() not in (o.lower() for o in out):
            out.append(item)
    if len(out) > MAX_RECIPIENTS:
        return [], f"At most {MAX_RECIPIENTS} recipients."
    return out, None


def send_report(recipients: list[str], site: SiteSettings | None = None) -> dict:
    """Email the report (HTML body plus a plain-text summary). Returns the report summary."""
    site = site or SiteSettings.load()
    report = current_report(site)
    s = report["summary"]
    to_review = s["findings"]["high"] + s["findings"]["medium"]
    subject = f"{report['title']}: {s['running']}/{s['containers']} running, {to_review} finding{'s' if to_review != 1 else ''} to review"
    lines = [
        report["title"],
        "",
        f"Hosts online: {s['hosts_online']}/{s['hosts']}",
        f"Containers running: {s['running']}/{s['containers']}",
        f"Unhealthy: {s['unhealthy']}",
        "",
        "Findings:",
    ]
    lines += [f"  [{f['severity']}] {f['target']}: {f['message']}" for f in report["findings"] if f["severity"] in ("high", "medium")] or ["  none"]
    if settings.SERVCHART_PUBLIC_URL:
        lines += ["", f"Full report: {settings.SERVCHART_PUBLIC_URL}/report/"]
    msg = EmailMultiAlternatives(subject, "\n".join(lines), settings.DEFAULT_FROM_EMAIL, recipients)
    msg.attach_alternative(render_html(report, site, printable=False), "text/html")
    msg.attach(f"servchart-report-{_stamp()}.json", json.dumps(report, indent=2, default=str), "application/json")
    msg.send(fail_silently=False)
    return s


@api_view(["POST"])
def report_send(request):
    if not request.user.is_staff:
        return Response({"error": "Only admins can email reports."}, status=status.HTTP_403_FORBIDDEN)
    if not email_configured():
        return Response({"error": "Email isn't set up. Set SERVCHART_SMTP_HOST (and friends) on the hub."}, status=status.HTTP_400_BAD_REQUEST)
    site = SiteSettings.load()
    recipients, error = parse_recipients(request.data.get("recipients") or site.report_recipients)
    if error:
        return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
    if not recipients:
        return Response({"error": "Add at least one recipient."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        send_report(recipients, site)
    except Exception as exc:  # SMTP errors are shown to the admin, not hidden
        log.warning("report email failed: %s", exc)
        return Response({"error": f"Sending failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
    audit(request, "report.send", ", ".join(recipients))
    return Response({"ok": True, "recipients": recipients})


def schedule_payload(site: SiteSettings) -> dict:
    return {
        "schedule": site.report_schedule,
        "recipients": [r for r in site.report_recipients.split(",") if r],
        "last_sent": site.report_last_sent.isoformat() if site.report_last_sent else None,
        "next_run": next_run(site).isoformat() if next_run(site) else None,
        "hour": settings.SERVCHART_REPORT_HOUR,
        "email_configured": email_configured(),
        "from_email": settings.DEFAULT_FROM_EMAIL if email_configured() else None,
    }


@api_view(["GET", "PATCH"])
def report_schedule(request):
    if not request.user.is_staff:
        return Response({"error": "Only admins can manage reports."}, status=status.HTTP_403_FORBIDDEN)
    site = SiteSettings.load()
    if request.method == "PATCH":
        if "schedule" in request.data:
            if request.data["schedule"] not in SCHEDULES:
                return Response({"error": f"Schedule must be one of {', '.join(SCHEDULES)}."}, status=status.HTTP_400_BAD_REQUEST)
            site.report_schedule = request.data["schedule"]
        if "recipients" in request.data:
            recipients, error = parse_recipients(request.data["recipients"])
            if error:
                return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
            site.report_recipients = ",".join(recipients)
        if site.report_schedule != "off" and not site.report_recipients:
            return Response({"error": "Add at least one recipient for scheduled reports."}, status=status.HTTP_400_BAD_REQUEST)
        site.save()
        audit(request, "report.schedule", site.report_schedule, recipients=site.report_recipients)
    return Response(schedule_payload(site))


# --- schedule logic (used by the report_scheduler command) ----------------------------------


def _slot(now: datetime, schedule: str, hour: int) -> datetime | None:
    """The most recent moment a report was due at or before `now`."""
    at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if schedule == "daily":
        return at if at <= now else at - timedelta(days=1)
    if schedule == "weekly":  # Mondays
        at -= timedelta(days=at.weekday())
        return at if at <= now else at - timedelta(days=7)
    if schedule == "monthly":  # the 1st
        at = at.replace(day=1)
        if at > now:
            prev = at - timedelta(days=1)
            at = prev.replace(day=1)
        return at
    return None


def is_due(schedule: str, last_sent: datetime | None, now: datetime, hour: int) -> bool:
    slot = _slot(now, schedule, hour)
    return slot is not None and (last_sent is None or last_sent < slot)


def next_run(site: SiteSettings) -> datetime | None:
    if site.report_schedule == "off":
        return None
    now = timezone.localtime()
    hour = settings.SERVCHART_REPORT_HOUR
    if is_due(site.report_schedule, site.report_last_sent, now, hour):
        return now
    slot = _slot(now, site.report_schedule, hour)
    if site.report_schedule == "daily":
        return slot + timedelta(days=1)
    if site.report_schedule == "weekly":
        return slot + timedelta(days=7)
    return (slot + timedelta(days=32)).replace(day=1)


# --- activity log ----------------------------------------------------------------------------


@api_view(["GET"])
def audit_list(request):
    if not request.user.is_staff:
        return Response({"error": "Only admins can see the activity log."}, status=status.HTTP_403_FORBIDDEN)
    qs = AuditEvent.objects.all()
    if request.GET.get("action"):
        qs = qs.filter(action__startswith=request.GET["action"])
    try:
        limit = max(1, min(int(request.GET.get("limit", 100)), 500))
    except ValueError:
        limit = 100
    return Response(
        [
            {"id": e.pk, "at": e.created_at.isoformat(), "user": e.username or None, "action": e.action, "target": e.target, "detail": e.detail, "ip": e.ip}
            for e in qs[:limit]
        ]
    )
