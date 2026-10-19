"""Custom name, accent color, logo and favicon (Settings -> Appearance).

Uploads are identified by their content (magic bytes), never by the file name or the
browser's claimed type. SVGs are rejected if they contain scripts or event handlers, and
every image is served with a sandboxing Content-Security-Policy and nosniff.
"""

import re

from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .audit import audit
from .models import SiteSettings

MAX_BYTES = 512 * 1024
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
SVG_FORBIDDEN = re.compile(rb"<\s*script|<\s*foreignobject|<\s*iframe|<\s*embed|<\s*object|\bon[a-z]+\s*=|javascript:|data:text/html", re.IGNORECASE)
KINDS = ("logo", "favicon")


def sniff(data: bytes):
    """Content type from the file's bytes, or None if it isn't an image we accept."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"
    head = data[:1024].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in head:
        return "image/svg+xml"
    return None


def validate_image(data: bytes):
    """-> (content_type, None) or (None, error message)."""
    if not data:
        return None, "The file is empty."
    if len(data) > MAX_BYTES:
        return None, f"Images must be {MAX_BYTES // 1024} KB or smaller."
    ctype = sniff(data)
    if ctype is None:
        return None, "Use a PNG, JPEG, WebP, ICO or SVG image."
    if ctype == "image/svg+xml" and SVG_FORBIDDEN.search(data):
        return None, "This SVG contains scripts or event handlers, which aren't allowed."
    return ctype, None


def branding_payload(site: SiteSettings | None = None) -> dict:
    from servchart import __version__

    site = site or SiteSettings.load()
    stamp = int(site.updated_at.timestamp()) if site.updated_at else 0
    return {
        "app_name": site.app_name or "ServChart",
        "accent_color": site.accent_color or None,
        "logo_url": f"/branding/logo?v={stamp}" if site.logo else None,
        "favicon_url": f"/branding/favicon?v={stamp}" if site.favicon else None,
        "version": __version__,
    }


@api_view(["GET", "PATCH"])
@permission_classes([permissions.AllowAny])
def branding(request):
    if request.method == "GET":  # public: the login page shows the name and logo
        return Response(branding_payload())
    if not (request.user and request.user.is_authenticated and request.user.is_staff):
        return Response({"error": "Only admins can change the appearance."}, status=status.HTTP_403_FORBIDDEN)
    site = SiteSettings.load()
    if "app_name" in request.data:
        name = str(request.data["app_name"]).strip()
        if not name or len(name) > 60:
            return Response({"error": "The name must be 1-60 characters."}, status=status.HTTP_400_BAD_REQUEST)
        site.app_name = name
    if "accent_color" in request.data:
        color = str(request.data["accent_color"] or "").strip()
        if color and not HEX_COLOR.match(color):
            return Response({"error": "Use a color like #2563eb."}, status=status.HTTP_400_BAD_REQUEST)
        site.accent_color = color.lower()
    site.save()
    audit(request, "branding.update", "appearance", app_name=site.app_name, accent_color=site.accent_color)
    return Response(branding_payload(site))


@api_view(["POST", "DELETE"])
def branding_image(request, kind: str):
    if kind not in KINDS:
        return Response({"error": "Unknown image."}, status=status.HTTP_404_NOT_FOUND)
    if not request.user.is_staff:
        return Response({"error": "Only admins can change the appearance."}, status=status.HTTP_403_FORBIDDEN)
    site = SiteSettings.load()
    if request.method == "DELETE":
        setattr(site, kind, None)
        setattr(site, f"{kind}_type", "")
        site.save()
        audit(request, f"branding.{kind}.remove", kind)
        return Response(branding_payload(site))
    upload = request.FILES.get("file")
    if upload is None:
        return Response({"error": "Choose an image file."}, status=status.HTTP_400_BAD_REQUEST)
    data = upload.read(MAX_BYTES + 1)
    ctype, error = validate_image(data)
    if error:
        return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
    setattr(site, kind, data)
    setattr(site, f"{kind}_type", ctype)
    site.save()
    audit(request, f"branding.{kind}.upload", kind, type=ctype, bytes=len(data))
    return Response(branding_payload(site))


@require_GET
def serve_image(request, kind: str):
    if kind not in KINDS:
        raise Http404
    site = SiteSettings.load()
    data = getattr(site, kind)
    if not data:
        raise Http404
    resp = HttpResponse(bytes(data), content_type=getattr(site, f"{kind}_type") or "application/octet-stream")
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    resp["Cache-Control"] = "public, max-age=300"
    return resp


def context(request):
    """Template context processor: branding for the login page and reports."""
    try:
        return {"branding": branding_payload()}
    except Exception:  # e.g. before migrations ran
        return {"branding": {"app_name": "ServChart", "accent_color": None, "logo_url": None, "favicon_url": None}}
