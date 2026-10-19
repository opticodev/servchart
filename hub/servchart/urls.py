from django.contrib import admin
from django.urls import include, path, re_path

from inventory import auth_views, branding, oidc, reports_api, views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.logout_view, name="logout"),
    path("auth/oidc/login", oidc.oidc_login, name="oidc-login"),
    path("auth/oidc/callback", oidc.oidc_callback, name="oidc-callback"),
    path("healthz", views.healthz, name="healthz"),
    path("branding/<str:kind>", branding.serve_image, name="branding-serve"),
    path("report/", reports_api.report_page, name="report-page"),
    path("api/v1/", include("inventory.urls")),
    # Everything else is the React single-page app.
    re_path(r"^(?!static/|api/|admin/|auth/|branding/|report/).*$", views.spa, name="spa"),
]
