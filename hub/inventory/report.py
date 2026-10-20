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


def _gb(n) -> str:
    return f"{n / 1024 ** 3:.1f} GB" if n else "0 GB"


def build_report(graph: dict, site_name: str = "ServChart", certs: list | None = None, changes: dict | None = None,
                 limits: dict | None = None) -> dict:
    """certs: [cert payloads]; changes: host name -> history.changes(); limits: thresholds."""
    limits = {"disk_warn": 85, "disk_critical": 95, "cert_warn_days": 14, **(limits or {})}
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

    # --- server health, storage and backups ----------------------------------------------------
    health_rows, backup_rows = [], []
    for h in hosts:
        info = h.get("info") or {}
        hh = info.get("health")
        if hh:
            mem_pct = round(100 * (hh["mem_total"] - hh["mem_available"]) / hh["mem_total"], 1) if hh.get("mem_total") and hh.get("mem_available") is not None else None
            for d in hh.get("disks") or []:
                pct = d.get("pct") or 0
                where = f"{h['name']}: {d['mount']}"
                if pct >= limits["disk_critical"]:
                    add("high", "disk-full", where, f"Disk is {pct:.0f}% full ({_gb(d['total'] - d['used'])} free).")
                elif pct >= limits["disk_warn"]:
                    add("medium", "disk-filling", where, f"Disk is {pct:.0f}% full ({_gb(d['total'] - d['used'])} free).")
            if mem_pct is not None and mem_pct >= 90:
                add("medium", "memory", h["name"], f"Memory is {mem_pct:.0f}% used.")
            load1 = (hh.get("load") or [None])[0]
            if load1 is not None and info.get("cpus") and load1 > 2 * info["cpus"]:
                add("low", "load", h["name"], f"Load {load1:.1f} on {info['cpus']} CPUs.")
            if hh.get("swap_total") and hh.get("swap_free") is not None and hh["swap_free"] < hh["swap_total"] * 0.5:
                add("low", "swap", h["name"], f"More than half of the swap is in use ({_gb(hh['swap_total'] - hh['swap_free'])}).")
            health_rows.append(
                {
                    "host": h["name"], "cpu_pct": hh.get("cpu_pct"), "mem_pct": mem_pct, "mem_total": hh.get("mem_total"),
                    "load": hh.get("load"), "cpus": info.get("cpus"), "uptime_s": hh.get("uptime_s"),
                    "disks": hh.get("disks") or [], "disk_source": hh.get("disk_source"),
                    "storage": {k: v for k, v in (h.get("storage") or {}).items() if k != "volumes"} or None,
                }
            )
        elif h.get("status") == "online":
            add("info", "health-off", h["name"], "No health data: update the agent to 0.4+ (CPU, memory, disks, backups).")
        st = h.get("storage") or {}
        if st.get("volumes_unused"):
            unused = sum(v.get("size") or 0 for v in st.get("volumes") or [] if v.get("refs") == 0)
            add("info", "unused-volumes", h["name"], f"{st['volumes_unused']} volume(s) not used by any container ({_gb(unused)}).")
        if (st.get("build_cache_bytes") or 0) > 5 * 1024**3:
            add("info", "build-cache", h["name"], f"Build cache uses {_gb(st['build_cache_bytes'])} (docker builder prune).")
        for b in h.get("backups") or []:
            where = f"{h['name']}: {b['name']}"
            if b["state"] == "failed":
                add("high", "backup-failed", where, f"Last backup run failed{': ' + b['message'] if b.get('message') else ''}.")
            elif b["state"] == "overdue":
                add("medium", "backup-overdue", where, f"No successful backup for {b['age_hours']:.0f} h." if b.get("age_hours") is not None else "Backup time unknown.")
            backup_rows.append({"host": h["name"], **b})

    for hid, c in containers:
        st = c.get("stats") or {}
        if st.get("mem_limit") and st.get("mem_used") and st["mem_used"] > 0.9 * st["mem_limit"]:
            add("medium", "container-memory", _ctr_label(host_name.get(hid, hid), c), f"Uses {100 * st['mem_used'] / st['mem_limit']:.0f}% of its memory limit.")

    update_rows = []
    for hid, c in containers:
        u = c.get("image_update")
        if not u or u["state"] == "current" and not u.get("newer_tag"):
            continue
        label = _ctr_label(host_name.get(hid, hid), c)
        if u["state"] == "update":
            add("low", "image-update", label, f"A newer image is published for {c['image']}; pull and recreate to update.")
        if u.get("newer_tag"):
            add("info", "newer-version", label, f"Version {u['newer_tag']} is available (running {c['image']}).")
        if u["state"] != "unknown" or u.get("newer_tag"):
            update_rows.append({"host": host_name.get(hid, hid), "container": c.get("name"), "image": c.get("image"), "state": u["state"], "newer_tag": u.get("newer_tag")})

    cert_rows = list(certs or [])
    for cert in cert_rows:
        where = f"{cert['hostname']}:{cert['port']}" if cert["port"] != 443 else cert["hostname"]
        if cert.get("error"):
            add("high", "cert-error", where, cert["error"])
        elif cert.get("days_left") is not None:
            if cert["days_left"] < 0:
                add("high", "cert-expired", where, "Certificate has expired.")
            elif cert["days_left"] < 7:
                add("high", "cert-expiring", where, f"Certificate expires in {cert['days_left']} day(s).")
            elif cert["days_left"] < limits["cert_warn_days"]:
                add("medium", "cert-expiring", where, f"Certificate expires in {cert['days_left']} days.")

    top = sorted(
        ({"host": host_name.get(hid, hid), "container": c.get("name"), "cpu_pct": (c.get("stats") or {}).get("cpu_pct"), "mem_used": (c.get("stats") or {}).get("mem_used")}
         for hid, c in containers if c.get("stats")),
        key=lambda r: -(r["mem_used"] or 0),
    )[:10]

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
                "kind": "agent_report" if e.get("agent") else "observed" if e["kind"] == "flow" else "depends_on",
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
            "disks_warn": sum(1 for f in findings if f["code"] in ("disk-full", "disk-filling")),
            "backups": len(backup_rows),
            "backups_bad": sum(1 for b in backup_rows if b["state"] != "ok"),
            "certs": len(cert_rows),
            "certs_bad": sum(1 for f in findings if f["code"].startswith("cert-")),
            "updates": sum(1 for u in update_rows if u["state"] == "update" or u.get("newer_tag")),
        },
        "findings": findings,
        "inventory": inventory,
        "connections": connections,
        "health": health_rows,
        "top_containers": top,
        "backups": backup_rows,
        "certificates": cert_rows,
        "updates": update_rows,
        "changes": {k: v for k, v in (changes or {}).items() if v and (v["added"] or v["removed"] or v["image_changed"])},
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

