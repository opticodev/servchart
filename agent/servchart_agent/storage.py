"""Docker disk usage (images, container layers, volumes, build cache) from `GET /system/df`.

Docker has to measure every volume to answer, which can take a while on big hosts, so the
result is cached and refreshed every SERVCHART_DF_INTERVAL seconds (default 1 hour;
0 turns it off).
"""

from __future__ import annotations

import os
import time

MAX_VOLUMES = 500
_cache: dict = {"at": 0.0, "data": None}


def interval() -> int:
    try:
        return int(os.environ.get("SERVCHART_DF_INTERVAL", "3600"))
    except ValueError:
        return 3600


def summarize(df: dict) -> dict:
    images = df.get("Images") or []
    containers = df.get("Containers") or []
    volumes = df.get("Volumes") or []
    cache = df.get("BuildCache") or []
    vols = []
    for v in volumes:
        usage = v.get("UsageData") or {}
        size = usage.get("Size")
        vols.append({"name": v.get("Name"), "size": size if isinstance(size, int) and size >= 0 else None, "refs": usage.get("RefCount")})
    vols.sort(key=lambda v: -(v["size"] or 0))
    return {
        "images_bytes": df.get("LayersSize"),
        "images_count": len(images),
        "images_unused": sum(1 for i in images if not i.get("Containers")),
        "containers_rw_bytes": sum(c.get("SizeRw") or 0 for c in containers),
        "volumes_bytes": sum(v["size"] or 0 for v in vols),
        "volumes_count": len(vols),
        "volumes_unused": sum(1 for v in vols if v["refs"] == 0),
        "build_cache_bytes": sum(b.get("Size") or 0 for b in cache if not b.get("Shared")),
        "volumes": vols[:MAX_VOLUMES],
        "measured_at": int(time.time()),
    }


def collect(client) -> dict | None:
    every = interval()
    if every <= 0:
        return None
    now = time.time()
    if now - _cache["at"] >= every:
        try:
            slow = client
            if hasattr(client, "docker_host"):  # measuring volumes can take minutes on big hosts
                from .docker_api import DockerClient

                slow = DockerClient(client.docker_host, timeout=180)
            _cache["data"] = summarize(slow.get("/system/df"))
            _cache["at"] = now
        except Exception:
            _cache["at"] = now - every + 300  # retry in 5 minutes
    return _cache["data"]
