import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, MarkerType, MiniMap, ReactFlow, ReactFlowProvider, applyNodeChanges, useReactFlow } from "@xyflow/react";
import { api } from "./api.js";
import { filterEdges, layoutGraph } from "./layout.js";
import { nodeTypes } from "./components/nodes.jsx";
import DetailsPanel from "./components/DetailsPanel.jsx";
import AddHostDialog from "./components/AddHostDialog.jsx";
import Legend from "./components/Legend.jsx";
import LogViewer from "./components/LogViewer.jsx";
import Settings from "./components/Settings.jsx";

const REFRESH_MS = 15000;

function useStored(key, initial) {
  const [value, setValue] = useState(() => {
    try {
      const v = localStorage.getItem(key);
      return v === null ? initial : JSON.parse(v);
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable */
    }
  }, [key, value]);
  return [value, setValue];
}

// Name, accent color, logo and favicon from Settings -> Appearance.
function applyBranding(b) {
  if (!b) return;
  document.title = b.app_name || "ServChart";
  const root = document.documentElement.style;
  if (b.accent_color) root.setProperty("--accent", b.accent_color);
  else root.removeProperty("--accent");
  if (b.favicon_url) {
    let link = document.querySelector('link[rel="icon"]');
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.appendChild(link);
    }
    link.href = b.favicon_url;
  }
}

function portLabel(d) {
  const ports = d.ports || [];
  const shown = ports.slice(0, 3).map((p) => ":" + p).join(" ") + (ports.length > 3 ? ` +${ports.length - 3}` : "");
  return d.aggregated && d.links > 1 ? `${shown} · ${d.links} links` : shown;
}

function closeMenu(e) {
  const d = e.currentTarget.closest("details");
  if (d) d.open = false;
}

