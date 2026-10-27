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

const draftOf = (e) => ({ color: e.color, position: e.position, greeting: e.greeting, style: { ...e.style } });

function CopyBox({ text, label = "Copy" }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="snippet">
      <code>{text}</code>
      <button
        className="btn small"
        onClick={() =>
          navigator.clipboard.writeText(text).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          })
        }
      >
        {copied ? "Copied ✓" : label}
      </button>
    </div>
  );
}

function examples(embed, base) {
  const sk = "$SITEBOT_SERVER_KEY";
  return {
    curl: `# Streams NDJSON events: conversation, user_saved, token..., replace?, done (or error)
curl -N ${base}/api/v1/messages \\
  -H "Authorization: Bearer ${sk}" \\
  -H "Content-Type: application/json" \\
  -d '{"visitor_id": "user-123", "content": "What do you offer?"}'

# One JSON reply instead of a stream
curl ${base}/api/v1/messages \\
  -H "Authorization: Bearer ${sk}" \\
  -H "Content-Type: application/json" \\
  -d '{"visitor_id": "user-123", "content": "What do you offer?", "stream": false}'`,
    node: `// Express route that your own chat UI calls. The sk_ key stays on your server.
import express from "express";
const app = express();
app.use(express.json());

app.post("/chat", async (req, res) => {
  const r = await fetch("${base}/api/v1/messages", {
    method: "POST",
    headers: {
      Authorization: \`Bearer \${process.env.SITEBOT_SERVER_KEY}\`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      visitor_id: req.user?.id ?? req.ip,      // your own user id keeps their history
      conversation_id: req.body.conversationId, // optional: continue a conversation
      content: req.body.message,
    }),
  });
  // Pass the NDJSON stream straight through to your browser code.
  res.status(r.status).type("application/x-ndjson");
  for await (const chunk of r.body) res.write(chunk);
  res.end();
});

app.listen(3000);`,
    python: `# pip install requests
import json, os, requests

def ask(visitor_id, question, conversation_id=None):
    r = requests.post(
        "${base}/api/v1/messages",
        headers={"Authorization": f"Bearer {os.environ['SITEBOT_SERVER_KEY']}"},
        json={"visitor_id": visitor_id, "content": question,
              "conversation_id": conversation_id, "stream": False},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()  # {conversation_id, message_id, answer, sources, grounded}

reply = ask("user-123", "What do you offer?")
print(reply["answer"])
for s in reply["sources"]:
    print(f"[{s['n']}] {s['title']} {s['url']}")`,
    react: `// In your index.html (or load it once anywhere):
// <script src="${base}/sitebot-client.js"></script>
// Works only on ${embed.site.domain}: it uses your public key, no server needed.
import { useMemo, useState } from "react";

export default function Chat() {
  const bot = useMemo(() => window.SiteBot.connect({ key: "${embed.key}" }), []);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");

  async function send(e) {
    e.preventDefault();
    const question = text;
    setText("");
    setMessages((m) => [...m, { role: "user", content: question }, { role: "bot", content: "" }]);
    const show = (soFar) => setMessages((m) => [...m.slice(0, -1), { role: "bot", content: soFar }]);
    try {
      const reply = await bot.ask(question, { onToken: (_, soFar) => show(soFar) });
      show(reply.answer); // reply.sources = [{ n, title, url }]
    } catch (err) {
      show(err.message);
    }
  }

  return (
    <form onSubmit={send}>
      {messages.map((m, i) => <p key={i}><b>{m.role}:</b> {m.content}</p>)}
      <input value={text} onChange={(e) => setText(e.target.value)} />
    </form>
  );
}`,
  };
}

const EXAMPLE_TABS = [
  ["curl", "curl"],
  ["node", "Node / Express"],
  ["python", "Python"],
  ["react", "React (browser)"],
];

