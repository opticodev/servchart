"""ServChart hub settings. Everything a user may want to change is an environment variable."""

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SERVCHART_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _env_bool(name, default=False):
    return os.environ.get(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


def _env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


def _secret_key():
    """Use SERVCHART_SECRET_KEY, else generate one once and persist it in the data dir."""
    if os.environ.get("SERVCHART_SECRET_KEY"):
        return os.environ["SERVCHART_SECRET_KEY"]
    path = DATA_DIR / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(50))
        path.chmod(0o600)
    return path.read_text().strip()


SECRET_KEY = _secret_key()
DEBUG = _env_bool("SERVCHART_DEBUG")
ALLOWED_HOSTS = _env_list("SERVCHART_ALLOWED_HOSTS", "*")
CSRF_TRUSTED_ORIGINS = _env_list("SERVCHART_CSRF_TRUSTED_ORIGINS")
# Public URL agents should use; shown in the "Add host" command. Falls back to the request URL.
SERVCHART_PUBLIC_URL = os.environ.get("SERVCHART_PUBLIC_URL", "").rstrip("/")
# Agent image used in the generated install command.
SERVCHART_AGENT_IMAGE = os.environ.get("SERVCHART_AGENT_IMAGE", "opticodev/servchart-agent:latest")
# Hosts that haven't reported for this many seconds are shown as stale.
SERVCHART_STALE_AFTER = int(os.environ.get("SERVCHART_STALE_AFTER", "300"))
# Largest accepted agent report (bytes).
SERVCHART_MAX_REPORT_BYTES = int(os.environ.get("SERVCHART_MAX_REPORT_BYTES", str(5 * 1024 * 1024)))
DATA_UPLOAD_MAX_MEMORY_SIZE = SERVCHART_MAX_REPORT_BYTES

# --- Single sign-on ----------------------------------------------------------------------
# Two provider-neutral modes; both can be on at once, and local passwords keep working
# unless SERVCHART_PASSWORD_LOGIN=0. See README "Single sign-on" for provider recipes.

# 1) OpenID Connect: any standards-compliant provider (Authentik, Keycloak, Authelia, Zitadel,
#    Kanidm, Pocket ID, Google, Microsoft Entra ID, Okta, ...). Enabled when issuer + client id are set.
SERVCHART_OIDC_ISSUER = os.environ.get("SERVCHART_OIDC_ISSUER", "").strip().rstrip("/")
SERVCHART_OIDC_CLIENT_ID = os.environ.get("SERVCHART_OIDC_CLIENT_ID", "").strip()
SERVCHART_OIDC_CLIENT_SECRET = os.environ.get("SERVCHART_OIDC_CLIENT_SECRET", "").strip()  # empty = public client (PKCE only)
SERVCHART_OIDC_SCOPES = os.environ.get("SERVCHART_OIDC_SCOPES", "openid profile email").strip()
SERVCHART_OIDC_USERNAME_CLAIM = os.environ.get("SERVCHART_OIDC_USERNAME_CLAIM", "preferred_username").strip()
SERVCHART_OIDC_GROUPS_CLAIM = os.environ.get("SERVCHART_OIDC_GROUPS_CLAIM", "groups").strip()
SERVCHART_OIDC_PROVIDER_NAME = os.environ.get("SERVCHART_OIDC_PROVIDER_NAME", "single sign-on").strip()  # button: "Sign in with ..."
SERVCHART_OIDC_TOKEN_AUTH = os.environ.get("SERVCHART_OIDC_TOKEN_AUTH", "client_secret_basic").strip()  # or client_secret_post
SERVCHART_OIDC_ALLOW_HTTP = _env_bool("SERVCHART_OIDC_ALLOW_HTTP")  # only for local testing: the security model relies on TLS

