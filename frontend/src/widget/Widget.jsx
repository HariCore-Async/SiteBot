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
const query = `origin=${encodeURIComponent(ORIGIN)}${PREVIEW ? "&preview=true" : ""}`;

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

const ChatIcon = () => (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z" />
  </svg>
);
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
  const [open, setOpen] = useState(PREVIEW);
  const [messages, setMessages] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    api
      .get(`/api/public/${encodeURIComponent(KEY)}/config?${query}`)
      .then(setCfg)
      .catch((e) => {
        setUnavailable(e.message);
        tellParent({ hidden: true });
      });
  }, []);

  useEffect(() => {
    if (cfg) tellParent({ open, position: cfg.position });
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
    return PREVIEW && unavailable ? <div className="w-unavailable">{unavailable}</div> : null;
  }

  const style = { "--w-accent": cfg.color, "--w-on-accent": onAccent(cfg.color) };

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
        { visitor_id: visitorId(), content, origin: ORIGIN, preview: PREVIEW },
        (ev) => {
          if (ev.type === "token") patchLast((last) => ({ ...last, content: last.content + ev.text }));
          else if (ev.type === "replace") patchLast((last) => ({ ...last, content: ev.text }));
          else if (ev.type === "done") patchLast((last) => ({ ...last, pending: false, sources: ev.sources, grounded: ev.grounded }));
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
    setMessages([]);
    setError("");
    inputRef.current?.focus();
  };

  if (!open) {
    return (
      <div className={`w-launcher ${cfg.position}`} style={style}>
        <button className="w-bubble" onClick={() => setOpen(true)} aria-label={`Chat with ${cfg.name}`} title={`Chat with ${cfg.name}`}>
          <ChatIcon />
        </button>
      </div>
    );
  }

  const asked = new Set(messages.filter((m) => m.role === "user").map((m) => m.content.trim().toLowerCase()));
  const suggestions = messages.length ? [] : (cfg.suggestions || []).filter((q) => !asked.has(q.toLowerCase()));

  return (
    <div className={`w-panel ${PREVIEW ? "preview" : ""}`} style={style} role="dialog" aria-label={`${cfg.name} assistant`}>
      <header className="w-head">
        <Avatar cfg={cfg} />
        <div className="w-head-meta">
          <strong>{cfg.name}</strong>
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
