"""Test questions: an owner lists questions their website chatbot should answer (and what a good answer says), or
should decline because the website doesn't cover them. A run asks every question the normal way (charged like any
visitor's question, so the daily cap applies) and grades the answers. Runs happen on demand and after each re-index.
"""

import json
import logging
import re
import threading

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import llm
from .chat import CITATION, answer_stream, fact_tokens
from .db import SessionLocal
from .models import Chat, Embed, EvalQuestion, EvalRun, Site, User, utcnow
from .usage import record_usage

log = logging.getLogger(__name__)

MAX_QUESTIONS = 30
KEEP_RUNS = 20
_running: set[int] = set()
_lock = threading.Lock()


def is_running(embed_id: int) -> bool:
    return embed_id in _running


def start(embed_id: int, trigger: str = "manual") -> bool:
    """Runs the chatbot's test questions in the background. False if a run is already going or there's nothing to run."""
    with _lock:
        if embed_id in _running:
            return False
        with SessionLocal() as db:
            if not db.scalar(select(EvalQuestion.id).where(EvalQuestion.embed_id == embed_id).limit(1)):
                return False
        _running.add(embed_id)
    threading.Thread(target=_run, args=(embed_id, trigger), daemon=True).start()
    return True


def after_reindex(site_id: int) -> None:
    """The website was read again: check that every chatbot on it still answers its test questions."""
    with SessionLocal() as db:
        embed_ids = db.scalars(
            select(Embed.id).where(Embed.site_id == site_id, Embed.id.in_(select(EvalQuestion.embed_id)))
        ).all()
    for embed_id in embed_ids:
        start(embed_id, "reindex")


def _ask(db: Session, owner: User, e: Embed, question: str) -> dict:
    """One question through the normal answering, in a throwaway test chat. Returns the final text and how it ended."""
    chat = Chat(user_id=None, site_id=e.site_id, embed_id=e.id, visitor_id="test-questions", origin="Test questions", is_test=True)
    db.add(chat)
    db.commit()
    text, end = "", {}
    try:
        for line in answer_stream(db, owner, chat, question, embed=e, use_cache=False):
            ev = json.loads(line)
            if ev["type"] == "token":
                text += ev["text"]
            elif ev["type"] == "replace":
                text = ev["text"]
            elif ev["type"] in ("done", "error"):
                end = ev
    finally:
        db.delete(chat)
        db.commit()
    return {"text": text.strip(), **end}


def _judge(db: Session, owner: User, e: Embed, question: str, expected: str, answer: str) -> tuple[bool, str]:
    """Does the answer say what the expected answer says? Asked of the fast model; if that fails, every number and name
    in the expected answer has to appear in the answer."""
    try:
        reply, usage = llm.complete(
            "fast",
            [
                {
                    "role": "system",
                    "content": "You grade a chatbot's answer against the answer its owner expects. PASS if the chatbot's answer "
                    "states the same key facts as the expected answer (different wording, extra correct detail or another "
                    "language are fine). FAIL if it misses a key fact, contradicts it, or says it doesn't know. "
                    "Reply with PASS or FAIL, then a few words on why.",
                },
                {"role": "user", "content": f"QUESTION: {question}\n\nEXPECTED ANSWER: {expected}\n\nCHATBOT'S ANSWER: {answer}"},
            ],
            max_tokens=40,
            site_id=e.site_id,
        )
        record_usage(db, owner.id, "eval", usage.get("model", ""), usage, e.id)
        verdict = reply.strip()
        if verdict.upper().startswith(("PASS", "FAIL")):
            return verdict.upper().startswith("PASS"), verdict[4:].strip(" :.-") or ("Matches" if verdict.upper().startswith("PASS") else "Doesn't match")
    except llm.LLMError as err:
        log.warning("Test question grading fell back to word matching: %s", err)
    missing = [t for t in fact_tokens(expected) if t.lower() not in answer.lower()]
    if not fact_tokens(expected):
        return True, "Answered (nothing specific to compare)"
    return not missing, "Matches" if not missing else f"Missing: {', '.join(sorted(missing)[:5])}"


def grade(db: Session, owner: User, e: Embed, q: EvalQuestion, result: dict) -> tuple[bool, str]:
    if result.get("type") == "error":
        return False, result.get("message", "Couldn't answer")
    grounded = bool(result.get("grounded"))
    if q.mode == "not_on_site":
        return (True, "Said it doesn't know") if not grounded else (False, "Answered, but the website doesn't cover this")
    if not grounded:
        return False, "Said it doesn't know"
    if not q.expected.strip():
        return True, "Answered with sources"
    return _judge(db, owner, e, q.question, q.expected, CITATION.sub("", result["text"]))


def _run(embed_id: int, trigger: str) -> None:
    db = SessionLocal()
    run = None
    try:
        e = db.get(Embed, embed_id)
        owner = db.get(User, e.owner_id) if e else None
        questions = db.scalars(select(EvalQuestion).where(EvalQuestion.embed_id == embed_id).order_by(EvalQuestion.id)).all()
        if not e or not owner or not questions or not db.get(Site, e.site_id):
            return
        run = EvalRun(embed_id=embed_id, trigger=trigger, status="running", total=len(questions))
        db.add(run)
        db.commit()
        results = []
        for q in questions:
            res = _ask(db, owner, e, q.question)
            ok, reason = grade(db, owner, e, q, res)
            results.append({
                "question_id": q.id, "question": q.question, "mode": q.mode, "expected": q.expected,
                "answer": res.get("text", "")[:2000], "grounded": bool(res.get("grounded")),
                "sources": [{"title": s.get("title", ""), "url": s.get("url", "")} for s in res.get("sources") or []],
                "passed": ok, "reason": reason[:300],
            })
            run.results, run.passed = list(results), sum(r["passed"] for r in results)
            db.commit()
            if res.get("type") == "error":
                # The daily cap or a budget ran out: the remaining questions would fail the same way.
                run.message = f"Stopped after {len(results)} of {len(questions)}: {res.get('message', '')}"
                break
        run.status = "done"
        run.finished_at = utcnow()
        db.commit()
        old = db.scalars(select(EvalRun.id).where(EvalRun.embed_id == embed_id).order_by(EvalRun.id.desc()).offset(KEEP_RUNS)).all()
        if old:
            db.execute(delete(EvalRun).where(EvalRun.id.in_(old)))
            db.commit()
    except Exception as err:  # noqa: BLE001  (report it on the run instead of losing it)
        log.exception("Test question run failed for embed %s", embed_id)
        db.rollback()
        if run is not None:
            run.status, run.message, run.finished_at = "failed", f"Something went wrong: {err}"[:500], utcnow()
            db.commit()
    finally:
        db.close()
        with _lock:
            _running.discard(embed_id)


def question_out(q: EvalQuestion) -> dict:
    return {"id": q.id, "question": q.question, "expected": q.expected, "mode": q.mode}


def run_out(r: EvalRun, full: bool = False) -> dict:
    out = {
        "id": r.id, "trigger": r.trigger, "status": r.status, "total": r.total, "passed": r.passed, "message": r.message,
        "done": len(r.results or []), "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }
    if full:
        out["results"] = r.results or []
    return out


def clean_question(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
