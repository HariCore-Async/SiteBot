"""The public (pk_) API used by the widget and sitebot-client.js: domain lock, answers, limits, feedback."""

from conftest import SAME, ask, cross, ndjson


def origin_of(embed):
    return f"https://{embed['site']['domain']}"


def test_config_on_own_domain_and_www(client, embed):
    for o in (origin_of(embed), origin_of(embed).replace("https://", "https://www.")):
        r = client.get(f"/api/public/{embed['key']}/config", params={"origin": o}, headers=SAME)
        assert r.status_code == 200 and r.json()["name"] == embed["site"]["name"]


def test_config_refused_elsewhere(client, embed):
    for o in ("https://evil.example", "http://" + embed["site"]["domain"]):
        assert client.get(f"/api/public/{embed['key']}/config", params={"origin": o}, headers=SAME).status_code == 403


def test_unknown_key(client):
    assert client.get("/api/public/pk_nope/config", params={"origin": "https://x.example"}, headers=SAME).status_code == 404


def test_visitor_gets_a_grounded_streamed_answer_without_owner_usage(client, embed):
    events = ndjson(ask(client, embed["key"], "What do you sell?", origin=origin_of(embed)))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "user_saved" and "token" in kinds and kinds[-1] == "done"
    done = events[-1]
    assert done["grounded"] and done["sources"] and done["usage"] is None


def test_history_kept_per_visitor(client, embed):
    ask(client, embed["key"], "What do you sell?", visitor="visitorHISTORY000000001", origin=origin_of(embed))
    h = client.get(f"/api/public/{embed['key']}/messages", params={"visitor_id": "visitorHISTORY000000001", "origin": origin_of(embed)}, headers=SAME).json()
    assert [m["role"] for m in h] == ["user", "assistant"]
    other = client.get(f"/api/public/{embed['key']}/messages", params={"visitor_id": "visitorSOMEONEELSE00001", "origin": origin_of(embed)}, headers=SAME)
    assert other.json() == []


def test_not_found_answer_is_marked_ungrounded(client, embed, fakes):
    fakes.answer = "NOT_FOUND"
    done = ndjson(ask(client, embed["key"], "What is the meaning of life?", origin=origin_of(embed)))[-1]
    assert done["grounded"] is False and done["sources"] == []


