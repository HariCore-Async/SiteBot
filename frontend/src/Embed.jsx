import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useConfirm } from "./Confirm.jsx";
import { api, money, plural, timeAgo } from "./api.js";
import { BotIcon } from "./Sidebar.jsx";
import { Pager, useFitPageSize } from "./BotsPage.jsx";
import { linkCitations, mdComponents, Sources } from "./answer.jsx";
import { ArrowRightIcon, CodeIcon, PlusIcon } from "./Icons.jsx";

// "Add a chatbot to your website": a list of your website chatbots, and a page per chatbot with tabs
// (Design, Install, Conversations, Usage & settings). The open chatbot and tab live in the URL (see App.jsx).

/** The one status shown everywhere: Pending, Not approved, Live or Off. */
export function pillOf(e) {
  if (e.status === "pending") return { label: "Pending", cls: "pending" };
  if (e.status === "rejected") return { label: "Not approved", cls: "failed" };
  return e.enabled ? { label: "Live", cls: "ready" } : { label: "Off", cls: "off" };
}

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

function CodeBlock({ code }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="code-block">
      <pre>
        <code>{code}</code>
      </pre>
      <button
        className="btn small"
        onClick={() =>
          navigator.clipboard.writeText(code).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          })
        }
      >
        {copied ? "Copied ✓" : "Copy"}
      </button>
    </div>
  );
}

function Tabs({ tabs, value, onChange, className = "" }) {
  return (
    <div className={`tabs ${className}`} role="tablist">
      {tabs.map(([id, label, badge]) => (
        <button key={id} role="tab" aria-selected={value === id} className={`tab ${value === id ? "active" : ""}`} onClick={() => onChange(id)}>
          {label}
          {badge && <span className="pill accent tab-badge">{badge}</span>}
        </button>
      ))}
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


function plainExample(embed, base) {
  return `<!-- Your own chat UI in plain JavaScript. Works only on ${embed.site.domain}. -->
<div id="answer"></div>
<input id="question" placeholder="Ask a question"><button id="ask">Ask</button>

<script src="${base}/sitebot-client.js"></script>
<script>
  const bot = SiteBot.connect({ key: "${embed.key}" });
  document.getElementById("ask").onclick = async () => {
    const out = document.getElementById("answer");
    const reply = await bot.ask(document.getElementById("question").value, {
      onToken: (text, soFar) => (out.textContent = soFar),   // streamed as it arrives
    });
    out.textContent = reply.answer;      // reply.sources = [{ n, title, url }]
  };
</script>`;
}

// ---------- Design ----------

function DesignTab({ embed, onChanged }) {
  const [draft, setDraft] = useState(draftOf(embed));
  const [previewRev, setPreviewRev] = useState(0);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftOf(embed));
  const setStyle = (k, v) => setDraft((d) => ({ ...d, style: { ...d.style, [k]: v } }));

  const save = async () => {
    setError("");
    setSaving(true);
    try {
      const updated = await api.patch(`/api/embeds/${embed.id}`, draft);
      onChanged(updated);
      setDraft(draftOf(updated)); // the server may have cleaned up the custom CSS
      setPreviewRev((r) => r + 1);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="design-tab">
      <div className="embed-settings">
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
        {error && <p className="error">{error}</p>}
        <div className="embed-actions">
          <button className="btn primary small" disabled={!dirty || saving} onClick={save}>
            {saving ? "Saving…" : "Save changes"}
          </button>
          {dirty && (
            <button className="btn ghost small" onClick={() => setDraft(draftOf(embed))}>
              Discard
            </button>
          )}
        </div>
      </div>
      <div className="embed-preview">
        <div className="preview-label muted small">Live preview{dirty ? " (save to update)" : ""}</div>
        <iframe key={`${embed.key}-${previewRev}`} title="Chat preview" src={`/widget/${embed.key}?preview=1`} />
      </div>
    </div>
  );
}

// ---------- Install ----------

function ServerKey({ embed, onChanged }) {
  const [confirmAsk, confirmDialog] = useConfirm();
  const [secret, setSecret] = useState("");
  const [error, setError] = useState("");

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
    <div className="way">
      <strong>Server key</strong>
      <p className="muted small">Keep it on your server. Requests that use it from a browser are refused.</p>
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
      ) : (
        <p className="small muted">No server key yet.</p>
      )}
      {error && <p className="error">{error}</p>}
      <div className="embed-actions">
        <button className="btn small" onClick={makeKey}>
          {embed.server_key ? "Regenerate" : "Create server key"}
        </button>
        {embed.server_key && (
          <button className="btn ghost small danger" onClick={revoke}>
            Revoke
          </button>
        )}
      </div>
      {confirmDialog}
    </div>
  );
}

