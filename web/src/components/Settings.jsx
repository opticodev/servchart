import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

function ago(iso) {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function Notice({ notice, onClose }) {
  if (!notice) return null;
  return (
    <div className={`notice ${notice.error ? "is-error" : ""}`} role="status">
      <div>
        {notice.text}
        {notice.secret && (
          <div className="secret">
            <code>{notice.secret}</code>
            <span className="muted small"> - shown once, copy it now</span>
          </div>
        )}
      </div>
      <button className="close" onClick={onClose} aria-label="Dismiss">
        ×
      </button>
    </div>
  );
}

function useAction(setNotice, reload) {
  return useCallback(
    async (fn, ok) => {
      try {
        const result = await fn();
        setNotice(typeof ok === "function" ? ok(result) : ok ? { text: ok } : null);
        await reload();
        return true;
      } catch (e) {
        setNotice({ text: e.message, error: true });
        return false;
      }
    },
    [setNotice, reload]
  );
}

function HostsTab({ me, onRotate, onAdd }) {
  const [hosts, setHosts] = useState([]);
  const [editing, setEditing] = useState(null); // {pk, name}
  const [notice, setNotice] = useState(null);
  const load = useCallback(async () => setHosts(await api.hosts()), []);
  const act = useAction(setNotice, load);
  useEffect(() => {
    load().catch((e) => setNotice({ text: e.message, error: true }));
  }, [load]);

  return (
    <section>
      <div className="section-head">
        <h2>Hosts</h2>
        {me.is_staff && (
          <button className="btn" onClick={onAdd}>
            + Add host
          </button>
        )}
      </div>
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Last report</th>
              <th>Containers</th>
              <th>Agent</th>
              <th>Traffic</th>
              {me.is_staff && <th aria-label="Actions" />}
            </tr>
          </thead>
          <tbody>
            {hosts.map((h) => (
              <tr key={h.pk} className={h.enabled ? "" : "is-disabled"}>
                <td>
                  {editing?.pk === h.pk ? (
                    <form
                      className="inline-form"
                      onSubmit={(e) => {
                        e.preventDefault();
                        act(() => api.updateHost(h.pk, { name: editing.name.trim() }), "Host renamed.").then((done) => done && setEditing(null));
                      }}
                    >
                      <input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} autoFocus maxLength={128} />
                      <button className="btn btn-small">Save</button>
                      <button type="button" className="btn btn-small btn-ghost" onClick={() => setEditing(null)}>
                        Cancel
                      </button>
                    </form>
                  ) : (
                    <>
                      <strong>{h.name}</strong>
                      {h.is_local && <span className="tag">this hub</span>}
                    </>
                  )}
                </td>
                <td>
                  <span className={`dot dot-${h.enabled ? h.status : "exited"}`} /> {h.enabled ? h.status : "disabled"}
                </td>
                <td>{ago(h.last_seen)}</td>
                <td>
                  {h.counts.running}/{h.counts.containers}
                </td>
                <td className="mono">{h.agent_version || "-"}</td>
                <td>{h.info?.observe === "on" ? "observed" : h.info?.observe === "unavailable" ? "needs --pid host" : "off"}</td>
                {me.is_staff && (
                  <td className="row-actions">
                    <button className="btn btn-small btn-ghost" onClick={() => setEditing({ pk: h.pk, name: h.name })}>
                      Rename
                    </button>
                    {!h.is_local && (
                      <>
                        <button
                          className="btn btn-small btn-ghost"
                          onClick={() => act(() => api.updateHost(h.pk, { enabled: !h.enabled }), h.enabled ? `${h.name} disabled: its token no longer works.` : `${h.name} enabled.`)}
                        >
                          {h.enabled ? "Disable" : "Enable"}
                        </button>
                        <button className="btn btn-small btn-ghost" onClick={() => onRotate(h)}>
                          New token
                        </button>
                        <button
                          className="btn btn-small btn-danger"
                          onClick={() => {
                            if (window.confirm(`Delete ${h.name}? Stop its agent first (docker rm -f servchart-agent on that server), or it keeps trying to report.`))
                              act(() => api.deleteHost(h.pk), `${h.name} deleted.`);
                          }}
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {me.is_staff && <PublicAddresses />}
    </section>
  );
}

function PublicAddresses() {
  const [text, setText] = useState("");
  const [resolved, setResolved] = useState([]);
  const [notice, setNotice] = useState(null);
  const load = useCallback(async () => {
    const r = await api.publicAddresses();
    setText(r.addresses.join("\n"));
    setResolved(r.resolved);
  }, []);
  const act = useAction(setNotice, load);
  useEffect(() => {
    load().catch(() => {});
  }, [load]);
  return (
    <div className="addresses">
      <h3>Your public addresses</h3>
      <p className="muted small">
        The public IP of your router (or a DNS name pointing straight at it, like a DDNS name). Servers outside your network that connect to it, through
        your port forwards, get a line to the container publishing that port. Agents report connections to these addresses only. Names behind Cloudflare's proxy
        don't work: they resolve to Cloudflare's shared addresses.
      </p>
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <form
        className="password-form wide"
        onSubmit={(e) => {
          e.preventDefault();
          act(() => api.setPublicAddresses(text), "Saved. Agents pick this up with their next report.");
        }}
      >
        <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder={"203.0.113.7\nhome.example.net"} />
        {resolved.length > 0 && <span className="muted small">Resolves to {resolved.join(", ")}</span>}
        <button className="btn">Save</button>
      </form>
    </div>
  );
}

function UsersTab({ me }) {
  const [users, setUsers] = useState([]);
  const [notice, setNotice] = useState(null);
  const [form, setForm] = useState({ username: "", email: "", password: "", is_staff: false });
  const load = useCallback(async () => setUsers(await api.users()), []);
  const act = useAction(setNotice, load);
  useEffect(() => {
    load().catch((e) => setNotice({ text: e.message, error: true }));
  }, [load]);

  return (
    <section>
      <div className="section-head">
        <h2>Users</h2>
      </div>
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <form
        className="add-user"
        onSubmit={(e) => {
          e.preventDefault();
          act(
            () => api.createUser({ ...form, username: form.username.trim() }),
            (u) => ({ text: `${u.username} created.`, secret: u.password ? `Password: ${u.password}` : null })
          ).then((done) => done && setForm({ username: "", email: "", password: "", is_staff: false }));
        }}
      >
        <input placeholder="Username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required maxLength={150} />
        <input placeholder="Email (optional)" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <input placeholder="Password (blank = generate)" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" />
        <label className="toggle">
          <input type="checkbox" checked={form.is_staff} onChange={(e) => setForm({ ...form, is_staff: e.target.checked })} /> Admin
        </label>
        <button className="btn">Add user</button>
      </form>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>User</th>
              <th>Role</th>
              <th>Sign-in</th>
              <th>Last login</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const self = u.id === me.id;
              return (
                <tr key={u.id} className={u.is_active ? "" : "is-disabled"}>
                  <td>
                    <strong>{u.username}</strong>
                    {self && <span className="tag">you</span>}
                    {u.email && <div className="muted small">{u.email}</div>}
                  </td>
                  <td>{u.is_staff ? "Admin" : "Viewer"}</td>
                  <td>{u.sso ? "Single sign-on" : "Password"}</td>
                  <td>{ago(u.last_login)}</td>
                  <td className="row-actions">
                    {!self && (
                      <button className="btn btn-small btn-ghost" onClick={() => act(() => api.updateUser(u.id, { is_staff: !u.is_staff }), `${u.username} is now ${u.is_staff ? "a viewer" : "an admin"}.`)}>
                        {u.is_staff ? "Make viewer" : "Make admin"}
                      </button>
                    )}
                    {!u.sso && (
                      <button
                        className="btn btn-small btn-ghost"
                        onClick={() => {
                          if (window.confirm(`Set a new random password for ${u.username}?`))
                            act(() => api.resetPassword(u.id), (r) => ({ text: `New password for ${u.username}.`, secret: r.password }));
                        }}
                      >
                        Reset password
                      </button>
                    )}
                    {!self && (
                      <button className="btn btn-small btn-ghost" onClick={() => act(() => api.updateUser(u.id, { is_active: !u.is_active }), `${u.username} ${u.is_active ? "deactivated" : "reactivated"}.`)}>
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    )}
                    {!self && (
                      <button
                        className="btn btn-small btn-danger"
                        onClick={() => {
                          if (window.confirm(`Delete ${u.username}?`)) act(() => api.deleteUser(u.id), `${u.username} deleted.`);
                        }}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {me.sso_enabled && <p className="muted small">Single sign-on is on: people who sign in through your identity provider get an account automatically. Their admin rights follow the identity provider's groups.</p>}
    </section>
  );
}

function AccountTab({ me }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [notice, setNotice] = useState(null);

  async function submit(e) {
    e.preventDefault();
    if (next !== confirm) return setNotice({ text: "The new passwords don't match.", error: true });
    try {
      await api.changeMyPassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setNotice({ text: "Password changed." });
    } catch (err) {
      setNotice({ text: err.message, error: true });
    }
  }

  return (
    <section>
      <div className="section-head">
        <h2>My account</h2>
      </div>
      <p>
        Signed in as <strong>{me.username}</strong> ({me.is_staff ? "admin" : "viewer"}).
      </p>
      <Notice notice={notice} onClose={() => setNotice(null)} />
      {me.sso_user ? (
        <p className="muted">You sign in through single sign-on, so your password is managed by your identity provider.</p>
      ) : (
        <form className="password-form" onSubmit={submit}>
          <label>
            Current password
            <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
          </label>
          <label>
            New password
            <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required minLength={8} />
          </label>
          <label>
            Repeat new password
            <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required minLength={8} />
          </label>
          <button className="btn">Change password</button>
        </form>
      )}
    </section>
  );
}

function AppearanceTab({ onBranding }) {
  const [b, setB] = useState(null);
  const [name, setName] = useState("");
  const [color, setColor] = useState("");
  const [notice, setNotice] = useState(null);
  const load = useCallback(async () => {
    const r = await api.branding();
    setB(r);
    setName(r.app_name);
    setColor(r.accent_color || "");
    onBranding?.();
  }, [onBranding]);
  const act = useAction(setNotice, load);
  useEffect(() => {
    load().catch((e) => setNotice({ text: e.message, error: true }));
  }, [load]);
  if (!b) return <Notice notice={notice} onClose={() => setNotice(null)} />;

  const pick = (kind) => (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) act(() => api.uploadBrandingImage(kind, file), kind === "logo" ? "Logo updated." : "Favicon updated.");
  };

  return (
    <section>
      <div className="section-head">
        <h2>Appearance</h2>
      </div>
      <p className="muted">Shown in the top bar, the browser tab, the sign-in page and reports.</p>
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <form
        className="password-form"
        onSubmit={(e) => {
          e.preventDefault();
          act(() => api.updateBranding({ app_name: name.trim(), accent_color: color }), "Appearance saved.");
        }}
      >
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} required />
        </label>
        <label>
          Accent color
          <span className="color-row">
            <input type="color" value={color || "#2563eb"} onChange={(e) => setColor(e.target.value)} aria-label="Pick accent color" />
            <input value={color} onChange={(e) => setColor(e.target.value)} placeholder="default" pattern="#[0-9a-fA-F]{6}" maxLength={7} />
            {color && (
              <button type="button" className="btn btn-small btn-ghost" onClick={() => setColor("")}>
                Default
              </button>
            )}
          </span>
        </label>
        <button className="btn">Save</button>
      </form>

      {[
        ["logo", "Logo", "PNG, SVG, WebP or JPEG, up to 512 KB. Shown about 24 px high."],
        ["favicon", "Favicon", "Square PNG, ICO or SVG, up to 512 KB."],
      ].map(([kind, label, hint]) => {
        const url = kind === "logo" ? b.logo_url : b.favicon_url;
        return (
          <div key={kind} className="image-setting">
            <h3>{label}</h3>
            <div className="image-row">
              <div className={`image-preview ${kind}`}>{url ? <img src={url} alt="" /> : <span className="muted small">default</span>}</div>
              <label className="btn btn-small btn-ghost file-btn">
                {url ? "Replace…" : "Upload…"}
                <input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml,image/x-icon,.ico" onChange={pick(kind)} />
              </label>
              {url && (
                <button className="btn btn-small btn-danger" onClick={() => act(() => api.deleteBrandingImage(kind), `${label} removed.`)}>
                  Remove
                </button>
              )}
            </div>
            <p className="muted small">{hint}</p>
          </div>
        );
      })}
    </section>
  );
}

const SCHEDULE_LABELS = { off: "Off", daily: "Every day", weekly: "Every Monday", monthly: "On the 1st of each month" };

function ReportsTab() {
  const [cfg, setCfg] = useState(null);
  const [schedule, setSchedule] = useState("off");
  const [recipients, setRecipients] = useState("");
  const [notice, setNotice] = useState(null);
  const load = useCallback(async () => {
    const r = await api.reportSchedule();
    setCfg(r);
    setSchedule(r.schedule);
    setRecipients(r.recipients.join(", "));
  }, []);
  const act = useAction(setNotice, load);
  useEffect(() => {
    load().catch((e) => setNotice({ text: e.message, error: true }));
  }, [load]);

  const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "never");
  return (
    <section>
      <div className="section-head">
        <h2>Reports</h2>
      </div>
      <p className="muted">A summary of hosts, stacks and containers, things worth a look (unhealthy or restarting containers, unpinned images, ports open on every interface…) and who talks to whom.</p>
      <div className="btn-row">
        <a className="btn" href="/report/" target="_blank" rel="noopener">
          Open printable report
        </a>
        <a className="btn btn-ghost" href="/api/v1/report.json?download=1">
          JSON
        </a>
        {["containers", "ports", "connections", "findings", "hosts", "backups", "certificates", "updates"].map((k) => (
          <a key={k} className="btn btn-ghost" href={`/api/v1/report/${k}.csv`}>
            {k[0].toUpperCase() + k.slice(1)} CSV
          </a>
        ))}
      </div>
      <p className="muted small">Use your browser's Print → Save as PDF on the printable report for a PDF.</p>

      <h3>Email</h3>
      <Notice notice={notice} onClose={() => setNotice(null)} />
      {cfg && !cfg.email_configured && (
        <div className="notice is-error">
          <div>
            Email isn't set up on the hub. Set <code>SERVCHART_SMTP_HOST</code>, <code>SERVCHART_SMTP_USER</code>, <code>SERVCHART_SMTP_PASSWORD</code> and <code>SERVCHART_SMTP_FROM</code> (see README → Reports).
          </div>
        </div>
      )}
      {cfg && (
        <form
          className="password-form wide"
          onSubmit={(e) => {
            e.preventDefault();
            act(() => api.updateReportSchedule({ schedule, recipients }), "Schedule saved.");
          }}
        >
          <label>
            Recipients
            <input value={recipients} onChange={(e) => setRecipients(e.target.value)} placeholder="ops@example.com, me@example.com" />
          </label>
          <label>
            Send automatically
            <select value={schedule} onChange={(e) => setSchedule(e.target.value)}>
              {Object.entries(SCHEDULE_LABELS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                  {k !== "off" ? ` at ${String(cfg.hour).padStart(2, "0")}:00` : ""}
                </option>
              ))}
            </select>
          </label>
          <div className="btn-row">
            <button className="btn">Save</button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={!cfg.email_configured || !recipients.trim()}
              onClick={() => act(() => api.sendReport(recipients), (r) => ({ text: `Report sent to ${r.recipients.join(", ")}.` }))}
            >
              Send now
            </button>
          </div>
          <p className="muted small">
            Last sent: {fmt(cfg.last_sent)}
            {cfg.next_run ? ` · next: ${fmt(cfg.next_run)}` : ""}
            {cfg.from_email ? ` · from ${cfg.from_email}` : ""}
          </p>
        </form>
      )}
    </section>
  );
}

function ChecksTab() {
  const [certs, setCerts] = useState([]);
  const [images, setImages] = useState(null);
  const [hostname, setHostname] = useState("");
  const [busy, setBusy] = useState(false);
  const [onlyUpdates, setOnlyUpdates] = useState(true);
  const [notice, setNotice] = useState(null);
  const load = useCallback(async () => {
    const [c, i] = await Promise.all([api.certs(), api.imageChecks()]);
    setCerts(c);
    setImages(i);
  }, []);
  const act = useAction(setNotice, load);
  useEffect(() => {
    load().catch((e) => setNotice({ text: e.message, error: true }));
  }, [load]);

  const certState = (c) => (c.error || (c.days_left !== null && c.days_left < 7) ? "failed" : c.days_left !== null && c.days_left < 14 ? "overdue" : c.days_left === null ? "pending" : "ok");
  const rows = (images?.items || []).filter((r) => !onlyUpdates || r.state === "update" || r.newer_tag);
  return (
    <section>
      <div className="section-head">
        <h2>Certificates</h2>
      </div>
      <p className="muted">The hub connects to each address every few hours and warns 14 days before the certificate expires, or when it isn't trusted.</p>
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <form
        className="add-user"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          if (await act(() => api.addCert(hostname.trim()), (c) => ({ text: c.error ? `Added ${c.hostname}: ${c.error}` : `Added ${c.hostname}: ${c.days_left} days left.` }))) setHostname("");
          setBusy(false);
        }}
      >
        <input value={hostname} onChange={(e) => setHostname(e.target.value)} placeholder="example.com or example.com:8443" required />
        <button className="btn" disabled={busy}>
          {busy ? "Checking…" : "Add"}
        </button>
      </form>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Address</th>
              <th>State</th>
              <th>Expires</th>
              <th>Issuer</th>
              <th>Checked</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {certs.map((c) => (
              <tr key={c.id}>
                <td className="mono">
                  {c.hostname}
                  {c.port !== 443 ? `:${c.port}` : ""}
                </td>
                <td>
                  <span className={`state-pill pill-${certState(c)}`}>{c.error ? "error" : c.days_left === null ? "pending" : `${c.days_left} d`}</span>
                  {c.error && <div className="small muted">{c.error}</div>}
                </td>
                <td>{c.expires_at ? new Date(c.expires_at).toLocaleDateString() : "–"}</td>
                <td>{c.issuer || "–"}</td>
                <td>{ago(c.checked_at)}</td>
                <td className="row-actions">
                  <button className="btn btn-small btn-ghost" onClick={() => act(() => api.recheckCert(c.id), "Checked again.")}>
                    Check now
                  </button>
                  <button className="btn btn-small btn-danger" onClick={() => act(() => api.deleteCert(c.id), `Removed ${c.hostname}.`)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {!certs.length && (
              <tr>
                <td colSpan={6} className="muted">
                  No certificates watched yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="section-head" style={{ marginTop: 28 }}>
        <h2>Image updates</h2>
        <div className="btn-row" style={{ margin: 0 }}>
          <label className="toggle">
            <input type="checkbox" checked={onlyUpdates} onChange={(e) => setOnlyUpdates(e.target.checked)} /> Only updates
          </label>
          {images?.enabled && (
            <button
              className="btn btn-small btn-ghost"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                await act(() => api.runImageChecks(), "Checked all images.");
                setBusy(false);
              }}
            >
              {busy ? "Checking…" : "Check now"}
            </button>
          )}
        </div>
      </div>
      <p className="muted">
        {images?.enabled
          ? `Every ${images.every_hours} h the hub asks each image's registry, anonymously, whether its tag now points to a newer image and whether a higher version exists. Only image names and tags are sent.`
          : "Image checks are turned off on this hub (SERVCHART_IMAGE_CHECKS=0)."}
      </p>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Container</th>
              <th>Image</th>
              <th>Tag</th>
              <th>Newer version</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.host_pk}-${r.container}`}>
                <td>
                  <span className="muted">{r.host} /</span> {r.container}
                </td>
                <td className="mono small">{r.image}</td>
                <td>
                  <span className={`state-pill pill-${r.state}`} title={r.error || ""}>
                    {r.state === "update" ? "update" : r.state === "current" ? "current" : r.state === "pending" ? "not checked" : "unknown"}
                  </span>
                </td>
                <td className="mono">{r.newer_tag || ""}</td>
              </tr>
            ))}
            {images && !rows.length && (
              <tr>
                <td colSpan={4} className="muted">
                  {onlyUpdates ? "Everything is up to date (or not checked yet)." : "No images."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const ACTION_LABELS = {
  "logs.view": "viewed logs",
  "host.create": "added host",
  "host.update": "changed host",
  "host.delete": "deleted host",
  "host.rotate_token": "rotated token",
  "user.create": "added user",
  "user.update": "changed user",
  "user.delete": "deleted user",
  "user.reset_password": "reset password of",
  "me.password": "changed own password",
  "branding.update": "changed appearance",
  "branding.logo.upload": "uploaded logo",
  "branding.logo.remove": "removed logo",
  "branding.favicon.upload": "uploaded favicon",
  "branding.favicon.remove": "removed favicon",
  "report.send": "emailed report to",
  "report.schedule": "set report schedule",
  "report.scheduled": "scheduled report sent to",
  "report.scheduled.failed": "scheduled report failed for",
  "check.cert.add": "watches certificate of",
  "addresses.update": "set public addresses to",
  "check.cert.remove": "stopped watching certificate of",
};

function ActivityTab() {
  const [events, setEvents] = useState(null);
  const [filter, setFilter] = useState("");
  const [notice, setNotice] = useState(null);
  useEffect(() => {
    api.audit(filter).then(setEvents).catch((e) => setNotice({ text: e.message, error: true }));
  }, [filter]);
  return (
    <section>
      <div className="section-head">
        <h2>Activity</h2>
        <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter">
          <option value="">Everything</option>
          <option value="logs.">Log views</option>
          <option value="host.">Hosts</option>
          <option value="user.">Users</option>
          <option value="branding.">Appearance</option>
          <option value="report.">Reports</option>
          <option value="check.">Checks</option>
        </select>
      </div>
      <Notice notice={notice} onClose={() => setNotice(null)} />
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>When</th>
              <th>Who</th>
              <th>What</th>
              <th>From</th>
            </tr>
          </thead>
          <tbody>
            {(events || []).map((e) => (
              <tr key={e.id}>
                <td title={new Date(e.at).toLocaleString()}>{ago(e.at)}</td>
                <td>{e.user || <span className="muted">system</span>}</td>
                <td>
                  {ACTION_LABELS[e.action] || e.action} <strong>{e.target}</strong>
                  {e.detail?.renamed_from ? <span className="muted"> (was {e.detail.renamed_from})</span> : null}
                  {e.detail?.error ? <span className="muted"> - {e.detail.error}</span> : null}
                </td>
                <td className="mono small">{e.ip || ""}</td>
              </tr>
            ))}
            {events && !events.length && (
              <tr>
                <td colSpan={4} className="muted">
                  Nothing recorded yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function Settings({ me, onClose, onRotate, onAdd, onBranding }) {
  const tabs = [
    ["hosts", "Hosts"],
    ...(me.is_staff ? [["users", "Users"], ["checks", "Checks"], ["appearance", "Appearance"], ["reports", "Reports"], ["activity", "Activity"]] : []),
    ["account", "My account"],
  ];
  const [tab, setTab] = useState("hosts");
  return (
    <div className="settings">
      <div className="settings-inner">
        <div className="settings-top">
          <nav className="tabs" role="tablist">
            {tabs.map(([key, label]) => (
              <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "is-active" : ""} onClick={() => setTab(key)}>
                {label}
              </button>
            ))}
          </nav>
          <button className="btn btn-ghost" onClick={onClose}>
            ← Back to map
          </button>
        </div>
        {tab === "hosts" && <HostsTab me={me} onRotate={onRotate} onAdd={onAdd} />}
        {tab === "users" && me.is_staff && <UsersTab me={me} />}
        {tab === "appearance" && me.is_staff && <AppearanceTab onBranding={onBranding} />}
        {tab === "checks" && me.is_staff && <ChecksTab />}
        {tab === "reports" && me.is_staff && <ReportsTab />}
        {tab === "activity" && me.is_staff && <ActivityTab />}
        {tab === "account" && <AccountTab me={me} />}
      </div>
    </div>
  );
}
