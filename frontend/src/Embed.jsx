import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useConfirm } from "./Confirm.jsx";
import { api, money, plural, timeAgo } from "./api.js";
import { BotIcon } from "./Sidebar.jsx";
import { linkCitations, mdComponents, Sources } from "./answer.jsx";

const STATUS = {
  pending: { label: "Waiting for approval", cls: "queued" },
  approved: { label: "Approved", cls: "ready" },
  rejected: { label: "Not approved", cls: "failed" },
};

function snippetFor(key) {
  return `<script src="${location.origin}/embed.js" data-bot="${key}" async></script>`;
}

function Conversations({ embed }) {
  const [chats, setChats] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [messages, setMessages] = useState([]);
  useEffect(() => {
    api.get(`/api/embeds/${embed.id}/chats`).then(setChats).catch(() => setChats([]));
  }, [embed.id]);
  useEffect(() => {
    if (!openId) return;
    api.get(`/api/embeds/${embed.id}/chats/${openId}/messages`).then(setMessages).catch(() => setMessages([]));
  }, [embed.id, openId]);

  if (!chats) return <p className="muted small">Loading…</p>;
  if (!chats.length) return <p className="muted small">No visitor conversations yet.</p>;
  return (
    <div className="embed-convos">
      <ul className="convo-list">
        {chats.map((c) => (
          <li key={c.id}>
            <button className={`convo-row ${openId === c.id ? "active" : ""}`} onClick={() => setOpenId(c.id)}>
              <span className="convo-title">{c.title}</span>
              <span className="muted small">
                Visitor {c.visitor} · {plural(c.messages, "message")} · {timeAgo(c.updated_at)}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {openId && (
        <div className="convo-view">
          {messages.map((m) => (
            <div key={m.id} className={`convo-msg ${m.role}`}>
              <span className="convo-role">{m.role === "user" ? "Visitor" : "Bot"}</span>
              {m.role === "assistant" ? (
                <div>
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                    {linkCitations(m.content, m.sources)}
                  </ReactMarkdown>
                  <Sources sources={m.sources} />
                </div>
              ) : (
                <p>{m.content}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EmbedCard({ embed, onChanged, onRemoved }) {
  const [confirmAsk, confirmDialog] = useConfirm();
  const [draft, setDraft] = useState({ color: embed.color, position: embed.position, greeting: embed.greeting });
  const [previewRev, setPreviewRev] = useState(0);
  const [copied, setCopied] = useState(false);
  const [showChats, setShowChats] = useState(false);
  const [error, setError] = useState("");
  const status = STATUS[embed.status] || STATUS.pending;
  const dirty = draft.color !== embed.color || draft.position !== embed.position || draft.greeting !== embed.greeting;
  const snippet = snippetFor(embed.key);

  const act = async (fn) => {
    setError("");
    try {
      onChanged(await fn());
    } catch (e) {
      setError(e.message);
    }
  };

  const save = () =>
    act(async () => {
      const updated = await api.patch(`/api/embeds/${embed.id}`, draft);
      setPreviewRev((r) => r + 1);
      return updated;
    });

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Couldn't copy. Select the code and copy it yourself.");
    }
  };

  return (
    <section className="embed-card">
      <header className="embed-card-head">
        <BotIcon site={embed.site} size={32} />
        <div className="embed-card-meta">
          <h2>{embed.site.name} Chatbot</h2>
          <span className="muted small">Works on {embed.site.domain} and its subdomains</span>
        </div>
        <span className={`status ${status.cls}`}>{status.label}</span>
        {embed.status === "approved" && (
          <button
            role="switch"
            aria-checked={embed.enabled}
            aria-label="Show this chatbot on the website"
            title={embed.enabled ? "On: visitors can chat" : "Off: hidden from visitors"}
            className={`switch ${embed.enabled ? "on" : ""}`}
            onClick={() => act(() => api.patch(`/api/embeds/${embed.id}`, { enabled: !embed.enabled }))}
          >
            <span />
          </button>
        )}
      </header>

      {embed.status === "pending" && (
        <p className="muted small">An admin needs to approve this before it answers visitors. You can set it up and add the code to your website now.</p>
      )}
      {embed.status === "rejected" && (
        <p className="muted small">
          An admin didn't approve this.{" "}
          <button className="link-btn" onClick={() => act(() => api.post("/api/embeds", { site_id: embed.site_id }))}>
            Ask again
          </button>
        </p>
      )}
      {error && <p className="error">{error}</p>}

      <div className="embed-grid">
        <div className="embed-settings">
          <h3 className="section-title">1. Add this code to your website</h3>
          <p className="muted small">Paste it just before &lt;/body&gt; on every page where the chat should appear.</p>
          <div className="snippet">
            <code>{snippet}</code>
            <button className="btn small" onClick={copy}>
              {copied ? "Copied ✓" : "Copy"}
            </button>
          </div>

          <h3 className="section-title">2. Make it yours</h3>
          <div className="embed-fields">
            <label className="field">
              <span>Colour</span>
              <input type="color" value={draft.color} onChange={(e) => setDraft((d) => ({ ...d, color: e.target.value }))} />
            </label>
            <label className="field">
              <span>Position</span>
              <select value={draft.position} onChange={(e) => setDraft((d) => ({ ...d, position: e.target.value }))}>
                <option value="right">Bottom right</option>
                <option value="left">Bottom left</option>
              </select>
            </label>
          </div>
          <label className="field">
            <span>Greeting</span>
            <textarea
              rows={2}
              maxLength={300}
              placeholder={`Hi, welcome to ${embed.site.name}! Ask me anything about ${embed.site.name}.`}
              value={draft.greeting}
              onChange={(e) => setDraft((d) => ({ ...d, greeting: e.target.value }))}
            />
          </label>
          <button className="btn primary small" disabled={!dirty} onClick={save}>
            Save changes
          </button>

          <h3 className="section-title">Usage</h3>
          <p className="muted small">
            Visitors' questions use your credits. Today: {money(embed.spent_today_usd)} of the {money(embed.daily_cap_usd)} daily limit. All
            time: {money(embed.spent_total_usd)} across {plural(embed.conversations, "conversation")}.
          </p>
          <div className="embed-actions">
            <button className="btn ghost small" onClick={() => setShowChats((v) => !v)}>
              {showChats ? "Hide conversations" : "Visitor conversations"}
            </button>
            <button
              className="btn ghost small"
              onClick={async () => {
                const ok = await confirmAsk({
                  title: "Make a new code?",
                  message: "The code on your website stops working straight away. You'll need to paste the new code there.",
                  confirmLabel: "Make new code",
                });
                if (ok) act(() => api.post(`/api/embeds/${embed.id}/rotate-key`));
              }}
            >
              New code
            </button>
            <button
              className="btn ghost small danger"
              onClick={async () => {
                const ok = await confirmAsk({
                  title: "Remove from your website?",
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
              Remove
            </button>
          </div>
        </div>

        <div className="embed-preview">
          <div className="preview-label muted small">Preview{dirty ? " (save to update)" : ""}</div>
          <iframe key={`${embed.key}-${previewRev}`} title="Chat preview" src={`/widget/${embed.key}?preview=1`} />
        </div>
      </div>

      {showChats && <Conversations embed={embed} />}
      {confirmDialog}
    </section>
  );
}

export default function EmbedPage({ me, sites }) {
  const [embeds, setEmbeds] = useState(null);
  const [siteId, setSiteId] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(() => api.get("/api/embeds").then(setEmbeds).catch((e) => setError(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);

  const taken = new Set((embeds || []).map((e) => e.site_id));
  const eligible = sites.filter((s) => s.ready && (s.created_by === me.id || me.role === "admin") && !taken.has(s.id));

  const request = async (e) => {
    e.preventDefault();
    setError("");
    try {
      const created = await api.post("/api/embeds", { site_id: Number(siteId) });
      setEmbeds((list) => [created, ...(list || [])]);
      setSiteId("");
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="page embed-page">
      <div className="dash-head">
        <h1>Add a chatbot to your website</h1>
        <p className="muted">
          Put one of your chatbots on its own website. Visitors get a chat bubble that answers from your pages, with sources. It only
          works on that website, and an admin approves it first.
        </p>
      </div>

      <form className="add-form compact" onSubmit={request}>
        <select value={siteId} onChange={(e) => setSiteId(e.target.value)} required aria-label="Chatbot">
          <option value="">{eligible.length ? "Choose one of your chatbots" : "No chatbots to add"}</option>
          {eligible.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} Chatbot ({s.domain})
            </option>
          ))}
        </select>
        <button className="btn primary" disabled={!siteId}>
          {me.role === "admin" ? "Add to website" : "Request"}
        </button>
      </form>
      {!eligible.length && embeds && !embeds.length && (
        <p className="muted small">You can add chatbots you created. Create one for your website first, then come back here.</p>
      )}
      {error && <p className="error">{error}</p>}

      {(embeds || []).map((e) => (
        <EmbedCard
          key={e.id}
          embed={e}
          onChanged={(updated) => setEmbeds((list) => list.map((x) => (x.id === updated.id ? updated : x)))}
          onRemoved={(id) => setEmbeds((list) => list.filter((x) => x.id !== id))}
        />
      ))}
    </div>
  );
}
