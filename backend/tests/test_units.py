"""Small pure functions: domain lock, CSS sanitiser, question grouping, Excel writer, rate limiter, emails."""

import io
import time
import zipfile
from types import SimpleNamespace
from unittest import mock

from app import accounts
from app.embeds import RateLimiter, normalize_question, origin_allowed, sanitize_css
from app.xlsx import to_xlsx

SITE = SimpleNamespace(domain="shop.example")
LOCKED = SimpleNamespace(restrict_to_domain=True)
OPEN = SimpleNamespace(restrict_to_domain=False)


def test_domain_lock_allows_own_domain_www_and_subdomains():
    for origin in ("https://shop.example", "https://www.shop.example", "https://help.shop.example/", "HTTPS://Shop.Example"):
        assert origin_allowed(LOCKED, SITE, origin), origin


def test_domain_lock_refuses_other_sites_lookalikes_and_http():
    for origin in ("https://evil.example", "https://shop.example.evil.com", "https://notshop.example", "http://shop.example", "", "null"):
        assert not origin_allowed(LOCKED, SITE, origin), origin


def test_dev_origins_always_allowed():
    assert origin_allowed(LOCKED, SITE, "http://localhost:5500")


def test_unlocked_allows_any_https_but_not_http():
    assert origin_allowed(OPEN, SITE, "https://other-shop.example")
    assert not origin_allowed(OPEN, SITE, "http://other-shop.example")


def test_css_sanitiser_removes_anything_that_loads_or_runs():
    css = sanitize_css(
        ".w-head{letter-spacing:.1em}\n@import url(https://evil.example/x.css);\n.a{background:url(https://evil.example/t.png)}"
        "\n.b{background:u\\72l(https://evil.example/y)}\n.c{background-image:image-set(\"https://evil.example/z.png\" 1x)}"
        "\n.d{width:expression(alert(1))}\n</style><script>alert(1)</script>"
    )
    assert ".w-head{letter-spacing:.1em}" in css
    for bad in ("@import", "url(", "image-set", "expression(", "<", "\\"):
        assert bad not in css.lower(), bad


def test_css_sanitiser_caps_length():
    assert len(sanitize_css("a{}" * 5000)) <= 5000


def test_questions_group_by_normalised_text():
    assert normalize_question("Do you ship to Canada?") == normalize_question("  do YOU ship to canada  ")
    assert normalize_question("?!") == ""


def test_xlsx_is_a_valid_workbook():
    data = to_xlsx([["Name", "Count"], ["Shoes & socks <1>", 3], ["\x01bad control char", None]], "Report")
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.testzip() is None
    sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert "Shoes &amp; socks &lt;1&gt;" in sheet and "<v>3</v>" in sheet and "\x01" not in sheet
    assert 'name="Report"' in z.read("xl/workbook.xml").decode()


def test_rate_limiter_windows():
    rl = RateLimiter([(3, 60)])
    assert [rl.allow("k") for _ in range(4)] == [True, True, True, False]
    assert rl.allow("other")


def test_notify_dedupes_skips_invalid_and_never_raises():
    sent = []
    with mock.patch.object(accounts, "email_enabled", return_value=True), mock.patch.object(accounts, "send_email", side_effect=lambda to, s, b: sent.append(to)):
        accounts.notify(["A@x.com", "a@x.com", "b@x.com", "", "nope"], "s", "b")
        time.sleep(0.3)
    assert sorted(sent) == ["a@x.com", "b@x.com"]
    with mock.patch.object(accounts, "email_enabled", return_value=True), mock.patch.object(accounts, "send_email", side_effect=OSError("down")):
        accounts.notify(["a@x.com"], "s", "b")
        time.sleep(0.3)


def test_notify_without_provider_sends_nothing():
    with mock.patch.object(accounts, "send_email") as send:
        accounts.notify(["a@x.com"], "s", "b")
        time.sleep(0.2)
    send.assert_not_called()
