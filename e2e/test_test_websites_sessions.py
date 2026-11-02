"""Test websites (a page on a port the bot isn't allowed on gets the bubble only once it's added), admin approval for
real websites, and signing out: an admin signing a member out, and "Sign out of all devices"."""

from conftest import MEMBER_EMAIL, SEL, login, widget_visibility


def bubble(browser, env, path="/"):
    page = browser.new_page()
    page.goto(env.BLOCKED + path)
    page.wait_for_timeout(3000)
    return page, widget_visibility(page)


def test_localhost_test_website(env, browser, check):
    B, A = env.B, env.api("admin")
    e = A.post(f"{B}/api/embeds", json={"site_id": env.site_id}).json()
    env.write_pages(e["key"])
    page, vis = bubble(browser, env)
    check("before: no bubble on the other port", vis in ("hidden", "removed"), vis)
    page.close()

    ctx, dash, errors = login(browser, env, "admin")
    dash.goto(f"{B}/#/website/{e['id']}/install")
    dash.wait_for_selector(".test-websites")
    dash.fill(".test-websites input", env.BLOCKED.replace("http://", ""))
    dash.click(".test-websites button:text-is('Add')")
    dash.wait_for_selector(f".test-origin-list li:has-text('{env.BLOCKED}')")
    row = dash.inner_text(".test-origin-list li")
    check("added in the dashboard, shows 7 days left", "7 days left" in row and "Renew" in row, row)
    dash.fill(".test-websites input", "http://staging.example.com")
    dash.click(".test-websites button:text-is('Add')")
    dash.wait_for_selector(".test-websites .error")
    check("plain-http staging site refused with a clear message", "https" in dash.inner_text(".test-websites .error"))
    dash.fill(".test-websites input", "https://staging.example.com")
    dash.click(".test-websites button:text-is('Add')")
    dash.wait_for_selector(".test-origin-list li:has-text('staging.example.com')")
    check("https staging site added (admin: no approval needed), no expiry", "No expiry" in dash.inner_text(".test-origin-list li:has-text('staging.example.com')"))

    page, vis = bubble(browser, env)
    check("after: bubble shows on the test website", vis == "visible", vis)
    if vis == "visible":
        w = page.query_selector(SEL).content_frame()
        w.click(".w-bubble")
        w.fill("textarea", "What does Acme Outdoor sell?")
        w.press("textarea", "Enter")
        w.wait_for_selector(".w-msg.assistant:has(.w-rate)", timeout=60000)
    page.close()
    chats = A.get(f"{B}/api/embeds/{e['id']}/chats").json()
    check("that chat is listed as a test chat from the test website", chats and chats[0]["origin"] == env.BLOCKED and chats[0]["is_test"], chats[:1])

    dash.click(f".test-origin-list li:has-text('{env.BLOCKED}') button:text-is('Remove')")
    dash.wait_for_selector(f".test-origin-list li:has-text('{env.BLOCKED}')", state="detached")
    page, vis = bubble(browser, env)
    check("removed: bubble gone again", vis in ("hidden", "removed"), vis)
    page.close()
    check("no page errors", not errors, errors)
    ctx.close()


def test_member_https_test_website_needs_approval(env, browser, check):
    B, M = env.B, env.api("member")
    env.member_embeds()
    mine = [x for x in M.get(f"{B}/api/embeds").json() if x["status"] == "approved"][0]
    t = M.post(f"{B}/api/embeds/{mine['id']}/test-origins", json={"origin": "https://staging.example.com"}).json()["test_origins"][0]
    check("member's https test website waits", t["status"] == "pending" and not t["active"])
    ctx, page, errors = login(browser, env, "admin")
    page.goto(B)
    page.click(".side-link:has-text('Admin console')")
    page.click("role=tab[name='Embeds']")
    page.wait_for_selector(".test-origins-review tr:has-text('staging.example.com')")
    check("listed for the admin as waiting", "Waiting" in page.inner_text(".test-origins-review tr:has-text('staging.example.com')"))
    page.click(".test-origins-review tr:has-text('staging.example.com') button:text-is('Approve')")
    page.wait_for_selector(".test-origins-review tr:has-text('staging.example.com'):has-text('Active')")
    t = [x for x in M.get(f"{B}/api/embeds").json() if x["id"] == mine["id"]][0]["test_origins"][0]
    check("approved and active", t["status"] == "approved" and t["active"])
    check("no page errors", not errors, errors)
    ctx.close()


def test_signing_out(env, browser, check):
    B = env.B
    M = env.api("member")
    check("member is signed in", M.get(f"{B}/api/me").status_code == 200)
    ctx, page, errors = login(browser, env, "admin")
    page.goto(B)
    page.click(".side-link:has-text('Admin console')")
    row = page.locator("tr", has_text=MEMBER_EMAIL)
    row.locator("button:text-is('Sign out')").click()
    page.click(".modal button:text-is('Sign out everywhere')")
    row.locator("text=Signed out").wait_for()
    check("member's session ended by the admin", M.get(f"{B}/api/me").status_code == 401)
    ctx.close()

    env.refresh_tokens()  # a new sign-in
    other = env.api("member")
    check("a new sign-in works", other.get(f"{B}/api/me").status_code == 200)
    ctx, page, errors = login(browser, env, "member", 1300, 900)
    page.goto(B)
    page.click(".side-link:has-text('Settings')")
    page.click("button:text-is('Sign out of all devices')")
    page.click(".modal button:text-is('Sign out everywhere')")
    page.wait_for_timeout(2500)
    check("this browser is back at sign-in", page.locator("input[type=password]").count() > 0 or page.locator("text=Sign in").count() > 0)
    check("the other device's session ended too", other.get(f"{B}/api/me").status_code == 401)
    check("no page errors", not errors, errors)
    ctx.close()
