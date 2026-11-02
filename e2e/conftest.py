"""End-to-end tests: the real backend and the built frontend in a real browser, against a throwaway database, a
stand-in AI (mock_llm.py) and two small test websites (one the bots are allowed on, one they aren't).

Needs Postgres with pgvector (E2E_DATABASE_URL, default the local docker one on 5433), `npm run build` in frontend/,
and Playwright's Chromium. Run from the repo root:  python -m pytest e2e -q
"""

import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "e2e" / ".output"
PAGES = OUT / "pages"
DB_URL = os.environ.get("E2E_DATABASE_URL", "postgresql+psycopg://sitebot:sitebot@localhost:5433/sitebot_e2e")
PORT = int(os.environ.get("E2E_PORT", "8100"))
AI_PORT = int(os.environ.get("E2E_AI_PORT", "5610"))
ALLOWED_PORT, BLOCKED_PORT = int(os.environ.get("E2E_ALLOWED_PORT", "5510")), int(os.environ.get("E2E_BLOCKED_PORT", "5511"))
B = f"http://localhost:{PORT}"
ALLOWED, BLOCKED = f"http://localhost:{ALLOWED_PORT}", f"http://localhost:{BLOCKED_PORT}"
ADMIN_EMAIL, MEMBER_EMAIL = "admin@e2e.test", "member@e2e.test"
SECRET = "e2e-secret-key-long-enough-for-hs256-signing"

# The backend under test and this process (which seeds the database) share these settings.
SERVER_ENV = {
    "DATABASE_URL": DB_URL,
    "SECRET_KEY": SECRET,
    "ADMIN_EMAILS": ADMIN_EMAIL,
    "EMBED_DEV_ORIGINS": ALLOWED,
    "SCHEDULER_ENABLED": "false",
    "OPENROUTER_API_KEY": "",
    "GOOGLE_CLIENT_ID": "",
    "RESEND_API_KEY": "",
    "SMTP_HOST": "",
    "SENTRY_DSN": "",
    "APP_URL": "",
    "REDIS_URL": "",
    "VERIFY_ANSWERS": "true",
    "ENABLE_PLAYWRIGHT": "false",
    # Every test talks from 127.0.0.1, much faster than real visitors; the per-visitor limit stays as it is.
    "IP_QUESTIONS_PER_MINUTE": "100000",
    "IP_QUESTIONS_PER_DAY": "100000",
    "IP_READS_PER_MINUTE": "100000",
}
os.environ.update(SERVER_ENV)
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "e2e"))

import mock_llm  # noqa: E402
import seed  # noqa: E402


def _free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _serve(directory: Path, port: int) -> ThreadingHTTPServer:
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Quiet, directory=str(directory)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Stack:
    """Everything the tests talk to, plus helpers. One per test session."""

    B, ALLOWED, BLOCKED = B, ALLOWED, BLOCKED
    log_path = OUT / "backend.log"

    def __init__(self, ids: dict):
        self.ids = ids
        self.site_id, self.domain = ids["acme"], seed.ACME_DOMAIN
        self.refresh_tokens()

    # ---- sessions
    def refresh_tokens(self) -> None:
        self.tokens = {role: seed.token_for(email, SECRET) for role, email in (("admin", ADMIN_EMAIL), ("member", MEMBER_EMAIL))}

    def api(self, role: str) -> requests.Session:
        s = requests.Session()
        s.cookies.set("sitebot_session", self.tokens[role])
        return s

    def cookie(self, role: str) -> dict:
        return {"name": "sitebot_session", "value": self.tokens[role], "url": B}

    # ---- state
    def reset(self) -> None:
        """Back to the seeded state between test modules (each module sets up what it needs)."""
        seed.reset(self.ids)
        self.refresh_tokens()

    def write_pages(self, key: str) -> None:
        seed.write_pages(PAGES, key, B)

    def member_embeds(self) -> None:
        seed.member_embeds(self.ids)

    def member_site(self, **kw) -> int:
        return seed.member_site(self.ids, **kw)

    def set_role(self, who: str, role: str) -> None:
        seed.set_role(self.ids[who], role)

    def log_size(self) -> int:
        return self.log_path.stat().st_size

    def log_since(self, size: int) -> str:
        time.sleep(0.5)
        return self.log_path.read_bytes()[size:].decode("utf-8", "ignore")