CSV_KINDS = ("containers", "ports", "connections", "findings", "hosts", "backups", "certificates", "updates")


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
    elif kind == "hosts":
        w.writerow(["host", "cpu_pct", "mem_pct", "mem_total", "load1", "cpus", "uptime_hours", "mount", "disk_total", "disk_used", "disk_pct"])
        for r in report["health"]:
            base = [r["host"], r["cpu_pct"], r["mem_pct"], r["mem_total"], (r["load"] or [None])[0], r["cpus"], round(r["uptime_s"] / 3600, 1) if r["uptime_s"] else ""]
            for d in r["disks"] or [{}]:
                w.writerow([_safe(v) for v in base + [d.get("mount"), d.get("total"), d.get("used"), d.get("pct")]])
    elif kind == "backups":
        w.writerow(["host", "name", "state", "finished_at", "age_hours", "message", "size_bytes"])
        for b in report["backups"]:
            w.writerow([_safe(b.get(k)) for k in ("host", "name", "state", "finished_at", "age_hours", "message", "size_bytes")])
    elif kind == "certificates":
        w.writerow(["hostname", "port", "expires_at", "days_left", "issuer", "error", "checked_at"])
        for c in report["certificates"]:
            w.writerow([_safe(c.get(k)) for k in ("hostname", "port", "expires_at", "days_left", "issuer", "error", "checked_at")])
    elif kind == "updates":
        w.writerow(["host", "container", "image", "state", "newer_tag"])
        for u in report["updates"]:
            w.writerow([_safe(u.get(k)) for k in ("host", "container", "image", "state", "newer_tag")])
    else:
        raise ValueError(kind)
    return buf.getvalue()
