import { useState } from "react";
import { api } from "./api.js";
import { useConfirm } from "./Confirm.jsx";

/** Stops a running index. Shown to the person who added the bot and to admins. */
export default function StopButton({ site, me, onStopped, className = "btn small" }) {
  const [confirmAsk, confirmDialog] = useConfirm();
  const [busy, setBusy] = useState(false);
  if (!site.running || !(me.role === "admin" || site.created_by === me.id)) return null;
  const updating = site.ready;
  const stop = async () => {
    const ok = await confirmAsk({
      title: updating ? "Stop updating this chatbot?" : "Stop indexing this website?",
      message: updating
        ? "The update will be discarded and the chatbot keeps its current version."
        : "The chatbot will keep the pages read so far, and you can read the rest later. If nothing has been read yet, it will be removed.",
      confirmLabel: "Stop",
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api.post(`/api/sites/${site.id}/stop`);
      onStopped?.();
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button className={className} onClick={stop} disabled={busy}>
        {busy ? "Stopping…" : updating ? "Stop update" : "Stop indexing"}
      </button>
      {confirmDialog}
    </>
  );
}
