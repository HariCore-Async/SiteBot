import { useCallback, useEffect, useRef, useState } from "react";
import { useConfirm } from "./Confirm.jsx";
import { api, money, plural } from "./api.js";
import { BotIcon } from "./Sidebar.jsx";
import { Pager, useFitPageSize } from "./BotsPage.jsx";
import { Tabs } from "./Tabs.jsx";
import { CodeIcon, PlusIcon, SearchIcon } from "./Icons.jsx";
import { ConversationsTab } from "./embed/ConversationsTab.jsx";
import { DesignTab } from "./embed/DesignTab.jsx";
import { InstallTab } from "./embed/InstallTab.jsx";
import { KnowledgeTab } from "./embed/KnowledgeTab.jsx";
import { TestsTab } from "./embed/TestsTab.jsx";
import { LeadsTab } from "./embed/LeadsTab.jsx";
import { UsageTab } from "./embed/UsageTab.jsx";
import { InstallCheck } from "./embed/shared.jsx";

// "Add a chatbot to your website": a list of your website chatbots, and a page per chatbot with tabs
// (Design, Install, Conversations, Usage & settings). The open chatbot and tab live in the URL (see App.jsx).

/** The one status shown everywhere: Pending, Not approved, Live or Off. */
export function pillOf(e) {
  if (e.status === "pending") return { label: "Pending", cls: "pending" };
  if (e.status === "rejected") return { label: "Not approved", cls: "failed" };
  return e.enabled ? { label: "Live", cls: "ready" } : { label: "Off", cls: "off" };
}

const BOT_TABS = [
  ["design", "Design"],
  ["install", "Install"],
  ["knowledge", "Knowledge"],
  ["tests", "Test questions"],
  ["conversations", "Conversations"],
  ["leads", "Leads"],
  ["usage", "Usage & settings"],
];

