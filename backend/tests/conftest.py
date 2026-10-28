"""Test setup: a throwaway database, fake AI calls and fake embeddings, so tests need no keys and download nothing.

Database: TEST_DATABASE_URL, default postgresql+psycopg://sitebot:sitebot@localhost:5433/sitebot_test (the local
docker compose Postgres). CI points it at a pgvector service container. Every run starts from empty tables.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://sitebot:sitebot@localhost:5433/sitebot_test")
os.environ.update(
    DATABASE_URL=TEST_DB,
    SECRET_KEY="test-secret-key-that-is-long-enough-for-hs256",
    ADMIN_EMAILS="admin@test.example",
    OPENROUTER_API_KEY="test-key",
    GOOGLE_CLIENT_ID="",
    RESEND_API_KEY="",
    SMTP_HOST="",
    EMBED_DEV_ORIGINS="http://localhost:5500",
    VERIFY_ANSWERS="true",
    SENTRY_DSN="",
    APP_URL="",
)

import jwt  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _ensure_database() -> None:
    url = sa.engine.make_url(TEST_DB)
    admin = sa.create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if not conn.scalar(sa.text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": url.database}):
            conn.execute(sa.text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


_ensure_database()

from app import embeddings, knowledge, llm, main, retrieval, suggest  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.embeds import ip_limiter, read_limiter, server_limiter, visitor_limiter  # noqa: E402
from app.models import Chunk, Page, Site, User  # noqa: E402

VECTOR = [1.0] + [0.0] * (settings.embedding_dim - 1)


class FakeAI:
    """Stands in for the LLM. `answer` is what the bot streams; "NOT_FOUND" makes it say it doesn't know."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.answer = "We sell running shoes and trail shoes [1]."
        self.calls = []

    def complete(self, purpose, messages, max_tokens=300, site_id=None):
        system = messages[0]["content"]
        self.calls.append(("complete", purpose, site_id))
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001, "model": "fake-fast", "provider": "Fake"}
        if "check an assistant's answer" in system:
            return "NONE", usage
        if "suggested questions" in system:
            return "What do you sell?\nDo you ship abroad?\nWhat are your opening hours?", usage
        if "standalone search question" in system:
            return messages[-1]["content"].split("LATEST MESSAGE:")[-1].strip(), usage
        return "ok", usage

    def stream(self, purpose, messages, max_tokens=900, site_id=None):
        self.calls.append(("stream", purpose, site_id))
        for word in self.answer.split(" "):
            yield "token", word + " "
        yield "usage", {"prompt_tokens": 50, "completion_tokens": 20, "cost": 0.002, "model": "fake-answer", "provider": "Fake"}


AI = FakeAI()


@pytest.fixture(scope="session", autouse=True)
def database():
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
    init_db()
    yield


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    AI.reset()
    monkeypatch.setattr(llm, "complete", AI.complete)
    monkeypatch.setattr(llm, "stream", AI.stream)
    monkeypatch.setattr(retrieval, "embed_query", lambda text: VECTOR)
    monkeypatch.setattr(embeddings, "embed_query", lambda text: VECTOR)
    monkeypatch.setattr(knowledge, "embed_passages", lambda texts: [VECTOR for _ in texts])
    monkeypatch.setattr(main, "warm_up", lambda: None)
    monkeypatch.setattr(suggest, "retrieve", lambda db, site_id, gen, q: ([], 1.0))
    for limiter in (visitor_limiter, ip_limiter, read_limiter, server_limiter):
        limiter.hits.clear()
    yield AI


@pytest.fixture(scope="session")
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


_counter = iter(range(1, 10**6))


def make_user(role="member", email=None) -> User:
    s = SessionLocal()
    n = next(_counter)
    u = User(email=email or f"user{n}@test.example", name=f"User {n}", role=role, email_verified=True)
    s.add(u)
    s.commit()
    s.refresh(u)
    s.close()
    return u


def session_for(user: User) -> dict:
    token = jwt.encode({"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, settings.secret_key, algorithm="HS256")
    return {"sitebot_session": token}


class As:
    """A signed-in user's view of the API: as_admin.get("/api/me")."""

    def __init__(self, client, user):
        self.client, self.user, self.cookies = client, user, session_for(user)

    def _call(self, method, path, **kw):
        self.client.cookies.clear()
        for k, v in self.cookies.items():
            self.client.cookies.set(k, v)
        try:
            return self.client.request(method, path, **kw)
        finally:
            self.client.cookies.clear()

    def get(self, path, **kw):
        return self._call("GET", path, **kw)

    def post(self, path, **kw):
        return self._call("POST", path, **kw)

    def patch(self, path, **kw):
        return self._call("PATCH", path, **kw)

    def put(self, path, **kw):
        return self._call("PUT", path, **kw)

    def delete(self, path, **kw):
        return self._call("DELETE", path, **kw)


@pytest.fixture
def admin(client):
    return As(client, make_user("admin"))


@pytest.fixture
def member(client):
    return As(client, make_user("member"))


def make_site(created_by=None, domain=None, chunks=3) -> Site:
    """A ready bot with a few indexed pages, all matching the fake query vector."""
    s = SessionLocal()
    n = next(_counter)
    domain = domain or f"shop{n}.example"
    site = Site(domain=domain, name=f"Shop {n}", root_url=f"https://{domain}/", status="ready", generation=1, live_pages=chunks, created_by=created_by)
    s.add(site)
    s.commit()
    for i in range(chunks):
        url = f"https://{domain}/page-{i}"
        s.add(Page(site_id=site.id, generation=1, url=url, title=f"Page {i}", status="indexed"))
        s.add(Chunk(site_id=site.id, generation=1, url=url, title=f"Page {i}", content=f"We sell running shoes and trail shoes. Page {i}.", embedding=VECTOR))
    s.commit()
    s.refresh(site)
    s.close()
    return site


@pytest.fixture
def site(admin):
    return make_site(created_by=admin.user.id)


@pytest.fixture
def embed(admin, site):
    """An approved embed on `site`, owned by `admin`."""
    r = admin.post("/api/embeds", json={"site_id": site.id})
    assert r.status_code == 200, r.text
    return r.json()


SAME = {"Sec-Fetch-Site": "same-origin"}


def cross(origin):
    return {"Origin": origin, "Sec-Fetch-Site": "cross-site"}


def ndjson(response) -> list[dict]:
    import json

    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def ask(client, key, content, visitor="visitorAAAAAAAAAAAAAAAA1", origin=None, headers=None, preview=False):
    return client.post(
        f"/api/public/{key}/messages",
        json={"visitor_id": visitor, "content": content, "origin": origin or "", "preview": preview},
        headers=headers or SAME,
    )
