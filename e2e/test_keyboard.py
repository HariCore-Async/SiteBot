"""Keyboard-friendly tabs, and the server key's "Last used"."""

import requests

from conftest import login


def test_keyboard_tabs_and_key_last_used(env, browser, check):
    B, A = env.B, env.api("admin")
    e = A.post(f"{B}/api/embeds", json={"site_id": env.site_id}).json()
    secret = A.post(f"{B}/api/embeds/{e['id']}/server-key").json()["secret"]
    requests.get(f"{B}/api/v1/bot", headers={"Authorization": f"Bearer {secret}"})

    ctx, page, errors = login(browser, env, "admin")
    page.goto(f"{B}/#/website/{e['id']}/design")
    page.wait_for_selector(".bot-tabs")
    stops = page.eval_on_selector_all(".bot-tabs [role=tab]", "els => els.map(t => t.tabIndex)")
    check("only the selected tab is a Tab stop", stops[0] == 0 and stops.count(0) == 1 and len(stops) >= 4, stops)
    page.focus(".bot-tabs [role=tab][aria-selected=true]")
    page.keyboard.press("ArrowRight")
    page.wait_for_selector(".install-tab")
    focused = page.wait_for_function("document.activeElement && document.activeElement.textContent.startsWith('Install')", timeout=5000)
    check("ArrowRight moves to the next tab (Install) and keeps focus there", focused)
    page.keyboard.press("End")
    page.wait_for_selector(".usage-tab")
    check("End jumps to the last tab", page.wait_for_function("document.activeElement && document.activeElement.textContent.includes('Usage')", timeout=5000))
    check("tab list has an accessible name", page.get_attribute(".bot-tabs", "aria-label") == "Chatbot settings")
    check("server key shows 'Last used'", "Last used" in page.inner_text(".usage-tab"))
    page.keyboard.press("Home")
    page.wait_for_selector(".design-tab")
    page.goto(f"{B}/")
    page.click(".dash-card:has-text('Chat with a bot')")
    page.wait_for_selector(".bots-page [role=tab]")
    page.focus(".bots-page [role=tab][aria-selected=true]")
    page.keyboard.press("ArrowRight")
    check("Chat with a bot tabs work by keyboard", page.get_attribute(".bots-page [role=tab][aria-selected=true]", "id") == "tab-library")
    check("no page errors", not errors, errors)
    ctx.close()
