"""Activity log: who did what and when (Settings -> Activity)."""

import logging

from .models import AuditEvent

log = logging.getLogger("servchart.audit")


def audit(request, action: str, target: str = "", **detail) -> None:
    user = getattr(request, "user", None)
    authed = bool(user and getattr(user, "is_authenticated", False) and hasattr(user, "get_username"))
    try:
        AuditEvent.objects.create(
            user=user if authed else None,
            username=user.get_username() if authed else "",
            action=action[:60],
            target=str(target)[:255],
            detail=detail,
            ip=request.META.get("REMOTE_ADDR") or None,
        )
    except Exception:  # auditing must never break the action itself
        log.exception("could not record audit event %s", action)
