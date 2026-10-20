import { plural, timeAgo } from "./api.js";
import { ExternalIcon, InfoIcon } from "./Icons.jsx";

/** ⓘ button that shows a bot's site link, pages read and last indexed time on hover or focus. */
export default function BotInfo({ site, align = "right" }) {
  return (
    <span className="info-wrap" onClick={(e) => e.stopPropagation()}>
      <span className="icon-btn" tabIndex={0} role="button" aria-label={`About the ${site.name} Chatbot`} aria-describedby={`info-${site.id}`}>
        <InfoIcon />
      </span>
      <span className={`info-pop ${align}`} role="tooltip" id={`info-${site.id}`}>
        <a href={site.root_url} target="_blank" rel="noreferrer" className="info-link">
          {site.domain} <ExternalIcon />
        </a>
        <span className="info-row">
          <span>Pages read</span>
          <strong>{plural(site.live_pages || site.pages_indexed, "page")}</strong>
        </span>
        <span className="info-row">
          <span>Last indexed</span>
          <strong>{timeAgo(site.indexed_at) || "—"}</strong>
        </span>
      </span>
    </span>
  );
}
