"""Background indexing: crawl -> chunk -> embed -> swap in the new generation."""

import logging
import re
import threading

from sqlalchemy import delete

from .config import settings
from .crawler import Crawler, CrawlError, PageResult, extract_site_identity
from .db import SessionLocal
from .embeddings import embed_passages
from .models import Chunk, Page, Site, utcnow

log = logging.getLogger(__name__)

CHUNK_CHARS = 1400
OVERLAP_CHARS = 200
EMBED_BATCH = 64

_running: set[int] = set()
_running_lock = threading.Lock()
# One website is indexed at a time: each crawl runs a headless browser and the embedding model, and several at once
# can exhaust a small server's memory. Others wait their turn in the queue.
_one_at_a_time = threading.Semaphore(1)


def chunk_text(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    pieces: list[str] = []
    for p in paragraphs:
        if len(p) <= CHUNK_CHARS:
            pieces.append(p)
        else:
            pieces.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+", p) if s.strip())

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        while len(piece) > CHUNK_CHARS:  # a single huge sentence
            chunks.append(piece[:CHUNK_CHARS])
            piece = piece[CHUNK_CHARS - OVERLAP_CHARS:]
        if current and len(current) + len(piece) + 1 > CHUNK_CHARS:
            chunks.append(current)
            tail = current[-OVERLAP_CHARS:]
            current = tail[tail.find(" ") + 1:] + "\n" + piece if " " in tail else piece
        else:
            current = f"{current}\n{piece}" if current else piece
    if current.strip():
        chunks.append(current)
    return [c for c in chunks if len(c) >= 40]


def is_running(site_id: int) -> bool:
    with _running_lock:
        return site_id in _running


def start_ingestion(site_id: int) -> bool:
    with _running_lock:
        if site_id in _running:
            return False
        _running.add(site_id)
    threading.Thread(target=_run, args=(site_id,), daemon=True, name=f"ingest-{site_id}").start()
    return True


def _run(site_id: int) -> None:
    try:
        if not _one_at_a_time.acquire(blocking=False):
            db = SessionLocal()
            try:
                site = db.get(Site, site_id)
                site.status = "queued"
                site.message = "Waiting for another website to finish indexing…"
                db.commit()
            finally:
                db.close()
            _one_at_a_time.acquire()
        try:
            run_ingestion(site_id)
        finally:
            _one_at_a_time.release()
    finally:
        with _running_lock:
            _running.discard(site_id)


def run_ingestion(site_id: int) -> None:
    db = SessionLocal()
    site = db.get(Site, site_id)
    gen = site.generation + 1
    pending: list[tuple[str, str, str]] = []  # (url, title, chunk)

    site.status = "crawling"
    site.message = "Reading the website…"
    for attr in ("pages_found", "pages_done", "pages_indexed", "pages_login", "pages_blocked", "pages_failed", "chunks_total", "chunks_done"):
        setattr(site, attr, 0)
    db.commit()

    def on_page(r: PageResult) -> None:
        db.add(Page(site_id=site_id, generation=gen, url=r.url, title=r.title, status=r.status, rendered=r.rendered))
        if r.status == "indexed":
            site.pages_indexed += 1
            for c in chunk_text(r.text):
                pending.append((r.url, r.title, c))
        elif r.status == "login":
            site.pages_login += 1
        elif r.status == "blocked":
            site.pages_blocked += 1
        elif r.status == "failed":
            site.pages_failed += 1

    def on_progress(found: int, done: int) -> None:
        site.pages_found = found
        site.pages_done = done
        site.message = f"Read {done} of {found} pages…"
        db.commit()

    try:
        limit = settings.max_pages if site.full_crawl else settings.large_site_pages
        crawler = Crawler(site.domain, site.root_url, site.include_pdfs, on_page, on_progress, max_pages=limit)
        crawler.run()
        if crawler.homepage_html:
            name, favicon = extract_site_identity(crawler.homepage_html, crawler.homepage_url, site.domain)
            site.name, site.favicon = name, favicon

        if not pending:
            if site.pages_blocked:
                reason = "The site blocked our crawler (bot protection)."
            elif site.pages_login:
                reason = "Every page we found requires a login."
            else:
                reason = "We couldn't find any readable text on this site."
            raise CrawlError(reason)

        site.status = "embedding"
        site.chunks_total = len(pending)
        site.message = f"Learning {len(pending)} sections of content…"
        db.commit()
        for i in range(0, len(pending), EMBED_BATCH):
            batch = pending[i:i + EMBED_BATCH]
            vectors = embed_passages([f"{title}\n{chunk}" for _, title, chunk in batch])
            for (url, title, chunk), vec in zip(batch, vectors):
                db.add(Chunk(site_id=site_id, generation=gen, url=url, title=title, content=chunk, embedding=vec))
            site.chunks_done = min(i + EMBED_BATCH, len(pending))
            db.commit()

        # Swap: the new generation goes live, then the old one is removed.
        site.generation = gen
        site.status = "ready"
        site.indexed_at = utcnow()
        site.suggestions = None  # regenerated from the new pages on next request
        site.truncated = crawler.truncated
        parts = [f"Indexed {site.pages_indexed} page{'' if site.pages_indexed == 1 else 's'}"]
        if site.pages_login:
            parts.append(f"{site.pages_login} skipped (login required)")
        if site.pages_blocked:
            parts.append(f"{site.pages_blocked} blocked")
        if site.pages_failed:
            parts.append(f"{site.pages_failed} failed")
        if crawler.truncated:
            parts.append("more pages not yet read")
        site.message = " · ".join(parts)
        db.commit()
        db.execute(delete(Chunk).where(Chunk.site_id == site_id, Chunk.generation != gen))
        db.execute(delete(Page).where(Page.site_id == site_id, Page.generation != gen))
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.exception("Ingestion failed for site %s", site_id)
        db.rollback()
        site = db.get(Site, site_id)
        db.execute(delete(Chunk).where(Chunk.site_id == site_id, Chunk.generation == gen))
        db.execute(delete(Page).where(Page.site_id == site_id, Page.generation == gen))
        msg = str(e) if isinstance(e, CrawlError) else "Something went wrong while reading the site."
        if site.generation > 0:
            site.status = "ready"
            site.message = f"Re-index failed: {msg} The previous index is still in use."
        else:
            site.status = "failed"
            site.message = msg
        db.commit()
    finally:
        db.close()
