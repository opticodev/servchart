import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

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
        self.assertIn("SERVCHART_OBSERVE_CONNECTIONS=1", body["install_command"])

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


class LinkTests(TestCase):
    """Dependencies and observed traffic, on one host and across hosts."""

    def setUp(self):
        from .validation import clean_report

        def ctr(name, project, service, ip, net, ports=(), depends=(), conns=()):
            return {
                "name": name,
                "state": "running",
                "compose": {"project": project, "service": service, "depends_on": list(depends)},
                "networks": [{"name": net, "ip": ip}],
                "ports": [{"private": p, "public": q, "protocol": "tcp", "ips": ["0.0.0.0"]} for p, q in ports],
                "connections": [{"ip": i, "port": p, "count": n} for i, p, n in conns],
            }

        app = {
            "schema": 1,
            "host": {"hostname": "apps", "ips": ["192.168.0.28"], "observe": "on"},
            "networks": [{"name": "erp_default"}],
            "containers": [
                ctr("erp-backend", "erp", "backend", "172.18.0.2", "erp_default", depends=["db", "redis"],
                    conns=[("172.18.0.3", 3306, 4), ("172.18.0.4", 6379, 2), ("10.9.9.9", 5432, 1)]),
                ctr("erp-db", "erp", "db", "172.18.0.3", "erp_default"),
                ctr("erp-redis", "erp", "redis", "172.18.0.4", "erp_default"),
                ctr("erp-frontend", "erp", "frontend", "172.18.0.5", "erp_default", ports=[(8080, 8082)]),
            ],
        }
        edge = {
            "schema": 1,
            "host": {"hostname": "edge", "ips": ["192.168.0.15"], "observe": "on"},
            "networks": [{"name": "mon"}],
            "containers": [ctr("uptime", "mon", "kuma", "172.18.0.2", "mon", conns=[("192.168.0.28", 8082, 1)])],
            # nginx on the edge host itself proxying to the app host, plus Docker forwarding noise
            "host_connections": [{"ip": "192.168.0.28", "port": 8082, "count": 3}, {"ip": "172.18.0.2", "port": 3001, "count": 1}],
        }
        self.apps, _ = Host.create_with_token("apps")
        self.edge, _ = Host.create_with_token("edge")
        for h, snap in ((self.apps, app), (self.edge, edge)):
            h.snapshot = clean_report(snap)
            h.save()

    def edges(self, kind):
        return {(e["source"], e["target"]): e for e in build_graph()["edges"] if e["kind"] == kind}

    def test_depends_on(self):
        a = self.apps.pk
        deps = self.edges("depends")
        self.assertEqual(set(deps), {(f"ctr:{a}:erp-backend", f"ctr:{a}:erp-db"), (f"ctr:{a}:erp-backend", f"ctr:{a}:erp-redis")})

    def test_flows_same_host_and_cross_host(self):
        a, e = self.apps.pk, self.edge.pk
        flows = self.edges("flow")
        db = flows[(f"ctr:{a}:erp-backend", f"ctr:{a}:erp-db")]
        self.assertEqual((db["ports"], db["count"], db["cross_host"]), ([3306], 4, False))
        # container on edge -> published port on apps
        cross = flows[(f"ctr:{e}:uptime", f"ctr:{a}:erp-frontend")]
        self.assertTrue(cross["cross_host"])
        # host-level process on edge (nginx) -> apps' published port
        self.assertIn((f"host:{e}", f"ctr:{a}:erp-frontend"), flows)
        # edge host -> its own container is port forwarding, not a link
        self.assertNotIn((f"host:{e}", f"ctr:{e}:uptime"), flows)
        # container IPs never match across hosts (172.18.0.2 exists on both)
        self.assertFalse(any(src.startswith(f"host:{e}") and tgt == f"ctr:{a}:erp-backend" for src, tgt in flows))

    def test_unresolved_kept_for_details(self):
        a = self.apps.pk
        node = next(n for n in build_graph()["nodes"] if n["id"] == f"ctr:{a}:erp-backend")
        self.assertEqual(node["data"]["talks_to_unresolved"], [{"ip": "10.9.9.9", "port": 5432, "count": 1}])
        self.assertEqual({t["name"] for t in node["data"]["talks_to"]}, {"erp-db", "erp-redis"})

    def test_network_knows_its_stacks(self):
        a = self.apps.pk
        net = next(n for n in build_graph()["nodes"] if n["id"] == f"net:{a}:erp_default")
        self.assertEqual(net["data"]["stacks"], [f"stack:{a}:erp"])

    def test_report_records_source_address(self):
        _, token = Host.create_with_token("nas")
        resp = self.client.post("/api/v1/report", json.dumps(REPORT), "application/json",
                                HTTP_AUTHORIZATION=f"Bearer {token}", REMOTE_ADDR="192.168.0.40")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Host.objects.get(name="nas").snapshot["seen_from"], "192.168.0.40")


class SettingsApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("admin", "", "pw-admin-123")
        self.viewer = User.objects.create_user("viewer", "", "pw-viewer-123")
        self.host, _ = Host.create_with_token("nas")

    def api(self, method, url, body=None, user=None):
        self.client.force_login(user or self.admin)
        if method == "get":
            return self.client.get(url)
        return getattr(self.client, method)(url, json.dumps(body or {}), content_type="application/json")

    def test_rename_and_disable_host(self):
        r = self.api("patch", f"/api/v1/hosts/{self.host.pk}", {"name": "nas-01", "enabled": False})
        self.assertEqual(r.status_code, 200, r.content)
        self.host.refresh_from_db()
        self.assertEqual((self.host.name, self.host.enabled), ("nas-01", False))

    def test_rename_conflict(self):
        Host.create_with_token("other")
        self.assertEqual(self.api("patch", f"/api/v1/hosts/{self.host.pk}", {"name": "other"}).status_code, 400)

    def test_delete_host_but_not_local(self):
        local = Host.objects.create(name="hub", is_local=True, token_hash="x" * 64, token_hint="local")
        self.assertEqual(self.api("delete", f"/api/v1/hosts/{local.pk}").status_code, 400)
        self.assertEqual(self.api("delete", f"/api/v1/hosts/{self.host.pk}").status_code, 204)
        self.assertFalse(Host.objects.filter(pk=self.host.pk).exists())

    def test_viewer_cannot_manage(self):
        for method, url in (("patch", f"/api/v1/hosts/{self.host.pk}"), ("get", "/api/v1/users"), ("post", "/api/v1/users"),
                            ("delete", f"/api/v1/users/{self.admin.pk}")):
            self.assertEqual(self.api(method, url, {"name": "x"}, user=self.viewer).status_code, 403, (method, url))

    def test_create_user_with_generated_password(self):
        r = self.api("post", "/api/v1/users", {"username": "alice", "is_staff": True})
        self.assertEqual(r.status_code, 201, r.content)
        pw = r.json()["password"]
        self.client.logout()
        self.assertTrue(self.client.login(username="alice", password=pw))
        self.assertTrue(get_user_model().objects.get(username="alice").is_staff)

    def test_weak_password_rejected(self):
        self.assertEqual(self.api("post", "/api/v1/users", {"username": "bob", "password": "123"}).status_code, 400)

    def test_lockout_guards(self):
        me = f"/api/v1/users/{self.admin.pk}"
        self.assertEqual(self.api("patch", me, {"is_staff": False}).status_code, 400)
        self.assertEqual(self.api("patch", me, {"is_active": False}).status_code, 400)
        self.assertEqual(self.api("delete", me).status_code, 400)

    def test_promote_and_reset_password(self):
        r = self.api("patch", f"/api/v1/users/{self.viewer.pk}", {"is_staff": True})
        self.assertTrue(r.json()["is_staff"])
        pw = self.api("post", f"/api/v1/users/{self.viewer.pk}/reset-password").json()["password"]
        self.client.logout()
        self.assertTrue(self.client.login(username="viewer", password=pw))

    def test_change_my_password_keeps_session(self):
        r = self.api("post", "/api/v1/me/password", {"current_password": "pw-viewer-123", "new_password": "a-much-better-pass-42"}, user=self.viewer)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.client.get("/api/v1/me").status_code, 200)  # still signed in
        self.viewer.refresh_from_db()  # force_login with the stale object would carry the old password hash
        bad = self.api("post", "/api/v1/me/password", {"current_password": "wrong", "new_password": "another-good-pass-43"}, user=self.viewer)
        self.assertEqual(bad.status_code, 400)


HEADER_SSO = dict(
    SERVCHART_SSO_HEADER="X-authentik-username",
    SERVCHART_SSO_EMAIL_HEADER="X-authentik-email",
    SERVCHART_SSO_GROUPS_HEADER="X-authentik-groups",
    SERVCHART_SSO_TRUSTED_PROXIES=["192.168.0.15"],
    SERVCHART_SSO_ADMIN_GROUPS=["servchart-admins"],
    SERVCHART_SSO_LOGOUT_URL="/outpost.goauthentik.io/sign_out",
)


@override_settings(**HEADER_SSO)
class HeaderSsoTests(TestCase):
    PROXY = {"REMOTE_ADDR": "192.168.0.15"}

    def get(self, path="/api/v1/me", user="mawaki", groups="", **extra):
        headers = {"HTTP_X_AUTHENTIK_USERNAME": user, "HTTP_X_AUTHENTIK_GROUPS": groups, "HTTP_X_AUTHENTIK_EMAIL": f"{user}@example.com"}
        headers.update(extra)
        return self.client.get(path, **headers)

    def test_signs_in_and_creates_user_from_trusted_proxy(self):
        r = self.get(**self.PROXY)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual((body["username"], body["is_staff"], body["sso_user"], body["sso_enabled"]), ("mawaki", False, True, True))
        u = get_user_model().objects.get(username="mawaki")
        self.assertFalse(u.has_usable_password())
        self.assertEqual(u.email, "mawaki@example.com")

    def test_admin_group_follows_identity_provider(self):
        self.assertTrue(self.get(groups="users|servchart-admins", **self.PROXY).json()["is_staff"])
        self.assertFalse(self.get(groups="users", **self.PROXY).json()["is_staff"])

    def test_header_ignored_from_untrusted_address(self):
        r = self.get(REMOTE_ADDR="192.168.0.99")
        self.assertIn(r.status_code, (401, 403))
        self.assertFalse(get_user_model().objects.filter(username="mawaki").exists())

    def test_header_ignored_on_agent_endpoint(self):
        self.client.post("/api/v1/report", "{}", "application/json", HTTP_X_AUTHENTIK_USERNAME="admin", **self.PROXY)
        self.assertFalse(get_user_model().objects.filter(username="admin").exists())
        self.assertNotIn("sessionid", self.client.cookies)

    def test_switching_identity_logs_previous_user_out(self):
        self.assertEqual(self.get(user="alice", **self.PROXY).json()["username"], "alice")
        self.assertEqual(self.get(user="bob", **self.PROXY).json()["username"], "bob")

    def test_local_admin_rights_not_touched_by_groups(self):
        get_user_model().objects.create_superuser("mawaki", "", "local-pass-123")
        self.assertTrue(self.get(groups="users", **self.PROXY).json()["is_staff"])

    def test_no_auto_create_when_disabled(self):
        with self.settings(SERVCHART_SSO_CREATE_USERS=False):
            self.assertIn(self.get(**self.PROXY).status_code, (401, 403))

    def test_sso_user_cannot_set_password_here(self):
        self.get(**self.PROXY)
        r = self.client.post("/api/v1/me/password", json.dumps({"current_password": "", "new_password": "whatever-123-abc"}),
                             content_type="application/json", HTTP_X_AUTHENTIK_USERNAME="mawaki", **self.PROXY)
        self.assertEqual(r.status_code, 400)

    def test_logout_goes_to_proxy_sign_out(self):
        self.get(**self.PROXY)
        r = self.client.post("/logout/")
        self.assertEqual(r["Location"], "/outpost.goauthentik.io/sign_out")


