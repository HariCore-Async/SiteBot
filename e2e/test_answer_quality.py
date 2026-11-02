"""Test questions in the dashboard (add, run, see what passed and why), and the answer cache for repeated questions."""

import json

import requests

from conftest import login, same_origin


def test_test_questions_tab(env, browser, check):
    B, A = env.B, env.api("admin")
    e = A.post(f"{B}/api/embeds", json={"site_id": env.site_id}).json()
    ctx, page, errors = login(browser, env, "admin")
    page.goto(f"{B}/#/website/{e['id']}/tests")
    page.wait_for_selector(".tests-tab")
    check("empty state", "No test questions yet" in page.inner_text(".tests-tab") and page.locator("button:has-text('Run all')").is_disabled())

    def add(question, expected="", declines=False):
        page.click("button:has-text('Add a question')")
        page.fill(".answer-form input[maxlength='500']", question)
        if declines:
            page.check(".answer-form input[type=checkbox]")
        elif expected:
            page.fill(".answer-form textarea", expected)
        page.click(".answer-form button:has-text('Add question')")
        page.wait_for_selector(f".test-list li:has-text(\"{question}\")")

    add("What does Acme Outdoor sell?", "hiking boots")
    add("What is the airspeed velocity of an unladen swallow?", declines=True)
    add("Which city is the shop in?", "Paris")
    check("three questions listed", page.locator(".test-list > li").count() == 3)
    check("declining question shown as such", "Should say it doesn't know" in page.inner_text(".test-list li:has-text('swallow')"))

    page.click("button:has-text('Run all')")
    page.wait_for_selector("text=/2 of 3 passed/", timeout=60000)
    rows = {q: page.inner_text(f".test-list li:has-text(\"{q}\")") for q in ("Acme Outdoor sell", "swallow", "Which city")}
    check("answered with the expected facts: Pass", "Pass" in rows["Acme Outdoor sell"], rows["Acme Outdoor sell"])
    check("declined what the website doesn't cover: Pass", "Pass" in rows["swallow"], rows["swallow"])
    check("wrong facts: Fail, with the reason", "Fail" in rows["Which city"] and "different" in rows["Which city"], rows["Which city"])
    page.click(".test-list li:has-text('Which city') summary")
    page.screenshot(path="e2e/.output/tests-tab.png", full_page=True)
    check("the answer it gave is shown", "Lyon" in page.inner_text(".test-list li:has-text('Which city') .test-answer"))
    check("run summary says it was run by hand", "run by hand" in page.inner_text(".tests-tab"))
    chats = A.get(f"{B}/api/embeds/{e['id']}/chats").json()
    check("test runs leave no conversations behind", chats == [], chats)
    check("no page errors", not errors, errors)
    ctx.close()


def test_answer_cache(env, check):
    B, A = env.B, env.api("admin")
    e = A.post(f"{B}/api/embeds", json={"site_id": env.site_id}).json()

    def ask(visitor):
        r = requests.post(f"{B}/api/public/{e['key']}/messages", headers=same_origin(), stream=True,
                          json={"visitor_id": visitor, "content": "Do you ship to Switzerland?", "origin": f"https://{env.domain}"})
        events = [json.loads(line) for line in r.iter_lines() if line]
        return "".join(x.get("text", "") for x in events if x["type"] == "token").strip(), events[-1]

    spent = lambda: [x for x in A.get(f"{B}/api/embeds").json() if x["id"] == e["id"]][0]["spent_today_usd"]  # noqa: E731
    first, done1 = ask("visitorCacheE2E000000001")
    after_first = spent()
    second, done2 = ask("visitorCacheE2E000000002")
    check("same answer and sources the second time", second == first and done2["sources"] == done1["sources"] and done2["grounded"], (first, second))
    check("the second time costs nothing", spent() == after_first and after_first > 0, (after_first, spent()))
    check("both are conversations for the owner", len(A.get(f"{B}/api/embeds/{e['id']}/chats").json()) == 2)
    A.post(f"{B}/api/sites/{env.site_id}/knowledge/answers", json={"question": "Do you ship to Switzerland?", "answer": "Yes, for a flat fee of 12 euros."})
    ask("visitorCacheE2E000000003")
    check("teaching the bot clears the cache: the next answer costs again", spent() > after_first)
