import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useConfirm } from "./Confirm.jsx";
import { api, money, plural, timeAgo } from "./api.js";
import { BotIcon } from "./Sidebar.jsx";
import { Pager, useFitPageSize } from "./BotsPage.jsx";
import { linkCitations, mdComponents, Sources } from "./answer.jsx";
import { Tabs } from "./Tabs.jsx";
import { ArrowRightIcon, CodeIcon, PlusIcon, SearchIcon } from "./Icons.jsx";

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

function DesignTab({ embed, onChanged, onDirty }) {
  const [draft, setDraft] = useState(draftOf(embed));
  const [previewRev, setPreviewRev] = useState(0);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const previewRef = useRef(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftOf(embed));
  const setStyle = (k, v) => setDraft((d) => ({ ...d, style: { ...d.style, [k]: v } }));

  // Live preview: send every change to the preview straight away; Save keeps it.
  const sendDraft = useCallback(() => {
    previewRef.current?.contentWindow?.postMessage({ type: "sitebot:preview-style", draft }, location.origin);
  }, [draft]);
  useEffect(sendDraft, [sendDraft]);
  useEffect(() => {
    const onReady = (e) => {
      if (e.source === previewRef.current?.contentWindow && e.data?.type === "sitebot:preview-ready") sendDraft();
    };
    window.addEventListener("message", onReady);
    return () => window.removeEventListener("message", onReady);
  }, [sendDraft]);
  useEffect(() => onDirty?.(dirty), [dirty, onDirty]);
  useEffect(() => () => onDirty?.(false), [onDirty]);

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
        <div className="embed-fields">
          <label className="field">
            <span>Pop up a greeting</span>
            <select value={draft.style.proactive_seconds} onChange={(e) => setStyle("proactive_seconds", Number(e.target.value))}>
              <option value={0}>Off</option>
              {[5, 10, 20, 30, 60].map((s) => (
                <option key={s} value={s}>
                  After {s} seconds
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Pop-up text</span>
            <input maxLength={200} disabled={!draft.style.proactive_seconds} placeholder="The greeting" value={draft.style.proactive_text} onChange={(e) => setStyle("proactive_text", e.target.value)} />
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
          <button className="btn primary small" disabled={!dirty || saving || embed.my_role === "viewer"} title={embed.my_role === "viewer" ? "Viewers can't change the design" : ""} onClick={save}>
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
        <div className="preview-label muted small">Live preview{dirty ? " · unsaved changes" : ""}</div>
        <iframe
          ref={previewRef}
          key={`${embed.key}-${previewRev}`}
          title="Chat preview"
          src={`/widget/${embed.key}?preview=1`}
          onLoad={() => setTimeout(sendDraft, 50)}
        />
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
          Server key <code>sk_…{embed.server_key.hint}</code>, created {timeAgo(embed.server_key.created_at)}.{" "}
          {embed.server_key.last_used_at ? `Last used ${timeAgo(embed.server_key.last_used_at)}.` : "Not used yet."}
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

/** "Check installation": the last time a website loaded this bot (recorded by the widget and sitebot-client.js). */
function InstallCheck({ embed, compact = false }) {
  const seen = embed.last_seen;
  if (compact) {
    return seen ? (
      <span className="install-state ok">Installed on {seen.origin.replace(/^https?:\/\//, "")}</span>
    ) : (
      <span className="install-state">Not detected yet</span>
    );
  }
  return (
    <div className={`install-check ${seen ? "ok" : ""}`} role="status">
      <strong>{seen ? "Installed" : "Not detected yet"}</strong>
      <span className="muted small">
        {seen
          ? `Last seen on ${seen.origin.replace(/^https?:\/\//, "")} ${timeAgo(seen.at)}.`
          : embed.status === "approved"
            ? "Once the snippet is on your website, this updates the first time someone opens a page with it."
            : "This updates once the chatbot is approved and someone opens a page with the snippet."}
      </span>
    </div>
  );
}

const PLATFORMS = [
  ["WordPress", ["In WordPress, go to Appearance > Theme File Editor (or install the free “WPCode” plugin and open Code Snippets > Header & Footer).", "Paste the snippet into the footer area, just before </body>.", "Save, then open your website to check the chat bubble."]],
  ["Shopify", ["In Shopify admin, go to Online Store > Themes > … > Edit code.", "Open layout/theme.liquid and paste the snippet just before </body>.", "Save, then open your store to check the chat bubble."]],
  ["Wix", ["In your Wix dashboard, go to Settings > Custom Code (under Advanced).", "Click + Add Custom Code, paste the snippet, choose All pages, and place it in Body – end.", "Apply, then publish your site."]],
  ["Webflow", ["Open Project Settings > Custom Code.", "Paste the snippet in the Footer Code box (before </body> tag).", "Save, then publish your site."]],
  ["Squarespace", ["Go to Settings > Advanced > Code Injection (Website > Pages > Custom Code on newer versions).", "Paste the snippet into the Footer box.", "Save; the chat appears on every page."]],
  ["Google Tag Manager", ["In your GTM container, add a new tag of type Custom HTML.", "Paste the snippet and set the trigger to All Pages.", "Save, then Submit and Publish the container."]],
];

function PlatformGuides({ snippet }) {
  return (
    <div className="platform-guides">
      <strong>How to add it on…</strong>
      {PLATFORMS.map(([name, steps]) => (
        <details key={name} className="guide">
          <summary>{name}</summary>
          <ol>
            {steps.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>
          <CopyBox text={snippet} />
        </details>
      ))}
      <p className="muted small">Any other website: paste the snippet just before &lt;/body&gt; on every page, or in your site's “footer code” setting.</p>
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
      <Tabs tabs={INSTALL_TABS} value={tab} onChange={onSub} className="sub-tabs" label="Ways to install" />

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
          <InstallCheck embed={embed} />
          <PlatformGuides snippet={snippetFor(embed.key)} />
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
          {embed.my_role === "owner" ? (
            <ServerKey embed={embed} onChanged={onChanged} />
          ) : (
            <p className="info-note">Only the owner can create or change the server key.</p>
          )}
          <Tabs tabs={SERVER_EXAMPLES} value={serverLang} onChange={setServerLang} className="code-tabs" />
          <CodeBlock code={ex[serverLang]} />
        </div>
      )}
    </div>
  );
}

// ---------- Conversations ----------

function ConversationsTab({ embed, onTeach }) {
  const [chats, setChats] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [page, setPage] = useState(1);
  const [onlyMissed, setOnlyMissed] = useState(false);
  const [showTests, setShowTests] = useState(true);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const listRef = useRef(null);
  useEffect(() => {
    api.get(`/api/embeds/${embed.id}/chats`).then(setChats).catch(() => setChats([]));
  }, [embed.id]);
  useEffect(() => {
    if (!openId) return;
    api.get(`/api/embeds/${embed.id}/chats/${openId}/messages`).then(setMessages).catch(() => setMessages([]));
  }, [embed.id, openId]);
  useEffect(() => setPage(1), [onlyMissed, showTests, start, end]);

  const shown = (chats || []).filter((c) => {
    const day = c.updated_at.slice(0, 10);
    return (!onlyMissed || c.unanswered > 0) && (showTests || !c.is_test) && (!start || day >= start) && (!end || day <= end);
  });
  const pageSize = useFitPageSize(listRef, 80, [shown.length > 0, onlyMissed, showTests]);

  if (!chats) return <p className="muted small">Loading…</p>;
  if (!chats.length)
    return <p className="muted">No visitor conversations yet. They show up here as soon as someone chats with this bot on your website.</p>;
  const pages = Math.max(1, Math.ceil(shown.length / pageSize));
  const current = Math.min(page, pages);
  const visible = shown.slice((current - 1) * pageSize, current * pageSize);
  const missedTotal = chats.filter((c) => c.unanswered > 0 && !c.is_test).length;
  const exportUrl = (format) =>
    `/api/embeds/${embed.id}/export?` + new URLSearchParams({ format, start, end, unanswered: onlyMissed, tests: showTests }).toString();

  return (
    <div className="convos-tab">
      <div className="convo-toolbar">
        <label className="check">
          <input type="checkbox" checked={onlyMissed} onChange={(e) => setOnlyMissed(e.target.checked)} />
          Couldn't answer <span className="count">{missedTotal}</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={showTests} onChange={(e) => setShowTests(e.target.checked)} />
          Show test chats
        </label>
        <label className="date-field">
          <span className="muted small">From</span>
          <input type="date" value={start} max={end || undefined} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="date-field">
          <span className="muted small">To</span>
          <input type="date" value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <div className="export-btns">
          <span className="muted small">Export</span>
          <a className="btn small" href={exportUrl("xlsx")} download>
            Excel
          </a>
          <a className="btn small" href={exportUrl("csv")} download>
            CSV
          </a>
        </div>
      </div>
      <p className="muted small">The export includes every message of the conversations shown, using the same filters and dates.</p>

      <div className="embed-convos">
        <div>
          {shown.length ? (
            <ul className="convo-list" ref={listRef}>
              {visible.map((c) => (
                <li key={c.id}>
                  <button className={`convo-row ${openId === c.id ? "active" : ""}`} onClick={() => setOpenId(c.id)}>
                    <span className="convo-title">
                      {c.title}
                      {c.is_test && <span className="pill">Test</span>}
                      {c.unanswered > 0 && <span className="pill warn-pill">Couldn't answer {c.unanswered}</span>}
                    </span>
                    <span className="muted small">
                      {c.is_test ? "Your test" : `Visitor ${c.visitor}`}
                      {c.origin && !c.is_test ? ` on ${c.origin.replace(/^https?:\/\//, "")}` : ""} · {plural(c.messages, "message")} · {timeAgo(c.updated_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small">No conversations match these filters.</p>
          )}
          <Pager page={current} pages={pages} onPage={setPage} />
        </div>
        <div className="convo-view">
          {!openId && <p className="muted small">Pick a conversation to read it.</p>}
          {openId &&
            messages.map((m, i) => (
              <div key={m.id} className={`convo-msg ${m.role} ${m.role === "assistant" && !m.grounded ? "missed" : ""}`}>
                <span className="convo-role">
                  {m.role === "user" ? "Visitor" : "Bot"}
                  {m.role === "assistant" && !m.grounded && <span className="pill warn-pill">Couldn't answer from the website</span>}
                  {m.role === "assistant" && !m.grounded && messages[i - 1]?.role === "user" && onTeach && (
                    <button className="link-btn small teach-btn" onClick={() => onTeach(messages[i - 1].content)}>
                      Teach the bot
                    </button>
                  )}
                </span>
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
    </div>
  );
}

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

function UsageTab({ embed, me, onChanged, onRemoved, onInstall, onTeach }) {
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

// ---------- One chatbot's page ----------

// ---------- Knowledge: teach the bot ----------

const MAX_UPLOAD = 10 * 1024 * 1024;

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error("Couldn't read that file."));
    reader.readAsDataURL(file);
  });
}

function AnswerForm({ siteId, initial, onSaved, onCancel }) {
  const [question, setQuestion] = useState(initial?.title || initial?.question || "");
  const [answer, setAnswer] = useState(initial?.content || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="answer-form"
      onSubmit={async (e) => {
        e.preventDefault();
        setError("");
        setBusy(true);
        try {
          const saved = initial?.id
            ? await api.patch(`/api/sites/${siteId}/knowledge/${initial.id}`, { question, answer })
            : await api.post(`/api/sites/${siteId}/knowledge/answers`, { question, answer });
          onSaved(saved);
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label className="field">
        <span>Question</span>
        <input required maxLength={500} placeholder="Do you ship to Canada?" value={question} onChange={(e) => setQuestion(e.target.value)} />
      </label>
      <label className="field">
        <span>Answer</span>
        <textarea required rows={4} maxLength={5000} placeholder="Yes, we ship to Canada in 5–7 working days." value={answer} onChange={(e) => setAnswer(e.target.value)} />
      </label>
      {error && <p className="error">{error}</p>}
      <div className="embed-actions">
        <button className="btn primary small" disabled={busy}>
          {busy ? "Saving…" : initial?.id ? "Save answer" : "Teach the bot"}
        </button>
        {onCancel && (
          <button type="button" className="btn ghost small" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

function KnowledgeTab({ embed, prefill, onPrefillUsed }) {
  const readOnly = embed.my_role === "viewer";
  const siteId = embed.site_id;
  const [items, setItems] = useState(null);
  const [adding, setAdding] = useState(prefill ? { question: prefill } : null);
  const [editing, setEditing] = useState(null);
  const [uploading, setUploading] = useState("");
  const [error, setError] = useState("");
  const [confirmAsk, confirmDialog] = useConfirm();
  const load = useCallback(() => api.get(`/api/sites/${siteId}/knowledge`).then(setItems).catch((e) => setError(e.message)), [siteId]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (prefill) onPrefillUsed?.();
  }, [prefill, onPrefillUsed]);

  const upload = async (files) => {
    setError("");
    for (const file of files) {
      if (file.size > MAX_UPLOAD) {
        setError(`${file.name} is over 10 MB.`);
        continue;
      }
      setUploading(file.name);
      try {
        await api.post(`/api/sites/${siteId}/knowledge/documents`, { filename: file.name, data_b64: await readAsBase64(file) });
      } catch (e) {
        setError(`${file.name}: ${e.message}`);
      }
    }
    setUploading("");
    load();
  };

  const remove = async (k) => {
    const ok = await confirmAsk({
      title: `Remove ${k.kind === "answer" ? "this answer" : k.filename}?`,
      message: "The bot stops using it straight away.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    await api.del(`/api/sites/${siteId}/knowledge/${k.id}`);
    load();
  };

  const answers = (items || []).filter((k) => k.kind === "answer");
  const docs = (items || []).filter((k) => k.kind === "document");
  return (
    <div className="knowledge-tab">
      <p className="muted">
        Teach {embed.site.name} Chatbot things that aren't on the website. It uses your answers and documents alongside the website's pages, and cites
        them like any other source. Updating the website from its pages keeps them.
      </p>
      {error && <p className="error">{error}</p>}
      <section className="way">
        <div className="section-row">
          <strong>Your answers</strong>
          {!adding && !readOnly && (
            <button className="btn small" onClick={() => setAdding({})}>
              <PlusIcon size={14} /> Add an answer
            </button>
          )}
        </div>
        {adding && (
          <AnswerForm
            siteId={siteId}
            initial={adding}
            onCancel={() => setAdding(null)}
            onSaved={() => {
              setAdding(null);
              load();
            }}
          />
        )}
        {items && !answers.length && !adding && <p className="muted small">No answers yet. Tip: the Usage tab lists questions it couldn't answer, each with "Teach the bot".</p>}
        <ul className="knowledge-list">
          {answers.map((k) =>
            editing === k.id ? (
              <li key={k.id}>
                <AnswerForm siteId={siteId} initial={k} onCancel={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />
              </li>
            ) : (
              <li key={k.id}>
                <div>
                  <div className="strong">{k.title}</div>
                  <div className="muted small knowledge-answer">{k.content}</div>
                </div>
                {!readOnly && <div className="row-actions">
                  <button className="link-btn small" onClick={() => setEditing(k.id)}>
                    Edit
                  </button>
                  <button className="link-btn small danger-link" onClick={() => remove(k)}>
                    Remove
                  </button>
                </div>}
              </li>
            )
          )}
        </ul>
      </section>
      <section className="way">
        <strong>Documents</strong>
        <p className="muted small">PDF, Word (.docx), text or Markdown, up to 10 MB each (50 per bot). Scanned PDFs without a text layer can't be read.</p>
        {!readOnly && <label className="btn small upload-btn">
          {uploading ? `Uploading ${uploading}…` : "Upload documents"}
          <input
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.md,application/pdf,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            disabled={!!uploading}
            onChange={(e) => {
              upload([...e.target.files]);
              e.target.value = "";
            }}
          />
        </label>}
        <ul className="knowledge-list">
          {docs.map((k) => (
            <li key={k.id}>
              <div>
                <div className="strong">{k.filename}</div>
                <div className="muted small">
                  {(k.size / 1024).toFixed(0)} KB · {plural(k.chunks, "passage")} · added {timeAgo(k.created_at)}
                </div>
              </div>
              {!readOnly && <div className="row-actions">
                <button className="link-btn small danger-link" onClick={() => remove(k)}>
                  Remove
                </button>
              </div>}
            </li>
          ))}
        </ul>
      </section>
      {confirmDialog}
    </div>
  );
}

// ---------- Leads: visitors who want to hear back ----------

function LeadsTab({ embed, onChanged }) {
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

const BOT_TABS = [
  ["design", "Design"],
  ["install", "Install"],
  ["knowledge", "Knowledge"],
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
          <strong>Waiting for admin approval.</strong> You can design and install it now; it starts answering visitors once an admin approves it.
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