@override_settings(SERVCHART_SSO_HEADER="Remote-User", SERVCHART_SSO_GROUPS_HEADER="Remote-Groups",
                   SERVCHART_SSO_TRUSTED_PROXIES=["10.0.0.0/24"], SERVCHART_SSO_ADMIN_GROUPS=["admins"])
class HeaderSsoOtherProviderTests(TestCase):
    """Nothing is specific to one vendor: Authelia-style headers and a CIDR work the same way."""

    def test_authelia_style_headers(self):
        r = self.client.get("/api/v1/me", HTTP_REMOTE_USER="jane", HTTP_REMOTE_GROUPS="admins,dev", REMOTE_ADDR="10.0.0.7")
        self.assertEqual((r.json()["username"], r.json()["is_staff"]), ("jane", True))

    def test_sso_off_without_trusted_proxies(self):
        with self.settings(SERVCHART_SSO_TRUSTED_PROXIES=[]):
            r = self.client.get("/api/v1/me", HTTP_REMOTE_USER="jane", REMOTE_ADDR="10.0.0.7")
            self.assertIn(r.status_code, (401, 403))


OIDC = dict(
    SERVCHART_OIDC_ISSUER="https://idp.example.com/application/o/servchart",
    SERVCHART_OIDC_CLIENT_ID="servchart",
    SERVCHART_OIDC_CLIENT_SECRET="s3cret",
    SERVCHART_OIDC_PROVIDER_NAME="Example IdP",
    SERVCHART_PUBLIC_URL="https://sc.example.com",
    SERVCHART_SSO_ADMIN_GROUPS=["servchart-admins"],
)


@override_settings(**OIDC)
class OidcTests(TestCase):
    """The full authorization-code flow against a fake provider."""

    ISSUER = OIDC["SERVCHART_OIDC_ISSUER"]

    def setUp(self):
        from unittest import mock

        from . import oidc

        oidc._discovery_cache.clear()
        self.calls = []
        self.claims = {"preferred_username": "jane", "email": "jane@example.com", "groups": ["servchart-admins"], "sub": "u-1"}
        self.patch = mock.patch.object(oidc, "http_json", side_effect=self.fake_provider)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def fake_provider(self, url, data=None, headers=None):
        import base64
        import hashlib
        import time

        self.calls.append((url, data, headers))
        if url.endswith("/.well-known/openid-configuration"):
            return {
                "issuer": self.ISSUER + "/",
                "authorization_endpoint": "https://idp.example.com/authorize",
                "token_endpoint": "https://idp.example.com/token",
                "userinfo_endpoint": "https://idp.example.com/userinfo",
                "end_session_endpoint": "https://idp.example.com/end-session",
            }
        if url.endswith("/token"):
            # PKCE: the verifier must hash to the challenge we sent
            challenge = base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest()).rstrip(b"=").decode()
            assert challenge == self.challenge, "PKCE mismatch"
            assert data["redirect_uri"] == "https://sc.example.com/auth/oidc/callback"
            payload = {"iss": self.ISSUER, "aud": "servchart", "exp": time.time() + 300, "nonce": self.nonce, "sub": "u-1", **self.id_token_overrides}
            enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
            return {"id_token": f"{enc({'alg': 'RS256'})}.{enc(payload)}.sig", "access_token": "at"}
        if url.endswith("/userinfo"):
            return self.claims
        raise AssertionError(url)

    def start(self, next_url="/"):
        from urllib.parse import parse_qs, urlparse

        r = self.client.get(f"/auth/oidc/login?next={next_url}")
        self.assertEqual(r.status_code, 302, r.content)
        q = parse_qs(urlparse(r["Location"]).query)
        self.assertEqual(q["client_id"], ["servchart"])
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.state, self.nonce, self.challenge = q["state"][0], q["nonce"][0], q["code_challenge"][0]
        self.id_token_overrides = {}

    def test_login_page_shows_button(self):
        r = self.client.get("/login/")
        self.assertContains(r, "Sign in with Example IdP")
        self.assertContains(r, 'name="password"')  # password login still available by default

    def test_full_flow_creates_admin_and_redirects(self):
        self.start("/somewhere")
        r = self.client.get(f"/auth/oidc/callback?code=abc&state={self.state}")
        self.assertEqual((r.status_code, r["Location"]), (302, "/somewhere"))
        me = self.client.get("/api/v1/me").json()
        self.assertEqual((me["username"], me["is_staff"], me["sso_user"]), ("jane", True, True))
        token_call = next(c for c in self.calls if c[0].endswith("/token"))
        self.assertTrue(token_call[2]["Authorization"].startswith("Basic "))  # client_secret_basic

    def test_wrong_state_rejected(self):
        self.start()
        r = self.client.get("/auth/oidc/callback?code=abc&state=forged")
        self.assertEqual(r.status_code, 400)
        self.assertIn(self.client.get("/api/v1/me").status_code, (401, 403))

    def test_bad_tokens_rejected(self):
        for overrides in ({"nonce": "other"}, {"aud": "someone-else"}, {"iss": "https://evil.example.com"}, {"exp": 1}):
            self.start()
            self.id_token_overrides = overrides
            r = self.client.get(f"/auth/oidc/callback?code=abc&state={self.state}")
            self.assertEqual(r.status_code, 502, overrides)
            self.assertIn(self.client.get("/api/v1/me").status_code, (401, 403), overrides)

    def test_open_redirect_blocked(self):
        self.start("https://evil.example.com/")
        r = self.client.get(f"/auth/oidc/callback?code=abc&state={self.state}")
        self.assertEqual(r["Location"], "/")

    def test_logout_ends_provider_session(self):
        self.start()
        self.client.get(f"/auth/oidc/callback?code=abc&state={self.state}")
        r = self.client.post("/logout/")
        self.assertTrue(r["Location"].startswith("https://idp.example.com/end-session?"))
        self.assertIn("id_token_hint=", r["Location"])

    def test_password_form_can_be_hidden(self):
        with self.settings(SERVCHART_PASSWORD_LOGIN=False):
            self.assertNotContains(self.client.get("/login/"), 'name="password"')
            self.assertContains(self.client.get("/login/?local=1"), 'name="password"')

    def test_http_issuer_refused(self):
        from . import oidc

        self.patch.stop()
        with self.settings(SERVCHART_OIDC_ISSUER="http://idp.example.com"):
            with self.assertRaises(oidc.OIDCError):
                oidc.http_json("http://idp.example.com/.well-known/openid-configuration")
        self.patch.start()


