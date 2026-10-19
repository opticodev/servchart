"""Observed network connections ("who talks to whom"), read from the kernel's TCP tables.

Every network namespace has its own /proc/<pid>/net/tcp{,6} - the same data `ss -tn`
shows. Reading another container's table needs the host's /proc, so the agent must run
with `--pid host` (or as a plain process on the host). This is opt-in:
SERVCHART_OBSERVE_CONNECTIONS=1.

What is reported, per container and for the host itself:
  * outbound ESTABLISHED connections only (inbound ones are the other side's outbound),
    aggregated to (destination IP, destination port, count) - no source ports, no payloads;
  * private destinations only (RFC 1918, CGNAT/Tailscale 100.64/10, ULA fc00::/7) unless
    SERVCHART_OBSERVE_PUBLIC=1, so the internet hosts your apps call never leave the host.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import struct
from collections import Counter

PROC = os.environ.get("SERVCHART_PROC", "/proc")
TCP_ESTABLISHED = "01"
TCP_LISTEN = "0A"
CGNAT = ipaddress.ip_network("100.64.0.0/10")
MAX_PER_SOURCE = 200


def _hex_to_ip(h: str) -> str:
    if len(h) == 8:  # IPv4: one 32-bit word in host (little-endian) order
        return socket.inet_ntop(socket.AF_INET, struct.pack("<I", int(h, 16)))
    # IPv6: four 32-bit words, each in host order
    raw = b"".join(struct.pack("<I", int(h[i : i + 8], 16)) for i in range(0, 32, 8))
    addr = ipaddress.IPv6Address(raw)
    return str(addr.ipv4_mapped) if addr.ipv4_mapped else str(addr)


def parse_tcp_table(text: str) -> list[tuple[str, int, str, int, str]]:
    """Parse /proc/net/tcp or tcp6 into (local_ip, local_port, remote_ip, remote_port, state)."""
    rows = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            lip, lport = parts[1].split(":")
            rip, rport = parts[2].split(":")
            rows.append((_hex_to_ip(lip), int(lport, 16), _hex_to_ip(rip), int(rport, 16), parts[3].upper()))
        except (ValueError, struct.error):
            continue
    return rows


def read_netns(pid: int | str) -> list[tuple[str, int, str, int, str]] | None:
    """TCP rows of the network namespace that process `pid` lives in, or None if unreadable."""
    rows, ok = [], False
    for name in ("tcp", "tcp6"):
        try:
            with open(f"{PROC}/{pid}/net/{name}") as fh:
                rows.extend(parse_tcp_table(fh.read()))
                ok = True
        except OSError:
            continue
    return rows if ok else None


def is_reportable(ip: str, include_public: bool = False) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback or addr.is_unspecified or addr.is_link_local or addr.is_multicast:
        return False
    if include_public:
        return True
    return addr.is_private or (addr.version == 4 and addr in CGNAT)


def outbound(rows, exclude_ips=(), include_public: bool = False) -> list[dict]:
    """Aggregate outbound established connections: [{"ip", "port", "count"}].

    A connection is outbound when its local port isn't one this namespace listens on.
    """
    listening = {lport for _, lport, _, _, st in rows if st == TCP_LISTEN}
    exclude = set(exclude_ips)
    counts: Counter = Counter()
    for _lip, lport, rip, rport, st in rows:
        if st != TCP_ESTABLISHED or lport in listening:
            continue
        if rip in exclude or not is_reportable(rip, include_public):
            continue
        counts[(rip, rport)] += 1
    out = [{"ip": ip, "port": port, "count": n} for (ip, port), n in counts.items()]
    out.sort(key=lambda c: (-c["count"], c["ip"], c["port"]))
    return out[:MAX_PER_SOURCE]


def listening_ports(rows) -> list[int]:
    return sorted({lport for lip, lport, _, _, st in rows if st == TCP_LISTEN and not lip.startswith("127.")})


def host_ips(docker_subnets=()) -> list[str]:
    """Addresses of the host itself (from the host's routing trie), minus Docker bridge gateways.

    Docker bridge gateways (172.17.0.1, ...) exist on every host, so they would make
    cross-host matching ambiguous; anything inside a Docker network subnet is dropped.
    Extra addresses can be added with SERVCHART_HOST_IPS=ip1,ip2 (e.g. a public IP).
    """
    found = set()
    try:
        with open(f"{PROC}/1/net/fib_trie") as fh:
            last = None
            for line in fh:
                s = line.strip()
                if s.startswith("|--"):
                    last = s[3:].strip()
                elif "/32 host LOCAL" in s and last:
                    found.add(last)
    except OSError:
        pass
    nets = []
    for sn in docker_subnets:
        try:
            nets.append(ipaddress.ip_network(sn, strict=False))
        except ValueError:
            continue
    keep = set()
    for ip in found:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_loopback or any(addr in n for n in nets if n.version == addr.version):
            continue
        keep.add(ip)
    keep.update(host_ips_from_env())
    return sorted(keep)


def host_ips_from_env() -> list[str]:
    return sorted({ip.strip() for ip in (os.environ.get("SERVCHART_HOST_IPS") or "").split(",") if ip.strip()})


INIT_NAMES = {"systemd", "init", "runit", "openrc-init", "s6-svscan", "launchd"}


def _in_container() -> bool:
    return os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")


def observe_available() -> bool:
    """True when this process sees the host's processes: run natively, or in a container with --pid host.

    Without --pid host, PID 1 is the container's own entrypoint, and /proc/1/net would be
    our own namespace - so it must never be mistaken for the host's.
    """
    if not _in_container():
        return True
    try:
        with open(f"{PROC}/1/comm") as fh:
            return fh.read().strip() in INIT_NAMES
    except OSError:
        return False
