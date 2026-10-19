"""Generate the fictional demo hosts in sample-data/. Nothing here describes a real system."""
import json
import zlib
from pathlib import Path

OUT = Path(__file__).parent / "sample-data"


def ctr(name, image, project=None, service=None, nets=(), ports=(), state="running", health=None, mode=None, mounts=()):
    return {
        "id": f"{zlib.crc32(name.encode()):012x}",
        "name": name, "image": image, "state": state, "health": health,
        "started_at": "2026-10-01T08:00:00Z", "restart_policy": "unless-stopped",
        "network_mode": mode or (nets[0] if nets else "bridge"),
        "compose": {"project": project, "service": service,
                    "working_dir": f"/opt/stacks/{project}" if project else None,
                    "config_files": [f"/opt/stacks/{project}/compose.yml"] if project else []},
        "labels": {"com.docker.compose.project": project, "com.docker.compose.service": service} if project else {},
        "networks": [{"name": n, "ip": f"172.{20 + i}.0.{(zlib.crc32(name.encode()) % 200) + 2}", "aliases": [service] if service else []} for i, n in enumerate(nets)],
        "ports": [{"private": p, "protocol": "tcp", "public": q, "ips": ["0.0.0.0"] if q else []} for p, q in ports],
        "mounts": [{"type": t, "source": s, "destination": d, "rw": True} for t, s, d in mounts],
    }


def net(name, subnet, internal=False):
    return {"id": name[:12], "name": name, "driver": "bridge", "scope": "local", "internal": internal, "subnets": [subnet]}


def host(hostname, os_, cpus, mem_gb, containers, networks):
    return {
        "schema": 1, "agent_version": "0.1.0", "collected_at": "2026-10-19T12:00:00+00:00",
        "host": {"hostname": hostname, "os": os_, "kernel": "6.8.0", "arch": "x86_64", "cpus": cpus,
                 "memory_bytes": mem_gb * 2**30, "docker_version": "27.3.1"},
        "containers": containers, "networks": networks,
    }


edge = host("edge-01", "Debian GNU/Linux 12", 4, 8, [
    ctr("traefik", "traefik:v3.1", "proxy", "traefik", ["proxy"], [(80, 80), (443, 443)], mounts=[("bind", "/srv/traefik", "/etc/traefik")]),
    ctr("authelia", "authelia/authelia:4.38", "proxy", "authelia", ["proxy", "auth_internal"], health="healthy"),
    ctr("authelia-redis", "redis:7-alpine", "proxy", "redis", ["auth_internal"]),
    ctr("cloudflared", "cloudflare/cloudflared:latest", "tunnel", "cloudflared", ["proxy"]),
    ctr("uptime-kuma", "louislam/uptime-kuma:1", "monitoring", "kuma", ["proxy"], [(3001, None)], health="healthy"),
    ctr("node-exporter", "prom/node-exporter:v1.8.2", "monitoring", "node-exporter", mode="host"),
], [net("bridge", "172.17.0.0/16"), net("host", ""), net("proxy", "172.20.0.0/16"), net("auth_internal", "172.21.0.0/16", True)])

apps = host("apps-01", "Ubuntu 24.04.1 LTS", 8, 32, [
    ctr("nextcloud-app", "nextcloud:29-apache", "nextcloud", "app", ["nextcloud_default"], [(80, 8080)], mounts=[("volume", "nextcloud_data", "/var/www/html")]),
    ctr("nextcloud-db", "postgres:16", "nextcloud", "db", ["nextcloud_default"], mounts=[("volume", "nextcloud_db", "/var/lib/postgresql/data")], health="healthy"),
    ctr("nextcloud-redis", "redis:7-alpine", "nextcloud", "redis", ["nextcloud_default"]),
    ctr("gitea", "gitea/gitea:1.22", "git", "server", ["git_default"], [(3000, 3000), (22, 2222)]),
    ctr("gitea-db", "postgres:16", "git", "db", ["git_default"], health="healthy"),
    ctr("gitea-runner", "gitea/act_runner:0.2", "git", "runner", ["git_default"], state="exited"),
    ctr("vaultwarden", "vaultwarden/server:1.32", "vault", "web", ["vault_default"], [(80, 8082)], health="healthy"),
    ctr("backup", "kopia/kopia:0.17", None, None, ["bridge"], [(51515, 51515)]),
    ctr("watchtower", "containrrr/watchtower:latest", None, None, ["bridge"], health="unhealthy"),
], [net("bridge", "172.17.0.0/16"), net("nextcloud_default", "172.22.0.0/16"), net("git_default", "172.23.0.0/16"), net("vault_default", "172.24.0.0/16")])

nas = host("media-nas", "Ubuntu 22.04.5 LTS", 4, 16, [
    ctr("jellyfin", "jellyfin/jellyfin:10.9", "media", "jellyfin", mode="host", mounts=[("bind", "/mnt/media", "/media")]),
    ctr("sonarr", "lscr.io/linuxserver/sonarr:latest", "media", "sonarr", ["media_default"], [(8989, 8989)]),
    ctr("radarr", "lscr.io/linuxserver/radarr:latest", "media", "radarr", ["media_default"], [(7878, 7878)]),
    ctr("qbittorrent", "lscr.io/linuxserver/qbittorrent:latest", "media", "qbittorrent", ["media_default"], [(8081, 8081)]),
    ctr("samba", "dperson/samba:latest", None, None, mode="host"),
], [net("bridge", "172.17.0.0/16"), net("host", ""), net("media_default", "172.25.0.0/16")])

OUT.mkdir(exist_ok=True)
for h in (edge, apps, nas):
    (OUT / f"{h['host']['hostname']}.json").write_text(json.dumps(h, indent=2) + "\n")
    print("wrote", h["host"]["hostname"], len(h["containers"]))
