"""The server (sk_) API for customers who build their own UI on their backend."""

from conftest import ndjson


def key_for(admin, embed):
    return admin.post(f"/api/embeds/{embed['id']}/server-key").json()["secret"]


def test_key_shown_once_and_never_listed(admin, embed):
    secret = key_for(admin, embed)
    assert secret.startswith("sk_")
    listed = admin.get("/api/embeds").json()[0]
    assert secret not in str(listed) and listed["server_key"]["hint"] == secret[-4:]


def test_auth(client, admin, embed):
    secret = key_for(admin, embed)
    assert client.get("/api/v1/bot").status_code == 401
    assert client.get("/api/v1/bot", headers={"Authorization": "Bearer sk_wrong"}).status_code == 401
    assert client.get("/api/v1/bot", headers={"Authorization": f"Bearer {embed['key']}"}).status_code == 401
    assert client.get("/api/v1/bot", headers={"Authorization": f"Bearer {secret}"}).json()["domain"] == embed["site"]["domain"]


def test_refused_from_browsers(client, admin, embed):
    h = {"Authorization": f"Bearer {key_for(admin, embed)}", "Origin": f"https://{embed['site']['domain']}"}
    assert client.get("/api/v1/bot", headers=h).status_code == 403


def test_answers_stream_and_json_and_conversations(client, admin, embed):
    h = {"Authorization": f"Bearer {key_for(admin, embed)}"}
    one = client.post("/api/v1/messages", headers=h, json={"visitor_id": "crm-user-1", "content": "What do you sell?", "stream": False}).json()
    assert one["answer"] and one["sources"] and one["grounded"]
    events = ndjson(client.post("/api/v1/messages", headers=h, json={"visitor_id": "crm-user-1", "content": "And trail shoes?", "conversation_id": one["conversation_id"]}))
    assert events[0] == {"type": "conversation", "conversation_id": one["conversation_id"]} and events[-1]["type"] == "done"
    msgs = client.get(f"/api/v1/conversations/{one['conversation_id']}/messages", params={"visitor_id": "crm-user-1"}, headers=h).json()
    assert len(msgs) == 4
    assert client.get(f"/api/v1/conversations/{one['conversation_id']}/messages", params={"visitor_id": "someone-else"}, headers=h).status_code == 404
    fresh = client.post("/api/v1/messages", headers=h, json={"visitor_id": "crm-user-1", "content": "hi", "new_conversation": True, "stream": False}).json()
    assert fresh["conversation_id"] != one["conversation_id"]
    assert client.post("/api/v1/messages", headers=h, json={"visitor_id": "bad id!", "content": "hi"}).status_code == 422
    fb = client.post("/api/v1/feedback", headers=h, json={"message_id": one["message_id"], "rating": "down", "comment": "too long"})
    assert fb.json() == {"ok": True}


def test_daily_cap_returns_503(client, admin, embed):
    h = {"Authorization": f"Bearer {key_for(admin, embed)}"}
    admin.patch(f"/api/admin/embeds/{embed['id']}", json={"daily_cap_usd": 0})
    r = client.post("/api/v1/messages", headers=h, json={"visitor_id": "crm-user-2", "content": "What do you sell?", "stream": False})
    assert r.status_code == 503 and "short break" in r.json()["detail"]


def test_replace_and_revoke(client, admin, embed):
    old = key_for(admin, embed)
    new = key_for(admin, embed)
    assert client.get("/api/v1/bot", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert client.get("/api/v1/bot", headers={"Authorization": f"Bearer {new}"}).status_code == 200
    admin.delete(f"/api/embeds/{embed['id']}/server-key")
    assert client.get("/api/v1/bot", headers={"Authorization": f"Bearer {new}"}).status_code == 401


def test_last_used_is_shown(client, admin, embed):
    secret = key_for(admin, embed)
    assert admin.get("/api/embeds").json()[0]["server_key"]["last_used_at"] is None
    client.get("/api/v1/bot", headers={"Authorization": f"Bearer {secret}"})
    assert admin.get("/api/embeds").json()[0]["server_key"]["last_used_at"] is not None
