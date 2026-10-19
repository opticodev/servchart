import { useState } from "react";
import { api } from "../api.js";

function CommandBox({ command }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="cmd">
      <pre>{command}</pre>
      <button
        className="btn btn-small"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(command);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            /* clipboard not available (http) - user can select the text */
          }
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

// mode "add": ask for a name, create the host. mode "rotate": show a fresh token for an existing host.
export default function AddHostDialog({ onClose, onDone, rotateHost }) {
  const [name, setName] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e?.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = rotateHost ? await api.rotateToken(rotateHost.pk) : await api.addHost(name.trim());
      setResult(r);
      onDone?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="add-host-title">
        <h2 id="add-host-title">{rotateHost ? `New token for ${rotateHost.name}` : "Add a host"}</h2>
        {!result ? (
          <form onSubmit={submit}>
            {rotateHost ? (
              <p>The current token stops working immediately. You'll need to restart the agent on {rotateHost.name} with the new token.</p>
            ) : (
              <>
                <label htmlFor="host-name">Name shown on the map</label>
                <input id="host-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. nas, web-01" autoFocus required maxLength={128} />
              </>
            )}
            {error && <p className="error">{error}</p>}
            <div className="actions">
              <button type="button" className="btn btn-ghost" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" className="btn" disabled={busy || (!rotateHost && !name.trim())}>
                {rotateHost ? "Rotate token" : "Create"}
              </button>
            </div>
          </form>
        ) : (
          <>
            <p>
              Run this on the host. It needs Docker and outbound access to this hub. <strong>The token is shown only once.</strong>
            </p>
            <CommandBox command={result.install_command} />
            <p className="muted small">
              The agent only reads Docker's state and never sends environment variables. Mounting the socket still gives the container broad access to Docker; see the README for running it behind a read-only socket proxy.
            </p>
            <div className="actions">
              <button className="btn" onClick={onClose}>
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
