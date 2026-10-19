import { Handle, Position } from "@xyflow/react";

const hidden = { opacity: 0, pointerEvents: "none" };

function fmtBytes(n) {
  if (!n) return "";
  const gb = n / 2 ** 30;
  return gb >= 1 ? `${gb.toFixed(gb >= 10 ? 0 : 1)} GB` : `${Math.round(n / 2 ** 20)} MB`;
}

export function HostNode({ data, selected }) {
  const info = data.info || {};
  return (
    <div className={`host-node status-${data.status} ${selected ? "is-selected" : ""}`}>
      <Handle type="target" position={Position.Top} style={hidden} />
      <Handle id="out" type="source" position={Position.Right} style={hidden} />
      <Handle id="in" type="target" position={Position.Left} style={hidden} />
      <div className="host-head">
        <span className={`dot dot-${data.status}`} title={data.status} />
        <div className="host-title">
          <strong>{data.name}</strong>
          <span className="muted">
            {[info.os, info.cpus && `${info.cpus} CPU`, fmtBytes(info.memory_bytes)].filter(Boolean).join(" · ")}
          </span>
        </div>
        {data.info?.observe === "on" && (
          <span className="badge badge-live" title="Observed traffic is on for this host">
            traffic
          </span>
        )}
        <span className="badge">
          {data.counts.running}/{data.counts.containers} running
        </span>
      </div>
      {data.status === "pending" && <div className="host-empty">Waiting for the agent's first report…</div>}
    </div>
  );
}

export function NetworkNode({ data, selected }) {
  return (
    <div className={`network-node ${data.internal ? "is-internal" : ""} ${data.local ? "is-local" : ""} ${selected ? "is-selected" : ""}`} title={(data.subnets || []).join(", ")}>
      <Handle type="target" position={Position.Bottom} style={hidden} />
      <span className="net-icon" aria-hidden>⇄</span>
      <span className="net-name">{data.name}</span>
      <span className="net-count">{data.attached}</span>
    </div>
  );
}

export function ContainerNode({ data, selected }) {
  const published = (data.ports || []).filter((p) => p.public);
  const state = data.health === "unhealthy" ? "unhealthy" : data.state;
  return (
    <div className={`container-node state-${state} ${data.dimmed ? "is-dimmed" : ""} ${selected ? "is-selected" : ""}`}>
      <Handle type="source" position={Position.Top} style={hidden} />
      <Handle type="target" position={Position.Top} style={hidden} />
      <Handle id="out" type="source" position={Position.Right} style={hidden} />
      <Handle id="in" type="target" position={Position.Left} style={hidden} />
      <div className="ctr-top">
        <span className={`dot dot-${state}`} title={state} />
        <span className="ctr-name" title={data.name}>{data.name}</span>
      </div>
      <div className="ctr-sub" title={data.image}>
        {data.compose?.project ? <span className="chip">{data.compose.project}</span> : null}
        <span className="ctr-image">{data.image}</span>
      </div>
      {published.length > 0 && (
        <div className="ctr-ports">
          {published.slice(0, 3).map((p) => (
            <span key={`${p.public}-${p.private}-${p.protocol}`} className="port">:{p.public}</span>
          ))}
          {published.length > 3 && <span className="port">+{published.length - 3}</span>}
        </div>
      )}
    </div>
  );
}

function shortPath(p) {
  if (!p) return "";
  return p.length > 38 ? "…" + p.slice(-37) : p;
}

export function StackNode({ data, selected }) {
  const allUp = data.running === data.total;
  return (
    <div className={`stack-node ${data.standalone ? "is-standalone" : ""} ${data.dimmed ? "is-dimmed" : ""} ${selected ? "is-selected" : ""}`}>
      <div className="stack-head">
        <span className="stack-icon" aria-hidden>
          {data.standalone ? "▢" : "▤"}
        </span>
        <div className="stack-title">
          <strong title={data.name || "Standalone containers"}>{data.standalone ? "Standalone containers" : data.name}</strong>
          <span className="muted mono-small" title={data.working_dir || ""}>
            {data.standalone ? "not started by Compose" : shortPath(data.working_dir) || "folder unknown"}
          </span>
        </div>
        <span className={`stack-count ${allUp ? "" : "is-partial"}`}>
          {data.running}/{data.total}
        </span>
      </div>
    </div>
  );
}

export const nodeTypes = { host: HostNode, network: NetworkNode, stack: StackNode, container: ContainerNode };
