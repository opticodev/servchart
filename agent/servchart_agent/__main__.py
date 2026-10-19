"""ServChart agent entry point.

    python -m servchart_agent --hub https://servchart.example.com --token sc_xxx
    python -m servchart_agent --stdout          # print one snapshot and exit

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

from . import __version__
from .collect import collect
from .docker_api import DockerClient, DockerError

log = logging.getLogger("servchart.agent")


def push(snapshot: dict, hub: str, token: str, ca_file: str | None = None, insecure: bool = False) -> None:
    url = hub.rstrip("/") + "/api/v1/report"
    data = json.dumps(snapshot).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": f"servchart-agent/{__version__}",
        },
    )
    ctx = None
    if url.startswith("https://"):
        ctx = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
        if insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"hub answered HTTP {resp.status}")


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
    p.add_argument("--version", action="version", version=f"servchart-agent {__version__}")
    return p.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(level=os.environ.get("SERVCHART_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    client = DockerClient()

    if args.stdout:
        json.dump(collect(client, args.hostname), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if not args.hub or not args.token:
        log.error("--hub and --token are required (or SERVCHART_HUB / SERVCHART_TOKEN)")
        return 2

    log.info("servchart-agent %s reporting to %s every %ss", __version__, args.hub, args.interval)
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
