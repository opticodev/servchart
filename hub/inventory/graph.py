"""Turn the latest host snapshots into a graph: hosts -> networks / stacks -> containers,
plus the links between containers: declared dependencies and observed traffic.

Node ids are stable across refreshes so the UI can keep positions/selection:
    host:<host_id>
    net:<host_id>:<network name>
    stack:<host_id>:<compose project>   (or "~standalone")
    ctr:<host_id>:<container name>
"""

from django.utils import timezone

from .models import Host

# Networks every Docker host has; shown only when something is attached to them.
DEFAULT_NETWORKS = {"bridge", "host", "none"}
# Bucket for containers that weren't started by Docker Compose.
STANDALONE = "~standalone"


def host_summary(host: Host) -> dict:
    snap = host.snapshot or {}
    containers = snap.get("containers") or []
    return {
        "id": f"host:{host.pk}",
        "pk": host.pk,
        "name": host.name,
        "status": host.status,
        "is_local": host.is_local,
        "last_seen": host.last_seen.isoformat() if host.last_seen else None,
        "agent_version": host.agent_version,
        "enabled": host.enabled,
        "token_hint": host.token_hint,
        "created_at": host.created_at.isoformat() if getattr(host, "created_at", None) else None,
        "info": snap.get("host") or {},
        "counts": {
            "containers": len(containers),
            "running": sum(1 for c in containers if c.get("state") == "running"),
            "networks": len(snap.get("networks") or []),
            "stacks": len({(c.get("compose") or {}).get("project") for c in containers} - {None}),
        },
    }


def build_graph(hosts=None) -> dict:
    hosts = list(hosts if hosts is not None else Host.objects.filter(enabled=True))
    nodes, edges = [], []

    for host in hosts:
        hid = host.pk
        host_node_id = f"host:{hid}"
        summary = host_summary(host)
        nodes.append({"id": host_node_id, "type": "host", "host": host_node_id, "data": summary})

        snap = host.snapshot or {}
        containers = snap.get("containers") or []
        networks = {n["name"]: n for n in snap.get("networks") or [] if n.get("name")}
        used_networks = {n["name"] for c in containers for n in c.get("networks") or []}

        for name, net in sorted(networks.items()):
            if name in DEFAULT_NETWORKS and name not in used_networks:
                continue
            if name == "none":
                continue
            nodes.append(
                {
                    "id": f"net:{hid}:{name}",
                    "type": "network",
                    "host": host_node_id,
                    "data": {
                        **net,
                        "attached": sum(1 for c in containers for n in c.get("networks") or [] if n["name"] == name),
                        # which stacks use it: a network used by one stack is drawn inside that stack
                        "stacks": sorted(
                            {
                                f"stack:{hid}:{(c.get('compose') or {}).get('project') or STANDALONE}"
                                for c in containers
                                if any(n["name"] == name for n in c.get("networks") or [])
                            }
                        ),
                    },
                }
            )

        stacks = {}
        for c in containers:
            project = (c.get("compose") or {}).get("project")
            key = project or STANDALONE
            s = stacks.setdefault(
                key,
                {
                    "id": f"stack:{hid}:{key}",
                    "name": project,
                    "standalone": project is None,
                    "working_dir": None,
                    "config_files": [],
                    "containers": [],
                    "running": 0,
                },
            )
            compose = c.get("compose") or {}
            s["working_dir"] = s["working_dir"] or compose.get("working_dir")
            for f in compose.get("config_files") or []:
                if f not in s["config_files"]:
                    s["config_files"].append(f)
            s["containers"].append({"name": c["name"], "service": compose.get("service"), "state": c.get("state"), "health": c.get("health")})
            s["running"] += c.get("state") == "running"
        for key in sorted(stacks, key=lambda k: (k == STANDALONE, k)):
            s = stacks[key]
            s["total"] = len(s["containers"])
            nodes.append({"id": s["id"], "type": "stack", "host": host_node_id, "data": s})

        names = {c["name"] for c in containers}
        for c in containers:
            cid = f"ctr:{hid}:{c['name']}"
            stack_id = f"stack:{hid}:{(c.get('compose') or {}).get('project') or STANDALONE}"
            nodes.append({"id": cid, "type": "container", "host": host_node_id, "stack": stack_id, "data": c})
            mode = c.get("network_mode") or ""
            if mode == "host":
                edges.append({"id": f"{cid}->host", "source": cid, "target": host_node_id, "kind": "host-network"})
            elif mode.startswith("container:"):
                # network namespace shared with another container (identified by name or id)
                other = mode.split(":", 1)[1]
                match = next((o["name"] for o in containers if o["name"] == other or o.get("id", "").startswith(other[:12])), None)
                if match and match in names:
                    edges.append({"id": f"{cid}->ns", "source": cid, "target": f"ctr:{hid}:{match}", "kind": "shared-netns"})
            for n in c.get("networks") or []:
                if n["name"] in networks and n["name"] != "none":
                    edges.append(
                        {
                            "id": f"{cid}->{n['name']}",
                            "source": cid,
                            "target": f"net:{hid}:{n['name']}",
                            "kind": "network",
                            "ip": n.get("ip"),
                        }
                    )

    edges.extend(build_links(hosts, nodes))

    return {
        "generated_at": timezone.now().isoformat(),
        "hosts": [n["data"] for n in nodes if n["type"] == "host"],
        "nodes": nodes,
        "edges": edges,
    }


