"""Load the fictional sample hosts from examples/sample-data (for demos and screenshots)."""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from inventory.models import Host
from inventory.validation import clean_report

DEFAULT_DIR = Path(settings.BASE_DIR).parent / "examples" / "sample-data"


class Command(BaseCommand):
    help = "Load demo hosts from JSON snapshots (default: examples/sample-data)."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(DEFAULT_DIR))

    def handle(self, *args, dir, **options):
        files = sorted(Path(dir).glob("*.json"))
        if not files:
            self.stderr.write(f"No .json files in {dir}")
            return
        for f in files:
            snap = clean_report(json.loads(f.read_text()))
            name = snap["host"].get("hostname") or f.stem
            host = Host.objects.filter(name=name).first() or Host.create_with_token(name)[0]
            host.snapshot = snap
            host.agent_version = snap["agent_version"]
            host.last_seen = timezone.now()
            host.save()
            self.stdout.write(f"loaded {name}: {len(snap['containers'])} containers")
