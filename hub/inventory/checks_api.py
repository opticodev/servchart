"""Settings -> Checks (certificates, image updates) and host history for the sparklines."""

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .audit import audit
from .checks import HOSTNAME_RE, cert_payload, check_cert, image_status, run_image_checks
from .history import series
from .models import CertCheck, Host, ImageCheck

MAX_CERTS = 200


def _forbidden():
    return Response({"error": "Only admins can manage checks."}, status=status.HTTP_403_FORBIDDEN)


@api_view(["GET", "POST"])
def certs(request):
    if request.method == "GET":
        return Response([cert_payload(c) for c in CertCheck.objects.all()])
    if not request.user.is_staff:
        return _forbidden()
    raw = str(request.data.get("hostname") or "").strip().lower()
    for prefix in ("https://", "http://"):
        raw = raw.removeprefix(prefix)
    raw = raw.split("/", 1)[0]
    hostname, _, port = raw.partition(":")
    try:
        port = int(port or request.data.get("port") or 443)
    except (TypeError, ValueError):
        port = 0
    if not HOSTNAME_RE.match(hostname) or not 1 <= port <= 65535:
        return Response({"error": "Enter a host name like example.com or example.com:8443."}, status=status.HTTP_400_BAD_REQUEST)
    if CertCheck.objects.count() >= MAX_CERTS:
        return Response({"error": f"At most {MAX_CERTS} certificates."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        with transaction.atomic():
            c = CertCheck.objects.create(hostname=hostname, port=port)
    except IntegrityError:
        return Response({"error": f"{hostname}:{port} is already checked."}, status=status.HTTP_400_BAD_REQUEST)
    audit(request, "check.cert.add", f"{hostname}:{port}")
    check_cert(c)  # first result right away
    return Response(cert_payload(c), status=status.HTTP_201_CREATED)


@api_view(["DELETE", "POST"])
def cert_detail(request, pk: int):
    if not request.user.is_staff:
        return _forbidden()
    c = CertCheck.objects.filter(pk=pk).first()
    if c is None:
        return Response({"error": "No such check."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "POST":  # check again now
        return Response(cert_payload(check_cert(c)))
    audit(request, "check.cert.remove", str(c))
    c.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "POST"])
def images(request):
    if request.method == "POST":
        if not request.user.is_staff:
            return _forbidden()
        if not settings.SERVCHART_IMAGE_CHECKS:
            return Response({"error": "Image checks are off (SERVCHART_IMAGE_CHECKS=0)."}, status=status.HTTP_400_BAD_REQUEST)
        run_image_checks(force=True, limit=200)
    checks = {c.ref: c for c in ImageCheck.objects.all()}
    rows = []
    for h in Host.objects.filter(enabled=True):
        for c in (h.snapshot or {}).get("containers") or []:
            st = image_status(c, checks)
            rows.append({"host": h.name, "host_pk": h.pk, "container": c["name"], "image": c.get("image"), **(st or {"state": "pending"})})
    return Response({"enabled": settings.SERVCHART_IMAGE_CHECKS, "every_hours": settings.SERVCHART_IMAGE_CHECK_HOURS, "items": rows})


@api_view(["GET"])
def host_history(request, pk: int):
    host = Host.objects.filter(pk=pk).first()
    if host is None:
        return Response({"error": "No such host."}, status=status.HTTP_404_NOT_FOUND)
    try:
        hours = max(1, min(int(request.GET.get("hours", 24)), 24 * settings.SERVCHART_HISTORY_DAYS))
    except ValueError:
        hours = 24
    return Response({"hours": hours, **series(host, hours)})


@api_view(["GET", "PATCH"])
def public_addresses(request):
    """Settings -> Hosts: your public IPs / DDNS names (see addresses.py)."""
    from .addresses import parse, resolve
    from .models import SiteSettings

    site = SiteSettings.load()
    if request.method == "PATCH":
        if not request.user.is_staff:
            return _forbidden()
        entries, error = parse(str(request.data.get("addresses") or ""))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        site.public_addresses = "\n".join(entries)
        site.save(update_fields=["public_addresses", "updated_at"])
        audit(request, "addresses.update", ", ".join(entries))
    entries, _ = parse(site.public_addresses)
    return Response({"addresses": entries, "resolved": sorted(resolve(entries))})
