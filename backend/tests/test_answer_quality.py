"""Answer quality: the answer checker no longer throws away supported answers, repeated questions come from the answer
cache, and test questions grade a chatbot's answers."""

import time

import pytest

from app import chat as C
from app import evals, llm
from app.db import SessionLocal
from app.models import AnswerCache, Chat, EvalRun, Site, UsageEvent
from app.retrieval import Hit

from conftest import SAME, As, ask, make_user, ndjson

HITS = [Hit(1, "https://shop.example/office", "Office", "Yes. Acme opened a Berlin office in 2026, at Torstrasse 1, 10119 Berlin.", 0.9)]


# ---------- The answer checker ----------

def test_fact_tokens():
    assert C.fact_tokens("We opened a Berlin office in 2026, at Torstrasse 1 [1].") == {"Berlin", "2026", "Torstrasse", "1"}
    assert C.fact_tokens("Yes.") == set()
    assert "10:00" in C.fact_tokens("Support opens at 10:00 on Mondays.")


def checker_flagging(monkeypatch, labels):
    calls = []

    def complete(purpose, messages, max_tokens=300, site_id=None):
        calls.append(messages[-1]["content"])
        return labels, {"model": "fake"}

    monkeypatch.setattr(llm, "complete", complete)
    return calls


def test_supported_answer_survives_a_checker_that_flags_everything(monkeypatch):
    calls = checker_flagging(monkeypatch, "S1, S2")
    with SessionLocal() as db:
        user = db.get(type(make_user()), make_user().id)
        answer = "Yes. We opened a Berlin office in 2026, located at Torstrasse 1, 10119 Berlin [1]."
        assert C.verify_answer(db, user, HITS, answer) == answer
    assert calls == []  # nothing needed checking: every number and name is in the excerpt


def test_made_up_facts_are_still_removed(monkeypatch):
    calls = checker_flagging(monkeypatch, "S3")
    with SessionLocal() as db:
        user = db.get(type(make_user()), make_user().id)
        answer = "Yes. We opened a Berlin office in 2026 [1]. Our Munich office has 40 staff [1]."
        assert C.verify_answer(db, user, HITS, answer) == "Yes. We opened a Berlin office in 2026 [1]."
    assert len(calls) == 2 and "S3: Our Munich office" in calls[0] and "S1" not in calls[0] and "S2" not in calls[0]


def test_unsupported_claims_without_names_still_get_checked(monkeypatch):
    calls = checker_flagging(monkeypatch, "NONE")
    with SessionLocal() as db:
        user = db.get(type(make_user()), make_user().id)
        C.verify_answer(db, user, HITS, "Returns are always free and take no time at all [1].")
    assert len(calls) == 1 and "S1: Returns are always free" in calls[0]


# ---------- Answer cache ----------

def visitor_answer(client, key, question, visitor, domain):
    events = ndjson(ask(client, key, question, visitor=visitor, origin=f"https://{domain}"))
    text = "".join(e.get("text", "") for e in events if e["type"] == "token")
    return text, events[-1]


def test_repeated_first_question_comes_from_the_cache(client, admin, embed, fakes):
    domain = embed["site"]["domain"]
    text1, done1 = visitor_answer(client, embed["key"], "What do you sell?", "visitorCACHE0000000001", domain)
    streams = sum(1 for c in fakes.calls if c[0] == "stream")
    text2, done2 = visitor_answer(client, embed["key"], "what do you  sell", "visitorCACHE0000000002", domain)
    assert sum(1 for c in fakes.calls if c[0] == "stream") == streams  # no AI call the second time
    assert text2.strip() == text1.strip() and done2["sources"] == done1["sources"] and done2["grounded"]
    with SessionLocal() as db:
        assert db.query(AnswerCache).filter_by(site_id=embed["site_id"]).one().hits == 1
    # Both are real conversations for the owner.
    assert len([c for c in admin.get(f"/api/embeds/{embed['id']}/chats").json() if not c["is_test"]]) == 2


