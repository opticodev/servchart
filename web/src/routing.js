// Orthogonal line routing: lines leave a card on its right, enter the next card on its left, and in
// between run only through the gaps between cards (never across one), with as few bends as possible.
//
// How: every card is an obstacle grown by a margin. The grown edges give a sparse grid of horizontal
// and vertical "streets" that all lie in the gaps; A* finds the shortest path along the streets with
// a penalty per bend. Lines that end up in the same street are then spread apart ("nudged") a few
// pixels so they stay distinguishable.

const DIRS = [
  [1, 0], // east
  [-1, 0], // west
  [0, 1], // south
  [0, -1], // north
];

function absoluteRects(nodes) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const rects = new Map();
  const place = (n) => {
    if (rects.has(n.id)) return rects.get(n.id);
    const parent = n.parentId ? byId.get(n.parentId) : null;
    const p = parent ? place(parent) : { x: 0, y: 0, host: null };
    const w = n.measured?.width ?? n.width ?? n.style?.width ?? 0;
    const h = n.measured?.height ?? n.height ?? n.style?.height ?? 0;
    const host = n.type === "host" ? n.id : parent ? p.host : null;
    const r = { x: p.x + n.position.x, y: p.y + n.position.y, w, h, type: n.type, host };
    rects.set(n.id, r);
    return r;
  };
  nodes.forEach(place);
  return rects;
}

// smallest index with a[i] >= v
function lowerBound(a, v) {
  let lo = 0;
  let hi = a.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (a[mid] < v) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

class Heap {
  constructor() {
    this.k = [];
    this.v = [];
  }
  get size() {
    return this.k.length;
  }
  push(key, val) {
    const { k, v } = this;
    let i = k.length;
    k.push(key);
    v.push(val);
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (k[p] <= key) break;
      k[i] = k[p];
      v[i] = v[p];
      i = p;
    }
    k[i] = key;
    v[i] = val;
  }
  pop() {
    const { k, v } = this;
    const top = v[0];
    const lk = k.pop();
    const lv = v.pop();
    if (k.length) {
      let i = 0;
      for (;;) {
        let c = 2 * i + 1;
        if (c >= k.length) break;
        if (c + 1 < k.length && k[c + 1] < k[c]) c++;
        if (k[c] >= lk) break;
        k[i] = k[c];
        v[i] = v[c];
        i = c;
      }
      k[i] = lk;
      v[i] = lv;
    }
    return top;
  }
}

