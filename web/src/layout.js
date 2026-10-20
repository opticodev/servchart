// Turns the hub's graph (hosts -> networks / stacks -> containers) into positioned React Flow nodes.
//
//   ┌ host ─────────────────────────────────────────────┐
//   │ (shared network) (bridge)                         │
//   │ ┌ stack: nextcloud ──────┐ ┌ stack: git ────────┐ │
//   │ │ (nextcloud_default)    │ │ (git_default)      │ │
//   │ │ [app]  [db]            │ │ [server] [db]      │ │
//   │ │ [redis]                │ │ [runner]           │ │
//   │ └────────────────────────┘ └────────────────────┘ │
//   └───────────────────────────────────────────────────┘
//
// A network used by a single stack is drawn inside that stack, so its lines stay short;
// only networks shared between stacks (or standalone containers) sit in the host's top row.
// With grouping off, a host's containers sit in one plain grid (no stack boxes).

export const SIZES = {
  container: { w: 210, h: 66 },
  network: { w: 180, h: 34 },
  gap: 14,
  colGap: 30, // between container columns and rows: room for lines to run between cards
  rowGap: 24,
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

// Arrange a group's containers in columns by how they talk: callers on the left, what they
// call on the right (web -> app -> db), so lines run left to right instead of across the box.
// Returns [{col,row}] per member, or null when the members don't talk to each other.
export function layeredSlots(members, edges, maxCols, minCols = 1) {
  const ids = members.map((m) => m.id);
  const index = new Map(ids.map((id, i) => [id, i]));
  const out = ids.map(() => new Set());
  const inn = ids.map(() => new Set());
  for (const e of edges) {
    if (e.kind !== "flow" && e.kind !== "depends") continue;
    const a = index.get(e.source);
    const b = index.get(e.target);
    if (a === undefined || b === undefined || a === b) continue;
    out[a].add(b);
    inn[b].add(a);
  }
  const linked = ids.map((_, i) => out[i].size + inn[i].size > 0);
  if (!linked.some(Boolean)) return null;

  // longest path from the callers; DFS ignores edges that would close a cycle
  const layer = ids.map(() => 0);
  const state = ids.map(() => 0); // 0 new, 1 on stack, 2 done
  const order = [];
  const visit = (i) => {
    state[i] = 1;
    for (const j of out[i]) if (state[j] === 0) visit(j);
    state[i] = 2;
    order.push(i);
  };
  ids.forEach((_, i) => state[i] === 0 && inn[i].size === 0 && visit(i));
  ids.forEach((_, i) => state[i] === 0 && visit(i));
  order.reverse(); // topological order (sources first)
  const pos = new Map(order.map((i, k) => [i, k]));
  for (const i of order) for (const j of out[i]) if (pos.get(j) > pos.get(i)) layer[j] = Math.max(layer[j], layer[i] + 1);

  const layers = Math.max(...ids.map((_, i) => (linked[i] ? layer[i] : 0))) + 1;
  const cols = Math.min(maxCols, Math.max(layers, minCols)); // extra columns take the loners
  // more layers than columns (long chains, cycles): keep the first ones apart, merge the deepest
  const colOf = (i) => Math.min(layer[i], cols - 1);
  const columns = Array.from({ length: cols }, () => []);
  ids.forEach((_, i) => linked[i] && columns[colOf(i)].push(i));

  // order each column by the average row of its neighbours (barycenter), sweeping left-to-right
  // then right-to-left a few times: connected containers end up level, so lines run straight across
  const rowOf = new Map();
  columns.forEach((col) => col.forEach((i, r) => rowOf.set(i, r)));
  const crossings = () => {
    let n = 0;
    const es = [];
    ids.forEach((_, i) => linked[i] && out[i].forEach((j) => es.push([colOf(i), rowOf.get(i), colOf(j), rowOf.get(j)])));
    for (let a = 0; a < es.length; a++)
      for (let b = a + 1; b < es.length; b++) {
        const [c1, r1, d1, s1] = es[a];
        const [c2, r2, d2, s2] = es[b];
        if (c1 === c2 && d1 === d2 && (r1 - r2) * (s1 - s2) < 0) n++;
      }
    return n;
  };
  const sweep = (c, side) => {
    const score = (i) => {
      const ns = [...inn[i], ...out[i]].filter((j) => linked[j] && (side < 0 ? colOf(j) < c : colOf(j) > c)).map((j) => rowOf.get(j));
      return ns.length ? ns.reduce((a, b) => a + b, 0) / ns.length : rowOf.get(i);
    };
    columns[c].sort((a, b) => score(a) - score(b) || rowOf.get(a) - rowOf.get(b));
    columns[c].forEach((i, r) => rowOf.set(i, r));
  };
  let best = { n: crossings(), cols: columns.map((c) => [...c]) };
  for (let pass = 0; pass < 4; pass++) {
    for (let c = 1; c < cols; c++) sweep(c, -1);
    for (let c = cols - 2; c >= 0; c--) sweep(c, 1);
    const n = crossings();
    if (n < best.n) best = { n, cols: columns.map((c) => [...c]) };
  }
  best.cols.forEach((col, c) => {
    columns[c] = col;
    col.forEach((i, r) => rowOf.set(i, r));
  });
  // containers that don't talk to the others fill the shortest columns
  ids.forEach((_, i) => {
    if (linked[i]) return;
    const c = columns.reduce((best, col, k) => (col.length < columns[best].length ? k : best), 0);
    columns[c].push(i);
  });
  const slots = ids.map(() => null);
  columns.forEach((col, c) => col.forEach((i, r) => (slots[i] = { col: c, row: r })));
  return slots;
}

// Stacks on one server, ordered like containers inside a stack: stacks that call others first (left),
// the stacks they call after them (right), so lines between stacks also run left to right.
// Stacks with no links keep their alphabetical place after the linked ones.
export function orderStacks(groups, edges) {
  const stackOf = new Map();
  groups.forEach((g, k) => g.members.forEach((m) => stackOf.set(m.id, k)));
  const out = groups.map(() => new Set());
  const inn = groups.map(() => new Set());
  for (const e of edges) {
    if ((e.kind !== "flow" && e.kind !== "depends") || e.agent) continue;
    const a = stackOf.get(e.source);
    const b = stackOf.get(e.target);
    if (a === undefined || b === undefined || a === b) continue;
    out[a].add(b);
    inn[b].add(a);
  }
  const layer = groups.map(() => 0);
  const seen = groups.map(() => 0);
  const order = [];
  const visit = (i) => {
    seen[i] = 1;
    for (const j of out[i]) if (!seen[j]) visit(j);
    order.push(i);
  };
  groups.forEach((_, i) => !seen[i] && !inn[i].size && visit(i));
  groups.forEach((_, i) => !seen[i] && visit(i));
  order.reverse();
  const pos = new Map(order.map((i, k) => [i, k]));
  for (const i of order) for (const j of out[i]) if (pos.get(j) > pos.get(i)) layer[j] = Math.max(layer[j], layer[i] + 1);
  const linked = (i) => out[i].size + inn[i].size > 0;
  return groups
    .map((g, i) => ({ g, i }))
    .sort((a, b) => (linked(b.i) - linked(a.i)) || (linked(a.i) ? layer[a.i] - layer[b.i] : 0) || a.i - b.i)
    .map((x) => x.g);
}

// Put servers that talk to each other next to each other, so lines between them stay short:
// start with the busiest server, then repeatedly add the one with the most traffic to the last placed.
export function orderHosts(byHost, edges) {
  const hostOf = (id) => (id.startsWith("host:") ? id : "host:" + id.split(":")[1]);
  const w = new Map();
  const add = (a, b, n) => {
    if (a === b || !byHost.has(a) || !byHost.has(b)) return;
    for (const [x, y] of [[a, b], [b, a]]) {
      if (!w.has(x)) w.set(x, new Map());
      w.get(x).set(y, (w.get(x).get(y) || 0) + n);
    }
  };
  for (const e of edges) if (e.kind === "flow" && !e.agent) add(hostOf(e.source), hostOf(e.target), 1);
  const ids = [...byHost.keys()];
  const total = (id) => [...(w.get(id)?.values() || [])].reduce((a, b) => a + b, 0);
  const left = new Set(ids);
  const order = [];
  while (left.size) {
    let next;
    const last = order[order.length - 1];
    if (last && w.has(last)) {
      next = [...left].sort((a, b) => (w.get(last).get(b) || 0) - (w.get(last).get(a) || 0) || total(b) - total(a))[0];
      if (!w.get(last).get(next)) next = undefined;
    }
    next = next || [...left].sort((a, b) => total(b) - total(a) || ids.indexOf(a) - ids.indexOf(b))[0];
    order.push(next);
    left.delete(next);
  }
  return order.map((id) => [id, byHost.get(id)]);
}

// Position the server boxes. Servers that talk are laid out like containers in a stack: servers that
// call others in the left columns, the ones they call further right (a server many others report to,
// such as a log or security server, ends up on the right), servers in the same column stacked
// vertically. Without links between servers they wrap in rows as before.
export function placeHosts(placed, graph, maxCols = 4) {
  const { hostGap, rowWidth } = SIZES;
  const hostOfNode = new Map(graph.nodes.map((n) => [n.id, n.type === "host" ? n.id : n.host]));
  const hostEdges = [];
  for (const e of graph.edges) {
    if (e.kind !== "flow" || e.agent) continue; // "reports to ServChart" lines would pull every server left of the hub
    const a = hostOfNode.get(e.source);
    const b = hostOfNode.get(e.target);
    if (a && b && a !== b) hostEdges.push({ kind: "flow", source: a, target: b });
  }
  const slots = placed.length > 1 ? layeredSlots(placed, hostEdges, maxCols) : null;
  if (!slots) {
    let x = 0;
    let y = 0;
    let rowHeight = 0;
    for (const p of placed) {
      if (x > 0 && x + p.width > rowWidth) {
        x = 0;
        y += rowHeight + hostGap;
        rowHeight = 0;
      }
      p.node.position = { x, y };
      x += p.width + hostGap;
      rowHeight = Math.max(rowHeight, p.height);
    }
    return;
  }
  const cols = Math.max(...slots.map((s) => s.col)) + 1;
  const colW = Array.from({ length: cols }, () => 0);
  placed.forEach((p, i) => (colW[slots[i].col] = Math.max(colW[slots[i].col], p.width)));
  const colX = [];
  colW.reduce((x, w, c) => ((colX[c] = x), x + w + hostGap * 2), 0); // wider gap: room for lines between servers
  const inCol = (c) =>
    placed
      .map((p, i) => ({ p, s: slots[i] }))
      .filter(({ s }) => s.col === c)
      .sort((a, b) => a.s.row - b.s.row);
  const colH = (c) => inCol(c).reduce((h, { p }) => h + p.height + hostGap, -hostGap);
  const tallest = Math.max(...Array.from({ length: cols }, (_, c) => colH(c)));
  for (let c = 0; c < cols; c++) {
    let y = Math.round((tallest - colH(c)) / 2); // centred, so lines to a lone server split up and down
    inCol(c).forEach(({ p }) => {
        p.node.position = { x: colX[c], y };
        y += p.height + hostGap;
      });
  }
}

// For a selected node: does an edge end touch it or something inside it (a stack's or host's members)?
export function relatedTo(nodes, selectedId) {
  const parentOf = new Map(nodes.map((n) => [n.id, n.parentId]));
  return (id) => {
    if (!selectedId) return false;
    for (let cur = id; cur; cur = parentOf.get(cur)) if (cur === selectedId) return true;
    return false;
  };
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
  const { container: C, network: N, gap, colGap, rowGap, pad, header, stackHeader, stackPad } = SIZES;

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
  const placed = []; // host boxes, positioned once all are sized

  for (const [hostId, b] of orderHosts(byHost, graph.edges)) {
    if (hostFilter !== "all" && hostFilter !== hostId) continue;

    // networks actually used by the visible containers
    const ctrIds = new Set(b.containers.map((c) => c.id));
    const usedNets = new Set();
    for (const e of graph.edges) if (ctrIds.has(e.source) && e.kind === "network") usedNets.add(e.target);
    const allNets = b.networks.filter((n) => usedNets.has(n.id)).sort((a, z) => a.data.name.localeCompare(z.data.name));
    const localStackOf = (n) => (groupStacks && (n.data.stacks || []).length === 1 && b.stacks.has(n.data.stacks[0]) ? n.data.stacks[0] : null);
    const nets = allNets.filter((n) => !localStackOf(n)); // shared ones, in the host's top row
    const localNets = new Map(); // stack id -> its own networks
    for (const n of allNets) {
      const sid = localStackOf(n);
      if (sid) localNets.set(sid, [...(localNets.get(sid) || []), n]);
    }

    // groups: one per stack (or a single unboxed group when grouping is off)
    let groups;
    if (groupStacks) {
      for (const c of b.containers) b.stacks.get(c.stack)?.members.push(c);
      groups = orderStacks(
        [...b.stacks.values()]
          .filter((g) => g.members.length)
          .sort((a, z) => (a.node.id.endsWith(STANDALONE_SUFFIX) - z.node.id.endsWith(STANDALONE_SUFFIX)) || (a.node.data.name || "").localeCompare(z.node.data.name || "")),
        graph.edges
      );
    } else {
      groups = [{ node: null, members: [...b.containers] }];
    }
    for (const g of groups) g.members.sort((a, z) => (a.data.compose?.service || a.data.name).localeCompare(z.data.compose?.service || z.data.name));

    // size each group
    for (const g of groups) {
      const n = g.members.length;
      g.cols = g.node ? stackCols(n) : Math.max(3, Math.min(6, Math.ceil(Math.sqrt(n * 1.6))));
      g.slots = layeredSlots(g.members, graph.edges, g.node ? 4 : 6, g.cols);
      if (g.slots) {
        g.cols = Math.max(1, ...g.slots.map((p) => p.col + 1));
        g.rows = Math.max(1, ...g.slots.map((p) => p.row + 1));
      } else {
        g.slots = g.members.map((_, i) => ({ col: i % g.cols, row: Math.floor(i / g.cols) }));
        g.rows = Math.max(1, Math.ceil(n / g.cols));
      }
      const innerPad = g.node ? stackPad : 0;
      g.nets = g.node ? localNets.get(g.node.id) || [] : [];
      const innerW = g.cols * C.w + (g.cols - 1) * colGap;
      g.netCols = Math.max(1, Math.floor((innerW + gap) / (N.w + gap)));
      const netRows = Math.ceil(g.nets.length / g.netCols);
      g.netH = netRows ? netRows * (N.h + 8) - 8 + 12 : 0;
      const top = (g.node ? stackHeader : 0) + g.netH;
      g.w = innerW + innerPad * 2;
      g.h = top + g.rows * C.h + (g.rows - 1) * rowGap + innerPad;
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

    const hostNode = { id: hostId, type: "host", position: { x: 0, y: 0 }, data: b.host.data, style: { width, height } };
    placed.push({ id: hostId, node: hostNode, width, height });
    rfNodes.push(hostNode);
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
        g.nets.forEach((n, i) => {
          rfNodes.push({
            id: n.id,
            type: "network",
            parentId,
            extent: "parent",
            position: { x: stackPad + (i % g.netCols) * (N.w + gap), y: stackHeader + Math.floor(i / g.netCols) * (N.h + 8) },
            data: { ...n.data, local: true },
            style: { width: N.w, height: N.h },
          });
          visible.add(n.id);
        });
        ox = stackPad;
        oy = stackHeader + g.netH;
      }
      g.members.forEach((m, i) => {
        rfNodes.push({
          id: m.id,
          type: "container",
          parentId,
          extent: "parent",
          position: { x: ox + g.slots[i].col * (C.w + colGap), y: oy + g.slots[i].row * (C.h + rowGap) },
          data: { ...m.data, dimmed: !matchesQuery(q, m.data, g.node?.data) },
          style: { width: C.w, height: C.h },
        });
        visible.add(m.id);
      });
    }

  }
  placeHosts(placed, graph);

  const rfEdges = graph.edges
    .filter((e) => visible.has(e.source) && visible.has(e.target))
    .map((e) => ({ id: e.id, source: e.source, target: e.target, type: "default", className: `edge-${e.kind}`, data: e }));
  return { nodes: rfNodes, edges: rfEdges };
}

