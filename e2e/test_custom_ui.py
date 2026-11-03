"""Bring your own UI: the server API (sk_ keys), the public API from another origin (sitebot-client.js) and styling;
then the styled widget and sitebot-client.js in a browser."""

import json

import requests

from conftest import SEL

state = {}


def test_server_api_client_api_and_styling(env, check):
    B, S = env.B, env.api("admin")
    e = S.post(f"{B}/api/embeds", json={"site_id": env.site_id}).json()
    key, eid, domain = e["key"], e["id"], e["site"]["domain"]

    check("no server key at first", e["server_key"] is None)
    r = S.post(f"{B}/api/embeds/{eid}/server-key").json()
    sk = r["secret"]
    check("server key created and shown once", sk.startswith("sk_") and r["server_key"]["hint"] == sk[-4:])
    check("listing never shows the secret", sk not in json.dumps(S.get(f"{B}/api/embeds").json()))
    H = {"Authorization": f"Bearer {sk}"}

    r = requests.get(f"{B}/api/v1/bot", headers=H)
    check("GET /api/v1/bot", r.status_code == 200 and r.json()["domain"] == domain, r.text[:200])
    check("GET /api/v1/suggestions", requests.get(f"{B}/api/v1/suggestions", headers=H).json().get("questions") is not None)
    check("missing key -> 401", requests.get(f"{B}/api/v1/bot").status_code == 401)
    check("wrong key -> 401", requests.get(f"{B}/api/v1/bot", headers={"Authorization": "Bearer sk_wrong"}).status_code == 401)
    check("pk_ key can't be used as a server key", requests.get(f"{B}/api/v1/bot", headers={"Authorization": f"Bearer {key}"}).status_code == 401)
    check("sk_ refused when sent from a browser (Origin header)", requests.get(f"{B}/api/v1/bot", headers={**H, "Origin": "https://evil-example.com"}).status_code == 403)
    check("sk_ refused from a browser even on the bot's own domain", requests.get(f"{B}/api/v1/bot", headers={**H, "Origin": f"https://{domain}"}).status_code == 403)

    r = requests.post(f"{B}/api/v1/messages", headers=H, json={"visitor_id": "crm-user-42", "content": "What does Acme Outdoor sell?", "stream": False})
    body = r.json()
    check("non-streaming answer", r.status_code == 200 and body.get("answer") and body.get("sources"), r.text[:300])
    conv = body.get("conversation_id")
    r = requests.post(f"{B}/api/v1/messages", headers=H, json={"visitor_id": "crm-user-42", "content": "Where is the shop?", "conversation_id": conv}, stream=True)
    events = [json.loads(line) for line in r.iter_lines() if line]
    types = [x["type"] for x in events]
    check("streaming answer: conversation, user_saved, token..., done", types[0] == "conversation" and "user_saved" in types and "token" in types and types[-1] == "done", types[:3] + types[-2:])
    check("follow-up continues the same conversation", events[0]["conversation_id"] == conv)
    done = events[-1]

    msgs = requests.get(f"{B}/api/v1/conversations/{conv}/messages", params={"visitor_id": "crm-user-42"}, headers=H).json()
    check("history via server API", len(msgs) == 4)
    check("another visitor_id can't read it", requests.get(f"{B}/api/v1/conversations/{conv}/messages", params={"visitor_id": "someone-else"}, headers=H).status_code == 404)
    check("conversation list", requests.get(f"{B}/api/v1/conversations", params={"visitor_id": "crm-user-42"}, headers=H).json()[0]["conversation_id"] == conv)
    r = requests.post(f"{B}/api/v1/messages", headers=H, json={"visitor_id": "crm-user-42", "content": "hi", "new_conversation": True, "stream": False})
    check("new_conversation starts a fresh one", r.status_code == 200 and r.json()["conversation_id"] != conv)
    check("bad visitor_id rejected", requests.post(f"{B}/api/v1/messages", headers=H, json={"visitor_id": "bad id!", "content": "hi"}).status_code == 422)

    check("server feedback saved", requests.post(f"{B}/api/v1/feedback", headers=H, json={"message_id": done["message_id"], "rating": "down", "comment": "too long"}).status_code == 200)
    check("feedback on a user message refused", requests.post(f"{B}/api/v1/feedback", headers=H, json={"message_id": msgs[0]["id"], "rating": "up"}).status_code == 404)

    listed = S.get(f"{B}/api/embeds").json()[0]
    check("owner sees feedback counts", listed["feedback"]["down"] == 1, listed["feedback"])
    check("server usage charged to the embed", listed["spent_today_usd"] > 0)
    chats = S.get(f"{B}/api/embeds/{eid}/chats").json()
    owner_msgs = S.get(f"{B}/api/embeds/{eid}/chats/{conv}/messages").json()
    check("owner sees the server conversation with its rating", any(c["id"] == conv for c in chats) and any((m.get("feedback") or {}).get("comment") == "too long" for m in owner_msgs))

    S.patch(f"{B}/api/admin/embeds/{eid}", json={"daily_cap_usd": 0})
    r = requests.post(f"{B}/api/v1/messages", headers=H, json={"visitor_id": "crm-user-43", "content": "What do you sell?", "stream": False})
    check("daily cap -> 503 with a polite message", r.status_code == 503 and "short break" in r.json()["detail"], r.text)
    S.patch(f"{B}/api/admin/embeds/{eid}", json={"daily_cap_usd": 0.5})

    S.patch(f"{B}/api/embeds/{eid}", json={"enabled": False})
    check("turned-off embed: server API refuses", requests.get(f"{B}/api/v1/bot", headers=H).status_code == 404)
    S.patch(f"{B}/api/embeds/{eid}", json={"enabled": True})
    r = S.post(f"{B}/api/embeds/{eid}/server-key").json()
    check("replaced key: old one stops working", requests.get(f"{B}/api/v1/bot", headers=H).status_code == 401)
    H = {"Authorization": f"Bearer {r['secret']}"}
    check("replaced key: new one works", requests.get(f"{B}/api/v1/bot", headers=H).status_code == 200)
    S.delete(f"{B}/api/embeds/{eid}/server-key")
    check("revoked key stops working", requests.get(f"{B}/api/v1/bot", headers=H).status_code == 401)

    def X(origin):
        return {"Origin": origin, "Sec-Fetch-Site": "cross-site"}

    r = requests.get(f"{B}/api/public/{key}/config", headers=X(f"https://{domain}"))
    check("client: config from the bot's domain + CORS header", r.status_code == 200 and r.headers.get("access-control-allow-origin") == f"https://{domain}")
    check("client: refused from another domain", requests.get(f"{B}/api/public/{key}/config", headers=X("https://evil-example.com")).status_code == 403)
    r = requests.get(f"{B}/api/public/{key}/config", params={"origin": f"https://{domain}"}, headers=X("https://evil-example.com"))
    check("client: a claimed origin can't override the browser's Origin", r.status_code == 403)
    r = requests.options(f"{B}/api/public/{key}/messages", headers={"Origin": f"https://{domain}", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    check("client: CORS preflight answered", r.status_code == 204 and "POST" in r.headers.get("access-control-allow-methods", ""))
    check("client: no credentials allowed", "access-control-allow-credentials" not in r.headers)
    check("sitebot-client.js served", requests.get(f"{B}/sitebot-client.js").status_code == 200)

    style = {"launcher_icon": "sparkle", "launcher_label": "Ask us", "title": "Help desk", "font": "serif", "radius": 4, "theme": "dark",
             "custom_css": ".w-head{letter-spacing:.1em}\n@import url(https://evil.example/x.css);\n.w-bubble{background:url(https://evil.example/t.png)}\n"
                           ".x{background:u\\72l(https://evil.example/y)}\n.y{background-image:image-set(\"https://evil.example/z.png\" 1x)}\n</style><script>alert(1)</script>"}
    r = S.patch(f"{B}/api/embeds/{eid}", json={"style": style}).json()
    css = r["style"]["custom_css"]
    check("style saved", r["style"]["title"] == "Help desk" and r["style"]["theme"] == "dark" and r["style"]["radius"] == 4)
    check("custom CSS kept", ".w-head{letter-spacing:.1em}" in css)
    check("custom CSS: @import, url(), image-set() and escapes removed", "@import" not in css and "url(" not in css.lower() and "image-set" not in css.lower() and "\\" not in css, css)
    check("custom CSS: no '<' left", "<" not in css)
    check("invalid style rejected", S.patch(f"{B}/api/embeds/{eid}", json={"style": {"font": "comic"}}).status_code == 422)
    csp = requests.get(f"{B}/widget/{key}").headers.get("content-security-policy", "")
    check("widget CSP blocks loading from elsewhere (images only from the favicon host)",
          "default-src 'self'" in csp and "connect-src 'self'" in csp and f"img-src 'self' data: https://{domain};" in csp, csp)
    state["key"] = key


def test_styled_widget_and_client_js_in_a_browser(env, browser, check):
    env.write_pages(state["key"])
    page = browser.new_page(viewport={"width": 1280, "height": 860})
    page.goto(env.ALLOWED + "/")
    fe = page.wait_for_selector(SEL, state="attached")
    page.wait_for_function(f"document.querySelector(\"{SEL}\").style.visibility === 'visible'")
    w = fe.content_frame()
    w.wait_for_selector(".w-bubble.labelled")
    check("launcher shows its label", w.inner_text(".w-bubble") == "Ask us")
    page.wait_for_function(f"parseInt(document.querySelector(\"{SEL}\").style.width) > 84")
    w.click(".w-bubble")
    w.wait_for_selector(".w-panel")
    check("header uses the custom title", "Help desk" in w.inner_text(".w-head"))
    check("dark theme applied", w.evaluate("document.documentElement.dataset.theme") == "dark")
    check("serif font applied", "Georgia" in w.evaluate("getComputedStyle(document.querySelector('.w-panel')).fontFamily"))
    check("corner radius applied", w.evaluate("getComputedStyle(document.querySelector('.w-panel')).borderTopLeftRadius") == "4px")
    ls = w.evaluate("getComputedStyle(document.querySelector('.w-head')).letterSpacing")
    check("custom CSS applied inside the widget", ls not in ("normal", "0px"), ls)
    check("custom CSS doesn't touch the host page", page.evaluate("getComputedStyle(document.querySelector('h1')).letterSpacing") == "normal")
    check("Powered by SiteBot still shown", "Powered by SiteBot" in w.inner_text(".w-foot"))
    w.fill("textarea", "Where is the Acme shop?")
    w.press("textarea", "Enter")
    w.wait_for_selector(".w-rate", timeout=60000)
    w.click(".w-rate button[aria-label='Helpful']")
    w.wait_for_selector("text=Thanks for the feedback")
    page.close()

    c = browser.new_page(viewport={"width": 1100, "height": 700})
    c.goto(env.ALLOWED + "/client.html")
    c.wait_for_function("document.getElementById('status').textContent !== 'connecting...'", timeout=15000)
    check("client.js: config on the allowed site", c.inner_text("#status").startswith("Connected to"), c.inner_text("#status"))
    c.click("button")
    c.wait_for_selector("#done", timeout=60000)
    done = c.query_selector("#done")
    check("client.js: streamed answer rendered by the site's own UI", done.inner_text().startswith("Bot: ") and int(done.get_attribute("data-tokens") or 0) > 1, done.inner_text()[:120])
    check("client.js: sources returned", int(done.get_attribute("data-sources") or 0) > 0)
    c.wait_for_function("document.getElementById('done').dataset.rated === 'yes'", timeout=10000)
    c.close()

    d = browser.new_page(viewport={"width": 1100, "height": 700})
    d.goto(env.BLOCKED + "/client.html")
    d.wait_for_function("document.getElementById('status').textContent !== 'connecting...'", timeout=15000)
    status = d.inner_text("#status")
    check("client.js: refused on a blocked origin", status.startswith("ERROR") and "only works on" in status, status)
    d.click("button")
    d.wait_for_selector("#done", timeout=30000)
    check("client.js: asking is refused too", d.inner_text("#done").startswith("ERROR"), d.inner_text("#done"))
    d.close()
