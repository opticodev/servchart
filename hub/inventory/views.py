import logging
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from .audit import audit
from .authentication import AgentPrincipal, HostTokenAuthentication
from .graph import build_graph, host_summary
from .models import Host
from .validation import ReportError, clean_report

log = logging.getLogger(__name__)



def healthz(request):
    return JsonResponse({"ok": True})


@login_required
def spa(request):
    get_token(request)  # make sure the csrftoken cookie is set for the SPA's POST requests
    index = Path(settings.BASE_DIR) / "web_dist" / "index.html"
    if not index.exists():
        return HttpResponse(
            "<h1>ServChart</h1><p>The web UI has not been built. Run <code>npm run build</code> in <code>web/</code>, "
            "or use the Docker image.</p><p>API: <a href='/api/v1/graph'>/api/v1/graph</a></p>",
            content_type="text/html",
        )
    return HttpResponse(index.read_text(), content_type="text/html")


def store_report(host: Host, report: dict) -> None:
    host.snapshot = report
    host.agent_version = report.get("agent_version", "")
    host.last_seen = timezone.now()
    host.save(update_fields=["snapshot", "agent_version", "last_seen"])
    try:
        from .history import record

        record(host, report)
    except Exception:  # history must never make a report fail
        log.exception("could not record history for %s", host.name)


class IsAgent(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.user, AgentPrincipal)


@api_view(["POST"])
@authentication_classes([HostTokenAuthentication])
@permission_classes([IsAgent])
def report(request):
    """Agents POST their snapshot here with `Authorization: Bearer <host token>`."""
    try:
        cleaned = clean_report(request.data)
    except ReportError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    # where the report came from: lets other hosts' connections to this address resolve to it
    cleaned["seen_from"] = request.META.get("REMOTE_ADDR")
    store_report(request.auth, cleaned)
    from .addresses import public_ips

    return Response(
        {
            "ok": True,
            "host": request.auth.name,
            "containers": len(cleaned["containers"]),
            # your public addresses: the agent reports connections to these even though they're public
            "observe_ips": sorted(public_ips()),
        }
    )


@api_view(["GET"])
def graph(request):
    return Response(build_graph())


def _install_command(request, token: str) -> str:
    hub = settings.SERVCHART_PUBLIC_URL or request.build_absolute_uri("/").rstrip("/")
    return (
        "docker run -d --name servchart-agent --restart unless-stopped --pid host \\\n"
        "  -v /var/run/docker.sock:/var/run/docker.sock:ro \\\n"
        "  -v /:/host:ro,rslave -e SERVCHART_HOST_ROOT=/host \\\n"
        "  -e SERVCHART_OBSERVE_CONNECTIONS=1 \\\n"
        f"  -e SERVCHART_HUB={hub} \\\n"
        f"  -e SERVCHART_TOKEN={token} \\\n"
        f"  {settings.SERVCHART_AGENT_IMAGE}"
    )


@api_view(["GET", "POST"])
def hosts(request):
    if request.method == "GET":
        return Response([host_summary(h) for h in Host.objects.all()])
    if not request.user.is_staff:
        return Response({"error": "Only admins can add hosts."}, status=status.HTTP_403_FORBIDDEN)
    name = str(request.data.get("name", "")).strip()
    if not name or len(name) > 128:
        return Response({"error": "A name (1-128 characters) is required."}, status=status.HTTP_400_BAD_REQUEST)
    if Host.objects.filter(name=name).exists():
        return Response({"error": f"A host named {name!r} already exists."}, status=status.HTTP_400_BAD_REQUEST)
    host, token = Host.create_with_token(name)
    audit(request, "host.create", host.name)
    return Response(
        {**host_summary(host), "token": token, "install_command": _install_command(request, token)},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
def rotate_token(request, pk: int):
    if not request.user.is_staff:
        return Response({"error": "Only admins can rotate tokens."}, status=status.HTTP_403_FORBIDDEN)
    try:
        host = Host.objects.get(pk=pk, is_local=False)
    except Host.DoesNotExist:
        return Response({"error": "No such agent host."}, status=status.HTTP_404_NOT_FOUND)
    token = host.rotate_token()
    audit(request, "host.rotate_token", host.name)
    return Response({"token": token, "install_command": _install_command(request, token)})


@api_view(["GET"])
def me(request):
    from .settings_api import me_payload

    return Response(me_payload(request))
