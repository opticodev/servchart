"""Backup status, from small status files your backup jobs write (any backup tool).

Put one file per job in /var/lib/servchart/status on the host (or SERVCHART_STATUS_DIR). In a
container the agent finds it through the host root mount (SERVCHART_HOST_ROOT=/host):

  * a JSON file such as `kopia.json`:
      {"ok": true, "finished_at": "2026-10-20T03:12:00Z", "max_age_hours": 26,
       "message": "1.2 GB uploaded", "size_bytes": 1234567}
    every field is optional; `finished_at` defaults to the file's modification time;
  * or any other file: its modification time counts as the last successful run.

`servchart-agent --mark NAME` (or `--mark NAME --failed --message "..."`) writes one for you,
so a cron job can end with `&& servchart-agent --mark kopia || servchart-agent --mark kopia --failed`.
Only these fields are sent; the files are never executed.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

DEFAULT_DIR = "/var/lib/servchart/status"
NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MAX_FILES = 50
MAX_BYTES = 16 * 1024


def status_dir() -> str:
    """SERVCHART_STATUS_DIR, else the host's /var/lib/servchart/status (through SERVCHART_HOST_ROOT in a container)."""
    if os.environ.get("SERVCHART_STATUS_DIR"):
        return os.environ["SERVCHART_STATUS_DIR"]
    from .system import host_root

    root = host_root()
    return os.path.join(root, DEFAULT_DIR.lstrip("/")) if root and root != "/" else DEFAULT_DIR


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def read_one(path: str) -> dict | None:
    name = os.path.basename(path)
    stem = name[:-5] if name.endswith(".json") else name
    if not NAME_RE.match(stem):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    entry = {"name": stem, "ok": True, "finished_at": _iso(st.st_mtime), "max_age_hours": None, "message": "", "size_bytes": None}
    if name.endswith(".json") and st.st_size <= MAX_BYTES:
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            doc = None
        if isinstance(doc, dict):
            if "ok" in doc:
                entry["ok"] = bool(doc["ok"])
            if isinstance(doc.get("finished_at"), str):
                entry["finished_at"] = doc["finished_at"][:40]
            if isinstance(doc.get("max_age_hours"), (int, float)) and 0 < doc["max_age_hours"] <= 24 * 366:
                entry["max_age_hours"] = doc["max_age_hours"]
            if isinstance(doc.get("message"), str):
                entry["message"] = doc["message"][:300]
            if isinstance(doc.get("size_bytes"), int) and doc["size_bytes"] >= 0:
                entry["size_bytes"] = doc["size_bytes"]
    return entry


def collect() -> list[dict] | None:
    """None when the status directory doesn't exist (backups not set up for ServChart here)."""
    d = status_dir()
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return None
    out = []
    for n in names:
        if n.startswith(".") or n.endswith(".tmp"):
            continue
        path = os.path.join(d, n)
        if os.path.isfile(path):
            e = read_one(path)
            if e:
                out.append(e)
        if len(out) >= MAX_FILES:
            break
    return out


def mark(name: str, ok: bool = True, message: str = "", max_age_hours: float | None = None, size_bytes: int | None = None) -> str:
    """Write <status dir>/<name>.json atomically. Returns the path."""
    if not NAME_RE.match(name):
        raise ValueError("Use letters, digits, dot, dash or underscore (max 64) for the backup name.")
    d = status_dir()
    os.makedirs(d, exist_ok=True)
    doc = {"ok": ok, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "message": message[:300]}
    if max_age_hours:
        doc["max_age_hours"] = max_age_hours
    if size_bytes is not None:
        doc["size_bytes"] = size_bytes
    path = os.path.join(d, f"{name}.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(doc, fh)
    os.replace(tmp, path)
    return path
