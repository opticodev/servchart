"""Short history: one small sample per host every SERVCHART_SAMPLE_MINUTES (default 5), kept
for SERVCHART_HISTORY_DAYS (default 7). Feeds the sparklines and "what changed" in reports.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import Host, Sample


def _mem_used(h: dict):
    if h.get("mem_total") and h.get("mem_available") is not None:
        return h["mem_total"] - h["mem_available"]
    return None


def sample_data(snapshot: dict, with_inventory: bool) -> dict:
    host = snapshot.get("host") or {}
    h = host.get("health") or {}
    containers = snapshot.get("containers") or []
    data = {
        "cpu": h.get("cpu_pct"),
        "mem": _mem_used(h),
        "mem_total": h.get("mem_total"),
        "load": (h.get("load") or [None])[0],
        "disks": {d["mount"]: d.get("pct") for d in h.get("disks") or []},
        "running": sum(1 for c in containers if c.get("state") == "running"),
        "total": len(containers),
        "ctr": {
            c["name"]: [(c.get("stats") or {}).get("cpu_pct"), (c.get("stats") or {}).get("mem_used")]
            for c in containers
            if c.get("stats")
        },
    }
    if with_inventory:  # hourly: enough to tell what was added, removed or upgraded
        data["inv"] = {c["name"]: c.get("image") for c in containers}
    return data


def record(host: Host, snapshot: dict, now=None) -> Sample | None:
    now = now or timezone.now()
    last = host.samples.order_by("-created_at").values_list("created_at", flat=True).first()
    if last and now - last < timedelta(minutes=settings.SERVCHART_SAMPLE_MINUTES) - timedelta(seconds=5):
        return None
    last_inv = host.samples.filter(data__has_key="inv").order_by("-created_at").values_list("created_at", flat=True).first()
    with_inv = not last_inv or now - last_inv >= timedelta(minutes=55)
    return Sample.objects.create(host=host, created_at=now, data=sample_data(snapshot, with_inv))


def purge(now=None) -> int:
    now = now or timezone.now()
    deleted, _ = Sample.objects.filter(created_at__lt=now - timedelta(days=settings.SERVCHART_HISTORY_DAYS)).delete()
    return deleted


def series(host: Host, hours: int = 24) -> dict:
    since = timezone.now() - timedelta(hours=hours)
    rows = list(host.samples.filter(created_at__gte=since).order_by("created_at").values_list("created_at", "data"))
    out = {"t": [], "cpu": [], "mem": [], "mem_total": None, "load": [], "disks": {}, "containers": {}}
    for i, (at, d) in enumerate(rows):
        out["t"].append(int(at.timestamp()))
        out["cpu"].append(d.get("cpu"))
        out["mem"].append(d.get("mem"))
        out["load"].append(d.get("load"))
        out["mem_total"] = d.get("mem_total") or out["mem_total"]
        for mount, pct in (d.get("disks") or {}).items():
            out["disks"].setdefault(mount, [None] * i).append(pct)
        for name, (cpu, mem) in (d.get("ctr") or {}).items():
            c = out["containers"].setdefault(name, {"cpu": [None] * i, "mem": [None] * i})
            c["cpu"].append(cpu)
            c["mem"].append(mem)
        n = i + 1
        for arr in out["disks"].values():
            arr.extend([None] * (n - len(arr)))
        for c in out["containers"].values():
            c["cpu"].extend([None] * (n - len(c["cpu"])))
            c["mem"].extend([None] * (n - len(c["mem"])))
    return out


def changes(host: Host, snapshot: dict, hours: int = 24) -> dict | None:
    """Containers added, removed or running another image compared with ~`hours` ago."""
    target = timezone.now() - timedelta(hours=hours)
    old = (
        host.samples.filter(data__has_key="inv", created_at__lte=target + timedelta(minutes=90))
        .order_by("-created_at")
        .values_list("created_at", "data")
        .first()
    )
    if not old:
        return None
    before = old[1].get("inv") or {}
    now = {c["name"]: c.get("image") for c in snapshot.get("containers") or []}
    return {
        "since": old[0].isoformat(),
        "added": sorted(set(now) - set(before)),
        "removed": sorted(set(before) - set(now)),
        "image_changed": sorted([{"name": n, "from": before[n], "to": now[n]} for n in set(now) & set(before) if before[n] != now[n]], key=lambda x: x["name"]),
    }
