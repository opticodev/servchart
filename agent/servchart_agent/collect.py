"""Build a sanitized inventory snapshot of one Docker host.

Privacy rules (enforced here, before anything leaves the host):
  * Container environment variables (Config.Env) are never read into the snapshot.
  * Command lines / entrypoint arguments are dropped (they often carry secrets).
  * Label values whose key looks secret-ish are replaced with "[redacted]".
  * Bind-mount source paths are kept (they are useful for the map) but can be
    hidden entirely with SERVCHART_HIDE_PATHS=1.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from . import SCHEMA_VERSION, __version__
from .docker_api import DockerClient

SECRET_KEY_RE = re.compile(r"(pass|secret|token|key|auth|credential|cookie|private)", re.IGNORECASE)
REDACTED = "[redacted]"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sanitize_labels(labels: dict | None) -> dict:
    out = {}
    for key, value in (labels or {}).items():
        out[key] = REDACTED if SECRET_KEY_RE.search(key) else value
    return out


def _ports(inspect: dict) -> list[dict]:
    """One entry per (private port, protocol, public port); host IPs are merged.

    Docker reports IPv4 and IPv6 bindings of the same port separately; the map
    only needs to know the port is published and on which addresses.
    """
    merged: dict[tuple, dict] = {}
    bindings = (inspect.get("NetworkSettings") or {}).get("Ports") or {}
    for spec, published in bindings.items():
        private, _, proto = spec.partition("/")
        proto = proto or "tcp"
        for b in published or [None]:
            public = int(b["HostPort"]) if b and b.get("HostPort") else None
            entry = merged.setdefault(
                (int(private), proto, public),
                {"private": int(private), "protocol": proto, "public": public, "ips": []},
            )
            ip = (b or {}).get("HostIp")
            if ip and ip not in entry["ips"]:
                entry["ips"].append(ip)
    return [merged[k] for k in sorted(merged, key=lambda k: (k[0], k[1], k[2] or 0))]


def _mounts(inspect: dict, hide_paths: bool) -> list[dict]:
    mounts = []
    for m in inspect.get("Mounts") or []:
        kind = m.get("Type")
        if kind == "volume":
            source = m.get("Name")
        elif hide_paths:
            source = None
        else:
            source = m.get("Source")
        mounts.append(
            {"type": kind, "source": source, "destination": m.get("Destination"), "rw": bool(m.get("RW"))}
        )
    return mounts


def _networks(inspect: dict) -> list[dict]:
    nets = []
    for name, cfg in sorted(((inspect.get("NetworkSettings") or {}).get("Networks") or {}).items()):
        cfg = cfg or {}
        nets.append(
            {
                "name": name,
                "ip": cfg.get("IPAddress") or None,
                "aliases": sorted(set(cfg.get("Aliases") or []) - {inspect.get("Id", "")[:12]}),
            }
        )
    return nets


def container_record(inspect: dict, hide_paths: bool = False) -> dict:
    """Convert a `docker inspect` document into a sanitized ServChart record.

    Deliberately whitelists fields instead of copying the document, so new
    Docker fields (or Env) can never leak by accident.
    """
    config = inspect.get("Config") or {}
    state = inspect.get("State") or {}
    host_config = inspect.get("HostConfig") or {}
    labels = config.get("Labels") or {}
    health = (state.get("Health") or {}).get("Status")
    return {
        "id": (inspect.get("Id") or "")[:12],
        "name": (inspect.get("Name") or "").lstrip("/"),
        "image": config.get("Image"),
        "state": state.get("Status"),
        "health": health,
        "started_at": state.get("StartedAt"),
        "restart_policy": (host_config.get("RestartPolicy") or {}).get("Name") or None,
        "network_mode": host_config.get("NetworkMode"),
        "compose": {
            "project": labels.get("com.docker.compose.project"),
            "service": labels.get("com.docker.compose.service"),
        },
        "labels": sanitize_labels(labels),
        "networks": _networks(inspect),
        "ports": _ports(inspect),
        "mounts": _mounts(inspect, hide_paths),
    }


def network_record(net: dict) -> dict:
    ipam = (net.get("IPAM") or {}).get("Config") or []
    return {
        "id": (net.get("Id") or "")[:12],
        "name": net.get("Name"),
        "driver": net.get("Driver"),
        "scope": net.get("Scope"),
        "internal": bool(net.get("Internal")),
        "subnets": [c.get("Subnet") for c in ipam if c.get("Subnet")],
    }


def collect(client: DockerClient | None = None, hostname: str | None = None) -> dict:
    client = client or DockerClient()
    hide_paths = os.environ.get("SERVCHART_HIDE_PATHS", "0") == "1"
    info = client.info()
    version = client.version()
    containers = []
    for summary in client.containers():
        try:
            containers.append(container_record(client.inspect_container(summary["Id"]), hide_paths))
        except Exception:  # container vanished between list and inspect
            continue
    networks = [network_record(n) for n in client.networks()]
    return {
        "schema": SCHEMA_VERSION,
        "agent_version": __version__,
        "collected_at": _now(),
        "host": {
            "hostname": hostname or os.environ.get("SERVCHART_HOSTNAME") or info.get("Name"),
            "os": info.get("OperatingSystem"),
            "kernel": info.get("KernelVersion"),
            "arch": info.get("Architecture"),
            "cpus": info.get("NCPU"),
            "memory_bytes": info.get("MemTotal"),
            "docker_version": version.get("Version"),
        },
        "containers": sorted(containers, key=lambda c: c["name"]),
        "networks": sorted(networks, key=lambda n: n["name"] or ""),
    }
