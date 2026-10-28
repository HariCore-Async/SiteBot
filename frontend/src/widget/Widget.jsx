import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, streamEvents } from "../api.js";
import { linkCitations, mdComponents, Sources } from "../answer.jsx";

// The chat bubble and window a website shows through embed.js. It runs inside an iframe served by SiteBot.
// URL: /widget/<key>?origin=<the website> (from embed.js), or ?preview=1 inside SiteBot's own Embed page.
const params = new URLSearchParams(location.search);
const KEY = decodeURIComponent(location.pathname.split("/").filter(Boolean)[1] || "");
const ORIGIN = params.get("origin") || "";
const PREVIEW = params.get("preview") === "1";
// "Test it" page: behaves like the real embed (bubble, open and close) but answers as a preview for the signed-in
// owner, so it works before approval and on SiteBot's own sample page.
const TEST = params.get("test") === "1";
const AS_PREVIEW = PREVIEW || TEST;
const query = `origin=${encodeURIComponent(ORIGIN)}${AS_PREVIEW ? "&preview=true" : ""}`;

// Visitors are anonymous: a random id in this browser keeps their conversation across page loads.
const STORE = `sitebot_visitor_${KEY}`;
let memoryVisitor = "";
function newVisitorId() {
  const id = (crypto.randomUUID?.() || `${Date.now()}${Math.random()}`).replace(/[^A-Za-z0-9]/g, "").slice(0, 32).padEnd(16, "0");
  memoryVisitor = id;
  try {
    localStorage.setItem(STORE, id);
  } catch {
    /* storage blocked: the conversation lasts until the page is closed */
  }
  return id;
}
function visitorId() {
  try {
    const saved = localStorage.getItem(STORE);
    if (saved) return saved;
  } catch {
    /* fall through */
  }
  return memoryVisitor || newVisitorId();
}

/** Tells embed.js how big to make the iframe (and whether to show it at all). */
function tellParent(state) {
  if (window.parent === window || PREVIEW) return;
  window.parent.postMessage({ type: "sitebot:state", ...state }, ORIGIN || "*");
}

/** The saved config with the Design tab's unsaved changes on top (live preview). */
function withDraft(cfg, d) {
  return {
    ...cfg,
    color: d.color || cfg.color,
    position: d.position || cfg.position,
    greeting: d.greeting?.trim() || `Hi, welcome to ${cfg.name}! Ask me anything about ${cfg.name}.`,
    style: { ...cfg.style, ...d.style },
  };
}

// Text on the accent colour: dark on light accents, white on dark ones.
function onAccent(hex) {
  const n = parseInt((hex || "#000000").slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return 0.299 * r + 0.587 * g + 0.114 * b > 170 ? "#111111" : "#ffffff";
}

function Avatar({ cfg, size = 30 }) {
  const [broken, setBroken] = useState(false);
  if (cfg.favicon && !broken) return <img className="w-avatar" src={cfg.favicon} alt="" width={size} height={size} onError={() => setBroken(true)} />;
  return (
    <span className="w-avatar letter" style={{ width: size, height: size }}>
      {(cfg.name || "?").charAt(0).toUpperCase()}
    </span>
  );
}

const icon = (d, size = 26) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={d} />
  </svg>
);
const LAUNCHER_ICONS = {
  chat: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17h.01",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
};
const FONTS = {
  system: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  sans: '"Helvetica Neue", Helvetica, Arial, sans-serif',
  serif: 'Georgia, Cambria, "Times New Roman", serif',
  rounded: 'ui-rounded, "SF Pro Rounded", "Nunito", "Segoe UI", system-ui, sans-serif',
  mono: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
};
const ThumbIcon = ({ down }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={down ? { transform: "rotate(180deg)" } : undefined}>
    <path d="M7 10v11M15 5.9 14 10h5.8a2 2 0 0 1 2 2.3l-1.4 7A2 2 0 0 1 18.4 21H7V10l4-8a3 3 0 0 1 3 3.9z" />
  </svg>
);

/** Thumbs up/down under an answer. Owners see the ratings on their Embed page. */
/** Human handoff: after an answer the bot couldn't give, the visitor can leave their email for the team. */
function Handoff({ onSent }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ email: "", name: "", message: "" });
  const [state, setState] = useState("");
  const [error, setError] = useState("");
  if (state === "sent") return <p className="w-handoff-done">Thanks! The team will get back to you at {form.email}.</p>;
  if (!open)
    return (
      <button className="w-handoff-open" onClick={() => setOpen(true)}>
        Want a person to get back to you? Leave your email
      </button>
    );
  return (
    <form
      className="w-handoff"
      onSubmit={async (e) => {
        e.preventDefault();
        setError("");
        setState("sending");
        try {
          await api.post(`/api/public/${encodeURIComponent(KEY)}/leads`, { visitor_id: visitorId(), origin: ORIGIN, ...form });
          setState("sent");
          onSent?.();
        } catch (err) {
          setError(err.message);
          setState("");
        }
      }}
    >
      <input type="email" required placeholder="Your email" aria-label="Your email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
      <input placeholder="Your name (optional)" aria-label="Your name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      <textarea rows={2} maxLength={2000} placeholder="Anything else? (optional)" aria-label="Message" value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} />
      {error && <p className="w-error">{error}</p>}
      <button className="w-send-lead" disabled={state === "sending"}>
        {state === "sending" ? "Sending…" : "Send"}
      </button>
    </form>
  );
}

