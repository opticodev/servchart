"""Per-container CPU and memory, from Docker's stats endpoint (read-only, one-shot).

`one-shot=true` answers immediately with a single sample, so CPU use is computed against
the sample taken at the previous report. Memory excludes the page cache, the way
`docker stats` shows it.
"""

from __future__ import annotations

from urllib.parse import quote

_prev: dict[str, tuple[int, int]] = {}  # container id -> (container cpu ns, system cpu ns)


def _mem_used(mem: dict) -> int | None:
    usage = mem.get("usage")
    if usage is None:
        return None
    st = mem.get("stats") or {}
    cache = st.get("inactive_file", st.get("total_inactive_file", st.get("cache", 0))) or 0
    return max(0, usage - cache)


def _sum(items, key):
    return sum((i or {}).get(key) or 0 for i in items or [])


def parse(cid: str, s: dict, prev: dict | None = None) -> dict:
    """One container's stats document -> {cpu_pct, mem_used, mem_limit, pids, net_rx, net_tx, ...}."""
    prev = _prev if prev is None else prev
    cpu = s.get("cpu_stats") or {}
    total = (cpu.get("cpu_usage") or {}).get("total_usage")
    system = cpu.get("system_cpu_usage")
    cpus = cpu.get("online_cpus") or len((cpu.get("cpu_usage") or {}).get("percpu_usage") or []) or 1
    cpu_pct = None
    if total is not None and system is not None:
        before = prev.get(cid)
        pre = s.get("precpu_stats") or {}
        if before is None and pre.get("system_cpu_usage"):  # a streamed sample carries its own baseline
            before = ((pre.get("cpu_usage") or {}).get("total_usage") or 0, pre["system_cpu_usage"])
        if before and system > before[1] and total >= before[0]:
            cpu_pct = round(100.0 * (total - before[0]) / (system - before[1]) * cpus, 1)
        prev[cid] = (total, system)
    mem = s.get("memory_stats") or {}
    limit = mem.get("limit")
    nets = (s.get("networks") or {}).values()
    blk = (s.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []
    return {
        "cpu_pct": cpu_pct,
        "mem_used": _mem_used(mem),
        "mem_limit": limit if limit and limit < 2**60 else None,  # "no limit" is a huge number
        "pids": (s.get("pids_stats") or {}).get("current"),
        "net_rx": _sum(nets, "rx_bytes") if nets else None,
        "net_tx": _sum(nets, "tx_bytes") if nets else None,
        "blk_read": sum(b.get("value") or 0 for b in blk if (b.get("op") or "").lower() == "read") if blk else None,
        "blk_write": sum(b.get("value") or 0 for b in blk if (b.get("op") or "").lower() == "write") if blk else None,
    }


def collect(client, running_ids: list[str]) -> dict[str, dict]:
    """container id -> stats, for running containers. Failures are skipped silently."""
    out = {}
    for cid in running_ids:
        try:
            doc = client.get(f"/containers/{quote(cid)}/stats?stream=false&one-shot=true")
        except Exception:
            continue
        if isinstance(doc, dict):
            out[cid] = parse(cid, doc)
    for gone in set(_prev) - set(running_ids):
        _prev.pop(gone, None)
    return out
