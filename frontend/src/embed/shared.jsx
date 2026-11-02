// Small pieces used by several website chatbot tabs.
import { useState } from "react";
import { timeAgo } from "../api.js";

export function CopyBox({ text, label = "Copy" }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="snippet">
      <code>{text}</code>
      <button
        className="btn small"
        onClick={() =>
          navigator.clipboard.writeText(text).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          })
        }
      >
        {copied ? "Copied ✓" : label}
      </button>
    </div>
  );
}

/** "Check installation": the last time a website loaded this bot (recorded by the widget and sitebot-client.js). */
export function InstallCheck({ embed, compact = false }) {
  const seen = embed.last_seen;
  if (compact) {
    return seen ? (
      <span className="install-state ok">Installed on {seen.origin.replace(/^https?:\/\//, "")}</span>
    ) : (
      <span className="install-state">Not detected yet</span>
    );
  }
  return (
    <div className={`install-check ${seen ? "ok" : ""}`} role="status">
      <strong>{seen ? "Installed" : "Not detected yet"}</strong>
      <span className="muted small">
        {seen
          ? `Last seen on ${seen.origin.replace(/^https?:\/\//, "")} ${timeAgo(seen.at)}.`
          : embed.status === "approved"
            ? "Once the snippet is on your website, this updates the first time someone opens a page with it."
            : "This updates once the chatbot is approved and someone opens a page with the snippet."}
      </span>
    </div>
  );
}
