"""Suggested starter questions, generated once per index from the site's own pages."""

import logging
import re
import threading

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import llm
from .config import settings
from .models import Chunk, Site, User
from .retrieval import retrieve
from .usage import check_budget, record_usage

log = logging.getLogger(__name__)

MAX_SUGGESTIONS = 6
SAMPLE_PAGES = 12
SAMPLE_CHARS = 9000

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(site_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(site_id, threading.Lock())


def _sample(db: Session, site: Site) -> str:
    """The first chunk of each of the first pages: a broad, cheap overview of what the site covers."""
    first_ids = (
        select(func.min(Chunk.id))
        .where(Chunk.site_id == site.id, Chunk.generation == site.generation)
        .group_by(Chunk.url)
        .order_by(func.min(Chunk.id))
        .limit(SAMPLE_PAGES)
    )
    chunks = db.scalars(select(Chunk).where(Chunk.id.in_(first_ids)).order_by(Chunk.id)).all()
    text, used = [], 0
    for c in chunks:
        piece = f"## {c.title or c.url}\n{c.content[:900]}"
        if used + len(piece) > SAMPLE_CHARS:
            break
        text.append(piece)
        used += len(piece)
    return "\n\n".join(text)


def _generate(db: Session, site: Site, user: User) -> list[str]:
    sample = _sample(db, site)
    if not sample:
        return []
    text, usage = llm.complete(
        settings.openrouter_fast_model,
        [
            {
                "role": "system",
                "content": f"You write suggested questions for the chat assistant on {site.name}'s website. Write 8 short, "
                "varied questions a visitor might ask, addressed to the company (e.g. \"What does ... cost?\", \"Do you offer ...?\"). "
                "Each question must be directly answerable from the TEXT below. Keep each under 60 characters. "
                "Output one question per line, with no numbering or extra text.",
            },
            {"role": "user", "content": f"TEXT:\n{sample}"},
        ],
        max_tokens=300,
    )
    record_usage(db, user.id, "suggest", settings.openrouter_fast_model, usage)
    if not text.strip():
        log.warning("Suggestion model returned no text for site %s", site.id)

    questions: list[str] = []
    for line in text.splitlines():
        q = re.sub(r"^\s*(\d+[.)]|[-*•])\s*", "", line).strip().strip('"')
        if not q.endswith("?") or not 8 <= len(q) <= 80 or q.lower() in (x.lower() for x in questions):
            continue
        # Only keep questions the bot can actually find an answer for.
        _, best = retrieve(db, site.id, site.generation, q)
        if best >= settings.min_similarity:
            questions.append(q)
        if len(questions) == MAX_SUGGESTIONS:
            break
    return questions


def get_suggestions(db: Session, site: Site, user: User) -> list[str]:
    if site.generation == 0:
        return []
    if site.suggestions:
        return site.suggestions
    with _lock(site.id):
        db.refresh(site)
        if site.suggestions:
            return site.suggestions
        if reason := check_budget(db, user):
            log.info("Suggestions for site %s skipped: %s", site.id, reason)
            return []
        try:
            questions = _generate(db, site, user)
        except llm.LLMError as e:
            log.warning("Suggestion generation failed for site %s: %s", site.id, e)
            return []
        log.info("Suggestions for site %s: kept %d", site.id, len(questions))
        # An empty result isn't stored, so the next visit tries again instead of showing nothing forever.
        if questions:
            site.suggestions = questions
            db.commit()
        return questions
