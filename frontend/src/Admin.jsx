import { useConfirm } from "./Confirm.jsx";
import { useCallback, useEffect, useState } from "react";
import { api, money, timeAgo } from "./api.js";
import { BotIcon } from "./Sidebar.jsx";
import { Tabs } from "./Tabs.jsx";
import AIProviders, { modelChoices } from "./AdminAI.jsx";

function Users({ me, onUsageChange, billing }) {
  const [users, setUsers] = useState([]);
  const [plans, setPlans] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [error, setError] = useState("");
  const load = useCallback(() => api.get("/api/admin/users").then(setUsers).catch((e) => setError(e.message)), []);
  useEffect(() => {
    load();
    if (billing) api.get("/api/admin/plans").then(setPlans).catch(() => {});
  }, [load, billing]);

  const setPlan = async (u, value) => {
    setError("");
    try {
      await api.patch(`/api/admin/users/${u.id}/plan`, { plan_id: value ? Number(value) : null });
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

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
              {billing && <th>Plan</th>}
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
                    <div className="strong">
                      {u.name} {u.locked_admin && <span className="pill accent" title="Permanent admin (ADMIN_EMAILS). Can't be demoted or removed.">Owner</span>}
                    </div>
                    <div className="muted small">{u.email}</div>
                  </td>
                  <td>
                    <select
                      value={u.role}
                      disabled={u.locked_admin}
                      title={u.locked_admin ? "Permanent admin: can't be demoted" : ""}
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
                        step="0.01"
                        value={draft ?? u.limit_usd}
                        onChange={(e) => setDrafts((d) => ({ ...d, [u.id]: e.target.value }))}
                      />
                      {draft !== undefined && <button className="btn small primary">Save</button>}
                    </form>
                  </td>
                  {billing && (
                    <td>
                      <select aria-label="Plan" value={u.plan_id ?? ""} onChange={(e) => setPlan(u, e.target.value)}>
                        <option value="">No plan</option>
                        {plans.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </td>
                  )}
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
  const [requireApproval, setRequireApproval] = useState(null);
  const load = useCallback(() => api.get("/api/admin/access").then(setData).catch((e) => setError(e.message)), []);
  useEffect(() => {
    load();
    api.get("/api/admin/settings").then((s) => setRequireApproval(s.require_approval)).catch(() => {});
  }, [load]);

  const toggleApproval = async () => {
    const next = !requireApproval;
    setRequireApproval(next);
    try {
      await api.put("/api/admin/settings", { require_approval: next });
    } catch (e) {
      setRequireApproval(!next);
      setError(e.message);
    }
  };

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
      <div className="setting-row">
        <div>
          <strong>Require approval for new users</strong>
          <p className="muted">
            {requireApproval
              ? "On: only the emails and company domains approved below can sign in."
              : "Off: anyone can create an account (their email is verified with a code) or sign in with Google."}
          </p>
        </div>
        <button
          role="switch"
          aria-checked={!!requireApproval}
          aria-label="Require approval for new users"
          className={`switch ${requireApproval ? "on" : ""}`}
          disabled={requireApproval === null}
          onClick={toggleApproval}
        >
          <span />
        </button>
      </div>
      <p className="muted">
        Approve an email to let that person sign in, with Google or by creating an account with that email. Approving a company
        email (not Gmail, Outlook, etc.) gives everyone at that company's domain access.
        {!requireApproval && " These approvals only take effect while approval is required."}
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
  const [ai, setAi] = useState(null);
  useEffect(() => {
    api.get("/api/admin/ai").then(setAi).catch(() => setAi(null));
  }, []);
  const choices = modelChoices(ai);
  const [error, setError] = useState("");
  // Per-bot "Read PDFs" choice for the next re-index; defaults to the bot's current setting.
  const [pdfs, setPdfs] = useState({});
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
              <th>Read PDFs</th>
              <th>Answer model</th>
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
                <td>
                  <label className="check nowrap" title="Takes effect when you re-index this bot">
                    <input
                      type="checkbox"
                      checked={pdfs[s.id] ?? s.include_pdfs}
                      onChange={(e) => setPdfs((p) => ({ ...p, [s.id]: e.target.checked }))}
                    />
                    {(pdfs[s.id] ?? s.include_pdfs) ? "On" : "Off"}
                  </label>
                </td>
                <td>
                  <select
                    aria-label={`Answer model for ${s.name} Chatbot`}
                    value={s.answer_model || ""}
                    onChange={(e) => act(() => api.patch(`/api/admin/sites/${s.id}/models`, { answer_model: e.target.value }))}
                  >
                    <option value="">Default</option>
                    {choices.map(([r, l]) => (
                      <option key={r} value={r}>
                        {l}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="muted small">{timeAgo(s.indexed_at) || "—"}</td>
                <td className="actions">
                  <button className="btn ghost small" disabled={s.running} onClick={() => act(() => api.post(`/api/admin/sites/${s.id}/reindex`, { include_pdfs: pdfs[s.id] ?? s.include_pdfs }))}>
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

const EMBED_STATUS = { pending: ["Waiting", "queued"], approved: ["Approved", "ready"], rejected: ["Not approved", "failed"] };

function Embeds() {
  const [embeds, setEmbeds] = useState([]);
  const [caps, setCaps] = useState({});
  // Rejection reasons being typed, per embed (undefined: not rejecting).
  const [notes, setNotes] = useState({});
  const [confirmAsk, confirmDialog] = useConfirm();
  const [error, setError] = useState("");
  const load = useCallback(() => api.get("/api/admin/embeds").then(setEmbeds).catch((e) => setError(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);

  const review = async (e, body) => {
    setError("");
    try {
      const updated = await api.patch(`/api/admin/embeds/${e.id}`, body);
      setEmbeds((list) => list.map((x) => (x.id === updated.id ? updated : x)));
      setCaps((c) => ({ ...c, [e.id]: undefined }));
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section>
      <p className="muted">
        Requests to put a chatbot on its own website. Approved chatbots answer that website's visitors, charged to the owner's credits and
        stopped for the day at the daily limit.
      </p>
      {error && <p className="error">{error}</p>}
      {!embeds.length ? (
        <p className="muted small">No requests yet.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Chatbot</th>
                <th>Owner</th>
                <th>Status</th>
                <th>Only own domain</th>
                <th>Today / daily limit</th>
                <th>Total</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {embeds.map((e) => {
                const [label, cls] = EMBED_STATUS[e.status] || EMBED_STATUS.pending;
                const cap = caps[e.id];
                return (
                  <tr key={e.id}>
                    <td>
                      <div className="cell-bot">
                        <BotIcon site={e.site} size={24} />
                        <div>
                          <div className="strong">{e.site.name} Chatbot</div>
                          <div className="muted small">{e.site.domain}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <div>{e.owner.name}</div>
                      <div className="muted small">{e.owner.email}</div>
                    </td>
                    <td>
                      <span className={`status ${cls}`}>{label}</span>
                      {e.status === "approved" && !e.enabled && <div className="muted small">Turned off by owner</div>}
                    </td>
                    <td>
                      <button
                        role="switch"
                        aria-checked={e.restrict_to_domain}
                        aria-label={`Only allow ${e.site.name} Chatbot on ${e.site.domain}`}
                        className={`switch ${e.restrict_to_domain ? "on" : ""}`}
                        onClick={async () => {
                          if (e.restrict_to_domain) {
                            const ok = await confirmAsk({
                              title: "Let any website use this chatbot?",
                              message: "Any website can use this bot, and every question is charged to the owner's credits. Limits and the daily cap still apply.",
                              confirmLabel: "Allow any website",
                              danger: true,
                            });
                            if (!ok) return;
                          }
                          review(e, { restrict_to_domain: !e.restrict_to_domain });
                        }}
                      >
                        <span />
                      </button>
                      {!e.restrict_to_domain && <div className="warn-text small">Any website</div>}
                    </td>
                    <td>
                      <form
                        className="inline-form"
                        onSubmit={(ev) => {
                          ev.preventDefault();
                          review(e, { daily_cap_usd: Number(cap) });
                        }}
                      >
                        <span className="nowrap">{money(e.spent_today_usd)} /</span>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          aria-label="Daily limit in USD"
                          value={cap ?? e.daily_cap_usd}
                          onChange={(ev) => setCaps((c) => ({ ...c, [e.id]: ev.target.value }))}
                        />
                        {cap !== undefined && <button className="btn small primary">Save</button>}
                      </form>
                    </td>
                    <td>{money(e.spent_total_usd)}</td>
                    <td className="actions">
                      {e.status !== "approved" && (
                        <button className="btn small primary" onClick={() => review(e, { status: "approved" })}>
                          Approve
                        </button>
                      )}
                      {e.status !== "rejected" && notes[e.id] === undefined && (
                        <button className="btn ghost small danger" onClick={() => setNotes((n) => ({ ...n, [e.id]: "" }))}>
                          {e.status === "approved" ? "Revoke" : "Reject"}
                        </button>
                      )}
                      {notes[e.id] !== undefined && (
                        <form
                          className="reject-form"
                          onSubmit={async (ev) => {
                            ev.preventDefault();
                            await review(e, { status: "rejected", note: notes[e.id] });
                            setNotes((n) => ({ ...n, [e.id]: undefined }));
                          }}
                        >
                          <input
                            autoFocus
                            maxLength={500}
                            placeholder="Reason (optional, shown to the owner)"
                            aria-label="Reason for not approving"
                            value={notes[e.id]}
                            onChange={(ev) => setNotes((n) => ({ ...n, [e.id]: ev.target.value }))}
                          />
                          <button className="btn small danger-solid">{e.status === "approved" ? "Revoke" : "Reject"}</button>
                          <button type="button" className="btn ghost small" onClick={() => setNotes((n) => ({ ...n, [e.id]: undefined }))}>
                            Cancel
                          </button>
                        </form>
                      )}
                      {e.status === "rejected" && e.review_note && <div className="muted small">Reason: {e.review_note}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {confirmDialog}
    </section>
  );
}

const BLANK_PLAN = { name: "", price_usd_month: 0, credit_usd_month: 0, max_bots: 0, max_embeds: 0, active: true };

// Billing scaffolding: plans are only records for now. Nothing is charged and no limit is enforced.
function Plans() {
  const [plans, setPlans] = useState([]);
  const [draft, setDraft] = useState(BLANK_PLAN);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState("");
  const [confirmAsk, confirmDialog] = useConfirm();
  const load = useCallback(() => api.get("/api/admin/plans").then(setPlans).catch((e) => setError(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);

  const save = async (e) => {
    e.preventDefault();
    setError("");
    const body = { ...draft, name: draft.name.trim() };
    for (const k of ["price_usd_month", "credit_usd_month", "max_bots", "max_embeds"]) body[k] = Number(body[k]) || 0;
    try {
      if (editing) await api.put(`/api/admin/plans/${editing}`, body);
      else await api.post("/api/admin/plans", body);
      setDraft(BLANK_PLAN);
      setEditing(null);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const remove = async (p) => {
    const ok = await confirmAsk({
      title: `Delete the ${p.name} plan?`,
      message: p.users ? `${p.users} user(s) on it will have no plan.` : "No one is on it.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.del(`/api/admin/plans/${p.id}`);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const field = (k, label, props = {}) => (
    <label>
      {label}
      <input value={draft[k]} onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))} {...props} />
    </label>
  );

  return (
    <section>
      <p className="muted">Plans are records only for now: nothing is charged and no limits are enforced.</p>
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Plan</th>
              <th>Price / month</th>
              <th>AI credit / month</th>
              <th>Bots</th>
              <th>Embeds</th>
              <th>Users</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {plans.map((p) => (
              <tr key={p.id}>
                <td className="strong">
                  {p.name} {!p.active && <span className="pill">Hidden</span>}
                </td>
                <td>{money(p.price_usd_month)}</td>
                <td>{money(p.credit_usd_month)}</td>
                <td>{p.max_bots || "Unlimited"}</td>
                <td>{p.max_embeds || "Unlimited"}</td>
                <td>{p.users}</td>
                <td className="actions">
                  <button
                    className="btn ghost small"
                    onClick={() => {
                      setEditing(p.id);
                      setDraft({ name: p.name, price_usd_month: p.price_usd_month, credit_usd_month: p.credit_usd_month, max_bots: p.max_bots, max_embeds: p.max_embeds, active: p.active });
                    }}
                  >
                    Edit
                  </button>
                  <button className="btn ghost small danger" onClick={() => remove(p)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {!plans.length && (
              <tr>
                <td colSpan={7} className="muted">
                  No plans yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <form className="plan-form" onSubmit={save}>
        <h3>{editing ? "Edit plan" : "Add a plan"}</h3>
        {field("name", "Name", { required: true, maxLength: 100 })}
        {field("price_usd_month", "Price per month (USD)", { type: "number", min: 0, step: "0.01" })}
        {field("credit_usd_month", "AI credit per month (USD)", { type: "number", min: 0, step: "0.01" })}
        {field("max_bots", "Bots (0 = unlimited)", { type: "number", min: 0, step: 1 })}
        {field("max_embeds", "Embeds (0 = unlimited)", { type: "number", min: 0, step: 1 })}
        <label className="check">
          <input type="checkbox" checked={draft.active} onChange={(e) => setDraft((d) => ({ ...d, active: e.target.checked }))} /> Offered
        </label>
        <div className="actions">
          <button className="btn primary">{editing ? "Save" : "Add plan"}</button>
          {editing && (
            <button
              type="button"
              className="btn ghost"
              onClick={() => {
                setEditing(null);
                setDraft(BLANK_PLAN);
              }}
            >
              Cancel
            </button>
          )}
        </div>
      </form>
      {confirmDialog}
    </section>
  );
}

const TABS = ["Users", "Access", "Bots", "Embeds", "AI providers", "Budget"];

export default function Admin({ me, sites, refreshSites, onUsageChange, billing = false }) {
  const [tab, setTab] = useState("Users");
  const tabs = billing ? [...TABS, "Plans"] : TABS;
  return (
    <div className="page admin">
      <h1>Admin console</h1>
      <Tabs label="Admin sections" value={tab} onChange={setTab} tabs={tabs.map((t) => [t, t])} />
      {tab === "Users" && <Users me={me} onUsageChange={onUsageChange} billing={billing} />}
      {tab === "Access" && <Access />}
      {tab === "Bots" && <Bots sites={sites} refreshSites={refreshSites} />}
      {tab === "Embeds" && <Embeds />}
      {tab === "AI providers" && <AIProviders />}
      {tab === "Budget" && <Budget onUsageChange={onUsageChange} />}
      {tab === "Plans" && billing && <Plans />}
    </div>
  );
}
