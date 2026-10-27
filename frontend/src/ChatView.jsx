import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useConfirm } from "./Confirm.jsx";
import { api, streamAnswer, timeAgo } from "./api.js";
import { BotIcon } from "./Sidebar.jsx";
import { CloseIcon, RefreshIcon, SendIcon } from "./Icons.jsx";
import BotInfo from "./BotInfo.jsx";
import ReadAllBanner from "./ReadAll.jsx";
import StopButton from "./StopButton.jsx";
import { linkCitations, mdComponents, Sources } from "./answer.jsx";

export default function ChatView({ site, me, chatId, onChatCreated, onAnswered, onClose, onSiteChanged }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [confirmAsk, confirmDialog] = useConfirm();
  const [suggestions, setSuggestions] = useState([]);
  const [updatedNote, setUpdatedNote] = useState("");
  const seenIndexedAt = useRef(site.indexed_at);

  // When a re-index finishes while this chat is open, the new version is already live; say so.
  useEffect(() => {
    if (seenIndexedAt.current && site.indexed_at && site.indexed_at !== seenIndexedAt.current) {
      const n = site.live_pages || site.pages_indexed;
      setUpdatedNote(`This chatbot has just been updated. It now knows ${n} page${n === 1 ? "" : "s"} from ${site.domain}.`);
    }
    seenIndexedAt.current = site.indexed_at;
  }, [site.indexed_at, site.live_pages, site.pages_indexed, site.domain]);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const createdChatRef = useRef(null);

  useEffect(() => {
    // A chat we just created already has its messages in state; don't reload over the stream.
    if (!chatId || createdChatRef.current === chatId) return;
    api.get(`/api/chats/${chatId}/messages`).then(setMessages).catch((e) => setError(e.message));
  }, [chatId]);

  useEffect(() => {
    api
      .get(`/api/sites/${site.id}/suggestions`)
      .then((d) => setSuggestions(d.questions || []))
      .catch(() => setSuggestions([]));
  }, [site.id, site.indexed_at]);

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

  const asked = new Set(messages.filter((m) => m.role === "user").map((m) => m.content.trim().toLowerCase()));
  const remaining = suggestions.filter((q) => !asked.has(q.toLowerCase())).slice(0, messages.length ? 3 : 6);

  const startFresh = async () => {
    const ok = await confirmAsk({
      title: "Start a fresh chat?",
      message: "This clears the current conversation. You can't undo this.",
      confirmLabel: "Start fresh",
      danger: true,
    });
    if (!ok) return;
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
        </div>
        <BotInfo site={site} />
        {chatId && messages.length > 0 && (
          <button className="btn ghost small" onClick={startFresh} disabled={sending}>
            <RefreshIcon /> <span className="fresh-label">Start fresh chat</span>
          </button>
        )}
        {onClose && (
          <button className="icon-btn" onClick={onClose} title="Close this chat (your conversation is kept)" aria-label={`Close chat with ${site.name}`}>
            <CloseIcon />
          </button>
        )}
      </header>

      {site.ready && site.running && (
        <div className="update-note" role="status">
          <span className="spinner" />
          <span className="update-text">
            Updating this chatbot in the background. You can keep chatting; answers use the current version until the update is ready.
          </span>
          {me && <StopButton site={site} me={me} onStopped={onSiteChanged} className="link-btn" />}
        </div>
      )}
      {updatedNote && (
        <div className="update-note done" role="status">
          {updatedNote}
          <button className="link-btn" onClick={() => setUpdatedNote("")}>
            Dismiss
          </button>
        </div>
      )}
      <ReadAllBanner site={site} onStarted={onSiteChanged} />
      <div className="messages" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="empty">
            <BotIcon site={site} size={56} />
            <h3>Hi, welcome to {site.name}!</h3>
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
      <div className="composer-wrap">
      {remaining.length > 0 && (
        <div className={`suggestions ${messages.length === 0 ? "intro" : ""}`} aria-label="Suggested questions">
          {remaining.map((q) => (
            <button key={q} type="button" className="suggestion" disabled={sending} onClick={() => send(q)}>
              {q}
            </button>
          ))}
        </div>
      )}
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
          <SendIcon />
        </button>
      </form>
      <p className="composer-note">Answers come only from {site.domain}.</p>
      </div>
      {confirmDialog}
    </div>
  );
}
