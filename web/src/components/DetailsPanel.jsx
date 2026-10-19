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
