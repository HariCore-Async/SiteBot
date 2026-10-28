import { useCallback, useEffect, useState } from "react";
import { useConfirm } from "./Confirm.jsx";
import { api } from "./api.js";

// Admin console > AI providers: connect AI services, list their models and prices, and choose which model answers.

const NEEDS_URL = new Set(["azure", "openai_compatible"]);

/** Every model that can be picked, as [ref, label]. */
export function modelChoices(data) {
  if (!data) return [];
  const env = data.env.models.map((m) => [m.ref, `OpenRouter (environment) · ${m.model}`]);
  const added = data.providers.flatMap((p) =>
    p.enabled && (p.has_key || p.kind === "openai_compatible")
      ? p.models.filter((m) => m.enabled).map((m) => [m.ref, `${p.name} · ${m.label || m.model}`])
      : []
  );
  return [...env, ...added];
}

function TestButton({ refId }) {
  const [state, setState] = useState(null);
  return (
    <span className="test-result">
      <button
        className="btn ghost small"
        disabled={state === "testing"}
        onClick={async () => {
          setState("testing");
          try {
            setState(await api.post("/api/admin/ai/test", { ref: refId }));
          } catch (e) {
            setState({ ok: false, error: e.message });
          }
        }}
      >
        {state === "testing" ? "Testing…" : "Test connection"}
      </button>
      {state && state !== "testing" && (
        <span className={`small ${state.ok ? "ok-text" : "error-text"}`} role="status">
          {state.ok ? `Works (${state.ms} ms): "${state.reply}"` : state.error}
        </span>
      )}
    </span>
  );
}

