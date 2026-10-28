"""Team access per website chatbot, scheduled re-index, weekly reports, proactive greeting and page-aware suggestions."""

from datetime import timedelta

from app import scheduler
from app.db import SessionLocal
from app.models import Chunk, Embed, Site, utcnow
from conftest import SAME, As, ask, make_site, make_user


def team(client, admin, embed, role):
    """A new user added to `embed` with `role`, signed in."""
    u = make_user("member")
    r = admin.post(f"/api/embeds/{embed['id']}/team", json={"email": u.email.upper(), "role": role})
    assert r.status_code == 200 and r.json()["role"] == role and r.json()["joined"]
    return As(client, u)


def test_owner_invites_and_the_list_shows_the_role(client, admin, embed):
    viewer = team(client, admin, embed, "viewer")
    listed = viewer.get("/api/embeds").json()
    assert [e["id"] for e in listed] == [embed["id"]] and listed[0]["my_role"] == "viewer"
    assert admin.get("/api/embeds").json()[0]["my_role"] == "owner"
    t = viewer.get(f"/api/embeds/{embed['id']}/team").json()
    assert t["owner"]["email"] == admin.user.email and len(t["members"]) == 1


def test_viewer_reads_but_cannot_change(client, admin, embed):
    v = team(client, admin, embed, "viewer")
    for path in ("chats", "insights", "leads", "team"):
        assert v.get(f"/api/embeds/{embed['id']}/{path}").status_code == 200, path
    assert v.get(f"/api/sites/{embed['site_id']}/knowledge").status_code == 200
    assert v.patch(f"/api/embeds/{embed['id']}", json={"color": "#111111"}).status_code == 403
    assert v.post(f"/api/sites/{embed['site_id']}/knowledge/answers", json={"question": "q?", "answer": "a."}).status_code == 403
    assert v.post(f"/api/embeds/{embed['id']}/server-key").status_code == 403


def test_editor_changes_design_knowledge_and_schedule_but_not_keys_team_or_removal(client, admin, embed):
    ed = team(client, admin, embed, "editor")
    assert ed.patch(f"/api/embeds/{embed['id']}", json={"color": "#222222"}).json()["color"] == "#222222"
    assert ed.post(f"/api/sites/{embed['site_id']}/knowledge/answers", json={"question": "Hours?", "answer": "9 to 5."}).status_code == 200
    assert ed.patch(f"/api/sites/{embed['site_id']}/schedule", json={"reindex_schedule": "weekly"}).json()["reindex_schedule"] == "weekly"
    for method, path in (("post", "rotate-key"), ("post", "server-key"), ("delete", "")):
        r = getattr(ed, method)(f"/api/embeds/{embed['id']}/{path}".rstrip("/"))
        assert r.status_code == 403, path
    assert ed.post(f"/api/embeds/{embed['id']}/team", json={"email": "x@y.example", "role": "viewer"}).status_code == 403


def test_outsiders_see_nothing(client, member, embed):
    assert member.get("/api/embeds").json() == []
    assert member.get(f"/api/embeds/{embed['id']}/chats").status_code == 404


def test_change_role_remove_and_leave(client, admin, embed):
    v = team(client, admin, embed, "viewer")
    mid = admin.get(f"/api/embeds/{embed['id']}/team").json()["members"][0]["id"]
    assert admin.patch(f"/api/embeds/{embed['id']}/team/{mid}", json={"role": "editor"}).json()["role"] == "editor"
    assert v.patch(f"/api/embeds/{embed['id']}", json={"color": "#333333"}).status_code == 200
    other = team(client, admin, embed, "viewer")
    other_id = [m["id"] for m in admin.get(f"/api/embeds/{embed['id']}/team").json()["members"] if m["email"] == other.user.email][0]
    assert v.delete(f"/api/embeds/{embed['id']}/team/{other_id}").status_code == 403  # editors can't remove others
    assert v.delete(f"/api/embeds/{embed['id']}/team/{mid}").json() == {"ok": True}  # but can leave
    assert v.get("/api/embeds").json() == []


def test_invite_validation_and_email(monkeypatch, client, admin, embed):
    from app import accounts

    sent = []
    monkeypatch.setattr(accounts, "notify", lambda to, s, b: sent.append((to, s)))
    assert admin.post(f"/api/embeds/{embed['id']}/team", json={"email": "nope", "role": "viewer"}).status_code == 400
    assert admin.post(f"/api/embeds/{embed['id']}/team", json={"email": admin.user.email, "role": "viewer"}).status_code == 400
    assert admin.post(f"/api/embeds/{embed['id']}/team", json={"email": "new@colleague.example", "role": "boss"}).status_code == 422
    r = admin.post(f"/api/embeds/{embed['id']}/team", json={"email": "New@Colleague.example", "role": "editor"}).json()
    assert r["email"] == "new@colleague.example" and r["joined"] is False
    assert sent == [(["new@colleague.example"], sent[0][1])] and "added you" in sent[0][1]