const INSTALL_TABS = [
  ["snippet", "Website snippet", "Recommended"],
  ["client", "Custom UI (browser)"],
  ["server", "Server API"],
];
const SERVER_EXAMPLES = [
  ["curl", "curl"],
  ["node", "Node / Express"],
  ["python", "Python"],
];
const CLIENT_EXAMPLES = [
  ["plain", "Plain JavaScript"],
  ["react", "React"],
];

function InstallTab({ embed, sub, onSub, onChanged }) {
  const [serverLang, setServerLang] = useState("curl");
  const [clientLang, setClientLang] = useState("plain");
  const base = location.origin;
  const ex = examples(embed, base);
  const where = embed.restrict_to_domain ? `on ${embed.site.domain} and its subdomains` : "on any secure (https) website";
  const tab = INSTALL_TABS.some(([id]) => id === sub) ? sub : "snippet";

  return (
    <div className="install-tab">
      {embed.status !== "approved" && (
        <p className="info-note">
          You can install it now: it starts answering visitors as soon as an admin approves it. Until then the widget stays hidden on your website.
        </p>
      )}
      <Tabs tabs={INSTALL_TABS} value={tab} onChange={onSub} className="sub-tabs" />

      {tab === "snippet" && (
        <div className="install-panel">
          <p className="muted">
            Our ready-made chat bubble, styled on the Design tab. Paste this line just before <code>&lt;/body&gt;</code> on every page where the chat should
            appear. It works {where}.
          </p>
          <CopyBox text={snippetFor(embed.key)} />
          <div className="embed-actions">
            <a className="btn small" href={`/widget-test.html?key=${encodeURIComponent(embed.key)}`} target="_blank" rel="noreferrer">
              Test it <ArrowRightIcon size={14} />
            </a>
            <span className="muted small">Opens a sample page with your widget, so you can try it before adding it to your website.</span>
          </div>
        </div>
      )}

      {tab === "client" && (
        <div className="install-panel">
          <p className="muted">
            Build your own chat UI in React, Vue or plain JavaScript, with no server code. Load <code>{base}/sitebot-client.js</code> and call{" "}
            <code>SiteBot.connect({"{"} key: "{embed.key}" {"}"})</code>. It uses your public key, so it works {where}.
          </p>
          <CopyBox text={`<script src="${base}/sitebot-client.js"></script>`} />
          <Tabs tabs={CLIENT_EXAMPLES} value={clientLang} onChange={setClientLang} className="code-tabs" />
          <CodeBlock code={clientLang === "react" ? ex.react : plainExample(embed, base)} />
        </div>
      )}

      {tab === "server" && (
        <div className="install-panel">
          <p className="muted">
            Ask from your own backend with a secret server key, then show the answers in any UI. Usage, limits and conversations work the same and show up here.
            Full reference: <code>docs/API.md</code> in the SiteBot repo.
          </p>
          <ServerKey embed={embed} onChanged={onChanged} />
          <Tabs tabs={SERVER_EXAMPLES} value={serverLang} onChange={setServerLang} className="code-tabs" />
          <CodeBlock code={ex[serverLang]} />
        </div>
      )}
    </div>
  );
}

// ---------- Conversations ----------

