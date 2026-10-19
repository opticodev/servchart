"""Container logs, relayed from the host's agent to an admin's browser.

Flow: admin asks (POST .../logs) -> a LogRequest waits for the agent -> the agent picks
it up (GET /api/v1/agent/commands, every few seconds) -> posts the lines back -> the
browser collects them (GET /api/v1/logs/<id>) and the request is deleted right away.
Nothing is kept: unread requests are purged after a few minutes. Every request is
recorded in the activity log. The hub's own host is read directly, without an agent.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from .audit import audit
from .authentication import HostTokenAuthentication
from .models import Host, LogRequest
from .views import IsAgent

AGENT_TIMEOUT = timedelta(seconds=30)  # no answer by then -> tell the admin why
KEEP_FOR = timedelta(minutes=5)
MAX_LINES = 2000


def _purge():
    LogRequest.objects.filter(created_at__lt=timezone.now() - KEEP_FOR).delete()


def _clean_result(result) -> dict:
    """The agent's answer, re-checked: a list of {t, s, m} strings, capped."""
    if not isinstance(result, dict):
        return {"lines": [], "truncated": False}
    lines = []
    for item in result.get("lines") or []:
        if isinstance(item, dict):
            lines.append({"t": str(item.get("t") or "")[:40], "s": "err" if item.get("s") == "err" else "out", "m": str(item.get("m") or "")[:4000]})
        if len(lines) >= MAX_LINES:
            break
    return {"lines": lines, "truncated": bool(result.get("truncated")), "redacted": bool(result.get("redacted"))}


def _container_exists(host: Host, name: str) -> bool:
    return any(c.get("name") == name for c in (host.snapshot or {}).get("containers") or [])


@api_view(["POST"])
def request_logs(request, pk: int):
    if not request.user.is_staff:
        return Response({"error": "Only admins can view logs."}, status=status.HTTP_403_FORBIDDEN)
    host = Host.objects.filter(pk=pk, enabled=True).first()
    if host is None:
        return Response({"error": "No such host."}, status=status.HTTP_404_NOT_FOUND)
    container = str(request.data.get("container") or "")
    if not _container_exists(host, container):
        return Response({"error": f"{container!r} isn't a container on {host.name}."}, status=status.HTTP_404_NOT_FOUND)
    if ((host.snapshot or {}).get("host") or {}).get("logs") != "on":
        return Response(
            {"error": f"Log viewing is off on {host.name}. Start its agent with SERVCHART_ALLOW_LOGS=1 to allow it."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        tail = max(1, min(int(request.data.get("tail") or 200), MAX_LINES))
        since = int(request.data["since"]) if request.data.get("since") else None
    except (TypeError, ValueError):
        return Response({"error": "tail and since must be numbers."}, status=status.HTTP_400_BAD_REQUEST)

    if not since:  # follow-mode refreshes aren't logged one by one
        audit(request, "logs.view", f"{host.name}/{container}", tail=tail)
    _purge()

    if host.is_local:  # the hub's own host: read through the mounted Docker socket
        from servchart_agent.docker_api import DockerClient, DockerError
        from servchart_agent.logs import fetch

        try:
            return Response({"id": None, "status": "done", **_clean_result(fetch(DockerClient(), container, tail=tail, since=since))})
        except DockerError as exc:
            return Response({"id": None, "status": "error", "error": str(exc)})

    req = LogRequest.objects.create(host=host, container=container, tail=tail, since=since, requested_by=request.user)
    return Response({"id": str(req.id), "status": "pending"}, status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
def log_result(request, req_id):
    if not request.user.is_staff:
        return Response({"error": "Only admins can view logs."}, status=status.HTTP_403_FORBIDDEN)
    req = LogRequest.objects.filter(pk=req_id, requested_by=request.user).select_related("host").first()
    if req is None:
        return Response({"error": "This log request has expired."}, status=status.HTTP_404_NOT_FOUND)
    if req.status == "done":
        body = {"id": str(req.id), "status": "done", **_clean_result(req.result)}
        req.delete()  # read once, then gone
        return Response(body)
    if req.status == "error" or timezone.now() - req.created_at > AGENT_TIMEOUT:
        error = req.error or (
            f"The agent on {req.host.name} didn't answer. It needs version 0.3+ and SERVCHART_ALLOW_LOGS=1, "
            "and must be able to reach the hub."
        )
        req.delete()
        return Response({"id": str(req.id), "status": "error", "error": error})
    return Response({"id": str(req.id), "status": req.status})


# --- agent side ---------------------------------------------------------------------------


@api_view(["GET"])
@authentication_classes([HostTokenAuthentication])
@permission_classes([IsAgent])
def agent_commands(request):
    host = request.auth
    _purge()
    pending = list(LogRequest.objects.filter(host=host, status="pending").order_by("created_at")[:10])
    LogRequest.objects.filter(pk__in=[r.pk for r in pending]).update(status="sent")
    return Response(
        {"commands": [{"id": str(r.id), "type": "logs", "container": r.container, "tail": r.tail, "since": r.since} for r in pending]}
    )


@api_view(["POST"])
@authentication_classes([HostTokenAuthentication])
@permission_classes([IsAgent])
def agent_command_result(request, req_id):
    req = LogRequest.objects.filter(pk=req_id, host=request.auth, status__in=["pending", "sent"]).first()
    if req is None:  # unknown, already answered, or another host's request
        return Response({"error": "No such request."}, status=status.HTTP_404_NOT_FOUND)
    if request.data.get("ok"):
        req.result, req.status = _clean_result(request.data.get("result")), "done"
    else:
        req.error, req.status = str(request.data.get("error") or "The agent couldn't read the logs.")[:500], "error"
    req.save(update_fields=["result", "status", "error"])
    return Response({"ok": True})