// nodes: React Flow nodes (relative positions, parentId, style sizes); edges: [{id, source, target}]
// Returns Map(edgeId -> [{x,y}, ...]) from the source's right side to the target's left side.
export function routeEdges(nodes, edges, { margin = 7, bend = 80, maxEdges = 600 } = {}) {
  const routes = new Map();
  if (!edges.length || edges.length > maxEdges) return routes;
  const rects = absoluteRects(nodes);
  const obstacles = [];
  for (const r of rects.values()) {
    if (!r.w || !r.h) continue;
    if (r.type === "container" || r.type === "network") obstacles.push(r);
    // the title strips of servers (name, health meters) and stacks: lines may cross the boxes' sides
    // but not their headings
    else if (r.type === "host") obstacles.push({ ...r, h: Math.min(r.h, 48) });
    else if (r.type === "stack") obstacles.push({ ...r, h: Math.min(r.h, 34) });
  }

  const hostRects = [...rects.entries()].filter(([, r]) => r.type === "host" && r.w && r.h);
  const hostNo = new Map(hostRects.map(([id], k) => [id, k + 1]));
  const xsSet = new Set();
  const ysSet = new Set();
  for (const [, o] of hostRects) {
    xsSet.add(o.x - margin);
    xsSet.add(o.x + o.w + margin);
    ysSet.add(o.y - margin);
    ysSet.add(o.y + o.h + margin);
  }
  for (const o of obstacles) {
    xsSet.add(o.x - margin);
    xsSet.add(o.x + o.w + margin);
    ysSet.add(o.y - margin);
    ysSet.add(o.y + o.h + margin);
  }
  const ends = [];
  for (const e of edges) {
    const s = rects.get(e.source);
    const t = rects.get(e.target);
    if (!s || !t) continue;
    const sp = { x: s.x + s.w, y: s.y + s.h / 2 };
    const tp = { x: t.x, y: t.y + t.h / 2 };
    const a = { x: sp.x + margin, y: sp.y };
    const b = { x: tp.x - margin, y: tp.y };
    xsSet.add(a.x);
    xsSet.add(b.x);
    ysSet.add(a.y);
    ysSet.add(b.y);
    const sh = hostNo.get(s.host) || 0;
    const th = hostNo.get(t.host) || 0;
    ends.push({ e, sp, tp, a, b, sh, th, cross: sh !== th, span: Math.abs(tp.x - sp.x) + Math.abs(tp.y - sp.y) });
  }
  // streets right next to a card are a fallback; wide gaps also get a street down their middle,
  // which lines prefer, so they don't run along a box's border
  const hugging = new Set();
  for (const o of [...obstacles, ...hostRects.map(([, r]) => r)]) {
    hugging.add("x" + (o.x - margin)).add("x" + (o.x + o.w + margin));
    hugging.add("y" + (o.y - margin)).add("y" + (o.y + o.h + margin));
  }
  for (const { a, b } of ends) {
    hugging.delete("y" + a.y); // a line's own level is fine
    hugging.delete("y" + b.y);
  }
  const withMiddles = (set) => {
    const v = [...set].sort((p, q) => p - q);
    const out = [];
    for (let k = 0; k < v.length; k++) {
      out.push(v[k]);
      if (k + 1 < v.length && v[k + 1] - v[k] >= 2 * margin - 2) out.push(Math.round((v[k] + v[k + 1]) / 2));
    }
    return out;
  };
  const xs = withMiddles(xsSet);
  const ys = withMiddles(ysSet);
  const hugX = xs.map((x) => hugging.has("x" + x));
  const hugY = ys.map((y) => hugging.has("y" + y));
  const NX = xs.length;
  const NY = ys.length;
  const N = NX * NY;
  const at = (i, j) => j * NX + i;

  // blocked grid points and grid links (a link from (i,j) east to (i+1,j), or south to (i,j+1))
  const bN = new Uint8Array(N);
  const bE = new Uint8Array(N);
  const bS = new Uint8Array(N);
  for (const o of obstacles) {
    const L = o.x - margin;
    const R = o.x + o.w + margin;
    const T = o.y - margin;
    const B = o.y + o.h + margin;
    const i0 = lowerBound(xs, L); // xs[i0] == L (a grid line)
    const i1 = lowerBound(xs, R);
    const j0 = lowerBound(ys, T);
    const j1 = lowerBound(ys, B);
    for (let j = j0 + 1; j < j1; j++) for (let i = i0; i < i1; i++) bE[at(i, j)] = 1;
    for (let i = i0 + 1; i < i1; i++) for (let j = j0; j < j1; j++) bS[at(i, j)] = 1;
    for (let j = j0 + 1; j < j1; j++) for (let i = i0 + 1; i < i1; i++) bN[at(i, j)] = 1;
  }
  // which server box each grid point is inside: a line may only pass through its own two servers,
  // so lines between servers use the gaps between the boxes
  const hostAt = new Uint16Array(N);
  for (const [id, o] of hostRects) {
    const i0 = lowerBound(xs, o.x - margin);
    const i1 = lowerBound(xs, o.x + o.w + margin);
    const j0 = lowerBound(ys, o.y - margin);
    const j1 = lowerBound(ys, o.y + o.h + margin);
    const k = hostNo.get(id);
    for (let j = j0 + 1; j < j1; j++) for (let i = i0 + 1; i < i1; i++) hostAt[at(i, j)] = k;
  }
  let hostA = 0;
  let hostB = 0;
  const inAllowedHost = (n) => {
    const k = hostAt[n];
    return k === 0 || k === hostA || k === hostB;
  };
  const canMove = (i, j, d) => {
    if (d === 0) return i + 1 < NX && !bE[at(i, j)] && !bN[at(i + 1, j)] && inAllowedHost(at(i + 1, j));
    if (d === 1) return i > 0 && !bE[at(i - 1, j)] && !bN[at(i - 1, j)] && inAllowedHost(at(i - 1, j));
    if (d === 2) return j + 1 < NY && !bS[at(i, j)] && !bN[at(i, j + 1)] && inAllowedHost(at(i, j + 1));
    return j > 0 && !bS[at(i, j - 1)] && !bN[at(i, j - 1)] && inAllowedHost(at(i, j - 1));
  };
  // streets already used by lines between servers: later ones are drawn to them, so lines going
  // the same way share a path and run together like a cable bundle
  const usedE = new Uint8Array(N);
  const usedS = new Uint8Array(N);
  let bundling = false;

  const dist = new Float64Array(N * 4);
  const prev = new Int32Array(N * 4);
  const stamp = new Int32Array(N * 4); // which search last touched a state, so arrays are reused
  let search = 0;

  const route = (a, b) => {
    search++;
    const hk = bundling ? 0.5 : 1; // keeps the estimate below the real (discounted) cost
    const si = lowerBound(xs, a.x);
    const sj = lowerBound(ys, a.y);
    const gi = lowerBound(xs, b.x);
    const gj = lowerBound(ys, b.y);
    if (bN[at(si, sj)] || bN[at(gi, gj)]) return null;
    const goal = at(gi, gj);
    const h = (i, j) => hk * (Math.abs(xs[i] - xs[gi]) + Math.abs(ys[j] - ys[gj]));
    const heap = new Heap();
    const s0 = at(si, sj) * 4; // leave heading east
    stamp[s0] = search;
    dist[s0] = 0;
    prev[s0] = -1;
    heap.push(h(si, sj), s0);
    let found = -1;
    let budget = 200000;
    while (heap.size && budget-- > 0) {
      const st = heap.pop();
      const node = st >> 2;
      const d = st & 3;
      const g = dist[st];
      if (node === goal) {
        found = st; // costs already include the turn into the target, so the first one out is best
        break;
      }
      const i = node % NX;
      const j = (node / NX) | 0;
      for (let nd = 0; nd < 4; nd++) {
        if ((d ^ nd) === 1) continue; // no U-turns (0<->1, 2<->3)
        if (!canMove(i, j, nd)) continue;
        const ni = i + DIRS[nd][0];
        const nj = j + DIRS[nd][1];
        const nn = at(ni, nj);
        const ns = nn * 4 + nd;
        const len = Math.abs(xs[ni] - xs[i]) + Math.abs(ys[nj] - ys[j]);
        const hug = nd < 2 ? hugY[j] : hugX[i]; // running right next to cards costs a bit more
        const link = nd === 0 ? usedE[node] : nd === 1 ? usedE[nn] : nd === 2 ? usedS[node] : usedS[nn];
        const share = bundling && link ? 0.5 : 1;
        let cost = g + len * (hug ? 1.6 : 1) * share + (nd !== d ? bend : 0);
        if (nn === goal && nd !== 0) cost += bend; // still has to turn into the target
        if (stamp[ns] === search && dist[ns] <= cost) continue;
        stamp[ns] = search;
        dist[ns] = cost;
        prev[ns] = st;
        heap.push(cost + h(ni, nj), ns);
      }
    }
    if (found < 0) return null;
    const path = [];
    for (let st = found; st >= 0; st = prev[st]) path.push(st >> 2);
    path.reverse();
    if (bundling)
      for (let k = 1; k < path.length; k++) {
        const p = path[k - 1];
        const q = path[k];
        if (q === p + 1) usedE[p] = 1;
        else if (q === p - 1) usedE[q] = 1;
        else if (q > p) usedS[p] = 1;
        else usedS[q] = 1;
      }
    return path.map((node) => ({ x: xs[node % NX], y: ys[(node / NX) | 0] }));
  };

  // lines inside a server first, then lines between servers, longest first, so the long runs lay
  // down the trunks the shorter ones join
  ends.sort((p, q) => p.cross - q.cross || (p.cross ? q.span - p.span : 0));
  const all = [];
  for (const { e, sp, tp, a, b, sh, th, cross } of ends) {
    hostA = sh;
    hostB = th;
    bundling = cross;
    const mid = route(a, b);
    if (!mid) continue;
    const pts = simplify([sp, ...mid, tp]);
    routes.set(e.id, pts);
    all.push(pts);
  }
  nudge(all);
  return routes;
}