# --- v0.3: logs, branding, reports, activity log -------------------------------------------

import copy  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from django.core import mail  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.utils import timezone  # noqa: E402

from .models import AuditEvent, LogRequest  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _logs_report(on=True):
    r = copy.deepcopy(REPORT)
    r["host"]["logs"] = "on" if on else "off"
    return r


class AdminClientMixin:
    def make_users(self):
        User = get_user_model()
        self.admin = User.objects.create_user("admin", password="x-Strong-pass-1", is_staff=True)
        self.viewer = User.objects.create_user("viewer", password="x-Strong-pass-1")

    def as_admin(self):
        self.client.force_login(self.admin)

    def as_viewer(self):
        self.client.force_login(self.viewer)


class LogsRelayTests(AdminClientMixin, TestCase):
    def setUp(self):
        self.make_users()
        self.host, self.token = Host.create_with_token("box")
        self.agent_post("/api/v1/report", _logs_report())

    def agent_post(self, path, body):
        return self.client.post(path, data=json.dumps(body), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def agent_get(self, path):
        return self.client.get(path, HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def ask(self, container="web", **extra):
        return self.client.post(f"/api/v1/hosts/{self.host.pk}/logs", data=json.dumps({"container": container, "tail": 50, **extra}), content_type="application/json")

    def test_admin_only(self):
        self.as_viewer()
        self.assertEqual(self.ask().status_code, 403)

    def test_full_round_trip_and_result_read_once(self):
        self.as_admin()
        resp = self.ask()
        self.assertEqual(resp.status_code, 202, resp.content)
        req_id = resp.json()["id"]
        self.assertEqual(self.client.get(f"/api/v1/logs/{req_id}").json()["status"], "pending")

        self.client.logout()
        cmds = self.agent_get("/api/v1/agent/commands").json()["commands"]
        self.assertEqual([c["container"] for c in cmds], ["web"])
        self.assertEqual(self.agent_get("/api/v1/agent/commands").json()["commands"], [])  # handed out once
        body = {"ok": True, "result": {"lines": [{"t": "2026", "s": "err", "m": "boom"}, {"x": 1}, "junk"], "truncated": False}}
        self.assertEqual(self.agent_post(f"/api/v1/agent/commands/{req_id}/result", body).status_code, 200)

        self.as_admin()
        done = self.client.get(f"/api/v1/logs/{req_id}").json()
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["lines"][0], {"t": "2026", "s": "err", "m": "boom"})
        self.assertEqual(self.client.get(f"/api/v1/logs/{req_id}").status_code, 404)  # gone once read
        self.assertTrue(AuditEvent.objects.filter(action="logs.view", target="box/web", username="admin").exists())

    def test_unknown_container_and_logs_off(self):
        self.as_admin()
        self.assertEqual(self.ask("../../etc").status_code, 404)
        self.agent_post("/api/v1/report", _logs_report(on=False))
        resp = self.ask()
        self.assertEqual(resp.status_code, 400)
        self.assertIn("SERVCHART_ALLOW_LOGS", resp.json()["error"])

    def test_other_host_cannot_answer(self):
        self.as_admin()
        req_id = self.ask().json()["id"]
        _, other_token = Host.create_with_token("other")
        resp = self.client.post(f"/api/v1/agent/commands/{req_id}/result", data=json.dumps({"ok": True, "result": {}}),
                                content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {other_token}")
        self.assertEqual(resp.status_code, 404)

    def test_timeout_explains(self):
        self.as_admin()
        req_id = self.ask().json()["id"]
        LogRequest.objects.filter(pk=req_id).update(created_at=timezone.now() - timedelta(seconds=40))
        out = self.client.get(f"/api/v1/logs/{req_id}").json()
        self.assertEqual(out["status"], "error")
        self.assertIn("didn't answer", out["error"])

    def test_users_cannot_use_agent_endpoints(self):
        self.as_admin()
        self.assertIn(self.client.get("/api/v1/agent/commands").status_code, (401, 403))

    def test_validation_keeps_logs_flag_and_restart_count(self):
        r = _logs_report()
        r["containers"][0]["restart_count"] = 3
        self.agent_post("/api/v1/report", r)
        self.host.refresh_from_db()
        self.assertEqual(self.host.snapshot["host"]["logs"], "on")
        self.assertEqual(self.host.snapshot["containers"][0]["restart_count"], 3)


class BrandingTests(AdminClientMixin, TestCase):
    def setUp(self):
        self.make_users()

    def test_public_get_and_admin_patch(self):
        self.assertEqual(self.client.get("/api/v1/branding").json()["app_name"], "ServChart")
        self.as_viewer()
        self.assertEqual(self.client.patch("/api/v1/branding", data=json.dumps({"app_name": "X"}), content_type="application/json").status_code, 403)
        self.as_admin()
        resp = self.client.patch("/api/v1/branding", data=json.dumps({"app_name": "Acme Ops", "accent_color": "#0D9488"}), content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["accent_color"], "#0d9488")
        bad = self.client.patch("/api/v1/branding", data=json.dumps({"accent_color": "red;}</style>"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        self.client.logout()
        self.assertContains(self.client.get("/login/"), "Acme Ops")

    def upload(self, data, name="logo.png", kind="logo"):
        return self.client.post(f"/api/v1/branding/{kind}", {"file": SimpleUploadedFile(name, data, content_type="image/png")})

    def test_upload_sniffs_content_and_serves_safely(self):
        self.as_admin()
        self.assertEqual(self.upload(b"GIF89a....").status_code, 400)  # not by extension
        resp = self.upload(PNG)
        self.assertEqual(resp.status_code, 200, resp.content)
        img = self.client.get("/branding/logo")
        self.assertEqual(img["Content-Type"], "image/png")
        self.assertEqual(img["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", img["Content-Security-Policy"])
        self.assertEqual(self.client.delete("/api/v1/branding/logo").status_code, 200)
        self.assertEqual(self.client.get("/branding/logo").status_code, 404)

    def test_svg_with_script_rejected(self):
        self.as_admin()
        evil = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        self.assertEqual(self.upload(evil, "x.svg").status_code, 400)
        evil2 = b'<svg xmlns="http://www.w3.org/2000/svg"><rect onload="alert(1)"/></svg>'
        self.assertEqual(self.upload(evil2, "x.svg").status_code, 400)
        ok = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="4" height="4"/></svg>'
        self.assertEqual(self.upload(ok, "x.svg").status_code, 200)

    def test_viewer_cannot_upload(self):
        self.as_viewer()
        self.assertEqual(self.upload(PNG).status_code, 403)


class ReportTests(AdminClientMixin, TestCase):
    def setUp(self):
        self.make_users()
        host, token = Host.create_with_token("box")
        r = copy.deepcopy(REPORT)
        r["containers"][0].update(health="unhealthy", restart_policy="unless-stopped", restart_count=9)
        r["containers"][0]["labels"]["title"] = "=HYPERLINK(\"http://x\")"
        r["containers"][2].update(restart_policy="always", name="=cmd|calc")
        self.client.post("/api/v1/report", data=json.dumps(r), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_findings(self):
        self.as_viewer()
        rep = self.client.get("/api/v1/report.json").json()
        codes = {(f["code"], f["target"]) for f in rep["findings"]}
        self.assertIn(("unhealthy", "box / web"), codes)
        self.assertIn(("restart-count", "box / web"), codes)
        self.assertIn(("latest-tag", "box / web"), codes)
        self.assertIn(("all-interfaces", "box / web"), codes)
        self.assertIn(("stopped", "box / =cmd|calc"), codes)
        self.assertEqual(rep["findings"][0]["severity"], "high")
        self.assertEqual(rep["summary"]["containers"], 3)

    def test_page_and_csv(self):
        self.assertEqual(self.client.get("/report/").status_code, 302)  # login required
        self.as_viewer()
        page = self.client.get("/report/")
        self.assertContains(page, "infrastructure report")
        self.assertNotContains(page, "<script>")
        for kind in ("containers", "ports", "connections", "findings"):
            resp = self.client.get(f"/api/v1/report/{kind}.csv")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("attachment", resp["Content-Disposition"])
        csv_text = self.client.get("/api/v1/report/containers.csv").content.decode()
        self.assertIn("'=cmd|calc", csv_text)  # formula injection neutralized
        self.assertEqual(self.client.get("/api/v1/report/secrets.csv").status_code, 404)

    @override_settings(EMAIL_HOST="smtp.example.com", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_send_and_schedule(self):
        self.as_viewer()
        self.assertEqual(self.client.post("/api/v1/report/send", data=json.dumps({"recipients": "a@example.com"}), content_type="application/json").status_code, 403)
        self.as_admin()
        bad = self.client.patch("/api/v1/report/schedule", data=json.dumps({"schedule": "weekly", "recipients": "nope"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.patch("/api/v1/report/schedule", data=json.dumps({"schedule": "weekly", "recipients": "a@example.com, b@example.com"}), content_type="application/json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()["recipients"], ["a@example.com", "b@example.com"])
        sent = self.client.post("/api/v1/report/send", data=json.dumps({}), content_type="application/json")
        self.assertEqual(sent.status_code, 200, sent.content)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("finding", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")

        from .management.commands.report_scheduler import run_once

        mail.outbox.clear()
        monday = timezone.make_aware(datetime(2026, 10, 19, 9, 0))
        self.assertTrue(run_once(monday))
        self.assertFalse(run_once(monday + timedelta(hours=1)))  # once per slot
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(AuditEvent.objects.filter(action="report.scheduled").exists())

    def test_send_without_smtp(self):
        self.as_admin()
        resp = self.client.post("/api/v1/report/send", data=json.dumps({"recipients": "a@example.com"}), content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("SERVCHART_SMTP_HOST", resp.json()["error"])

    def test_is_due(self):
        from .reports_api import is_due

        now = datetime(2026, 10, 19, 8, 0)  # a Monday
        self.assertTrue(is_due("daily", None, now, 7))
        self.assertFalse(is_due("daily", datetime(2026, 10, 19, 7, 1), now, 7))
        self.assertTrue(is_due("weekly", datetime(2026, 10, 12, 7, 0), now, 7))
        self.assertFalse(is_due("monthly", datetime(2026, 10, 1, 7, 0), datetime(2026, 10, 31, 23, 0), 7))
        self.assertFalse(is_due("off", None, now, 7))


class AuditTests(AdminClientMixin, TestCase):
    def setUp(self):
        self.make_users()

    def test_actions_are_recorded_and_admin_only(self):
        self.as_admin()
        self.client.post("/api/v1/hosts", data=json.dumps({"name": "n1"}), content_type="application/json")
        self.client.patch(f"/api/v1/users/{self.viewer.pk}", data=json.dumps({"is_staff": True}), content_type="application/json")
        actions = [e["action"] for e in self.client.get("/api/v1/audit").json()]
        self.assertIn("host.create", actions)
        self.assertIn("user.update", actions)
        self.client.force_login(get_user_model().objects.create_user("plain", password="x-Strong-pass-1"))
        self.assertEqual(self.client.get("/api/v1/audit").status_code, 403)


class HeaderPathTests(TestCase):
    def test_report_prefix_is_not_unprotected(self):
        from .sso import unprotected

        self.assertTrue(unprotected("/api/v1/report"))
        self.assertTrue(unprotected("/api/v1/agent/commands"))
        self.assertFalse(unprotected("/api/v1/report.json"))
        self.assertFalse(unprotected("/api/v1/report/send"))


class LocalCollectorTests(TestCase):
    def test_collector_never_writes_into_agent_hosts(self):
        from unittest import mock

        from django.core.management import call_command

        from inventory.models import hash_token

        agent, _ = Host.create_with_token("a-agent")  # sorts before the hub's own record
        Host.objects.filter(pk=agent.pk).update(is_local=True)  # e.g. ticked by mistake in 0.3.0's admin
        local = Host.objects.create(name="z-hub", is_local=True, token_hash=hash_token("x"), token_hint="local")
        snap = copy.deepcopy(REPORT)
        with mock.patch("servchart_agent.collect.collect", return_value=snap), mock.patch("servchart_agent.docker_api.DockerClient"):
            call_command("local_agent", once=True)
        local.refresh_from_db()
        agent.refresh_from_db()
        self.assertEqual(len(local.snapshot["containers"]), 3)
        self.assertEqual(agent.snapshot, {})

    def test_is_local_not_editable_in_admin(self):
        from django.contrib import admin

        self.assertIn("is_local", admin.site._registry[Host].readonly_fields)


# --- v0.4: server health, container resources, storage, backups, checks, history -----------

from unittest import mock  # noqa: E402

G = 1024**3


def _v04_report():
    r = copy.deepcopy(REPORT)
    r["host"]["cpus"] = 4
    r["host"]["health"] = {
        "cpu_pct": 12.5, "load": [0.5, 0.4, 0.3], "uptime_s": 3600, "mem_total": 8 * G, "mem_available": 2 * G,
        "swap_total": 0, "swap_free": 0, "disk_source": "host", "evil": "x",
        "disks": [{"mount": "/", "fs": "ext4", "total": 100 * G, "used": 97 * G, "pct": 97.0}, {"mount": 5}],
    }
    r["containers"][0]["stats"] = {"cpu_pct": 4.0, "mem_used": 100, "mem_limit": 105, "secret": "x"}
    r["containers"][0]["image_digests"] = ["nginx@sha256:" + "a" * 64, "bad digest"]
    r["storage"] = {"images_bytes": 10 * G, "volumes_bytes": 2 * G, "volumes_unused": 1, "volumes": [{"name": "old", "size": G, "refs": 0}]}
    r["backups"] = [
        {"name": "kopia", "ok": True, "finished_at": "2000-01-01T00:00:00Z"},
        {"name": "restic", "ok": False, "finished_at": timezone.now().isoformat(), "message": "locked"},
        {"name": "fresh", "ok": True, "finished_at": timezone.now().isoformat()},
        "junk",
    ]
    return r


class V04ReportTests(AdminClientMixin, TestCase):
    def setUp(self):
        self.make_users()
        self.host, self.token = Host.create_with_token("box")

    def post(self, body):
        return self.client.post("/api/v1/report", data=json.dumps(body), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_validation_keeps_known_fields_only(self):
        self.assertEqual(self.post(_v04_report()).status_code, 200)
        self.host.refresh_from_db()
        snap = self.host.snapshot
        h = snap["host"]["health"]
        self.assertNotIn("evil", h)
        self.assertEqual([d["mount"] for d in h["disks"]], ["/"])
        c = snap["containers"][0]
        self.assertNotIn("secret", c["stats"])
        self.assertEqual(c["image_digests"], ["nginx@sha256:" + "a" * 64])
        self.assertEqual(len(snap["backups"]), 3)
        self.assertEqual(snap["storage"]["volumes"][0]["name"], "old")

    def test_findings_and_backup_states(self):
        self.post(_v04_report())
        self.as_viewer()
        rep = self.client.get("/api/v1/report.json").json()
        codes = {(f["code"], f["target"]) for f in rep["findings"]}
        self.assertIn(("disk-full", "box: /"), codes)
        self.assertIn(("backup-overdue", "box: kopia"), codes)
        self.assertIn(("backup-failed", "box: restic"), codes)
        self.assertNotIn(("backup-overdue", "box: fresh"), codes)
        self.assertIn(("container-memory", "box / web"), codes)
        self.assertIn(("unused-volumes", "box"), codes)
        self.assertEqual(rep["summary"]["backups_bad"], 2)
        for kind in ("hosts", "backups", "certificates", "updates"):
            self.assertEqual(self.client.get(f"/api/v1/report/{kind}.csv").status_code, 200)
        page = self.client.get("/report/")
        self.assertContains(page, "Server health")
        self.assertContains(page, "Backups")

    def test_history_is_sampled_and_served(self):
        self.post(_v04_report())
        self.post(_v04_report())  # within 5 minutes: no second sample
        self.assertEqual(self.host.samples.count(), 1)
        from .history import record

        self.assertIsNotNone(record(self.host, _v04_report(), now=timezone.now() + timedelta(minutes=6)))
        self.as_viewer()
        h = self.client.get(f"/api/v1/hosts/{self.host.pk}/history?hours=24").json()
        self.assertEqual(h["cpu"], [12.5, 12.5])
        self.assertEqual(h["disks"]["/"], [97.0, 97.0])
        self.assertEqual(h["containers"]["web"]["mem"], [100, 100])

    def test_changes_since_yesterday(self):
        from .history import changes
        from .models import Sample

        Sample.objects.create(host=self.host, created_at=timezone.now() - timedelta(hours=24), data={"inv": {"web": "nginx:1.26", "gone": "x"}})
        snap = _v04_report()
        snap["containers"][0]["image"] = "nginx:1.27"
        ch = changes(self.host, snap)
        self.assertEqual(ch["removed"], ["gone"])
        self.assertIn("netdata", ch["added"])
        self.assertEqual(ch["image_changed"], [{"name": "web", "from": "nginx:1.26", "to": "nginx:1.27"}])

    def test_purge(self):
        from .history import purge
        from .models import Sample

        Sample.objects.create(host=self.host, created_at=timezone.now() - timedelta(days=30), data={})
        Sample.objects.create(host=self.host, created_at=timezone.now(), data={})
        self.assertEqual(purge(), 1)


class CheckTests(AdminClientMixin, TestCase):
    def setUp(self):
        self.make_users()

    def test_parse_ref(self):
        from .checks import parse_ref

        self.assertEqual(parse_ref("nginx"), ("registry-1.docker.io", "library/nginx", "latest"))
        self.assertEqual(parse_ref("frappe/erpnext:v16.37.0"), ("registry-1.docker.io", "frappe/erpnext", "v16.37.0"))
        self.assertEqual(parse_ref("ghcr.io/org/app:1.2"), ("ghcr.io", "org/app", "1.2"))
        self.assertEqual(parse_ref("localhost:5000/app"), ("localhost:5000", "app", "latest"))
        self.assertIsNone(parse_ref("sha256:" + "a" * 64))

    def test_newer_tag(self):
        from .checks import newer_tag

        tags = ["1.27.2", "1.27.4", "1.28.0", "1.28.0-alpine", "v1.29.0", "latest", "1.27", "2.0.0-rc1"]
        self.assertEqual(newer_tag("1.27.2", tags), "1.28.0")
        self.assertEqual(newer_tag("1.27.4-alpine", tags + ["1.27.5-alpine"]), "1.28.0-alpine")  # same "-alpine" flavour, highest wins
        self.assertEqual(newer_tag("v1.28.0", tags), "v1.29.0")
        self.assertIsNone(newer_tag("latest", tags))
        self.assertIsNone(newer_tag("1.28.0", ["1.27.0"]))

    def test_image_status_and_run(self):
        from .checks import image_status, run_image_checks
        from .models import ImageCheck

        host, token = Host.create_with_token("box")
        r = _v04_report()
        r["containers"][0]["image"] = "nginx:1.27.2"
        self.client.post("/api/v1/report", data=json.dumps(r), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        with mock.patch("inventory.checks.check_image", return_value={"latest_digest": "sha256:" + "b" * 64, "newer_tag": "1.28.0"}):
            self.assertEqual(run_image_checks(force=True), 1)
        checks = {c.ref: c for c in ImageCheck.objects.all()}
        st = image_status({"image": "nginx:1.27.2", "image_digests": ["nginx@sha256:" + "a" * 64]}, checks)
        self.assertEqual((st["state"], st["newer_tag"]), ("update", "1.28.0"))
        same = image_status({"image": "nginx:1.27.2", "image_digests": ["nginx@sha256:" + "b" * 64]}, checks)
        self.assertEqual(same["state"], "current")
        self.as_viewer()
        graph = self.client.get("/api/v1/graph").json()
        web = next(n for n in graph["nodes"] if n["id"].endswith(":web"))
        self.assertEqual(web["data"]["image_update"]["state"], "update")

    def test_cert_api(self):
        from datetime import datetime, timezone as dt_tz

        fake = {"expires_at": datetime(2030, 1, 1, tzinfo=dt_tz.utc), "issuer": "Test CA", "error": ""}
        self.as_viewer()
        self.assertEqual(self.client.post("/api/v1/checks/certs", data=json.dumps({"hostname": "example.com"}), content_type="application/json").status_code, 403)
        self.as_admin()
        with mock.patch("inventory.checks.fetch_cert", return_value=fake):
            r = self.client.post("/api/v1/checks/certs", data=json.dumps({"hostname": "https://Example.com:8443/path"}), content_type="application/json")
            self.assertEqual(r.status_code, 201, r.content)
            self.assertEqual((r.json()["hostname"], r.json()["port"], r.json()["issuer"]), ("example.com", 8443, "Test CA"))
            dup = self.client.post("/api/v1/checks/certs", data=json.dumps({"hostname": "example.com:8443"}), content_type="application/json")
            self.assertEqual(dup.status_code, 400)
        bad = self.client.post("/api/v1/checks/certs", data=json.dumps({"hostname": "not a host; rm -rf"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        pk = r.json()["id"]
        self.assertEqual(self.client.delete(f"/api/v1/checks/certs/{pk}").status_code, 204)

    def test_expiring_cert_is_a_finding(self):
        from datetime import datetime, timezone as dt_tz

        from .models import CertCheck

        CertCheck.objects.create(hostname="soon.example.com", port=443, checked_at=timezone.now(), expires_at=timezone.now() + timedelta(days=3))
        CertCheck.objects.create(hostname="bad.example.com", port=443, checked_at=timezone.now(), error="Not trusted: self-signed")
        CertCheck.objects.create(hostname="fine.example.com", port=443, checked_at=timezone.now(), expires_at=datetime(2030, 1, 1, tzinfo=dt_tz.utc))
        self.as_viewer()
        rep = self.client.get("/api/v1/report.json").json()
        codes = {(f["code"], f["target"]) for f in rep["findings"]}
        self.assertIn(("cert-expiring", "soon.example.com"), codes)
        self.assertIn(("cert-error", "bad.example.com"), codes)
        self.assertFalse(any(t == "fine.example.com" for _, t in codes))

    def test_background_checks_pace(self):
        from .management.commands.report_scheduler import background_checks

        state = {}
        with mock.patch("inventory.checks.run_cert_checks") as certs, mock.patch("inventory.checks.run_image_checks") as images, mock.patch("inventory.history.purge") as purge:
            background_checks(state, now=1000)
            background_checks(state, now=1100)
        self.assertEqual((certs.call_count, images.call_count, purge.call_count), (1, 1, 1))


class PublicAddressTests(AdminClientMixin, TestCase):
    """A cloud VM reaching home servers through the router's public IP and port forwards."""

    def setUp(self):
        self.make_users()

    def _host(self, name, containers, host_extra=None, conns=None, local=False):
        if local:
            from inventory.models import hash_token

            h = Host.objects.create(name=name, is_local=True, token_hash=hash_token(name), token_hint="local")
        else:
            h, _ = Host.create_with_token(name)
        h.snapshot = {"host": {"ips": [], **(host_extra or {})}, "containers": containers, "networks": [], "host_connections": conns or []}
        h.last_seen = timezone.now()
        h.save()
        return h

    def test_connection_to_public_ip_resolves_by_published_port(self):
        from .graph import build_graph
        from .models import SiteSettings

        site = SiteSettings.load()
        site.public_addresses = "203.0.113.7"
        site.save()
        home = self._host("hestia", [{"name": "headscale", "ports": [{"private": 8080, "public": 8843, "ips": ["192.168.0.15"]}], "networks": []}])
        self._host("cloud", [{"name": "tailscale", "networks": [], "connections": [{"ip": "203.0.113.7", "port": 8843, "count": 1}, {"ip": "203.0.113.7", "port": 9999, "count": 1}]}])
        from . import addresses

        addresses._cache["key"] = None  # forget the cached resolution
        g = build_graph()
        flows = [e for e in g["edges"] if e["kind"] == "flow"]
        self.assertEqual([(e["source"].split(":")[-1], e["target"]) for e in flows], [("tailscale", f"ctr:{home.pk}:headscale")])

    def test_agents_are_told_the_addresses(self):
        self.as_admin()
        bad = self.client.patch("/api/v1/addresses", data=json.dumps({"addresses": "not an address!"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.patch("/api/v1/addresses", data=json.dumps({"addresses": "203.0.113.7\n203.0.113.7"}), content_type="application/json")
        self.assertEqual(ok.json()["addresses"], ["203.0.113.7"])
        host, token = Host.create_with_token("cloud")
        self.client.logout()
        r = self.client.post("/api/v1/report", data=json.dumps(REPORT), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.json()["observe_ips"], ["203.0.113.7"])

    def test_agent_reporting_to_the_hub_gets_a_line(self):
        from .graph import build_graph

        hub = self._host("harbor", [{"name": "servchart-hub", "image": "opticodev/servchart-hub:0.4.0", "networks": []}], local=True)
        cloud = self._host("namdje", [{"name": "servchart-agent", "image": "opticodev/servchart-agent:0.4.0", "networks": []}])
        g = build_graph()
        agent_edges = [e for e in g["edges"] if e.get("agent")]
        self.assertEqual([(e["source"], e["target"]) for e in agent_edges], [(f"ctr:{cloud.pk}:servchart-agent", f"ctr:{hub.pk}:servchart-hub")])
