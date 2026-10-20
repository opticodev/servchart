"""Collect the hub's own host through the mounted Docker socket.

This is what makes a fresh install show a map within seconds, before any agent
is installed. It uses exactly the same collector as the standalone agent.
"""

import logging
import os
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from inventory.models import Host, hash_token
from inventory.validation import clean_report
from inventory.views import store_report

log = logging.getLogger("servchart.local_agent")


class Command(BaseCommand):
    help = "Report the hub's own Docker host every SERVCHART_INTERVAL seconds."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, once=False, **options):
        from servchart_agent.collect import collect
        from servchart_agent.docker_api import DockerClient, DockerError

        interval = int(os.environ.get("SERVCHART_INTERVAL", "60"))
        client = DockerClient()
        while True:
            close_old_connections()
            try:
                snap = clean_report(collect(client))
                name = os.environ.get("SERVCHART_LOCAL_NAME") or snap["host"].get("hostname") or "local"
                # the record this collector created (token_hint "local"), never an agent host
                host = Host.objects.filter(is_local=True, token_hint="local").order_by("pk").first()
                if host is None:
                    # Local host never authenticates with a token; store an unusable random hash.
                    host = Host.objects.create(
                        name=name, is_local=True, token_hash=hash_token(os.urandom(32).hex()), token_hint="local"
                    )
                store_report(host, snap)
                log.info("local host %s: %d containers", host.name, len(snap["containers"]))
            except DockerError as exc:
                log.warning("local collector: %s", exc)
            except Exception:
                log.exception("local collector failed")
            if once:
                return
            time.sleep(interval)