export const LINK_KINDS = {
  structure: new Set(["network", "host-network", "shared-netns"]), // what a container is attached to
  relation: new Set(["depends", "flow"]), // how containers talk
};

// Which edges to draw. mode:
//   "overview" (default): one line per stack pair on a host and one per host pair across hosts,
//              with ports merged; lines inside a stack and Compose dependencies only around
//              the selection. Selecting anything expands its own lines in full.
//   "smart":   every traffic and dependency line, structure lines only around the selection.
//   "all":     everything.  "selected": only lines touching the selection.
export function filterEdges(edges, nodes, mode, selectedId) {
  const parentOf = new Map(nodes.map((n) => [n.id, n.parentId]));
  const touches = (id) => {
    if (!selectedId) return false;
    for (let cur = id; cur; cur = parentOf.get(cur)) if (cur === selectedId) return true; // inside a selected stack/host
    return false;
  };
  const ancestor = (id, prefix) => {
    for (let cur = id; cur; cur = parentOf.get(cur)) if (cur.startsWith(prefix)) return cur;
    return null;
  };

  // a Compose dependency that is also seen as traffic: draw the traffic line only
  const seen = new Set(edges.filter((e) => e.data.kind === "flow").map((e) => `${e.source}>${e.target}`));
  if (mode !== "all") edges = edges.filter((e) => e.data.kind !== "depends" || !seen.has(`${e.source}>${e.target}`));
  // "reports to ServChart" lines: only for the selection (every agent has one, they'd cross the whole map)
  if (mode !== "all") edges = edges.filter((e) => !e.data.agent || touches(e.source) || touches(e.target));

  if (mode !== "overview") {
    return edges.filter((e) => {
      const related = touches(e.source) || touches(e.target);
      if (mode === "all") return true;
      if (mode === "selected") return related;
      return LINK_KINDS.relation.has(e.data.kind) || related;
    });
  }

  const out = [];
  const merged = new Map();
  for (const e of edges) {
    const kind = e.data.kind;
    const related = touches(e.source) || touches(e.target);
    if (related) {
      out.push(e);
      continue;
    }
    if (kind !== "flow") continue; // structure and depends_on: only around the selection
    const sHost = ancestor(e.source, "host:");
    const tHost = ancestor(e.target, "host:");
    let a;
    let b;
    if (sHost !== tHost) {
      a = sHost;
      b = tHost;
    } else {
      a = ancestor(e.source, "stack:") || e.source;
      b = ancestor(e.target, "stack:") || e.target;
      if (a === b) continue; // inside one stack: shown when the stack or a member is selected
    }
    if (!a || !b) continue;
    const key = `${a}->${b}`;
    const m = merged.get(key) || { ports: new Set(), count: 0, links: 0, cross_host: sHost !== tHost, agent: true };
    m.agent = m.agent && !!e.data.agent;
    (e.data.ports || []).forEach((p) => m.ports.add(p));
    m.count += e.data.count || 0;
    m.links += 1;
    merged.set(key, m);
  }
  for (const [key, m] of merged) {
    const [source, target] = key.split("->");
    out.push({
      id: `agg:${key}`,
      source,
      target,
      type: "default",
      className: "edge-flow edge-agg",
      data: { kind: "flow", ports: [...m.ports].sort((x, y) => x - y), count: m.count, links: m.links, cross_host: m.cross_host, aggregated: true, agent: m.agent },
    });
  }
  return out;
}