def test_rate_limit_per_visitor(client, embed):
    codes = [ask(client, embed["key"], "hi", visitor="visitorRATE000000000001", origin=origin_of(embed)).status_code for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[6] == 429


def test_daily_cap_stops_politely(client, admin, embed):
    admin.patch(f"/api/admin/embeds/{embed['id']}", json={"daily_cap_usd": 0})
    events = ndjson(ask(client, embed["key"], "What do you sell?", origin=origin_of(embed)))
    assert events[-1]["type"] == "error" and "short break" in events[-1]["message"]


def test_pending_and_off_embeds_dont_answer(client, admin, embed):
    admin.patch(f"/api/embeds/{embed['id']}", json={"enabled": False})
    assert client.get(f"/api/public/{embed['key']}/config", params={"origin": origin_of(embed)}, headers=SAME).status_code == 404
    admin.patch(f"/api/embeds/{embed['id']}", json={"enabled": True})
    admin.patch(f"/api/admin/embeds/{embed['id']}", json={"status": "pending"})
    assert client.get(f"/api/public/{embed['key']}/config", params={"origin": origin_of(embed)}, headers=SAME).status_code == 404


def test_preview_needs_owner_signin_and_is_a_test_chat(client, admin, embed):
    assert client.get(f"/api/public/{embed['key']}/config", params={"preview": "true"}, headers=SAME).status_code == 403
    assert admin.get(f"/api/public/{embed['key']}/config", params={"preview": "true"}, headers=SAME).status_code == 200
    admin.post(f"/api/public/{embed['key']}/messages", headers=SAME, json={"visitor_id": "previewVisitor00000001", "content": "hi", "preview": True})
    chats = admin.get(f"/api/embeds/{embed['id']}/chats").json()
    assert chats[0]["is_test"] is True
    e = [x for x in admin.get("/api/embeds").json() if x["id"] == embed["id"]][0]
    assert e["conversations"] == 0 and e["chats_today"] == 0


def test_client_js_cross_origin_uses_real_origin_header(client, admin, embed):
    key, own = embed["key"], origin_of(embed)
    r = client.get(f"/api/public/{key}/config", headers=cross(own))
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == own
    assert client.get(f"/api/public/{key}/config", headers=cross("https://evil.example")).status_code == 403
    # A claimed origin can't override the browser's Origin header.
    assert client.get(f"/api/public/{key}/config", params={"origin": own}, headers=cross("https://evil.example")).status_code == 403
    # Cross-site with no Origin header at all is refused.
    assert client.get(f"/api/public/{key}/config", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_old_browsers_without_sec_fetch_site(client, embed):
    key, own = embed["key"], origin_of(embed)
    assert client.get(f"/api/public/{key}/config", headers={"Origin": own}).status_code == 200
    assert client.get(f"/api/public/{key}/config", headers={"Origin": "https://evil.example"}).status_code == 403


def test_cors_preflight_without_credentials(client, embed):
    r = client.options(f"/api/public/{embed['key']}/messages", headers={"Origin": "https://x.example", "Access-Control-Request-Method": "POST"})
    assert r.status_code == 204 and "POST" in r.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in r.headers


def test_domain_lock_off_allows_any_https_site(client, admin, embed):
    admin.patch(f"/api/embeds/{embed['id']}", json={"restrict_to_domain": False})
    assert client.get(f"/api/public/{embed['key']}/config", headers=cross("https://other-shop.example")).status_code == 200
    assert client.get(f"/api/public/{embed['key']}/config", headers=cross("http://other-shop.example")).status_code == 403
    ask(client, embed["key"], "hi", visitor="visitorELSEWHERE0000001", headers=cross("https://other-shop.example"))
    chats = admin.get(f"/api/embeds/{embed['id']}/chats").json()
    assert chats[0]["origin"] == "https://other-shop.example"


def test_feedback_on_answers(client, admin, embed):
    done = ndjson(ask(client, embed["key"], "What do you sell?", visitor="visitorFEEDBACK00000001", origin=origin_of(embed)))[-1]
    body = {"visitor_id": "visitorFEEDBACK00000001", "message_id": done["message_id"], "rating": "up", "origin": origin_of(embed)}
    assert client.post(f"/api/public/{embed['key']}/feedback", json=body, headers=SAME).json() == {"ok": True}
    body["visitor_id"] = "visitorSOMEONEELSE00002"
    assert client.post(f"/api/public/{embed['key']}/feedback", json=body, headers=SAME).status_code == 404
    e = [x for x in admin.get("/api/embeds").json() if x["id"] == embed["id"]][0]
    assert e["feedback"]["up"] == 1


def test_install_check_records_page_loads_but_not_previews(client, admin, embed):
    admin.get(f"/api/public/{embed['key']}/config", params={"preview": "true"}, headers=SAME)
    assert admin.get("/api/embeds").json()[0]["last_seen"] is None
    client.get(f"/api/public/{embed['key']}/config", params={"origin": origin_of(embed)}, headers=SAME)
    assert admin.get("/api/embeds").json()[0]["last_seen"]["origin"] == origin_of(embed)


def test_usage_charged_to_owner_and_embed(client, admin, embed):
    ask(client, embed["key"], "What do you sell?", visitor="visitorBILLING000000001", origin=origin_of(embed))
    e = admin.get("/api/embeds").json()[0]
    assert e["spent_today_usd"] > 0
    assert admin.get("/api/usage").json()["user_spent"] > 0


def test_static_scripts_served(client):
    import pytest

    if b"Frontend not built" in client.get("/embed.js").content:
        pytest.skip("frontend/dist not built")
    for path in ("/embed.js", "/sitebot-client.js", "/widget-test.html"):
        r = client.get(path)
        assert r.status_code == 200 and b"Frontend not built" not in r.content, path
