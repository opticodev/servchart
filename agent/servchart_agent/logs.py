"""On-demand container logs, for the hub's log viewer.

Opt-in per host with SERVCHART_ALLOW_LOGS=1. Logs are read only when an admin asks for
them in the hub, are capped (lines and bytes), and pass through a redaction step that
masks the most common secret patterns before leaving the host. Redaction is best effort -
that's why the feature is off by default.
"""

from __future__ import annotations

import os
import re
import struct

MAX_LINES = 2000
MAX_BYTES = 1024 * 1024  # what we send to the hub
READ_LIMIT = 4 * 1024 * 1024  # what we read from Docker

# (pattern, replacement) - replacements keep the key so lines stay readable
REDACT_RULES = [
    # key=value / key: value where the key looks secret
    (re.compile(r"(?i)\b([\w.-]*(?:pass(?:word|wd)?|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)[\w.-]*[\"']?\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&\"']+)"),
     r"\1[redacted]"),
    # Authorization headers
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*(?:bearer|basic|token)\s+)[A-Za-z0-9._~+/=-]+"), r"\1[redacted]"),
    # credentials in URLs: scheme://user:pass@host
    (re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+@"), r"\1[redacted]@"),
    # JSON Web Tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[redacted-jwt]"),
]


def redaction_enabled() -> bool:
    return os.environ.get("SERVCHART_LOGS_REDACT", "1").lower() not in ("0", "false", "no", "off")


def redact(line: str) -> str:
    for pattern, replacement in REDACT_RULES:
        line = pattern.sub(replacement, line)
    return line


def demux(raw: bytes, tty: bool) -> list[tuple[str, str]]:
    """Split Docker's log stream into (stream, line).

    Without a TTY, Docker multiplexes stdout/stderr in frames:
    [stream(1) 0 0 0 size(4, big-endian)] payload.  With a TTY it's one raw stream.
    """
    if tty:
        return [("out", ln) for ln in raw.decode("utf-8", "replace").splitlines()]
    out, i = [], 0
    buffers = {1: "", 2: ""}
    while i + 8 <= len(raw):
        stream, size = raw[i], struct.unpack(">I", raw[i + 4 : i + 8])[0]
        chunk = raw[i + 8 : i + 8 + size].decode("utf-8", "replace")
        i += 8 + size
        key = 2 if stream == 2 else 1
        text = buffers[key] + chunk
        *lines, rest = text.split("\n")
        buffers[key] = rest
        out.extend(("err" if key == 2 else "out", ln) for ln in lines)
    for key, rest in buffers.items():
        if rest:
            out.append(("err" if key == 2 else "out", rest))
    return out


def fetch(client, container: str, tail: int = 200, since: int | None = None) -> dict:
    """Read, split, cap and redact a container's recent logs."""
    tail = max(1, min(int(tail or 200), MAX_LINES))
    info = client.inspect_container(container)
    tty = bool((info.get("Config") or {}).get("Tty"))
    raw = client.logs(info.get("Id") or container, tail=tail, since=since, limit=READ_LIMIT)
    redact_on = redaction_enabled()
    lines, size, truncated = [], 0, len(raw) >= READ_LIMIT
    for stream, text in demux(raw, tty)[-tail:]:
        ts, _, msg = text.partition(" ")
        if not ts[:4].isdigit():
            ts, msg = "", text  # line without a timestamp prefix
        if redact_on:
            msg = redact(msg)
        size += len(msg) + 40
        if size > MAX_BYTES:
            truncated = True
            break
        lines.append({"t": ts, "s": stream, "m": msg})
    return {"lines": lines, "truncated": truncated, "redacted": redact_on, "tty": tty}
