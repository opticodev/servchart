import { useState } from "react";

export default function Legend({ hosts, linkMode, lineStyle, onLineStyle }) {
  const [open, setOpen] = useState(true);
  const observing = hosts.filter((h) => h.info?.observe === "on").length;
  return (
    <div className={`legend ${open ? "" : "is-closed"}`}>
      <button className="legend-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        Legend {open ? "▾" : "▸"}
      </button>
      {open && (
        <ul>
          <li>
            <svg width="34" height="10" aria-hidden>
              <line x1="0" y1="5" x2="34" y2="5" className="lg-flow" />
            </svg>
            Traffic seen (with port)
          </li>
          <li>
            <svg width="34" height="10" aria-hidden>
              <line x1="0" y1="5" x2="34" y2="5" className="lg-cross" />
            </svg>
            Traffic to another server
          </li>
          <li>
            <svg width="34" height="10" aria-hidden>
              <line x1="0" y1="5" x2="34" y2="5" className="lg-depends" />
            </svg>
            Depends on (Compose)
          </li>
          <li>
            <svg width="34" height="10" aria-hidden>
              <line x1="0" y1="5" x2="34" y2="5" className="lg-network" />
            </svg>
            Attached to network
          </li>
          <li className="small muted">
            Point at a container:{" "}
            <svg width="22" height="8" aria-hidden>
              <line x1="0" y1="4" x2="22" y2="4" className="lg-out" />
            </svg>{" "}
            calls,{" "}
            <svg width="22" height="8" aria-hidden>
              <line x1="0" y1="4" x2="22" y2="4" className="lg-in" />
            </svg>{" "}
            called by
          </li>
          <li className="legend-style">
            Lines:
            {[
              ["angled", "angled"],
              ["curved", "curved"],
            ].map(([v, label]) => (
              <button key={v} type="button" className={lineStyle === v ? "is-active" : ""} onClick={() => onLineStyle(v)}>
                {label}
              </button>
            ))}
          </li>
          {linkMode === "overview" && (
            <li className="muted small">Overview: lines are merged per stack and per server. Click a server, stack or container to see its own lines in full.</li>
          )}
          <li className="muted small">
            Traffic observed on {observing} of {hosts.length} host{hosts.length === 1 ? "" : "s"}
            {observing < hosts.length ? " (enable with SERVCHART_OBSERVE_CONNECTIONS=1 and --pid host)" : ""}
          </li>
        </ul>
      )}
    </div>
  );
}
