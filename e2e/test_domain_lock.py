"""The per-chatbot "Only allow on <domain>" switch: API rules, then a browser on another (https) website."""

import json

import requests

from conftest import SEL, login, widget_visibility

state = {}


def X(origin):
    return {"Origin": origin, "Sec-Fetch-Site": "cross-site"}


def test_domain_lock_rules(env, check):
    B, A, M = env.B, env.api("admin"), env.api("member")
    e = A.post(f"{B}/api/embeds", json={"site_id": env.site_id}).json()
    key, eid, domain = e["key"], e["id"], e["site"]["domain"]

    def cfg(h, **params):
        return requests.get(f"{B}/api/public/{key}/config", params=params, headers=h)

    check("new embeds are locked to their domain", e["restrict_to_domain"] is True)
    check("locked: own domain works", cfg(X(f"https://{domain}")).status_code == 200)
    r = cfg(X("https://other-shop.example"))
    check("locked: another website refused", r.status_code == 403 and domain in r.json()["detail"])
    check("locked: widget CSP only frames the bot's domain", f"https://*.{domain}" in requests.get(f"{B}/widget/{key}").headers["content-security-policy"])

    r = A.patch(f"{B}/api/embeds/{eid}", json={"restrict_to_domain": False})
    check("admin can switch the lock off (embed page)", r.status_code == 200 and r.json()["restrict_to_domain"] is False, r.text[:200])
    check("unlocked: another https website works (client.js path)", cfg(X("https://other-shop.example")).status_code == 200)
    check("unlocked: widget path with another website works", cfg({"Sec-Fetch-Site": "same-origin"}, origin="https://other-shop.example").status_code == 200)
    r = cfg(X("http://other-shop.example"))
    check("unlocked: plain http still refused", r.status_code == 403 and "https" in r.json()["detail"], r.text)
    csp = requests.get(f"{B}/widget/{key}").headers["content-security-policy"]
    check("unlocked: widget CSP lets any https site frame it", "frame-ancestors 'self' https:" in csp, csp)
    r = requests.options(f"{B}/api/public/{key}/messages", headers={"Origin": "https://other-shop.example", "Access-Control-Request-Method": "POST"})
    check("unlocked: CORS preflight from any origin", r.status_code == 204 and r.headers.get("access-control-allow-origin") == "https://other-shop.example")

    r = requests.post(f"{B}/api/public/{key}/messages", json={"visitor_id": "lockVisitorAAAAAAAAAAAA1", "content": "hi"}, headers=X("https://other-shop.example"), stream=True)
    events = [json.loads(line) for line in r.iter_lines() if line]
    check("unlocked: visitor on another site gets answers", r.status_code == 200 and events[-1]["type"] == "done", events[-1:])
    chats = A.get(f"{B}/api/embeds/{eid}/chats").json()
    check("conversation records which website it came from", chats and chats[0]["origin"] == "https://other-shop.example", chats[:1])
    check("admin list shows the lock state", A.get(f"{B}/api/admin/embeds").json()[0]["restrict_to_domain"] is False)

    sk = A.post(f"{B}/api/embeds/{eid}/server-key").json()["secret"]
    check("sk_ still refused from a browser", requests.get(f"{B}/api/v1/bot", headers={"Authorization": f"Bearer {sk}", "Origin": "https://other-shop.example"}).status_code == 403)

    env.member_embeds()
    me_embed = [x for x in M.get(f"{B}/api/embeds").json() if x["status"] == "approved"][0]
    r = M.patch(f"{B}/api/embeds/{me_embed['id']}", json={"restrict_to_domain": False})
    check("member can't switch the lock off (403)", r.status_code == 403, r.text)
    check("member's embed is still locked", [x for x in M.get(f"{B}/api/embeds").json() if x["id"] == me_embed["id"]][0]["restrict_to_domain"] is True)
    check("member can still change other settings", M.patch(f"{B}/api/embeds/{me_embed['id']}", json={"color": "#111111"}).status_code == 200)
    check("member can't use the admin endpoint", M.patch(f"{B}/api/admin/embeds/{me_embed['id']}", json={"restrict_to_domain": False}).status_code == 403)
    r = A.patch(f"{B}/api/admin/embeds/{me_embed['id']}", json={"restrict_to_domain": False})
    check("admin can switch it from the Admin console", r.status_code == 200 and r.json()["restrict_to_domain"] is False)

    A.patch(f"{B}/api/embeds/{eid}", json={"restrict_to_domain": True})
    check("lock back on: another website refused again", cfg(X("https://other-shop.example")).status_code == 403)
    A.patch(f"{B}/api/embeds/{eid}", json={"restrict_to_domain": False})  # off for the browser test
    state.update(key=key, eid=eid)


