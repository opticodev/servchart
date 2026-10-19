from rest_framework import authentication, exceptions

from .models import Host, hash_token


class AgentPrincipal:
    """Stands in for request.user on agent requests. Agents are never Django users."""

    is_authenticated = True
    is_staff = False

    def __init__(self, host: Host):
        self.host = host


class HostTokenAuthentication(authentication.BaseAuthentication):
    """`Authorization: Bearer sc_...` -> the Host that owns the token."""

    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode(errors="ignore")
        if not header.startswith(self.keyword + " "):
            return None
        token = header[len(self.keyword) + 1 :].strip()
        try:
            host = Host.objects.get(token_hash=hash_token(token))
        except Host.DoesNotExist:
            raise exceptions.AuthenticationFailed("Unknown host token.")
        if not host.enabled:
            raise exceptions.AuthenticationFailed("Host is disabled.")
        return AgentPrincipal(host), host

    def authenticate_header(self, request):
        return self.keyword
