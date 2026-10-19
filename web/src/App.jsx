import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, MiniMap, ReactFlow, ReactFlowProvider, applyNodeChanges, useReactFlow } from "@xyflow/react";
import { api } from "./api.js";
import { layoutGraph } from "./layout.js";
import { nodeTypes } from "./components/nodes.jsx";
import DetailsPanel from "./components/DetailsPanel.jsx";
import AddHostDialog from "./components/AddHostDialog.jsx";

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

function MapView() {
  const [graph, setGraph] = useState(null);
  const [me, setMe] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [hostFilter, setHostFilter] = useStored("servchart.hostFilter", "all");
  const [hideStopped, setHideStopped] = useStored("servchart.hideStopped", false);
  const [selectedId, setSelectedId] = useState(null);
  const [dialog, setDialog] = useState(null); // {mode:'add'} | {mode:'rotate', host}
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

  const laid = useMemo(() => (graph ? layoutGraph(graph, { hideStopped, query, hostFilter }) : { nodes: [], edges: [] }), [graph, hideStopped, query, hostFilter]);

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
    fitted.current = false; // refit when the host filter changes
  }, [hostFilter]);

  const onNodesChange = useCallback((changes) => {
    for (const c of changes) if (c.type === "position" && c.position) dragged.current[c.id] = c.position;
    setNodes((ns) => applyNodeChanges(changes, ns));
  }, []);

  const edges = useMemo(() => {
    if (!selectedId) return laid.edges;
    return laid.edges.map((e) => (e.source === selectedId || e.target === selectedId ? { ...e, animated: true, className: `${e.className} is-active` } : e));
  }, [laid.edges, selectedId]);

  const selectedNode = useMemo(() => graph?.nodes.find((n) => n.id === selectedId) || null, [graph, selectedId]);
  const hosts = graph?.hosts || [];
  const totals = hosts.reduce((a, h) => ({ c: a.c + h.counts.containers, r: a.r + h.counts.running }), { c: 0, r: 0 });

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>
            ◆
          </span>
          ServChart
        </div>
        <div className="stats muted">
          {hosts.length} hosts · {totals.r}/{totals.c} containers running
        </div>
        <div className="toolbar">
          <input className="search" type="search" placeholder="Search name, image, project, port…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select value={hostFilter} onChange={(e) => setHostFilter(e.target.value)} aria-label="Host">
            <option value="all">All hosts</option>
            {hosts.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
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
              {me?.is_staff && <a href="/admin/">Admin</a>}
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
        <DetailsPanel node={selectedNode} onClose={() => setSelectedId(null)} isStaff={me?.is_staff} onRotate={(h) => setDialog({ mode: "rotate", host: h })} />
      </main>

      {dialog && <AddHostDialog rotateHost={dialog.mode === "rotate" ? dialog.host : null} onClose={() => setDialog(null)} onDone={load} />}
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
