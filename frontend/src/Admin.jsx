import { useConfirm } from "./Confirm.jsx";
import { useCallback, useEffect, useState } from "react";
import { api, money, timeAgo } from "./api.js";
import { BotIcon } from "./Sidebar.jsx";

function Users({ me, onUsageChange }) {
  const [users, setUsers] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [error, setError] = useState("");
  const load = useCallback(() => api.get("/api/admin/users").then(setUsers).catch((e) => setError(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);

  const update = async (u, body) => {
    setError("");
    try {
      await api.patch(`/api/admin/users/${u.id}`, body);
      setDrafts((d) => ({ ...d, [u.id]: undefined }));
      await load();
      if (u.id === me.id) onUsageChange();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <section>
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>User</th>
              <th>Role</th>
              <th>Used</th>
              <th>Limit (USD)</th>
              <th>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const draft = drafts[u.id];
              const pct = u.limit_usd > 0 ? Math.min(100, (u.spent_usd / u.limit_usd) * 100) : 100;
              return (
                <tr key={u.id}>
                  <td>
                    <div className="strong">{u.name}</div>
                    <div className="muted small">{u.email}</div>
                  </td>
                  <td>
                    <select
                      value={u.role}
                      disabled={u.locked_admin}
                      title={u.locked_admin ? "Set by ADMIN_EMAILS" : ""}
                      onChange={(e) => update(u, { role: e.target.value })}
                    >
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                  <td>
                    {money(u.spent_usd)}
                    <div className="bar small">
                      <div className={`bar-fill ${pct >= 90 ? "danger" : pct >= 70 ? "warn" : ""}`} style={{ width: `${pct}%` }} />
                    </div>
                  </td>
                  <td>
                    <form
                      className="inline-form"
                      onSubmit={(e) => {
                        e.preventDefault();
                        update(u, { limit_usd: Number(draft) });
                      }}
                    >
                      <input
                        type="number"
                        min="0"
                        step="0.1"
                        value={draft ?? u.limit_usd}
                        onChange={(e) => setDrafts((d) => ({ ...d, [u.id]: e.target.value }))}
                      />
                      {draft !== undefined && <button className="btn small primary">Save</button>}
                    </form>
                  </td>
                  <td className="muted small">{timeAgo(u.last_seen_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Access() {
  const [data, setData] = useState({ grants: [], admin_emails: [] });
  const [confirmAsk, confirmDialog] = useConfirm();
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(() => api.get("/api/admin/access").then(setData).catch((e) => setError(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);

  const add = async (e) => {
    e.preventDefault();
    setError("");
    try {
      await api.post("/api/admin/access", { email });
      setEmail("");
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section>
      <p className="muted">
        Approve an email to let that person sign in with Google. Approving a company email (not Gmail, Outlook, etc.) gives everyone
        at that company's domain access.
      </p>
      <form className="add-form compact" onSubmit={add}>
        <input type="email" required placeholder="name@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        <button className="btn primary">Approve</button>
      </form>
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Email</th>
              <th>Access</th>
              <th>Added by</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.admin_emails.map((e) => (
              <tr key={`admin-${e}`}>
                <td>{e}</td>
                <td>
                  <span className="pill">Admin (env)</span>
                </td>
                <td className="muted small">ADMIN_EMAILS</td>
                <td />
              </tr>
            ))}
            {data.grants.map((g) => (
              <tr key={g.id}>
                <td>{g.email}</td>
                <td>{g.domain_access ? <span className="pill accent">Everyone @{g.domain_access}</span> : <span className="pill">This email</span>}</td>
                <td className="muted small">{g.created_by}</td>
                <td>
                  <button
                    className="btn ghost small danger"
                    onClick={async () => {
                      const ok = await confirmAsk({
                        title: `Remove access for ${g.email}?`,
                        message: g.domain_access ? `Everyone at @${g.domain_access} will lose access too.` : "They won't be able to sign in any more.",
                        confirmLabel: "Remove access",
                        danger: true,
                      });
                      if (!ok) return;
                      await api.del(`/api/admin/access/${g.id}`);
                      load();
                    }}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {confirmDialog}
    </section>
  );
}

function Budget({ onUsageChange }) {
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    api.get("/api/admin/budget").then((b) => setValue(String(b.global_budget_usd)));
  }, []);
  return (
    <section>
      <p className="muted">The total OpenRouter spend allowed across all users. Chat stops for everyone once it's reached.</p>
      <form
        className="add-form compact"
        onSubmit={async (e) => {
          e.preventDefault();
          await api.put("/api/admin/budget", { global_budget_usd: Number(value) });
          setSaved(true);
          onUsageChange();
          setTimeout(() => setSaved(false), 1500);
        }}
      >
        <span className="prefix">$</span>
        <input type="number" min="0" step="0.5" value={value} onChange={(e) => setValue(e.target.value)} />
        <button className="btn primary">{saved ? "Saved ✓" : "Save"}</button>
      </form>
    </section>
  );
}

function Bots({ sites, refreshSites }) {
  const [error, setError] = useState("");
  const [confirmAsk, confirmDialog] = useConfirm();
  const act = async (fn) => {
    setError("");
    try {
      await fn();
      await refreshSites();
    } catch (e) {
      setError(e.message);
    }
  };
  return (
    <section>
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Bot</th>
              <th>Status</th>
              <th>Pages</th>
              <th>Indexed</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {sites.map((s) => (
              <tr key={s.id}>
                <td>
                  <div className="cell-bot">
                    <BotIcon site={s} size={24} />
                    <div>
                      <div className="strong">{s.name} Chatbot</div>
                      <div className="muted small">{s.domain}</div>
                    </div>
                  </div>
                </td>
                <td>
                  <span className={`status ${s.running ? "crawling" : s.status}`}>{s.running ? "indexing" : s.status}</span>
                </td>
                <td>{s.pages_indexed}</td>
                <td className="muted small">{timeAgo(s.indexed_at) || "—"}</td>
                <td className="actions">
                  <button className="btn ghost small" disabled={s.running} onClick={() => act(() => api.post(`/api/admin/sites/${s.id}/reindex`))}>
                    Re-index
                  </button>
                  <button
                    className="btn ghost small danger"
                    disabled={s.running}
                    onClick={async () => {
                      const ok = await confirmAsk({
                        title: `Delete ${s.name} Chatbot?`,
                        message: "This deletes the bot, its index and everyone's chats with it. You can't undo this.",
                        confirmLabel: "Delete bot",
                        danger: true,
                      });
                      if (ok) act(() => api.del(`/api/admin/sites/${s.id}`));
                    }}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {confirmDialog}
    </section>
  );
}

const TABS = ["Users", "Access", "Bots", "Budget"];

export default function Admin({ me, sites, refreshSites, onUsageChange }) {
  const [tab, setTab] = useState("Users");
  return (
    <div className="page admin">
      <h1>Admin</h1>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      {tab === "Users" && <Users me={me} onUsageChange={onUsageChange} />}
      {tab === "Access" && <Access />}
      {tab === "Bots" && <Bots sites={sites} refreshSites={refreshSites} />}
      {tab === "Budget" && <Budget onUsageChange={onUsageChange} />}
    </div>
  );
}
