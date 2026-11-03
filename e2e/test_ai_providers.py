"""AI providers: add an OpenAI-compatible provider in the Admin console, test its models, answer with one, fall back
when it fails, choose a model per bot; then provider alerts and the AI health panel."""

import json

from conftest import AI_PORT, login, same_origin


def chat_answer(env, A, question):
    chat = A.post(f"{env.B}/api/chats", json={"site_id": env.site_id}).json()
    A.post(f"{env.B}/api/chats/{chat['id']}/reset")
    r = A.post(f"{env.B}/api/chats/{chat['id']}/messages", json={"content": question}, stream=True)
    events = [json.loads(line) for line in r.iter_lines() if line]
    text = "".join(e.get("text", "") for e in events if e["type"] == "token")
    for e in events:
        if e["type"] == "replace":
            text = e["text"]
    return text, events[-1]


def test_add_provider_fallback_and_per_bot_model(env, browser, check):
    B, A = env.B, env.api("admin")
    ctx, page, errors = login(browser, env, "admin", 1400, 1000)
    page.goto(f"{B}/")
    page.click(".side-link:has-text('Admin console')")
    page.click("role=tab[name='AI providers']")
    page.wait_for_selector(".ai-providers")
    check("the seeded provider is listed", "Local test model" in page.inner_text(".ai-providers"))

    page.select_option(".add-provider select", "openai_compatible")
    page.fill(".add-provider input[placeholder^='http://localhost']", f"http://localhost:{AI_PORT}/v1")
    page.fill(".add-provider label:has-text('Name') input", "Local mock")
    page.click(".add-provider button:has-text('Add provider')")
    page.wait_for_selector(".provider:has-text('Local mock')")
    prov = page.locator(".provider:has-text('Local mock')")
    for model in ("mock-good", "mock-down"):
        prov.locator("input[aria-label='Model ID']").fill(model)
        prov.locator("input[aria-label='Input price per million tokens']").fill("1")
        prov.locator("input[aria-label='Output price per million tokens']").fill("2")
        prov.locator("button:has-text('Add model')").click()
        page.wait_for_selector(f".provider:has-text('Local mock') td:has-text('{model}')")
    check("provider and two models added", prov.locator("tbody tr").count() == 2)
    prov.locator("tr:has-text('mock-good') button:has-text('Test connection')").click()
    page.wait_for_selector(".provider:has-text('Local mock') tr:has-text('mock-good') .ok-text")
    prov.locator("tr:has-text('mock-down') button:has-text('Test connection')").click()
    page.wait_for_selector(".provider:has-text('Local mock') tr:has-text('mock-down') .error-text")
    check("Test connection: working model OK, broken model shows the error", "503" in prov.locator("tr:has-text('mock-down') .error-text").inner_text())

    mp = [x for x in A.get(f"{B}/api/admin/ai").json()["providers"] if x["name"] == "Local mock"][0]
    good = [m["ref"] for m in mp["models"] if m["model"] == "mock-good"][0]
    down = [m["ref"] for m in mp["models"] if m["model"] == "mock-down"][0]
    page.reload()
    page.click(".side-link:has-text('Admin console')")
    page.click("role=tab[name='AI providers']")
    page.wait_for_selector(".ai-defaults")
    page.select_option(".ai-defaults label:has-text('Answers') select", down)
    page.select_option(".ai-defaults label:has-text('Fast tasks') select", good)
    page.select_option(".ai-defaults select[aria-label='Add a fallback model']", good)
    page.click(".ai-defaults button:has-text('Add')")
    page.click(".ai-defaults button:has-text('Save')")
    page.wait_for_selector(".ai-defaults button:has-text('Saved')")
    check("defaults saved from the UI", A.get(f"{B}/api/admin/ai").json()["defaults"] == {"answer": down, "fast": good, "fallbacks": [good]})

    text, done = chat_answer(env, A, "What does Acme Outdoor sell?")
    check("chat answered by the fallback model after the default failed", text.strip().endswith("[1].") and done["type"] == "done", (text, done))

    seeded_good = f"m:{env.ids['models']['mock-good']}"
    page.click("role=tab[name='Bots']")
    sel = page.locator("select[aria-label^='Answer model for Acme Outdoor']")
    sel.select_option(seeded_good)
    page.wait_for_timeout(800)
    check("per-bot model saved", [s for s in A.get(f"{B}/api/sites").json() if s["id"] == env.site_id][0]["answer_model"] == seeded_good)
    text, done = chat_answer(env, A, "What does Acme Outdoor sell?")
    check("that bot now answers with its own model, without falling back", done["type"] == "done" and done.get("grounded") is True, (text[:80], done))
    sel.select_option("")
    page.wait_for_timeout(800)

    page.click("role=tab[name='AI providers']")
    page.locator(".provider:has-text('Local mock') button:has-text('Remove provider')").click()
    page.click(".modal .btn.danger-solid")
    page.wait_for_selector(".provider:has-text('Local mock')", state="detached")
    check("provider removed", all(p["name"] != "Local mock" for p in A.get(f"{B}/api/admin/ai").json()["providers"]))
    check("no page errors", not errors, errors)
    ctx.close()


def test_provider_alerts_and_health(env, browser, check):
    B, A = env.B, env.api("admin")
    broke, good = (f"m:{env.ids['models'][m]}" for m in ("mock-broke", "mock-good"))
    A.put(f"{B}/api/admin/ai/defaults", json={"answer": broke, "fast": good, "fallbacks": [good]})
    e = A.post(f"{B}/api/embeds", json={"site_id": env.site_id}).json()
    r = A.post(f"{B}/api/public/{e['key']}/messages", headers=same_origin(), json={"visitor_id": "alertVisitor00000000001", "content": "What does Acme Outdoor sell?", "preview": True})
    check("visitor still gets an answer through the fallback", '"type": "done"' in r.text, r.text[-200:])
    alerts = A.get(f"{B}/api/admin/ai/health").json()["alerts"]
    check("alert raised: out of credit", any(a["kind"] == "credit" and a["model"] == "mock-broke" for a in alerts), alerts)

    ctx, page, errors = login(browser, env, "admin")
    page.goto(B)
    page.click(".side-link:has-text('Admin')")
    page.wait_for_selector(".provider-alert")
    check("red banner in the Admin console", "out of credit" in page.inner_text(".provider-alert"), page.inner_text(".provider-alert"))
    page.click(".provider-alert button:text-is('AI providers')")
    page.wait_for_selector(".ai-health table")
    row = page.inner_text(".ai-health tr:has-text('Local test model')")
    check("AI health shows the provider's requests and the 402", "requires more credits" in row, row)
    page.click(".provider-alert button:text-is('Dismiss')")
    page.wait_for_selector(".provider-alert", state="detached")
    check("dismissed", A.get(f"{B}/api/admin/ai/health").json()["alerts"] == [])
    check("no page errors", not errors, errors)
    ctx.close()
