"""Checks the hub runs itself, from the background scheduler:

* TLS certificates of the endpoints listed in Settings -> Checks: days until expiry, issuer,
  and whether the certificate is trusted at all.
* Image updates: for every image reference in use, ask its registry (anonymously) whether
  the tag now points to a different image, and whether a newer version tag exists.
  Only the image name and tag leave the hub. Private registries that need a login are
  skipped. Turn it off with SERVCHART_IMAGE_CHECKS=0.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.utils import timezone

from .models import CertCheck, Host, ImageCheck

log = logging.getLogger("servchart.checks")

HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9])?$")
TIMEOUT = 10
USER_AGENT = "servchart-hub (image update check)"


# --- certificates -----------------------------------------------------------------------------


def fetch_cert(hostname: str, port: int = 443) -> dict:
    """-> {expires_at, issuer, error}. A certificate that isn't trusted is reported as an error."""
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, port), timeout=TIMEOUT) as sock, ctx.wrap_socket(sock, server_hostname=hostname) as tls:
            cert = tls.getpeercert()
    except ssl.SSLCertVerificationError as exc:
        return {"expires_at": None, "issuer": "", "error": f"Not trusted: {exc.verify_message or exc.reason}"[:500]}
    except (OSError, ssl.SSLError) as exc:
        return {"expires_at": None, "issuer": "", "error": f"Couldn't connect: {exc}"[:500]}
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), dt_timezone.utc)
    issuer = dict(x[0] for x in cert.get("issuer") or [])
    return {"expires_at": expires, "issuer": issuer.get("organizationName") or issuer.get("commonName") or "", "error": ""}


def check_cert(c: CertCheck) -> CertCheck:
    r = fetch_cert(c.hostname, c.port)
    c.expires_at, c.issuer, c.error, c.checked_at = r["expires_at"], r["issuer"][:255], r["error"], timezone.now()
    c.save(update_fields=["expires_at", "issuer", "error", "checked_at"])
    return c


def cert_payload(c: CertCheck) -> dict:
    days = (c.expires_at - timezone.now()).days if c.expires_at else None
    return {
        "id": c.pk,
        "hostname": c.hostname,
        "port": c.port,
        "checked_at": c.checked_at.isoformat() if c.checked_at else None,
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "days_left": days,
        "issuer": c.issuer,
        "error": c.error,
    }


def run_cert_checks(force: bool = False) -> int:
    due = timezone.now() - timedelta(hours=settings.SERVCHART_CERT_CHECK_HOURS)
    n = 0
    for c in CertCheck.objects.all():
        if force or not c.checked_at or c.checked_at < due:
            check_cert(c)
            n += 1
    return n


# --- image references and registries ----------------------------------------------------------


def parse_ref(image: str) -> tuple[str, str, str] | None:
    """"nginx:1.27" -> ("registry-1.docker.io", "library/nginx", "1.27"). None for digests/ids."""
    if not image or "@" in image or image.startswith("sha256:"):
        return None
    name, tag = image, "latest"
    last = image.rsplit("/", 1)[-1]
    if ":" in last:
        name, tag = image.rsplit(":", 1)
    parts = name.split("/", 1)
    if len(parts) == 2 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry, repo = parts
    else:
        registry, repo = "docker.io", name
    if registry in ("docker.io", "index.docker.io"):
        registry = "registry-1.docker.io"
        if "/" not in repo:
            repo = "library/" + repo
    return registry, repo, tag


def ref_key(image: str) -> str | None:
    p = parse_ref(image)
    return f"{p[0]}/{p[1]}:{p[2]}" if p else None


MANIFEST_TYPES = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
    ]
)


class RegistryError(Exception):
    pass


def _bearer_token(challenge: str) -> str | None:
    """Anonymous token from a `WWW-Authenticate: Bearer realm=...,service=...,scope=...` challenge."""
    if not challenge.lower().startswith("bearer "):
        return None
    params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm = params.pop("realm", None)
    if not realm or not realm.startswith("https://"):
        return None
    url = realm + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        doc = json.loads(resp.read(65536))
    return doc.get("token") or doc.get("access_token")


