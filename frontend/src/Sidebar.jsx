import { useState } from "react";
import ThemeToggle from "./ThemeToggle.jsx";
import { HomeIcon, LogOutIcon, LogoMark, PlusIcon, SearchIcon, SettingsIcon } from "./Icons.jsx";
import { money } from "./api.js";

export function BotIcon({ site, size = 28 }) {
  const [broken, setBroken] = useState(false);
  if (site.favicon && !broken) {
    return <img className="bot-icon" src={site.favicon} alt="" width={size} height={size} onError={() => setBroken(true)} />;
  }
  return (
    <span className="bot-icon letter" style={{ width: size, height: size }}>
      {(site.name || site.domain || "?").charAt(0).toUpperCase()}
    </span>
  );
}

function UsageBar({ usage }) {
  if (!usage) return null;
  const pct = usage.user_limit > 0 ? Math.min(100, (usage.user_spent / usage.user_limit) * 100) : 100;
  const gpct = usage.global_budget > 0 ? Math.min(100, (usage.global_spent / usage.global_budget) * 100) : 100;
  const level = pct >= 90 ? "danger" : pct >= 70 ? "warn" : "";
  return (
    <div className="usage" tabIndex={0} aria-label="Credits used">
      <div className="usage-label">
        <span>Credits</span>
        <span>{Math.round(pct)}%</span>
      </div>
      <div className="bar">
        <div className={`bar-fill ${level}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="usage-tip" role="tooltip">
        <div className="tip-row">
          <span>You</span>
          <strong>
            {money(usage.user_spent)} / {money(usage.user_limit)}
          </strong>
        </div>
        <div className="bar small">
          <div className={`bar-fill ${level}`} style={{ width: `${pct}%` }} />
        </div>
        <div className="tip-row">
          <span>All users</span>
          <strong>
            {money(usage.global_spent)} / {money(usage.global_budget)}
          </strong>
        </div>
        <div className="bar small">
          <div className={`bar-fill ${gpct >= 90 ? "danger" : gpct >= 70 ? "warn" : ""}`} style={{ width: `${gpct}%` }} />
        </div>
      </div>
    </div>
  );
}

const STATUS_LABEL = { queued: "Queued", crawling: "Reading", embedding: "Learning", failed: "Failed" };

export default function Sidebar({ me, sites, chats, usage, view, go, logout }) {
  const [query, setQuery] = useState("");
  const chatsBySite = {};
  for (const c of chats) (chatsBySite[c.site_id] ||= []).push(c);

  // The sidebar shows your bots (ones you added or chatted with); the rest of the library is found by searching.
  const q = query.trim().toLowerCase();
  const mine = sites.filter((s) => s.created_by === me.id || chatsBySite[s.id]);
  const shown = q ? sites.filter((s) => s.ready && `${s.name} ${s.domain}`.toLowerCase().includes(q)) : mine;

  // Most recently used first.
  const ordered = [...shown].sort((a, b) => {
    const ca = chatsBySite[a.id]?.[0]?.updated_at || "";
    const cb = chatsBySite[b.id]?.[0]?.updated_at || "";
    return cb.localeCompare(ca) || a.name.localeCompare(b.name);
  });

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <div className="brand" role="button" tabIndex={0} onClick={() => go({ type: "home" })} title="Home">
          <LogoMark size={26} /> <span>SiteBot</span>
        </div>
        <ThemeToggle />
      </div>
      <nav className="side-nav">
        <button className={`side-link ${view.type === "home" ? "active" : ""}`} onClick={() => go({ type: "home" })}>
          <HomeIcon /> Home
        </button>
        <button className={`side-link ${view.type === "add" ? "active" : ""}`} onClick={() => go({ type: "add" })}>
          <PlusIcon size={17} /> New chatbot
        </button>
      </nav>

      <div className="bot-search">
        <SearchIcon />
        <input type="search" placeholder="Search chatbots" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search chatbots" />
      </div>

      <div className="bot-list">
        <div className="list-label">{q ? "Search results" : "Your chatbots"}</div>
        {q && ordered.length === 0 && <p className="muted small pad">No chatbots match "{query.trim()}". Create one from its website link.</p>}
        {!q && ordered.length === 0 && <p className="muted small pad">You haven't used any chatbots yet. Create one, or search the library.</p>}
        {ordered.map((s) => {
          const siteChats = chatsBySite[s.id] || [];
          const busy = !s.ready && s.status !== "failed";
          return (
            <div key={s.id} className="bot-group">
              <div
                className={`bot-row ${view.siteId === s.id && view.type !== "admin" ? "active" : ""}`}
                onClick={() => {
                  setQuery("");
                  if (!s.ready) return go({ type: "progress", siteId: s.id });
                  go({ type: "chat", siteId: s.id, chatId: siteChats[0]?.id ?? null });
                }}
              >
                <BotIcon site={s} size={24} />
                <div className="bot-meta">
                  <div className="bot-name">{s.name} Chatbot</div>
                  <div className="bot-sub">
                    {s.ready ? s.domain : <span className={`status ${s.status}`}>{STATUS_LABEL[s.status] || s.status}</span>}
                    {s.ready && s.running && <span className="status crawling"> · re-indexing</span>}
                  </div>
                </div>
                {busy && <span className="spinner" />}
              </div>
            </div>
          );
        })}
      </div>

      <div className="sidebar-foot">
        <UsageBar usage={usage} />
        {me.role === "admin" && (
          <button className={`side-link ${view.type === "admin" ? "active" : ""}`} onClick={() => go({ type: "admin" })}>
            <SettingsIcon /> Admin
          </button>
        )}
        <div className="me">
          {me.picture ? <img src={me.picture} alt="" className="avatar" referrerPolicy="no-referrer" /> : <span className="avatar letter">{me.name.charAt(0).toUpperCase()}</span>}
          <div className="me-meta">
            <div className="me-name">{me.name}</div>
            <div className="me-role">{me.role}</div>
          </div>
          <button className="icon-btn" onClick={logout} title="Sign out" aria-label="Sign out">
            <LogOutIcon />
          </button>
        </div>
      </div>
    </aside>
  );
}
