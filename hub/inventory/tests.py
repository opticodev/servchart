import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from .graph import build_graph
from .models import Host

REPORT = {
    "schema": 1,
    "agent_version": "0.1.0",
    "collected_at": "2026-10-19T00:00:00+00:00",
    "host": {"hostname": "box", "os": "Debian", "secret_field": "nope"},
    "containers": [
        {
            "id": "abc",
            "name": "web",
            "image": "nginx",
            "state": "running",
            "network_mode": "app_default",
            "env": ["PASSWORD=leak"],
            "labels": {"com.example.api_token": "leak2", "title": "web"},
            "compose": {"project": "app", "service": "web", "working_dir": "/srv/app", "config_files": ["/srv/app/compose.yml"]},
            "networks": [{"name": "app_default", "ip": "172.18.0.2", "aliases": ["web"]}],
            "ports": [{"private": 80, "protocol": "tcp", "public": 8080, "ips": ["0.0.0.0"]}],
            "mounts": [],
        },
        {"id": "def", "name": "netdata", "state": "running", "network_mode": "host", "networks": []},
        {"id": "ghi", "name": "sidecar", "state": "exited", "network_mode": "container:web", "networks": []},
    ],
    "networks": [
        {"name": "app_default", "driver": "bridge"},
        {"name": "bridge", "driver": "bridge"},
        {"name": "none", "driver": "null"},
    ],
}


class ReportApiTests(TestCase):
    def setUp(self):
        self.host, self.token = Host.create_with_token("box")

    def post(self, body, token=None):
        return self.client.post(
            "/api/v1/report",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token or self.token}",
        )

    def test_report_stored_and_sanitized(self):
        resp = self.post(REPORT)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.host.refresh_from_db()
        blob = json.dumps(self.host.snapshot)
        self.assertNotIn("leak", blob)
        self.assertNotIn("secret_field", blob)
        self.assertEqual(self.host.status, "online")
        self.assertEqual(self.host.agent_version, "0.1.0")

    def test_bad_token_rejected(self):
        self.assertEqual(self.post(REPORT, token="sc_wrong").status_code, 401)

    def test_disabled_host_rejected(self):
        self.host.enabled = False
        self.host.save()
        self.assertEqual(self.post(REPORT).status_code, 401)

    def test_unknown_schema_rejected(self):
        self.assertEqual(self.post({**REPORT, "schema": 99}).status_code, 400)

    def test_token_not_stored_in_plaintext(self):
        self.assertNotIn(self.token, json.dumps(list(Host.objects.values()), default=str))

    def test_agent_token_cannot_read_graph(self):
        resp = self.client.get("/api/v1/graph", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertIn(resp.status_code, (401, 403))


class UiApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("admin", "", "pw-admin-123")
        self.viewer = User.objects.create_user("viewer", "", "pw-viewer-123")

    def test_graph_requires_login(self):
        self.assertIn(self.client.get("/api/v1/graph").status_code, (401, 403))

    def test_spa_redirects_to_login(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_admin_adds_host_and_gets_command(self):
        self.client.force_login(self.admin)
        resp = self.client.post("/api/v1/hosts", {"name": "nas"}, content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertTrue(body["token"].startswith("sc_"))
        self.assertIn(body["token"], body["install_command"])
        self.assertIn("docker.sock", body["install_command"])

    def test_viewer_cannot_add_host(self):
        self.client.force_login(self.viewer)
        resp = self.client.post("/api/v1/hosts", {"name": "nas"}, content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    def test_rotate_token_invalidates_old(self):
        host, old = Host.create_with_token("nas")
        self.client.force_login(self.admin)
        new = self.client.post(f"/api/v1/hosts/{host.pk}/rotate-token").json()["token"]
        self.client.logout()
        auth = lambda t: {"HTTP_AUTHORIZATION": f"Bearer {t}"}  # noqa: E731
        body = json.dumps(REPORT)
        self.assertEqual(self.client.post("/api/v1/report", body, "application/json", **auth(old)).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/report", body, "application/json", **auth(new)).status_code, 200)


class GraphTests(TestCase):
    def test_graph_shape(self):
        host, _ = Host.create_with_token("box")
        from .validation import clean_report

        host.snapshot = clean_report(REPORT)
        host.save()
        g = build_graph()
        ids = {n["id"] for n in g["nodes"]}
        hid = host.pk
        self.assertIn(f"host:{hid}", ids)
        self.assertIn(f"net:{hid}:app_default", ids)
        self.assertNotIn(f"net:{hid}:bridge", ids)  # unused default network hidden
        self.assertNotIn(f"net:{hid}:none", ids)
        kinds = {(e["source"], e["kind"]) for e in g["edges"]}
        self.assertIn((f"ctr:{hid}:web", "network"), kinds)
        self.assertIn((f"ctr:{hid}:netdata", "host-network"), kinds)
        self.assertIn((f"ctr:{hid}:sidecar", "shared-netns"), kinds)
        self.assertEqual(g["hosts"][0]["counts"], {"containers": 3, "running": 2, "networks": 3, "stacks": 1})
        stacks = {n["id"]: n["data"] for n in g["nodes"] if n["type"] == "stack"}
        app = stacks[f"stack:{hid}:app"]
        self.assertEqual((app["working_dir"], app["config_files"], app["total"], app["running"]), ("/srv/app", ["/srv/app/compose.yml"], 1, 1))
        self.assertEqual(stacks[f"stack:{hid}:~standalone"]["total"], 2)
        web = next(n for n in g["nodes"] if n["id"] == f"ctr:{hid}:web")
        self.assertEqual(web["stack"], f"stack:{hid}:app")