def registry_request(registry: str, path: str, method: str = "GET", accept: str = "application/json", _token=None):
    """-> (headers, body bytes). Handles the anonymous bearer-token dance once."""
    headers = {"Accept": accept, "User-Agent": USER_AGENT}
    if _token:
        headers["Authorization"] = f"Bearer {_token}"
    req = urllib.request.Request(f"https://{registry}/v2/{path}", method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.headers, (resp.read(2 * 1024 * 1024) if method == "GET" else b"")
    except urllib.error.HTTPError as exc:
        if exc.code == 401 and not _token:
            token = _bearer_token(exc.headers.get("WWW-Authenticate", ""))
            if token:
                return registry_request(registry, path, method, accept, _token=token)
            raise RegistryError("the registry needs a login") from exc
        if exc.code in (401, 403):
            raise RegistryError("the registry needs a login") from exc
        if exc.code == 404:
            raise RegistryError("not found in the registry") from exc
        if exc.code == 429:
            raise RegistryError("rate-limited by the registry; will retry later") from exc
        raise RegistryError(f"registry answered HTTP {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise RegistryError(f"couldn't reach the registry: {exc}") from exc


VERSION_RE = re.compile(r"^(v?)(\d+(?:\.\d+)*)(.*)$")


def _version(tag: str):
    m = VERSION_RE.match(tag)
    if not m:
        return None
    nums = tuple(int(x) for x in m.group(2).split("."))
    return m.group(1), len(nums), m.group(3), nums


def newer_tag(current: str, tags: list[str]) -> str | None:
    """The highest tag shaped like `current` (same prefix, number of parts and suffix) above it.

    "1.27.2" -> "1.27.4"; "v16.37.0" -> "v16.38.1"; "8.6-alpine" -> "8.8-alpine". Suffixes like
    "-rc1" or "-beta" are only compared with tags that have the same suffix.
    """
    cur = _version(current)
    if not cur or (cur[1] == 1 and not cur[2] and len(str(cur[3][0])) >= 8):  # date stamps, build numbers
        return None
    best = None
    for t in tags:
        v = _version(t)
        if v and v[:3] == cur[:3] and v[3] > cur[3] and (best is None or v[3] > best[1]):
            best = (t, v[3])
    return best[0] if best else None


def list_tags(registry: str, repo: str, pages: int = 5) -> list[str]:
    tags, path = [], f"{repo}/tags/list?n=1000"
    for _ in range(pages):
        headers, body = registry_request(registry, path)
        tags += (json.loads(body or b"{}").get("tags") or [])
        link = headers.get("Link") or ""
        m = re.search(r"<([^>]+)>", link)
        if not m:
            break
        nxt = m.group(1)
        path = nxt.split("/v2/", 1)[1] if "/v2/" in nxt else nxt.lstrip("/")
    return tags


def check_image(ref: str) -> dict:
    registry, repo, tag = parse_ref(ref)
    headers, _ = registry_request(registry, f"{repo}/manifests/{tag}", method="HEAD", accept=MANIFEST_TYPES)
    digest = headers.get("Docker-Content-Digest") or ""
    newer = None
    if _version(tag):
        try:
            newer = newer_tag(tag, list_tags(registry, repo))
        except RegistryError:
            newer = None
    return {"latest_digest": digest[:80], "newer_tag": (newer or "")[:128]}


def images_in_use(hosts=None) -> dict[str, set[str]]:
    """registry ref key -> set of local digests ("sha256:...") seen for it across hosts."""
    out: dict[str, set[str]] = {}
    for h in hosts if hosts is not None else Host.objects.filter(enabled=True):
        for c in (h.snapshot or {}).get("containers") or []:
            key = ref_key(c.get("image") or "")
            if key:
                out.setdefault(key, set()).update(d.split("@", 1)[1] for d in c.get("image_digests") or [] if "@" in d)
    return out


def run_image_checks(force: bool = False, limit: int = 40) -> int:
    if not settings.SERVCHART_IMAGE_CHECKS:
        return 0
    due = timezone.now() - timedelta(hours=settings.SERVCHART_IMAGE_CHECK_HOURS)
    n = 0
    for key in sorted(images_in_use()):
        obj, _ = ImageCheck.objects.get_or_create(ref=key)
        if not force and obj.checked_at and obj.checked_at > due:
            continue
        try:
            r = check_image(key)
            obj.latest_digest, obj.newer_tag, obj.error = r["latest_digest"], r["newer_tag"], ""
        except RegistryError as exc:
            obj.error = str(exc)[:300]
        except Exception as exc:  # never let one odd registry stop the loop
            log.warning("image check %s failed: %s", key, exc)
            obj.error = "check failed"
        obj.checked_at = timezone.now()
        obj.save()
        n += 1
        if n >= limit:  # spread the work: the rest go on the next round
            break
    ImageCheck.objects.exclude(ref__in=list(images_in_use())).delete()
    return n


def image_status(container: dict, checks: dict[str, ImageCheck]) -> dict | None:
    """For one container: {"state": "update"|"current"|"unknown", "newer_tag", "error"}."""
    key = ref_key(container.get("image") or "")
    c = checks.get(key) if key else None
    if not c or not c.checked_at:
        return None
    local = {d.split("@", 1)[1] for d in container.get("image_digests") or [] if "@" in d}
    if c.error or not c.latest_digest or not local:
        state = "unknown"
    else:
        state = "current" if c.latest_digest in local else "update"
    return {"state": state, "newer_tag": c.newer_tag or None, "error": c.error or None, "checked_at": c.checked_at.isoformat()}
