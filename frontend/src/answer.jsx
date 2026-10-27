// How a bot's answer is shown: Markdown with [n] citation pills and the list of source pages.
// Shared by the app's chat and the website widget.

/** Turns [n] markers into links to the cited page so they render as citation pills. */
export function linkCitations(text, sources) {
  const byN = Object.fromEntries((sources || []).map((s) => [s.n, s.url]));
  return text.replace(/\[(\d+)\](?!\()/g, (m, n) => (byN[n] ? `[${n}](${byN[n]} "cite")` : ""));
}

function hostPath(url) {
  try {
    const u = new URL(url);
    return u.pathname === "/" ? u.hostname : u.pathname;
  } catch {
    return url;
  }
}

export function Sources({ sources }) {
  const unique = [];
  const seen = new Set();
  for (const s of sources || []) {
    if (!seen.has(s.url)) {
      seen.add(s.url);
      unique.push(s);
    }
  }
  if (!unique.length) return null;
  return (
    <div className="sources">
      <span className="sources-label">Sources</span>
      {unique.map((s) => (
        <a key={s.url} className="source-chip" href={s.url} target="_blank" rel="noreferrer" title={s.url}>
          <span className="source-n">{s.n}</span>
          <span className="source-title">{s.title && s.title !== s.url ? s.title : hostPath(s.url)}</span>
        </a>
      ))}
    </div>
  );
}

export const mdComponents = {
  a: ({ href, title, children }) =>
    title === "cite" ? (
      <a className="cite" href={href} target="_blank" rel="noreferrer" title={href}>
        {children}
      </a>
    ) : (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    ),
};
