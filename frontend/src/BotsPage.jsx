import { useEffect, useLayoutEffect, useRef, useState } from "react";
import BotInfo from "./BotInfo.jsx";
import { useConfirm } from "./Confirm.jsx";
import { BotIcon } from "./Sidebar.jsx";
import { SearchIcon, TrashIcon } from "./Icons.jsx";

const STATUS_LABEL = { queued: "Queued", crawling: "Reading", embedding: "Learning", failed: "Failed" };

/** How many cards fit on screen without scrolling: the grid's columns times the rows that fit below its top edge. */
export function useFitPageSize(gridRef, reserve, deps) {
  const [size, setSize] = useState(12);
  useLayoutEffect(() => {
    const measure = () => {
      const grid = gridRef.current;
      if (!grid) return;
      const css = getComputedStyle(grid);
      const cols = css.gridTemplateColumns.split(" ").filter(Boolean).length || 1;
      const gap = parseFloat(css.rowGap) || 0;
      const rowHeight = (grid.firstElementChild?.offsetHeight || 64) + gap;
      const available = window.innerHeight - grid.getBoundingClientRect().top - reserve;
      setSize(cols * Math.max(1, Math.floor((available + gap) / rowHeight)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(gridRef.current?.parentElement || document.body);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return size;
}

/** Page numbers 1, 2, 3 …, with gaps once there are many pages. */
export function Pager({ page, pages, onPage }) {
  if (pages <= 1) return <div className="pager" />;
  const shown = [...new Set([1, page - 1, page, page + 1, pages].filter((n) => n >= 1 && n <= pages))].sort((a, b) => a - b);
  const items = [];
  shown.forEach((n, i) => {
    if (i && n - shown[i - 1] > 1) items.push(<span key={`gap-${n}`} className="pager-gap">…</span>);
    items.push(
      <button key={n} className={`pager-btn ${n === page ? "active" : ""}`} aria-current={n === page ? "page" : undefined} onClick={() => onPage(n)}>
        {n}
      </button>
    );
  });
  return (
    <nav className="pager" aria-label="Pages">
      <button className="pager-btn" disabled={page === 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
        ‹
      </button>
      {items}
      <button className="pager-btn" disabled={page === pages} onClick={() => onPage(page + 1)} aria-label="Next page">
        ›
      </button>
    </nav>
  );
}

function BotCard({ site, onOpen, onRemove }) {
  const busy = !site.ready && site.status !== "failed";
  return (
    <div className="bot-card" role="button" tabIndex={0} onClick={() => onOpen(site)} onKeyDown={(e) => e.key === "Enter" && onOpen(site)}>
      <BotIcon site={site} size={32} />
      <div className="bot-name">
        {site.name} Chatbot
        {!site.ready && <div className={`status ${site.status}`}>{STATUS_LABEL[site.status] || site.status}</div>}
      </div>
      {busy ? <span className="spinner" /> : <BotInfo site={site} />}
      {onRemove && (
        <button
          className="icon-btn card-remove"
          title="Remove from your list"
          aria-label={`Remove ${site.name} Chatbot from your list`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove(site);
          }}
        >
          <TrashIcon />
        </button>
      )}
    </div>
  );
}

export default function BotsPage({ mine, library, onOpen, onRemove }) {
  const [tab, setTab] = useState(mine.length ? "mine" : "library");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [confirmAsk, confirmDialog] = useConfirm();
  const gridRef = useRef(null);

  const list = tab === "mine" ? mine : library;
  const q = query.trim().toLowerCase();
  const shown = q ? list.filter((s) => `${s.name} ${s.domain}`.toLowerCase().includes(q)) : list;
  // Room under the grid for the page numbers and the page's bottom padding.
  const pageSize = useFitPageSize(gridRef, 96, [tab, shown.length > 0]);
  const pages = Math.max(1, Math.ceil(shown.length / pageSize));
  const current = Math.min(page, pages);
  const visible = shown.slice((current - 1) * pageSize, current * pageSize);

  useEffect(() => setPage(1), [tab, q]);

  const remove = async (site) => {
    const ok = await confirmAsk({
      title: `Remove ${site.name} Chatbot from your list?`,
      message: "It disappears from your chatbots and your conversation with it is deleted. It stays in the Library, so you can add it back any time.",
      confirmLabel: "Remove from your list",
      danger: true,
    });
    if (ok) onRemove(site.id);
  };

  return (
    <div className="page wide bots-page">
      <div className="page-head">
        <div>
          <h1>Chat with a bot</h1>
          <p className="muted">Open one of your chatbots, or any chatbot in the Library. No need to add it first.</p>
        </div>
      </div>
      <div className="bots-toolbar">
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "mine"} className={`tab ${tab === "mine" ? "active" : ""}`} onClick={() => setTab("mine")}>
            Your chatbots <span className="count">{mine.length}</span>
          </button>
          <button role="tab" aria-selected={tab === "library"} className={`tab ${tab === "library" ? "active" : ""}`} onClick={() => setTab("library")}>
            Library <span className="count">{library.length}</span>
          </button>
        </div>
        <div className="bot-search library-search">
          <SearchIcon />
          <input
            type="search"
            placeholder={tab === "mine" ? "Search your chatbots" : "Search the library"}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search chatbots"
          />
        </div>
      </div>

      {shown.length ? (
        <div className="bot-grid" ref={gridRef}>
          {visible.map((s) => (
            <BotCard key={s.id} site={s} onOpen={onOpen} onRemove={tab === "mine" ? remove : null} />
          ))}
        </div>
      ) : (
        <p className="muted small">
          {q
            ? `No chatbots match "${query.trim()}".`
            : tab === "mine"
              ? "You don't have any chatbots yet. Create one with + New chatbot, or open one from the Library."
              : "The Library is empty. Create the first chatbot with + New chatbot."}
        </p>
      )}
      <Pager page={current} pages={pages} onPage={setPage} />
      {confirmDialog}
    </div>
  );
}