def test_follow_ups_are_not_cached(client, embed, fakes):
    domain = embed["site"]["domain"]
    visitor_answer(client, embed["key"], "What do you sell?", "visitorFOLLOW000000001", domain)
    visitor_answer(client, embed["key"], "And in blue?", "visitorFOLLOW000000001", domain)
    with SessionLocal() as db:
        assert [r.question for r in db.query(AnswerCache).filter_by(site_id=embed["site_id"])] == ["What do you sell?"]


def test_teaching_reindexing_and_a_thumbs_down_clear_it(client, admin, embed, fakes):
    domain, sid = embed["site"]["domain"], embed["site_id"]

    def cached():
        with SessionLocal() as db:
            return db.query(AnswerCache).filter_by(site_id=sid).count()

    visitor_answer(client, embed["key"], "What do you sell?", "visitorCLEAR000000001", domain)
    assert cached() == 1
    admin.post(f"/api/sites/{sid}/knowledge/answers", json={"question": "Do you sell socks?", "answer": "Yes, wool socks."})
    assert cached() == 0

    visitor_answer(client, embed["key"], "What do you sell?", "visitorCLEAR000000002", domain)
    with SessionLocal() as db:
        site = db.get(Site, sid)
        site.generation += 1  # what a re-index does: the old entry no longer matches
        db.commit()
    streams = sum(1 for c in fakes.calls if c[0] == "stream")
    visitor_answer(client, embed["key"], "What do you sell?", "visitorCLEAR000000003", domain)
    assert sum(1 for c in fakes.calls if c[0] == "stream") == streams + 1

    _, done = visitor_answer(client, embed["key"], "What do you sell?", "visitorCLEAR000000004", domain)
    r = client.post(f"/api/public/{embed['key']}/feedback", headers=SAME,
                    json={"visitor_id": "visitorCLEAR000000004", "message_id": done["message_id"], "rating": "down", "origin": f"https://{domain}"})
    assert r.status_code == 200 and cached() == 0


def test_cache_can_be_switched_off(client, embed, fakes, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "answer_cache", False)
    domain = embed["site"]["domain"]
    visitor_answer(client, embed["key"], "What do you sell?", "visitorOFF0000000001", domain)
    visitor_answer(client, embed["key"], "What do you sell?", "visitorOFF0000000002", domain)
    assert sum(1 for c in fakes.calls if c[0] == "stream") == 2


# ---------- Test questions ----------

def wait_for_run(admin, embed_id):
    for _ in range(100):
        data = admin.get(f"/api/embeds/{embed_id}/evals").json()
        if not data["running"] and data["latest"]:
            return data
        time.sleep(0.05)
    raise AssertionError("the run didn't finish")


@pytest.fixture
def grader(monkeypatch, fakes):
    """The fast model grades by looking for the expected answer in the chatbot's answer."""
    fake = fakes.complete

    def complete(purpose, messages, max_tokens=300, site_id=None):
        if "grade a chatbot's answer" in messages[0]["content"]:
            text = messages[-1]["content"]
            expected = text.split("EXPECTED ANSWER:")[1].split("CHATBOT'S ANSWER:")[0].strip().rstrip(".").lower()
            ok = expected in text.split("CHATBOT'S ANSWER:")[1].lower()
            return ("PASS same facts" if ok else "FAIL different"), {"model": "fake", "cost": 0.0001}
        return fake(purpose, messages, max_tokens, site_id)

    monkeypatch.setattr(llm, "complete", complete)


