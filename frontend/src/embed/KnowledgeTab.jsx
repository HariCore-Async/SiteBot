// Website chatbot > Knowledge: answers and documents the owner teaches the bot.
import { useCallback, useEffect, useState } from "react";
import { useConfirm } from "../Confirm.jsx";
import { api, plural, timeAgo } from "../api.js";
import { PlusIcon } from "../Icons.jsx";

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

export function KnowledgeTab({ embed, prefill, onPrefillUsed }) {
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
