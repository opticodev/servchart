from django.urls import path

from . import branding, logs_api, reports_api, settings_api, views

urlpatterns = [
    path("report", views.report, name="agent-report"),
    path("agent/commands", logs_api.agent_commands, name="agent-commands"),
    path("agent/commands/<uuid:req_id>/result", logs_api.agent_command_result, name="agent-command-result"),
    path("graph", views.graph, name="graph"),
    path("hosts", views.hosts, name="hosts"),
    path("hosts/<int:pk>/rotate-token", views.rotate_token, name="rotate-token"),
    path("hosts/<int:pk>/logs", logs_api.request_logs, name="host-logs"),
    path("hosts/<int:pk>", settings_api.host_detail, name="host-detail"),
    path("logs/<uuid:req_id>", logs_api.log_result, name="log-result"),
    path("users", settings_api.users, name="users"),
    path("users/<int:pk>", settings_api.user_detail, name="user-detail"),
    path("users/<int:pk>/reset-password", settings_api.user_reset_password, name="user-reset-password"),
    path("me", views.me, name="me"),
    path("me/password", settings_api.my_password, name="my-password"),
    path("branding", branding.branding, name="branding"),
    path("branding/<str:kind>", branding.branding_image, name="branding-image"),
    path("report.json", reports_api.report_json, name="report-json"),
    path("report/<str:kind>.csv", reports_api.report_csv, name="report-csv"),
    path("report/send", reports_api.report_send, name="report-send"),
    path("report/schedule", reports_api.report_schedule, name="report-schedule"),
    path("audit", reports_api.audit_list, name="audit"),
]
