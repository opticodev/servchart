import os
import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the first admin user if no user exists (SERVCHART_ADMIN_USER / SERVCHART_ADMIN_PASSWORD)."

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.exists():
            return
        username = os.environ.get("SERVCHART_ADMIN_USER", "admin")
        password = os.environ.get("SERVCHART_ADMIN_PASSWORD")
        generated = not password
        if generated:
            password = secrets.token_urlsafe(16)
        User.objects.create_superuser(username=username, email="", password=password)
        if generated:
            bar = "=" * 64
            self.stdout.write(
                f"\n{bar}\n ServChart admin created\n   user:     {username}\n   password: {password}\n"
                f" Change it after first login (top-right menu -> Admin).\n{bar}\n"
            )
        else:
            self.stdout.write(f"ServChart admin '{username}' created from SERVCHART_ADMIN_PASSWORD.")
