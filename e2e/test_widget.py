"""The website widget: domain lock, visitor questions, history, rate limits, daily cap, approval, new keys; then the
real widget in a browser on a website it's allowed on, and one it isn't."""

import json

import requests

from conftest import ADMIN_EMAIL, SEL, same_origin
from seed import set_role

state = {}


def ask(env, key, content, origin, visitor, headers=None, preview=False, session=None):
    r = (session or requests).post(
        f"{env.B}/api/public/{key}/messages",
        json={"visitor_id": visitor, "content": content, "origin": origin, "preview": preview},
        headers=headers or same_origin(), stream=True,
    )
    if r.status_code != 200:
        return r.status_code, []
    return 200, [json.loads(line) for line in r.iter_lines() if line]


def test_widget_api(env, check):
    B, S = env.B, env.api("admin")
    e = S.post(f"{B}/api/embeds", json={"site_id": env.site_id}).json()
    key = e["key"]
    check("admin's own request is approved", e["status"] == "approved", e)
    e = S.patch(f"{B}/api/embeds/{e['id']}", json={"color": "#7c3aed", "greeting": "Hello from the test!", "position": "left"}).json()
    check("customise saved", e["color"] == "#7c3aed" and e["position"] == "left")
    check("bad colour rejected", S.patch(f"{B}/api/embeds/{e['id']}", json={"color": "red"}).status_code == 422)
    domain = e["site"]["domain"]

    def cfg(origin, **kw):
        return requests.get(f"{B}/api/public/{key}/config", params={"origin": origin, **kw}, headers=same_origin())

    r = cfg(f"https://{domain}")
    check("config on own domain", r.status_code == 200 and r.json()["greeting"] == "Hello from the test!", r.text[:200])
    check("config on www subdomain", cfg(f"https://www.{domain}").status_code == 200)
    check("config refused on another website", cfg("https://evil-example.com").status_code == 403)
    check("config refused on look-alike domain", cfg(f"https://{domain}.evil.com").status_code == 403)
    check("config refused over plain http", cfg(f"http://{domain}").status_code == 403)
    check("dev origin allowed (EMBED_DEV_ORIGINS)", cfg(env.ALLOWED).status_code == 200)
    check("other localhost port refused", cfg(env.BLOCKED).status_code == 403)
    r = requests.get(f"{B}/api/public/{key}/config", params={"origin": f"https://{domain}"}, headers={"Sec-Fetch-Site": "cross-site"})
    check("direct cross-site API call refused", r.status_code == 403)
    check("unknown key -> 404", requests.get(f"{B}/api/public/pk_nope/config", params={"origin": f"https://{domain}"}).status_code == 404)

    w = requests.get(f"{B}/widget/{key}")
    csp = w.headers.get("content-security-policy", "")
    check("widget page CSP locks frame to bot's domain", w.status_code == 200 and f"https://{domain}" in csp and f"https://*.{domain}" in csp and "evil" not in csp, csp)
    check("unknown widget key only frameable by SiteBot", requests.get(f"{B}/widget/pk_nope").headers.get("content-security-policy", "").endswith("frame-ancestors 'self'"))
    check("embed.js served", requests.get(f"{B}/embed.js").status_code == 200)

    visitor = "visitorAAAAAAAAAAAAAAAA1"
    code, events = ask(env, key, "What does Acme Outdoor sell?", f"https://{domain}", visitor)
    done = [x for x in events if x["type"] == "done"]
    errors = [x for x in events if x["type"] == "error"]
    check("visitor gets an answer", code == 200 and done and not errors, (code, errors))
    check("answer has sources", done and done[0]["sources"], done[:1])
    check("visitor never sees the owner's usage", done and done[0].get("usage") is None)
    code, _ = ask(env, key, "hi", "https://evil-example.com", visitor)
    check("question refused from another website", code == 403)
    hist = requests.get(f"{B}/api/public/{key}/messages", params={"visitor_id": visitor, "origin": f"https://{domain}"}, headers=same_origin()).json()
    check("visitor history kept", len(hist) == 2 and hist[0]["role"] == "user")
    other = requests.get(f"{B}/api/public/{key}/messages", params={"visitor_id": "visitorBBBBBBBBBBBBBBBB2", "origin": f"https://{domain}"}, headers=same_origin()).json()
    check("another visitor can't see it", other == [])

    chats = S.get(f"{B}/api/embeds/{e['id']}/chats").json()
    check("owner sees the conversation", len(chats) == 1 and chats[0]["messages"] == 2, chats)
    msgs = S.get(f"{B}/api/embeds/{e['id']}/chats/{chats[0]['id']}/messages").json()
    check("owner reads the messages", len(msgs) == 2)
    e = [x for x in S.get(f"{B}/api/embeds").json() if x["id"] == e["id"]][0]
    check("spend charged to the embed", e["spent_today_usd"] > 0, e["spent_today_usd"])
    check("visitor chats not in owner's own chat list", all(c["id"] != chats[0]["id"] for c in S.get(f"{B}/api/chats").json()))

    # 6 questions a minute per visitor (greetings skip the AI, so this costs nothing).
    codes = [ask(env, key, "hi", f"https://{domain}", "visitorRATERATERATE00001")[0] for _ in range(7)]
    check("7th question in a minute is rate limited", codes[:6] == [200] * 6 and codes[6] == 429, codes)

    S.patch(f"{B}/api/admin/embeds/{e['id']}", json={"daily_cap_usd": 0})
    code, events = ask(env, key, "What do you sell?", f"https://{domain}", "visitorCAPCAPCAPCAP00001")
    err = [x for x in events if x["type"] == "error"]
    check("daily cap stops answers politely", err and "short break" in err[0]["message"], events)
    S.patch(f"{B}/api/admin/embeds/{e['id']}", json={"daily_cap_usd": 0.5})

    S.patch(f"{B}/api/admin/embeds/{e['id']}", json={"status": "pending"})
    check("pending embed doesn't answer", cfg(f"https://{domain}").status_code == 404)
    check("owner can still preview while pending", requests.get(f"{B}/api/public/{key}/config", params={"preview": "true"}, cookies=S.cookies, headers=same_origin()).status_code == 200)
    check("preview needs the owner's sign-in", requests.get(f"{B}/api/public/{key}/config", params={"preview": "true"}, headers=same_origin()).status_code == 403)
    S.patch(f"{B}/api/admin/embeds/{e['id']}", json={"status": "approved"})
    check("approved embed answers again", cfg(f"https://{domain}").status_code == 200)
    S.patch(f"{B}/api/embeds/{e['id']}", json={"enabled": False})
    check("turned-off embed doesn't answer", cfg(f"https://{domain}").status_code == 404)
    S.patch(f"{B}/api/embeds/{e['id']}", json={"enabled": True})
    admin_list = S.get(f"{B}/api/admin/embeds").json()
    check("admin list shows owner", admin_list and admin_list[0]["owner"]["email"] == ADMIN_EMAIL)

    old = key
    e = S.post(f"{B}/api/embeds/{e['id']}/rotate-key").json()
    key = e["key"]
    check("old key stops working after new code", requests.get(f"{B}/api/public/{old}/config", params={"origin": f"https://{domain}"}).status_code == 404)
    check("new key works", cfg(f"https://{domain}").status_code == 200)

    set_role(env.ids["admin"], "member")
    try:
        r = S.post(f"{B}/api/embeds", json={"site_id": env.site_id})
        check("member can't embed a bot they didn't create", r.status_code == 403, r.text)
    finally:
        set_role(env.ids["admin"], "admin")
    state["key"] = key


