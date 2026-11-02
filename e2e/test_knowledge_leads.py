"""Human handoff (a visitor leaves their email), leads, teaching the bot from "Couldn't answer", and uploaded
documents. With the stand-in AI, answers quote the top excerpt; what matters here is which source they cite."""

from conftest import SEL, login

UNKNOWN = "What is the airspeed velocity of an unladen swallow?"


def widget(browser, env):
    page = browser.new_context(viewport={"width": 1200, "height": 860}).new_page()  # a new visitor each time
    page.goto(env.ALLOWED + "/")
    fe = page.wait_for_selector(SEL, state="attached")
    page.wait_for_function(f"document.querySelector(\"{SEL}\").style.visibility === 'visible'")
    w = fe.content_frame()
    w.click(".w-bubble")
    return page, w


def ask(w, question, n):
    w.fill("textarea", question)
    w.press("textarea", "Enter")
    answer = w.locator(".w-msg.assistant:has(.w-rate)").nth(n - 1)
    answer.wait_for(timeout=60000)
    return answer.inner_text()


def test_handoff_leads_teach_and_documents(env, browser, check, tmp_path):
    B, A = env.B, env.api("admin")
    e = A.post(f"{B}/api/embeds", json={"site_id": env.site_id}).json()
    env.write_pages(e["key"])

    page, w = widget(browser, env)
    ans = ask(w, UNKNOWN, 1)
    check("bot says it doesn't know", "don't have information" in ans or "rather not guess" in ans, ans[:120])
    w.click(".w-handoff-open")
    w.fill(".w-handoff input[type=email]", "visitor@example.com")
    w.fill(".w-handoff input[aria-label='Your name']", "Vera Visitor")
    w.fill(".w-handoff textarea", "Please email me about swallows.")
    w.click(".w-send-lead")
    w.wait_for_selector(".w-handoff-done")
    check("handoff: visitor leaves their email", "visitor@example.com" in w.inner_text(".w-handoff-done"))
    page.context.close()

    ctx, admin, errors = login(browser, env, "admin", 1400, 950)
    admin.goto(f"{B}/#/website/{e['id']}/leads")
    admin.wait_for_selector(".lead-list li")
    lead = admin.inner_text(".lead-list li")
    check("Leads tab: name, email, the question and the message", all(x in lead for x in ("Vera Visitor", "visitor@example.com", "swallow", "Please email me")), lead)
    check("Leads tab label shows the open count", "1" in admin.inner_text("role=tab[name=/Leads/]"))
    admin.click(".lead-list button:has-text('Mark handled')")
    admin.wait_for_selector("text=Nothing open")

    admin.click("role=tab[name='Usage & settings']")
    admin.wait_for_selector(".usage-tab section:has-text(\"Couldn't answer\") li")
    admin.locator(".usage-tab section:has-text(\"Couldn't answer\") li", has_text="swallow").locator("button:has-text('Teach the bot')").click()
    admin.wait_for_selector(".knowledge-tab .answer-form")
    check("Teach the bot opens Knowledge with the question filled in", admin.input_value(".answer-form input") == UNKNOWN)
    admin.fill(".answer-form textarea", "About 11 metres per second, according to our guide Marie, who has measured it on the Lyon river path.")
    admin.click(".answer-form button:has-text('Teach the bot')")
    admin.wait_for_selector(".knowledge-list li:has-text('swallow')")

    doc = tmp_path / "acme-christmas.txt"
    doc.write_text("Christmas closure. The Acme Outdoor shop in Lyon is closed for the Christmas holidays on 25 and 26 December "
                   "and on 1 January. Online orders placed then ship on 2 January. " * 3, encoding="utf-8")
    admin.set_input_files(".upload-btn input[type=file]", str(doc))
    admin.wait_for_selector(".knowledge-list li:has-text('acme-christmas.txt')", timeout=60000)
    check("document uploaded and listed", "passage" in admin.inner_text(".knowledge-list li:has-text('acme-christmas.txt')"))

    page2, w2 = widget(browser, env)
    ans = ask(w2, UNKNOWN, 1)
    check("taught answer is used and cited as 'Answer from the Acme Outdoor team'", "Answer from the Acme Outdoor team" in ans, ans[-200:])
    ans = ask(w2, "Is the shop closed at Christmas?", 2)
    check("document is used and cited", "acme-christmas.txt" in ans, ans[-250:])
    page2.context.close()
    check("no page errors in the app", not errors, errors)
    ctx.close()
