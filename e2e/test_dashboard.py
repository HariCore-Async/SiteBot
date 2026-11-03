"""The dashboard as an admin and as a member: home cards, side panel, paginated bot lists that never scroll, removing
bots from your list, and the Admin console."""

from conftest import login


def nav_labels(page):
    return [t.strip() for t in page.locator(".side-nav .side-link").all_inner_texts()]


def grid_state(page):
    return page.evaluate("""() => {
        const pageEl = document.querySelector('.bots-page');
        const grid = document.querySelector('.bot-grid');
        const cols = grid ? getComputedStyle(grid).gridTemplateColumns.split(' ').length : 0;
        return { cards: document.querySelectorAll('.bot-grid .bot-card').length, cols,
                 pages: document.querySelectorAll('.pager-btn:not([aria-label])').length,
                 scrolls: pageEl.scrollHeight > pageEl.clientHeight + 1,
                 pageWidth: pageEl.clientWidth, gridWidth: grid ? grid.clientWidth : 0 };
    }""")


def open_home(browser, env, role, w, h):
    ctx, page, errors = login(browser, env, role, w, h)
    page.goto(env.B + "/")
    page.wait_for_selector(".dash-card")
    return ctx, page, errors


def test_admin_dashboard(env, browser, check):
    ctx, page, errors = open_home(browser, env, "admin", 1400, 900)
    check("home: two cards, Chat with a bot + Add to website", page.locator(".dash-card h2").all_inner_texts() == ["Chat with a bot", "Add a chatbot to your website"])
    check("home: side panel = Home, New chatbot, Settings, Admin console", nav_labels(page) == ["Home", "New chatbot", "Settings", "Admin console"], nav_labels(page))
    check("home: no 'Your chatbots' list in the side panel", page.locator(".sidebar .bot-row").count() == 0)

    page.click(".dash-card:has-text('Chat with a bot')")
    page.wait_for_selector(".bots-page .bot-grid .bot-card")
    check("inside: side panel shows Your chatbots", page.locator(".sidebar .bot-row").count() >= 12)
    s = grid_state(page)
    check("page uses the full width beside the side panel", s["gridWidth"] >= s["pageWidth"] - 100, s)

    page.set_viewport_size({"width": 1000, "height": 560})
    page.wait_for_timeout(400)
    s = grid_state(page)
    check("small window: paginates (numbered pages)", s["pages"] >= 2, s)
    check("small window: no scrolling", not s["scrolls"], s)
    seen = []
    for n in range(1, s["pages"] + 1):
        page.click(f".pager-btn:text-is('{n}')")
        page.wait_for_timeout(100)
        seen += page.locator(".bot-grid .bot-name").all_inner_texts()
    rows = page.locator(".sidebar .bot-row").count()
    check("every chatbot appears exactly across the pages", len(seen) == rows, (len(seen), rows))
    small = s["cards"]
    page.set_viewport_size({"width": 1600, "height": 1000})
    page.wait_for_timeout(400)
    s = grid_state(page)
    check("resize bigger: more cards per page", s["cards"] > small and not s["scrolls"], (small, s))

    page.set_viewport_size({"width": 1000, "height": 560})
    page.click("role=tab[name=/Library/]")
    page.wait_for_timeout(300)
    s = grid_state(page)
    check("Library: paginates without scrolling", s["pages"] >= 2 and not s["scrolls"], s)
    check("Library: no remove buttons", page.locator(".card-remove").count() == 0)
    page.click("role=tab[name=/Your chatbots/]")
    page.set_viewport_size({"width": 1400, "height": 900})
    page.wait_for_timeout(300)

    before = page.locator(".sidebar .bot-row").count()
    lib_before = page.locator("role=tab[name=/Library/]").inner_text()
    first = page.locator(".bot-grid .bot-card").first
    first.hover()
    first.locator(".card-remove").click()
    page.wait_for_selector("text=from your list?")
    page.click("button:has-text('Remove from your list') >> nth=-1")
    page.wait_for_function(f"document.querySelectorAll('.sidebar .bot-row').length === {before - 1}", timeout=10000)
    row = page.locator(".sidebar .bot-row").first
    row.hover()
    row.locator(".row-action").click()
    page.click("button:has-text('Remove from your list') >> nth=-1")
    page.wait_for_function(f"document.querySelectorAll('.sidebar .bot-row').length === {before - 2}", timeout=10000)
    lib = page.locator("role=tab[name=/Library/]").inner_text()
    check("removed bots stay in the Library", lib.split()[-1] == lib_before.split()[-1], (lib_before, lib))

    page.locator(".bot-grid .bot-card").first.click()
    page.wait_for_selector(".chat")
    check("in a chat: side panel still shows Your chatbots", page.locator(".sidebar .bot-row").count() > 0)
    page.click(".side-link:has-text('Home')")
    check("back home: list hidden again", page.locator(".sidebar .bot-row").count() == 0)

    page.click(".side-link:has-text('Admin console')")
    page.wait_for_selector("h1:has-text('Admin console')")
    tabs = page.locator(".admin .tab").all_inner_texts()
    check("Admin console tabs", tabs == ["Users", "Access", "Bots", "Embeds", "AI providers", "Budget"], tabs)
    page.click("role=tab[name='Bots']")
    check("Admin console: full delete available", page.locator(".admin button:has-text('Delete')").count() > 0)

    page.click(".side-link:has-text('Home')")
    page.click(".dash-card:has-text('Add a chatbot to your website')")
    page.wait_for_selector(".embed-page h1")
    check("embed page opens", "website" in page.inner_text(".embed-page h1").lower())
    check("admin: no page errors", not errors, errors)
    ctx.close()


def test_member_dashboard(env, browser, check):
    ctx, page, errors = open_home(browser, env, "member", 1400, 900)
    check("member: side panel = Home, New chatbot, Settings (no Admin console)", nav_labels(page) == ["Home", "New chatbot", "Settings"], nav_labels(page))
    page.click(".dash-card:has-text('Chat with a bot')")
    page.wait_for_selector(".bots-page .bot-card")
    check("member: can remove from their list", page.locator(".card-remove").count() > 0)
    page.set_viewport_size({"width": 390, "height": 800})
    page.wait_for_timeout(400)
    s = grid_state(page)
    check("member (phone): one column, paginated, no scrolling", s["cols"] == 1 and s["pages"] >= 2 and not s["scrolls"], s)
    page.set_viewport_size({"width": 1400, "height": 900})
    page.click(".side-link:has-text('Home')")
    page.click(".dash-card:has-text('Add a chatbot to your website')")
    page.wait_for_selector(".empty-embeds")
    page.click(".empty-embeds button")
    check("member: only bots they created are offered (none here)", "haven't created one" in page.inner_text(".add-embed"))
    check("member: no page errors", not errors, errors)
    ctx.close()
