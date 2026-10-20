import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from servchart_agent import backups, stats, storage, system  # noqa: E402

MOUNTS = """/dev/sda2 / ext4 rw,relatime 0 0
proc /proc proc rw 0 0
overlay /var/lib/docker/overlay2/abc/merged overlay rw 0 0
/dev/sda1 /boot/efi vfat rw 0 0
/dev/sda2 /home/user/bind ext4 rw 0 0
/dev/loop3 /snap/core/1 squashfs ro 0 0
nas:/export /mnt/my\\040nas nfs4 rw 0 0
tmpfs /run tmpfs rw 0 0
"""


class SystemTests(unittest.TestCase):
    def test_cpu_times(self):
        busy, total = system.cpu_times("cpu  100 0 50 800 50 0 0 0 0 0\ncpu0 1 2 3 4\n")
        self.assertEqual((busy, total), (150, 1000))

    def test_meminfo_load_uptime(self):
        m = system.meminfo("MemTotal:  1000 kB\nMemAvailable:  250 kB\nSwapTotal: 0 kB\n")
        self.assertEqual((m["mem_total"], m["mem_available"]), (1024000, 256000))
        self.assertEqual(system.loadavg("0.50 1.00 2.00 1/100 42"), [0.5, 1.0, 2.0])
        self.assertEqual(system.uptime("3600.55 100.0"), 3600)

    def test_parse_mounts_keeps_real_filesystems_once(self):
        rows = system.parse_mounts(MOUNTS)
        self.assertEqual([r[1] for r in rows], ["/", "/boot/efi", "/mnt/my nas"])

    def test_docker_fallback_in_container(self):
        with mock.patch.object(system, "host_root", return_value=None):
            disks, source = system.disks("/var/lib/docker")
        self.assertEqual(source, "docker")
        self.assertEqual(disks[0]["mount"], "/var/lib/docker")


class StatsTests(unittest.TestCase):
    DOC = {
        "cpu_stats": {"cpu_usage": {"total_usage": 2_000_000}, "system_cpu_usage": 20_000_000, "online_cpus": 4},
        "precpu_stats": {},
        "memory_stats": {"usage": 300, "limit": 2**63, "stats": {"inactive_file": 100}},
        "pids_stats": {"current": 7},
        "networks": {"eth0": {"rx_bytes": 10, "tx_bytes": 20}},
    }

    def test_cpu_from_previous_sample_and_memory_without_cache(self):
        prev = {}
        first = stats.parse("c1", self.DOC, prev)
        self.assertIsNone(first["cpu_pct"])  # nothing to compare with yet
        self.assertEqual(first["mem_used"], 200)
        self.assertIsNone(first["mem_limit"])  # no limit
        nxt = json.loads(json.dumps(self.DOC))
        nxt["cpu_stats"]["cpu_usage"]["total_usage"] = 3_000_000
        nxt["cpu_stats"]["system_cpu_usage"] = 30_000_000
        self.assertEqual(stats.parse("c1", nxt, prev)["cpu_pct"], 40.0)  # 1/10 of the machine x 4 cpus


class StorageTests(unittest.TestCase):
    def test_summarize(self):
        df = {
            "LayersSize": 5000,
            "Images": [{"Containers": 1}, {"Containers": 0}],
            "Containers": [{"SizeRw": 10}, {"SizeRw": None}],
            "Volumes": [{"Name": "small", "UsageData": {"Size": 1, "RefCount": 1}}, {"Name": "big", "UsageData": {"Size": 900, "RefCount": 0}}],
            "BuildCache": [{"Size": 7, "Shared": False}],
        }
        s = storage.summarize(df)
        self.assertEqual(s["volumes"][0]["name"], "big")
        self.assertEqual((s["images_unused"], s["volumes_unused"], s["volumes_bytes"], s["containers_rw_bytes"]), (1, 1, 901, 10))

    def test_disabled(self):
        with mock.patch.dict(os.environ, {"SERVCHART_DF_INTERVAL": "0"}):
            self.assertIsNone(storage.collect(object()))


class BackupTests(unittest.TestCase):
    def test_missing_dir_means_not_set_up(self):
        with mock.patch.dict(os.environ, {"SERVCHART_STATUS_DIR": "/nonexistent/servchart"}):
            self.assertIsNone(backups.collect())

    def test_mark_and_read(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"SERVCHART_STATUS_DIR": d}):
            backups.mark("kopia", message="1 GB", max_age_hours=26)
            backups.mark("restic", ok=False, message="repo locked")
            open(os.path.join(d, "borg-nightly"), "w").close()  # plain file: mtime counts
            with open(os.path.join(d, "bad name!.json"), "w") as fh:
                fh.write("{}")
            got = {b["name"]: b for b in backups.collect()}
        self.assertEqual(sorted(got), ["borg-nightly", "kopia", "restic"])
        self.assertTrue(got["kopia"]["ok"])
        self.assertEqual(got["kopia"]["max_age_hours"], 26)
        self.assertFalse(got["restic"]["ok"])
        self.assertTrue(got["borg-nightly"]["ok"])
        with self.assertRaises(ValueError):
            backups.mark("../etc/passwd")


if __name__ == "__main__":
    unittest.main()
