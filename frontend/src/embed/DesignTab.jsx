// Website chatbot > Design: look and greeting, with a live preview of the widget.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const draftOf = (e) => ({ color: e.color, position: e.position, greeting: e.greeting, style: { ...e.style } });

// ---------- Design ----------

export function DesignTab({ embed, onChanged, onDirty }) {
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
