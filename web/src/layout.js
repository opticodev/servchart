// Turns the hub's graph (hosts -> networks / stacks -> containers) into positioned React Flow nodes.
//
//   ┌ host ─────────────────────────────────────────────┐
//   │ (network) (network) (network)                     │
//   │ ┌ stack: nextcloud ──────┐ ┌ stack: git ────────┐ │
//   │ │ [app]  [db]            │ │ [server] [db]      │ │
//   │ │ [redis]                │ │ [runner]           │ │
//   │ └────────────────────────┘ └────────────────────┘ │
//   └───────────────────────────────────────────────────┘
//
// With grouping off, a host's containers sit in one plain grid (no stack boxes).

export const SIZES = {
  container: { w: 210, h: 66 },
  network: { w: 180, h: 34 },
  gap: 14,
  pad: 18,
  header: 64,
  stackHeader: 46,
  stackPad: 12,
  hostGap: 60,
  hostInnerMax: 1500, // stacks wrap onto a new row past this width
  rowWidth: 2800, // hosts wrap onto a new row past this width
};

const STANDALONE_SUFFIX = ":~standalone";

function stackCols(n) {
  if (n <= 2) return Math.max(1, n);
  if (n <= 6) return 2;
  return 3;
}

function matchesQuery(q, d, stack) {
  if (!q) return true;
  const hay = [
    d.name,
    d.image,
    d.compose?.project,
    d.compose?.service,
    d.compose?.working_dir,
    stack?.working_dir,
    ...(d.ports || []).map((p) => String(p.public ?? "")),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return hay.includes(q);
}

export function layoutGraph(graph, { hideStopped = false, query = "", hostFilter = "all", groupStacks = true } = {}) {
  const q = query.trim().toLowerCase();
  const { container: C, network: N, gap, pad, header, stackHeader, stackPad } = SIZES;

  const byHost = new Map();
  for (const n of graph.nodes) if (n.type === "host") byHost.set(n.id, { host: n, networks: [], stacks: new Map(), containers: [] });
  for (const n of graph.nodes) {
    const b = byHost.get(n.host);
    if (!b || n.type === "host") continue;
    if (n.type === "network") b.networks.push(n);
    if (n.type === "stack") b.stacks.set(n.id, { node: n, members: [] });
    if (n.type === "container") {
      if (hideStopped && n.data.state !== "running") continue;
      b.containers.push(n);
    }
  }

  const rfNodes = [];
  const visible = new Set();
  let x = 0;
  let y = 0;
  let rowHeight = 0;

  for (const [hostId, b] of byHost) {
    if (hostFilter !== "all" && hostFilter !== hostId) continue;

    // networks actually used by the visible containers
    const ctrIds = new Set(b.containers.map((c) => c.id));
    const usedNets = new Set();
    for (const e of graph.edges) if (ctrIds.has(e.source) && e.kind === "network") usedNets.add(e.target);
    const nets = b.networks.filter((n) => usedNets.has(n.id)).sort((a, z) => a.data.name.localeCompare(z.data.name));

    // groups: one per stack (or a single unboxed group when grouping is off)
    let groups;
    if (groupStacks) {
      for (const c of b.containers) b.stacks.get(c.stack)?.members.push(c);
      groups = [...b.stacks.values()]
        .filter((g) => g.members.length)
        .sort((a, z) => (a.node.id.endsWith(STANDALONE_SUFFIX) - z.node.id.endsWith(STANDALONE_SUFFIX)) || (a.node.data.name || "").localeCompare(z.node.data.name || ""));
    } else {
      groups = [{ node: null, members: [...b.containers] }];
    }
    for (const g of groups) g.members.sort((a, z) => (a.data.compose?.service || a.data.name).localeCompare(z.data.compose?.service || z.data.name));

    // size each group
    for (const g of groups) {
      const n = g.members.length;
      g.cols = g.node ? stackCols(n) : Math.max(3, Math.min(6, Math.ceil(Math.sqrt(n * 1.6))));
      g.rows = Math.max(1, Math.ceil(n / g.cols));
      const innerPad = g.node ? stackPad : 0;
      const top = g.node ? stackHeader : 0;
      g.w = g.cols * C.w + (g.cols - 1) * gap + innerPad * 2;
      g.h = top + g.rows * C.h + (g.rows - 1) * gap + innerPad;
    }

    // shelf-pack groups inside the host
    const widest = Math.max(N.w, ...groups.map((g) => g.w));
    const total = groups.reduce((s, g) => s + g.w, 0) + gap * Math.max(0, groups.length - 1);
    const innerW = Math.max(widest, Math.min(total, SIZES.hostInnerMax), nets.length ? Math.min(nets.length, 4) * (N.w + gap) - gap : 0);
    const netCols = Math.max(1, Math.floor((innerW + gap) / (N.w + gap)));
    const netRows = Math.ceil(nets.length / netCols);
    const netBlockH = netRows ? netRows * N.h + (netRows - 1) * gap + 24 : 0;

    let gx = 0;
    let gy = 0;
    let shelfH = 0;
    for (const g of groups) {
      if (gx > 0 && gx + g.w > innerW) {
        gx = 0;
        gy += shelfH + gap;
        shelfH = 0;
      }
      g.x = pad + gx;
      g.y = header + netBlockH + gy;
      gx += g.w + gap;
      shelfH = Math.max(shelfH, g.h);
    }
    const width = innerW + pad * 2;
    const height = header + netBlockH + gy + Math.max(shelfH, C.h) + pad;

    if (x > 0 && x + width > SIZES.rowWidth) {
      x = 0;
      y += rowHeight + SIZES.hostGap;
      rowHeight = 0;
    }

    rfNodes.push({ id: hostId, type: "host", position: { x, y }, data: b.host.data, style: { width, height } });
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

    for (const g of groups) {
      let parentId = hostId;
      let ox = g.x;
      let oy = g.y;
      if (g.node) {
        const stackData = g.node.data;
        const shown = g.members.length;
        const dimmed = q ? !g.members.some((m) => matchesQuery(q, m.data, stackData)) : false;
        rfNodes.push({
          id: g.node.id,
          type: "stack",
          parentId: hostId,
          extent: "parent",
          position: { x: g.x, y: g.y },
          data: { ...stackData, shown, dimmed },
          style: { width: g.w, height: g.h },
        });
        visible.add(g.node.id);
        parentId = g.node.id;
        ox = stackPad;
        oy = stackHeader;
      }
      g.members.forEach((m, i) => {
        rfNodes.push({
          id: m.id,
          type: "container",
          parentId,
          extent: "parent",
          position: { x: ox + (i % g.cols) * (C.w + gap), y: oy + Math.floor(i / g.cols) * (C.h + gap) },
          data: { ...m.data, dimmed: !matchesQuery(q, m.data, g.node?.data) },
          style: { width: C.w, height: C.h },
        });
        visible.add(m.id);
      });
    }

    x += width + SIZES.hostGap;
    rowHeight = Math.max(rowHeight, height);
  }

  const rfEdges = graph.edges
    .filter((e) => visible.has(e.source) && visible.has(e.target))
    .map((e) => ({ id: e.id, source: e.source, target: e.target, type: "default", className: `edge-${e.kind}`, data: e }));

  return { nodes: rfNodes, edges: rfEdges };
}