function MapView() {
  const [graph, setGraph] = useState(null);
  const [me, setMe] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [hostFilter, setHostFilter] = useStored("servchart.hostFilter", "all");
  const [hideStopped, setHideStopped] = useStored("servchart.hideStopped", false);
  const [groupStacks, setGroupStacks] = useStored("servchart.groupStacks", true);
  const [linkMode, setLinkMode] = useStored("servchart.linkMode", "overview");
  const [selectedId, setSelectedId] = useState(null);
  const [dialog, setDialog] = useState(null); // {mode:'add'} | {mode:'rotate', host}
  const [view, setView] = useState(() => (window.location.hash === "#settings" ? "settings" : "map"));
  const [settingsRev, setSettingsRev] = useState(0); // remounts Settings after the add-host dialog
  const [branding, setBranding] = useState(null);
  const [logs, setLogs] = useState(null); // {hostPk, hostName, container}
  const loadBranding = useCallback(() => api.branding().then((b) => { setBranding(b); applyBranding(b); }).catch(() => {}), []);
  useEffect(() => {
    loadBranding();
  }, [loadBranding]);
  useEffect(() => {
    const want = view === "settings" ? "#settings" : "";
    if (window.location.hash !== want) window.history.replaceState(null, "", window.location.pathname + want);
  }, [view]);
  const [nodes, setNodes] = useState([]);
  const dragged = useRef({}); // node id -> position the user dragged it to
  const fitted = useRef(false);
  const { fitView } = useReactFlow();

  const load = useCallback(async () => {
    try {
      setGraph(await api.graph());
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    api.me().then(setMe).catch(() => {});
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  const laid = useMemo(() => (graph ? layoutGraph(graph, { hideStopped, query, hostFilter, groupStacks }) : { nodes: [], edges: [] }), [graph, hideStopped, query, hostFilter, groupStacks]);

  useEffect(() => {
    setNodes(laid.nodes.map((n) => (dragged.current[n.id] ? { ...n, position: dragged.current[n.id] } : n)).map((n) => ({ ...n, selected: n.id === selectedId })));
  }, [laid, selectedId]);

  useEffect(() => {
    if (!fitted.current && laid.nodes.length) {
      fitted.current = true;
      requestAnimationFrame(() => fitView({ padding: 0.08 }));
    }
  }, [laid, fitView]);

  useEffect(() => {
    fitted.current = false; // refit when the host filter or grouping changes
    dragged.current = {}; // positions from the other layout no longer make sense
  }, [hostFilter, groupStacks]);

  const onNodesChange = useCallback((changes) => {
    for (const c of changes) if (c.type === "position" && c.position) dragged.current[c.id] = c.position;
    setNodes((ns) => applyNodeChanges(changes, ns));
  }, []);

  const edges = useMemo(() => {
    const shown = filterEdges(laid.edges, nodes.length ? nodes : laid.nodes, linkMode, selectedId);
    return shown.map((e) => {
      const d = e.data;
      const active = selectedId && (e.source === selectedId || e.target === selectedId);
      const cls = `${e.className}${d.cross_host ? " edge-cross" : ""}${active ? " is-active" : ""}`;
      if (d.kind === "flow") {
        return {
          ...e,
          className: cls,
          sourceHandle: "out",
          targetHandle: "in",
          animated: !!active, // moving dashes only on the selection's lines
          label: portLabel(d),
          labelShowBg: true,
          labelBgPadding: [4, 2],
          labelBgBorderRadius: 4,
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
          zIndex: 5,
        };
      }
      if (d.kind === "depends") {
        return { ...e, className: cls, sourceHandle: "out", targetHandle: "in", markerEnd: { type: MarkerType.Arrow, width: 14, height: 14 }, zIndex: 4 };
      }
      return { ...e, className: cls, animated: !!active };
    });
  }, [laid, nodes, linkMode, selectedId]);

  const selectedNode = useMemo(() => graph?.nodes.find((n) => n.id === selectedId) || null, [graph, selectedId]);
  const selectedHost = useMemo(() => (selectedNode ? graph.nodes.find((n) => n.id === selectedNode.host)?.data || null : null), [graph, selectedNode]);
  const hosts = graph?.hosts || [];
  const totals = hosts.reduce((a, h) => ({ c: a.c + h.counts.containers, r: a.r + h.counts.running, s: a.s + (h.counts.stacks || 0) }), { c: 0, r: 0, s: 0 });

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          {branding?.logo_url ? (
            <img src={branding.logo_url} alt="" />
          ) : (
            <span className="logo" aria-hidden>
              ◆
            </span>
          )}
          {branding?.app_name || "ServChart"}
        </div>
        <div className="stats muted">
          {hosts.length} hosts · {totals.s} stacks · {totals.r}/{totals.c} containers running
        </div>
        <div className="toolbar">
          <input className="search" type="search" placeholder="Search name, image, stack, folder, port…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select value={hostFilter} onChange={(e) => setHostFilter(e.target.value)} aria-label="Host">
            <option value="all">All hosts</option>
            {hosts.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
          <select value={linkMode} onChange={(e) => setLinkMode(e.target.value)} aria-label="Links" title="Which lines to draw">
            <option value="overview">Links: overview</option>
            <option value="smart">Links: every connection</option>
            <option value="all">Links: everything</option>
            <option value="selected">Links: selection only</option>
          </select>
          <label className="toggle">
            <input type="checkbox" checked={groupStacks} onChange={(e) => setGroupStacks(e.target.checked)} /> Group by stack
          </label>
          <label className="toggle">
            <input type="checkbox" checked={hideStopped} onChange={(e) => setHideStopped(e.target.checked)} /> Hide stopped
          </label>
          {me?.is_staff && (
            <button className="btn" onClick={() => setDialog({ mode: "add" })}>
              + Add host
            </button>
          )}
          <details className="menu">
            <summary>{me?.username || "…"}</summary>
            <div className="menu-items">
              <button type="button" onClick={(e) => { closeMenu(e); setView("settings"); }}>
                Settings
              </button>
              <div className="menu-sep" />
              <div className="menu-label">Report</div>
              <a href="/report/" target="_blank" rel="noopener" onClick={closeMenu}>
                Printable report / PDF
              </a>
              <a href="/api/v1/report.json?download=1" onClick={closeMenu}>
                Download JSON
              </a>
              <a href="/api/v1/report/containers.csv" onClick={closeMenu}>
                Containers (CSV)
              </a>
              <a href="/api/v1/report/connections.csv" onClick={closeMenu}>
                Connections (CSV)
              </a>
              <a href="/api/v1/report/findings.csv" onClick={closeMenu}>
                Findings (CSV)
              </a>
              <div className="menu-sep" />
              {me?.is_staff && <a href="/admin/">Django admin</a>}
              <form method="post" action="/logout/">
                <input type="hidden" name="csrfmiddlewaretoken" value={api.csrfToken()} />
                <button type="submit">Sign out</button>
              </form>
            </div>
          </details>
        </div>
      </header>

      {error && <div className="banner">Couldn't refresh: {error}</div>}

      <main className="canvas">
        {graph && hosts.length === 0 ? (
          <div className="empty">
            <h2>No hosts yet</h2>
            <p className="muted">Mount the Docker socket into the hub to map this machine, or add a host to install an agent.</p>
            {me?.is_staff && (
              <button className="btn" onClick={() => setDialog({ mode: "add" })}>
                + Add host
              </button>
            )}
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onNodeClick={(_, n) => setSelectedId(n.id)}
            onPaneClick={() => setSelectedId(null)}
            nodesConnectable={false}
            minZoom={0.1}
            maxZoom={2}
            proOptions={{ hideAttribution: false }}
          >
            <Background gap={24} size={1} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable nodeStrokeWidth={2} />
          </ReactFlow>
        )}
        {graph && hosts.length > 0 && <Legend hosts={hosts} linkMode={linkMode} />}
        {view === "settings" && me && (
          <Settings
            key={settingsRev}
            me={me}
            onClose={() => setView("map")}
            onAdd={() => setDialog({ mode: "add" })}
            onRotate={(h) => setDialog({ mode: "rotate", host: h })}
            onBranding={loadBranding}
          />
        )}
        <DetailsPanel
          node={selectedNode}
          host={selectedHost}
          onClose={() => setSelectedId(null)}
          isStaff={me?.is_staff}
          onRotate={(h) => setDialog({ mode: "rotate", host: h })}
          onLogs={(node, host) => setLogs({ hostPk: host.pk, hostName: host.name, container: node.data.name })}
        />
      </main>

      {logs && <LogViewer {...logs} onClose={() => setLogs(null)} />}

      {dialog && (
        <AddHostDialog
          rotateHost={dialog.mode === "rotate" ? dialog.host : null}
          onClose={() => {
            setDialog(null);
            setSettingsRev((r) => r + 1);
          }}
          onDone={load}
        />
      )}
    </div>
  );
}

export default function App() {
  return (
    <ReactFlowProvider>
      <MapView />
    </ReactFlowProvider>
  );
}
