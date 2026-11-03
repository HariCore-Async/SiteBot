"""The "Your website chatbots" pages: empty state, adding one, every tab, the URL, On/Off and removing it (admin);
then Pending / Live / Off cards, read-only bits and phone layouts (member)."""

import re

from conftest import SEL, login


def no_sideways(page):
    return page.evaluate("(() => { const p = document.querySelector('.embed-page'); return p.scrollWidth <= p.clientWidth + 1; })()")


def test_admin_embed_pages(env, browser, check):
    B = env.B
    ctx, page, errors = login(browser, env, "admin")
    # The fictional shop's favicon address doesn't exist; any other console error counts.
    page.on("console", lambda m: errors.append("console: " + m.text[:300]) if m.type == "error" and "ERR_NAME_NOT_RESOLVED" not in m.text else None)
    page.goto(B + "/")
    page.wait_for_selector(".dash-card", timeout=60000)
    page.click(".dash-card:has-text('Add a chatbot to your website')")
    page.wait_for_selector(".empty-embeds")
    check("empty state: 3-step explainer", page.locator(".steps li").count() == 3 and "Paste one line" in page.inner_text(".steps"))
    check("URL is #/website", page.evaluate("location.hash") == "#/website")
    page.click(".empty-embeds button:has-text('Add to a website')")
    page.wait_for_selector(".add-embed select")
    value = page.eval_on_selector(".add-embed select", f"s => [...s.options].find(o => o.textContent.includes('{env.domain}')).value")
    page.select_option(".add-embed select", value)
    page.click(".add-embed button:has-text('Add to website')")
    page.wait_for_selector(".bot-head")
    m = re.match(r"#/website/(\d+)/design$", page.evaluate("location.hash"))
    check("added: opens the bot page on the Design tab (in the URL)", m, page.evaluate("location.hash"))
    eid = m.group(1) if m else "0"
    check("header: name, Live pill, On/Off and domain-lock switches",
          "Acme Outdoor Chatbot" in page.inner_text(".bot-head") and page.inner_text(".bot-head .status") == "Live" and page.locator(".head-switches .switch").count() == 2)
    page.frame_locator(".embed-preview iframe").locator(".w-head").wait_for(timeout=15000)
    check("Design: options left, live preview right", page.eval_on_selector(".design-tab", "el => { const [a, b] = el.children; return a.getBoundingClientRect().left < b.getBoundingClientRect().left && Math.abs(a.getBoundingClientRect().top - b.getBoundingClientRect().top) < 5; }"))
    page.fill("input[placeholder='Acme Outdoor']", "Ask Acme")
    page.click("button:has-text('Save changes')")
    # The preview updates while typing, so wait for the save itself (otherwise leaving asks to discard changes).
    page.wait_for_selector("button:has-text('Save changes'):disabled", timeout=15000)
    page.frame_locator(".embed-preview iframe").locator(".w-head:has-text('Ask Acme')").wait_for(timeout=15000)

    page.click("role=tab[name='Install']")
    page.wait_for_selector(".install-tab")
    check("Install: URL remembers the tab", page.evaluate("location.hash") == f"#/website/{eid}/install")
    check("Install: three ways, snippet marked Recommended", page.locator(".sub-tabs .tab").all_inner_texts()[0].startswith("Website snippet") and "Recommended" in page.inner_text(".sub-tabs"))
    check("Install > snippet: the one line", "embed.js" in page.inner_text(".install-panel .snippet code"))
    with ctx.expect_page() as pinfo:
        page.click("a:has-text('Test it')")
    test = pinfo.value
    test.wait_for_load_state()
    fe = test.wait_for_selector(SEL, state="attached", timeout=15000)
    test.wait_for_function(f"document.querySelector(\"{SEL}\").style.visibility === 'visible'", timeout=15000)
    w = fe.content_frame()
    w.click(".w-bubble")
    w.fill("textarea", "hi")
    w.press("textarea", "Enter")
    w.wait_for_selector(".w-msg.assistant >> nth=1", timeout=30000)
    # The reply is saved just after it's shown; closing the page earlier can leave it unsaved.
    A = env.api("admin")
    for _ in range(50):
        chats = A.get(f"{B}/api/embeds/{eid}/chats").json()
        if chats and chats[0]["messages"] >= 2:
            break
        test.wait_for_timeout(200)
    check("Test it: sample page loads the widget and it answers", "Ask Acme" in w.inner_text(".w-head"))
    test.close()
    page.click("role=tab[name='Custom UI (browser)']")
    check("Install > Custom UI: sitebot-client.js + examples", "sitebot-client.js" in page.inner_text(".install-panel") and "SiteBot.connect" in page.inner_text(".code-block"))
    page.click("role=tab[name='React']")
    check("Install > Custom UI: React example", "useMemo" in page.inner_text(".code-block"))
    page.click("role=tab[name='Server API']")
    check("URL remembers the sub-tab", page.evaluate("location.hash") == f"#/website/{eid}/install/server")
    page.click("button:has-text('Create server key')")
    page.wait_for_selector("text=Copy your key now")
    check("Install > Server API: key created and shown once", page.inner_text(".secret-box code").startswith("sk_"))
    page.click("role=tab[name='Python']")
    check("Install > Server API: examples", "api/v1/messages" in page.inner_text(".code-block"))
    page.reload()
    page.wait_for_selector(".install-tab")
    check("reload keeps the bot, tab and sub-tab", page.locator(".sub-tabs .tab.active").inner_text().startswith("Server API") and "Copy your key now" not in page.inner_text(".install-tab"))

    page.click("role=tab[name='Conversations']")
    page.wait_for_selector(".convo-row")
    check("Conversations: the Test-it chat is listed and labelled Test", "Test" in page.inner_text(".convo-row") and "Your test" in page.inner_text(".convo-row"))
    page.click(".convo-row >> nth=0")
    page.wait_for_function("document.querySelectorAll('.convo-msg').length >= 2", timeout=10000)

    page.click("role=tab[name='Usage & settings']")
    page.wait_for_selector(".usage-tab")
    check("Usage: spend vs daily limit + bar", "daily limit" in page.inner_text(".usage-tab") and page.locator(".usage-tab .bar").count() == 1)
    page.fill("#cap", "0.75")
    page.click(".usage-tab button:has-text('Save')")
    page.wait_for_selector("text=/of \\$0\\.75(00)? daily limit/")
    check("Usage: keys overview (public code + server key)", "Public code" in page.inner_text(".usage-tab") and "sk_…" in page.inner_text(".usage-tab"))
    check("Usage: danger zone with Remove", page.locator(".danger-zone button:has-text('Remove embed')").count() == 1)

    page.click(".head-switches button[aria-label='Show this chatbot on the website']")
    page.wait_for_selector(".bot-head .status:text-is('Off')")
    page.click("button:has-text('← Your website chatbots')")
    page.wait_for_selector(".embed-tile")
    tile = page.inner_text(".embed-tile")
    check("List: card with name, Off pill, domain and today's chats",
          "Acme Outdoor Chatbot" in tile and "Off" in tile and env.domain in tile and "0 chats" in tile and "today" in tile, tile)
    check("List: URL back to #/website", page.evaluate("location.hash") == "#/website")
    page.go_back()
    page.wait_for_selector(".bot-head")
    page.go_forward()
    page.wait_for_selector(".embed-tile")
    page.click(".embed-tile")
    page.click(".head-switches button[aria-label='Show this chatbot on the website']")
    page.wait_for_selector(".bot-head .status:text-is('Live')")

    page.click("role=tab[name='Usage & settings']")
    page.click("button:has-text('Remove embed')")
    page.click(".modal .modal-actions button.danger-solid")
    page.wait_for_selector(".empty-embeds", timeout=10000)
    check("admin: no page errors", not errors, errors)
    ctx.close()