// drop points that sit in the middle of a straight run
function simplify(pts) {
  const out = [pts[0]];
  for (let k = 1; k < pts.length - 1; k++) {
    const p = out[out.length - 1];
    const c = pts[k];
    const n = pts[k + 1];
    if ((p.x === c.x && c.x === n.x) || (p.y === c.y && c.y === n.y)) continue;
    out.push(c);
  }
  out.push(pts[pts.length - 1]);
  return out;
}

// Spread lines sharing a street: segments on the same line whose ranges overlap get small, distinct
// offsets. The first and last segments stay put (they are attached to the cards).
function nudge(routes) {
  for (const axis of ["x", "y"]) {
    const other = axis === "x" ? "y" : "x";
    const segs = [];
    routes.forEach((pts, r) => {
      for (let k = 1; k < pts.length - 2; k++) {
        const p = pts[k];
        const q = pts[k + 1];
        if (p[axis] !== q[axis]) continue; // not running along this axis
        segs.push({ r, k, at: p[axis], lo: Math.min(p[other], q[other]), hi: Math.max(p[other], q[other]) });
      }
    });
    segs.sort((s, t) => s.at - t.at || s.lo - t.lo);
    for (let a = 0; a < segs.length; ) {
      let b = a + 1;
      let hi = segs[a].hi;
      while (b < segs.length && segs[b].at === segs[a].at && segs[b].lo < hi) hi = Math.max(hi, segs[b++].hi);
      const group = segs.slice(a, b);
      const n = new Set(group.map((s) => s.r)).size;
      if (n > 1) {
        const step = Math.min(4, 10 / (n - 1));
        const order = [...new Set(group.map((s) => s.r))];
        for (const s of group) {
          const off = (order.indexOf(s.r) - (n - 1) / 2) * step;
          const pts = routes[s.r];
          pts[s.k] = { ...pts[s.k], [axis]: s.at + off };
          pts[s.k + 1] = { ...pts[s.k + 1], [axis]: s.at + off };
        }
      }
      a = b;
    }
  }
}

