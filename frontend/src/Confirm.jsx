import { useCallback, useEffect, useRef, useState } from "react";

function ConfirmDialog({ title, message, confirmLabel = "Confirm", danger = false, onConfirm, onCancel }) {
  const confirmRef = useRef(null);

  useEffect(() => {
    confirmRef.current?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" onClick={(e) => e.stopPropagation()}>
        <h3 id="confirm-title">{title}</h3>
        {message && <p className="muted">{message}</p>}
        <div className="modal-actions">
          <button className="btn ghost" onClick={onCancel}>
            Cancel
          </button>
          <button ref={confirmRef} className={`btn ${danger ? "danger-solid" : "primary"}`} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** In-app replacement for window.confirm. Returns [ask, dialog]; render `dialog` and `await ask({...})`. */
export function useConfirm() {
  const [request, setRequest] = useState(null);
  const ask = useCallback((options) => new Promise((resolve) => setRequest({ ...options, resolve })), []);
  const close = useCallback(
    (value) => {
      request?.resolve(value);
      setRequest(null);
    },
    [request]
  );
  const cancel = useCallback(() => close(false), [close]);
  const dialog = request ? <ConfirmDialog {...request} onConfirm={() => close(true)} onCancel={cancel} /> : null;
  return [ask, dialog];
}