function EmbedBot({ embed, me, tab, sub, onRoute, onChanged, onRemoved }) {
  const [confirmAsk, confirmDialog] = useConfirm();
  const [error, setError] = useState("");
  const pill = pillOf(embed);
  const current = BOT_TABS.some(([id]) => id === tab) ? tab : "design";
  // Unsaved Design changes: ask before switching tabs or leaving, and before closing or reloading the page.
  const dirtyRef = useRef(false);
  const setDirty = useCallback((v) => {
    dirtyRef.current = v;
  }, []);
  useEffect(() => {
    const onUnload = (e) => {
      if (dirtyRef.current) e.preventDefault();
    };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, []);
  const go = async (route) => {
    if (dirtyRef.current) {
      const ok = await confirmAsk({
        title: "Discard changes?",
        message: "You have design changes that aren't saved yet.",
        confirmLabel: "Discard changes",
        danger: true,
      });
      if (!ok) return;
      dirtyRef.current = false;
    }
    onRoute(route);
  };
  // "Teach the bot" from an unanswered question: open Knowledge with the question filled in.
  const [teach, setTeach] = useState("");
  const onTeach = (question) => {
    setTeach(question);
    go({ embedId: embed.id, tab: "knowledge" });
  };
  const clearTeach = useCallback(() => setTeach(""), []);
  const act = async (fn) => {
    setError("");
    try {
      onChanged(await fn());
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="page wide embed-page">
      <button className="link-btn back-link" onClick={() => go({})}>
        ← Your website chatbots
      </button>
      <header className="bot-head">
        <BotIcon site={embed.site} size={40} />
        <div className="bot-head-meta">
          <h1>{embed.site.name} Chatbot</h1>
          <span className="muted small">
            {embed.restrict_to_domain ? `Works on ${embed.site.domain} and its subdomains` : "Works on any website"}
          </span>
        </div>
        <span className={`status ${pill.cls}`}>{pill.label}</span>
        <div className="head-switches">
          {embed.status === "approved" && (
            <label className="switch-label">
              <span className="small">{embed.enabled ? "On" : "Off"}</span>
              <button
                role="switch"
                aria-checked={embed.enabled}
                aria-label="Show this chatbot on the website"
                disabled={embed.my_role === "viewer"}
                className={`switch ${embed.enabled ? "on" : ""}`}
                onClick={() => act(() => api.patch(`/api/embeds/${embed.id}`, { enabled: !embed.enabled }))}
              >
                <span />
              </button>
            </label>
          )}
          <label className="switch-label" title={me.role !== "admin" ? "Only an admin can change this" : ""}>
            <span className="small">Only on {embed.site.domain}</span>
            <button
              role="switch"
              aria-checked={embed.restrict_to_domain}
              aria-label={`Only allow on ${embed.site.domain}`}
              className={`switch ${embed.restrict_to_domain ? "on" : ""}`}
              disabled={me.role !== "admin"}
              onClick={async () => {
                if (embed.restrict_to_domain) {
                  const ok = await confirmAsk({
                    title: "Let any website use this chatbot?",
                    message: "Any website can use this bot, and every question is charged to the owner's credits. Limits and the daily cap still apply.",
                    confirmLabel: "Allow any website",
                    danger: true,
                  });
                  if (!ok) return;
                }
                act(() => api.patch(`/api/embeds/${embed.id}`, { restrict_to_domain: !embed.restrict_to_domain }));
              }}
            >
              <span />
            </button>
          </label>
        </div>
      </header>

      {embed.status === "pending" && (
        <div className="banner pending" role="status">
          <strong>Waiting for admin approval.</strong> You can design and install it now; it starts answering visitors once an admin approves it.{" "}
          {embed.my_role === "owner" && !embed.reviewed_at && (
            <button className="link-btn" onClick={() => go({ embedId: embed.id, tab: "usage" })}>
              Or verify your domain to go live now
            </button>
          )}
        </div>
      )}
      {embed.status === "rejected" && (
        <div className="banner rejected" role="status">
          <strong>An admin didn't approve this.</strong>{embed.review_note ? ` Reason: ${embed.review_note}` : ""}{" "}
          <button className="link-btn" onClick={() => act(() => api.post("/api/embeds", { site_id: embed.site_id }))}>
            Ask again
          </button>
        </div>
      )}
      {!embed.restrict_to_domain && (
        <p className="warn-note">Any website can use this bot, and every question is charged to the owner's credits.</p>
      )}
      {me.role !== "admin" && <p className="muted small lock-note">Only an admin can change which websites may use this chatbot.</p>}
      {error && <p className="error">{error}</p>}

      <Tabs tabs={BOT_TABS.map(([id, label]) => (id === "leads" && embed.leads_open ? [id, label, String(embed.leads_open)] : [id, label]))} value={current} onChange={(t) => t !== current && go({ embedId: embed.id, tab: t })} className="bot-tabs" label="Chatbot settings" />
      {current === "design" && <DesignTab embed={embed} onChanged={onChanged} onDirty={setDirty} />}
      {current === "install" && (
        <InstallTab embed={embed} sub={sub} onSub={(s) => onRoute({ embedId: embed.id, tab: "install", sub: s })} onChanged={onChanged} />
      )}
      {current === "knowledge" && <KnowledgeTab embed={embed} prefill={teach} onPrefillUsed={clearTeach} />}
      {current === "tests" && <TestsTab embed={embed} />}
      {current === "conversations" && <ConversationsTab embed={embed} onTeach={onTeach} />}
      {current === "leads" && <LeadsTab embed={embed} onChanged={onChanged} />}
      {current === "usage" && (
        <UsageTab
          key={embed.daily_cap_usd}
          embed={embed}
          me={me}
          onChanged={onChanged}
          onRemoved={onRemoved}
          onInstall={() => onRoute({ embedId: embed.id, tab: "install", sub: "server" })}
          onTeach={onTeach}
        />
      )}
      {confirmDialog}
    </div>
  );
}

// ---------- The list ----------

function AddToWebsite({ me, choices, onCreated, onCancel }) {
  const [siteId, setSiteId] = useState(choices[0]?.id || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const create = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onCreated(await api.post("/api/embeds", { site_id: Number(siteId) }));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <form className="add-embed" onSubmit={create}>
      <strong>Which chatbot?</strong>
      {choices.length ? (
        <>
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)} aria-label="Chatbot">
            {choices.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} Chatbot ({s.domain})
              </option>
            ))}
          </select>
          <p className="muted small">
            {me.role === "admin" ? "As an admin, yours is approved straight away." : "An admin approves it before it answers visitors; you can set it up meanwhile."}
          </p>
        </>
      ) : (
        <p className="muted small">
          All your chatbots are already on a website, or you haven't created one yet. You can add chatbots you created; make one with + New chatbot.
        </p>
      )}
      {error && <p className="error">{error}</p>}
      <div className="embed-actions">
        <button className="btn primary" disabled={!siteId || busy}>
          {me.role === "admin" ? "Add to website" : "Request"}
        </button>
        <button type="button" className="btn ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function EmbedList({ me, embeds, choices, onOpen, onCreated }) {
  const [adding, setAdding] = useState(false);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const gridRef = useRef(null);
  const q = query.trim().toLowerCase();
  const shown = embeds.filter(
    (e) => (status === "all" || pillOf(e).label.toLowerCase() === status) && (!q || `${e.site.name} ${e.site.domain}`.toLowerCase().includes(q))
  );
  const pageSize = useFitPageSize(gridRef, 96, [shown.length > 0, adding, status]);
  const pages = Math.max(1, Math.ceil(shown.length / pageSize));
  const current = Math.min(page, pages);
  const visible = shown.slice((current - 1) * pageSize, current * pageSize);
  useEffect(() => setPage(1), [q, status]);
  const counts = { all: embeds.length };
  for (const e of embeds) counts[pillOf(e).label.toLowerCase()] = (counts[pillOf(e).label.toLowerCase()] || 0) + 1;

  return (
    <div className="page wide embed-page">
      <div className="page-head">
        <div>
          <h1>Your website chatbots</h1>
          <p className="muted">Put your chatbots on their own websites: style our chat widget, or build your own UI with our API.</p>
        </div>
        {!adding && embeds.length > 0 && (
          <button className="btn primary" onClick={() => setAdding(true)}>
            <PlusIcon size={16} /> Add to a website
          </button>
        )}
      </div>
      {adding && <AddToWebsite me={me} choices={choices} onCreated={onCreated} onCancel={() => setAdding(false)} />}
      {embeds.length > 0 && (
        <div className="bots-toolbar">
          <div className="tabs status-filter" role="tablist" aria-label="Filter by status">
            {[["all", "All"], ["live", "Live"], ["pending", "Pending"], ["off", "Off"]].map(([id, label]) => (
              <button key={id} role="tab" aria-selected={status === id} className={`tab ${status === id ? "active" : ""}`} onClick={() => setStatus(id)}>
                {label} <span className="count">{counts[id] || 0}</span>
              </button>
            ))}
          </div>
          <div className="bot-search library-search">
            <SearchIcon />
            <input type="search" placeholder="Search your website chatbots" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search website chatbots" />
          </div>
        </div>
      )}

      {embeds.length === 0 && !adding ? (
        <section className="empty-embeds">
          <span className="dash-icon">
            <CodeIcon />
          </span>
          <h2>Add a chatbot to your website</h2>
          <ol className="steps">
            <li>
              <strong>1. Pick a chatbot</strong>
              <span className="muted small">One you created for your website.</span>
            </li>
            <li>
              <strong>2. Style it</strong>
              <span className="muted small">Colours, font, launcher and greeting, with a live preview.</span>
            </li>
            <li>
              <strong>3. Paste one line</strong>
              <span className="muted small">Add the snippet to your website. Or use our API for your own UI.</span>
            </li>
          </ol>
          <button className="btn primary" onClick={() => setAdding(true)}>
            <PlusIcon size={16} /> Add to a website
          </button>
        </section>
      ) : (
        embeds.length > 0 && (
          <>
            {!shown.length && <p className="muted small">No website chatbots match. Try another status or search.</p>}
            <div className="bot-grid embed-grid-list" ref={gridRef}>
              {visible.map((e) => {
                const pill = pillOf(e);
                return (
                  <div key={e.id} className="bot-card embed-tile" role="button" tabIndex={0} onClick={() => onOpen(e.id)} onKeyDown={(ev) => ev.key === "Enter" && onOpen(e.id)}>
                    <BotIcon site={e.site} size={32} />
                    <div className="bot-name">
                      {e.site.name} Chatbot
                      {e.my_role && e.my_role !== "owner" && <span className="pill shared-pill">Shared · {e.my_role}</span>}
                      <div className="muted small tile-meta">
                        {e.site.domain}
                        {!e.restrict_to_domain && <span className="pill warn-pill">any website</span>}
                      </div>
                      <div className="muted small">
                        {plural(e.chats_today, "chat")} · {money(e.spent_today_usd)} today
                      </div>
                      <InstallCheck embed={e} compact />
                    </div>
                    <span className={`status ${pill.cls}`}>{pill.label}</span>
                  </div>
                );
              })}
            </div>
            <Pager page={current} pages={pages} onPage={setPage} />
          </>
        )
      )}
    </div>
  );
}