def test_test_questions_run_and_grade(client, admin, embed, fakes, grader):
    eid = embed["id"]
    base = f"/api/embeds/{eid}/evals"
    assert admin.post(f"{base}/run").status_code == 400  # nothing to run yet
    q1 = admin.post(f"{base}/questions", json={"question": "What do you sell?", "expected": "Running shoes and trail shoes."}).json()
    admin.post(f"{base}/questions", json={"question": "Do you sell bikes?", "expected": "Mountain bikes."})
    admin.post(f"{base}/questions", json={"question": "Is there a shop on Mars?", "mode": "not_on_site"})
    admin.post(f"{base}/questions", json={"question": "What's on sale?"})
    assert admin.post(f"{base}/questions", json={"question": "x", "mode": "maybe"}).status_code == 422
    assert admin.put(f"{base}/questions/{q1['id']}", json={"question": "What do you sell?", "expected": "Running shoes."}).json()["expected"] == "Running shoes."

    spent_before = admin.get("/api/embeds").json()[0]["spent_today_usd"]
    assert admin.post(f"{base}/run").json() == {"ok": True}
    data = wait_for_run(admin, eid)
    run = data["latest"]
    by_q = {r["question"]: r for r in run["results"]}
    assert run["status"] == "done" and run["trigger"] == "manual" and run["total"] == 4
    assert by_q["What do you sell?"]["passed"] and by_q["What do you sell?"]["sources"]
    assert by_q["Do you sell bikes?"]["passed"] is False and "different" in by_q["Do you sell bikes?"]["reason"]
    assert by_q["Is there a shop on Mars?"]["passed"] is False  # the fake bot answers everything
    assert by_q["What's on sale?"]["passed"]  # no expected answer: any sourced answer passes
    assert run["passed"] == 2
    # Charged like visitors' questions, and the throwaway chats are gone.
    assert admin.get("/api/embeds").json()[0]["spent_today_usd"] > spent_before
    with SessionLocal() as db:
        assert db.query(Chat).filter_by(embed_id=eid, visitor_id="test-questions").count() == 0
        assert db.query(UsageEvent).filter_by(embed_id=eid, kind="eval").count() == 2
    assert admin.get(f"{base}/runs/{run['id']}").json()["results"] == run["results"]


def test_not_on_site_passes_when_the_bot_declines(client, admin, embed, fakes, grader):
    fakes.answer = "NOT_FOUND"
    admin.post(f"/api/embeds/{embed['id']}/evals/questions", json={"question": "Is there a shop on Mars?", "mode": "not_on_site"})
    admin.post(f"/api/embeds/{embed['id']}/evals/questions", json={"question": "What do you sell?", "expected": "Shoes."})
    admin.post(f"/api/embeds/{embed['id']}/evals/run")
    by_q = {r["question"]: r for r in wait_for_run(admin, embed["id"])["latest"]["results"]}
    assert by_q["Is there a shop on Mars?"]["passed"] and by_q["What do you sell?"]["reason"] == "Said it doesn't know"


def test_runs_after_reindex_and_stop_at_the_daily_cap(client, admin, embed, fakes, grader):
    admin.post(f"/api/embeds/{embed['id']}/evals/questions", json={"question": "What do you sell?"})
    admin.post(f"/api/embeds/{embed['id']}/evals/questions", json={"question": "Where are you?"})
    admin.patch(f"/api/admin/embeds/{embed['id']}", json={"daily_cap_usd": 0})
    evals.after_reindex(embed["site_id"])
    run = wait_for_run(admin, embed["id"])["latest"]
    assert run["trigger"] == "reindex" and run["passed"] == 0 and run["message"].startswith("Stopped after 1 of 2")


def test_who_can_see_and_change_test_questions(client, admin, embed):
    viewer, editor = As(client, make_user()), As(client, make_user())
    admin.post(f"/api/embeds/{embed['id']}/team", json={"email": viewer.user.email, "role": "viewer"})
    admin.post(f"/api/embeds/{embed['id']}/team", json={"email": editor.user.email, "role": "editor"})
    base = f"/api/embeds/{embed['id']}/evals"
    assert viewer.get(base).status_code == 200
    assert viewer.post(f"{base}/questions", json={"question": "Hi?"}).status_code == 403
    assert viewer.post(f"{base}/run").status_code == 403
    assert editor.post(f"{base}/questions", json={"question": "Hi?"}).status_code == 200
    stranger = As(client, make_user())
    assert stranger.get(base).status_code == 404
    with SessionLocal() as db:
        assert db.query(EvalRun).filter_by(embed_id=embed["id"]).count() == 0
