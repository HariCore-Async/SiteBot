"""Billing scaffolding: invisible and inert unless BILLING_ENABLED; when on, admins manage plans and assign them."""

from app.config import settings


def test_off_by_default(client, admin):
    assert client.get("/api/config").json()["billing_enabled"] is False
    assert admin.get("/api/admin/plans").status_code == 404
    assert admin.post("/api/admin/plans", json={"name": "Pro"}).status_code == 404


def test_plans_when_enabled(monkeypatch, client, admin, member):
    monkeypatch.setattr(settings, "billing_enabled", True)
    assert member.get("/api/admin/plans").status_code == 403
    p = admin.post("/api/admin/plans", json={"name": "Starter", "price_usd_month": 19, "credit_usd_month": 5, "max_bots": 3, "max_embeds": 1}).json()
    assert p["name"] == "Starter" and p["users"] == 0
    assert admin.post("/api/admin/plans", json={"name": "Bad", "price_usd_month": -1}).status_code == 422
    p = admin.put(f"/api/admin/plans/{p['id']}", json={"name": "Starter", "price_usd_month": 29, "credit_usd_month": 5}).json()
    assert p["price_usd_month"] == 29
    assert admin.patch(f"/api/admin/users/{member.user.id}/plan", json={"plan_id": p["id"]}).json()["plan_id"] == p["id"]
    assert admin.get("/api/admin/plans").json()[0]["users"] == 1
    assert admin.patch(f"/api/admin/users/{member.user.id}/plan", json={"plan_id": 999999}).status_code == 400
    assert admin.delete(f"/api/admin/plans/{p['id']}").json() == {"ok": True}
    users = {u["id"]: u for u in admin.get("/api/admin/users").json()}
    assert users[member.user.id]["plan_id"] is None