def test_member_embed_pages(env, browser, check):
    env.member_embeds()
    ctx, page, errors = login(browser, env, "member", 1000, 620)
    page.goto(env.B + "/#/website")
    page.wait_for_selector(".embed-tile")
    pills = page.locator(".embed-tile .status").all_inner_texts()
    check("member list: Pending, Live and Off pills", {"Pending", "Live", "Off"} <= set(pills), pills)
    pages_n = page.locator(".pager-btn:not([aria-label])").count()
    scrolls = page.evaluate("(() => { const p = document.querySelector('.embed-page'); return p.scrollHeight > p.clientHeight + 1; })()")
    check("member list: paginates to fit, no scrolling", pages_n >= 2 and not scrolls, (pages_n, scrolls))
    page.locator(".embed-tile:has(.status:text-is('Pending'))").first.click()
    page.wait_for_selector(".banner.pending")
    check("pending: 'Waiting for admin approval' banner", "Waiting for admin approval" in page.inner_text(".banner.pending"))
    check("pending: no On/Off switch yet", page.locator("button[aria-label='Show this chatbot on the website']").count() == 0)
    check("member: domain-lock switch read-only", page.locator(".head-switches button[aria-label^='Only allow on']").is_disabled())
    page.click("role=tab[name='Install']")
    check("pending: Install explains it works once approved", "as soon as an admin approves it" in page.inner_text(".info-note"))
    page.click("role=tab[name='Usage & settings']")
    check("member: can't edit the daily limit", "Only an admin can change the daily limit" in page.inner_text(".usage-tab") and page.locator("#cap").count() == 0)
    page.click("role=tab[name='Conversations']")
    page.wait_for_selector("text=No visitor conversations yet")

    page.set_viewport_size({"width": 390, "height": 800})
    page.click("role=tab[name='Design']")
    page.wait_for_selector(".design-tab")
    page.wait_for_timeout(300)
    stacked = page.eval_on_selector(".design-tab", "el => { const [a, b] = el.children; return b.getBoundingClientRect().top > a.getBoundingClientRect().top; }")
    check("phone: Design stacks preview under the options", stacked)
    check("phone: bot page has no sideways scrolling", no_sideways(page))
    page.click("button:has-text('← Your website chatbots')")
    page.wait_for_selector(".embed-tile")
    cols = page.eval_on_selector(".embed-grid-list", "g => getComputedStyle(g).gridTemplateColumns.split(' ').length")
    check("phone: list is one column, no sideways scrolling", cols == 1 and no_sideways(page))
    check("member: no page errors", not errors, errors)
    ctx.close()
