"""OpenID Connect sign-in (authorization code flow + PKCE), standard library only.

Works with any compliant provider: Authentik, Keycloak, Authelia, Zitadel, Kanidm,
Pocket ID, Google, Microsoft Entra ID, Okta, ...

Configure SERVCHART_OIDC_ISSUER / _CLIENT_ID / _CLIENT_SECRET and register the redirect URI
  <SERVCHART_PUBLIC_URL>/auth/oidc/callback
at the provider. Everything else comes from the issuer's discovery document.

ID token validation: the token is obtained by ServChart itself, server to server, from the
provider's token endpoint over verified HTTPS. OpenID Connect Core 1.0 section 3.1.3.7 allows
TLS server validation to stand in for checking the token's signature in exactly this case,
so no JWT/crypto dependency is needed. We still check issuer, audience, authorized party,
expiry and nonce, and use PKCE + state against code interception and login CSRF. HTTPS is
required for the issuer unless SERVCHART_OIDC_ALLOW_HTTP=1 (local testing only).
"""

import base64
import hashlib
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib.auth import login
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme

from .sso import BACKEND, oidc_enabled, provision_user, split_groups

log = logging.getLogger("servchart.oidc")

_discovery_cache: dict = {}
DISCOVERY_TTL = 3600
CLOCK_SKEW = 120


class OIDCError(Exception):
    """Something went wrong talking to the provider; the message is safe to show."""


# --- HTTP helpers (patched in tests) -------------------------------------------------------


def _check_url(url: str):
    if not url.startswith("https://") and not settings.SERVCHART_OIDC_ALLOW_HTTP:
        raise OIDCError(f"Refusing non-HTTPS provider URL {url!r} (set SERVCHART_OIDC_ALLOW_HTTP=1 only for local testing).")