function Defaults({ data, onSaved }) {
  const choices = modelChoices(data);
  const [answer, setAnswer] = useState(data.defaults.answer);
  const [fast, setFast] = useState(data.defaults.fast);
  const [fallbacks, setFallbacks] = useState(data.defaults.fallbacks);
  const [adding, setAdding] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const label = (ref) => choices.find(([r]) => r === ref)?.[1] || `${ref} (not available)`;
  const move = (i, d) => setFallbacks((f) => {
    const next = [...f];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    return next;
  });

  const save = async () => {
    setError("");
    try {
      onSaved(await api.put("/api/admin/ai/defaults", { answer, fast, fallbacks }));
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <section className="way ai-defaults">
      <strong>Which model answers</strong>
      <p className="muted small">The default for every bot (Admin console &gt; Bots can choose a different one per bot). If a model fails, the fallbacks are tried in order.</p>
      <div className="embed-fields">
        <label className="field">
          <span>Answers</span>
          <select value={answer} onChange={(e) => setAnswer(e.target.value)}>
            {choices.map(([r, l]) => (
              <option key={r} value={r}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Fast tasks (rewriting, checking, suggestions)</span>
          <select value={fast} onChange={(e) => setFast(e.target.value)}>
            {choices.map(([r, l]) => (
              <option key={r} value={r}>
                {l}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="field">
        <span>Fallbacks, in order</span>
        {fallbacks.length === 0 && <p className="muted small">None: if the model fails, the visitor sees a "try again" message.</p>}
        <ol className="fallbacks">
          {fallbacks.map((ref, i) => (
            <li key={ref}>
              <span>{label(ref)}</span>
              <button className="icon-btn" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move ${label(ref)} up`}>
                ↑
              </button>
              <button className="icon-btn" disabled={i === fallbacks.length - 1} onClick={() => move(i, 1)} aria-label={`Move ${label(ref)} down`}>
                ↓
              </button>
              <button className="link-btn" onClick={() => setFallbacks((f) => f.filter((x) => x !== ref))}>
                Remove
              </button>
            </li>
          ))}
        </ol>
        <div className="inline-form">
          <select value={adding} onChange={(e) => setAdding(e.target.value)} aria-label="Add a fallback model">
            <option value="">Add a fallback…</option>
            {choices
              .filter(([r]) => !fallbacks.includes(r))
              .map(([r, l]) => (
                <option key={r} value={r}>
                  {l}
                </option>
              ))}
          </select>
          <button
            className="btn small"
            disabled={!adding}
            onClick={() => {
              setFallbacks((f) => [...f, adding]);
              setAdding("");
            }}
          >
            Add
          </button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="embed-actions">
        <button className="btn primary small" onClick={save}>
          {saved ? "Saved ✓" : "Save"}
        </button>
      </div>
    </section>
  );
}

function AddModel({ provider, onSaved }) {
  const [form, setForm] = useState({ model: "", label: "", input_per_m: "", output_per_m: "" });
  const [error, setError] = useState("");
  const isAzure = provider.kind === "azure";
  return (
    <form
      className="add-model"
      onSubmit={async (e) => {
        e.preventDefault();
        setError("");
        try {
          onSaved(
            await api.post(`/api/admin/ai/providers/${provider.id}/models`, {
              ...form,
              input_per_m: Number(form.input_per_m || 0),
              output_per_m: Number(form.output_per_m || 0),
            })
          );
          setForm({ model: "", label: "", input_per_m: "", output_per_m: "" });
        } catch (err) {
          setError(err.message);
        }
      }}
    >
      <input required placeholder={isAzure ? "Deployment name" : "Model ID, e.g. gpt-4o-mini"} aria-label="Model ID" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
      <input placeholder="Label (optional)" aria-label="Label" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
      <input type="number" min="0" step="0.001" placeholder="$ in / 1M" aria-label="Input price per million tokens" value={form.input_per_m} onChange={(e) => setForm({ ...form, input_per_m: e.target.value })} />
      <input type="number" min="0" step="0.001" placeholder="$ out / 1M" aria-label="Output price per million tokens" value={form.output_per_m} onChange={(e) => setForm({ ...form, output_per_m: e.target.value })} />
      <button className="btn small">Add model</button>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

function Provider({ p, onSaved }) {
  const [confirmAsk, confirmDialog] = useConfirm();
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const act = async (fn) => {
    setError("");
    try {
      onSaved(await fn());
    } catch (e) {
      setError(e.message);
    }
  };
  return (
    <section className="way provider">
      <div className="provider-head">
        <div>
          <strong>{p.name}</strong>
          <div className="muted small">
            {p.kind_label}
            {p.base_url ? ` · ${p.base_url}` : ""}
            {p.api_version ? ` · API ${p.api_version}` : ""}
          </div>
        </div>
        <span className={`small ${p.has_key ? "" : "warn-text"}`}>{p.has_key ? `Key ••••${p.key_hint}` : "No API key"}</span>
        <button
          role="switch"
          aria-checked={p.enabled}
          aria-label={`Use ${p.name}`}
          className={`switch ${p.enabled ? "on" : ""}`}
          onClick={() => act(() => api.patch(`/api/admin/ai/providers/${p.id}`, { enabled: !p.enabled }))}
        >
          <span />
        </button>
      </div>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          act(() => api.patch(`/api/admin/ai/providers/${p.id}`, { api_key: key })).then(() => setKey(""));
        }}
      >
        <input type="password" autoComplete="off" placeholder={p.has_key ? "Replace the API key" : "Paste the API key"} aria-label={`API key for ${p.name}`} value={key} onChange={(e) => setKey(e.target.value)} />
        <button className="btn small" disabled={!key.trim()}>
          Save key
        </button>
      </form>
      {p.models.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>$ / 1M in</th>
                <th>$ / 1M out</th>
                <th>On</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {p.models.map((m) => (
                <tr key={m.id}>
                  <td>
                    <div className="strong">{m.label || m.model}</div>
                    {m.label && <div className="muted small">{m.model}</div>}
                  </td>
                  <td>{m.input_per_m}</td>
                  <td>{m.output_per_m}</td>
                  <td>
                    <button
                      role="switch"
                      aria-checked={m.enabled}
                      aria-label={`Use model ${m.model}`}
                      className={`switch ${m.enabled ? "on" : ""}`}
                      onClick={() => act(() => api.patch(`/api/admin/ai/models/${m.id}`, { enabled: !m.enabled }))}
                    >
                      <span />
                    </button>
                  </td>
                  <td className="actions">
                    <TestButton refId={m.ref} />
                    <button className="btn ghost small danger" onClick={() => act(() => api.del(`/api/admin/ai/models/${m.id}`))}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <AddModel provider={p} onSaved={onSaved} />
      {error && <p className="error">{error}</p>}
      <div>
        <button
          className="btn ghost small danger"
          onClick={async () => {
            const ok = await confirmAsk({
              title: `Remove ${p.name}?`,
              message: "Its models and saved key are deleted. Bots using them go back to the default model.",
              confirmLabel: "Remove provider",
              danger: true,
            });
            if (ok) act(() => api.del(`/api/admin/ai/providers/${p.id}`));
          }}
        >
          Remove provider
        </button>
      </div>
      {confirmDialog}
    </section>
  );
}

function AddProvider({ kinds, onSaved }) {
  const [form, setForm] = useState({ kind: "openai", name: "", base_url: "", api_key: "", api_version: "" });
  const [error, setError] = useState("");
  const kind = kinds.find((k) => k.kind === form.kind);
  return (
    <form
      className="way add-provider"
      onSubmit={async (e) => {
        e.preventDefault();
        setError("");
        try {
          onSaved(await api.post("/api/admin/ai/providers", { ...form, name: form.name || kind.label }));
          setForm({ kind: form.kind, name: "", base_url: "", api_key: "", api_version: "" });
        } catch (err) {
          setError(err.message);
        }
      }}
    >
      <strong>Add a provider</strong>
      <div className="embed-fields">
        <label className="field">
          <span>Service</span>
          <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {kinds.map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Name</span>
          <input placeholder={kind?.label} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </label>
      </div>
      <div className="embed-fields">
        <label className="field">
          <span>Base URL {NEEDS_URL.has(form.kind) ? "(required)" : "(optional)"}</span>
          <input
            required={NEEDS_URL.has(form.kind)}
            placeholder={form.kind === "azure" ? "https://<resource>.openai.azure.com" : form.kind === "openai_compatible" ? "http://localhost:11434/v1" : kind?.base_url}
            value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
          />
        </label>
        {form.kind === "azure" && (
          <label className="field">
            <span>API version</span>
            <input placeholder="2024-10-21" value={form.api_version} onChange={(e) => setForm({ ...form, api_version: e.target.value })} />
          </label>
        )}
      </div>
      <label className="field">
        <span>API key {form.kind === "openai_compatible" ? "(if your server needs one)" : ""}</span>
        <input type="password" autoComplete="off" placeholder="Saved encrypted; never shown again" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
      </label>
      {error && <p className="error">{error}</p>}
      <div>
        <button className="btn primary small">Add provider</button>
      </div>
    </form>
  );
}

export default function AIProviders() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.get("/api/admin/ai").then(setData).catch((e) => setError(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);
  if (!data) return error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>;
  return (
    <div className="ai-providers">
      {/* Re-read the saved defaults when the available models change (e.g. a provider was removed), not on every save. */}
      <Defaults key={modelChoices(data).map(([r]) => r).join()} data={data} onSaved={setData} />
      {data.env.available && (
        <section className="way provider">
          <div className="provider-head">
            <div>
              <strong>OpenRouter (environment)</strong>
              <div className="muted small">From OPENROUTER_API_KEY, OPENROUTER_MODEL and OPENROUTER_FAST_MODEL on the server. Change them in Railway's variables.</div>
            </div>
          </div>
          {data.env.models.map((m) => (
            <div key={m.ref} className="key-row">
              <span className="small">{m.label}</span>
              <TestButton refId={m.ref} />
            </div>
          ))}
        </section>
      )}
      {data.providers.map((p) => (
        <Provider key={p.id} p={p} onSaved={setData} />
      ))}
      <AddProvider kinds={data.kinds} onSaved={setData} />
    </div>
  );
}