def _host_ips(hosts) -> dict:
    """ip -> host pk, from what agents report about themselves plus the address they report from.

    An address claimed by more than one host (a reverse proxy, NAT, a shared Docker
    gateway) can't identify a host, so it's ignored.
    """
    claims = {}
    for h in hosts:
        snap = h.snapshot or {}
        ips = set((snap.get("host") or {}).get("ips") or [])
        if snap.get("seen_from"):
            ips.add(snap["seen_from"])
        for ip in ips:
            claims.setdefault(ip, set()).add(h.pk)
    return {ip: next(iter(owners)) for ip, owners in claims.items() if len(owners) == 1}


def build_links(hosts, nodes) -> list[dict]:
    """Edges for how containers talk: "depends" (Compose depends_on) and "flow" (observed TCP)."""
    names = {n["id"]: (n["data"].get("name") or n["id"]) for n in nodes}
    ctr_by_ip, published, by_service = {}, {}, {}
    for h in hosts:
        for c in (h.snapshot or {}).get("containers") or []:
            cid = f"ctr:{h.pk}:{c['name']}"
            for n in c.get("networks") or []:
                if n.get("ip"):
                    ctr_by_ip[(h.pk, n["ip"])] = cid
            for p in c.get("ports") or []:
                if p.get("public"):
                    published.setdefault((h.pk, p["public"]), cid)
            compose = c.get("compose") or {}
            if compose.get("project") and compose.get("service"):
                by_service[(h.pk, compose["project"], compose["service"])] = cid
    host_by_ip = _host_ips(hosts)

    def resolve(hid, ip, port):
        """Destination of a connection made on host `hid` -> (node id, how) or (None, None)."""
        if (hid, ip) in ctr_by_ip:  # container IPs are only meaningful on the same host
            return ctr_by_ip[(hid, ip)], "container"
        target_host = host_by_ip.get(ip)
        if target_host is not None:
            if (target_host, port) in published:
                return published[(target_host, port)], "published-port"
            return f"host:{target_host}", "host"
        return None, None

    edges, flows = [], {}
    for h in hosts:
        snap = h.snapshot or {}
        sources = [(f"ctr:{h.pk}:{c['name']}", c) for c in snap.get("containers") or []]
        for cid, c in sources:
            compose = c.get("compose") or {}
            for dep in compose.get("depends_on") or []:
                target = by_service.get((h.pk, compose.get("project"), dep))
                if target and target != cid:
                    edges.append({"id": f"dep:{cid}->{target}", "source": cid, "target": target, "kind": "depends"})
        conns = [(cid, c.get("connections") or [], c) for cid, c in sources]
        conns.append((f"host:{h.pk}", snap.get("host_connections") or [], None))
        for src, items, rec in conns:
            talks_to, unresolved = [], []
            for item in items:
                target, how = resolve(h.pk, item["ip"], item["port"])
                if not target or target == src:
                    unresolved.append(item)
                    continue
                if src.startswith("host:") and target.startswith(f"ctr:{h.pk}:"):
                    continue  # the host reaching its own containers is Docker port forwarding
                f = flows.setdefault((src, target), {"ports": set(), "count": 0})
                f["ports"].add(item["port"])
                f["count"] += item["count"]
                talks_to.append({"target": target, "name": names.get(target, target), "port": item["port"], "count": item["count"], "via": how})
            if rec is not None:
                rec["talks_to"] = talks_to
                rec["talks_to_unresolved"] = unresolved
            elif items:
                snap.setdefault("host", {})["talks_to"] = talks_to
                snap["host"]["talks_to_unresolved"] = unresolved

    for (src, target), f in sorted(flows.items()):
        src_host, target_host = _node_host(src), _node_host(target)
        edges.append(
            {
                "id": f"flow:{src}->{target}",
                "source": src,
                "target": target,
                "kind": "flow",
                "ports": sorted(f["ports"]),
                "count": f["count"],
                "cross_host": src_host != target_host,
            }
        )
    return edges


def _node_host(node_id: str) -> str:
    kind, rest = node_id.split(":", 1)
    return rest.split(":", 1)[0] if kind == "ctr" else rest
