"""Turn the latest host snapshots into a graph: hosts -> networks -> containers.

Node ids are stable across refreshes so the UI can keep positions/selection:
    host:<host_id>
    net:<host_id>:<network name>
    ctr:<host_id>:<container name>
"""

from django.utils import timezone

from .models import Host

# Networks every Docker host has; shown only when something is attached to them.
DEFAULT_NETWORKS = {"bridge", "host", "none"}


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
        "info": snap.get("host") or {},
        "counts": {
            "containers": len(containers),
            "running": sum(1 for c in containers if c.get("state") == "running"),
            "networks": len(snap.get("networks") or []),
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
                    "data": {**net, "attached": sum(1 for c in containers for n in c.get("networks") or [] if n["name"] == name)},
                }
            )

        names = {c["name"] for c in containers}
        for c in containers:
            cid = f"ctr:{hid}:{c['name']}"
            nodes.append({"id": cid, "type": "container", "host": host_node_id, "data": c})
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

    return {
        "generated_at": timezone.now().isoformat(),
        "hosts": [n["data"] for n in nodes if n["type"] == "host"],
        "nodes": nodes,
        "edges": edges,
    }
