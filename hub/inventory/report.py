"""Infrastructure report: a summary, things worth a look ("findings"), the inventory and who
talks to whom. Pure functions over build_graph() output, so the same data feeds the
printable page, the CSV/JSON exports and the scheduled email.
"""

from __future__ import annotations

import csv
import io

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
ALL_INTERFACES = {"", "0.0.0.0", "::"}
RESTART_WARN = 5


def _image_tag(image: str | None) -> str | None:
    """The tag of an image reference, or None when there is none (registry ports aren't tags)."""
    if not image or "@sha256:" in image:
        return "digest" if image else None
    last = image.rsplit("/", 1)[-1]
    return last.split(":", 1)[1] if ":" in last else None


def _ctr_label(host_name: str, c: dict) -> str:
    return f"{host_name} / {c.get('name')}"


def build_report(graph: dict, site_name: str = "ServChart") -> dict:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    hosts = [n["data"] for n in nodes if n["type"] == "host"]
    host_name = {n["id"]: n["data"].get("name") for n in nodes if n["type"] == "host"}
    names = {n["id"]: n["data"].get("name") or n["id"] for n in nodes}
    containers = [(n["host"], n["data"]) for n in nodes if n["type"] == "container"]
    stacks = [n for n in nodes if n["type"] == "stack"]

    findings = []

    def add(severity, code, target, message):
        findings.append({"severity": severity, "code": code, "target": target, "message": message})

    for h in hosts:
        info = h.get("info") or {}
        if h.get("status") == "stale":
            add("high", "host-stale", h["name"], f"No report since {h.get('last_seen')}. Is the agent running?")
        elif h.get("status") == "pending":
            add("medium", "host-pending", h["name"], "Added but never reported. Install the agent with the command from Settings.")
        if h.get("status") == "online" and info.get("observe") != "on" and not h.get("is_local"):
            add("info", "observe-off", h["name"], "Traffic isn't observed. Run the agent with --pid host and SERVCHART_OBSERVE_CONNECTIONS=1 to draw who talks to whom.")

    for hid, c in containers:
        label = _ctr_label(host_name.get(hid, hid), c)
        state, health, policy = c.get("state"), c.get("health"), c.get("restart_policy")
        if health == "unhealthy":
            add("high", "unhealthy", label, "Health check is failing.")
        if state == "restarting":
            add("high", "restarting", label, "Stuck restarting.")
        elif state in ("exited", "dead") and policy in ("always", "unless-stopped"):
            add("medium", "stopped", label, f"Stopped although its restart policy is '{policy}'.")
        if (c.get("restart_count") or 0) >= RESTART_WARN:
            add("medium", "restart-count", label, f"Restarted {c['restart_count']} times since it was created.")
        if state == "running" and policy in (None, "", "no"):
            add("low", "no-restart-policy", label, "No restart policy: it won't come back after a reboot or crash.")
        tag = _image_tag(c.get("image"))
        if c.get("image") and tag in (None, "latest"):
            add("low", "latest-tag", label, f"Image {c['image']} isn't pinned to a version; updates can change it silently.")
        open_ports = sorted({p["public"] for p in c.get("ports") or [] if p.get("public") and (not p.get("ips") or set(p["ips"]) & ALL_INTERFACES)})
        if open_ports:
            add("info", "all-interfaces", label, f"Port(s) {', '.join(map(str, open_ports))} listen on every interface; bind to 127.0.0.1 if only a proxy uses them.")
        unknown = c.get("talks_to_unresolved") or []
        if unknown:
            dests = ", ".join(sorted({f"{u['ip']}:{u['port']}" for u in unknown})[:5])
            add("info", "unknown-destination", label, f"Talks to addresses that aren't a mapped host: {dests}.")

    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["code"], f["target"]))

    inventory = []
    for h in hosts:
        hid = h["id"]
        host_stacks = []
        for s in stacks:
            if s["host"] != hid:
                continue
            members = [c for chost, c in containers if chost == hid and (c.get("compose") or {}).get("project") == s["data"].get("name")]
            host_stacks.append(
                {
                    "name": s["data"].get("name") or "Standalone containers",
                    "standalone": s["data"].get("standalone", False),
                    "working_dir": s["data"].get("working_dir"),
                    "containers": [_container_row(c) for c in sorted(members, key=lambda c: c.get("name") or "")],
                }
            )
        inventory.append(
            {
                "host": h["name"],
                "status": h.get("status"),
                "last_seen": h.get("last_seen"),
                "os": (h.get("info") or {}).get("os"),
                "docker_version": (h.get("info") or {}).get("docker_version"),
                "cpus": (h.get("info") or {}).get("cpus"),
                "memory_bytes": (h.get("info") or {}).get("memory_bytes"),
                "agent_version": h.get("agent_version"),
                "stacks": host_stacks,
            }
        )

    connections = []
    for e in edges:
        if e.get("kind") not in ("flow", "depends"):
            continue
        connections.append(
            {
                "kind": "observed" if e["kind"] == "flow" else "depends_on",
                "source": _qualified(e["source"], names, host_name),
                "target": _qualified(e["target"], names, host_name),
                "ports": e.get("ports") or [],
                "count": e.get("count"),
                "cross_host": bool(e.get("cross_host")),
            }
        )
    connections.sort(key=lambda c: (c["kind"], c["source"], c["target"]))

    all_ctrs = [c for _, c in containers]
    return {
        "title": f"{site_name} infrastructure report",
        "generated_at": graph.get("generated_at"),
        "summary": {
            "hosts": len(hosts),
            "hosts_online": sum(1 for h in hosts if h.get("status") == "online"),
            "stacks": sum(1 for s in stacks if not s["data"].get("standalone")),
            "containers": len(all_ctrs),
            "running": sum(1 for c in all_ctrs if c.get("state") == "running"),
            "unhealthy": sum(1 for c in all_ctrs if c.get("health") == "unhealthy"),
            "published_ports": sum(1 for c in all_ctrs for p in c.get("ports") or [] if p.get("public")),
            "connections": sum(1 for c in connections if c["kind"] == "observed"),
            "findings": {sev: sum(1 for f in findings if f["severity"] == sev) for sev in SEVERITY_ORDER},
        },
        "findings": findings,
        "inventory": inventory,
        "connections": connections,
    }


