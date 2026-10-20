# ServChart

**Map your servers, containers and how they connect.**

ServChart draws a live, zoomable map of every Docker host you run: the hosts, their Compose stacks and the folders they live in, networks, containers, published ports and health. Install one small agent per host, open the hub, and the map builds itself.

*ServChart by [OptiCoDev](https://github.com/opticodev).*

> **Status: early (v0.3).** Hosts, stacks, networks, containers, ports and health are mapped, along with who talks to whom, on one host and across hosts. Reverse-proxy routes are next (see [Roadmap](#roadmap)).

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
docker run -d --name servchart-agent --restart unless-stopped --pid host \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e SERVCHART_OBSERVE_CONNECTIONS=1 \
  -e SERVCHART_HUB=https://servchart.example.com \
  -e SERVCHART_TOKEN=sc_... \
  opticodev/servchart-agent:latest
```

Images are on Docker Hub ([`opticodev/servchart-hub`](https://hub.docker.com/r/opticodev/servchart-hub), [`opticodev/servchart-agent`](https://hub.docker.com/r/opticodev/servchart-agent)) and mirrored on GitHub as `ghcr.io/opticodev/servchart-hub` and `ghcr.io/opticodev/servchart-agent`, for anyone who hits Docker Hub's pull limits.

The agent connects **out** to the hub. Hosts don't open any ports, so it works for cloud VMs and machines behind NAT. It reports every 60 seconds.

No Docker for the agent? It's also on PyPI: `pipx install servchart-agent`, then `servchart-agent --hub ... --token ...`. The user running it needs access to the Docker socket.

## Stacks

Containers started by Docker Compose (including Portainer and Dockge stacks) are grouped into a box per stack. The box shows the stack's folder, and clicking it lists its compose files and the state of each service. Everything else goes in a **Standalone containers** box. Turn grouping off with **Group by stack** in the toolbar. ServChart reads this from the labels Compose puts on every container, so it never needs access to your compose files.

## Who talks to whom

ServChart draws two kinds of lines between containers:

| Line | Where it comes from | Needs |
|---|---|---|
| **Dashed purple arrow: depends on** | Compose's `depends_on`, which Compose records in a container label | nothing |
| **Blue arrow with port: traffic** | Live TCP connections, read from the kernel's per-container tables (what `ss -tn` shows) every report | `SERVCHART_OBSERVE_CONNECTIONS=1` and `--pid host` |
| **Orange arrow: traffic to another server** | The same, when the destination is another host running an agent, on a port one of its containers publishes (or the host itself) | the same, plus the destination host reporting to the same hub |

How a destination is matched:

1. **A container IP on the same host:** that container.
2. **An address of another host:** a container publishing that port there, otherwise the host itself (for example a database or NFS running outside Docker).
3. **Anything else:** listed as "Unknown" in the container's details.

Host processes (say, nginx installed on the host) get lines from the host box. Connections are aggregated per destination and port, and only **private** destinations are reported (`SERVCHART_OBSERVE_PUBLIC=1` to include public ones).

The **Links** menu chooses what to draw:

- **Overview** (the default): one line per pair of stacks on a server and one per pair of servers, labeled with the ports. Click a server, stack or container to see its own lines in full, including Compose dependencies and lines inside a stack.
- **Every connection:** every traffic and dependency line, plus network attachments for whatever you've selected.
- **Everything:** network attachments too.
- **Selection only.**

Networks used by a single stack are drawn inside that stack. Only shared networks sit at the top of the host.

## Users, hosts and settings

Open **Settings** from the top-right menu:

- **Hosts:** rename, disable (the token stops working, history stays), issue a new token, delete.
- **Users** (admins): add people as **Admin** or **Viewer**, reset passwords, deactivate, delete. A blank password generates one and shows it once. You can't remove your own admin rights or delete yourself.
- **Appearance** (admins): your own name, accent color, logo and favicon. Used in the top bar, the browser tab, the sign-in page and reports.
- **Reports** (admins): download or email the report, and schedule it (see below).
- **Activity** (admins): who viewed logs, changed hosts, users, appearance or report settings, when, and from where.
- **My account:** change your password.

Viewers see the map and reports; admins can also add and manage hosts and users and view logs. The Django admin (`/admin/`) is still there as a fallback.

## Container logs

Admins can open a container and click **View logs**: the last 100 to 2000 lines, with filtering, a stderr-only switch, follow mode and download. Lines from stderr are shown in red.

Log viewing is **off by default** on every host. Turn it on per host with `SERVCHART_ALLOW_LOGS=1` on that host's agent (or on the hub for the hub's own host). Then:

- The hub never connects to your servers. The agent checks for log requests every few seconds over its existing outbound connection and sends back only the requested lines.
- Nothing is stored. The lines are deleted as soon as they've been shown, and unread requests expire after 5 minutes.
- The agent redacts secret-looking values before sending: `PASSWORD=…`, `token: …`, `Authorization` headers, credentials in URLs and JWTs. Set `SERVCHART_LOGS_REDACT=0` to turn that off.
- Only admins can view logs, and every view is recorded in **Settings → Activity**.
- Only existing containers can be asked for, and the agent can't be asked to do anything else.

## Reports

**Report** in the top-right menu (or **Settings → Reports**) gives you:

- **A printable page** (`/report/`). It shows a summary, findings, the inventory per host and stack, and who talks to whom. Use **Print → Save as PDF** to get a PDF.
- **CSV exports:** containers, published ports, connections and findings.
- **JSON** of the whole report, for scripts.
- **Email:** send it now, or every day, every Monday or on the 1st of each month at `SERVCHART_REPORT_HOUR` (default 07:00, hub time zone `TZ`). The email has a summary, the full report and the JSON attached.

Findings flag things worth a look. Each has a severity:

| Severity | Findings |
|---|---|
| High | Hosts that stopped reporting; unhealthy containers; containers stuck restarting |
| Medium | Containers stopped despite a restart policy; containers restarted 5+ times |
| Low | No restart policy; images not pinned to a version (`:latest` or no tag) |
| Info | Ports published on every interface; connections to unknown addresses; traffic not observed |

Email needs an SMTP server:

```yaml
    environment:
      SERVCHART_SMTP_HOST: smtp.example.com
      SERVCHART_SMTP_PORT: "587"             # STARTTLS; use 465 with SERVCHART_SMTP_SSL=1
      SERVCHART_SMTP_USER: servchart@example.com
      SERVCHART_SMTP_PASSWORD: app-password
      SERVCHART_SMTP_FROM: "ServChart <servchart@example.com>"
      SERVCHART_PUBLIC_URL: https://servchart.example.com   # links in the email
```

## Single sign-on

ServChart works with the identity provider you already run, in either of two standard ways. Local accounts and passwords keep working alongside both.

### Option 1: OpenID Connect (recommended)

This adds a **Sign in with …** button to the login page. It works with any OpenID Connect provider: Authentik, Keycloak, Authelia, Zitadel, Kanidm, Pocket ID, Google, Microsoft Entra ID, Okta and others.

1. At your provider, create an OIDC client of type confidential / web app, with authorization code flow. Its redirect URI is `https://<your-servchart>/auth/oidc/callback`.
2. Configure the hub:

```env
SERVCHART_PUBLIC_URL=https://servchart.example.com
SERVCHART_OIDC_ISSUER=https://auth.example.com/application/o/servchart/   # the provider's issuer URL
SERVCHART_OIDC_CLIENT_ID=...
SERVCHART_OIDC_CLIENT_SECRET=...
SERVCHART_OIDC_PROVIDER_NAME=Authentik                                   # button text
SERVCHART_SSO_ADMIN_GROUPS=servchart-admins                              # optional
```

Where the issuer URL comes from, for some common providers:

| Provider | Issuer URL looks like | Groups |
|---|---|---|
| Authentik | `https://auth.example.com/application/o/<app-slug>/` | in the default `profile` scope as `groups` |
| Keycloak | `https://kc.example.com/realms/<realm>` | add a "Group Membership" mapper named `groups` |
| Authelia | `https://auth.example.com` | add `groups` to `SERVCHART_OIDC_SCOPES` |
| Zitadel | `https://<instance>.zitadel.cloud` | roles via `SERVCHART_OIDC_GROUPS_CLAIM` |
| Google | `https://accounts.google.com` | no groups; set `SERVCHART_OIDC_USERNAME_CLAIM=email` |
| Microsoft Entra ID | `https://login.microsoftonline.com/<tenant-id>/v2.0` | enable group claims in the app registration |

How it works and stays safe:

- **Authorization code flow** with PKCE, plus `state` and `nonce` checks.
- **The ID token is fetched by the hub itself**, directly from the provider over verified HTTPS, then checked for issuer, audience, expiry and nonce (as allowed by OIDC Core §3.1.3.7, with no extra crypto libraries).
- **HTTPS is required** for the provider.
- **Sign out** also ends the provider session when the provider supports it.
- Set `SERVCHART_PASSWORD_LOGIN=0` to show only the SSO button. `/login/?local=1` still shows the password form for emergencies.

### Option 2: trusted proxy headers (forward auth)

Use this if a proxy already authenticates every request and passes the username in a header. ServChart can then sign people in from that header, with no second login:

```env
SERVCHART_SSO_HEADER=Remote-User            # username header (see table)
SERVCHART_SSO_GROUPS_HEADER=Remote-Groups   # optional
SERVCHART_SSO_EMAIL_HEADER=Remote-Email     # optional
SERVCHART_SSO_TRUSTED_PROXIES=10.0.0.5      # the proxy's address(es), IPs or CIDRs - required
SERVCHART_SSO_LOGOUT_URL=https://auth.example.com/logout   # optional
```

Header names for common proxies:

| Proxy | Username | Groups | Email |
|---|---|---|---|
| Authentik (forward auth) | `X-authentik-username` | `X-authentik-groups` | `X-authentik-email` |
| Authelia | `Remote-User` | `Remote-Groups` | `Remote-Email` |
| oauth2-proxy (`--set-xauthrequest`) | `X-Auth-Request-User` | `X-Auth-Request-Groups` | `X-Auth-Request-Email` |
| Tailscale serve | `Tailscale-User-Login` | – | – |
| Pomerium / Caddy / Traefik forward auth | whatever your setup forwards | | |

> **Security: read this before turning it on.** Anyone who can send a request to ServChart **directly from a trusted proxy address** with that header becomes that user. So:
> 1. Only list your proxy in `SERVCHART_SSO_TRUSTED_PROXIES`, and keep the hub's port unreachable from elsewhere if you can.
> 2. The proxy must **set or clear** the header on **every** route. That includes routes that skip authentication, like the agent endpoint. ServChart already ignores the header on `/api/v1/report` and `/healthz`, but for nginx, add this to every `location` without `auth_request`:
>    ```nginx
>    proxy_set_header Remote-User "";   # use your header names
>    ```

### Both modes

- **Accounts are created on first sign-in.** `SERVCHART_SSO_CREATE_USERS=0` allows only people you've added in Settings.
- **`SERVCHART_SSO_ADMIN_GROUPS`:** members are admins, re-checked at every sign-in for SSO accounts. Accounts with a local password keep the role you gave them in Settings.

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
- **Logs (opt-in, on request):** the lines an admin asks for, with secret-looking values redacted. Not stored by the hub.
- **Traffic (opt-in):** destination IP, port and connection count for private destinations. No source ports, no payloads, no DNS names.
- **Redacted:** label values whose key contains `pass`, `secret`, `token`, `key`, `auth`, `credential`, `cookie` or `private` are replaced with `[redacted]`. The hub applies the same rules again on its side, so a modified agent can't store more.
- **Optional:** set `SERVCHART_HIDE_PATHS=1` on the agent to drop bind-mount host paths and stack folders.

Host tokens are stored only as SHA-256 hashes. Each host has its own token. Disable or rotate it at any time from the map or the admin.

**About the Docker socket.** The agent's code only reads, but any container with `/var/run/docker.sock` mounted can technically control Docker, and `:ro` doesn't change that. If that matters to you, put a read-only socket proxy in between and point the agent at it:

```bash
docker run -d --name dockerproxy -e CONTAINERS=1 -e NETWORKS=1 -e INFO=1 -e VERSION=1 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro --network servchart tecnativa/docker-socket-proxy
docker run -d --name servchart-agent --network servchart -e DOCKER_HOST=tcp://dockerproxy:2375 \
  -e SERVCHART_HUB=... -e SERVCHART_TOKEN=... opticodev/servchart-agent:latest
```

**About logs.** Container logs can contain anything an application prints. That's why viewing them is opt-in per host, admin-only, audited, redacted on the host and never stored by the hub. If you use a socket proxy, it needs `CONTAINERS=1`, which covers `/containers/{id}/logs`.

**About `--pid host`.** Traffic observation reads `/proc/<pid>/net/tcp` of each container, which requires seeing the host's processes. An agent that has the Docker socket can already start privileged containers, so `--pid host` adds little real power. Leave both the flag and `SERVCHART_OBSERVE_CONNECTIONS` off if you only want the map without traffic lines.

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
| `SERVCHART_OIDC_ISSUER` / `_CLIENT_ID` / `_CLIENT_SECRET` | – | OpenID Connect sign-in (see "Single sign-on") |
| `SERVCHART_OIDC_PROVIDER_NAME` | `single sign-on` | Button text: "Sign in with …" |
| `SERVCHART_OIDC_SCOPES` | `openid profile email` | Scopes to request |
| `SERVCHART_OIDC_USERNAME_CLAIM` / `_GROUPS_CLAIM` | `preferred_username` / `groups` | Claims to read |
| `SERVCHART_OIDC_TOKEN_AUTH` | `client_secret_basic` | Or `client_secret_post` |
| `SERVCHART_SSO_HEADER` + `SERVCHART_SSO_TRUSTED_PROXIES` | – | Trusted-header sign-in (both required) |
| `SERVCHART_SSO_GROUPS_HEADER` / `_EMAIL_HEADER` | – | Optional headers for groups / email |
| `SERVCHART_SSO_ADMIN_GROUPS` | – | Groups whose members are admins (both modes) |
| `SERVCHART_SSO_CREATE_USERS` | `1` | Create accounts on first SSO sign-in |
| `SERVCHART_SSO_LOGOUT_URL` | – | Header mode: where "Sign out" goes |
| `SERVCHART_PASSWORD_LOGIN` | `1` | `0` hides the password form (still at `/login/?local=1`) |
| `SERVCHART_AGENT_IMAGE` | `opticodev/servchart-agent:latest` | Image shown in the install command |
| `SERVCHART_ALLOW_LOGS` | `0` | Let admins view logs of the hub's own host's containers |
| `SERVCHART_SMTP_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_FROM` | – / `587` | SMTP server for report emails |
| `SERVCHART_SMTP_SSL` / `SERVCHART_SMTP_STARTTLS` | `0` / `1` | Implicit TLS (port 465) / STARTTLS (port 587) |
| `SERVCHART_REPORT_HOUR` | `7` | Hour (0-23, hub time zone `TZ`) scheduled reports go out |
| `SERVCHART_REPORT_SCHEDULER` | `1` | `0` to never send scheduled reports from this container |

### Agent

| Variable | Default | Purpose |
|---|---|---|
| `SERVCHART_HUB` | – | Hub URL (required) |
| `SERVCHART_TOKEN` | – | Host token (required) |
| `SERVCHART_INTERVAL` | `60` | Seconds between reports |
| `SERVCHART_HOSTNAME` | Docker's host name | Name reported for the host |
| `SERVCHART_HIDE_PATHS` | `0` | Don't send bind-mount host paths or stack folders |
| `SERVCHART_OBSERVE_CONNECTIONS` | `0` | Report live TCP connections (traffic lines). Needs `--pid host` in a container |
| `SERVCHART_OBSERVE_PUBLIC` | `0` | Also report connections to public IPs |
| `SERVCHART_ALLOW_LOGS` | `0` | Let hub admins view this host's container logs (on demand, audited) |
| `SERVCHART_LOGS_REDACT` | `1` | Redact secret-looking values in log lines before sending |
| `SERVCHART_COMMAND_POLL` | `3` | Seconds between checks for log requests (only when logs are allowed) |
| `SERVCHART_HOST_IPS` | auto | Extra addresses of this host (e.g. its public IP), so other hosts' connections to it resolve |
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

See [docs/RELEASING.md](docs/RELEASING.md). In short: bump the version, then push a `vX.Y.Z` tag. GitHub Actions publishes both images to Docker Hub and GHCR, and the agent to PyPI.

## Roadmap

- [x] Who-talks-to-whom: Compose dependencies and observed traffic, on one host and across hosts (v0.3)
- [x] Settings page, single sign-on, container logs, branding, reports and an activity log (v0.3)
- [ ] Reverse-proxy routes from Traefik labels and nginx configs (domain → container)
- [ ] Live status push (WebSockets) instead of 15 s polling
- [ ] Snapshot history and "what changed" diff
- [ ] Export the map as SVG/PNG

## License

[MIT](LICENSE) © OptiCoDev
