# Changelog

## 0.3.1

- **Calmer map.** New default "Links: overview": one line per pair of stacks on a host and one per pair of servers, with ports merged ("· 3 links"). Lines inside a stack and Compose dependencies appear when you select something. Moving dashes only on the selection. The previous behaviour is "Links: every connection".
- **Fix:** "Is local" could be ticked on agent hosts in the Django admin, which made the hub write its own host's containers into one of them (a duplicate server on the map). The field is now read-only, the hub only writes to its own record, and upgrading resets the flag on agent hosts.

## 0.3.0

- **Who talks to whom.** Dashed arrows for Compose `depends_on`. With `SERVCHART_OBSERVE_CONNECTIONS=1` and `--pid host`, solid arrows show live TCP traffic between containers, labeled with the port. Traffic to another server running an agent is drawn host-to-host in orange, and host processes such as a host-installed nginx are included. Only private destinations are reported.
- **Cleaner map.** Networks used by a single stack are drawn inside the stack. A new **Links** menu (traffic & dependencies / everything / selection only) replaces the always-on network lines. Added a legend.
- **Details panel.** Shows "Depends on", "Talks to" (resolved names, ports, counts) and "Unknown" destinations, plus each host's addresses and traffic status.
- The "Add host" command now enables traffic observation.
- **Settings page:**
  - Hosts: rename, disable or enable, new token, delete.
  - Users: add as admin or viewer, reset password, deactivate, delete.
  - My account: change password.
  - Guards stop you from removing your own admin rights, deactivating yourself or deleting yourself.
- **Single sign-on, provider-neutral:**
  - **OpenID Connect** ("Sign in with …") for any compliant provider (Authentik, Keycloak, Authelia, Zitadel, Kanidm, Google, Entra ID, Okta…). Uses PKCE, state and nonce, server-side token exchange and provider sign-out. No new dependencies.
  - **Trusted proxy headers** for forward-auth setups, with configurable header names and recipes for Authentik, Authelia, oauth2-proxy and Tailscale. Only trusted from configured proxy addresses, and never on the agent or health endpoints.
  - **Shared:** accounts created on first sign-in, admin rights from groups, and an option to hide the password form.
- **Container logs (admins).** "View logs" in a container's details: last 100-2000 lines, filter, stderr only, follow and download. Opt-in per host with `SERVCHART_ALLOW_LOGS=1`. Agents fetch requests over their outbound connection and redact secret-looking values. The hub keeps nothing, and every view is recorded.
- **Your branding.** Name, accent color, logo and favicon in Settings → Appearance. They're used on the map, the sign-in page and reports. Uploads are checked by content, and SVGs with scripts are rejected.
- **Reports.**
  - A printable page / PDF with a summary, findings, inventory and connections.
  - CSV exports (containers, ports, connections, findings) and JSON.
  - Email now or daily, weekly or monthly over SMTP (`SERVCHART_SMTP_*`).
  - Findings include stale hosts, unhealthy, restarting or stopped containers, frequent restarts, missing restart policies, unpinned images, ports open on every interface and unknown destinations.
- **Activity log** (Settings → Activity) for log views and changes to hosts, users, appearance and reports.
- Container details show how often a container restarted.

## 0.2.0

- Stacks view: a box per Compose project with its folder and compose files, and a "Group by stack" toggle.
- Agent published to PyPI (`servchart-agent`); images on Docker Hub and GHCR (amd64 + arm64).

## 0.1.0

- First release: hub (Django + React Flow), agent, hosts / networks / containers / ports map.
