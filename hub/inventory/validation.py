"""Server-side checks on agent reports.

The hub never trusts an agent to have sanitized its data: it re-applies the
whitelist so a modified or buggy agent can't store fields the UI doesn't expect
(e.g. environment variables).
"""

import ipaddress
import re

SUPPORTED_SCHEMAS = {1}
SECRET_KEY_RE = re.compile(r"(pass|secret|token|key|auth|credential|cookie|private)", re.IGNORECASE)

HOST_FIELDS = ("hostname", "os", "kernel", "arch", "cpus", "memory_bytes", "docker_version")
CONTAINER_FIELDS = ("id", "name", "image", "state", "health", "started_at", "restart_policy", "network_mode")
NETWORK_FIELDS = ("id", "name", "driver", "scope", "internal", "subnets")


class ReportError(ValueError):
    pass


def _ip(value):
    try:
        return str(ipaddress.ip_address(str(value)))
    except ValueError:
        return None


def _int(value, lo=0, hi=65535):
    return value if isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi else None


def clean_connections(value, limit=200):
    """[{ip, port, count}] observed outbound connections; anything malformed is dropped."""
    out = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        ip, port, count = _ip(item.get("ip")), _int(item.get("port"), 1), _int(item.get("count"), 1, 10**6)
        if ip and port and count:
            out.append({"ip": ip, "port": port, "count": count})
        if len(out) >= limit:
            break
    return out


def _pick(obj, fields):
    return {f: obj.get(f) for f in fields if f in obj}


def _list(value, what):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ReportError(f"{what} must be a list")
    return value


def clean_report(data) -> dict:
    if not isinstance(data, dict):
        raise ReportError("report must be a JSON object")
    if data.get("schema") not in SUPPORTED_SCHEMAS:
        raise ReportError(f"unsupported schema {data.get('schema')!r}; supported: {sorted(SUPPORTED_SCHEMAS)}")

    containers = []
    for c in _list(data.get("containers"), "containers"):
        if not isinstance(c, dict) or not c.get("name"):
            continue
        rec = _pick(c, CONTAINER_FIELDS)
        compose = c.get("compose") or {}
        config_files = compose.get("config_files") or []
        rec["compose"] = {
            "project": compose.get("project"),
            "service": compose.get("service"),
            "working_dir": compose.get("working_dir") if isinstance(compose.get("working_dir"), str) else None,
            "config_files": [str(f) for f in config_files][:20] if isinstance(config_files, list) else [],
            "depends_on": [str(d) for d in compose.get("depends_on") or [] if isinstance(d, str)][:50]
            if isinstance(compose.get("depends_on"), list)
            else [],
        }
        rec["labels"] = {
            str(k): ("[redacted]" if SECRET_KEY_RE.search(str(k)) else v)
            for k, v in (c.get("labels") or {}).items()
            if isinstance(v, (str, int, float, bool)) or v is None
        }
        rec["networks"] = [
            {"name": n.get("name"), "ip": n.get("ip"), "aliases": list(n.get("aliases") or [])}
            for n in _list(c.get("networks"), "networks")
            if isinstance(n, dict) and n.get("name")
        ]
        rec["ports"] = [
            {
                "private": p.get("private"),
                "protocol": p.get("protocol", "tcp"),
                "public": p.get("public"),
                "ips": list(p.get("ips") or []),
            }
            for p in _list(c.get("ports"), "ports")
            if isinstance(p, dict)
        ]
        rec["mounts"] = [
            _pick(m, ("type", "source", "destination", "rw"))
            for m in _list(c.get("mounts"), "mounts")
            if isinstance(m, dict)
        ]
        if "connections" in c:
            rec["connections"] = clean_connections(c.get("connections"))
        if isinstance(c.get("listening"), list):
            rec["listening"] = sorted({p for p in c["listening"] if _int(p, 1)})[:100]
        rec["restart_count"] = _int(c.get("restart_count"), 0, 10**9) or 0
        containers.append(rec)

    networks = [
        _pick(n, NETWORK_FIELDS)
        for n in _list(data.get("networks"), "networks")
        if isinstance(n, dict) and n.get("name")
    ]

    return {
        "schema": data["schema"],
        "agent_version": str(data.get("agent_version") or "")[:32],
        "collected_at": data.get("collected_at"),
        "host": clean_host(data.get("host") or {}),
        "host_connections": clean_connections(data.get("host_connections")),
        "containers": containers,
        "networks": networks,
    }


def clean_host(host: dict) -> dict:
    out = _pick(host, HOST_FIELDS)
    ips = host.get("ips")
    out["ips"] = sorted({ip for ip in (_ip(i) for i in ips) if ip})[:50] if isinstance(ips, list) else []
    out["observe"] = host.get("observe") if host.get("observe") in ("on", "off", "unavailable") else "off"
    out["logs"] = "on" if host.get("logs") == "on" else "off"
    return out
