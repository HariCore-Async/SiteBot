from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # Columns added after the first release; create_all doesn't alter existing tables.
        conn.execute(text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS suggestions JSON"))
        conn.execute(text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS full_crawl BOOLEAN NOT NULL DEFAULT false"))
        conn.execute(text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS truncated BOOLEAN NOT NULL DEFAULT false"))
        conn.execute(text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS live_pages INTEGER NOT NULL DEFAULT 0"))
        # Leftovers from runs interrupted by a restart: a later run of the same generation would otherwise
        # duplicate them.
        conn.execute(text("DELETE FROM chunks c USING sites s WHERE c.site_id = s.id AND c.generation > s.generation"))
        conn.execute(text("DELETE FROM pages p USING sites s WHERE p.site_id = s.id AND p.generation > s.generation"))
        # Older versions could leave duplicates inside the live generation the same way; remove them once.
        conn.execute(
            text(
                "DELETE FROM chunks a USING chunks b WHERE a.id > b.id AND a.site_id = b.site_id "
                "AND a.generation = b.generation AND a.url = b.url AND a.content = b.content"
            )
        )
        conn.execute(
            text(
                "DELETE FROM pages a USING pages b WHERE a.id > b.id AND a.site_id = b.site_id "
                "AND a.generation = b.generation AND a.url = b.url"
            )
        )
        # Count the live index's pages from the pages table (progress counters may be left over from an interrupted run).
        conn.execute(
            text(
                "UPDATE sites s SET live_pages = (SELECT count(DISTINCT p.url) FROM pages p WHERE p.site_id = s.id "
                "AND p.generation = s.generation AND p.status = 'indexed') WHERE s.generation > 0"
            )
        )
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(40) UNIQUE"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false"))
        # Website embeds: visitors' chats have no user, and usage remembers which embed caused it.
        conn.execute(text("ALTER TABLE chats ALTER COLUMN user_id DROP NOT NULL"))
        conn.execute(text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS embed_id INTEGER REFERENCES embeds(id) ON DELETE CASCADE"))
        conn.execute(text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS visitor_id VARCHAR(64)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chats_embed_id ON chats (embed_id)"))
        conn.execute(text("ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS embed_id INTEGER REFERENCES embeds(id) ON DELETE SET NULL"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_usage_events_embed_id ON usage_events (embed_id)"))
    with engine.begin() as conn:
        # A crawl that was running when the server stopped can never finish; mark it so it can be retried.
        conn.execute(
            text(
                "UPDATE sites SET status = CASE WHEN generation > 0 THEN 'ready' ELSE 'failed' END, "
                "message = 'Indexing was interrupted by a server restart. Please try again.' "
                "WHERE status IN ('queued', 'crawling', 'embedding')"
            )
        )
