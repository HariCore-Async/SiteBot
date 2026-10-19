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
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(40) UNIQUE"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false"))
    with engine.begin() as conn:
        # A crawl that was running when the server stopped can never finish; mark it so it can be retried.
        conn.execute(
            text(
                "UPDATE sites SET status = CASE WHEN generation > 0 THEN 'ready' ELSE 'failed' END, "
                "message = 'Indexing was interrupted by a server restart. Please try again.' "
                "WHERE status IN ('queued', 'crawling', 'embedding')"
            )
        )
