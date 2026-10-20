"""The report as one self-contained HTML page (inline CSS, logo as a data URI).

Used for the printable /report/ page (browser "Save as PDF") and the email body, so it
has no external resources and no scripts besides the optional print button.
Everything from agents is escaped.
"""

from __future__ import annotations

import base64
from datetime import datetime
from html import escape

DEFAULT_ACCENT = "#2563eb"
SEV_COLORS = {"high": "#dc2626", "medium": "#d97706", "low": "#2563eb", "info": "#64748b"}


def _e(value) -> str:
    return escape("" if value is None else str(value))


def _when(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso


def _gib(n) -> str:
    return f"{n / 1024 ** 3:.1f} GiB" if isinstance(n, (int, float)) and n else "-"


def _specs(h: dict) -> str:
    bits = [h.get("os"), f"Docker {h['docker_version']}" if h.get("docker_version") else None,
            f"{h['cpus']} CPU" if h.get("cpus") else None, _gib(h.get("memory_bytes")) if h.get("memory_bytes") else None]
    return " \u00b7 ".join(b for b in bits if b)


def _bar(pct) -> str:
    if pct is None:
        return "-"
    color = "#dc2626" if pct >= 95 else "#d97706" if pct >= 85 else "#16a34a"
    return (f'<span class="bar"><span style="width:{min(100, max(0, pct)):.0f}%;background:{color}"></span></span> '
            f'<span class="mono">{pct:.0f}%</span>')


def _dur(seconds) -> str:
    if not seconds:
        return "-"
    d, h = int(seconds // 86400), int(seconds % 86400 // 3600)
    return f"{d} d {h} h" if d else f"{h} h"


def _size(n) -> str:
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return "-"


STATE_COLORS = {"ok": "#16a34a", "current": "#16a34a", "overdue": "#d97706", "update": "#2563eb", "failed": "#dc2626", "unknown": "#64748b"}


def _pill(state: str) -> str:
    return f'<span class="sev" style="background:{STATE_COLORS.get(state, "#64748b")}">{_e(state)}</span>'


def _health_sections(report: dict) -> str:
    out = []
    if report.get("health"):
        out.append("<h2>Server health</h2>")
        rows = []
        for r in report["health"]:
            disks = "<br>".join(f'<span class="mono">{_e(d["mount"])}</span> {_bar(d.get("pct"))} <span class="muted">{_e(_size(d["total"] - d["used"]))} free</span>' for d in r["disks"]) or "-"
            if r.get("disk_source") == "docker":
                disks += '<br><span class="muted">Docker data only; mount the host root for all disks</span>'
            load = (r.get("load") or [None])[0]
            st = r.get("storage") or {}
            docker = f'{_e(_size(st.get("images_bytes")))} images · {_e(_size(st.get("volumes_bytes")))} volumes' if st else "-"
            rows.append(
                f'<tr><td><strong>{_e(r["host"])}</strong><br><span class="muted">up {_e(_dur(r.get("uptime_s")))}</span></td>'
                f'<td>{_bar(r.get("cpu_pct"))}<br><span class="muted">load {_e(f"{load:.2f}" if load is not None else "-")}{" / " + _e(r["cpus"]) + " CPU" if r.get("cpus") else ""}</span></td>'
                f'<td>{_bar(r.get("mem_pct"))}<br><span class="muted">of {_e(_size(r.get("mem_total")))}</span></td>'
                f"<td>{disks}</td><td>{docker}</td></tr>"
            )
        out.append(f"<table><thead><tr><th>Server</th><th>CPU</th><th>Memory</th><th>Disks</th><th>Docker</th></tr></thead><tbody>{''.join(rows)}</tbody></table>")
        if report.get("top_containers"):
            rows = ""
            for t in report["top_containers"]:
                cpu = f"{t['cpu_pct']:.1f}%" if t.get("cpu_pct") is not None else "-"
                rows += f'<tr><td class="mono">{_e(t["host"])} / {_e(t["container"])}</td><td>{_e(_size(t["mem_used"]))}</td><td>{_e(cpu)}</td></tr>'
            out.append(f"<h3>Biggest containers (memory)</h3><table><thead><tr><th>Container</th><th>Memory</th><th>CPU</th></tr></thead><tbody>{rows}</tbody></table>")
    if report.get("backups"):
        out.append("<h2>Backups</h2>")
        rows = ""
        for b in report["backups"]:
            ago = f"{b['age_hours']:.0f} h ago" if b.get("age_hours") is not None else ""
            rows += (
                f'<tr><td>{_e(b["host"])}</td><td class="mono">{_e(b["name"])}</td><td>{_pill(b["state"])}</td>'
                f'<td>{_e(_when(b.get("finished_at")))}<br><span class="muted">{_e(ago)}</span></td><td>{_e(b.get("message") or "")}</td></tr>'
            )
        out.append(f"<table><thead><tr><th>Server</th><th>Job</th><th>State</th><th>Last run</th><th>Note</th></tr></thead><tbody>{rows}</tbody></table>")
    if report.get("certificates"):
        out.append("<h2>Certificates</h2>")
        rows = []
        for c in report["certificates"]:
            days = c.get("days_left")
            state = "failed" if c.get("error") or (days is not None and days < 7) else "overdue" if days is not None and days < 14 else "ok"
            label = c["error"] or (f"{days} days left" if days is not None else "not checked yet")
            rows.append(f'<tr><td class="mono">{_e(c["hostname"])}{":" + _e(c["port"]) if c["port"] != 443 else ""}</td><td>{_pill(state)}</td><td>{_e(label)}</td><td>{_e(_when(c.get("expires_at")))}</td><td>{_e(c.get("issuer") or "")}</td></tr>')
        out.append(f"<table><thead><tr><th>Endpoint</th><th>State</th><th>Status</th><th>Expires</th><th>Issuer</th></tr></thead><tbody>{''.join(rows)}</tbody></table>")
    if report.get("updates"):
        out.append("<h2>Image updates</h2>")
        rows = "".join(
            f'<tr><td class="mono">{_e(u["host"])} / {_e(u["container"])}</td><td class="mono">{_e(u["image"])}</td><td>{_pill(u["state"])}</td><td class="mono">{_e(u.get("newer_tag") or "")}</td></tr>'
            for u in report["updates"]
        )
        out.append(f"<table><thead><tr><th>Container</th><th>Image</th><th>Tag</th><th>Newer version</th></tr></thead><tbody>{rows}</tbody></table>")
        out.append('<p class="muted">"update": the registry now has a different image under this tag (pull and recreate). "Newer version": a higher version tag exists.</p>')
    if report.get("changes"):
        out.append("<h2>What changed (last 24 h)</h2>")
        for host, ch in report["changes"].items():
            items = [f"added <span class=\"mono\">{_e(n)}</span>" for n in ch["added"]]
            items += [f"removed <span class=\"mono\">{_e(n)}</span>" for n in ch["removed"]]
            items += [f"<span class=\"mono\">{_e(x['name'])}</span>: {_e(x['from'])} → {_e(x['to'])}" for x in ch["image_changed"]]
            out.append(f"<h3>{_e(host)}</h3><ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
    return "".join(out)


def logo_data_uri(data: bytes | None, ctype: str | None) -> str | None:
    if not data or not ctype:
        return None
    return f"data:{ctype};base64,{base64.b64encode(bytes(data)).decode()}"


def render(report: dict, app_name: str = "ServChart", accent: str | None = None, logo_uri: str | None = None,
           version: str = "", printable: bool = True, base_url: str = "") -> str:
    accent = accent or DEFAULT_ACCENT
    s = report["summary"]
    parts = [f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(report['title'])}</title>
<style>
:root {{ --accent: {_e(accent)}; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #0f172a; background: #fff; }}
.page {{ max-width: 1000px; margin: 0 auto; padding: 28px 24px 48px; }}
header {{ display: flex; align-items: center; gap: 14px; border-bottom: 3px solid var(--accent); padding-bottom: 14px; }}
header img {{ height: 40px; max-width: 160px; object-fit: contain; }}
header h1 {{ font-size: 22px; margin: 0; }}
header .meta {{ color: #64748b; font-size: 12px; }}
header .spacer {{ flex: 1; }}
.btn {{ background: var(--accent); color: #fff; border: 0; border-radius: 6px; padding: 8px 14px; font: inherit; cursor: pointer; text-decoration: none; }}
.btn.ghost {{ background: transparent; color: var(--accent); border: 1px solid var(--accent); }}
h2 {{ font-size: 16px; margin: 28px 0 10px; color: var(--accent); }}
h3 {{ font-size: 14px; margin: 18px 0 6px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(112px, 1fr)); gap: 10px; margin-top: 18px; }}
.tile {{ border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; }}
.tile b {{ display: block; font-size: 22px; }}
.tile span {{ color: #64748b; font-size: 12px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
th, td {{ text-align: left; padding: 5px 8px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
th {{ background: #f8fafc; font-weight: 600; }}
td.mono, .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; word-break: break-all; }}
.sev {{ display: inline-block; color: #fff; border-radius: 4px; padding: 0 6px; font-size: 11px; font-weight: 600; text-transform: uppercase; }}
.state-running {{ color: #16a34a; }} .state-exited, .state-dead {{ color: #dc2626; }} .state-restarting {{ color: #d97706; }}
.muted {{ color: #64748b; }}
.bar {{ display: inline-block; width: 70px; height: 7px; background: #e2e8f0; border-radius: 4px; overflow: hidden; vertical-align: middle; }}
.bar span {{ display: block; height: 100%; }}
.host {{ border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px; margin-bottom: 14px; break-inside: avoid-page; }}
.host-head {{ display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: baseline; }}
.host-head strong {{ font-size: 15px; }}
.empty {{ color: #64748b; font-style: italic; }}
footer {{ margin-top: 36px; color: #94a3b8; font-size: 11px; border-top: 1px solid #e2e8f0; padding-top: 10px; }}
@media print {{
  .noprint {{ display: none !important; }}
  .page {{ padding: 0; max-width: none; }}
  h2 {{ break-after: avoid; }}
  tr {{ break-inside: avoid; }}
}}
</style></head><body><div class="page">
<header>"""]
    if logo_uri:
        parts.append(f'<img src="{_e(logo_uri)}" alt="">')
    parts.append(f"""<div><h1>{_e(report['title'])}</h1><div class="meta">Generated {_e(_when(report.get('generated_at')))}</div></div>
<div class="spacer"></div>""")
    if printable:
        parts.append('<a class="btn ghost noprint" href="/">Back to map</a> <button class="btn noprint" onclick="window.print()">Print / Save as PDF</button>')
    elif base_url:
        parts.append(f'<a class="btn" href="{_e(base_url)}/report/">Open in {_e(app_name)}</a>')
    parts.append("</header>")

    f = s["findings"]
    tiles = [
        (f"{s['hosts_online']}/{s['hosts']}", "hosts online"),
        (s["stacks"], "stacks"),
        (f"{s['running']}/{s['containers']}", "containers running"),
        (s["unhealthy"], "unhealthy"),
        (s["published_ports"], "published ports"),
        (s["connections"], "observed links"),
        (f["high"] + f["medium"], "findings to review"),
    ]
    if s.get("disks_warn") is not None and report.get("health"):
        tiles.append((s["disks_warn"], "disks filling up"))
    if s.get("backups"):
        tiles.append((f"{s['backups'] - s['backups_bad']}/{s['backups']}", "backups on time"))
    if s.get("certs"):
        tiles.append((s["certs_bad"], "certificate problems"))
    if s.get("updates"):
        tiles.append((s["updates"], "image updates"))
    tiles += [
    ]
    parts.append('<div class="tiles">' + "".join(f'<div class="tile"><b>{_e(v)}</b><span>{_e(k)}</span></div>' for v, k in tiles) + "</div>")

    parts.append("<h2>Findings</h2>")
    if report["findings"]:
        rows = "".join(
            f'<tr><td><span class="sev" style="background:{SEV_COLORS[x["severity"]]}">{_e(x["severity"])}</span></td>'
            f'<td class="mono">{_e(x["target"])}</td><td>{_e(x["message"])}</td></tr>'
            for x in report["findings"]
        )
        parts.append(f"<table><thead><tr><th>Severity</th><th>Where</th><th>What</th></tr></thead><tbody>{rows}</tbody></table>")
    else:
        parts.append('<p class="empty">Nothing to report.</p>')

    parts.append(_health_sections(report))
    parts.append("<h2>Inventory</h2>")
    if not report["inventory"]:
        parts.append('<p class="empty">No hosts yet.</p>')
    for h in report["inventory"]:
        parts.append(
            f'<div class="host"><div class="host-head"><strong>{_e(h["host"])}</strong>'
            f'<span class="muted">{_e(h["status"])} &middot; last report {_e(_when(h["last_seen"]))}</span>'
            f'<span class="muted">{_e(_specs(h))}</span></div>'
        )
        if not h["stacks"]:
            parts.append('<p class="empty">No containers.</p>')
        for st in h["stacks"]:
            where = f' <span class="muted mono">{_e(st["working_dir"])}</span>' if st.get("working_dir") else ""
            parts.append(f"<h3>{_e(st['name'])}{where}</h3>")
            rows = "".join(
                f'<tr><td>{_e(c["name"])}</td><td class="mono">{_e(c["image"])}</td>'
                f'<td class="state-{_e(c["state"])}">{_e(c["state"])}{" &middot; " + _e(c["health"]) if c["health"] else ""}</td>'
                f'<td>{_e(c["restart_policy"] or "-")}{" (" + _e(c["restart_count"]) + "x)" if c["restart_count"] else ""}</td>'
                f'<td class="mono">{"<br>".join(_e(p) for p in c["ports"]) or "-"}</td></tr>'
                for c in st["containers"]
            )
            parts.append(f"<table><thead><tr><th>Container</th><th>Image</th><th>State</th><th>Restart</th><th>Ports</th></tr></thead><tbody>{rows}</tbody></table>")
        parts.append("</div>")

    parts.append("<h2>Who talks to whom</h2>")
    observed = [c for c in report["connections"] if c["kind"] == "observed"]
    declared = [c for c in report["connections"] if c["kind"] == "depends_on"]
    if observed:
        rows = "".join(
            f'<tr><td class="mono">{_e(c["source"])}</td><td class="mono">{_e(c["target"])}</td>'
            f'<td class="mono">{_e(", ".join(map(str, c["ports"])))}</td><td>{_e(c["count"])}</td><td>{"yes" if c["cross_host"] else ""}</td></tr>'
            for c in observed
        )
        parts.append(f"<table><thead><tr><th>From</th><th>To</th><th>Ports</th><th>Open connections</th><th>Across hosts</th></tr></thead><tbody>{rows}</tbody></table>")
    else:
        parts.append('<p class="empty">No observed traffic. Agents need --pid host and SERVCHART_OBSERVE_CONNECTIONS=1.</p>')
    if declared:
        parts.append("<h3>Declared dependencies (Compose depends_on)</h3>")
        rows = "".join(f'<tr><td class="mono">{_e(c["source"])}</td><td class="mono">{_e(c["target"])}</td></tr>' for c in declared)
        parts.append(f"<table><thead><tr><th>Service</th><th>Depends on</th></tr></thead><tbody>{rows}</tbody></table>")

    credit = f"{_e(app_name)} &middot; " if app_name != "ServChart" else ""
    parts.append(f'<footer>{credit}Made with ServChart {_e(version)} by OptiCoDev &middot; open source, MIT</footer></div></body></html>')
    return "".join(parts)