@pytest.fixture(scope="session")
def stack():
    dist = ROOT / "frontend" / "dist" / "index.html"
    if not dist.exists():
        pytest.exit("Build the frontend first: cd frontend && npm run build", 2)
    for port in (PORT, AI_PORT, ALLOWED_PORT, BLOCKED_PORT):
        if not _free(port):
            pytest.exit(f"Port {port} is in use; set E2E_PORT / E2E_AI_PORT / E2E_ALLOWED_PORT / E2E_BLOCKED_PORT.", 2)
    OUT.mkdir(exist_ok=True)
    PAGES.mkdir(exist_ok=True)
    ids = seed.fresh_database(DB_URL, ai_base=f"http://localhost:{AI_PORT}/v1", admin=ADMIN_EMAIL, member=MEMBER_EMAIL)
    servers = [mock_llm.start(AI_PORT), _serve(PAGES, ALLOWED_PORT), _serve(PAGES, BLOCKED_PORT)]
    log = open(OUT / "backend.log", "wb")
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
        cwd=ROOT / "backend", env={**os.environ, **SERVER_ENV}, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(120):
            try:
                if requests.get(f"{B}/api/config", timeout=2).status_code == 200:
                    break
            except requests.ConnectionError:
                pass
            if backend.poll() is not None:
                pytest.exit("The backend didn't start; see e2e/.output/backend.log", 2)
            time.sleep(0.5)
        else:
            pytest.exit("The backend didn't answer within a minute; see e2e/.output/backend.log", 2)
        yield Stack(ids)
    finally:
        backend.terminate()
        try:
            backend.wait(10)
        except subprocess.TimeoutExpired:
            backend.kill()
        log.close()
        for s in servers:
            s.shutdown()


@pytest.fixture(scope="module")
def env(stack):
    """The stack, reset to the seeded state once per test module."""
    stack.reset()
    return stack


@pytest.fixture(scope="session")
def playwright():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright):
    b = playwright.chromium.launch()
    yield b
    b.close()


@pytest.fixture(scope="session")
def public_browser(playwright):
    """For pages that pretend to be public websites calling SiteBot on localhost: Chrome normally blocks that (the
    real SiteBot is public, so it never applies there)."""
    b = playwright.chromium.launch(args=["--disable-features=LocalNetworkAccessChecks,BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights"])
    yield b
    b.close()


class Checks:
    """Soft checks: a test runs every step and reports every failure, not just the first."""

    def __init__(self):
        self.failed = []

    def __call__(self, name, cond, extra=""):
        if not cond:
            self.failed.append(f"{name}" + (f"  [{str(extra)[:300]}]" if extra != "" else ""))
        return bool(cond)


@pytest.fixture
def check():
    c = Checks()
    yield c
    if c.failed:
        pytest.fail("Failed checks:\n  - " + "\n  - ".join(c.failed), pytrace=False)


def login(browser, stack, role, w=1400, h=900, **ctx_args):
    """A browser signed in as admin or member: (context, page, page errors)."""
    ctx = browser.new_context(viewport={"width": w, "height": h}, **ctx_args)
    ctx.add_cookies([stack.cookie(role)])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    return ctx, page, errors


SEL = "iframe[title='Chat with us']"


def widget_visibility(page) -> str:
    return page.evaluate(f"(() => {{ const f = document.querySelector(\"{SEL}\"); return f ? f.style.visibility : 'removed'; }})()")


def same_origin() -> dict:
    return {"Sec-Fetch-Site": "same-origin"}


def cross(origin: str) -> dict:
    return {"Origin": origin, "Sec-Fetch-Site": "cross-site"}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hours_ago(h: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=h)
