import os
import struct
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from servchart_agent import commands  # noqa: E402
from servchart_agent import logs as logs_mod  # noqa: E402


def frame(stream: int, text: str) -> bytes:
    data = text.encode()
    return bytes([stream, 0, 0, 0]) + struct.pack(">I", len(data)) + data


RAW = (
    frame(1, "2026-10-19T10:00:00.000000001Z starting web\n")
    + frame(2, "2026-10-19T10:00:01.000000001Z WARN DB_PASSWORD=hunter2 rejected\n2026-10-19T10:00:02.0Z sec")
    + frame(2, "ond line split across frames\n")
    + frame(1, "2026-10-19T10:00:03.0Z GET /api 200\n")
)


class FakeClient:
    def __init__(self, raw=RAW, tty=False):
        self.raw, self.tty, self.calls = raw, tty, []

    def containers(self):
        return [{"Names": ["/web"]}, {"Names": ["/db"]}]

    def inspect_container(self, name):
        return {"Id": "abc123", "Config": {"Tty": self.tty}}

    def logs(self, cid, tail=200, since=None, limit=None):
        self.calls.append((cid, tail, since))
        return self.raw


class DemuxTests(unittest.TestCase):
    def test_multiplexed_stream(self):
        lines = logs_mod.demux(RAW, tty=False)
        self.assertEqual([s for s, _ in lines], ["out", "err", "err", "out"])
        self.assertTrue(lines[2][1].endswith("second line split across frames"))

    def test_tty_stream(self):
        lines = logs_mod.demux(b"2026-10-19T10:00:00Z hello\n2026-10-19T10:00:01Z world\n", tty=True)
        self.assertEqual([m for _, m in lines], ["2026-10-19T10:00:00Z hello", "2026-10-19T10:00:01Z world"])


class FetchTests(unittest.TestCase):
    def test_fetch_splits_timestamp_and_redacts(self):
        out = logs_mod.fetch(FakeClient(), "web", tail=50)
        self.assertEqual(out["lines"][0], {"t": "2026-10-19T10:00:00.000000001Z", "s": "out", "m": "starting web"})
        self.assertEqual(out["lines"][1]["m"], "WARN DB_PASSWORD=[redacted] rejected")
        self.assertTrue(out["redacted"])

    def test_redaction_can_be_turned_off(self):
        with mock.patch.dict(os.environ, {"SERVCHART_LOGS_REDACT": "0"}):
            out = logs_mod.fetch(FakeClient(), "web")
        self.assertIn("hunter2", out["lines"][1]["m"])

    def test_tail_is_capped(self):
        client = FakeClient()
        logs_mod.fetch(client, "web", tail=999999)
        self.assertEqual(client.calls[0][1], logs_mod.MAX_LINES)

    def test_byte_cap(self):
        big = b"".join(frame(1, f"2026-10-19T10:00:00Z {'x' * 900}\n") for _ in range(2000))
        out = logs_mod.fetch(FakeClient(raw=big), "web", tail=2000)
        self.assertTrue(out["truncated"])
        self.assertLess(sum(len(l["m"]) for l in out["lines"]), logs_mod.MAX_BYTES)


class CommandTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SERVCHART_ALLOW_LOGS", None)
            self.assertFalse(commands.handle(FakeClient(), {"type": "logs", "container": "web"})["ok"])
            self.assertIsNone(commands.start(FakeClient(), lambda *a: None))

    def test_only_existing_containers_and_known_types(self):
        with mock.patch.dict(os.environ, {"SERVCHART_ALLOW_LOGS": "1"}):
            self.assertIn("No container", commands.handle(FakeClient(), {"type": "logs", "container": "../etc"})["error"])
            self.assertIn("Unknown request", commands.handle(FakeClient(), {"type": "exec", "container": "web"})["error"])
            ok = commands.handle(FakeClient(), {"type": "logs", "container": "web", "tail": 10})
            self.assertTrue(ok["ok"])
            self.assertEqual(len(ok["result"]["lines"]), 4)

    def test_loop_polls_and_posts_results(self):
        stop = threading.Event()
        posted = []

        def request(method, path, body):
            if method == "GET":
                return {"commands": [{"id": "r1", "type": "logs", "container": "web", "tail": 5}]}
            posted.append((path, body))
            stop.set()
            return {"ok": True}

        with mock.patch.dict(os.environ, {"SERVCHART_ALLOW_LOGS": "1"}):
            commands.loop(FakeClient(), request, interval=0.01, stop=stop)
        self.assertEqual(posted[0][0], "/api/v1/agent/commands/r1/result")
        self.assertTrue(posted[0][1]["ok"])


if __name__ == "__main__":
    unittest.main()
