"""ServChart agent entry point.

    python -m servchart_agent --hub https://servchart.example.com --token sc_xxx
    python -m servchart_agent --stdout          # print one snapshot and exit
    python -m servchart_agent --mark kopia      # record a successful backup run (see backups.py)

Every option can also be set with an environment variable (shown in --help).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

from . import __version__, backups, commands
from .collect import collect
from .docker_api import DockerClient, DockerError

log = logging.getLogger("servchart.agent")


def hub_request(hub: str, token: str, ca_file: str | None = None, insecure: bool = False):
    """Returns request(method, path, body) -> parsed JSON, bound to this hub and token."""
    ctx = None
    if hub.startswith("https://"):
        ctx = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
        if insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

    def request(method: str, path: str, body):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            hub.rstrip("/") + path,
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": f"servchart-agent/{__version__}",
            },
        )
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None

    return request


def push(snapshot: dict, hub: str, token: str, ca_file: str | None = None, insecure: bool = False) -> None:
    answer = hub_request(hub, token, ca_file, insecure)("POST", "/api/v1/report", snapshot)
    apply_hub_hints(answer)


def apply_hub_hints(answer) -> None:
    """The hub may list your public addresses so connections to them get reported (max 50, IPs only)."""
    import ipaddress

    from . import connections

    ips = (answer or {}).get("observe_ips") if isinstance(answer, dict) else None
    if not isinstance(ips, list):
        return
    clean = set()
    for ip in ips[:50]:
        try:
            clean.add(str(ipaddress.ip_address(str(ip))))
        except ValueError:
            continue
    connections.EXTRA_IPS.clear()
    connections.EXTRA_IPS.update(clean)


def parse_args(argv=None):
    env = os.environ.get
    p = argparse.ArgumentParser(prog="servchart-agent", description="Report this host's Docker state to a ServChart hub.")
    p.add_argument("--hub", default=env("SERVCHART_HUB"), help="Hub URL (env SERVCHART_HUB)")
    p.add_argument("--token", default=env("SERVCHART_TOKEN"), help="Host token from the hub (env SERVCHART_TOKEN)")
    p.add_argument("--interval", type=int, default=int(env("SERVCHART_INTERVAL", "60")),
                   help="Seconds between reports (env SERVCHART_INTERVAL, default 60)")
    p.add_argument("--hostname", default=env("SERVCHART_HOSTNAME"),
                   help="Override the reported host name (env SERVCHART_HOSTNAME)")
    p.add_argument("--ca-file", default=env("SERVCHART_CA_FILE"), help="CA bundle for a self-signed hub (env SERVCHART_CA_FILE)")
    p.add_argument("--insecure", action="store_true", default=env("SERVCHART_INSECURE") == "1",
                   help="Skip TLS verification (env SERVCHART_INSECURE=1). Not recommended.")
    p.add_argument("--once", action="store_true", help="Report once and exit")
    p.add_argument("--stdout", action="store_true", help="Print the snapshot as JSON instead of sending it")
    p.add_argument("--mark", metavar="NAME", help="Record that the backup job NAME just finished, then exit")
    p.add_argument("--failed", action="store_true", help="With --mark: the backup failed")
    p.add_argument("--message", default="", help="With --mark: a short note shown in ServChart")
    p.add_argument("--max-age-hours", type=float, help="With --mark: warn when no new run within this many hours (default 26)")
    p.add_argument("--version", action="version", version=f"servchart-agent {__version__}")
    return p.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(level=os.environ.get("SERVCHART_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    if args.mark:
        try:
            path = backups.mark(args.mark, ok=not args.failed, message=args.message, max_age_hours=args.max_age_hours)
        except (ValueError, OSError) as exc:
            log.error("could not record backup status: %s", exc)
            return 1
        log.info("recorded %s backup %s in %s", args.mark, "failure" if args.failed else "success", path)
        return 0
    client = DockerClient()

    if args.stdout:
        json.dump(collect(client, args.hostname), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if not args.hub or not args.token:
        log.error("--hub and --token are required (or SERVCHART_HUB / SERVCHART_TOKEN)")
        return 2

    log.info("servchart-agent %s reporting to %s every %ss", __version__, args.hub, args.interval)
    if not args.once:
        commands.start(client, hub_request(args.hub, args.token, args.ca_file, args.insecure))
    backoff = 0
    while True:
        try:
            snap = collect(client, args.hostname)
            push(snap, args.hub, args.token, args.ca_file, args.insecure)
            log.info("reported %d containers, %d networks", len(snap["containers"]), len(snap["networks"]))
            backoff = 0
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                log.error("hub rejected the token (HTTP %s) - check SERVCHART_TOKEN", exc.code)
            else:
                log.warning("hub error: HTTP %s", exc.code)
            backoff = min(max(backoff * 2, args.interval), 900)
        except (DockerError, OSError, RuntimeError) as exc:
            log.warning("report failed: %s", exc)
            backoff = min(max(backoff * 2, args.interval), 900)
        if args.once:
            return 0 if backoff == 0 else 1
        time.sleep(backoff or args.interval)


if __name__ == "__main__":
    sys.exit(main())
