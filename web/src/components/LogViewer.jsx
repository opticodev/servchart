import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";

const TAILS = [100, 500, 2000];
const FOLLOW_MS = 3000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// One request through the hub. Agent hosts answer asynchronously: poll until done.
async function fetchLogs(hostPk, container, tail, since, cancelled) {
  let r = await api.requestLogs(hostPk, container, tail, since);
  while (r.status === "pending" || r.status === "sent") {
    await sleep(800);
    if (cancelled()) return null;
    r = await api.logResult(r.id);
  }
  if (r.status === "error") throw new Error(r.error);
  return r;
}

const key = (l) => `${l.t}|${l.s}|${l.m}`;
const toSeconds = (t) => {
  const ms = Date.parse(t);
  return Number.isNaN(ms) ? null : Math.floor(ms / 1000);
};

export default function LogViewer({ hostPk, hostName, container, onClose }) {
  const [tail, setTail] = useState(200);
  const [lines, setLines] = useState([]);
  const [meta, setMeta] = useState({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [follow, setFollow] = useState(false);
  const [wrap, setWrap] = useState(true);
  const [query, setQuery] = useState("");
  const [onlyErr, setOnlyErr] = useState(false);
  const bodyRef = useRef(null);
  const atBottom = useRef(true);
  const linesRef = useRef([]);
  linesRef.current = lines;

  const load = useCallback(
    async (cancelled) => {
      setLoading(true);
      setError("");
      try {
        const r = await fetchLogs(hostPk, container, tail, null, cancelled);
        if (!r || cancelled()) return;
        setLines(r.lines || []);
        setMeta({ truncated: r.truncated, redacted: r.redacted });
        atBottom.current = true;
      } catch (e) {
        if (!cancelled()) setError(e.message);
      } finally {
        if (!cancelled()) setLoading(false);
      }
    },
    [hostPk, container, tail]
  );

  useEffect(() => {
    let stop = false;
    load(() => stop);
    return () => {
      stop = true;
    };
  }, [load]);

  // follow: ask for lines since the newest one we have, merge without duplicates
  useEffect(() => {
    if (!follow) return undefined;
    let stop = false;
    (async () => {
      while (!stop) {
        await sleep(FOLLOW_MS);
        if (stop) break;
        const last = linesRef.current[linesRef.current.length - 1];
        const since = last ? toSeconds(last.t) : Math.floor(Date.now() / 1000) - 5;
        try {
          const r = await fetchLogs(hostPk, container, 2000, since, () => stop);
          if (!r || stop) break;
          setLines((prev) => {
            const seen = new Set(prev.slice(-2000).map(key));
            const fresh = (r.lines || []).filter((l) => !seen.has(key(l)));
            return fresh.length ? [...prev, ...fresh].slice(-5000) : prev;
          });
        } catch (e) {
          setError(e.message);
          setFollow(false);
          break;
        }
      }
    })();
    return () => {
      stop = true;
    };
  }, [follow, hostPk, container]);

  useEffect(() => {
    const el = bodyRef.current;
    if (el && atBottom.current) el.scrollTop = el.scrollHeight;
  }, [lines, query, onlyErr, wrap]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return lines.filter((l) => (!onlyErr || l.s === "err") && (!q || l.m.toLowerCase().includes(q)));
  }, [lines, query, onlyErr]);

  function download() {
    const text = lines.map((l) => `${l.t} ${l.s === "err" ? "E" : "O"} ${l.m}`).join("\n") + "\n";
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${hostName}-${container}-${new Date().toISOString().slice(0, 19).replace(/:/g, "")}.log`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal logs" role="dialog" aria-label={`Logs of ${container}`}>
        <div className="logs-head">
          <h2>
            <span className="muted">{hostName} /</span> {container}
          </h2>
          <button className="close" onClick={onClose} aria-label="Close logs">
            ×
          </button>
        </div>
        <div className="logs-toolbar">
          <input type="search" placeholder="Filter lines…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select value={tail} onChange={(e) => setTail(Number(e.target.value))} aria-label="Lines">
            {[200, ...TAILS].filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => a - b).map((n) => (
              <option key={n} value={n}>
                last {n} lines
              </option>
            ))}
          </select>
          <label className="toggle">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Follow
          </label>
          <label className="toggle">
            <input type="checkbox" checked={onlyErr} onChange={(e) => setOnlyErr(e.target.checked)} /> stderr only
          </label>
          <label className="toggle">
            <input type="checkbox" checked={wrap} onChange={(e) => setWrap(e.target.checked)} /> Wrap
          </label>
          <button className="btn btn-ghost btn-small" onClick={() => load(() => false)} disabled={loading}>
            Refresh
          </button>
          <button className="btn btn-ghost btn-small" onClick={download} disabled={!lines.length}>
            Download
          </button>
        </div>
        {error && <div className="logs-error">{error}</div>}
        <div
          ref={bodyRef}
          className={`logs-body${wrap ? " wrap" : ""}`}
          onScroll={(e) => {
            const el = e.currentTarget;
            atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          }}
        >
          {loading && !lines.length ? <div className="muted">Asking {hostName} for the logs…</div> : null}
          {!loading && !error && !lines.length ? <div className="muted">No log lines.</div> : null}
          {shown.map((l, i) => (
            <div key={i} className={`log-line${l.s === "err" ? " is-err" : ""}`}>
              <span className="log-time" title={l.t}>
                {l.t ? l.t.slice(5, 19).replace("T", " ") : ""}
              </span>
              <span className="log-msg">{l.m}</span>
            </div>
          ))}
        </div>
        <div className="logs-foot muted small">
          {shown.length} of {lines.length} lines
          {meta.truncated ? " · cut at the size limit" : ""}
          {meta.redacted ? " · secret-looking values were redacted by the agent" : ""}
          {follow ? " · following" : ""} · Viewing logs is recorded in the activity log.
        </div>
      </div>
    </div>
  );
}
