"""Test chats, "installed" detection, insights, exports, rejection reasons and notification emails (API); then the
live design preview, unsaved-changes prompt, list filters, install help, conversation tools and insights (browser)."""

import csv
import io
import json
import time
import zipfile
from pathlib import Path
from unittest import mock

import requests

from app import accounts
from conftest import MEMBER_EMAIL, login, same_origin

state = {}


def test_insights_exports_and_reviews(env, check):
    B, A, M = env.B, env.api("admin"), env.api("member")
    e = A.post(f"{B}/api/embeds", json={"site_id": env.site_id}).json()
    key, eid, domain = e["key"], e["id"], e["site"]["domain"]

    def get_e():
        return [x for x in A.get(f"{B}/api/embeds").json() if x["id"] == eid][0]

    check("new embed: not detected yet", e["last_seen"] is None)
    A.get(f"{B}/api/public/{key}/config", params={"preview": "true"}, headers=same_origin())
    check("preview doesn't count as installed", get_e()["last_seen"] is None)
    requests.get(f"{B}/api/public/{key}/config", params={"origin": f"https://www.{domain}"}, headers=same_origin())
    seen = get_e()["last_seen"]
    check("page load on the website records 'installed'", seen and seen["origin"] == f"https://www.{domain}", seen)

    def ask(content, visitor, preview=False, session=requests):
        r = session.post(f"{B}/api/public/{key}/messages", headers=same_origin(), stream=True,
                         json={"visitor_id": visitor, "content": content, "origin": f"https://{domain}", "preview": preview})
        return [json.loads(line) for line in r.iter_lines() if line]

    ask("hi", "previewVisitor0000000001", preview=True, session=A)
    e1 = get_e()
    check("preview chat not counted in conversations / chats today", e1["conversations"] == 0 and e1["chats_today"] == 0, (e1["conversations"], e1["chats_today"]))
    chats = A.get(f"{B}/api/embeds/{eid}/chats").json()
    check("preview chat listed and labelled as a test", len(chats) == 1 and chats[0]["is_test"] is True)

    ask("What does Acme Outdoor sell?", "realVisitor000000000001")
    ask("What is the airspeed velocity of an unladen swallow?", "realVisitor000000000001")
    ask("=HYPERLINK(\"http://evil.example\",\"click\")", "realVisitor000000000002")
    e2 = get_e()
    check("visitor chats counted", e2["conversations"] == 2 and e2["chats_today"] == 2, (e2["conversations"], e2["chats_today"]))
    real = [c for c in A.get(f"{B}/api/embeds/{eid}/chats").json() if not c["is_test"]]
    check("chat list flags answers it couldn't give", any(c["unanswered"] >= 1 for c in real), real)

    ins = A.get(f"{B}/api/embeds/{eid}/insights").json()
    check("insights: 30 days of chats, today counted", len(ins["days"]) == 30 and ins["days"][-1]["chats"] == 2, ins["days"][-1])
    check("insights: most asked", any("sell" in q["question"].lower() for q in ins["top_questions"]), ins["top_questions"])
    check("insights: couldn't answer list", any("swallow" in q["question"].lower() for q in ins["unanswered"]), ins["unanswered"])
    check("insights: test chats left out", all(q["question"] != "hi" for q in ins["top_questions"]))
    check("insights: owner only", M.get(f"{B}/api/embeds/{eid}/insights").status_code == 404)

    def rows_of(r):
        return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))

    r = A.get(f"{B}/api/embeds/{eid}/export", params={"format": "csv"})
    rows = rows_of(r)
    check("CSV export: download with header and rows", r.status_code == 200 and "attachment" in r.headers.get("content-disposition", "") and rows[0][0] == "Conversation" and len(rows) >= 7, (r.status_code, len(rows)))
    check("CSV export: test chats left out by default", all(row[3] != "yes" for row in rows[1:]))
    check("CSV export: formula-looking text neutralised", any(row[6].startswith("'=HYPERLINK") for row in rows[1:]))
    check("CSV export: include tests when asked", any(row[3] == "yes" for row in rows_of(A.get(f"{B}/api/embeds/{eid}/export", params={"format": "csv", "tests": "true"}))))
    urows = rows_of(A.get(f"{B}/api/embeds/{eid}/export", params={"format": "csv", "unanswered": "true"}))
    convs = {row[0] for row in urows[1:]}
    check("CSV export: 'couldn't answer' filter keeps only those conversations", convs and all(any(x[0] == c and x[7] == "no" for x in urows[1:]) for c in convs), convs)
    check("CSV export: date range", len(rows_of(A.get(f"{B}/api/embeds/{eid}/export", params={"format": "csv", "start": "2099-01-01"}))) == 1)
    check("export: bad date refused", A.get(f"{B}/api/embeds/{eid}/export", params={"start": "yesterday"}).status_code == 400)
    r = A.get(f"{B}/api/embeds/{eid}/export", params={"format": "xlsx"})
    z = zipfile.ZipFile(io.BytesIO(r.content))
    sheet = z.read("xl/worksheets/sheet1.xml").decode()
    check("Excel export: valid workbook with the messages", r.headers["content-type"].startswith("application/vnd.openxmlformats") and "Conversation" in sheet and "swallow" in sheet and z.testzip() is None)
    check("export: owner only", M.get(f"{B}/api/embeds/{eid}/export").status_code == 404)

    # Rejection reason + emails (email isn't configured here, so they're logged and nothing breaks).
    site_id = env.member_site()
    size = env.log_size()
    r = M.post(f"{B}/api/embeds", json={"site_id": site_id})
    mid = r.json()["id"]
    check("member's request is pending", r.json()["status"] == "pending")
    log = env.log_since(size)
    check("admins notified of the request (logged: email not configured)", "Email isn't configured; not sending" in log and "wants to add Member Test Site" in log, log[-300:])
    r = A.patch(f"{B}/api/admin/embeds/{mid}", json={"status": "rejected", "note": "Please use your company website."})
    check("admin rejects with a reason", r.status_code == 200 and r.json()["review_note"] == "Please use your company website.")
    mine = M.get(f"{B}/api/embeds").json()[0]
    check("owner sees the reason", mine["status"] == "rejected" and mine["review_note"] == "Please use your company website.")
    check("owner notified of the rejection (logged)", "wasn't approved" in env.log_since(size))
    r = M.post(f"{B}/api/embeds", json={"site_id": site_id})
    check("asking again clears the reason", r.json()["status"] == "pending" and r.json()["review_note"] == "")
    A.patch(f"{B}/api/admin/embeds/{mid}", json={"status": "approved"})
    check("approval notifies the owner (logged)", "is approved for your website" in env.log_since(size))

    sent = []
    with mock.patch.object(accounts, "email_enabled", return_value=True), mock.patch.object(accounts, "send_email", side_effect=lambda to, s, b: sent.append(to)):
        accounts.notify(["A@x.com", "a@x.com", "b@x.com", "", "not-an-email"], "s", "b")
        time.sleep(0.5)
    check("notify(): de-duplicated recipients, invalid ones skipped", sorted(sent) == ["a@x.com", "b@x.com"], sent)
    with mock.patch.object(accounts, "email_enabled", return_value=True), mock.patch.object(accounts, "send_email", side_effect=OSError("smtp down")):
        accounts.notify(["a@x.com"], "s", "b")
        time.sleep(0.5)
    state.update(eid=eid)