# 2) Trusted proxy headers (forward auth): Authentik, Authelia, oauth2-proxy, Tailscale serve, ...
#    Enabled when a header AND trusted proxy addresses are set. The header is trusted ONLY on
#    requests coming straight from SERVCHART_SSO_TRUSTED_PROXIES.
SERVCHART_SSO_HEADER = os.environ.get("SERVCHART_SSO_HEADER", "").strip()  # username header
SERVCHART_SSO_TRUSTED_PROXIES = _env_list("SERVCHART_SSO_TRUSTED_PROXIES")  # IPs or CIDRs
SERVCHART_SSO_EMAIL_HEADER = os.environ.get("SERVCHART_SSO_EMAIL_HEADER", "").strip()
SERVCHART_SSO_GROUPS_HEADER = os.environ.get("SERVCHART_SSO_GROUPS_HEADER", "").strip()

# Shared by both modes
SERVCHART_SSO_ADMIN_GROUPS = _env_list("SERVCHART_SSO_ADMIN_GROUPS")  # members become ServChart admins
SERVCHART_SSO_CREATE_USERS = _env_bool("SERVCHART_SSO_CREATE_USERS", True)
SERVCHART_SSO_LOGOUT_URL = os.environ.get("SERVCHART_SSO_LOGOUT_URL", "").strip()  # where "Sign out" ends up (header mode)
SERVCHART_PASSWORD_LOGIN = _env_bool("SERVCHART_PASSWORD_LOGIN", True)  # False hides the password form (/login/?local=1 still shows it)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "inventory",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "inventory.sso.TrustedHeaderSSOMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "servchart.urls"
WSGI_APPLICATION = "servchart.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "inventory.branding.context",
            ],
        },
    },
]

if os.environ.get("SERVCHART_DB", "sqlite") == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": os.environ.get("POSTGRES_HOST", "db"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "NAME": os.environ.get("POSTGRES_DB", "servchart"),
            "USER": os.environ.get("POSTGRES_USER", "servchart"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "servchart.sqlite3",
            "OPTIONS": {"timeout": 20},
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TZ", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [p for p in [BASE_DIR / "web_dist"] if p.exists()]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if DEBUG:
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}

# Email (reports). Nothing is sent unless SERVCHART_SMTP_HOST is set.
EMAIL_HOST = os.environ.get("SERVCHART_SMTP_HOST", "").strip()
EMAIL_PORT = int(os.environ.get("SERVCHART_SMTP_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("SERVCHART_SMTP_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("SERVCHART_SMTP_PASSWORD", "")
EMAIL_USE_SSL = _env_bool("SERVCHART_SMTP_SSL")  # implicit TLS, usually port 465
EMAIL_USE_TLS = _env_bool("SERVCHART_SMTP_STARTTLS", not EMAIL_USE_SSL)  # STARTTLS, usually port 587
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = os.environ.get("SERVCHART_SMTP_FROM", "") or (EMAIL_HOST_USER if "@" in EMAIL_HOST_USER else "servchart@localhost")
SERVCHART_REPORT_HOUR = max(0, min(int(os.environ.get("SERVCHART_REPORT_HOUR", "7")), 23))  # local time (TIME_ZONE)

# History and checks (v0.4)
SERVCHART_SAMPLE_MINUTES = max(1, int(os.environ.get("SERVCHART_SAMPLE_MINUTES", "5")))
SERVCHART_HISTORY_DAYS = max(1, int(os.environ.get("SERVCHART_HISTORY_DAYS", "7")))
SERVCHART_IMAGE_CHECKS = _env_bool("SERVCHART_IMAGE_CHECKS", True)  # ask registries whether image tags moved
SERVCHART_IMAGE_CHECK_HOURS = max(1, int(os.environ.get("SERVCHART_IMAGE_CHECK_HOURS", "12")))
SERVCHART_CERT_CHECK_HOURS = max(1, int(os.environ.get("SERVCHART_CERT_CHECK_HOURS", "6")))
SERVCHART_DISK_WARN = int(os.environ.get("SERVCHART_DISK_WARN", "85"))  # percent
SERVCHART_DISK_CRITICAL = int(os.environ.get("SERVCHART_DISK_CRITICAL", "95"))
SERVCHART_CERT_WARN_DAYS = int(os.environ.get("SERVCHART_CERT_WARN_DAYS", "14"))

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = _env_bool("SERVCHART_SECURE_COOKIES")
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if _env_bool("SERVCHART_BEHIND_PROXY") else None

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": None,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("SERVCHART_LOG_LEVEL", "INFO")},
}
