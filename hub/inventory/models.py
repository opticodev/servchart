import hashlib
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

TOKEN_PREFIX = "sc_"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Host(models.Model):
    """One machine running Docker, reporting through an agent (or the hub's local collector)."""

    name = models.CharField(max_length=128, unique=True, help_text="Display name on the map.")
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    token_hint = models.CharField(max_length=12, editable=False, help_text="First characters of the token.")
    is_local = models.BooleanField(default=False, help_text="Collected by the hub itself.")
    enabled = models.BooleanField(default=True, help_text="Disabled hosts' tokens are rejected.")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    agent_version = models.CharField(max_length=32, blank=True)
    snapshot = models.JSONField(default=dict, blank=True, help_text="Latest sanitized report from the agent.")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @classmethod
    def create_with_token(cls, name: str, **kwargs):
        """Create a host and return (host, plaintext_token). The token is shown once and never stored."""
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        host = cls.objects.create(name=name, token_hash=hash_token(token), token_hint=token[:8], **kwargs)
        return host, token

    def rotate_token(self) -> str:
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        self.token_hash = hash_token(token)
        self.token_hint = token[:8]
        self.save(update_fields=["token_hash", "token_hint"])
        return token

    @property
    def status(self) -> str:
        if not self.last_seen:
            return "pending"
        age = (timezone.now() - self.last_seen).total_seconds()
        return "online" if age <= settings.SERVCHART_STALE_AFTER else "stale"


class SiteSettings(models.Model):
    """One row (pk=1): branding and the report schedule, editable in Settings."""

    app_name = models.CharField(max_length=60, default="ServChart")
    accent_color = models.CharField(max_length=7, blank=True, default="", help_text="#rrggbb; empty = default blue")
    logo = models.BinaryField(null=True, blank=True)
    logo_type = models.CharField(max_length=40, blank=True, default="")
    favicon = models.BinaryField(null=True, blank=True)
    favicon_type = models.CharField(max_length=40, blank=True, default="")
    report_schedule = models.CharField(max_length=10, default="off", help_text="off, daily, weekly or monthly")
    report_recipients = models.TextField(blank=True, default="", help_text="Comma-separated email addresses")
    report_last_sent = models.DateTimeField(null=True, blank=True)
    public_addresses = models.TextField(blank=True, default="", help_text="Your public IPs or DDNS names, one per line")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "site settings"
        verbose_name_plural = "site settings"

    def __str__(self):
        return "Site settings"

    @classmethod
    def load(cls) -> "SiteSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class LogRequest(models.Model):
    """An admin asked to see a container's logs; relayed to the host's agent.

    Short-lived by design: the result is deleted as soon as the requester has read it,
    and anything older than a few minutes is purged.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host = models.ForeignKey(Host, on_delete=models.CASCADE, related_name="log_requests")
    container = models.CharField(max_length=255)
    tail = models.PositiveIntegerField(default=200)
    since = models.BigIntegerField(null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=10, default="pending")  # pending, sent, done, error
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)


class AuditEvent(models.Model):
    """Who did what: log views, user/host changes, branding and report settings."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    username = models.CharField(max_length=150, blank=True, default="")
    action = models.CharField(max_length=60)
    target = models.CharField(max_length=255, blank=True, default="")
    detail = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.username} {self.action} {self.target}"


class Sample(models.Model):
    """A few numbers per host every few minutes, for small history graphs and "what changed"."""

    host = models.ForeignKey(Host, on_delete=models.CASCADE, related_name="samples")
    created_at = models.DateTimeField(db_index=True)
    data = models.JSONField(default=dict)

    class Meta:
        ordering = ["created_at"]


class CertCheck(models.Model):
    """A TLS endpoint whose certificate expiry the hub watches (Settings -> Checks)."""

    hostname = models.CharField(max_length=253)
    port = models.PositiveIntegerField(default=443)
    created_at = models.DateTimeField(auto_now_add=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    issuer = models.CharField(max_length=255, blank=True, default="")
    error = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["hostname", "port"]
        constraints = [models.UniqueConstraint(fields=["hostname", "port"], name="unique_cert_endpoint")]

    def __str__(self):
        return f"{self.hostname}:{self.port}"


class ImageCheck(models.Model):
    """Registry lookup for one image reference (repo:tag): has the tag moved, is there a newer version."""

    ref = models.CharField(max_length=255, unique=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    latest_digest = models.CharField(max_length=80, blank=True, default="")
    newer_tag = models.CharField(max_length=128, blank=True, default="")
    error = models.CharField(max_length=300, blank=True, default="")

    def __str__(self):
        return self.ref
