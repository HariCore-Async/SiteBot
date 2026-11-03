"""Measure search quality on real bots, with and without re-ranking.

For random passages of the given bots, the fast AI model writes a question a visitor might ask that the passage answers
(saved to a JSON file, so later runs cost nothing). Then, for each question: does today's hybrid search put that
passage's page first (hit@1), in the top 3, or among the 6 excerpts the answering model reads (hit@6)? And does
re-ranking the fused top candidates with a small cross-encoder do better, and how long does it take?

From backend/, against a database with indexed bots (costs a few cents of AI the first time):

    python -m tools.retrieval_eval --sites 3 5 9 --per-site 20 --questions retrieval_questions.json

Results from 2 November 2026 (120 questions over 6 bots) are in docs/QUALITY.md.
"""

import argparse
import json
import random
import time
from pathlib import Path

from sqlalchemy import select, text

from app import llm
from app.db import SessionLocal
from app.embeddings import embed_query
from app.models import Chunk, Site
from app.retrieval import CANDIDATES, RRF_K

TOP_K = 6
RERANKER = "Xenova/ms-marco-MiniLM-L-6-v2"
# (candidates re-ranked, characters of each passage given to the re-ranker)
SETTINGS = [(20, 4000), (20, 700), (12, 700), (10, 500)]


def make_questions(db, sites: list[int], per_site: int) -> list[dict]:
    rng = random.Random(42)
    out = []
    for sid in sites:
        site = db.get(Site, sid)
        rows = db.execute(select(Chunk.url, Chunk.content).where(Chunk.site_id == sid, Chunk.generation == site.generation)).all()
        for r in rng.sample([r for r in rows if len(r.content) > 300], min(per_site, len(rows))):
            q, _ = llm.complete("fast", [
                {"role": "system", "content": "Write ONE question a visitor to this website might type into its chatbot, which the "
                 "passage below answers. Use your own everyday words, not the passage's exact phrases. Reply with the question only."},
                {"role": "user", "content": r.content[:1500]},
            ], max_tokens=60)
            out.append({"site": sid, "url": r.url, "question": q.strip().strip('"')})
    return out


def candidates(db, site_id: int, generation: int, query: str) -> list[tuple[str, str]]:
    """The same hybrid search as app/retrieval.py, returning the whole fused list (url, content), best first."""
    distance = Chunk.embedding.cosine_distance(embed_query(query))
    vec = db.execute(
        select(Chunk.id, Chunk.url, Chunk.content).where(Chunk.site_id == site_id, Chunk.generation.in_((generation, 0)))
        .order_by(distance).limit(CANDIDATES)
    ).all()
    fts = db.execute(text(
        "WITH q AS (SELECT to_tsquery('english', replace(plainto_tsquery('english', :t)::text, '&', '|')) AS query) "
        "SELECT c.id, c.url, c.content FROM chunks c, q WHERE c.site_id = :s AND c.generation IN (:g, 0) "
        "AND q.query::text <> '' AND c.tsv @@ q.query ORDER BY ts_rank_cd(c.tsv, q.query) DESC LIMIT :n"
    ), {"t": query, "s": site_id, "g": generation, "n": CANDIDATES}).all()
    score, info = {}, {}
    for rows in (vec, fts):
        for rank, r in enumerate(rows):
            score[r.id] = score.get(r.id, 0) + 1 / (RRF_K + rank)
            info[r.id] = (r.url, r.content)
    return [info[i] for i in sorted(score, key=score.get, reverse=True)]


def rank_of(url: str, hits) -> int | None:
    return next((i for i, h in enumerate(hits, 1) if h[0] == url), None)


def report(name: str, ranks: list, seconds: float | None = None) -> None:
    n = len(ranks)
    hit = lambda k: sum(1 for r in ranks if r and r <= k) / n  # noqa: E731
    mrr = sum(1 / r for r in ranks if r) / n
    speed = f"  {seconds * 1000 / n:.0f} ms/question" if seconds is not None else ""
    print(f"{name:40} hit@1 {hit(1):.0%}  hit@3 {hit(3):.0%}  hit@6 {hit(TOP_K):.0%}  MRR {mrr:.3f}{speed}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sites", type=int, nargs="+", required=True, help="bot (site) ids to sample from")
    ap.add_argument("--per-site", type=int, default=20)
    ap.add_argument("--questions", type=Path, default=Path("retrieval_questions.json"), help="where questions are saved and reused")
    args = ap.parse_args()

    db = SessionLocal()
    if args.questions.exists():
        qs = json.loads(args.questions.read_text(encoding="utf-8"))
    else:
        qs = make_questions(db, args.sites, args.per_site)
        args.questions.write_text(json.dumps(qs, indent=1), encoding="utf-8")
    gens = {s.id: s.generation for s in db.scalars(select(Site).where(Site.id.in_({q["site"] for q in qs})))}
    cands = [candidates(db, q["site"], gens[q["site"]], q["question"]) for q in qs]
    print(f"{len(qs)} questions; right page among the candidates at all: {sum(1 for q, c in zip(qs, cands) if rank_of(q['url'], c)) / len(qs):.0%}\n")
    report("today (no re-ranking)", [rank_of(q["url"], c[:TOP_K]) for q, c in zip(qs, cands)])

    from fastembed.rerank.cross_encoder import TextCrossEncoder

    model = TextCrossEncoder(model_name=RERANKER)
    list(model.rerank("warm up", ["a passage"]))
    for n, chars in SETTINGS:
        t0, ranks = time.perf_counter(), []
        for q, c in zip(qs, cands):
            top = c[:n]
            scores = list(model.rerank(q["question"], [content[:chars] for _, content in top]))
            ordered = [top[i] for i in sorted(range(len(top)), key=lambda i: -scores[i])] + c[n:]
            ranks.append(rank_of(q["url"], ordered[:TOP_K]))
        report(f"re-ranked: top {n}, {chars} chars", ranks, time.perf_counter() - t0)


if __name__ == "__main__":
    main()
