"""Alembic environment: the app's own database URL and models. Migrations run at startup (see db.init_db) or with
`alembic upgrade head` from backend/."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db import Base
from app import models  # noqa: F401  (registers the tables)

config = context.config
target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Write pgvector columns as Vector(n) in generated migrations."""
    if type_ == "type" and obj.__class__.__module__.startswith("pgvector"):
        autogen_context.imports.add("from pgvector.sqlalchemy import Vector")
        return f"Vector({obj.dim})"
    return False


def run_migrations_offline() -> None:
    context.configure(url=settings.sqlalchemy_url, target_metadata=target_metadata, literal_binds=True, render_item=render_item)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # A connection passed in by db.init_db (inside its lock) is reused; otherwise connect from settings.
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, render_item=render_item)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = engine_from_config({"sqlalchemy.url": settings.sqlalchemy_url}, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_item=render_item)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
