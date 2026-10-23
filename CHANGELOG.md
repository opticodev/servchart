# Changelog

## 0.4.2

- **Fix:** on a fresh visit the map could stay zoomed in on the first server instead of fitting everything on screen; it now fits once the cards have been measured.
- **Fix:** pointing at a container didn't recolour its lines to other servers (they stayed orange); they now turn blue (calls) and green (called by) like the others.
- README: animated demo and screenshots (from the fictional demo hosts), "Why ServChart", how it compares with tools you may already use, and a short security summary.

## 0.4.1

- **Angled lines.** Connections are drawn with horizontal and vertical segments and rounded corners instead of curves. Switch back with **Lines: curved** in the legend.
- **Lines go around cards.** Lines are routed through the gaps between cards, stacks and servers (down the middle where there is room) instead of across them, with as few bends as possible; lines sharing a gap are spread apart. Columns of containers are a little further apart to make room. While you drag a card, lines are drawn simply and re-routed when you let go. Lines between servers only pass through their own two servers and otherwise use the gaps between server boxes, and lines going the same way are bundled into one path, like cables in a tray. **Lines: curved** follows the same routes with wide, smooth turns.
- **See where lines go.** Point at a container: lines it calls turn blue, lines calling it turn green, the rest fade. Point at a line to see "from → to" with its ports. Lines are drawn above the cards, and parallel lines are spread apart instead of merging into one.
- **Laid out by dependencies.** Stacks on a server are ordered like the containers inside them: stacks that call others on the left, the stacks they depend on to the right. Containers are reordered within each column to cross fewer lines, and long chains keep their first steps in separate columns. Servers are arranged the same way: servers that call others on the left, a server many others send to (a log or security server, say) on the right, so lines between servers run left to right instead of looping around.
- **Fewer labels.** Port labels show when there are only a few lines, on the selection's lines, or when you hover a line, instead of piling up.
- "Reports to ServChart" lines only appear for the selected server (or with Links: everything), so they no longer cross the whole map.

## 0.4.0

- **Server health.** CPU, RAM and fullest disk on every server box (orange at 85%, red at 95%); load, uptime, swap and every disk in the details. Needs the host root mounted read-only for all disks (`-v /:/host:ro,rslave -e SERVCHART_HOST_ROOT=/host`, now in the install command).
- **Container resources.** CPU and memory on every container (from Docker's stats), network traffic and volume sizes in the details.
- **Docker storage.** Images, volumes (largest and unused), container layers and build cache per server.
- **Backups, any tool.** Backup jobs drop a status file in `/var/lib/servchart/status`; servers show ok / overdue / failed. `servchart-agent --mark NAME` writes one.
- **Certificate checks.** Settings → Checks: the hub watches TLS endpoints and warns 14 days before expiry or when a certificate isn't trusted.
- **Image updates.** The hub asks registries whether running tags point to newer images and whether newer versions exist; ↑ on the map, list in Settings → Checks. `SERVCHART_IMAGE_CHECKS=0` turns it off.
- **Your public addresses.** Settings → Hosts: list your router's public IP or DDNS name. Connections from outside servers to it (through port forwards) are drawn to the container publishing that port, and the hub tells agents to report those connections.
- **Agent links.** Each agent's connection to the hub is drawn as a dotted "reports to ServChart" line, even when it goes through a proxy such as Cloudflare.
- **History.** 7 days of 5-minute samples; 24 h graphs in the details panel.
- **Reports** gain server health, biggest containers, backups, certificates, image updates and "what changed in 24 h", new findings (disk full, memory, load, swap, failed/overdue backups, certificates, updates, unused volumes, build cache), and CSV exports for hosts, backups, certificates and updates.

## 0.3.1

- **Calmer map.** New default "Links: overview": one line per pair of stacks on a host and one per pair of servers, with ports merged ("· 3 links"). Lines inside a stack and Compose dependencies appear when you select something. Moving dashes only on the selection. The previous behaviour is "Links: every connection".
- **Containers arranged by who talks to whom.** Inside a stack, callers sit on the left and what they call on the right (web → app → database), so lines run left to right instead of across the box.
- A Compose dependency that is also seen as traffic is drawn once.
- The account menu now looks like one (☰ name ▾), and a **Report** button sits next to it.
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
