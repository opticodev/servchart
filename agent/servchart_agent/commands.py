"""Hub -> agent requests (currently: "show me this container's logs").

The agent never accepts inbound connections. Instead, when logs are allowed
(SERVCHART_ALLOW_LOGS=1), a background thread asks the hub every few seconds whether an
admin is waiting for something, does it, and posts the answer back. Each request is
re-checked here: only known request types, only containers that exist on this host.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from . import logs as logs_mod

log = logging.getLogger("servchart.agent.commands")


def logs_allowed() -> bool:
    return os.environ.get("SERVCHART_ALLOW_LOGS", "0").lower() in ("1", "true", "yes", "on")


def handle(client, command: dict) -> dict:
    """Run one command; returns the result payload (never raises)."""
    kind = command.get("type")
    try:
        if kind == "logs":
            if not logs_allowed():
                return {"ok": False, "error": "Logs are disabled on this host (SERVCHART_ALLOW_LOGS=0)."}
            name = str(command.get("container") or "")
            known = {(c.get("Names") or [""])[0].lstrip("/") for c in client.containers()}
            if name not in known:
                return {"ok": False, "error": f"No container named {name!r} on this host."}
            since = command.get("since")
            return {"ok": True, "result": logs_mod.fetch(client, name, tail=command.get("tail") or 200, since=int(since) if since else None)}
        return {"ok": False, "error": f"Unknown request type {kind!r}."}
    except Exception as exc:  # report the failure to the admin instead of dying
        log.warning("command %s failed: %s", command.get("id"), exc)
        return {"ok": False, "error": str(exc)[:500]}


def loop(client, request, interval: float = 3.0, stop: threading.Event | None = None) -> None:
    """Poll the hub for commands until `stop` is set. `request(method, path, body)` does the HTTP."""
    stop = stop or threading.Event()
    backoff = 0.0
    while not stop.is_set():
        try:
            pending = (request("GET", "/api/v1/agent/commands", None) or {}).get("commands") or []
            for cmd in pending:
                request("POST", f"/api/v1/agent/commands/{cmd['id']}/result", handle(client, cmd))
            backoff = 0.0
        except Exception as exc:
            backoff = min(max(backoff * 2, interval * 2), 60.0)
            log.debug("command poll failed: %s", exc)
        stop.wait(backoff or interval)


def start(client, request) -> threading.Thread | None:
    if not logs_allowed():
        return None
    interval = float(os.environ.get("SERVCHART_COMMAND_POLL", "3"))
    t = threading.Thread(target=loop, args=(client, request, interval), name="servchart-commands", daemon=True)
    t.start()
    log.info("log viewing enabled: checking the hub for requests every %ss", interval)
    return t
