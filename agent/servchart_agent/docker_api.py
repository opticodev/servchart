"""Minimal, dependency-free, read-only client for the Docker Engine API.

Only GET requests are ever issued. Supports unix sockets (default) and plain
TCP (e.g. a docker-socket-proxy sidecar) via the standard DOCKER_HOST variable.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
from urllib.parse import quote, urlparse

DEFAULT_DOCKER_HOST = "unix:///var/run/docker.sock"


class DockerError(RuntimeError):
    pass


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 10.0):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:  # pragma: no cover - exercised against a real daemon
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


class DockerClient:
    """Read-only Docker Engine API client."""

    def __init__(self, docker_host: str | None = None, timeout: float = 10.0):
        self.docker_host = docker_host or os.environ.get("DOCKER_HOST") or DEFAULT_DOCKER_HOST
        self.timeout = timeout
        parsed = urlparse(self.docker_host)
        if parsed.scheme == "unix":
            self._target = ("unix", parsed.path)
        elif parsed.scheme in ("tcp", "http"):
            self._target = ("tcp", (parsed.hostname or "localhost", parsed.port or 2375))
        else:
            raise DockerError(f"Unsupported DOCKER_HOST scheme: {self.docker_host!r} (use unix:// or tcp://)")

    def _connection(self) -> http.client.HTTPConnection:
        kind, target = self._target
        if kind == "unix":
            return _UnixHTTPConnection(target, timeout=self.timeout)
        host, port = target
        return http.client.HTTPConnection(host, port, timeout=self.timeout)

    def get(self, path: str):
        conn = self._connection()
        try:
            conn.request("GET", path, headers={"Accept": "application/json"})
            resp = conn.getresponse()
            body = resp.read()
        except OSError as exc:
            raise DockerError(f"Cannot reach Docker at {self.docker_host}: {exc}") from exc
        finally:
            conn.close()
        if resp.status >= 400:
            raise DockerError(f"Docker API GET {path} -> HTTP {resp.status}: {body[:200]!r}")
        return json.loads(body or b"null")

    # Convenience wrappers -------------------------------------------------
    def info(self):
        return self.get("/info")

    def version(self):
        return self.get("/version")

    def containers(self):
        return self.get("/containers/json?all=1")

    def inspect_container(self, container_id: str):
        return self.get(f"/containers/{quote(container_id)}/json")

    def networks(self):
        return self.get("/networks")
