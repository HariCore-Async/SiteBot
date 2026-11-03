"""Migrations: the schema they build matches the models, and a database from before migrations upgrades in place."""

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db import Base, engine, migrate
from app import models  # noqa: F401

from conftest import TEST_DB


def test_migrations_build_exactly_the_models():
    """Changing app/models.py without a migration fails here: run `alembic revision --autogenerate -m "..."`."""
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        version = conn.scalar(sa.text("SELECT version_num FROM alembic_version"))
    assert diff == [], diff
    assert version


def test_database_from_before_migrations_is_upgraded_in_place():
    url = sa.engine.make_url(TEST_DB)
    admin = sa.create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    name = f"{url.database}_legacy"
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    legacy = sa.create_engine(url.set(database=name))
    try:
        # Built the old way (create_all at startup), missing some columns that were added later, with data in it.
        with legacy.begin() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(legacy)
        with legacy.begin() as conn:
            conn.execute(sa.text("ALTER TABLE users DROP COLUMN token_version"))
            conn.execute(sa.text("ALTER TABLE embeds DROP COLUMN test_origins"))
            conn.execute(sa.text("INSERT INTO users (email, name, picture, role, email_verified, limit_usd, created_at, last_seen_at) "
                                 "VALUES ('old@test.example', 'Old', '', 'admin', true, 1, now(), now())"))
        migrate(legacy)
        migrate(legacy)  # running again is a no-op
        with legacy.connect() as conn:
            assert conn.scalar(sa.text("SELECT token_version FROM users WHERE email = 'old@test.example'")) == 0
            assert conn.scalar(sa.text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'embeds' AND column_name = 'test_origins'")) == 1
            assert conn.scalar(sa.text("SELECT version_num FROM alembic_version"))
            assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    finally:
        legacy.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()
