// Website chatbot > Test questions: questions it should answer (or decline), run on demand and after each re-index.
import { useCallback, useEffect, useState } from "react";
import { useConfirm } from "../Confirm.jsx";
import { api, timeAgo } from "../api.js";
import { PlusIcon } from "../Icons.jsx";

const BLANK = { question: "", expected: "", mode: "answer" };

function QuestionForm({ embedId, initial, onSaved, onCancel }) {
  const [form, setForm] = useState({ ...BLANK, ...initial });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const declines = form.mode === "not_on_site";
  return (
    <form
      className="answer-form"
      onSubmit={async (e) => {
        e.preventDefault();
        setError("");
        setBusy(true);
        try {
          const body = { question: form.question, expected: declines ? "" : form.expected, mode: form.mode };
          const base = `/api/embeds/${embedId}/evals/questions`;
          onSaved(initial?.id ? await api.put(`${base}/${initial.id}`, body) : await api.post(base, body));
        } catch (err) {
          setError(err.message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label className="field">
        <span>Question</span>
        <input required maxLength={500} placeholder="Do you ship to Canada?" value={form.question} onChange={(e) => setForm({ ...form, question: e.target.value })} />
      </label>
      <label className="check">
        <input type="checkbox" checked={declines} onChange={(e) => setForm({ ...form, mode: e.target.checked ? "not_on_site" : "answer" })} />
        The website doesn't cover this: the bot should say it doesn't know
      </label>
      {!declines && (
        <label className="field">
          <span>What a good answer says (optional)</span>
          <textarea
            rows={3}
            maxLength={2000}
            placeholder="Yes, in 5–7 working days. Leave empty if any answer with sources will do."
            value={form.expected}
            onChange={(e) => setForm({ ...form, expected: e.target.value })}
          />
        </label>
      )}
      {error && <p className="error">{error}</p>}
      <div className="embed-actions">
        <button className="btn primary small" disabled={busy}>
          {busy ? "Saving…" : initial?.id ? "Save question" : "Add question"}
        </button>
        <button type="button" className="btn ghost small" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function RunSummary({ run }) {
  const when = run.finished_at ? timeAgo(run.finished_at) : "now";
  const why = run.trigger === "reindex" ? "after the website was re-read" : "run by hand";
  if (run.status === "running") return <span className="muted small">Running… {run.done} of {run.total}</span>;
  if (run.status === "failed") return <span className="error small">{run.message || "The run failed."}</span>;
  return (
    <span className="small">
      <strong className={run.passed === run.total ? "ok-text" : "danger-text"}>
        {run.passed} of {run.total} passed
      </strong>{" "}
      <span className="muted">
        · {when}, {why}
      </span>
    </span>
  );
}

export function TestsTab({ embed }) {
  const readOnly = embed.my_role === "viewer";
  const [data, setData] = useState(null);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState("");
  const [confirmAsk, confirmDialog] = useConfirm();
  const load = useCallback(() => api.get(`/api/embeds/${embed.id}/evals`).then(setData).catch((e) => setError(e.message)), [embed.id]);
  useEffect(() => {
    load();
  }, [load]);
  // While a run goes, follow its progress.
  useEffect(() => {
    if (!data?.running) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [data?.running, load]);

  const run = async () => {
    setError("");
    try {
      await api.post(`/api/embeds/${embed.id}/evals/run`);
      await load();
    } catch (e) {
      setError(e.message);
    }
  };
  const remove = async (q) => {
    const ok = await confirmAsk({ title: "Remove this test question?", message: q.question, confirmLabel: "Remove", danger: true });
    if (!ok) return;
    await api.del(`/api/embeds/${embed.id}/evals/questions/${q.id}`);
    load();
  };

  if (!data) return error ? <p className="error">{error}</p> : <p className="muted small">Loading…</p>;
  const latest = data.latest;
  const results = Object.fromEntries((latest?.results || []).map((r) => [r.question_id, r]));
  return (
    <div className="tests-tab">
      <p className="muted">
        Questions {embed.site.name} Chatbot should answer, and what a good answer says, or ones it should decline because the website doesn't cover them.
        They run after every re-read of the website and whenever you press Run, like a visitor's questions (so they count toward the daily limit).
      </p>
      {error && <p className="error">{error}</p>}
      <section className="way">
        <div className="section-row">
          <strong>Latest run</strong>
          {!readOnly && (
            <button className="btn small primary" disabled={data.running || !data.questions.length} onClick={run}>
              {data.running ? "Running…" : "Run all"}
            </button>
          )}
        </div>
        {latest ? <RunSummary run={data.running ? { ...latest, status: "running" } : latest} /> : <p className="muted small">Not run yet.</p>}
        {latest?.message && latest.status === "done" && <p className="muted small">{latest.message}</p>}
      </section>

      <section className="way">
        <div className="section-row">
          <strong>
            Test questions{" "}
            <span className="muted small">
              {data.questions.length} of {data.max_questions}
            </span>
          </strong>
          {!adding && !readOnly && data.questions.length < data.max_questions && (
            <button className="btn small" onClick={() => setAdding(true)}>
              <PlusIcon size={14} /> Add a question
            </button>
          )}
        </div>
        {adding && (
          <QuestionForm
            embedId={embed.id}
            onCancel={() => setAdding(false)}
            onSaved={() => {
              setAdding(false);
              load();
            }}
          />
        )}
        {!data.questions.length && !adding && <p className="muted small">No test questions yet. Start with the questions your visitors ask most.</p>}
        <ul className="test-list">
          {data.questions.map((q) => {
            const r = results[q.id];
            return editing === q.id ? (
              <li key={q.id}>
                <QuestionForm
                  embedId={embed.id}
                  initial={q}
                  onCancel={() => setEditing(null)}
                  onSaved={() => {
                    setEditing(null);
                    load();
                  }}
                />
              </li>
            ) : (
              <li key={q.id} className={r ? (r.passed ? "passed" : "failed") : ""}>
                <div className="test-main">
                  <div className="strong">
                    {r && <span className={`pill ${r.passed ? "ok-pill" : "warn-pill"}`}>{r.passed ? "Pass" : "Fail"}</span>} {q.question}
                  </div>
                  <div className="muted small">{q.mode === "not_on_site" ? "Should say it doesn't know" : q.expected ? `Expected: ${q.expected}` : "Any answer with sources"}</div>
                  {r && (
                    <details className="test-result">
                      <summary className="small">{r.reason}</summary>
                      <div className="small test-answer">{r.answer || "(no answer)"}</div>
                      {r.sources.length > 0 && <div className="muted small">Sources: {r.sources.map((s) => s.title || s.url).join(", ")}</div>}
                    </details>
                  )}
                </div>
                {!readOnly && (
                  <div className="row-actions">
                    <button className="link-btn small" onClick={() => setEditing(q.id)}>
                      Edit
                    </button>
                    <button className="link-btn small danger-link" onClick={() => remove(q)}>
                      Remove
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {data.runs.length > 1 && (
        <section className="way">
          <strong>Earlier runs</strong>
          <ul className="run-history">
            {data.runs.slice(1).map((r) => (
              <li key={r.id}>
                <RunSummary run={r} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {confirmDialog}
    </div>
  );
}
