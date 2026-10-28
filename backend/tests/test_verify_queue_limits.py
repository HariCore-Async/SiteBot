"""Domain verification, the indexing queue (resume after restart, order) and Redis-backed shared rate limits."""

import os

import httpx
import pytest

from app import embeds, ingest, verify
from app.db import SessionLocal
from app.models import Site
from conftest import make_site


class FakeHTTP:
    """Stands in for httpx in verify.py: pages and DNS answers by URL."""

    def __init__(self, pages=None, txt=None):
        self.pages, self.txt = pages or {}, txt or []

    def stream(self, method, url, **kw):
        body = self.pages.get(url)
        transport = httpx.MockTransport(lambda r: httpx.Response(200, text=body) if body is not None else httpx.Response(404))
        return httpx.Client(transport=transport).stream(method, url)

    def get(self, url, params=None, **kw):
        return httpx.Response(200, json={"Answer": [{"data": f'"{t}"'} for t in self.txt]}, request=httpx.Request("GET", url))


def test_meta_tag_matching():
    token = "abc123"
    assert verify._has_meta(f'<head><meta name="sitebot-verification" content="{token}"></head>', token)
    assert verify._has_meta(f"<META CONTENT='{token}' NAME='sitebot-verification' />", token)
    assert not verify._has_meta('<meta name="sitebot-verification" content="other">', token)
    assert not verify._has_meta(f'<meta name="description" content="{token}">', token)


def test_check_meta_and_dns():
    t = "tok"
    ok, _ = verify.check_meta("shop.example", t, FakeHTTP({"https://www.shop.example/": verify.meta_tag(t)}))
    assert ok
    ok, why = verify.check_meta("shop.example", t, FakeHTTP({"https://shop.example/": "<html></html>"}))
    assert not ok and "no matching tag" in why
    assert verify.check_dns("shop.example", t, FakeHTTP(txt=["v=spf1 -all", verify.dns_value(t)]))[0]
    assert not verify.check_dns("shop.example", t, FakeHTTP(txt=["v=spf1 -all"]))[0]


def test_verified_owner_skips_approval(monkeypatch, member, admin):
    site = make_site(created_by=member.user.id)
    e = member.post("/api/embeds", json={"site_id": site.id}).json()
    assert e["status"] == "pending" and e["verification"]["meta_tag"].startswith('<meta name="sitebot-verification"')
    token = e["verification"]["meta_tag"].split('content="')[1].split('"')[0]
    monkeypatch.setattr(verify, "check_meta", lambda domain, tok, http=None: (False, "no matching tag on https://x/"))
    r = member.post(f"/api/embeds/{e['id']}/verify", json={"method": "meta"})
    assert r.status_code == 400 and "Not verified yet" in r.json()["detail"]
    monkeypatch.setattr(verify, "check_meta", lambda domain, tok, http=None: (domain == site.domain and tok == token, ""))
    r = member.post(f"/api/embeds/{e['id']}/verify", json={"method": "meta"}).json()
    assert r["status"] == "approved" and r["verification"]["verified_at"] and r["verification"]["via"] == "meta"
    assert r["reviewed_by"] == "domain verification"


def test_verification_does_not_override_an_admin_rejection(monkeypatch, member, admin):
    site = make_site(created_by=member.user.id)
    e = member.post("/api/embeds", json={"site_id": site.id}).json()
    admin.patch(f"/api/admin/embeds/{e['id']}", json={"status": "rejected", "note": "No."})
    member.post("/api/embeds", json={"site_id": site.id})  # ask again: pending
    monkeypatch.setattr(verify, "check_dns", lambda domain, tok, http=None: (True, ""))
    r = member.post(f"/api/embeds/{e['id']}/verify", json={"method": "dns"}).json()
    assert r["verification"]["verified_at"] and r["status"] == "pending"


def test_only_owner_verifies(client, admin, embed, member):
    assert member.post(f"/api/embeds/{embed['id']}/verify", json={"method": "meta"}).status_code == 404
    assert admin.post(f"/api/embeds/{embed['id']}/verify", json={"method": "ftp"}).status_code == 422


# ---------- Indexing queue ----------

def test_interrupted_indexing_resumes_after_restart_with_a_cap(monkeypatch):
    started = []
    monkeypatch.setattr(ingest, "start_ingestion", lambda sid: started.append(sid) or True)
    site = make_site()
    db = SessionLocal()
    s = db.get(Site, site.id)
    s.status, s.message, s.resumes = "queued", ingest.RESUME_MESSAGE, 0
    db.commit()
    ingest.resume_interrupted()
    db.refresh(s)
    assert site.id in started and s.resumes == 1
    started.clear()
    s.status, s.message, s.resumes = "queued", ingest.RESUME_MESSAGE, 2
    db.commit()
    ingest.resume_interrupted()
    db.refresh(s)
    assert site.id not in started and s.status == "ready" and "kept being interrupted" in s.message
    db.close()


def test_init_db_marks_unfinished_indexing_for_resume():
    from app.db import init_db

    site = make_site()
    db = SessionLocal()
    s = db.get(Site, site.id)
    s.status = "crawling"
    db.commit()
    init_db()
    db.refresh(s)
    assert s.status == "queued" and s.message == ingest.RESUME_MESSAGE
    s.status = "ready"
    db.commit()
    db.close()


def test_queue_runs_in_order(monkeypatch):
    import threading

    order, gate = [], threading.Event()
    monkeypatch.setattr(ingest, "_slots", threading.Semaphore(1))

    def fake_run(site_id):
        order.append(site_id)
        if site_id == 1:
            gate.wait(5)

    monkeypatch.setattr(ingest, "run_ingestion", fake_run)
    monkeypatch.setattr(ingest, "_set_message", lambda sid, msg: None)
    threads = [threading.Thread(target=ingest._run, args=(i,)) for i in (1, 2, 3)]
    threads[0].start()
    import time

    time.sleep(0.2)
    threads[1].start()
    time.sleep(0.2)
    threads[2].start()
    time.sleep(0.2)
    assert ingest.queue_position(3) == 1 and ingest.queue_position(2) == 0
    gate.set()
    for t in threads:
        t.join(10)
    assert order == [1, 2, 3]


# ---------- Shared rate limits ----------

@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="set TEST_REDIS_URL to test Redis-backed limits")
def test_redis_limits_are_shared_between_app_copies(monkeypatch):
    monkeypatch.setattr(embeds.settings, "redis_url", os.environ["TEST_REDIS_URL"])
    monkeypatch.setattr(embeds, "_redis_client", None)
    monkeypatch.setattr(embeds, "_redis_failed_at", 0.0)
    key = f"k{os.getpid()}-{id(object())}"
    one, two = embeds.RateLimiter([(3, 60)], "test"), embeds.RateLimiter([(3, 60)], "test")  # two "servers"
    assert [one.allow(key), two.allow(key), one.allow(key), two.allow(key)] == [True, True, True, False]
    assert one.hits == {} and two.hits == {}  # nothing counted in memory


def test_redis_outage_falls_back_to_memory(monkeypatch):
    monkeypatch.setattr(embeds.settings, "redis_url", "redis://127.0.0.1:1/0")  # nothing listens there
    monkeypatch.setattr(embeds, "_redis_client", None)
    monkeypatch.setattr(embeds, "_redis_failed_at", 0.0)
    rl = embeds.RateLimiter([(2, 60)], "fallback")
    assert [rl.allow("k"), rl.allow("k"), rl.allow("k")] == [True, True, False]
    monkeypatch.setattr(embeds.settings, "redis_url", "")