function Rate({ m, onRate }) {
  if (!m.id || m.pending) return null;
  const rating = m.feedback?.rating;
  return (
    <div className="w-rate">
      <button className={rating === "up" ? "on" : ""} aria-label="Helpful" aria-pressed={rating === "up"} onClick={() => onRate(m, "up")}>
        <ThumbIcon />
      </button>
      <button className={rating === "down" ? "on" : ""} aria-label="Not helpful" aria-pressed={rating === "down"} onClick={() => onRate(m, "down")}>
        <ThumbIcon down />
      </button>
      {rating && <span>Thanks for the feedback</span>}
    </div>
  );
}
const CloseIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);
const SendIcon = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 19V5M5 12l7-7 7 7" />
  </svg>
);

export default function Widget() {
  const [cfg, setCfg] = useState(null);
  const [unavailable, setUnavailable] = useState("");
  // Offer the handoff once per conversation, under the latest answer the bot couldn't give.
  const [contactedId, setContactedId] = useState(null);
  const [open, setOpen] = useState(PREVIEW);
  const [messages, setMessages] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const launcherRef = useRef(null);
  const [dark, setDark] = useState(false);
  const [full, setFull] = useState(false);
  // Live preview: the Design tab sends its unsaved changes here as you edit (preview only, same origin only).
  const draftRef = useRef(null);

  useEffect(() => {
    if (!PREVIEW) return;
    const onMessage = (e) => {
      if (e.source !== window.parent || e.origin !== location.origin || e.data?.type !== "sitebot:preview-style") return;
      draftRef.current = e.data.draft;
      setCfg((c) => (c ? withDraft(c, e.data.draft) : c));
    };
    window.addEventListener("message", onMessage);
    // Ask the Design tab for its current draft, in case it was sent before this page was listening.
    if (window.parent !== window) window.parent.postMessage({ type: "sitebot:preview-ready" }, location.origin);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  useEffect(() => {
    const onMessage = (e) => {
      if (e.source === window.parent && e.data?.type === "sitebot:layout" && (!ORIGIN || e.origin === ORIGIN)) setFull(!!e.data.full);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  useEffect(() => {
    api
      .get(`/api/public/${encodeURIComponent(KEY)}/config?${query}`)
      .then((c) => setCfg(draftRef.current ? withDraft(c, draftRef.current) : c))
      .catch((e) => {
        setUnavailable(e.message);
        // On the "Test it" page, say why instead of disappearing.
        tellParent(TEST ? { open: true, position: "right" } : { hidden: true });
      });
  }, []);

  // Theme, font and the owner's custom CSS (already sanitised by the server) apply to this iframe's page only.
  useEffect(() => {
    if (!cfg) return;
    const theme = cfg.style?.theme || "light";
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => setDark(theme === "dark" || (theme === "auto" && media.matches));
    apply();
    media.addEventListener("change", apply);
    let tag = document.getElementById("sitebot-custom-css");
    if (!tag) {
      tag = document.createElement("style");
      tag.id = "sitebot-custom-css";
      document.head.appendChild(tag);
    }
    tag.textContent = cfg.style?.custom_css || "";
    return () => media.removeEventListener("change", apply);
  }, [cfg]);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  // embed.js sizes the iframe: the launcher's own size while closed, a chat window while open.
  useEffect(() => {
    if (!cfg) return;
    const el = launcherRef.current;
    const size = !open && el ? { width: Math.ceil(el.offsetWidth) + 24, height: Math.ceil(el.offsetHeight) + 24 } : null;
    tellParent({ open, position: cfg.position, size });
  }, [cfg, open]);

  useEffect(() => {
    if (!cfg || !open || loaded) return;
    setLoaded(true);
    api
      .get(`/api/public/${encodeURIComponent(KEY)}/messages?visitor_id=${visitorId()}&${query}`)
      .then(setMessages)
      .catch(() => {});
  }, [cfg, open, loaded]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  if (!cfg) {
    return AS_PREVIEW && unavailable ? <div className="w-unavailable">{unavailable}</div> : null;
  }

  const look = cfg.style || {};
  const style = {
    "--w-accent": cfg.color,
    "--w-on-accent": onAccent(cfg.color),
    "--w-radius": `${look.radius ?? 16}px`,
    "--w-font": FONTS[look.font] || FONTS.system,
    fontFamily: "var(--w-font)",
  };
  const title = look.title || cfg.name;

  const rate = async (m, rating) => {
    setMessages((list) => list.map((x) => (x === m ? { ...x, feedback: { rating } } : x)));
    try {
      await api.post(`/api/public/${encodeURIComponent(KEY)}/feedback`, { visitor_id: visitorId(), message_id: m.id, rating, origin: ORIGIN });
    } catch {
      /* feedback is best-effort */
    }
  };

  const send = async (text) => {
    const content = (text ?? input).trim();
    if (!content || sending) return;
    setError("");
    setInput("");
    setSending(true);
    setMessages((m) => [...m, { role: "user", content }, { role: "assistant", content: "", pending: true, sources: [] }]);
    const patchLast = (fn) => setMessages((m) => [...m.slice(0, -1), fn(m[m.length - 1])]);
    try {
      await streamEvents(
        `/api/public/${encodeURIComponent(KEY)}/messages`,
        { visitor_id: visitorId(), content, origin: ORIGIN, preview: AS_PREVIEW },
        (ev) => {
          if (ev.type === "token") patchLast((last) => ({ ...last, content: last.content + ev.text }));
          else if (ev.type === "replace") patchLast((last) => ({ ...last, content: ev.text }));
          else if (ev.type === "done") patchLast((last) => ({ ...last, id: ev.message_id, pending: false, sources: ev.sources, grounded: ev.grounded }));
          else if (ev.type === "error") {
            setMessages((m) => m.filter((x) => !x.pending));
            setError(ev.message);
          }
        }
      );
    } catch {
      setMessages((m) => m.filter((x) => !x.pending));
      setError("Couldn't send your message. Please try again.");
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  const startOver = () => {
    newVisitorId();
    setContactedId(null);
    setMessages([]);
    setError("");
    inputRef.current?.focus();
  };

  if (!open) {
    return (
      <div className={`w-launcher ${cfg.position}`} style={style} ref={launcherRef}>
        <button
          className={`w-bubble ${look.launcher_label ? "labelled" : ""}`}
          onClick={() => setOpen(true)}
          aria-label={look.launcher_label || `Chat with ${title}`}
          title={`Chat with ${title}`}
        >
          {look.launcher_icon !== "none" && icon(LAUNCHER_ICONS[look.launcher_icon] || LAUNCHER_ICONS.chat, look.launcher_label ? 22 : 26)}
          {look.launcher_label && <span>{look.launcher_label}</span>}
        </button>
      </div>
    );
  }

  const asked = new Set(messages.filter((m) => m.role === "user").map((m) => m.content.trim().toLowerCase()));
  const lastMissed = [...messages].reverse().find((m) => m.role === "assistant" && m.grounded === false);
  const suggestions = messages.length ? [] : (cfg.suggestions || []).filter((q) => !asked.has(q.toLowerCase()));

  return (
    <div className={`w-panel ${PREVIEW ? "preview" : ""} ${full ? "full" : ""}`} style={style} role="dialog" aria-label={`${title} assistant`}>
      <header className="w-head">
        <Avatar cfg={cfg} />
        <div className="w-head-meta">
          <strong>{title}</strong>
          <span>Answers from {cfg.domain}</span>
        </div>
        {messages.length > 0 && (
          <button className="w-link" onClick={startOver} disabled={sending}>
            New chat
          </button>
        )}
        {!PREVIEW && (
          <button className="w-icon" onClick={() => setOpen(false)} aria-label="Close chat">
            <CloseIcon />
          </button>
        )}
      </header>

      <div className="w-messages" ref={scrollRef}>
        <div className="w-msg assistant">
          <div className="w-bubble-text">
            <p>{cfg.greeting}</p>
          </div>
        </div>
        {messages.map((m, i) => (
          <div key={m.id ?? i} className={`w-msg ${m.role}`}>
            <div className="w-bubble-text">
              {m.role === "assistant" ? (
                m.pending && !m.content ? (
                  <span className="w-typing">
                    <i />
                    <i />
                    <i />
                  </span>
                ) : (
                  <>
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                      {linkCitations(m.content, m.sources)}
                    </ReactMarkdown>
                    {!m.pending && <Sources sources={m.sources} />}
                    {!AS_PREVIEW && <Rate m={m} onRate={rate} />}
                    {!AS_PREVIEW && !m.pending && m.grounded === false && (contactedId ? contactedId === m.id : m === lastMissed) && (
                      <Handoff onSent={() => setContactedId(m.id)} />
                    )}
                  </>
                )
              ) : (
                <p>{m.content}</p>
              )}
            </div>
          </div>
        ))}
        {suggestions.length > 0 && (
          <div className="w-suggestions">
            {suggestions.map((q) => (
              <button key={q} className="w-suggestion" disabled={sending} onClick={() => send(q)}>
                {q}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && <div className="w-error">{error}</div>}
      <form
        className="w-composer"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <textarea
          ref={inputRef}
          rows={1}
          value={input}
          maxLength={1000}
          placeholder="Ask a question…"
          aria-label="Your question"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button className="w-send" disabled={sending || !input.trim()} aria-label="Send">
          <SendIcon />
        </button>
      </form>
      <footer className="w-foot">
        <span>Chats are saved to help improve this assistant.</span>
        <a href={location.origin} target="_blank" rel="noreferrer">
          Powered by SiteBot
        </a>
      </footer>
    </div>
  );
}
