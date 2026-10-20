import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from servchart_agent import collect as collect_mod  # noqa: E402
from servchart_agent import connections as conn  # noqa: E402
from servchart_agent.collect import collect, parse_depends_on  # noqa: E402

HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
# 10.18.0.2 is the container. Hex addresses are little-endian 32-bit words, ports big-endian.
TCP = HEADER + "\n".join(
    [
        "   0: 00000000:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1",  # LISTEN :80
        "   1: 0200120A:9C40 0500120A:0CEA 01 00000000:00000000 00:00000000 00000000     0        0 2",  # -> 10.18.0.5:3306
        "   2: 0200120A:9C44 0500120A:0CEA 01 00000000:00000000 00:00000000 00000000     0        0 3",  # -> same again
        "   3: 0200120A:0050 0900120A:A000 01 00000000:00000000 00:00000000 00000000     0        0 4",  # inbound to :80
        "   4: 0200120A:9C41 08080808:01BB 01 00000000:00000000 00:00000000 00000000     0        0 5",  # -> 8.8.8.8:443 (public)
        "   5: 0100007F:9C42 0100007F:1F90 01 00000000:00000000 00:00000000 00000000     0        0 6",  # loopback
        "   6: 0200120A:9C43 0600120A:18EB 06 00000000:00000000 00:00000000 00000000     0        0 7",  # TIME_WAIT
    ]
)
# ::ffff:10.18.0.2 -> ::ffff:192.168.0.28:8484 established
TCP6 = HEADER + "   0: 0000000000000000FFFF00000200120A:9C50 0000000000000000FFFF00001C00A8C0:2124 01 0 0 0 0 0 0 8\n"
FIB_TRIE = """Main:
  +-- 0.0.0.0/0 3 0 5
     |-- 192.168.0.28
        /32 host LOCAL
     |-- 172.17.0.1
        /32 host LOCAL
     |-- 127.0.0.1
        /32 host LOCAL
"""


class ParseTests(unittest.TestCase):
    def test_parse_ipv4_and_mapped_ipv6(self):
        rows = conn.parse_tcp_table(TCP) + conn.parse_tcp_table(TCP6)
        self.assertIn(("10.18.0.2", 40000, "10.18.0.5", 3306, "01"), rows)
        self.assertIn(("10.18.0.2", 40016, "192.168.0.28", 8484, "01"), rows)

    def test_outbound_only_private_aggregated(self):
        rows = conn.parse_tcp_table(TCP) + conn.parse_tcp_table(TCP6)
        out = conn.outbound(rows, exclude_ips={"10.18.0.2"})
        self.assertEqual(out, [{"ip": "10.18.0.5", "port": 3306, "count": 2}, {"ip": "192.168.0.28", "port": 8484, "count": 1}])

    def test_public_opt_in(self):
        rows = conn.parse_tcp_table(TCP)
        self.assertIn({"ip": "8.8.8.8", "port": 443, "count": 1}, conn.outbound(rows, include_public=True))

    def test_listening(self):
        self.assertEqual(conn.listening_ports(conn.parse_tcp_table(TCP)), [80])

    def test_cgnat_counts_as_private(self):
        self.assertTrue(conn.is_reportable("100.101.1.2"))
        self.assertFalse(conn.is_reportable("1.1.1.1"))

    def test_depends_on_label(self):
        self.assertEqual(parse_depends_on("db:service_healthy:false,redis:service_started:false,db:x:y"), ["db", "redis"])
        self.assertEqual(parse_depends_on(None), [])


class ObserveTests(unittest.TestCase):
    """End to end: a fake /proc with one container namespace (pid 4242) and the host (pid 1)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        for pid, files in {"4242": {"tcp": TCP, "tcp6": TCP6}, "1": {"tcp": HEADER, "fib_trie": FIB_TRIE}}.items():
            os.makedirs(f"{self.tmp.name}/{pid}/net")
            for name, text in files.items():
                with open(f"{self.tmp.name}/{pid}/net/{name}", "w") as fh:
                    fh.write(text)
        self.patches = [
            mock.patch.object(conn, "PROC", self.tmp.name),
            mock.patch.object(conn, "observe_available", return_value=True),
            mock.patch.dict(os.environ, {"SERVCHART_OBSERVE_CONNECTIONS": "1"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_snapshot_has_connections_and_host_ips(self):
        class Client:
            def info(self):
                return {"Name": "docker-host"}

            def version(self):
                return {"Version": "29"}

            def containers(self):
                return [{"Id": "a"}]

            def inspect_container(self, cid):
                return {
                    "Id": "a" * 12,
                    "Name": "/web",
                    "Config": {"Image": "nginx", "Env": ["SECRET=x"], "Labels": {}},
                    "State": {"Status": "running", "Running": True, "Pid": 4242},
                    "HostConfig": {"NetworkMode": "app_default"},
                    "NetworkSettings": {"Networks": {"app_default": {"IPAddress": "10.18.0.2"}}},
                }

            def networks(self):
                return [{"Name": "app_default", "IPAM": {"Config": [{"Subnet": "10.18.0.0/16"}]}},
                        {"Name": "bridge", "IPAM": {"Config": [{"Subnet": "172.17.0.0/16"}]}}]

        snap = collect(Client())
        web = snap["containers"][0]
        self.assertEqual(snap["host"]["observe"], "on")
        self.assertEqual(snap["host"]["ips"], ["192.168.0.28"])  # docker gateway + loopback dropped
        self.assertEqual([(c["ip"], c["port"]) for c in web["connections"]], [("10.18.0.5", 3306), ("192.168.0.28", 8484)])
        self.assertEqual(web["listening"], [80])
        self.assertEqual(snap["host_connections"], [])
        self.assertNotIn("SECRET", json.dumps(snap))

    def test_unavailable_without_pid_host(self):
        with mock.patch.object(conn, "observe_available", return_value=False):
            snap = collect_mod.collect(type("C", (), {
                "info": lambda s: {"Name": "h"}, "version": lambda s: {}, "containers": lambda s: [], "networks": lambda s: []})())
        self.assertEqual(snap["host"]["observe"], "unavailable")


if __name__ == "__main__":
    unittest.main()


class ExtraIpTests(unittest.TestCase):
    def test_hub_listed_public_ip_is_reported(self):
        from servchart_agent import connections as c
        from servchart_agent.__main__ import apply_hub_hints

        rows = [("10.0.0.5", 50000, "73.173.202.24", 8843, "01"), ("10.0.0.5", 50001, "8.8.8.8", 443, "01")]
        self.assertEqual(c.outbound(rows), [])
        apply_hub_hints({"observe_ips": ["73.173.202.24", "not-an-ip"]})
        try:
            self.assertEqual(c.outbound(rows), [{"ip": "73.173.202.24", "port": 8843, "count": 1}])
        finally:
            apply_hub_hints({"observe_ips": []})
