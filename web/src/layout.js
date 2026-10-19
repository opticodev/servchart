// Turns the hub's graph (hosts -> networks -> containers) into positioned React Flow nodes.
// Each host is a group node; its networks sit in a row at the top and its containers
// in a grid below, clustered by Compose project.

export const SIZES = {
  container: { w: 210, h: 66 },
  network: { w: 180, h: 34 },
  gap: 14,
  pad: 18,
  header: 64,
  hostGap: 60,
  rowWidth: 2600,
};

function projectKey(c) {
  return (c.compose && c.compose.project) || "~" + c.name; // standalone containers sort last
}

export function layoutGraph(graph, { hideStopped = false, query = "", hostFilter = "all" } = {}) {
  const q = query.trim().toLowerCase();
  const { container: C, network: N, gap, pad, header } = SIZES;
  const byHost = new Map();
  for (const n of graph.nodes) {
    if (n.type === "host") byHost.set(n.id, { host: n, networks: [], containers: [] });
  }
  for (const n of graph.nodes) {
    const bucket = byHost.get(n.host);
    if (!bucket || n.type === "host") continue;
    if (n.type === "network") bucket.networks.push(n);
    if (n.type === "container") {
      if (hideStopped && n.data.state !== "running") continue;
      bucket.containers.push(n);
    }
  }

  const matches = (n) => {
    if (!q) return true;
    const d = n.data;
    const hay = [d.name, d.image, d.compose?.project, d.compose?.service, ...(d.ports || []).map((p) => String(p.public ?? ""))]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  };

  const rfNodes = [];
  const visible = new Set();
  let x = 0;
  let y = 0;
  let rowHeight = 0;

  for (const [hostId, b] of byHost) {
    if (hostFilter !== "all" && hostFilter !== hostId) continue;
    b.containers.sort((a, z) => projectKey(a.data).localeCompare(projectKey(z.data)) || a.data.name.localeCompare(z.data.name));
    const usedNets = new Set();
    const ctrIds = new Set(b.containers.map((c) => c.id));
    for (const e of graph.edges) if (ctrIds.has(e.source) && e.kind === "network") usedNets.add(e.target);
    const nets = b.networks.filter((n) => usedNets.has(n.id)).sort((a, z) => a.data.name.localeCompare(z.data.name));

    const cols = Math.max(3, Math.min(6, Math.ceil(Math.sqrt(b.containers.length * 1.6))));
    const innerW = cols * C.w + (cols - 1) * gap;
    const netCols = Math.max(1, Math.floor((innerW + gap) / (N.w + gap)));
    const netRows = Math.ceil(nets.length / netCols);
    const netBlockH = netRows ? netRows * N.h + (netRows - 1) * gap + 28 : 0;
    const ctrRows = Math.ceil(b.containers.length / cols);
    const width = innerW + pad * 2;
    const height = header + netBlockH + Math.max(1, ctrRows) * (C.h + gap) + pad;

    if (x > 0 && x + width > SIZES.rowWidth) {
      x = 0;
      y += rowHeight + SIZES.hostGap;
      rowHeight = 0;
    }

    rfNodes.push({
      id: hostId,
      type: "host",
      position: { x, y },
      data: { ...b.host.data, shown: b.containers.length },
      style: { width, height },
      selectable: true,
    });
    visible.add(hostId);

    nets.forEach((n, i) => {
      rfNodes.push({
        id: n.id,
        type: "network",
        parentId: hostId,
        extent: "parent",
        position: { x: pad + (i % netCols) * (N.w + gap), y: header + Math.floor(i / netCols) * (N.h + gap) },
        data: n.data,
        style: { width: N.w, height: N.h },
      });
      visible.add(n.id);
    });

    b.containers.forEach((n, i) => {
      rfNodes.push({
        id: n.id,
        type: "container",
        parentId: hostId,
        extent: "parent",
        position: { x: pad + (i % cols) * (C.w + gap), y: header + netBlockH + Math.floor(i / cols) * (C.h + gap) },
        data: { ...n.data, dimmed: !matches(n) },
        style: { width: C.w, height: C.h },
      });
      visible.add(n.id);
    });

    x += width + SIZES.hostGap;
    rowHeight = Math.max(rowHeight, height);
  }

  const rfEdges = graph.edges
    .filter((e) => visible.has(e.source) && visible.has(e.target))
    .map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: "default",
      className: `edge-${e.kind}`,
      data: e,
    }));

  return { nodes: rfNodes, edges: rfEdges };
}
