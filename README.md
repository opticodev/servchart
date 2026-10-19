# ServChart

**Map your servers, containers and how they connect.**

ServChart draws a live, zoomable map of every Docker host you run: the hosts, their Compose stacks and the folders they live in, networks, containers, published ports and health. Install one small agent per host, open the hub, and the map builds itself.

*ServChart by [OptiCoDev](https://github.com/opticodev).*

> **Status: early (v0.1).** Hosts, networks, containers, ports, mounts and health are mapped. Cross-host links and reverse-proxy routes are next (see [Roadmap](#roadmap)).

## Quick start

```bash
git clone https://github.com/opticodev/servchart.git
cd servchart
docker compose up -d
docker compose logs hub | grep -A3 "admin created"   # first-start admin password
```

Open <http://localhost:8484> and sign in. The hub maps its own host right away through the mounted Docker socket.

Want to look around first? Set `SERVCHART_DEMO: "1"` in `docker-compose.yml` to load three fictional demo hosts.

## Add another host

In the map, click **+ Add host**, give it a name, and run the command it shows on that host:

```bash
docker run -d --name servchart-agent --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e SERVCHART_HUB=https://servchart.example.com \
  -e SERVCHART_TOKEN=sc_... \
  ghcr.io/opticodev/servchart-agent:latest
```

The agent connects **out** to the hub. Hosts don't open any ports, so it works for cloud VMs and machines behind NAT. It reports every 60 seconds.

No Docker for the agent? It's also on PyPI: `pipx install servchart-agent`, then `servchart-agent --hub ... --token ...`. The user running it needs access to the Docker socket.

## Stacks

Containers started by Docker Compose (including Portainer and Dockge stacks) are grouped into a box per stack. The box shows the stack's folder, and clicking it lists its compose files and the state of each service. Everything else goes in a **Standalone containers** box. Turn grouping off with **Group by stack** in the toolbar. ServChart reads this from the labels Compose puts on every container, so it never needs access to your compose files.

## How it works

```
 host A                 host B                     hub (Django + React)
┌──────────────┐       ┌──────────────┐           ┌───────────────────────┐
│ agent ──GET──┼─docker│ agent        │  HTTPS    │ /api/v1/report  ◄─────┼── agents (Bearer token)
│   │          │       │   │          │ ────────► │ /api/v1/graph   ─────►│── map UI (login)
└───┼──────────┘       └───┼──────────┘           │ local collector       │── maps the hub's own host
    └──────── POST snapshot every 60s ───────────►└───────────────────────┘
```

- **Agent** (`agent/`): Python standard library only, with no dependencies. It reads the Docker Engine API (GET requests only), builds a sanitized snapshot and POSTs it to the hub.
- **Hub** (`hub/`): Django + Django REST Framework. It stores the latest snapshot per host (SQLite by default, PostgreSQL optional) and turns them into a graph.
- **Web** (`web/`): React + [React Flow](https://reactflow.dev). Built into static files that Django serves, so the hub is a single container.

## Privacy & security

What leaves a host:

- **Sent:** container names, images, state and health, networks and IPs, published ports, mount points, restart policy, Compose project, service, folder and compose file paths, and labels.
- **Never sent:** environment variables (they're never read), container commands and arguments, and file contents.
- **Redacted:** label values whose key contains `pass`, `secret`, `token`, `key`, `auth`, `credential`, `cookie` or `private` are replaced with `[redacted]`. The hub applies the same rules again on its side, so a modified agent can't store more.
- **Optional:** set `SERVCHART_HIDE_PATHS=1` on the agent to drop bind-mount host paths and stack folders.

Host tokens are stored only as SHA-256 hashes. Each host has its own token. Disable or rotate it at any time from the map or the admin.

**About the Docker socket.** The agent's code only reads, but any container with `/var/run/docker.sock` mounted can technically control Docker, and `:ro` doesn't change that. If that matters to you, put a read-only socket proxy in between and point the agent at it:

```bash
docker run -d --name dockerproxy -e CONTAINERS=1 -e NETWORKS=1 -e INFO=1 -e VERSION=1 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro --network servchart tecnativa/docker-socket-proxy
docker run -d --name servchart-agent --network servchart -e DOCKER_HOST=tcp://dockerproxy:2375 \
  -e SERVCHART_HUB=... -e SERVCHART_TOKEN=... ghcr.io/opticodev/servchart-agent:latest
```

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## Configuration

### Hub

| Variable | Default | Purpose |
|---|---|---|
| `SERVCHART_ADMIN_USER` / `SERVCHART_ADMIN_PASSWORD` | `admin` / random | First admin account. The random password is printed in the logs once. |
| `SERVCHART_PUBLIC_URL` | request URL | URL agents use to reach the hub. It's shown in the install command. |
| `SERVCHART_ALLOWED_HOSTS` | `*` | Django `ALLOWED_HOSTS`, comma-separated |
| `SERVCHART_CSRF_TRUSTED_ORIGINS` | – | Needed when the hub is served over HTTPS behind a proxy |
| `SERVCHART_BEHIND_PROXY` / `SERVCHART_SECURE_COOKIES` | `0` | Trust `X-Forwarded-Proto` / use secure cookies |
| `SERVCHART_LOCAL_AGENT` | `1` | Map the hub's own host when the socket is mounted |
| `SERVCHART_STALE_AFTER` | `300` | Seconds without a report before a host shows as stale |
| `SERVCHART_DB` | `sqlite` | `postgres` to use `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` |
| `SERVCHART_DEMO` | `0` | Load fictional demo hosts on start |
| `SERVCHART_AGENT_IMAGE` | `ghcr.io/opticodev/servchart-agent:latest` | Image shown in the install command |

### Agent

| Variable | Default | Purpose |
|---|---|---|
| `SERVCHART_HUB` | – | Hub URL (required) |
| `SERVCHART_TOKEN` | – | Host token (required) |
| `SERVCHART_INTERVAL` | `60` | Seconds between reports |
| `SERVCHART_HOSTNAME` | Docker's host name | Name reported for the host |
| `SERVCHART_HIDE_PATHS` | `0` | Don't send bind-mount host paths or stack folders |
| `SERVCHART_CA_FILE` / `SERVCHART_INSECURE` | – | Custom CA for a self-signed hub / skip TLS checks (not recommended) |
| `DOCKER_HOST` | `unix:///var/run/docker.sock` | Or `tcp://dockerproxy:2375` |

Run `python -m servchart_agent --stdout` to print exactly what the agent would send, without sending anything.

## Development

```bash
# hub
cd hub && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
SERVCHART_DEBUG=1 python manage.py migrate && python manage.py createsuperuser
SERVCHART_DEBUG=1 PYTHONPATH=../agent python manage.py runserver      # :8000
python manage.py test inventory

# web (hot reload, proxies /api to :8000)
cd web && npm install && npm run dev

# agent
cd agent && python -m unittest discover -s tests
```

## Releasing

See [docs/RELEASING.md](docs/RELEASING.md). In short: bump the version, then push a `vX.Y.Z` tag. GitHub Actions publishes both images to GHCR and the agent to PyPI.

## Roadmap

- [ ] Cross-host links (e.g. a client container talking to a service published on another host)
- [ ] Reverse-proxy routes from Traefik labels and nginx configs (domain → container)
- [ ] Live status push (WebSockets) instead of 15 s polling
- [ ] Snapshot history and "what changed" diff
- [ ] Export the map as SVG/PNG
- [ ] Multi-arch agent and hub images published to GHCR

## License

[MIT](LICENSE) © OptiCoDev
