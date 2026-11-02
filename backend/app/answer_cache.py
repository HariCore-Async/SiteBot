"""Answer cache: when the same first question comes to the same bot again, the checked answer is reused, at no AI cost.

An entry is keyed by the normalised question, the bot's live index (generation) and the model that answers, so
re-indexing or switching models never serves an old answer. Teaching the bot something (answers, documents) clears
its entries, and so does a visitor's thumbs-down on a cached answer. Entries older than a week aren't used.
"""

import hashlib
import logging
import re
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .models import AnswerCache, Site, utcnow

log = logging.getLogger(__name__)

MAX_AGE = timedelta(days=7)


def normalise(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower()).strip(" ?!.¿¡")


def _key(db: Session, site: Site, question: str) -> str:
    from .providers import defaults

    model = site.answer_model or defaults(db)["answer"]
    return hashlib.sha256(f"{site.generation}|{model}|{normalise(question)}".encode()).hexdigest()


def get(db: Session, site: Site, question: str) -> AnswerCache | None:
    if not settings.answer_cache:
        return None
    row = db.scalar(select(AnswerCache).where(AnswerCache.site_id == site.id, AnswerCache.key == _key(db, site, question)))
    if not row or utcnow() - row.created_at > MAX_AGE:
        return None
    row.hits += 1
    row.last_hit_at = utcnow()
    db.commit()
    log.info("Answer cache hit: site %s, %d times so far", site.id, row.hits)
    return row


def put(db: Session, site: Site, question: str, answer: str, sources: list[dict]) -> None:
    if not settings.answer_cache:
        return
    key = _key(db, site, question)
    row = db.scalar(select(AnswerCache).where(AnswerCache.site_id == site.id, AnswerCache.key == key))
    if row:
        row.answer, row.sources, row.created_at = answer, sources, utcnow()
    else:
        db.add(AnswerCache(site_id=site.id, key=key, question=question[:2000], answer=answer, sources=sources))
    # Old entries are never used again (and ones for an older index or another model never match).
    db.execute(delete(AnswerCache).where(AnswerCache.site_id == site.id, AnswerCache.created_at < utcnow() - MAX_AGE))
    db.commit()


def clear(db: Session, site_id: int) -> None:
    db.execute(delete(AnswerCache).where(AnswerCache.site_id == site_id))
    db.commit()


def forget(db: Session, site_id: int, answer: str) -> None:
    """A visitor said this answer wasn't helpful: don't hand it out again."""
    db.execute(delete(AnswerCache).where(AnswerCache.site_id == site_id, AnswerCache.answer == answer))
    db.commit()
