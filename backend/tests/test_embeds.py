"""Owner and admin side of website embeds: requests, approval, settings, keys, the domain lock switch."""

from conftest import SAME, make_site


def test_admin_request_is_approved_at_once(embed):
    assert embed["status"] == "approved" and embed["enabled"] and embed["restrict_to_domain"]


def test_member_request_waits_for_admin_and_can_be_rejected_with_reason(client, member, admin):
    site = make_site(created_by=member.user.id)
    e = member.post("/api/embeds", json={"site_id": site.id}).json()
    assert e["status"] == "pending"
    r = admin.patch(f"/api/admin/embeds/{e['id']}", json={"status": "rejected", "note": "Use your company site."})
    assert r.json()["review_note"] == "Use your company site."
    mine = member.get("/api/embeds").json()[0]
    assert mine["status"] == "rejected" and mine["review_note"] == "Use your company site."
    again = member.post("/api/embeds", json={"site_id": site.id}).json()
    assert again["status"] == "pending" and again["review_note"] == ""


def test_member_cannot_embed_someone_elses_bot(member, site):
    assert member.post("/api/embeds", json={"site_id": site.id}).status_code == 403


def test_owner_only_sees_and_edits_their_embeds(member, embed):
    assert member.get("/api/embeds").json() == []
    assert member.patch(f"/api/embeds/{embed['id']}", json={"color": "#000000"}).status_code == 404


def test_customise_and_validation(admin, embed):
    r = admin.patch(f"/api/embeds/{embed['id']}", json={"color": "#7c3aed", "position": "left", "greeting": "Hello!",
                                                        "style": {"title": "Help", "theme": "dark", "radius": 4, "font": "serif",
                                                                  "custom_css": ".w-head{color:red} @import url(x);"}})
    e = r.json()
    assert e["color"] == "#7c3aed" and e["position"] == "left" and e["style"]["theme"] == "dark"
    assert "@import" not in e["style"]["custom_css"]
    assert admin.patch(f"/api/embeds/{embed['id']}", json={"color": "red"}).status_code == 422
    assert admin.patch(f"/api/embeds/{embed['id']}", json={"style": {"font": "comic"}}).status_code == 422


def test_rotate_key_kills_old_snippet(client, admin, embed):
    old = embed["key"]
    new = admin.post(f"/api/embeds/{embed['id']}/rotate-key").json()["key"]
    origin = f"https://{embed['site']['domain']}"
    assert client.get(f"/api/public/{old}/config", params={"origin": origin}, headers=SAME).status_code == 404
    assert client.get(f"/api/public/{new}/config", params={"origin": origin}, headers=SAME).status_code == 200


def test_domain_lock_switch_is_admin_only(client, member, admin):
    site = make_site(created_by=member.user.id)
    e = member.post("/api/embeds", json={"site_id": site.id}).json()
    assert member.patch(f"/api/embeds/{e['id']}", json={"restrict_to_domain": False}).status_code == 403
    assert member.patch(f"/api/admin/embeds/{e['id']}", json={"restrict_to_domain": False}).status_code == 403
    assert admin.patch(f"/api/admin/embeds/{e['id']}", json={"restrict_to_domain": False}).json()["restrict_to_domain"] is False


def test_widget_page_csp(client, admin, embed):
    d = embed["site"]["domain"]
    csp = client.get(f"/widget/{embed['key']}").headers.get("content-security-policy", "")
    assert f"frame-ancestors 'self' https://{d} https://*.{d}" in csp and "connect-src 'self'" in csp
    admin.patch(f"/api/embeds/{embed['id']}", json={"restrict_to_domain": False})
    assert "frame-ancestors 'self' https:" in client.get(f"/widget/{embed['key']}").headers["content-security-policy"]
    assert client.get("/widget/pk_unknown").headers["content-security-policy"].endswith("frame-ancestors 'self'")


def test_daily_limit_editable_by_admin_only(admin, member, embed):
    assert admin.patch(f"/api/admin/embeds/{embed['id']}", json={"daily_cap_usd": 0.75}).json()["daily_cap_usd"] == 0.75
    assert member.patch(f"/api/admin/embeds/{embed['id']}", json={"daily_cap_usd": 5}).status_code == 403


def test_review_emails(monkeypatch, client, member, admin):
    from app import accounts

    sent = []
    monkeypatch.setattr(accounts, "notify", lambda to, subject, body: sent.append((sorted(to), subject)))
    site = make_site(created_by=member.user.id)
    e = member.post("/api/embeds", json={"site_id": site.id}).json()
    assert any("wants to add" in s for _, s in sent) and any(admin.user.email in to for to, _ in sent)
    admin.patch(f"/api/admin/embeds/{e['id']}", json={"status": "approved"})
    assert any("is approved" in s and to == [member.user.email] for to, s in sent)


def test_delete_embed(admin, embed):
    assert admin.delete(f"/api/embeds/{embed['id']}").json() == {"ok": True}
    assert admin.get("/api/embeds").json() == []
