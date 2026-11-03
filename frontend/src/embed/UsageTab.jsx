// Website chatbot > Usage & settings: spend, insights, keys, verification, team and reports.
import { useCallback, useEffect, useState } from "react";
import { useConfirm } from "../Confirm.jsx";
import { api, money, plural, timeAgo } from "../api.js";
import { CopyBox } from "./shared.jsx";

/** Chats per day as simple bars, newest on the right. */
function DayChart({ days }) {
  const max = Math.max(1, ...days.map((d) => d.chats));
  const total = days.reduce((s, d) => s + d.chats, 0);
  return (
    <div className="day-chart">
      <div className="day-bars" role="img" aria-label={`${total} chats in the last ${days.length} days`}>
        {days.map((d) => (
          <div key={d.date} className="day-bar" title={`${d.date}: ${plural(d.chats, "chat")}`}>
            <span style={{ height: `${(d.chats / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="day-axis muted small">
        <span>{days[0]?.date.slice(5)}</span>
        <span>
          {plural(total, "chat")} · peak {max === 1 && !total ? 0 : max} a day
        </span>
        <span>today</span>
      </div>
    </div>
  );
}

function Insights({ embed, onTeach }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    api.get(`/api/embeds/${embed.id}/insights`).then(setData).catch(() => setData({ days: [], top_questions: [], unanswered: [] }));
  }, [embed.id]);
  if (!data) return <p className="muted small">Loading insights…</p>;
  return (
    <>
      <section className="way insights-chart">
        <strong>Chats per day (last 30 days)</strong>
        <DayChart days={data.days} />
        <p className="muted small">Test chats aren't counted.</p>
      </section>
      <section className="way">
        <strong>Most asked</strong>
        {data.top_questions.length ? (
          <ol className="q-list">
            {data.top_questions.map((q) => (
              <li key={q.question}>
                <span>{q.question}</span>
                <span className="muted small">{q.count}×</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted small">No questions yet.</p>
        )}
      </section>
      <section className="way">
        <strong>Couldn't answer</strong>
        <p className="muted small">Questions your website doesn't cover yet. Teach the bot the answer, or add the information to your website.</p>
        {data.unanswered.length ? (
          <ol className="q-list">
            {data.unanswered.map((q) => (
              <li key={q.question}>
                <span>{q.question}</span>
                <span className="muted small">
                  {q.count}× · {timeAgo(q.last_at)}
                </span>{" "}
                {onTeach && (
                  <button className="link-btn small" onClick={() => onTeach(q.question)}>
                    Teach the bot
                  </button>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted small">Nothing yet: every question so far was answered from the website.</p>
        )}
      </section>
    </>
  );
}

// ---------- Usage & settings ----------

/** Domain verification: prove you control the website and a waiting request goes live without an admin. */
function Verification({ embed, onChanged }) {
  const v = embed.verification || {};
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState("");
  const check = async (method) => {
    setBusy(method);
    setResult("");
    try {
      onChanged(await api.post(`/api/embeds/${embed.id}/verify`, { method }));
      setResult("ok");
    } catch (e) {
      setResult(e.message);
    } finally {
      setBusy("");
    }
  };
  return (
    <section className="way verification">
      <strong>Verify {embed.site.domain}</strong>
      {v.verified_at ? (
        <p className="ok-text small">
          Verified {timeAgo(v.verified_at)} by {v.via === "dns" ? "DNS record" : "meta tag"}.
        </p>
      ) : (
        <p className="muted small">
          Prove you run this website{embed.status === "pending" ? " and it goes live straight away, without waiting for an admin" : ""}. Use either way:
        </p>
      )}
      <div className="verify-way">
        <span className="small">
          <strong>Meta tag</strong> on your home page, inside &lt;head&gt;:
        </span>
        <CopyBox text={v.meta_tag || ""} />
        <button className="btn small" disabled={!!busy} onClick={() => check("meta")}>
          {busy === "meta" ? "Checking…" : "Check meta tag"}
        </button>
      </div>
      <div className="verify-way">
        <span className="small">
          <strong>DNS TXT record</strong> on <code>{v.dns_name}</code>:
        </span>
        <CopyBox text={v.dns_value || ""} />
        <button className="btn small" disabled={!!busy} onClick={() => check("dns")}>
          {busy === "dns" ? "Checking…" : "Check DNS record"}
        </button>
      </div>
      {result === "ok" && <p className="ok-text small">Verified ✓</p>}
      {result && result !== "ok" && <p className="error">{result}</p>}
    </section>
  );
}

/** Keep the bot up to date (scheduled re-index of its website) and the weekly report email. */
function UpdatesAndReports({ embed, onChanged }) {
  const [error, setError] = useState("");
  const canEdit = embed.my_role !== "viewer";
  const refresh = async () => onChanged((await api.get("/api/embeds")).find((x) => x.id === embed.id) || embed);
  return (
    <section className="way">
      <strong>Updates and reports</strong>
      <div className="key-row">
        <div>
          <div className="small">Re-read {embed.site.domain} automatically</div>
          <div className="muted small">
            Only pages that changed are learned again, so updates are quick and cheap.
            {embed.site.indexed_at ? ` Last updated ${timeAgo(embed.site.indexed_at)}.` : ""}
          </div>
        </div>
        <select
          aria-label="Re-read the website"
          value={embed.site.reindex_schedule || "off"}
          disabled={!canEdit}
          onChange={async (e) => {
            setError("");
            try {
              await api.patch(`/api/sites/${embed.site_id}/schedule`, { reindex_schedule: e.target.value });
              await refresh();
            } catch (err) {
              setError(err.message);
            }
          }}
        >
          <option value="off">Off</option>
          <option value="daily">Every day</option>
          <option value="weekly">Every week</option>
        </select>
      </div>
      <div className="key-row">
        <div>
          <div className="small">Weekly email report</div>
          <div className="muted small">Conversations, most asked and unanswered questions, leads and spend, emailed to the owner every week there were chats.</div>
        </div>
        <button
          role="switch"
          aria-checked={embed.weekly_report}
          aria-label="Weekly email report"
          className={`switch ${embed.weekly_report ? "on" : ""}`}
          disabled={embed.my_role !== "owner"}
          onClick={async () => {
            try {
              onChanged(await api.patch(`/api/embeds/${embed.id}`, { weekly_report: !embed.weekly_report }));
            } catch (err) {
              setError(err.message);
            }
          }}
        >
          <span />
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

/** The people who can see or change this website chatbot. */
function Team({ embed, me, onLeft }) {
  const [team, setTeam] = useState(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [error, setError] = useState("");
  const [confirmAsk, confirmDialog] = useConfirm();
  const isOwner = embed.my_role === "owner";
  const load = useCallback(() => api.get(`/api/embeds/${embed.id}/team`).then(setTeam).catch((e) => setError(e.message)), [embed.id]);
  useEffect(() => {
    load();
  }, [load]);
  const act = async (fn) => {
    setError("");
    try {
      await fn();
      load();
    } catch (e) {
      setError(e.message);
    }
  };
  if (!team) return null;
  return (
    <section className="way team">
      <strong>Team</strong>
      <p className="muted small">Viewers see conversations, leads and insights. Editors can also change the design, teach the bot and handle leads. Only the owner manages keys, the team and removal.</p>
      <ul className="team-list">
        <li>
          <span>
            {team.owner.name} <span className="muted small">{team.owner.email}</span>
          </span>
          <span className="pill">Owner</span>
        </li>
        {team.members.map((m) => (
          <li key={m.id}>
            <span>
              {m.name || m.email} {m.name && <span className="muted small">{m.email}</span>}
              {!m.joined && <span className="muted small"> · hasn't signed in yet</span>}
            </span>
            {isOwner ? (
              <span className="row-actions">
                <select aria-label={`Role for ${m.email}`} value={m.role} onChange={(e) => act(() => api.patch(`/api/embeds/${embed.id}/team/${m.id}`, { role: e.target.value }))}>
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                </select>
                <button className="link-btn small danger-link" onClick={() => act(() => api.del(`/api/embeds/${embed.id}/team/${m.id}`))}>
                  Remove
                </button>
              </span>
            ) : m.email === me.email.toLowerCase() ? (
              <span className="row-actions">
                <span className="pill">{m.role === "editor" ? "Editor (you)" : "Viewer (you)"}</span>
                <button
                  className="link-btn small danger-link"
                  onClick={async () => {
                    const ok = await confirmAsk({ title: "Leave this chatbot's team?", message: "You'll lose access until the owner adds you again.", confirmLabel: "Leave", danger: true });
                    if (ok) {
                      await api.del(`/api/embeds/${embed.id}/team/${m.id}`);
                      onLeft();
                    }
                  }}
                >
                  Leave
                </button>
              </span>
            ) : (
              <span className="pill">{m.role === "editor" ? "Editor" : "Viewer"}</span>
            )}
          </li>
        ))}
      </ul>
      {isOwner && (
        <form
          className="inline-form team-invite"
          onSubmit={(e) => {
            e.preventDefault();
            act(async () => {
              await api.post(`/api/embeds/${embed.id}/team`, { email, role });
              setEmail("");
            });
          }}
        >
          <input type="email" required placeholder="colleague@company.com" aria-label="Teammate's email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="viewer">Viewer</option>
            <option value="editor">Editor</option>
          </select>
          <button className="btn small">Invite</button>
        </form>
      )}
      {isOwner && <p className="muted small">They get an email (when email is set up) and see it once they sign in with that address. If sign-ups need approval, approve their email in Admin console &gt; Access too.</p>}
      {error && <p className="error">{error}</p>}
      {confirmDialog}
    </section>
  );
}

export function UsageTab({ embed, me, onChanged, onRemoved, onInstall, onTeach }) {
  const [confirmAsk, confirmDialog] = useConfirm();
  const [cap, setCap] = useState(String(embed.daily_cap_usd));
  const [error, setError] = useState("");
  const pct = embed.daily_cap_usd > 0 ? Math.min(100, (embed.spent_today_usd / embed.daily_cap_usd) * 100) : 100;

  const act = async (fn) => {
    setError("");
    try {
      onChanged(await fn());
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="usage-tab">
      {error && <p className="error">{error}</p>}
      <section className="way">
        <strong>Today</strong>
        <div className="usage-line">
          <span>
            {money(embed.spent_today_usd)} of {money(embed.daily_cap_usd)} daily limit
          </span>
          <span className="muted small">{plural(embed.chats_today, "conversation")} today</span>
        </div>
        <div className="bar">
          <div className={`bar-fill ${pct >= 90 ? "danger" : pct >= 70 ? "warn" : ""}`} style={{ width: `${pct}%` }} />
        </div>
        <p className="muted small">
          Visitors' questions are charged to the owner's credits. When the daily limit is reached, the chat pauses politely until midnight UTC. All time:{" "}
          {money(embed.spent_total_usd)} across {plural(embed.conversations, "conversation")} · rated 👍 {embed.feedback.up} · 👎 {embed.feedback.down}.
        </p>
        {me.role === "admin" ? (
          <form
            className="inline-form"
            onSubmit={(e) => {
              e.preventDefault();
              act(() => api.patch(`/api/admin/embeds/${embed.id}`, { daily_cap_usd: Number(cap) }));
            }}
          >
            <label className="muted small" htmlFor="cap">
              Daily limit (USD)
            </label>
            <input id="cap" type="number" min="0" step="0.01" value={cap} onChange={(e) => setCap(e.target.value)} />
            {Number(cap) !== embed.daily_cap_usd && <button className="btn small primary">Save</button>}
          </form>
        ) : (
          <p className="muted small">Only an admin can change the daily limit.</p>
        )}
      </section>

      {embed.my_role === "owner" && <Verification embed={embed} onChanged={onChanged} />}
      <UpdatesAndReports embed={embed} onChanged={onChanged} />
      <Team embed={embed} me={me} onLeft={() => onRemoved(embed.id)} />

      {embed.my_role === "owner" && (
      <section className="way">
        <strong>Keys</strong>
        <div className="key-row">
          <div>
            <div className="small">
              Public code <code>{embed.key}</code>
            </div>
            <div className="muted small">Used by the website snippet and sitebot-client.js.</div>
          </div>
          <button
            className="btn ghost small"
            onClick={async () => {
              const ok = await confirmAsk({
                title: "Make a new public code?",
                message: "The code on your website stops working straight away. You'll need to paste the new snippet there.",
                confirmLabel: "Make new code",
              });
              if (ok) act(() => api.post(`/api/embeds/${embed.id}/rotate-key`));
            }}
          >
            Regenerate
          </button>
        </div>
        <div className="key-row">
          <div>
            <div className="small">
              Server key {embed.server_key ? <code>sk_…{embed.server_key.hint}</code> : <span className="muted">not created</span>}
            </div>
            <div className="muted small">
              For the server API.
              {embed.server_key && (embed.server_key.last_used_at ? ` Last used ${timeAgo(embed.server_key.last_used_at)}.` : " Not used yet.")}
            </div>
          </div>
          <button className="btn ghost small" onClick={onInstall}>
            Manage
          </button>
        </div>
      </section>
      )}

      <Insights embed={embed} onTeach={onTeach} />

      {embed.my_role === "owner" && (
      <section className="way danger-zone">
        <strong>Danger zone</strong>
        <div className="key-row">
          <div className="muted small">Removes the chat from your website and deletes its visitor conversations. You can't undo this.</div>
          <button
            className="btn small danger-solid"
            onClick={async () => {
              const ok = await confirmAsk({
                title: `Remove ${embed.site.name} Chatbot from your website?`,
                message: "The chat disappears from your website and its visitor conversations are deleted. You can't undo this.",
                confirmLabel: "Remove",
                danger: true,
              });
              if (!ok) return;
              try {
                await api.del(`/api/embeds/${embed.id}`);
                onRemoved(embed.id);
              } catch (e) {
                setError(e.message);
              }
            }}
          >
            Remove embed
          </button>
        </div>
      </section>
      )}
      {confirmDialog}
    </div>
  );
}
