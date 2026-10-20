import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0003_fix_is_local")]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="public_addresses",
            field=models.TextField(blank=True, default="", help_text="Your public IPs or DDNS names, one per line"),
        ),
        migrations.CreateModel(
            name="Sample",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(db_index=True)),
                ("data", models.JSONField(default=dict)),
                ("host", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="samples", to="inventory.host")),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="CertCheck",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("hostname", models.CharField(max_length=253)),
                ("port", models.PositiveIntegerField(default=443)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("checked_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("issuer", models.CharField(blank=True, default="", max_length=255)),
                ("error", models.CharField(blank=True, default="", max_length=500)),
            ],
            options={
                "ordering": ["hostname", "port"],
                "constraints": [models.UniqueConstraint(fields=("hostname", "port"), name="unique_cert_endpoint")],
            },
        ),
        migrations.CreateModel(
            name="ImageCheck",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ref", models.CharField(max_length=255, unique=True)),
                ("checked_at", models.DateTimeField(blank=True, null=True)),
                ("latest_digest", models.CharField(blank=True, default="", max_length=80)),
                ("newer_tag", models.CharField(blank=True, default="", max_length=128)),
                ("error", models.CharField(blank=True, default="", max_length=300)),
            ],
        ),
    ]
