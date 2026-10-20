"""Your public addresses: the IPs (or DDNS names) your servers are reached at from outside,
usually one router doing port forwarding for several servers.

A connection from another server (a cloud VM, say) to one of these addresses is drawn to
whichever container publishes that port - e.g. `203.0.113.7:8843` -> the container that
publishes 8843. Agents only report public destinations the hub lists here.

Domains behind a proxy such as Cloudflare resolve to the proxy's shared addresses, so they
can't identify a server; list your own IP or a DNS name that points straight at it.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time

from .models import SiteSettings

MAX_ENTRIES = 20
NAME_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")
_cache: dict = {"at": 0.0, "key": None, "ips": frozenset()}
TTL = 600


def parse(text: str) -> tuple[list[str], str | None]:
    entries = []
    for raw in re.split(r"[\s,;]+", text or ""):
        item = raw.strip().lower()
        if not item:
            continue
        try:
            item = str(ipaddress.ip_address(item))
        except ValueError:
            if not NAME_RE.match(item):
                return [], f"{raw!r} isn't an IP address or a DNS name."
        if item not in entries:
            entries.append(item)
    if len(entries) > MAX_ENTRIES:
        return [], f"At most {MAX_ENTRIES} addresses."
    return entries, None


def resolve(entries: list[str]) -> frozenset[str]:
    ips = set()
    for e in entries:
        try:
            ips.add(str(ipaddress.ip_address(e)))
            continue
        except ValueError:
            pass
        try:
            for info in socket.getaddrinfo(e, None, proto=socket.IPPROTO_TCP):
                ips.add(info[4][0])
        except OSError:
            continue
    return frozenset(ips)


def public_ips() -> frozenset[str]:
    """IPs of the configured addresses, DNS names re-resolved every 10 minutes."""
    try:
        text = SiteSettings.load().public_addresses
    except Exception:  # before migrations
        return frozenset()
    entries, _ = parse(text)
    now = time.time()
    if _cache["key"] != tuple(entries) or now - _cache["at"] > TTL:
        _cache.update(at=now, key=tuple(entries), ips=resolve(entries))
    return _cache["ips"]
