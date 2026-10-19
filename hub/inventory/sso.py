"""Single sign-on: shared account handling + the trusted-header mode.

ServChart supports two provider-neutral ways to sign people in (see README "Single sign-on"):

  * OpenID Connect (inventory/oidc.py) - a "Sign in with ..." button; works with any
    compliant provider.
  * Trusted proxy headers (this module) - for setups where a forward-auth proxy
    (Authentik, Authelia, oauth2-proxy, Tailscale serve, ...) authenticates every request and
    passes the username in a header.

Both end in provision_user(), so account creation and admin-group mapping behave the same.

Header-mode security model:
  * The header is ignored unless REMOTE_ADDR (the TCP peer, not X-Forwarded-For) is one of
    SERVCHART_SSO_TRUSTED_PROXIES - a client talking to the hub directly can't impersonate anyone.
  * It is never used on the agent / health / static endpoints, which usually skip the
    proxy's authentication, so a client-supplied header could reach us there.
  * SSO accounts get no usable password and can't use the login form.
"""

import ipaddress
import logging

from django.conf import settings
from django.contrib.auth import get_user_model, login, logout

log = logging.getLogger("servchart.sso")

# Paths that typically bypass the proxy's authentication - never trust identity headers there.
UNPROTECTED_PATHS = ("/healthz", "/static/", "/auth/oidc/", "/api/v1/agent/")
AGENT_REPORT_PATH = "/api/v1/report"  # exact: /api/v1/report.json etc. are user endpoints


def unprotected(path: str) -> bool:
    return path == AGENT_REPORT_PATH or path.startswith(UNPROTECTED_PATHS)
BACKEND = "django.contrib.auth.backends.ModelBackend"


# --- what's enabled ------------------------------------------------------------------------


def header_sso_enabled() -> bool:
    return bool(settings.SERVCHART_SSO_HEADER and settings.SERVCHART_SSO_TRUSTED_PROXIES)


def oidc_enabled() -> bool:
    return bool(settings.SERVCHART_OIDC_ISSUER and settings.SERVCHART_OIDC_CLIENT_ID)


def sso_enabled() -> bool:
    return header_sso_enabled() or oidc_enabled()


# --- shared account handling ---------------------------------------------------------------


def split_groups(raw) -> set[str]:
    """Groups from a header ("a|b", "a,b") or a claim (list or string)."""
    if not raw:
        return set()
    if isinstance(raw, (list, tuple, set)):
        return {str(g).strip() for g in raw if str(g).strip()}
    return {g.strip() for part in str(raw).split("|") for g in part.split(",") if g.strip()}


def provision_user(username: str, email: str = "", groups: set[str] | None = None):
    """Find or create the account for an identity the provider vouched for; None if not allowed.

    Admin rights follow SERVCHART_SSO_ADMIN_GROUPS for accounts that exist only through SSO,
    so removing someone from the group at the provider removes their ServChart admin rights.
    Local accounts (with a password) keep the role given in ServChart.
    """
    User = get_user_model()
    username = (username or "").strip()[:150]
    if not username:
        return None
    user = User.objects.filter(username=username).first()
    if user is None:
        if not settings.SERVCHART_SSO_CREATE_USERS:
            log.info("SSO user %r has no ServChart account and auto-creation is off", username)
            return None
        user = User(username=username)
        user.set_unusable_password()
        user.save()
        log.info("created SSO user %r", username)
    if not user.is_active:
        return None
    changed = []
    if email and user.email != email:
        user.email = email
        changed.append("email")
    if settings.SERVCHART_SSO_ADMIN_GROUPS and not user.has_usable_password():
        is_admin = bool((groups or set()) & set(settings.SERVCHART_SSO_ADMIN_GROUPS))
        if user.is_staff != is_admin or user.is_superuser != is_admin:
            user.is_staff = user.is_superuser = is_admin
            changed += ["is_staff", "is_superuser"]
    if changed:
        user.save(update_fields=changed)
    return user


# --- trusted-header mode -------------------------------------------------------------------


def _meta_key(header: str) -> str:
    return "HTTP_" + header.upper().replace("-", "_")


def _trusted_networks():
    nets = []
    for item in settings.SERVCHART_SSO_TRUSTED_PROXIES:
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            log.warning("ignoring invalid SERVCHART_SSO_TRUSTED_PROXIES entry %r", item)
    return nets


def from_trusted_proxy(request) -> bool:
    try:
        peer = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
    except ValueError:
        return False
    return any(peer in net for net in _trusted_networks() if net.version == peer.version)


def _header(request, name: str) -> str:
    return request.META.get(_meta_key(name), "").strip() if name else ""


class TrustedHeaderSSOMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if header_sso_enabled() and not unprotected(request.path):
            self.process(request)
        return self.get_response(request)

    def process(self, request):
        username = _header(request, settings.SERVCHART_SSO_HEADER)
        if not username or not from_trusted_proxy(request):
            return
        if request.user.is_authenticated and request.user.get_username() != username:
            logout(request)  # someone else is now signed in at the proxy
        user = provision_user(
            username,
            email=_header(request, settings.SERVCHART_SSO_EMAIL_HEADER),
            groups=split_groups(_header(request, settings.SERVCHART_SSO_GROUPS_HEADER)),
        )
        if user is None:
            if request.user.is_authenticated:
                logout(request)
            return
        if not request.user.is_authenticated:
            login(request, user, backend=BACKEND)
            request.session["servchart_sso"] = "header"
        else:
            request.user = user
