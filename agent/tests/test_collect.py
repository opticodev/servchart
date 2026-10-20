import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from servchart_agent.collect import REDACTED, collect, container_record, sanitize_labels  # noqa: E402

INSPECT = {
    "Id": "abcdef1234567890",
    "Name": "/vaultwarden",
    "Config": {
        "Image": "vaultwarden/server:latest",
        "Env": ["ADMIN_TOKEN=supersecret", "DATABASE_URL=postgres://u:p@db/x"],
        "Cmd": ["--password", "hunter2"],
        "Labels": {
            "com.docker.compose.project": "vault",
            "com.docker.compose.service": "web",
            "com.docker.compose.project.working_dir": "/opt/stacks/vault",
            "com.docker.compose.project.config_files": "/opt/stacks/vault/compose.yml,/opt/stacks/vault/override.yml",
            "traefik.http.middlewares.auth.basicauth.users": "admin:$apr1$hash",
            "org.opencontainers.image.title": "vaultwarden",
        },
    },
    "State": {"Status": "running", "StartedAt": "2026-10-01T00:00:00Z", "Health": {"Status": "healthy"}},
    "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}, "NetworkMode": "vault_default"},
    "NetworkSettings": {
        "Ports": {
            "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8082"}, {"HostIp": "::", "HostPort": "8082"}],
            "3012/tcp": None,
        },
        "Networks": {"vault_default": {"IPAddress": "172.20.0.2", "Aliases": ["web", "abcdef123456"]}},
    },
    "Mounts": [
        {"Type": "bind", "Source": "/srv/vw/data", "Destination": "/data", "RW": True},
        {"Type": "volume", "Name": "vw_cache", "Source": "/var/lib/docker/volumes/vw_cache/_data",
         "Destination": "/cache", "RW": False},
    ],
}


class FakeClient:
    def info(self):
        return {"Name": "docker-host", "OperatingSystem": "Ubuntu 24.04", "NCPU": 4, "MemTotal": 16 * 2**30}

    def version(self):
        return {"Version": "29.0.0"}

    def containers(self):
        return [{"Id": INSPECT["Id"]}]

    def inspect_container(self, cid):
        return INSPECT

    def networks(self):
        return [{"Id": "n1", "Name": "vault_default", "Driver": "bridge", "Scope": "local",
                 "IPAM": {"Config": [{"Subnet": "172.20.0.0/16"}]}}]


class CollectTests(unittest.TestCase):
    def test_no_env_or_command_leaks(self):
        blob = json.dumps(collect(FakeClient()))
        for secret in ("supersecret", "postgres://", "hunter2", "$apr1$hash"):
            self.assertNotIn(secret, blob)

    def test_secretish_labels_redacted(self):
        labels = sanitize_labels({"x.password": "a", "x.title": "b", "API_TOKEN": "c"})
        self.assertEqual(labels, {"x.password": REDACTED, "x.title": "b", "API_TOKEN": REDACTED})

    def test_record_shape(self):
        rec = container_record(INSPECT)
        self.assertEqual(rec["name"], "vaultwarden")
        self.assertEqual(rec["compose"]["project"], "vault")
        self.assertEqual(rec["compose"]["working_dir"], "/opt/stacks/vault")
        self.assertEqual(rec["compose"]["config_files"], ["/opt/stacks/vault/compose.yml", "/opt/stacks/vault/override.yml"])
        self.assertEqual(rec["health"], "healthy")
        # IPv4 + IPv6 bindings of the same port merge into one entry; unpublished port kept
        self.assertEqual([(p["private"], p["public"]) for p in rec["ports"]], [(80, 8082), (3012, None)])
        self.assertEqual(rec["ports"][0]["ips"], ["0.0.0.0", "::"])
        self.assertEqual(rec["networks"][0]["aliases"], ["web"])
        self.assertEqual(rec["mounts"][1]["source"], "vw_cache")

    def test_hide_paths(self):
        rec = container_record(INSPECT, hide_paths=True)
        self.assertIsNone(rec["mounts"][0]["source"])
        self.assertEqual(rec["mounts"][1]["source"], "vw_cache")
        self.assertIsNone(rec["compose"]["working_dir"])
        self.assertEqual(rec["compose"]["config_files"], [])
        self.assertEqual(rec["compose"]["project"], "vault")

    def test_snapshot_header(self):
        snap = collect(FakeClient(), hostname="override")
        self.assertEqual(snap["schema"], 1)
        self.assertEqual(snap["host"]["hostname"], "override")
        self.assertEqual(snap["networks"][0]["subnets"], ["172.20.0.0/16"])


if __name__ == "__main__":
    unittest.main()


class StatsClient(FakeClient):
    def inspect_container(self, cid):
        doc = json.loads(json.dumps(INSPECT))
        doc["Image"] = "sha256:" + "b" * 64
        doc["State"]["Running"] = True
        return doc

    def get(self, path):
        if path.startswith("/images/"):
            return {"RepoDigests": ["vaultwarden/server@sha256:" + "a" * 64]}
        if "/stats" in path:
            return {"cpu_stats": {"cpu_usage": {"total_usage": 1}, "system_cpu_usage": 10, "online_cpus": 1},
                    "memory_stats": {"usage": 2048, "limit": 4096, "stats": {}}}
        raise RuntimeError(path)


class CollectV04Tests(unittest.TestCase):
    def test_health_stats_and_digests(self):
        with mock.patch.dict(os.environ, {"SERVCHART_STATUS_DIR": "/nonexistent"}):
            snap = collect(StatsClient())
        self.assertIn("mem_total", snap["host"]["health"])
        self.assertIn(snap["host"]["health"]["disk_source"], ("host", "docker", "none"))
        c = snap["containers"][0]
        self.assertEqual(c["image_digests"], ["vaultwarden/server@sha256:" + "a" * 64])
        self.assertEqual(c["stats"]["mem_used"], 2048)
        self.assertNotIn("backups", snap)

    def test_health_can_be_turned_off(self):
        with mock.patch.dict(os.environ, {"SERVCHART_HEALTH": "0", "SERVCHART_STATS": "0"}):
            snap = collect(StatsClient())
        self.assertNotIn("health", snap["host"])
        self.assertNotIn("stats", snap["containers"][0])
