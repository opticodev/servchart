"""Server-side checks on agent reports.

The hub never trusts an agent to have sanitized its data: it re-applies the
whitelist so a modified or buggy agent can't store fields the UI doesn't expect
(e.g. environment variables).
"""

import re

SUPPORTED_SCHEMAS = {1}
SECRET_KEY_RE = re.compile(r"(pass|secret|token|key|auth|credential|cookie|private)", re.IGNORECASE)

HOST_FIELDS = ("hostname", "os", "kernel", "arch", "cpus", "memory_bytes", "docker_version")
CONTAINER_FIELDS = ("id", "name", "image", "state", "health", "started_at", "restart_policy", "network_mode")
NETWORK_FIELDS = ("id", "name", "driver", "scope", "internal", "subnets")


class ReportError(ValueError):
    pass


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
        "host": _pick(data.get("host") or {}, HOST_FIELDS),
        "containers": containers,
        "networks": networks,
    }
