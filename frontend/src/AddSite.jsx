import { useState } from "react";
import { api } from "./api.js";
import { useConfirm } from "./Confirm.jsx";
import ReadAllBanner from "./ReadAll.jsx";
import { BotIcon } from "./Sidebar.jsx";

function progressOf(s) {
  if (s.ready && !s.running) return 100;
  if (s.status === "embedding") return 80 + (s.chunks_total ? (s.chunks_done / s.chunks_total) * 20 : 0);
  if (s.status === "crawling") return 3 + (s.pages_found ? (s.pages_done / s.pages_found) * 77 : 0);
  return 2;
}

function Progress({ site, onChat, onRetry, onSiteChanged }) {
  const pct = Math.round(progressOf(site));
  const failed = site.status === "failed";
  const done = site.ready && !site.running;
  const phase = failed
    ? "Couldn't index this site"
    : done
      ? "Ready to chat"
      : site.status === "embedding"
        ? "Learning the content"
        : site.status === "crawling"
          ? "Reading pages"
          : "Getting started";
  return (
    <div className="progress-card">
      <div className="progress-head">
        <BotIcon site={site} size={40} />
        <div>
          <h2>{site.name} Chatbot</h2>
          <div className="muted">{site.domain}</div>
        </div>
      </div>
      <div className="progress-phase">
        <strong>{phase}</strong>
        {!failed && <span>{pct}%</span>}
      </div>
      <div className="bar big">
        <div className={`bar-fill ${failed ? "danger" : done ? "ok" : "animated"}`} style={{ width: `${failed ? 100 : pct}%` }} />
      </div>
      <p className={failed ? "error" : "muted"}>{site.message}</p>
      <div className="stats">
        <span>
          <strong>{site.pages_indexed}</strong> {site.pages_indexed === 1 ? "page" : "pages"} indexed
        </span>
        {site.pages_login > 0 && (
          <span title="Pages behind a login are skipped; SiteBot only reads public pages.">
            <strong>{site.pages_login}</strong> need login
          </span>
        )}
        {site.pages_blocked > 0 && (
          <span title="The site's bot protection refused these pages.">
            <strong>{site.pages_blocked}</strong> blocked
          </span>
        )}
        {site.pages_failed > 0 && (
          <span>
            <strong>{site.pages_failed}</strong> failed
          </span>
        )}
      </div>
      {done && <ReadAllBanner site={site} onStarted={onSiteChanged} />}
      {done && (
        <button className="btn primary" onClick={() => onChat(site.id)}>
          Start chatting →
        </button>
      )}
      {failed && (
        <button className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
      {!done && !failed && <p className="fine">You can leave this page; indexing continues in the background.</p>}
    </div>
  );
}

export default function AddSite({ sites, site, refreshSites, onOpen, onChat }) {
  const [url, setUrl] = useState("");
  const [includePdfs, setIncludePdfs] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [confirmAsk, confirmDialog] = useConfirm();

  const submit = async (e, retryUrl, confirmLarge = false) => {
    e?.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    if (!confirmLarge) setNotice("Checking the size of the website…");
    try {
      const res = await api.post("/api/sites", { url: retryUrl || url, include_pdfs: includePdfs, confirm_large: confirmLarge });
      if (res.needs_confirm) {
        setNotice("");
        setBusy(false);
        const count = res.estimated_pages.toLocaleString();
        const ok = await confirmAsk({
          title: "This is a large website",
          message:
            `It has ${res.exact ? "about" : "at least"} ${count} pages, so reading all of it will take roughly ` +
            `${res.estimated_minutes} minute${res.estimated_minutes === 1 ? "" : "s"}. You can leave while it works.` +
            (res.capped ? ` For safety, indexing stops at ${res.max_pages.toLocaleString()} pages.` : ""),
          confirmLabel: "Proceed",
        });
        if (ok) return submit(null, retryUrl || url, true);
        return;
      }
      const { site: s, existing } = res;
      await refreshSites();
      if (existing && s.ready) {
        setNotice(`${s.name} is already indexed — opening its chatbot.`);
        setTimeout(() => onChat(s.id), 700);
      } else {
        onOpen(s.id);
      }
      setUrl("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (site) {
    return (
      <div className="page center">
        <Progress site={site} onChat={onChat} onRetry={() => submit(null, site.root_url, true)} onSiteChanged={refreshSites} />
        {confirmDialog}
      </div>
    );
  }

  return (
    <div className="page">
      <div className="hero">
        <h1>Create a chatbot</h1>
        <p className="muted">Paste a website link. We'll read its public pages and build a chatbot that answers only from that site, with sources.</p>
        <form className="add-form" onSubmit={submit}>
          <input
            type="text"
            inputMode="url"
            placeholder="https://example.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
            autoFocus
          />
          <button className="btn primary" disabled={busy}>
            {busy ? "Starting…" : "Create chatbot"}
          </button>
        </form>
        <label className="check">
          <input type="checkbox" checked={includePdfs} onChange={(e) => setIncludePdfs(e.target.checked)} />
          Also read PDFs linked from the site
        </label>
        {error && <p className="error">{error}</p>}
        {notice && <p className="notice">{notice}</p>}
      </div>
      {confirmDialog}
    </div>
  );
}
