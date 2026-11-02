"""Provider alerts and AI health, test-website approval, and signing out everywhere."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from sqlalchemy import delete

from app import health, llm
from app.config import settings
from app.db import SessionLocal
from app.models import AIFailure, ProviderAlert, UsageEvent

from conftest import As, cross, make_site, make_user, session_for

REAL_COMPLETE = llm.complete  # conftest swaps in a fake per test; this is the real fallback loop


@pytest.fixture
def mail(monkeypatch):
    sent = []
    monkeypatch.setattr("app.accounts.notify", lambda to, subject, body: sent.append((sorted(to), subject, body)))
    with SessionLocal() as db:
        db.execute(delete(ProviderAlert))
        db.execute(delete(AIFailure))
        db.commit()
    health._open = None
    return sent


def failing_model(monkeypatch, status, message="boom"):
    t = SimpleNamespace(label="AcmeAI · acme-1", model="acme-1")

    def boom(*a, **k):
        raise llm.LLMError(f"AcmeAI · acme-1: error {status}: {message}", status)

    monkeypatch.setattr(llm, "_targets", lambda purpose, site_id: [t])
    monkeypatch.setattr(llm, "complete_with", boom)


def call():
    with pytest.raises(llm.LLMError):
        REAL_COMPLETE("answer", [{"role": "user", "content": "hi"}])


def test_out_of_credit_alerts_admins_once_an_hour_and_clears_when_it_works(monkeypatch, admin, mail):
    failing_model(monkeypatch, 402, "This request requires more credits")
    call()
    alerts = admin.get("/api/admin/ai/health").json()["alerts"]
    assert len(alerts) == 1 and alerts[0]["provider"] == "AcmeAI" and alerts[0]["kind"] == "credit"
    assert len(mail) == 1 and "AcmeAI" in mail[0][1] and admin.user.email in mail[0][0] and "out of credit" in mail[0][2]
    call()
    assert len(mail) == 1  # not again within the hour
    assert admin.get("/api/admin/ai/health").json()["alerts"][0]["failures"] == 2
    # It works again: the alert clears by itself.
    monkeypatch.setattr(llm, "complete_with", lambda *a, **k: ("ok", {}))
    REAL_COMPLETE("answer", [{"role": "user", "content": "hi"}])
    assert admin.get("/api/admin/ai/health").json()["alerts"] == []


def test_repeated_failures_alert_but_a_few_dont(monkeypatch, admin, mail):
    failing_model(monkeypatch, 503, "overloaded")
    for _ in range(health.FAILING_COUNT - 1):
        call()
    assert admin.get("/api/admin/ai/health").json()["alerts"] == [] and mail == []
    call()
    [alert] = admin.get("/api/admin/ai/health").json()["alerts"]
    assert alert["kind"] == "failing" and len(mail) == 1 and "failed 5 times" in mail[0][2]


def test_admin_can_dismiss_and_members_cant_see(monkeypatch, admin, member, mail):
    failing_model(monkeypatch, 402)
    call()
    alert_id = admin.get("/api/admin/ai/health").json()["alerts"][0]["id"]
    assert member.get("/api/admin/ai/health").status_code == 403
    assert member.post(f"/api/admin/ai/alerts/{alert_id}/dismiss").status_code == 403
    assert admin.post(f"/api/admin/ai/alerts/{alert_id}/dismiss").json() == {"ok": True}
    assert admin.get("/api/admin/ai/health").json()["alerts"] == []


def test_health_counts_the_last_24_hours(monkeypatch, admin, mail):
    with SessionLocal() as db:
        db.add(UsageEvent(user_id=admin.user.id, kind="answer", model="acme-1", provider="AcmeAI", cost_usd=0.01))
        db.add(UsageEvent(user_id=admin.user.id, kind="answer", model="acme-1", provider="AcmeAI", cost_usd=0.02))
        old = datetime.now(timezone.utc) - timedelta(days=2)
        db.add(UsageEvent(user_id=admin.user.id, kind="answer", model="acme-1", provider="AcmeAI", cost_usd=5, created_at=old))
        db.commit()
    failing_model(monkeypatch, 500, "server error")
    call()
    row = [p for p in admin.get("/api/admin/ai/health").json()["providers"] if p["provider"] == "AcmeAI"][0]
    assert row["ok"] >= 2 and row["errors"] == 1 and row["requests"] == row["ok"] + 1
    assert 0.03 <= row["spend_usd"] < 5 and "server error" in row["last_error"]["message"]


def test_out_of_credit_detection():
    assert health.is_out_of_credit(402, "")
    assert health.is_out_of_credit(200, "This request requires more credits, or fewer max_tokens")
    assert health.is_out_of_credit(429, "You exceeded your current quota: insufficient_quota")
    assert not health.is_out_of_credit(503, "overloaded")


# ---------- Test websites need an admin for real websites ----------

def member_embed(admin, member, site):
    e = member.post("/api/embeds", json={"site_id": site.id}).json()
    admin.patch(f"/api/admin/embeds/{e['id']}", json={"status": "approved"})
    return e


def test_https_test_website_from_a_member_waits_for_an_admin(client, admin, member, mail):
    site = make_site(created_by=member.user.id)
    e = member_embed(admin, member, site)
    sent_before = len(mail)
    r = member.post(f"/api/embeds/{e['id']}/test-origins", json={"origin": "https://staging.example.com"}).json()
    [t] = r["test_origins"]
    assert t["status"] == "pending" and t["active"] is False
    assert len(mail) == sent_before + 1 and "staging.example.com" in mail[-1][1]
    assert client.get(f"/api/public/{e['key']}/config", headers=cross("https://staging.example.com")).status_code == 403
    pending = [x for x in admin.get("/api/admin/test-origins").json() if x["embed_id"] == e["id"]]
    assert pending[0]["status"] == "pending" and pending[0]["owner"] == member.user.email
    assert member.post(f"/api/admin/embeds/{e['id']}/test-origins/approve", json={"origin": "https://staging.example.com"}).status_code == 403
    assert admin.post(f"/api/admin/embeds/{e['id']}/test-origins/approve", json={"origin": "https://staging.example.com"}).json() == {"ok": True}
    assert client.get(f"/api/public/{e['key']}/config", headers=cross("https://staging.example.com")).status_code == 200
    # Renewing or re-adding keeps it approved.
    r = member.post(f"/api/embeds/{e['id']}/test-origins", json={"origin": "https://staging.example.com"}).json()
    assert r["test_origins"][0]["status"] == "approved"
    # An admin can remove it from the Admin console.
    assert admin.delete(f"/api/admin/embeds/{e['id']}/test-origins", params={"origin": "https://staging.example.com"}).json() == {"ok": True}
    assert client.get(f"/api/public/{e['key']}/config", headers=cross("https://staging.example.com")).status_code == 403


def test_localhost_from_a_member_and_https_from_an_admin_are_instant(client, admin, member, embed, mail):
    site = make_site(created_by=member.user.id)
    e = member_embed(admin, member, site)
    r = member.post(f"/api/embeds/{e['id']}/test-origins", json={"origin": "http://localhost:5175"}).json()
    assert r["test_origins"][0]["status"] == "approved"
    assert client.get(f"/api/public/{e['key']}/config", headers=cross("http://localhost:5175")).status_code == 200
    r = admin.post(f"/api/embeds/{embed['id']}/test-origins", json={"origin": "https://qa.example.org"}).json()
    assert r["test_origins"][0]["status"] == "approved"
    assert client.get(f"/api/public/{embed['key']}/config", headers=cross("https://qa.example.org")).status_code == 200


def test_entries_saved_before_approval_existed_still_work(client, admin, embed):
    from app.models import Embed

    with SessionLocal() as db:
        e = db.get(Embed, embed["id"])
        e.test_origins = [{"origin": "https://old.example.com", "added_at": "2026-11-02T00:00:00+00:00", "expires_at": None, "added_by": "x@y.z"}]
        db.commit()
    assert client.get(f"/api/public/{embed['key']}/config", headers=cross("https://old.example.com")).status_code == 200


# ---------- Signing out everywhere ----------

def test_sign_out_everywhere_ends_all_sessions(client):
    u = make_user()
    phone, laptop = As(client, u), As(client, u)
    assert phone.get("/api/me").status_code == 200 and laptop.get("/api/me").status_code == 200
    r = phone.post("/api/auth/logout-everywhere")
    assert r.status_code == 200 and "sitebot_session" in r.headers.get("set-cookie", "")
    assert phone.get("/api/me").status_code == 401 and laptop.get("/api/me").status_code == 401


def test_admin_can_sign_a_user_out(client, admin, member):
    assert member.get("/api/me").status_code == 200
    assert member.post(f"/api/admin/users/{admin.user.id}/sign-out").status_code == 403
    assert admin.post(f"/api/admin/users/{member.user.id}/sign-out").json() == {"ok": True}
    assert member.get("/api/me").status_code == 401
    # A new sign-in gets a session with the new version.
    fresh = jwt.encode({"sub": str(member.user.id), "tv": 1, "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, settings.secret_key, algorithm="HS256")
    member.cookies = {"sitebot_session": fresh}
    assert member.get("/api/me").status_code == 200


def test_previous_secret_key_works_during_rotation(client, monkeypatch):
    u = make_user()
    old = jwt.encode({"sub": str(u.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "the-old-secret-key-from-before-rotation", algorithm="HS256")
    user = As(client, u)
    user.cookies = {"sitebot_session": old}
    assert user.get("/api/me").status_code == 401
    monkeypatch.setattr(settings, "secret_key_previous", "the-old-secret-key-from-before-rotation")
    assert user.get("/api/me").status_code == 200
    expired = jwt.encode({"sub": str(u.id), "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, settings.secret_key, algorithm="HS256")
    user.cookies = {"sitebot_session": expired}
    assert user.get("/api/me").status_code == 401
    user.cookies = session_for(u)
    assert user.get("/api/me").status_code == 200
