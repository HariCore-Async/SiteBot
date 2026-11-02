// Website chatbot > Leads: visitors who left their email when the bot couldn't answer.
import { useEffect, useState } from "react";
import { api, timeAgo } from "../api.js";

// ---------- Leads: visitors who want to hear back ----------

export function LeadsTab({ embed, onChanged }) {
  const [leads, setLeads] = useState(null);
  const [showDone, setShowDone] = useState(false);
  useEffect(() => {
    api.get(`/api/embeds/${embed.id}/leads`).then(setLeads).catch(() => setLeads([]));
  }, [embed.id]);
  if (!leads) return <p className="muted small">Loading…</p>;
  const shown = leads.filter((l) => showDone || l.status === "open");
  const toggle = async (l) => {
    const updated = await api.patch(`/api/embeds/${embed.id}/leads/${l.id}`, { status: l.status === "open" ? "done" : "open" });
    setLeads((list) => list.map((x) => (x.id === l.id ? updated : x)));
    api.get("/api/embeds").then((all) => onChanged(all.find((x) => x.id === embed.id) || embed)).catch(() => {});
  };
  return (
    <div className="leads-tab">
      <p className="muted">
        When the bot can't answer, visitors can leave their email so someone can get back to them. You also get an email for each one (when email is set up).
      </p>
      <label className="check">
        <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> Show handled
      </label>
      {!shown.length ? (
        <p className="muted small">{leads.length ? "Nothing open. Nice." : "No one has left their details yet."}</p>
      ) : (
        <ul className="lead-list">
          {shown.map((l) => (
            <li key={l.id} className={`way ${l.status === "done" ? "done" : ""}`}>
              <div className="lead-head">
                <strong>{l.name || l.email}</strong>
                <a href={`mailto:${l.email}`}>{l.email}</a>
                <span className="muted small">
                  {timeAgo(l.created_at)}
                  {l.origin ? ` · ${l.origin.replace(/^https?:\/\//, "")}` : ""}
                </span>
                {embed.my_role !== "viewer" && <button className="btn small" onClick={() => toggle(l)}>
                  {l.status === "open" ? "Mark handled" : "Reopen"}
                </button>}
              </div>
              {l.question && (
                <p className="small">
                  <span className="muted">Asked: </span>
                  {l.question}
                </p>
              )}
              {l.message && (
                <p className="small">
                  <span className="muted">Message: </span>
                  {l.message}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
