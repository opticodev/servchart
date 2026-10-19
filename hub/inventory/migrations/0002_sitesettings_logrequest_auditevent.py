import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SiteSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("app_name", models.CharField(default="ServChart", max_length=60)),
                ("accent_color", models.CharField(blank=True, default="", help_text="#rrggbb; empty = default blue", max_length=7)),
                ("logo", models.BinaryField(blank=True, null=True)),
                ("logo_type", models.CharField(blank=True, default="", max_length=40)),
                ("favicon", models.BinaryField(blank=True, null=True)),
                ("favicon_type", models.CharField(blank=True, default="", max_length=40)),
                ("report_schedule", models.CharField(default="off", help_text="off, daily, weekly or monthly", max_length=10)),
                ("report_recipients", models.TextField(blank=True, default="", help_text="Comma-separated email addresses")),
                ("report_last_sent", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "site settings", "verbose_name_plural": "site settings"},
        ),
        migrations.CreateModel(
            name="LogRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("container", models.CharField(max_length=255)),
                ("tail", models.PositiveIntegerField(default=200)),
                ("since", models.BigIntegerField(blank=True, null=True)),
                ("status", models.CharField(default="pending", max_length=10)),
                ("result", models.JSONField(blank=True, null=True)),
                ("error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("host", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="log_requests", to="inventory.host")),
                ("requested_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("username", models.CharField(blank=True, default="", max_length=150)),
                ("action", models.CharField(max_length=60)),
                ("target", models.CharField(blank=True, default="", max_length=255)),
                ("detail", models.JSONField(blank=True, default=dict)),
                ("ip", models.GenericIPAddressField(blank=True, null=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