/** route: {} for the list, or { embedId, tab, sub } for one chatbot's page. */
export default function EmbedPage({ me, sites, route, onRoute }) {
  const [embeds, setEmbeds] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.get("/api/embeds").then(setEmbeds).catch((e) => setError(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);

  if (!embeds) return <div className="page wide embed-page">{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</div>;

  const taken = new Set(embeds.map((e) => e.site_id));
  const choices = sites
    .filter((s) => s.ready && !taken.has(s.id) && (s.created_by === me.id || me.role === "admin"))
    .sort((a, b) => a.name.localeCompare(b.name));
  const embed = route.embedId && embeds.find((e) => e.id === route.embedId);
  // Some updates come from admin endpoints, which don't say what this user's role is; keep the one we know.
  const replace = (updated) => setEmbeds((list) => list.map((x) => (x.id === updated.id ? { ...updated, my_role: updated.my_role ?? x.my_role } : x)));

  if (embed) {
    return (
      <EmbedBot
        embed={embed}
        me={me}
        tab={route.tab}
        sub={route.sub}
        onRoute={onRoute}
        onChanged={replace}
        onRemoved={(id) => {
          setEmbeds((list) => list.filter((x) => x.id !== id));
          onRoute({});
        }}
      />
    );
  }
  return (
    <EmbedList
      me={me}
      embeds={embeds}
      choices={choices}
      onOpen={(id) => onRoute({ embedId: id, tab: "design" })}
      onCreated={(created) => {
        setEmbeds((list) => [created, ...list.filter((x) => x.id !== created.id)]);
        onRoute({ embedId: created.id, tab: "design" });
      }}
    />
  );
}
