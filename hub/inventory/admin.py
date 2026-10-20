from django.contrib import admin

from .models import AuditEvent, Host


@admin.register(Host)
class HostAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "is_local", "enabled", "agent_version", "last_seen", "token_hint")
    list_filter = ("enabled", "is_local")
    search_fields = ("name",)
    readonly_fields = ("is_local", "token_hint", "created_at", "last_seen", "agent_version", "snapshot")
    fields = ("name", "enabled", "is_local", "token_hint", "agent_version", "created_at", "last_seen", "snapshot")

    def has_add_permission(self, request):
        # Hosts are added from the map ("Add host") or `manage.py create_host`, which show the token once.
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "username", "action", "target", "ip")
    list_filter = ("action",)
    search_fields = ("username", "target")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