def test_widget_in_a_browser(env, browser, check):
    env.write_pages(state["key"])
    page = browser.new_page(viewport={"width": 1280, "height": 860})
    page.goto(env.ALLOWED + "/")
    frame_el = page.wait_for_selector(SEL, state="attached", timeout=10000)
    page.wait_for_function(f"document.querySelector(\"{SEL}\").style.visibility === 'visible'", timeout=10000)
    check("bubble placed bottom-left as configured", frame_el.evaluate("el => el.style.left") == "8px")

    w = frame_el.content_frame()
    w.click(".w-bubble")
    page.wait_for_function(f"parseInt(document.querySelector(\"{SEL}\").style.width) > 300")
    check("greeting shown", "Hello from the test!" in w.inner_text(".w-messages"))
    check("notice and Powered by shown", "Chats are saved" in w.inner_text(".w-foot") and "Powered by SiteBot" in w.inner_text(".w-foot"))
    w.fill("textarea", "What products does Acme Outdoor sell?")
    w.press("textarea", "Enter")
    w.wait_for_selector(".w-msg.assistant .sources, .w-error", timeout=60000)
    w.wait_for_timeout(500)
    check("answer streamed with sources", w.query_selector(".w-msg.assistant .sources") is not None)

    page.reload()
    frame_el = page.wait_for_selector(SEL, state="attached")
    page.wait_for_function(f"document.querySelector(\"{SEL}\").style.visibility === 'visible'")
    w = frame_el.content_frame()
    w.click(".w-bubble")
    w.wait_for_selector(".w-msg.user", timeout=10000)
    check("conversation survives a page reload", "What products" in w.inner_text(".w-messages"))
    w.click(".w-icon")
    page.wait_for_function(f"parseInt(document.querySelector(\"{SEL}\").style.width) < 100")
    page.close()

    m = browser.new_page(viewport={"width": 390, "height": 760})
    m.goto(env.ALLOWED + "/")
    fe = m.wait_for_selector(SEL, state="attached")
    m.wait_for_function(f"document.querySelector(\"{SEL}\").style.visibility === 'visible'")
    fe.content_frame().click(".w-bubble")
    m.wait_for_function(f"document.querySelector(\"{SEL}\").style.width === '100%'")
    check("full screen on a phone", True)
    m.close()

    d = browser.new_page(viewport={"width": 1280, "height": 860})
    d.goto(env.BLOCKED + "/")
    d.wait_for_timeout(3000)
    vis = d.evaluate(f"(() => {{ const f = document.querySelector(\"{SEL}\"); return f ? f.style.visibility : 'removed'; }})()")
    check("nothing shows on a website the bot isn't allowed on", vis in ("hidden", "removed"), vis)
    d.close()