function ConversationsTab({ embed }) {
  const [chats, setChats] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [page, setPage] = useState(1);
  const listRef = useRef(null);
  useEffect(() => {
    api.get(`/api/embeds/${embed.id}/chats`).then(setChats).catch(() => setChats([]));
  }, [embed.id]);
  useEffect(() => {
    if (!openId) return;
    api.get(`/api/embeds/${embed.id}/chats/${openId}/messages`).then(setMessages).catch(() => setMessages([]));
  }, [embed.id, openId]);
  const pageSize = useFitPageSize(listRef, 80, [chats?.length > 0]);

  if (!chats) return <p className="muted small">Loading…</p>;
  if (!chats.length)
    return <p className="muted">No visitor conversations yet. They show up here as soon as someone chats with this bot on your website.</p>;
  const pages = Math.max(1, Math.ceil(chats.length / pageSize));
  const current = Math.min(page, pages);
  const visible = chats.slice((current - 1) * pageSize, current * pageSize);

  return (
    <div className="embed-convos">
      <div>
        <ul className="convo-list" ref={listRef}>
          {visible.map((c) => (
            <li key={c.id}>
              <button className={`convo-row ${openId === c.id ? "active" : ""}`} onClick={() => setOpenId(c.id)}>
                <span className="convo-title">{c.title}</span>
                <span className="muted small">
                  Visitor {c.visitor}
                  {c.origin ? ` on ${c.origin.replace(/^https?:\/\//, "")}` : ""} · {plural(c.messages, "message")} · {timeAgo(c.updated_at)}
                </span>
              </button>
            </li>
          ))}
        </ul>
        <Pager page={current} pages={pages} onPage={setPage} />
      </div>
      <div className="convo-view">
        {!openId && <p className="muted small">Pick a conversation to read it.</p>}
        {openId &&
          messages.map((m) => (
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
    </div>
  );
}

// ---------- Usage & settings ----------

function UsageTab({ embed, me, onChanged, onRemoved, onInstall }) {
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
            <div className="muted small">For the server API.</div>
          </div>
          <button className="btn ghost small" onClick={onInstall}>
            Manage
          </button>
        </div>
      </section>

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
      {confirmDialog}
    </div>
  );
}

// ---------- One chatbot's page ----------

const BOT_TABS = [
  ["design", "Design"],
  ["install", "Install"],
  ["conversations", "Conversations"],
  ["usage", "Usage & settings"],
];

function EmbedBot({ embed, me, tab, sub, onRoute, onChanged, onRemoved }) {
  const [confirmAsk, confirmDialog] = useConfirm();
  const [error, setError] = useState("");
  const pill = pillOf(embed);
  const current = BOT_TABS.some(([id]) => id === tab) ? tab : "design";
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
      <button className="link-btn back-link" onClick={() => onRoute({})}>
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
          <strong>Waiting for admin approval.</strong> You can design and install it now; it starts answering visitors once an admin approves it.
        </div>
      )}
      {embed.status === "rejected" && (
        <div className="banner rejected" role="status">
          <strong>An admin didn't approve this.</strong>{" "}
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

      <Tabs tabs={BOT_TABS} value={current} onChange={(t) => onRoute({ embedId: embed.id, tab: t })} className="bot-tabs" />
      {current === "design" && <DesignTab embed={embed} onChanged={onChanged} />}
      {current === "install" && (
        <InstallTab embed={embed} sub={sub} onSub={(s) => onRoute({ embedId: embed.id, tab: "install", sub: s })} onChanged={onChanged} />
      )}
      {current === "conversations" && <ConversationsTab embed={embed} />}
      {current === "usage" && (
        <UsageTab
          key={embed.daily_cap_usd}
          embed={embed}
          me={me}
          onChanged={onChanged}
          onRemoved={onRemoved}
          onInstall={() => onRoute({ embedId: embed.id, tab: "install", sub: "server" })}
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
  const gridRef = useRef(null);
  const pageSize = useFitPageSize(gridRef, 96, [embeds.length > 0, adding]);
  const pages = Math.max(1, Math.ceil(embeds.length / pageSize));
  const current = Math.min(page, pages);
  const visible = embeds.slice((current - 1) * pageSize, current * pageSize);

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
            <div className="bot-grid embed-grid-list" ref={gridRef}>
              {visible.map((e) => {
                const pill = pillOf(e);
                return (
                  <div key={e.id} className="bot-card embed-tile" role="button" tabIndex={0} onClick={() => onOpen(e.id)} onKeyDown={(ev) => ev.key === "Enter" && onOpen(e.id)}>
                    <BotIcon site={e.site} size={32} />
                    <div className="bot-name">
                      {e.site.name} Chatbot
                      <div className="muted small tile-meta">
                        {e.site.domain}
                        {!e.restrict_to_domain && <span className="pill warn-pill">any website</span>}
                      </div>
                      <div className="muted small">{plural(e.chats_today, "chat")} today</div>
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
  const replace = (updated) => setEmbeds((list) => list.map((x) => (x.id === updated.id ? updated : x)));

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
