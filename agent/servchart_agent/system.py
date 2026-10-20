"""Server health: CPU, memory, load, uptime and disk usage, read from the kernel.

/proc/stat, /proc/meminfo, /proc/loadavg and /proc/uptime describe the whole machine even
inside a container, so they need nothing special. Disks are different: a container only
sees its own mounts. The agent reports

  * every real filesystem of the host when it can see the host's root: natively, or in a
    container with the host's / mounted read-only (`-v /:/host:ro` + SERVCHART_HOST_ROOT=/host);
  * otherwise just the filesystem holding Docker's data (the agent container's own root
    lives there), which is usually the one that fills up.

Nothing here reads file contents; only sizes and mount points are reported.
"""

from __future__ import annotations

import os
import time

from .connections import PROC, _in_container

# Filesystems worth reporting; pseudo, overlay and squashfs (snaps) are skipped.
REAL_FS = {
    "ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs", "vfat", "exfat",
    "ntfs", "ntfs3", "fuseblk", "nfs", "nfs4", "cifs", "smb3", "ceph", "glusterfs", "fuse.mergerfs",
    "fuse.sshfs", "apfs", "hfs", "hfsplus",
}
SKIP_PREFIXES = ("/proc", "/sys", "/dev", "/run", "/snap", "/var/lib/docker", "/var/lib/containerd", "/var/snap")
MAX_DISKS = 30

_prev_cpu: tuple[int, int] | None = None  # (busy, total) jiffies from the last report


def _read(path: str) -> str | None:
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None


def cpu_times(text: str | None = None) -> tuple[int, int] | None:
    """(busy, total) jiffies from the first line of /proc/stat."""
    text = text if text is not None else _read(f"{PROC}/stat")
    if not text:
        return None
    parts = text.splitlines()[0].split()
    if parts[0] != "cpu":
        return None
    values = [int(v) for v in parts[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
    total = sum(values[:8])  # guest time is already counted in user/nice
    return total - idle, total


def cpu_percent() -> float | None:
    """Average CPU use since the previous report (or over a short sample on the first one)."""
    global _prev_cpu
    now = cpu_times()
    if now is None:
        return None
    before = _prev_cpu
    if before is None:
        time.sleep(0.5)
        before, now = now, cpu_times() or now
    _prev_cpu = now
    busy, total = now[0] - before[0], now[1] - before[1]
    return round(100.0 * busy / total, 1) if total > 0 else None


def meminfo(text: str | None = None) -> dict:
    text = text if text is not None else _read(f"{PROC}/meminfo") or ""
    kb = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        fields = rest.split()
        if fields and fields[0].isdigit():
            kb[key] = int(fields[0]) * 1024
    total = kb.get("MemTotal")
    available = kb.get("MemAvailable", kb.get("MemFree"))
    return {
        "mem_total": total,
        "mem_available": available,
        "swap_total": kb.get("SwapTotal"),
        "swap_free": kb.get("SwapFree"),
    }


def loadavg(text: str | None = None) -> list[float] | None:
    text = text if text is not None else _read(f"{PROC}/loadavg")
    try:
        return [float(v) for v in text.split()[:3]]
    except (AttributeError, ValueError):
        return None


def uptime(text: str | None = None) -> int | None:
    text = text if text is not None else _read(f"{PROC}/uptime")
    try:
        return int(float(text.split()[0]))
    except (AttributeError, ValueError, IndexError):
        return None


def host_root() -> str | None:
    """Where the host's filesystem is visible: "/" natively, SERVCHART_HOST_ROOT in a container."""
    configured = os.environ.get("SERVCHART_HOST_ROOT")
    if configured:
        return configured.rstrip("/") or "/"
    return None if _in_container() else "/"


def parse_mounts(text: str) -> list[tuple[str, str, str]]:
    """(device, mount point, fs type) of real filesystems, one per device, shortest mount point first."""
    seen, out = set(), []
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mount, fstype = parts[0], parts[1].replace("\\040", " "), parts[2]
        if fstype not in REAL_FS or mount.startswith(SKIP_PREFIXES):
            continue
        rows.append((device, mount, fstype))
    for device, mount, fstype in sorted(rows, key=lambda r: (len(r[1]), r[1])):
        if device in seen:  # bind mounts of the same filesystem
            continue
        seen.add(device)
        out.append((device, mount, fstype))
    return out[:MAX_DISKS]


def _usage(path: str) -> tuple[int, int] | None:
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    total = st.f_blocks * st.f_frsize
    if total <= 0:
        return None
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    return total, used


def _disk(mount: str, fstype: str, usage: tuple[int, int]) -> dict:
    total, used = usage
    # percentage as df shows it: used / (used + available to users)
    return {"mount": mount, "fs": fstype, "total": total, "used": used, "pct": round(100.0 * used / total, 1)}


def disks(docker_root: str | None = None) -> tuple[list[dict], str]:
    """(disks, source). source is "host" (all real filesystems) or "docker" (Docker's data only)."""
    root = host_root()
    if root:
        text = _read(f"{PROC}/1/mounts") or _read(os.path.join(root, "proc/1/mounts")) or _read("/proc/mounts") or ""
        out = []
        for _device, mount, fstype in parse_mounts(text):
            path = mount if root == "/" else root + mount
            usage = _usage(path)
            if usage:
                out.append(_disk(mount, fstype, usage))
        if out:
            return out, "host"
    # In a container without the host's root: our own "/" sits on Docker's data filesystem.
    usage = _usage("/")
    if usage:
        return [_disk(docker_root or "/var/lib/docker", "docker", usage)], "docker"
    return [], "none"


def health(docker_root: str | None = None) -> dict:
    disk_list, source = disks(docker_root)
    return {
        "cpu_pct": cpu_percent(),
        "load": loadavg(),
        "uptime_s": uptime(),
        **meminfo(),
        "disks": disk_list,
        "disk_source": source,
    }
