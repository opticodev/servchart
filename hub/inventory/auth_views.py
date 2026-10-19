from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth import views as auth_views
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_POST

from .sso import oidc_enabled


class LoginView(auth_views.LoginView):
    """The password form, plus a "Sign in with ..." button when OpenID Connect is configured."""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["oidc_enabled"] = oidc_enabled()
        ctx["oidc_name"] = settings.SERVCHART_OIDC_PROVIDER_NAME
        ctx["show_password_form"] = settings.SERVCHART_PASSWORD_LOGIN or self.request.GET.get("local") == "1" or not oidc_enabled()
        return ctx


@require_POST
def logout_view(request):
    """Sign out of ServChart, then of the identity provider when we know how."""
    mode = request.session.get("servchart_sso")
    id_token = request.session.get("oidc_id_token")
    logout(request)
    target = None
    if mode == "oidc" and oidc_enabled():
        from .oidc import end_session_url

        target = end_session_url(request, id_token)
    elif mode == "header" and settings.SERVCHART_SSO_LOGOUT_URL:
        target = settings.SERVCHART_SSO_LOGOUT_URL
    return HttpResponseRedirect(target or settings.LOGOUT_REDIRECT_URL)
