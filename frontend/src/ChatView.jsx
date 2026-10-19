import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, streamAnswer, timeAgo } from "./api.js";
import { BotIcon } from "./Sidebar.jsx";

/** Turns [n] markers into links to the cited page so they render as citation pills. */
function linkCitations(text, sources) {
  const byN = Object.fromEntries((sources || []).map((s) => [s.n, s.url]));
  return text.replace(/\[(\d+)\](?!\()/g, (m, n) => (byN[n] ? `[${n}](${byN[n]} "cite")` : ""));
}

function hostPath(url) {
  try {
    const u = new URL(url);
    return u.pathname === "/" ? u.hostname : u.pathname;
  } catch {
    return url;
  }
}

function Sources({ sources }) {
  const unique = [];
  const seen = new Set();
  for (const s of sources || []) {
    if (!seen.has(s.url)) {
      seen.add(s.url);
      unique.push(s);
    }
  }
  if (!unique.length) return null;
  return (
    <div className="sources">
      <span className="sources-label">Sources</span>
      {unique.map((s) => (
        <a key={s.url} className="source-chip" href={s.url} target="_blank" rel="noreferrer" title={s.url}>
          <span className="source-n">{s.n}</span>
          <span className="source-title">{s.title && s.title !== s.url ? s.title : hostPath(s.url)}</span>
        </a>
      ))}
    </div>
  );
}

const mdComponents = {
  a: ({ href, title, children }) =>
    title === "cite" ? (
      <a className="cite" href={href} target="_blank" rel="noreferrer" title={href}>
        {children}
      </a>
    ) : (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    ),
};

function PagesDrawer({ site, onClose }) {
  const [pages, setPages] = useState(null);
  useEffect(() => {
    api.get(`/api/sites/${site.id}/pages`).then(setPages).catch(() => setPages([]));
  }, [site.id]);
  const indexed = (pages || []).filter((p) => p.status === "indexed");
  const skipped = (pages || []).filter((p) => p.status === "login" || p.status === "blocked");
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <h3>Pages this bot knows</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        {!pages ? (
          <p className="muted">Loading…</p>
        ) : (
          <>
            <p className="muted small">
              {indexed.length} pages indexed{skipped.length ? ` · ${skipped.length} skipped (login or blocked)` : ""}
            </p>
            <ul className="page-list">
              {indexed.map((p) => (
                <li key={p.url}>
                  <a href={p.url} target="_blank" rel="noreferrer">
                    {p.title || p.url}
                  </a>
                  <span className="muted small">{hostPath(p.url)}</span>
                </li>
              ))}
              {skipped.map((p) => (
                <li key={p.url} className="skipped">
                  <span>{hostPath(p.url)}</span>
                  <span className={`status ${p.status}`}>{p.status === "login" ? "needs login" : "blocked"}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}

export default function ChatView({ site, chatId, onChatCreated, onAnswered }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [showPages, setShowPages] = useState(false);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const createdChatRef = useRef(null);

  useEffect(() => {
    // A chat we just created already has its messages in state; don't reload over the stream.
    if (!chatId || createdChatRef.current === chatId) return;
    api.get(`/api/chats/${chatId}/messages`).then(setMessages).catch((e) => setError(e.message));
  }, [chatId]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(() => inputRef.current?.focus(), []);

  const send = async (text) => {
    const content = (text ?? input).trim();
    if (!content || sending) return;
    setError("");
    setInput("");
    setSending(true);
    setMessages((m) => [...m, { role: "user", content }, { role: "assistant", content: "", pending: true, sources: [] }]);
    const patchLast = (fn) => setMessages((m) => [...m.slice(0, -1), fn(m[m.length - 1])]);

    let id = chatId;
    try {
      if (!id) {
        id = (await api.post("/api/chats", { site_id: site.id })).id;
        createdChatRef.current = id;
      }
      await streamAnswer(id, content, (ev) => {
        if (ev.type === "token") patchLast((last) => ({ ...last, content: last.content + ev.text }));
        else if (ev.type === "replace") patchLast((last) => ({ ...last, content: ev.text }));
        else if (ev.type === "done") {
          patchLast((last) => ({ ...last, pending: false, sources: ev.sources, grounded: ev.grounded }));
          onAnswered(ev.usage);
        } else if (ev.type === "error") {
          setMessages((m) => m.filter((x) => !x.pending));
          setError(ev.message);
        }
      });
    } catch (e) {
      setMessages((m) => m.filter((x) => !x.pending));
      setError(e.message || "Couldn't send your message.");
    } finally {
      setSending(false);
      if (id && id !== chatId) onChatCreated(id);
      inputRef.current?.focus();
    }
  };

  const startFresh = async () => {
    if (!confirm("Start a fresh chat? This clears the current conversation.")) return;
    try {
      await api.post(`/api/chats/${chatId}/reset`);
      setMessages([]);
      setError("");
      onAnswered();
      inputRef.current?.focus();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="chat">
      <header className="chat-head">
        <BotIcon site={site} size={34} />
        <div className="chat-head-meta">
          <h2>{site.name} Chatbot</h2>
          <div className="muted small">
            <a href={site.root_url} target="_blank" rel="noreferrer">
              {site.domain}
            </a>{" "}
            · {site.pages_indexed} pages · indexed {timeAgo(site.indexed_at)}
          </div>
        </div>
        {chatId && messages.length > 0 && (
          <button className="btn ghost small" onClick={startFresh} disabled={sending}>
            Start fresh chat
          </button>
        )}
        <button className="btn ghost small" onClick={() => setShowPages(true)}>
          Pages
        </button>
      </header>

      <div className="messages" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="empty">
            <BotIcon site={site} size={56} />
            <h3>Ask {site.name} anything</h3>
            <p className="muted">
              I answer only from {site.domain}'s public pages and show my sources. If something isn't on the site, I'll say so instead of
              guessing.
            </p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={m.id ?? i} className={`msg ${m.role} ${m.grounded === false ? "ungrounded" : ""}`}>
            {m.role === "assistant" && <BotIcon site={site} size={26} />}
            <div className="bubble">
              {m.role === "assistant" ? (
                m.pending && !m.content ? (
                  <span className="typing">
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
      </div>

      {error && <div className="chat-error">{error}</div>}
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <textarea
          ref={inputRef}
          rows={1}
          value={input}
          placeholder={`Ask about ${site.name}…`}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          maxLength={2000}
        />
        <button className="btn primary send" disabled={sending || !input.trim()} aria-label="Send">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </button>
      </form>
      {showPages && <PagesDrawer site={site} onClose={() => setShowPages(false)} />}
    </div>
  );
}
