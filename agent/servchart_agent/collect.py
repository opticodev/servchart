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
from . import backups, stats, storage, system
from . import connections as conn
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


def compose_info(labels: dict, hide_paths: bool = False) -> dict:
    """Which Compose stack a container belongs to, and the folder/files it was started from.

    Docker Compose stamps every container with these labels, so no access to the
    compose files themselves is needed. Portainer and Dockge stacks use Compose too.
    """
    config_files = labels.get("com.docker.compose.project.config_files") or ""
    return {
        "project": labels.get("com.docker.compose.project"),
        "service": labels.get("com.docker.compose.service"),
        "working_dir": None if hide_paths else labels.get("com.docker.compose.project.working_dir"),
        "config_files": [] if hide_paths else [f for f in config_files.split(",") if f],
        "depends_on": parse_depends_on(labels.get("com.docker.compose.depends_on")),
    }


def parse_depends_on(value: str | None) -> list[str]:
    """Compose (v2.17+) stores depends_on as "db:service_healthy:false,redis:service_started:false"."""
    services = []
    for item in (value or "").split(","):
        name = item.split(":", 1)[0].strip()
        if name and name not in services:
            services.append(name)
    return services


_digests: dict[str, list[str]] = {}  # image id -> RepoDigests


def image_digests(client, image_id: str | None) -> list[str]:
    """Registry digests of an image ("repo@sha256:..."), so the hub can tell if its tag moved."""
    if not image_id:
        return []
    if image_id not in _digests:
        try:
            doc = client.get(f"/images/{image_id}/json")
            _digests[image_id] = [d for d in (doc.get("RepoDigests") or []) if isinstance(d, str)][:10]
        except Exception:
            return []
    return _digests[image_id]


def _flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


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
        "restart_count": inspect.get("RestartCount") or 0,
        "network_mode": host_config.get("NetworkMode"),
        "compose": compose_info(labels, hide_paths),
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


def observe_enabled() -> bool:
    return os.environ.get("SERVCHART_OBSERVE_CONNECTIONS", "0").lower() in ("1", "true", "yes", "on")


def collect(client: DockerClient | None = None, hostname: str | None = None) -> dict:
    client = client or DockerClient()
    hide_paths = os.environ.get("SERVCHART_HIDE_PATHS", "0") == "1"
    include_public = os.environ.get("SERVCHART_OBSERVE_PUBLIC", "0") == "1"
    info = client.info()
    version = client.version()

    inspected = []
    for summary in client.containers():
        try:
            inspected.append(client.inspect_container(summary["Id"]))
        except Exception:  # container vanished between list and inspect
            continue
    containers = [container_record(i, hide_paths) for i in inspected]
    for rec, doc in zip(containers, inspected):
        rec["image_digests"] = image_digests(client, doc.get("Image"))
    if _flag("SERVCHART_STATS"):
        by_id = stats.collect(client, [d.get("Id") for d in inspected if (d.get("State") or {}).get("Running")])
        for rec, doc in zip(containers, inspected):
            if doc.get("Id") in by_id:
                rec["stats"] = by_id[doc["Id"]]
    networks = [network_record(n) for n in client.networks()]

    host = {
        "hostname": hostname or os.environ.get("SERVCHART_HOSTNAME") or info.get("Name"),
        "os": info.get("OperatingSystem"),
        "kernel": info.get("KernelVersion"),
        "arch": info.get("Architecture"),
        "cpus": info.get("NCPU"),
        "memory_bytes": info.get("MemTotal"),
        "docker_version": version.get("Version"),
        "observe": "off",
        # on-demand log viewing, opt-in per host (SERVCHART_ALLOW_LOGS=1)
        "logs": "on" if os.environ.get("SERVCHART_ALLOW_LOGS", "0").lower() in ("1", "true", "yes", "on") else "off",
    }
    if _flag("SERVCHART_HEALTH"):
        host["health"] = system.health(info.get("DockerRootDir"))
    snapshot = {
        "schema": SCHEMA_VERSION,
        "agent_version": __version__,
        "collected_at": _now(),
        "host": host,
        "containers": containers,
        "networks": networks,
    }

    docker_disk = storage.collect(client)
    if docker_disk is not None:
        snapshot["storage"] = docker_disk
    backup_status = backups.collect()
    if backup_status is not None:
        snapshot["backups"] = backup_status

    # The host's own addresses let the hub resolve other hosts' connections to this one.
    # Readable only when we see the host's /proc (native, or --pid host); else SERVCHART_HOST_IPS.
    subnets = [s for n in networks for s in n.get("subnets") or []]
    host["ips"] = conn.host_ips(subnets) if conn.observe_available() else conn.host_ips_from_env()

    if observe_enabled():
        if conn.observe_available():
            observe(snapshot, inspected, include_public)
        else:
            host["observe"] = "unavailable"  # needs --pid host when running in a container

    snapshot["containers"] = sorted(containers, key=lambda c: c["name"])
    snapshot["networks"] = sorted(networks, key=lambda n: n["name"] or "")
    return snapshot


def observe(snapshot: dict, inspected: list[dict], include_public: bool = False) -> None:
    """Add observed outbound connections to each container and to the host itself."""
    host = snapshot["host"]
    container_ips = {n["ip"] for c in snapshot["containers"] for n in c["networks"] if n.get("ip")}
    by_name = {c["name"]: c for c in snapshot["containers"]}
    read = 0
    for doc in inspected:
        rec = by_name.get((doc.get("Name") or "").lstrip("/"))
        state = doc.get("State") or {}
        mode = (doc.get("HostConfig") or {}).get("NetworkMode") or ""
        # host-mode containers share the host's table (reported below); container:X shares X's.
        if not rec or not state.get("Running") or mode == "host" or mode.startswith("container:"):
            continue
        rows = conn.read_netns(state.get("Pid") or 0)
        if rows is None:
            continue
        read += 1
        own_ips = {n["ip"] for n in rec["networks"] if n.get("ip")}
        rec["connections"] = conn.outbound(rows, exclude_ips=own_ips, include_public=include_public)
        rec["listening"] = conn.listening_ports(rows)
    host_rows = conn.read_netns(1)
    if host_rows is not None:
        # skip host -> own containers: that's Docker's port forwarding, not an application talking
        snapshot["host_connections"] = conn.outbound(host_rows, exclude_ips=container_ips | set(host.get("ips") or []), include_public=include_public)
    host["observe"] = "on" if (read or host_rows is not None) else "unavailable"
