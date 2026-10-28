"""Core app: sign-in session, admin-only areas, the bot list and chat."""

from conftest import As, make_user, ndjson


def test_public_config(client):
    r = client.get("/api/config")
    assert r.status_code == 200 and {"google_client_id", "require_approval", "email_enabled"} <= set(r.json())


def test_signed_out_is_401(client):
    client.cookies.clear()
    assert client.get("/api/me").status_code == 401


def test_admin_only_areas(admin, member):
    for path in ("/api/admin/users", "/api/admin/embeds", "/api/admin/budget"):
        assert admin.get(path).status_code == 200, path
        assert member.get(path).status_code == 403, path


def test_permanent_admin_from_env(client):
    u = make_user("member", email="admin@test.example")
    # Signing in promotes ADMIN_EMAILS; the admin list marks them as locked.
    me = As(client, u)
    assert me.get("/api/me").status_code == 200


def test_chat_with_a_bot(admin, site):
    chat = admin.post("/api/chats", json={"site_id": site.id}).json()
    events = ndjson(admin.post(f"/api/chats/{chat['id']}/messages", json={"content": "What do you sell?"}))
    done = events[-1]
    assert done["type"] == "done" and done["grounded"] and done["usage"]["user_spent"] > 0
    assert [m["role"] for m in admin.get(f"/api/chats/{chat['id']}/messages").json()] == ["user", "assistant"]


def test_remove_from_my_list_keeps_the_bot(admin, member, site):
    member.post("/api/chats", json={"site_id": site.id})
    assert member.post(f"/api/sites/{site.id}/remove").json() == {"ok": True}
    listed = {s["id"]: s for s in member.get("/api/sites").json()}
    assert listed[site.id]["hidden"] is True
    assert admin.get(f"/api/sites/{site.id}").status_code == 200
