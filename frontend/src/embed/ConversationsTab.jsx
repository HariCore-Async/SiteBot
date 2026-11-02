// Website chatbot > Conversations: visitor chats with filters, export, and each conversation's messages.
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, plural, timeAgo } from "../api.js";
import { Pager, useFitPageSize } from "../BotsPage.jsx";
import { linkCitations, mdComponents, Sources } from "../answer.jsx";

// ---------- Conversations ----------

export function ConversationsTab({ embed, onTeach }) {
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