def http_json(url: str, data: dict | None = None, headers: dict | None = None) -> dict:
    _check_url(url)
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # verifies TLS certificates by default
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode(errors="replace")
        raise OIDCError(f"The identity provider answered HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise OIDCError(f"Couldn't reach the identity provider: {exc}") from exc


def discovery() -> dict:
    issuer = settings.SERVCHART_OIDC_ISSUER
    cached = _discovery_cache.get(issuer)
    if cached and cached[0] > time.time():
        return cached[1]
    doc = http_json(issuer + "/.well-known/openid-configuration")
    for key in ("issuer", "authorization_endpoint", "token_endpoint"):
        if not doc.get(key):
            raise OIDCError(f"The provider's discovery document has no {key!r}.")
    if doc["issuer"].rstrip("/") != issuer:
        raise OIDCError(f"Issuer mismatch: configured {issuer!r}, provider says {doc['issuer']!r}.")
    _discovery_cache[issuer] = (time.time() + DISCOVERY_TTL, doc)
    return doc


# --- small helpers -------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _jwt_payload(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as exc:
        raise OIDCError("The provider returned a malformed ID token.") from exc


def redirect_uri(request) -> str:
    base = settings.SERVCHART_PUBLIC_URL or request.build_absolute_uri("/").rstrip("/")
    return base + "/auth/oidc/callback"


def validate_id_token(claims: dict, issuer: str, nonce: str) -> None:
    client_id = settings.SERVCHART_OIDC_CLIENT_ID
    now = time.time()
    if str(claims.get("iss", "")).rstrip("/") != issuer.rstrip("/"):
        raise OIDCError("ID token was issued by someone else.")
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if client_id not in audiences:
        raise OIDCError("ID token is not meant for this client.")
    if len(audiences) > 1 and claims.get("azp") not in (None, client_id):
        raise OIDCError("ID token's authorized party is another client.")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < now - CLOCK_SKEW:
        raise OIDCError("ID token has expired; try signing in again.")
    if claims.get("nonce") != nonce:
        raise OIDCError("ID token nonce doesn't match this sign-in attempt.")


def _error(request, message, status=400):
    log.warning("OIDC sign-in failed: %s", message)
    return render(request, "registration/sso_error.html", {"message": message}, status=status)


# --- views ---------------------------------------------------------------------------------


def oidc_login(request):
    if not oidc_enabled():
        return HttpResponseBadRequest("OpenID Connect is not configured.")
    try:
        doc = discovery()
    except OIDCError as exc:
        return _error(request, str(exc), status=502)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    nxt = request.GET.get("next", "/")
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        nxt = "/"
    request.session["oidc"] = {"state": state, "nonce": nonce, "verifier": verifier, "next": nxt, "issuer": doc["issuer"]}
    params = {
        "response_type": "code",
        "client_id": settings.SERVCHART_OIDC_CLIENT_ID,
        "redirect_uri": redirect_uri(request),
        "scope": settings.SERVCHART_OIDC_SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
    }
    sep = "&" if "?" in doc["authorization_endpoint"] else "?"
    return HttpResponseRedirect(doc["authorization_endpoint"] + sep + urllib.parse.urlencode(params))


def oidc_callback(request):
    if not oidc_enabled():
        return HttpResponseBadRequest("OpenID Connect is not configured.")
    pending = request.session.pop("oidc", None)
    if request.GET.get("error"):
        return _error(request, f"The identity provider refused the sign-in: {request.GET.get('error_description') or request.GET['error']}")
    if not pending or not secrets.compare_digest(str(request.GET.get("state", "")), pending["state"]):
        return _error(request, "This sign-in link is stale or was not started here. Please start again.")
    code = request.GET.get("code")
    if not code:
        return _error(request, "The identity provider didn't return an authorization code.")

    try:
        doc = discovery()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(request),
            "code_verifier": pending["verifier"],
        }
        headers = {}
        secret = settings.SERVCHART_OIDC_CLIENT_SECRET
        if secret and settings.SERVCHART_OIDC_TOKEN_AUTH == "client_secret_basic":
            pair = f"{urllib.parse.quote(settings.SERVCHART_OIDC_CLIENT_ID, safe='')}:{urllib.parse.quote(secret, safe='')}"
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        else:
            form["client_id"] = settings.SERVCHART_OIDC_CLIENT_ID
            if secret:
                form["client_secret"] = secret
        tokens = http_json(doc["token_endpoint"], data=form, headers=headers)
        if not tokens.get("id_token"):
            raise OIDCError("The identity provider returned no ID token (is the 'openid' scope enabled?).")
        claims = _jwt_payload(tokens["id_token"])
        validate_id_token(claims, pending["issuer"], pending["nonce"])
        if doc.get("userinfo_endpoint") and tokens.get("access_token"):
            try:
                info = http_json(doc["userinfo_endpoint"], headers={"Authorization": f"Bearer {tokens['access_token']}"})
                if info.get("sub") == claims.get("sub"):  # OIDC Core 5.3.2: must match
                    claims = {**info, **claims}
            except OIDCError as exc:
                log.info("userinfo unavailable, using ID token claims only: %s", exc)
    except OIDCError as exc:
        return _error(request, str(exc), status=502)

    username = claims.get(settings.SERVCHART_OIDC_USERNAME_CLAIM) or claims.get("preferred_username") or claims.get("email") or claims.get("sub")
    user = provision_user(
        str(username or ""),
        email=str(claims.get("email") or ""),
        groups=split_groups(claims.get(settings.SERVCHART_OIDC_GROUPS_CLAIM)),
    )
    if user is None:
        return _error(request, "Your account isn't allowed to use ServChart. Ask an admin to add you.", status=403)
    login(request, user, backend=BACKEND)
    request.session["servchart_sso"] = "oidc"
    request.session["oidc_id_token"] = tokens["id_token"]
    return HttpResponseRedirect(pending.get("next") or "/")


def end_session_url(request, id_token: str | None) -> str | None:
    """RP-initiated logout at the provider, if it supports it."""
    try:
        endpoint = discovery().get("end_session_endpoint")
    except OIDCError:
        return None
    if not endpoint:
        return None
    params = {"client_id": settings.SERVCHART_OIDC_CLIENT_ID, "post_logout_redirect_uri": (settings.SERVCHART_PUBLIC_URL or request.build_absolute_uri("/").rstrip("/")) + "/login/"}
    if id_token:
        params["id_token_hint"] = id_token
    sep = "&" if "?" in endpoint else "?"
    return endpoint + sep + urllib.parse.urlencode(params)
