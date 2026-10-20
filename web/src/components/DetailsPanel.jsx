import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Meter, Sparkline, fmtBytes, fmtDuration, level, memPct } from "./health.jsx";

// History for the selected host, refreshed every 5 minutes while the panel is open.
function useHistory(hostPk) {
  const [hist, setHist] = useState(null);
  useEffect(() => {
    if (!hostPk) return undefined;
    let alive = true;
    const load = () => api.hostHistory(hostPk, 24).then((h) => alive && setHist(h)).catch(() => {});
    load();
    const t = setInterval(load, 300000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [hostPk]);
  return hist;
}

function Pill({ state, children }) {
  return <span className={`state-pill pill-${state}`}>{children || state}</span>;
}

function Row({ label, children }) {
  if (children === null || children === undefined || children === "" || (Array.isArray(children) && !children.length)) return null;
  return (
    <div className="row">
      <div className="row-label">{label}</div>
      <div className="row-value">{children}</div>
    </div>
  );
}

function ago(iso) {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

// Observed outbound connections, resolved to containers/hosts where possible.
function Talks({ items, unresolved, observed, title = "Talks to" }) {
  if (!observed) return null;
  const known = items || [];
  const other = unresolved || [];
  return (
    <>
      <Row label={title}>
        {known.length === 0 && other.length === 0 ? <span className="muted">no outbound connections right now</span> : null}
        {known.map((t) => (
          <div key={`${t.target}-${t.port}`} className="mono">
            {t.name}:{t.port} <span className="muted">×{t.count}</span>
          </div>
        ))}
      </Row>
      <Row label="Unknown">
        {other.map((t) => (
          <div key={`${t.ip}-${t.port}`} className="mono" title="Not a container or host ServChart knows about">
            {t.ip}:{t.port} <span className="muted">×{t.count}</span>
          </div>
        ))}
      </Row>
    </>
  );
}

function LogsButton({ host, onLogs }) {
  const on = host?.info?.logs === "on";
  return (
    <div className="btn-row">
      <button
        className="btn btn-small"
        disabled={!on}
        onClick={onLogs}
        title={on ? "Show this container's recent logs" : "Log viewing is off on this host: start its agent (or the hub, for its own host) with SERVCHART_ALLOW_LOGS=1"}
      >
        View logs
      </button>
      {!on && <span className="muted small">off on this host (SERVCHART_ALLOW_LOGS=1)</span>}
    </div>
  );
}

function ContainerResources({ d, host }) {
  const hist = useHistory(d.stats ? host?.pk : null);
  const series = hist?.containers?.[d.name];
  const st = d.stats;
  if (!st) return null;
  const vols = new Map((host?.storage?.volumes || []).map((v) => [v.name, v.size]));
  const sized = (d.mounts || []).filter((m) => m.type === "volume" && vols.get(m.source) !== undefined);
  return (
    <>
      <Row label="CPU">
        {st.cpu_pct === null || st.cpu_pct === undefined ? "–" : `${st.cpu_pct}%`}
        {series && <Sparkline values={series.cpu} label="CPU, last 24 h" />}
      </Row>
      <Row label="Memory">
        {fmtBytes(st.mem_used)}
        {st.mem_limit ? <span className="muted"> of {fmtBytes(st.mem_limit)} limit</span> : null}
        {series && <Sparkline values={series.mem} label="Memory, last 24 h" />}
      </Row>
      <Row label="Network">{st.net_rx !== null && st.net_rx !== undefined ? `${fmtBytes(st.net_rx)} in · ${fmtBytes(st.net_tx)} out (since start)` : null}</Row>
      <Row label="Volumes">
        {sized.map((m) => (
          <div key={m.source} className="mono small">
            {m.source} <span className="muted">· {fmtBytes(vols.get(m.source))}</span>
          </div>
        ))}
      </Row>
    </>
  );
}

function ImageUpdate({ u }) {
  if (!u) return null;
  return (
    <Row label="Image">
      {u.state === "update" && <Pill state="update">update</Pill>} {u.state === "update" ? "a newer image is published for this tag" : u.state === "current" ? "up to date with its tag" : `couldn't check${u.error ? `: ${u.error}` : ""}`}
      {u.newer_tag && <div className="small">Version <span className="mono">{u.newer_tag}</span> is available</div>}
    </Row>
  );
}

function ContainerDetails({ d, host, isStaff, onLogs }) {
  const labels = Object.entries(d.labels || {}).filter(([k]) => !k.startsWith("com.docker.compose."));
  return (
    <>
      <h2>{d.name}</h2>
      <p className="muted mono">{d.image}</p>
      {isStaff && <LogsButton host={host} onLogs={onLogs} />}
      <Row label="State">
        {d.state}
        {d.health ? ` · ${d.health}` : ""}
      </Row>
      <Row label="Started">{d.started_at && d.state === "running" ? ago(d.started_at) : null}</Row>
      <ImageUpdate u={d.image_update} />
      <ContainerResources d={d} host={host} />
      <Row label="Stack">{d.compose?.project ? `${d.compose.project} / ${d.compose.service}` : null}</Row>
      <Row label="Folder">{d.compose?.working_dir ? <span className="mono">{d.compose.working_dir}</span> : null}</Row>
      <Row label="Restart">
        {d.restart_policy ? `${d.restart_policy}${d.restart_count ? ` · restarted ${d.restart_count}×` : ""}` : d.restart_count ? `restarted ${d.restart_count}×` : null}
      </Row>
      <Row label="Depends on">{(d.compose?.depends_on || []).length ? d.compose.depends_on.join(", ") : null}</Row>
      <Talks items={d.talks_to} unresolved={d.talks_to_unresolved} observed={"connections" in d} />
      <Row label="Network mode">{d.network_mode && !(d.networks || []).some((n) => n.name === d.network_mode) ? d.network_mode : null}</Row>
      <Row label="Networks">
        {(d.networks || []).map((n) => (
          <div key={n.name} className="mono">
            {n.name}
            {n.ip ? <span className="muted"> · {n.ip}</span> : null}
          </div>
        ))}
      </Row>
      <Row label="Ports">
        {(d.ports || []).map((p) => (
          <div key={`${p.private}-${p.protocol}-${p.public}`} className="mono">
            {p.public ? `${(p.ips || []).includes("127.0.0.1") ? "127.0.0.1:" : ""}${p.public} → ` : "internal "}
            {p.private}/{p.protocol}
          </div>
        ))}
      </Row>
      <Row label="Mounts">
        {(d.mounts || []).map((m, i) => (
          <div key={i} className="mono">
            {m.source || `(${m.type})`} → {m.destination}
            {m.rw ? "" : <span className="muted"> · ro</span>}
          </div>
        ))}
      </Row>
      {labels.length > 0 && (
        <details>
          <summary>Labels ({labels.length})</summary>
          {labels.map(([k, v]) => (
            <div key={k} className="mono small">
              <span className="muted">{k}</span> = {String(v)}
            </div>
          ))}
        </details>
      )}
    </>
  );
}

function HostHealth({ d }) {
  const h = d.info?.health;
  const hist = useHistory(h ? d.pk : null);
  if (!h) {
    return d.status === "online" ? <p className="muted small">Update this host's agent to 0.4+ to see CPU, memory, disks and backups.</p> : null;
  }
  const mp = memPct(h);
  return (
    <>
      <h3>Health</h3>
      <Row label="CPU">
        <Meter label="" pct={h.cpu_pct} warn={80} bad={95} />
        <span className="muted small"> load {(h.load || []).map((v) => v.toFixed(2)).join(" ")}</span>
        {hist && <Sparkline values={hist.cpu} max={100} label="CPU, last 24 h" />}
      </Row>
      <Row label="Memory">
        <Meter label="" pct={mp} />
        <span className="muted small"> {fmtBytes(h.mem_total - h.mem_available)} of {fmtBytes(h.mem_total)}</span>
        {hist && <Sparkline values={hist.mem} max={hist.mem_total || h.mem_total} label="Memory, last 24 h" />}
      </Row>
      {h.swap_total ? <Row label="Swap">{fmtBytes(h.swap_total - h.swap_free)} of {fmtBytes(h.swap_total)}</Row> : null}
      <Row label="Up">{fmtDuration(h.uptime_s)}</Row>
      <Row label="Disks">
        {(h.disks || []).map((disk) => (
          <div key={disk.mount} className={`disk-row meter-${level(disk.pct)}`} title={`${disk.fs} · ${fmtBytes(disk.used)} used of ${fmtBytes(disk.total)}`}>
            <span className="mono">{disk.mount}</span>
            <span className="meter-bar">
              <span style={{ width: `${disk.pct}%` }} />
            </span>
            <span className="meter-value small">
              {Math.round(disk.pct)}% · {fmtBytes(disk.total - disk.used)} free
            </span>
          </div>
        ))}
        {h.disk_source === "docker" && <div className="muted small">Only Docker's disk is visible. Mount the host root (-v /:/host:ro, SERVCHART_HOST_ROOT=/host) to see all disks.</div>}
      </Row>
    </>
  );
}

function HostStorage({ s }) {
  if (!s) return null;
  return (
    <>
      <h3>Docker storage</h3>
      <Row label="Images">
        {fmtBytes(s.images_bytes)} <span className="muted">· {s.images_count} images{s.images_unused ? `, ${s.images_unused} unused` : ""}</span>
      </Row>
      <Row label="Volumes">
        {fmtBytes(s.volumes_bytes)} <span className="muted">· {s.volumes_count} volumes{s.volumes_unused ? `, ${s.volumes_unused} unused` : ""}</span>
      </Row>
      <Row label="Containers">{fmtBytes(s.containers_rw_bytes)}</Row>
      <Row label="Build cache">{s.build_cache_bytes ? fmtBytes(s.build_cache_bytes) : null}</Row>
      {(s.volumes || []).length > 0 && (
        <details>
          <summary>Largest volumes</summary>
          {s.volumes.slice(0, 15).map((v) => (
            <div key={v.name} className="mono small">
              {v.name} <span className="muted">· {fmtBytes(v.size)}{v.refs === 0 ? " · unused" : ""}</span>
            </div>
          ))}
        </details>
      )}
    </>
  );
}

function HostBackups({ items }) {
  if (!items) return null;
  return (
    <>
      <h3>Backups</h3>
      {items.length === 0 && <p className="muted small">No status files yet in /var/lib/servchart/status.</p>}
      {items.map((b) => (
        <Row key={b.name} label={b.name}>
          <Pill state={b.state} /> {b.age_hours !== null && b.age_hours !== undefined ? `${Math.round(b.age_hours)} h ago` : "time unknown"}
          {b.message ? <div className="muted small">{b.message}</div> : null}
        </Row>
      ))}
    </>
  );
}

function HostDetails({ d, isStaff, onRotate }) {
  const info = d.info || {};
  return (
    <>
      <h2>{d.name}</h2>
      <p className="muted">
        {d.is_local ? "This hub's own host" : "Agent host"} · {d.status}
      </p>
      <Row label="Last report">{ago(d.last_seen)}</Row>
      <Row label="Containers">
        {d.counts.running} running of {d.counts.containers}
      </Row>
      <Row label="OS">{info.os}</Row>
      <Row label="Kernel">{info.kernel}</Row>
      <Row label="Docker">{info.docker_version}</Row>
      <Row label="Agent">{d.agent_version}</Row>
      <Row label="Logs">{d.agent_version || d.is_local ? (info.logs === "on" ? "admins can view container logs" : "off (SERVCHART_ALLOW_LOGS=1 to allow)") : null}</Row>
      <Row label="Addresses">{(info.ips || []).join(", ") || null}</Row>
      <Row label="Traffic">
        {info.observe === "on"
          ? "observed"
          : info.observe === "unavailable"
            ? "enabled, but the agent can't see other processes: run it with --pid host"
            : "off (SERVCHART_OBSERVE_CONNECTIONS=1 to enable)"}
      </Row>
      <Talks items={info.talks_to} unresolved={info.talks_to_unresolved} observed={info.observe === "on"} title="Host processes talk to" />
      <HostHealth d={d} />
      <HostBackups items={d.backups} />
      <HostStorage s={d.storage} />
      {isStaff && !d.is_local && (
        <button className="btn btn-ghost" onClick={() => onRotate(d)}>
          Rotate token…
        </button>
      )}
    </>
  );
}

function NetworkDetails({ d }) {
  return (
    <>
      <h2>{d.name}</h2>
      <p className="muted">Docker network</p>
      <Row label="Driver">{d.driver}</Row>
      <Row label="Scope">{d.scope}</Row>
      <Row label="Subnets">{(d.subnets || []).join(", ")}</Row>
      <Row label="Internal">{d.internal ? "yes (no outside access)" : null}</Row>
      <Row label="Attached">{d.attached}</Row>
    </>
  );
}

function StackDetails({ d }) {
  return (
    <>
      <h2>{d.standalone ? "Standalone containers" : d.name}</h2>
      <p className="muted">{d.standalone ? "Containers not started by Docker Compose" : "Compose stack"}</p>
      <Row label="Running">
        {d.running} of {d.total}
      </Row>
      <Row label="Folder">{d.working_dir ? <span className="mono">{d.working_dir}</span> : d.standalone ? null : "unknown (older Compose or hidden by the agent)"}</Row>
      <Row label="Compose files">
        {(d.config_files || []).map((f) => (
          <div key={f} className="mono">
            {f}
          </div>
        ))}
      </Row>
      <Row label="Containers">
        <ul className="stack-list">
          {(d.containers || []).map((c) => (
            <li key={c.name}>
              <span className={`dot dot-${c.health === "unhealthy" ? "unhealthy" : c.state}`} />
              <span className="mono">{c.service || c.name}</span>
              {c.service && c.service !== c.name ? <span className="muted small">{c.name}</span> : null}
            </li>
          ))}
        </ul>
      </Row>
    </>
  );
}

export default function DetailsPanel({ node, host, onClose, isStaff, onRotate, onLogs }) {
  if (!node) return null;
  return (
    <aside className="details" aria-label="Details">
      <button className="close" onClick={onClose} aria-label="Close details">
        ×
      </button>
      {node.type === "container" && <ContainerDetails d={node.data} host={host} isStaff={isStaff} onLogs={() => onLogs(node, host)} />}
      {node.type === "host" && <HostDetails d={node.data} isStaff={isStaff} onRotate={onRotate} />}
      {node.type === "network" && <NetworkDetails d={node.data} />}
      {node.type === "stack" && <StackDetails d={node.data} />}
    </aside>
  );
}