function Developers({ embed, onChanged }) {
  const [confirmAsk, confirmDialog] = useConfirm();
  const [secret, setSecret] = useState("");
  const [tab, setTab] = useState("curl");
  const [error, setError] = useState("");
  const base = location.origin;
  const code = examples(embed, base)[tab];

  const makeKey = async () => {
    if (embed.server_key) {
      const ok = await confirmAsk({
        title: "Replace the server key?",
        message: "The current key stops working straight away. Update it on your server.",
        confirmLabel: "Replace key",
      });
      if (!ok) return;
    }
    setError("");
    try {
      const res = await api.post(`/api/embeds/${embed.id}/server-key`);
      setSecret(res.secret);
      onChanged(res);
    } catch (e) {
      setError(e.message);
    }
  };

  const revoke = async () => {
    const ok = await confirmAsk({
      title: "Revoke the server key?",
      message: "Anything using it stops working straight away.",
      confirmLabel: "Revoke",
      danger: true,
    });
    if (!ok) return;
    try {
      setSecret("");
      onChanged(await api.del(`/api/embeds/${embed.id}/server-key`));
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="developers">
      <h3 className="section-title">Build your own chat UI</h3>
      <p className="muted small">
        Prefer your own design or tech stack? Skip our widget and use the same answers, with sources, from your code. Usage, limits and
        conversations work the same and show up here. Full reference: <code>docs/API.md</code> in the SiteBot repo.
      </p>
      <div className="dev-options">
        <div>
          <strong>In the browser</strong>
          <p className="muted small">
            Load <code>{base}/sitebot-client.js</code> and call <code>SiteBot.connect({"{"} key: "{embed.key}" {"}"})</code>. It uses your public key, so it only
            works on {embed.site.domain}.
          </p>
        </div>
        <div>
          <strong>From your server</strong>
          <p className="muted small">
            Call the server API with a secret key. Keep it on your server: requests sent from a browser are refused.
          </p>
          {secret ? (
            <div className="secret-box">
              <p className="small">
                <strong>Copy your key now.</strong> It won't be shown again.
              </p>
              <CopyBox text={secret} />
            </div>
          ) : embed.server_key ? (
            <p className="small">
              Server key <code>sk_…{embed.server_key.hint}</code>, created {timeAgo(embed.server_key.created_at)}.
            </p>
          ) : null}
          <div className="embed-actions">
            <button className="btn small" onClick={makeKey}>
              {embed.server_key ? "Replace server key" : "Create server key"}
            </button>
            {embed.server_key && (
              <button className="btn ghost small danger" onClick={revoke}>
                Revoke
              </button>
            )}
          </div>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="tabs code-tabs" role="tablist">
        {EXAMPLE_TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={`tab ${tab === id ? "active" : ""}`} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      <div className="code-block">
        <pre>
          <code>{code}</code>
        </pre>
        <button className="btn small" onClick={() => navigator.clipboard.writeText(code)}>
          Copy
        </button>
      </div>
      {confirmDialog}
    </div>
  );
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
                  {m.feedback && (
                    <span className={`pill ${m.feedback.rating === "up" ? "accent" : ""}`}>
                      Visitor rated this {m.feedback.rating === "up" ? "👍 helpful" : "👎 not helpful"}
                      {m.feedback.comment ? `: "${m.feedback.comment}"` : ""}
                    </span>
                  )}
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
  const [draft, setDraft] = useState(draftOf(embed));
  const [previewRev, setPreviewRev] = useState(0);
  const [copied, setCopied] = useState(false);
  const [showChats, setShowChats] = useState(false);
  const [error, setError] = useState("");
  const status = STATUS[embed.status] || STATUS.pending;
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftOf(embed));
  const setStyle = (k, v) => setDraft((d) => ({ ...d, style: { ...d.style, [k]: v } }));
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
      setDraft(draftOf(updated)); // the server may have cleaned up the custom CSS
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
            <label className="field">
              <span>Theme</span>
              <select value={draft.style.theme} onChange={(e) => setStyle("theme", e.target.value)}>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
                <option value="auto">Match visitor's device</option>
              </select>
            </label>
          </div>
          <div className="embed-fields">
            <label className="field">
              <span>Header title</span>
              <input maxLength={60} placeholder={embed.site.name} value={draft.style.title} onChange={(e) => setStyle("title", e.target.value)} />
            </label>
            <label className="field">
              <span>Font</span>
              <select value={draft.style.font} onChange={(e) => setStyle("font", e.target.value)}>
                <option value="system">System</option>
                <option value="sans">Sans serif</option>
                <option value="serif">Serif</option>
                <option value="rounded">Rounded</option>
                <option value="mono">Monospace</option>
              </select>
            </label>
          </div>
          <div className="embed-fields">
            <label className="field">
              <span>Launcher icon</span>
              <select value={draft.style.launcher_icon} onChange={(e) => setStyle("launcher_icon", e.target.value)}>
                <option value="chat">Chat bubble</option>
                <option value="help">Question mark</option>
                <option value="sparkle">Sparkle</option>
                <option value="none">No icon (label only)</option>
              </select>
            </label>
            <label className="field">
              <span>Launcher label</span>
              <input maxLength={30} placeholder="None (round button)" value={draft.style.launcher_label} onChange={(e) => setStyle("launcher_label", e.target.value)} />
            </label>
          </div>
          <label className="field">
            <span>Corner rounding: {draft.style.radius}px</span>
            <input type="range" min="0" max="28" value={draft.style.radius} onChange={(e) => setStyle("radius", Number(e.target.value))} />
          </label>
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
          <details className="custom-css">
            <summary>Custom CSS</summary>
            <p className="muted small">
              Applies only inside the chat window. Style classes such as <code>.w-head</code>, <code>.w-bubble</code>, <code>.w-msg.user .w-bubble-text</code>,{" "}
              <code>.w-suggestion</code> and <code>.w-composer</code>. Imports and <code>url()</code> are removed.
            </p>
            <textarea
              rows={5}
              maxLength={5000}
              spellCheck={false}
              placeholder={".w-head { letter-spacing: 0.02em; }"}
              value={draft.style.custom_css}
              onChange={(e) => setStyle("custom_css", e.target.value)}
            />
          </details>
          <button className="btn primary small" disabled={!dirty} onClick={save}>
            Save changes
          </button>

          <h3 className="section-title">Usage</h3>
          <p className="muted small">
            Visitors' questions use your credits. Today: {money(embed.spent_today_usd)} of the {money(embed.daily_cap_usd)} daily limit. All
            time: {money(embed.spent_total_usd)} across {plural(embed.conversations, "conversation")}. Visitors rated answers 👍{" "}
            {embed.feedback.up} · 👎 {embed.feedback.down}.
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
      <Developers embed={embed} onChanged={onChanged} />
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