// SVG path through the points with rounded corners; also returns a label position halfway along.
export function roundedPath(pts, radius = 8) {
  let d = `M ${pts[0].x} ${pts[0].y}`;
  for (let k = 1; k < pts.length - 1; k++) {
    const p = pts[k - 1];
    const c = pts[k];
    const n = pts[k + 1];
    const r = Math.min(radius, Math.hypot(c.x - p.x, c.y - p.y) / 2, Math.hypot(n.x - c.x, n.y - c.y) / 2);
    const ux = Math.sign(c.x - p.x);
    const uy = Math.sign(c.y - p.y);
    const vx = Math.sign(n.x - c.x);
    const vy = Math.sign(n.y - c.y);
    d += ` L ${c.x - ux * r} ${c.y - uy * r} Q ${c.x} ${c.y} ${c.x + vx * r} ${c.y + vy * r}`;
  }
  const last = pts[pts.length - 1];
  d += ` L ${last.x} ${last.y}`;
  let total = 0;
  for (let k = 1; k < pts.length; k++) total += Math.abs(pts[k].x - pts[k - 1].x) + Math.abs(pts[k].y - pts[k - 1].y);
  let half = total / 2;
  let lx = pts[0].x;
  let ly = pts[0].y;
  for (let k = 1; k < pts.length; k++) {
    const len = Math.abs(pts[k].x - pts[k - 1].x) + Math.abs(pts[k].y - pts[k - 1].y);
    if (half <= len) {
      const f = len ? half / len : 0;
      lx = pts[k - 1].x + (pts[k].x - pts[k - 1].x) * f;
      ly = pts[k - 1].y + (pts[k].y - pts[k - 1].y) * f;
      break;
    }
    half -= len;
  }
  return [d, lx, ly];
}
