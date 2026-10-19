from django.urls import path

from . import views

urlpatterns = [
    path("report", views.report, name="agent-report"),
    path("graph", views.graph, name="graph"),
    path("hosts", views.hosts, name="hosts"),
    path("hosts/<int:pk>/rotate-token", views.rotate_token, name="rotate-token"),
    path("me", views.me, name="me"),
]
