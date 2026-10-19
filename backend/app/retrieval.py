"""Hybrid retrieval: pgvector cosine search + Postgres full-text search, fused with reciprocal rank fusion."""

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import settings
from .embeddings import embed_query
from .models import Chunk

CANDIDATES = 20
RRF_K = 60


@dataclass
class Hit:
    id: int
    url: str
    title: str
    content: str
    similarity: float
    score: float = 0.0


def retrieve(db: Session, site_id: int, generation: int, query: str) -> tuple[list[Hit], float]:
    """Returns (top hits, best vector similarity). Best similarity drives the 'not on this site' gate."""
    qvec = embed_query(query)
    distance = Chunk.embedding.cosine_distance(qvec)
    vec_rows = db.execute(
        select(Chunk.id, Chunk.url, Chunk.title, Chunk.content, (1 - distance).label("sim"))
        .where(Chunk.site_id == site_id, Chunk.generation == generation)
        .order_by(distance)
        .limit(CANDIDATES)
    ).all()

    # OR the query terms so natural-language questions still match on keywords.
    fts_rows = db.execute(
        text(
            """
            WITH q AS (
                SELECT to_tsquery('english', replace(plainto_tsquery('english', :t)::text, '&', '|')) AS query
            )
            SELECT c.id, c.url, c.title, c.content, ts_rank_cd(c.tsv, q.query) AS rank
            FROM chunks c, q
            WHERE c.site_id = :s AND c.generation = :g AND q.query::text <> '' AND c.tsv @@ q.query
            ORDER BY rank DESC
            LIMIT :n
            """
        ),
        {"t": query, "s": site_id, "g": generation, "n": CANDIDATES},
    ).all()

    hits: dict[int, Hit] = {}
    for rank, r in enumerate(vec_rows):
        h = hits.setdefault(r.id, Hit(r.id, r.url, r.title, r.content, float(r.sim)))
        h.score += 1 / (RRF_K + rank)
    for rank, r in enumerate(fts_rows):
        h = hits.get(r.id) or hits.setdefault(r.id, Hit(r.id, r.url, r.title, r.content, 0.0))
        h.score += 1 / (RRF_K + rank)

    best_sim = max((float(r.sim) for r in vec_rows), default=0.0)
    top = sorted(hits.values(), key=lambda h: h.score, reverse=True)[: settings.top_k]
    return top, best_sim
