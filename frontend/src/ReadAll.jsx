import { useState } from "react";
import { api } from "./api.js";
import { useConfirm } from "./Confirm.jsx";

/** Shown when indexing stopped at the page limit: offers to read the rest of the site. */
export default function ReadAllBanner({ site, onStarted }) {
  const [confirmAsk, confirmDialog] = useConfirm();
  const [error, setError] = useState("");
  if (!site.truncated || site.running) return null;
  const start = async () => {
    const ok = await confirmAsk({
      title: "Read the whole website?",
      message:
        `So far we've read the first ${site.pages_indexed} pages of ${site.domain}. Reading everything can take a while ` +
        "on a large site. The chatbot keeps answering from what it already knows in the meantime.",
      confirmLabel: "Read whole site",
    });
    if (!ok) return;
    try {
      await api.post(`/api/sites/${site.id}/read-all`);
      onStarted?.();
    } catch (e) {
      setError(e.message);
    }
  };
  return (
    <div className="read-all">
      <span>
        {error || `This website has more pages than we've read so far (${site.pages_indexed}).`}
      </span>
      <button className="btn small" onClick={start}>
        Read whole site
      </button>
      {confirmDialog}
    </div>
  );
}
