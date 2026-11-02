"""Test websites: extra places a bot may run while its owner tests it (their computer, or a staging site)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.db import SessionLocal
from app.embeds import parse_test_origin
from app.models import Embed

from conftest import As, ask, cross, make_user

LOCAL = "http://localhost:5175"


def add(user, embed, origin):
    return user.post(f"/api/embeds/{embed['id']}/test-origins", json={"origin": origin})


@pytest.mark.parametrize(
    "raw, out",
    [
        ("http://localhost:5175", "http://localhost:5175"),
        ("HTTP://LocalHost:5175/", "http://localhost:5175"),
        ("localhost:5175", "http://localhost:5175"),
        ("https://127.0.0.1:8443/some/", None),
        ("http://127.0.0.1:3000", "http://127.0.0.1:3000"),
        ("http://[::1]:5173", "http://[::1]:5173"),
        ("https://staging.example.com", "https://staging.example.com"),
        ("staging.example.com:8443", "https://staging.example.com:8443"),
    ],
)
def test_accepted_addresses_are_normalised(raw, out):
    if out is None:
        with pytest.raises(HTTPException):
            parse_test_origin(raw)  # a path isn't part of a website address
    else:
        assert parse_test_origin(raw) == out


@pytest.mark.parametrize(
    "raw",
    ["http://staging.example.com", "https://*.example.com", "https://10.0.0.5", "http://192.168.1.4:3000", "ftp://localhost",
     "https://user:pw@example.com", "https://example.com?x=1", "not a url", "https://localhost:99999", "https://exa_mple.com"],
)
def test_refused_addresses(raw):
    with pytest.raises(HTTPException):
        parse_test_origin(raw)


def test_test_website_can_use_the_bot(client, admin, embed):
    key = embed["key"]
    assert client.get(f"/api/public/{key}/config", headers=cross(LOCAL)).status_code == 403
    e = add(admin, embed, "localhost:5175/").json()
    [t] = e["test_origins"]
    assert t["origin"] == LOCAL and t["active"] and t["added_by"] == admin.user.email and t["expires_at"]
    assert client.get(f"/api/public/{key}/config", headers=cross(LOCAL)).status_code == 200
    assert client.get(f"/api/public/{key}/config", headers=cross("http://localhost:5176")).status_code == 403
    # The widget page may be framed by it, and the bot's own website still works.
    csp = client.get(f"/widget/{key}").headers["content-security-policy"]
    assert f" {LOCAL}" in csp and f"https://{embed['site']['domain']}" in csp
    assert client.get(f"/api/public/{key}/config", headers=cross(f"https://{embed['site']['domain']}")).status_code == 200
    # Chats from it are tests: kept out of visitor counts and "installed".
    assert ask(client, key, "hi", visitor="visitorTESTSITE00000001", headers=cross(LOCAL)).status_code == 200
    chats = admin.get(f"/api/embeds/{embed['id']}/chats").json()
    assert chats[0]["origin"] == LOCAL and chats[0]["is_test"] is True
    e = [x for x in admin.get("/api/embeds").json() if x["id"] == embed["id"]][0]
    assert e["conversations"] == 0 and e["last_seen"]["origin"] == f"https://{embed['site']['domain']}"


def test_works_with_any_website_mode_and_https_staging(client, admin, embed):
    add(admin, embed, "https://staging.example.com")
    e = [x for x in admin.get("/api/embeds").json() if x["id"] == embed["id"]][0]
    assert e["test_origins"][0]["expires_at"] is None  # https websites don't expire
    assert client.get(f"/api/public/{embed['key']}/config", headers=cross("https://staging.example.com")).status_code == 200
    admin.patch(f"/api/embeds/{embed['id']}", json={"restrict_to_domain": False})
    add(admin, embed, LOCAL)
    assert client.get(f"/api/public/{embed['key']}/config", headers=cross(LOCAL)).status_code == 200
    assert f" {LOCAL}" in client.get(f"/widget/{embed['key']}").headers["content-security-policy"]


def test_local_addresses_expire_and_can_be_renewed(client, admin, embed):
    add(admin, embed, LOCAL)
    with SessionLocal() as db:
        e = db.get(Embed, embed["id"])
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        e.test_origins = [{**e.test_origins[0], "expires_at": past}]
        db.commit()
    assert client.get(f"/api/public/{embed['key']}/config", headers=cross(LOCAL)).status_code == 403
    assert LOCAL not in client.get(f"/widget/{embed['key']}").headers["content-security-policy"]
    e = [x for x in admin.get("/api/embeds").json() if x["id"] == embed["id"]][0]
    assert e["test_origins"][0]["active"] is False
    r = admin.post(f"/api/embeds/{embed['id']}/test-origins/renew", json={"origin": LOCAL}).json()
    expires = datetime.fromisoformat(r["test_origins"][0]["expires_at"])
    assert timedelta(days=6, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=7)
    assert client.get(f"/api/public/{embed['key']}/config", headers=cross(LOCAL)).status_code == 200
    assert admin.post(f"/api/embeds/{embed['id']}/test-origins/renew", json={"origin": "http://localhost:1"}).status_code == 404


def test_remove_limit_and_duplicates(client, admin, embed):
    for port in range(5000, 5010):
        assert add(admin, embed, f"http://localhost:{port}").status_code == 200
    assert add(admin, embed, "http://localhost:5000").status_code == 200  # already there: renewed, not duplicated
    r = add(admin, embed, "http://localhost:6000")
    assert r.status_code == 400 and "up to 10" in r.json()["detail"]
    e = admin.delete(f"/api/embeds/{embed['id']}/test-origins", params={"origin": "http://localhost:5000/"}).json()
    assert len(e["test_origins"]) == 9 and "http://localhost:5000" not in [t["origin"] for t in e["test_origins"]]
    assert client.get(f"/api/public/{embed['key']}/config", headers=cross("http://localhost:5000")).status_code == 403


def test_who_can_change_them(client, admin, member, embed):
    assert add(member, embed, LOCAL).status_code in (403, 404)  # not on the team
    editor, viewer = As(client, make_user()), As(client, make_user())
    admin.post(f"/api/embeds/{embed['id']}/team", json={"email": editor.user.email, "role": "editor"})
    admin.post(f"/api/embeds/{embed['id']}/team", json={"email": viewer.user.email, "role": "viewer"})
    assert add(viewer, embed, LOCAL).status_code == 403
    assert add(editor, embed, LOCAL).status_code == 200
    assert viewer.delete(f"/api/embeds/{embed['id']}/test-origins", params={"origin": LOCAL}).status_code == 403
    assert editor.delete(f"/api/embeds/{embed['id']}/test-origins", params={"origin": LOCAL}).status_code == 200