def visit(browser, env, key):
    """A shop on another https website, with SiteBot at a public-looking address forwarded to the backend under test."""
    page_html = f"""<!doctype html><html><body style='font-family:sans-serif;padding:40px'><h1>Another company's shop</h1>
<div id=status>connecting...</div>
<script src='https://sitebot-test.example/sitebot-client.js'></script>
<script>SiteBot.connect({{ key: '{key}' }}).config().then(c => document.getElementById('status').textContent = 'client OK: ' + c.name).catch(e => document.getElementById('status').textContent = 'client ERROR: ' + e.message);</script>
<script src='https://sitebot-test.example/embed.js' data-bot='{key}' async></script></body></html>"""
    ctx = browser.new_context(viewport={"width": 1200, "height": 800})
    def forward(route):
        try:
            route.fulfill(response=route.fetch(url=route.request.url.replace("https://sitebot-test.example", env.B), headers=route.request.all_headers()))
        except Exception:  # the page was closed while a request was on its way: nothing left to answer
            pass

    ctx.route("https://sitebot-test.example/**", forward)
    page = ctx.new_page()
    page.route("https://other-shop.example/**", lambda route: route.fulfill(status=200, content_type="text/html", body=page_html))
    page.goto("https://other-shop.example/")
    page.wait_for_function("document.getElementById('status').textContent !== 'connecting...'", timeout=15000)
    page.wait_for_timeout(2500)
    return ctx, page, page.inner_text("#status"), widget_visibility(page)


def test_domain_lock_in_a_browser(env, public_browser, check):
    B, A, b = env.B, env.api("admin"), public_browser
    ctx, page, status, vis = visit(b, env, state["key"])
    check("lock OFF: sitebot-client.js works on another website", status.startswith("client OK"), status)
    check("lock OFF: widget shows on another website", vis == "visible", vis)
    if vis == "visible":
        w = page.query_selector(SEL).content_frame()
        w.click(".w-bubble")
        w.fill("textarea", "hi")
        w.press("textarea", "Enter")
        w.wait_for_selector(".w-msg.assistant >> nth=1", timeout=60000)
        page.wait_for_load_state("networkidle")
        check("lock OFF: a visitor there gets an answer", True)
    ctx.close()

    A.patch(f"{B}/api/embeds/{state['eid']}", json={"restrict_to_domain": True})
    ctx, page, status, vis = visit(b, env, state["key"])
    check("lock ON: sitebot-client.js refused on another website", status.startswith("client ERROR"), status)
    check("lock ON: widget doesn't show on another website", vis in ("hidden", "removed"), vis)
    ctx.close()

    for role, can in (("admin", True), ("member", False)):
        ctx, pg, errors = login(b, env, role)
        pg.goto(f"{B}/#/website/{state['eid']}/design" if role == "admin" else f"{B}/#/website")
        if role == "member":
            pg.wait_for_selector(".embed-tile")
            pg.click(".embed-tile >> nth=0")
        pg.wait_for_selector(".head-switches")
        sw = pg.locator(".head-switches button[aria-label^='Only allow on']")
        check(f"{role}: switch shown, {'enabled' if can else 'read-only'}", sw.is_enabled() == can)
        if can:
            sw.click()
            pg.wait_for_selector("text=Let any website use this chatbot?")
            pg.click("button:has-text('Allow any website')")
            pg.wait_for_selector(".warn-note")
            check("admin: turning it off shows the warning", "charged to the owner's credits" in pg.inner_text(".warn-note"))
            sw.click()
            pg.wait_for_selector(".warn-note", state="detached")
            pg.click(".side-link:has-text('Admin console')")
            pg.click("role=tab[name='Embeds']")
            pg.wait_for_selector("th:has-text('Only own domain')")
            check("Admin console > Embeds has the switch", pg.locator("td .switch").count() >= 2)
        else:
            check("member: told only an admin can change it", "Only an admin can change which websites" in pg.inner_text(".lock-note"))
        check(f"{role}: no page errors", not errors, errors)
        ctx.close()
