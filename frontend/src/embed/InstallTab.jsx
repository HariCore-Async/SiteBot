// Website chatbot > Install: the snippet, sitebot-client.js and the server API, plus test websites.
import { useState } from "react";
import { useConfirm } from "../Confirm.jsx";
import { api, timeAgo } from "../api.js";
import { Tabs } from "../Tabs.jsx";
import { ArrowRightIcon } from "../Icons.jsx";
import { CopyBox, InstallCheck } from "./shared.jsx";

function snippetFor(key) {
  return `<script src="${location.origin}/embed.js" data-bot="${key}" async></script>`;
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

export function InstallTab({ embed, sub, onSub, onChanged }) {
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
          <TestWebsites embed={embed} onChanged={onChanged} />
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
          <TestWebsites embed={embed} onChanged={onChanged} />
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

function daysLeft(iso) {
  return Math.max(0, Math.ceil((new Date(iso) - Date.now()) / 86400000));
}

/** Extra websites this bot may run on while testing: your own computer, or a staging site. */
function TestWebsites({ embed, onChanged }) {
  const [origin, setOrigin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const canEdit = embed.my_role !== "viewer";
  const run = async (fn) => {
    setError("");
    setBusy(true);
    try {
      onChanged(await fn());
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    } finally {
      setBusy(false);
    }
  };
  const base = `/api/embeds/${embed.id}/test-origins`;

  return (
    <section className="test-websites">
      <div className="test-websites-head">
        <h3>Test websites</h3>
        <span className="muted small">
          For testing on your computer or a staging site. Localhost entries switch off after 7 days; other websites need an admin's approval.
        </span>
      </div>
      {embed.test_origins.length > 0 && (
        <ul className="test-origin-list">
          {embed.test_origins.map((t) => (
            <li key={t.origin} className={t.active ? "" : "expired"}>
              <code>{t.origin}</code>
              <span className="muted small">
                {t.status === "pending"
                  ? "Waiting for admin approval"
                  : !t.active
                    ? "Expired"
                    : t.expires_at
                      ? `${daysLeft(t.expires_at)} day${daysLeft(t.expires_at) === 1 ? "" : "s"} left`
                      : "No expiry"}
              </span>
              {canEdit && (
                <span className="actions">
                  {t.expires_at && (
                    <button className="btn ghost small" disabled={busy} onClick={() => run(() => api.post(`${base}/renew`, { origin: t.origin }))}>
                      Renew
                    </button>
                  )}
                  <button
                    className="btn ghost small danger"
                    disabled={busy}
                    aria-label={`Remove ${t.origin}`}
                    onClick={() => run(() => api.del(`${base}?${new URLSearchParams({ origin: t.origin })}`))}
                  >
                    Remove
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {canEdit ? (
        <form
          className="inline-form"
          onSubmit={async (e) => {
            e.preventDefault();
            if (origin.trim() && (await run(() => api.post(base, { origin: origin.trim() })))) setOrigin("");
          }}
        >
          <input
            value={origin}
            onChange={(e) => setOrigin(e.target.value)}
            placeholder="http://localhost:5175 or https://staging.example.com"
            aria-label="Test website address"
            maxLength={300}
          />
          <button className="btn small" disabled={busy || !origin.trim()}>
            Add
          </button>
        </form>
      ) : (
        !embed.test_origins.length && <p className="muted small">None.</p>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
