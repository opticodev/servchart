import hashlib
import secrets

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