def test_dashboard_tools_in_a_browser(env, browser, check):
    B, A = env.B, env.api("admin")
    eid = state["eid"]
    ctx, page, errors = login(browser, env, "admin", accept_downloads=True)
    page.goto(f"{B}/#/website/{eid}/design")
    preview = page.frame_locator(".embed-preview iframe")
    preview.locator(".w-head").wait_for(timeout=15000)

    page.fill("input[placeholder='Acme Outdoor']", "Live Title")
    preview.locator(".w-head:has-text('Live Title')").wait_for(timeout=5000)
    page.select_option(".design-tab select >> nth=1", "dark")
    page.wait_for_timeout(300)
    check("live preview: theme changes before saving", preview.locator("html[data-theme='dark']").count() == 1)
    check("live preview: marked as unsaved", "unsaved changes" in page.inner_text(".preview-label"))

    page.click("role=tab[name='Install']")
    page.wait_for_selector("text=Discard changes?")
    page.click(".modal .btn.ghost")
    check("cancel keeps you on Design with the changes", page.locator(".design-tab").count() == 1 and page.input_value("input[placeholder='Acme Outdoor']") == "Live Title")
    page.click("button:has-text('← Your website chatbots')")
    page.wait_for_selector("text=Discard changes?")
    page.click(".modal .btn.danger-solid")
    page.wait_for_selector(".embed-tile")
    check("discarding leaves; nothing saved", A.get(f"{B}/api/embeds").json()[0]["style"]["title"] == "")

    tile = page.inner_text(".embed-tile")
    check("card shows today's spend and install state", "$" in tile and "Installed on" in tile, tile)
    page.fill("input[aria-label='Search website chatbots']", "zzz")
    check("search filters the cards", page.locator(".embed-tile").count() == 0 and "No website chatbots match" in page.inner_text(".embed-page"))
    page.fill("input[aria-label='Search website chatbots']", "acme")
    check("search finds the card", page.locator(".embed-tile").count() == 1)
    page.click(".status-filter .tab:has-text('Pending')")
    check("status filter: Pending hides the live one", page.locator(".embed-tile").count() == 0)
    page.click(".status-filter .tab:has-text('Live')")
    check("status filter: Live shows it", page.locator(".embed-tile").count() == 1)

    page.click(".embed-tile")
    page.click("role=tab[name='Install']")
    page.wait_for_selector(".install-check")
    check("Check installation: 'Installed', with website and time", "Installed" in page.inner_text(".install-check") and env.domain in page.inner_text(".install-check"))
    guides = page.locator(".guide summary").all_inner_texts()
    check("platform guides", guides == ["WordPress", "Shopify", "Wix", "Webflow", "Squarespace", "Google Tag Manager"], guides)
    page.click(".guide summary:has-text('Shopify')")
    check("guide shows steps and the real snippet", "theme.liquid" in page.inner_text(".guide[open]") and "embed.js" in page.inner_text(".guide[open] code"))

    page.click("role=tab[name='Conversations']")
    page.wait_for_selector(".convo-row")
    check("test chat labelled 'Test'", page.locator(".convo-row .pill:text-is('Test')").count() == 1)
    total = page.locator(".convo-row").count()
    page.click(".convo-toolbar label:has-text('Show test chats') input")
    check("test chats can be hidden", page.locator(".convo-row").count() == total - 1)
    page.click(".convo-toolbar label:has-text(\"Couldn't answer\") input")
    rows = page.locator(".convo-row")
    check("'Couldn't answer' filter", rows.count() >= 1 and all("Couldn't answer" in t for t in rows.all_inner_texts()))
    rows.first.click()
    page.wait_for_selector(".convo-msg.missed")
    with page.expect_download() as dl:
        page.click(".export-btns a:has-text('Excel')")
    check("Excel export downloads", dl.value.suggested_filename.endswith(".xlsx"))
    with page.expect_download() as dl:
        page.click(".export-btns a:has-text('CSV')")
    rows = list(csv.reader(io.StringIO(Path(dl.value.path()).read_text(encoding="utf-8-sig"))))
    check("CSV export follows the filters (couldn't answer, no tests)", rows[0][0] == "Conversation" and all(r[3] != "yes" for r in rows[1:]) and any(r[7] == "no" for r in rows[1:]), rows[:3])

    page.click("role=tab[name='Usage & settings']")
    page.wait_for_selector(".day-bars")
    check("chats per day: 30 bars", page.locator(".day-bar").count() == 30)
    check("most asked list", page.locator(".usage-tab section:has-text('Most asked') li").count() >= 1)
    check("couldn't answer list", "swallow" in page.inner_text(".usage-tab section:has-text(\"Couldn't answer\")").lower())

    page.set_viewport_size({"width": 390, "height": 800})
    page.wait_for_timeout(300)
    tops = page.eval_on_selector_all(".bot-tabs .tab", "els => els.map(e => Math.round(e.getBoundingClientRect().top))")
    scrollable = page.eval_on_selector(".bot-tabs", "el => el.scrollWidth > el.clientWidth && getComputedStyle(el).overflowX === 'auto'")
    check("phone: tabs on one row, swipeable", len(set(tops)) == 1 and scrollable, (tops, scrollable))
    check("admin: no page errors", not errors, errors)
    ctx.close()

    # Rejection reason: the admin's reject form, then the owner's page.
    env.member_embeds()
    ctx, page, errors = login(browser, env, "admin")
    page.goto(f"{B}/")
    page.click(".side-link:has-text('Admin console')")
    page.click("role=tab[name='Embeds']")
    row = page.locator(f"tr:has-text('{MEMBER_EMAIL}'):has-text('Waiting') >> nth=0")
    row.locator("button:has-text('Reject')").click()
    row.locator("input[aria-label='Reason for not approving']").fill("Please use the company's own website.")
    row.locator("button.danger-solid").click()
    page.wait_for_selector("text=Reason: Please use the company's own website.")
    ctx.close()
    ctx, page, errors = login(browser, env, "member")
    page.goto(f"{B}/#/website")
    page.wait_for_selector(".embed-tile")
    page.locator(".embed-tile:has(.status:text-is('Not approved'))").first.click()
    page.wait_for_selector(".banner.rejected")
    check("owner sees the reason on the bot page", "Please use the company's own website." in page.inner_text(".banner.rejected"))
    check("member: no page errors", not errors, errors)
    ctx.close()
