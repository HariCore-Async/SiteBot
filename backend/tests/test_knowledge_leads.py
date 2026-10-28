"""Teach the bot (answers and documents), human handoff (leads) and replies in the visitor's language."""

import base64
import io
import zipfile

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import KNOWLEDGE_GENERATION, Chunk, Lead, Message
from conftest import SAME, ask, make_site, ndjson


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def docx(text: str) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = f'<w:document xmlns:w="{ns}"><w:body>' + "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.split("\n")) + "</w:body></w:document>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def chunks_for(site_id):
    db = SessionLocal()
    rows = db.scalars(select(Chunk).where(Chunk.site_id == site_id, Chunk.generation == KNOWLEDGE_GENERATION)).all()
    db.close()
    return rows


# ---------- Teach the bot ----------

def test_teach_an_answer_and_it_gets_cited(admin, site):
    k = admin.post(f"/api/sites/{site.id}/knowledge/answers", json={"question": "Do you ship to Canada?", "answer": "Yes, in 5 days."}).json()
    rows = chunks_for(site.id)
    assert len(rows) == 1 and rows[0].title == f"Answer from the {site.name} team" and "Canada" in rows[0].content
    chat = admin.post("/api/chats", json={"site_id": site.id}).json()
    done = ndjson(admin.post(f"/api/chats/{chat['id']}/messages", json={"content": "Do you ship to Canada?"}))[-1]
    # The fake model cites [1]; retrieval must have had the owner's answer among the hits for it to be a source.
    assert done["grounded"]
    edited = admin.patch(f"/api/sites/{site.id}/knowledge/{k['id']}", json={"question": "Do you ship to Canada?", "answer": "Yes, in 3 days."}).json()
    assert edited["content"] == "Yes, in 3 days." and "3 days" in chunks_for(site.id)[0].content and len(chunks_for(site.id)) == 1
    assert chunks_for(site.id)[0].content.startswith("Frequently asked question: Do you ship to Canada?")
    assert admin.delete(f"/api/sites/{site.id}/knowledge/{k['id']}").json() == {"ok": True}
    assert chunks_for(site.id) == []


def test_owner_knowledge_is_retrieved_and_survives_reindex_cleanup(admin, site, monkeypatch):
    from app import retrieval

    admin.post(f"/api/sites/{site.id}/knowledge/answers", json={"question": "Opening hours?", "answer": "9 to 5."})
    db = SessionLocal()
    hits, _ = retrieval.retrieve(db, site.id, 1, "opening hours")
    assert any(h.title.startswith("Answer from") for h in hits)
    # What a finished re-index does to old generations; the owner's knowledge must stay.
    db.execute(delete(Chunk).where(Chunk.site_id == site.id, Chunk.generation != 2, Chunk.generation != KNOWLEDGE_GENERATION))
    db.commit()
    db.close()
    assert len(chunks_for(site.id)) == 1


def test_only_the_bots_creator_or_admin_can_teach(member, admin, site):
    assert member.get(f"/api/sites/{site.id}/knowledge").status_code == 403
    assert member.post(f"/api/sites/{site.id}/knowledge/answers", json={"question": "q", "answer": "a"}).status_code == 403
    mine = make_site(created_by=member.user.id)
    assert member.post(f"/api/sites/{mine.id}/knowledge/answers", json={"question": "q?", "answer": "a."}).status_code == 200


def test_upload_documents(admin, site):
    long = "Our warranty covers every pair of shoes for two years from the date of purchase. " * 5
    for name, data in (("policy.txt", long.encode()), ("faq.md", ("# FAQ\n\n" + long).encode()), ("terms.docx", docx(long + "\nReturns are free within 30 days of delivery."))):
        r = admin.post(f"/api/sites/{site.id}/knowledge/documents", json={"filename": name, "data_b64": b64(data)})
        assert r.status_code == 200 and r.json()["kind"] == "document" and r.json()["chunks"] >= 1, (name, r.text)
    titles = {c.title for c in chunks_for(site.id)}
    assert {"policy.txt", "faq.md", "terms.docx"} <= titles
    listed = admin.get(f"/api/sites/{site.id}/knowledge").json()
    assert len([k for k in listed if k["kind"] == "document"]) == 3