# ---------- Scheduled re-index ----------

def test_schedule_and_due_logic(admin, site):
    assert admin.patch(f"/api/sites/{site.id}/schedule", json={"reindex_schedule": "daily"}).json()["reindex_schedule"] == "daily"
    assert admin.patch(f"/api/sites/{site.id}/schedule", json={"reindex_schedule": "hourly"}).status_code == 422
    db = SessionLocal()
    s = db.get(Site, site.id)
    s.indexed_at = utcnow() - timedelta(hours=2)
    db.commit()
    assert site.id not in scheduler.due_reindexes(db)
    s.indexed_at = utcnow() - timedelta(days=1, minutes=1)
    db.commit()
    assert site.id in scheduler.due_reindexes(db)
    s.reindex_schedule = "weekly"
    db.commit()
    assert site.id not in scheduler.due_reindexes(db)
    db.close()


def test_scheduler_starts_due_reindexes(monkeypatch, admin, site):
    started = []
    monkeypatch.setattr(scheduler, "start_ingestion", lambda sid: started.append(sid) or True)
    db = SessionLocal()
    s = db.get(Site, site.id)
    s.reindex_schedule, s.indexed_at = "weekly", utcnow() - timedelta(days=8)
    db.commit()
    assert scheduler.run_reindexes(db) >= 1 and site.id in started
    db.close()


# ---------- Weekly report ----------

def test_weekly_report(monkeypatch, client, admin, embed):
    sent = []
    monkeypatch.setattr(scheduler.accounts, "notify", lambda to, s, b: sent.append((to, s, b)))
    db = SessionLocal()
    e = db.get(Embed, embed["id"])
    e.last_report_at = utcnow() - timedelta(days=8)
    db.commit()
    # A quiet week: no email, but it counts as this week's report.
    scheduler.send_reports(db)
    db.refresh(e)
    assert sent == [] and utcnow() - e.last_report_at < timedelta(minutes=1)
    ask(client, embed["key"], "What do you sell?", visitor="visitorREPORT00000001", origin=f"https://{embed['site']['domain']}")
    e.last_report_at = utcnow() - timedelta(days=8)
    db.commit()
    assert scheduler.send_reports(db) == 1
    to, subject, body = sent[0]
    assert to == [admin.user.email] and "your week" in subject and "Conversations: 1" in body and "What do you sell?" in body
    assert scheduler.send_reports(db) == 0  # not again this week
    admin.patch(f"/api/embeds/{embed['id']}", json={"weekly_report": False})
    db.refresh(e)
    e.last_report_at = utcnow() - timedelta(days=8)
    db.commit()
    assert embed["id"] not in scheduler.due_reports(db)
    db.close()


# ---------- Widget extras ----------

def test_proactive_greeting_settings(admin, client, embed):
    r = admin.patch(f"/api/embeds/{embed['id']}", json={"style": {"proactive_seconds": 10, "proactive_text": "Need help choosing shoes?"}})
    assert r.json()["style"]["proactive_seconds"] == 10
    cfg = client.get(f"/api/public/{embed['key']}/config", params={"origin": f"https://{embed['site']['domain']}"}, headers=SAME).json()
    assert cfg["style"]["proactive_text"] == "Need help choosing shoes?"
    assert admin.patch(f"/api/embeds/{embed['id']}", json={"style": {"proactive_seconds": 999}}).status_code == 422


def test_page_aware_suggestions(monkeypatch, client, admin):
    from app import embeddings, suggest

    site = make_site(created_by=admin.user.id, chunks=0)
    db = SessionLocal()
    s = db.get(Site, site.id)
    s.suggestions = ["Do you ship abroad?", "What sizes do you have?", "What are your opening hours?"]
    dim = len(s.suggestions) and 384
    shipping = [0.0] * dim
    shipping[1] = 1.0
    sizes = [0.0] * dim
    sizes[2] = 1.0
    db.add(Chunk(site_id=site.id, generation=1, url=f"https://{site.domain}/shipping", title="Shipping", content="We ship worldwide.", embedding=shipping))
    db.commit()
    db.close()
    vectors = {"Do you ship abroad?": shipping, "What sizes do you have?": sizes, "What are your opening hours?": [1.0] + [0.0] * (dim - 1)}
    monkeypatch.setattr(embeddings, "embed_query", lambda q: vectors[q])
    suggest._question_vectors.clear()
    e = admin.post("/api/embeds", json={"site_id": site.id}).json()
    base = {"origin": f"https://{site.domain}"}
    on_shipping = client.get(f"/api/public/{e['key']}/config", params={**base, "page": f"https://{site.domain}/shipping"}, headers=SAME).json()
    assert on_shipping["suggestions"][0] == "Do you ship abroad?"
    unknown = client.get(f"/api/public/{e['key']}/config", params={**base, "page": f"https://{site.domain}/nothing"}, headers=SAME).json()
    assert unknown["suggestions"] == ["Do you ship abroad?", "What sizes do you have?", "What are your opening hours?"]
