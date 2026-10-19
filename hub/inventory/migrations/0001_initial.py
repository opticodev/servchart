from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Host",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="Display name on the map.", max_length=128, unique=True)),
                ("token_hash", models.CharField(editable=False, max_length=64, unique=True)),
                ("token_hint", models.CharField(editable=False, help_text="First characters of the token.", max_length=12)),
                ("is_local", models.BooleanField(default=False, help_text="Collected by the hub itself.")),
                ("enabled", models.BooleanField(default=True, help_text="Disabled hosts' tokens are rejected.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen", models.DateTimeField(blank=True, null=True)),
                ("agent_version", models.CharField(blank=True, max_length=32)),
                ("snapshot", models.JSONField(blank=True, default=dict, help_text="Latest sanitized report from the agent.")),
            ],
            options={"ordering": ["name"]},
        ),
    ]