def _qualified(node_id: str, names: dict, host_name: dict) -> str:
    kind, rest = node_id.split(":", 1)
    if kind == "host":
        return host_name.get(node_id, node_id)
    hid = "host:" + rest.split(":", 1)[0]
    return f"{host_name.get(hid, hid)} / {names.get(node_id, node_id)}"


def _container_row(c: dict) -> dict:
    return {
        "name": c.get("name"),
        "service": (c.get("compose") or {}).get("service"),
        "image": c.get("image"),
        "state": c.get("state"),
        "health": c.get("health"),
        "restart_policy": c.get("restart_policy"),
        "restart_count": c.get("restart_count") or 0,
        "started_at": c.get("started_at"),
        "ports": [
            f"{','.join(p.get('ips') or []) + ':' if p.get('ips') else ''}{p['public']}->{p['private']}/{p.get('protocol', 'tcp')}"
            for p in c.get("ports") or []
            if p.get("public")
        ],
        "networks": [n.get("name") for n in c.get("networks") or []],
    }


# --- CSV exports -------------------------------------------------------------------------

CSV_KINDS = ("containers", "ports", "connections", "findings")


def _safe(value) -> str:
    """Stop spreadsheet formula injection: cells starting with = + - @ are prefixed with '."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(report: dict, kind: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    if kind == "containers":
        w.writerow(["host", "stack", "container", "service", "image", "state", "health", "restart_policy", "restart_count", "started_at", "ports", "networks"])
        for h in report["inventory"]:
            for s in h["stacks"]:
                for c in s["containers"]:
                    w.writerow([_safe(v) for v in (h["host"], "" if s["standalone"] else s["name"], c["name"], c["service"], c["image"], c["state"], c["health"], c["restart_policy"], c["restart_count"], c["started_at"], " ".join(c["ports"]), " ".join(c["networks"]))])
    elif kind == "ports":
        w.writerow(["host", "container", "binding"])
        for h in report["inventory"]:
            for s in h["stacks"]:
                for c in s["containers"]:
                    for p in c["ports"]:
                        w.writerow([_safe(h["host"]), _safe(c["name"]), _safe(p)])
    elif kind == "connections":
        w.writerow(["kind", "source", "target", "ports", "connections", "cross_host"])
        for c in report["connections"]:
            w.writerow([_safe(v) for v in (c["kind"], c["source"], c["target"], " ".join(map(str, c["ports"])), c["count"] if c["count"] is not None else "", "yes" if c["cross_host"] else "no")])
    elif kind == "findings":
        w.writerow(["severity", "code", "target", "message"])
        for f in report["findings"]:
            w.writerow([_safe(f[k]) for k in ("severity", "code", "target", "message")])
    else:
        raise ValueError(kind)
    return buf.getvalue()