def test_document_validation(admin, site):
    bad = admin.post(f"/api/sites/{site.id}/knowledge/documents", json={"filename": "virus.exe", "data_b64": b64(b"MZ")})
    assert bad.status_code == 400
    empty = admin.post(f"/api/sites/{site.id}/knowledge/documents", json={"filename": "blank.txt", "data_b64": b64(b"   ")})
    assert empty.status_code == 400 and "No text" in empty.json()["detail"]
    broken = admin.post(f"/api/sites/{site.id}/knowledge/documents", json={"filename": "x.docx", "data_b64": b64(b"not a zip")})
    assert broken.status_code == 400
    garbage = admin.post(f"/api/sites/{site.id}/knowledge/documents", json={"filename": "x.txt", "data_b64": "%%%"})
    assert garbage.status_code == 400
    big = admin.post(f"/api/sites/{site.id}/knowledge/documents", json={"filename": "big.txt", "data_b64": b64(b"a" * (10 * 1024 * 1024 + 1))})
    assert big.status_code in (413, 422)


# ---------- Human handoff ----------

def test_visitor_leaves_email_after_unanswered_question(monkeypatch, client, admin, embed, fakes):
    from app import accounts

    sent = []
    monkeypatch.setattr(accounts, "notify", lambda to, subject, body: sent.append((to, subject, body)))
    origin = f"https://{embed['site']['domain']}"
    fakes.answer = "NOT_FOUND"
    ask(client, embed["key"], "Do you have a store in Paris?", visitor="visitorLEAD0000000001", origin=origin)
    r = client.post(f"/api/public/{embed['key']}/leads", headers=SAME,
                    json={"visitor_id": "visitorLEAD0000000001", "email": "jo@example.com", "name": "Jo", "message": "Call me", "origin": origin})
    assert r.json() == {"ok": True}
    leads = admin.get(f"/api/embeds/{embed['id']}/leads").json()
    assert leads[0]["email"] == "jo@example.com" and leads[0]["question"] == "Do you have a store in Paris?" and leads[0]["status"] == "open"
    assert sent and sent[0][0] == [admin.user.email] and "Paris" in sent[0][2] and "jo@example.com" in sent[0][2]
    e = [x for x in admin.get("/api/embeds").json() if x["id"] == embed["id"]][0]
    assert e["leads_open"] == 1
    assert admin.patch(f"/api/embeds/{embed['id']}/leads/{leads[0]['id']}", json={"status": "done"}).json()["status"] == "done"


def test_lead_validation_and_limits(client, member, embed):
    origin = f"https://{embed['site']['domain']}"
    body = {"visitor_id": "visitorLEAD0000000002", "email": "not-an-email", "origin": origin}
    assert client.post(f"/api/public/{embed['key']}/leads", headers=SAME, json=body).status_code == 400
    body["email"] = "a@b.co"
    assert client.post(f"/api/public/{embed['key']}/leads", headers=SAME, json={**body, "origin": "https://evil.example"}).status_code == 403
    codes = [client.post(f"/api/public/{embed['key']}/leads", headers=SAME, json=body).status_code for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[6] == 429
    assert member.get(f"/api/embeds/{embed['id']}/leads").status_code == 404


# ---------- Visitor's language ----------

def test_non_english_question_is_searched_in_english_and_answered_in_its_own_words(client, embed, fakes, monkeypatch):
    from app import llm

    seen = []
    real_stream = llm.stream

    def spy(purpose, messages, max_tokens=900, site_id=None):
        seen.append(messages[-1]["content"])
        return real_stream(purpose, messages, max_tokens, site_id)

    monkeypatch.setattr(llm, "stream", spy)
    ask(client, embed["key"], "¿Qué zapatos venden?", visitor="visitorLANG0000000001", origin=f"https://{embed['site']['domain']}")
    assert any(c[0] == "complete" for c in fakes.calls)  # the English search rewrite ran without any history
    assert "¿Qué zapatos venden?" in seen[0]


def test_system_prompt_replies_in_the_visitors_language():
    from app.chat import system_prompt
    from types import SimpleNamespace

    prompt = system_prompt(SimpleNamespace(name="Shop", domain="shop.example"))
    assert "same language as the QUESTION" in prompt and "Answer in English" not in prompt


def test_messages_kept(db):
    # Guard: the lead lookup reads recent messages; make sure the model still has the fields it relies on.
    assert hasattr(Message, "grounded") and hasattr(Lead, "question")
