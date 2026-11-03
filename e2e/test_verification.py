"""Domain verification on a waiting website chatbot. The lookups are real (a fetch and DNS-over-HTTPS) against a
domain that doesn't exist, so both report that it isn't verified yet."""

from conftest import login


def test_domain_verification_ui(env, browser, check):
    env.member_embeds()
    ctx, page, errors = login(browser, env, "member", 1400, 950)
    page.goto(f"{env.B}/#/website")
    page.locator(".embed-tile:has(.status:text-is('Pending'))").first.click()
    page.wait_for_selector(".banner.pending")
    check("pending banner offers domain verification", "verify your domain" in page.inner_text(".banner.pending").lower())
    page.click(".banner.pending button:has-text('verify your domain')")
    page.wait_for_selector(".verification")
    text = page.inner_text(".verification")
    check("shows the meta tag and DNS record to add", "sitebot-verification" in text and "DNS TXT record" in text)
    page.click(".verification button:has-text('Check meta tag')")
    page.wait_for_selector(".verification .error", timeout=30000)
    check("meta tag check reports it's not there yet", "Not verified yet" in page.inner_text(".verification .error"), page.inner_text(".verification .error"))
    page.click(".verification button:has-text('Check DNS record')")
    page.wait_for_function("document.querySelector('.verification .error') && /TXT|DNS/.test(document.querySelector('.verification .error').textContent)", timeout=30000)
    check("DNS check reports no record yet (or that DNS can't be reached)", "Not verified yet" in page.inner_text(".verification .error"), page.inner_text(".verification .error"))
    check("still pending", page.inner_text(".bot-head .status") == "Pending")
    check("no page errors", not errors, errors)
    ctx.close()
