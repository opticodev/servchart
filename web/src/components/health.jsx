// Small shared pieces for v0.4 health data: meters, sizes, sparklines.

export function fmtBytes(n) {
  if (n === null || n === undefined) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 || i < 2 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

export function fmtDuration(s) {
  if (!s) return "–";
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  return d ? `${d} d ${h} h` : `${h} h ${Math.floor((s % 3600) / 60)} min`;
}

export function level(pct, warn = 85, bad = 95) {
  if (pct === null || pct === undefined) return "none";
  return pct >= bad ? "bad" : pct >= warn ? "warn" : "ok";
}

export function memPct(h) {
  return h?.mem_total && h.mem_available !== null && h.mem_available !== undefined ? (100 * (h.mem_total - h.mem_available)) / h.mem_total : null;
}

export function worstDisk(h) {
  return (h?.disks || []).reduce((w, d) => (!w || (d.pct ?? 0) > (w.pct ?? 0) ? d : w), null);
}

export function Meter({ label, pct, title, warn = 85, bad = 95 }) {
  return (
    <span className={`meter meter-${level(pct, warn, bad)}`} title={title || `${label} ${pct === null || pct === undefined ? "–" : Math.round(pct) + "%"}`}>
      <span className="meter-label">{label}</span>
      <span className="meter-bar">
        <span style={{ width: `${Math.max(0, Math.min(100, pct || 0))}%` }} />
      </span>
      <span className="meter-value">{pct === null || pct === undefined ? "–" : `${Math.round(pct)}%`}</span>
    </span>
  );
}

// values: numbers or nulls (gaps). max: fixed top of the scale (e.g. 100 for percentages).
export function Sparkline({ values, max, width = 220, height = 36, label }) {
  const pts = (values || []).map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
  if (pts.length < 2) return <span className="muted small">not enough history yet</span>;
  const n = values.length - 1 || 1;
  const top = max || Math.max(...pts.map(([, v]) => v)) || 1;
  const x = (i) => (i / n) * (width - 2) + 1;
  const y = (v) => height - 2 - (Math.min(v, top) / top) * (height - 4);
  const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={label}>
      <path d={`${d} L${x(pts[pts.length - 1][0]).toFixed(1)},${height - 1} L${x(pts[0][0]).toFixed(1)},${height - 1} Z`} className="spark-area" />
      <path d={d} className="spark-line" />
      
    </svg>
  );
}
