from django.core.management.base import BaseCommand, CommandError

from inventory.models import Host


class Command(BaseCommand):
    help = "Register a host and print its agent token (shown once)."

    def add_arguments(self, parser):
        parser.add_argument("name")

    def handle(self, *args, name, **options):
        if Host.objects.filter(name=name).exists():
            raise CommandError(f"Host {name!r} already exists.")
        _, token = Host.create_with_token(name)
        self.stdout.write(token)
