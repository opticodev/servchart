from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path

from inventory import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("healthz", views.healthz, name="healthz"),
    path("api/v1/", include("inventory.urls")),
    # Everything else is the React single-page app.
    re_path(r"^(?!static/|api/|admin/).*$", views.spa, name="spa"),
]
