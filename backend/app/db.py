from collections.abc import Iterator
from pathlib import Path

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


MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
# Any fixed number: the lock that keeps two copies of the app from migrating the same database at once.
MIGRATION_LOCK = 4242001


def migrate(bind=None, target: str = "head") -> None:
    """Brings the database schema up to date (backend/migrations). Safe on a new database and on one from before
    migrations existed (the baseline only adds what's missing)."""
    import logging

    from alembic import command
    from alembic.config import Config

    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with (bind or engine).connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK})
        try:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, target)
            conn.commit()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK})
            conn.commit()


def init_db() -> None:
    migrate()
    with engine.begin() as conn:
        # Leftovers from runs interrupted by a restart: a later run of the same generation would otherwise
        # duplicate them.
        conn.execute(text("DELETE FROM chunks c USING sites s WHERE c.site_id = s.id AND c.generation > s.generation"))
        conn.execute(text("DELETE FROM pages p USING sites s WHERE p.site_id = s.id AND p.generation > s.generation"))
        # Count the live index's pages from the pages table (progress counters may be left over from an interrupted run).
        conn.execute(
            text(
                "UPDATE sites s SET live_pages = (SELECT count(DISTINCT p.url) FROM pages p WHERE p.site_id = s.id "
                "AND p.generation = s.generation AND p.status = 'indexed') WHERE s.generation > 0"
            )
        )
        # Indexing that was waiting or running when the server stopped starts again (ingest.resume_interrupted). Its
        # half-built generation was removed above, so it starts clean; the live version keeps answering meanwhile.
        conn.execute(
            text("UPDATE sites SET status = 'queued', message = :m WHERE status IN ('queued', 'crawling', 'embedding')"),
            {"m": "Picking up again after a server restart…"},
        )
        # Test question runs live in memory while they run; one cut short by a restart won't finish.
        conn.execute(
            text("UPDATE eval_runs SET status = 'failed', message = :m, finished_at = now() WHERE status = 'running'"),
            {"m": "Stopped by a server restart. Run it again."},
        )
