"""Baseline: the schema as it was when migrations were introduced.

On a new database it creates everything. On a database from before migrations (built at startup by the old init_db),
every table and index already exists, so it only adds columns such a database might still lack, then Alembic records
this revision. Later schema changes go in their own revisions.

Revision ID: 0001
Revises:
Create Date: 2026-11-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from app.config import settings

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_COLUMNS = [
    "ALTER TABLE sites ADD COLUMN IF NOT EXISTS suggestions JSON",
    "ALTER TABLE sites ADD COLUMN IF NOT EXISTS full_crawl BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE sites ADD COLUMN IF NOT EXISTS truncated BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE sites ADD COLUMN IF NOT EXISTS live_pages INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(40) UNIQUE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE chats ALTER COLUMN user_id DROP NOT NULL",
    "ALTER TABLE chats ADD COLUMN IF NOT EXISTS embed_id INTEGER REFERENCES embeds(id) ON DELETE CASCADE",
    "ALTER TABLE chats ADD COLUMN IF NOT EXISTS visitor_id VARCHAR(64)",
    "CREATE INDEX IF NOT EXISTS ix_chats_embed_id ON chats (embed_id)",
    "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS embed_id INTEGER REFERENCES embeds(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_usage_events_embed_id ON usage_events (embed_id)",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS style JSON",
    # Added without NOT NULL back then; empty means the default style, which is what {} gives too.
    "UPDATE embeds SET style = '{}' WHERE style IS NULL",
    "ALTER TABLE embeds ALTER COLUMN style SET NOT NULL",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS secret_hash VARCHAR(64) UNIQUE",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS secret_hint VARCHAR(12) NOT NULL DEFAULT ''",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS secret_created_at TIMESTAMPTZ",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS restrict_to_domain BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE chats ADD COLUMN IF NOT EXISTS origin VARCHAR(300) NOT NULL DEFAULT ''",
    "ALTER TABLE chats ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS review_note TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS secret_last_used_at TIMESTAMPTZ",
    "ALTER TABLE sites ADD COLUMN IF NOT EXISTS answer_model VARCHAR(40)",
    "ALTER TABLE sites ADD COLUMN IF NOT EXISTS reindex_schedule VARCHAR(10) NOT NULL DEFAULT 'off'",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS weekly_report BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS last_report_at TIMESTAMPTZ",
    "ALTER TABLE sites ADD COLUMN IF NOT EXISTS fast_model VARCHAR(40)",
    "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS provider VARCHAR(100) NOT NULL DEFAULT ''",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS last_seen_origin VARCHAR(300) NOT NULL DEFAULT ''",
    "ALTER TABLE sites ADD COLUMN IF NOT EXISTS resumes INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS verify_token VARCHAR(64) NOT NULL DEFAULT ''",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS verified_via VARCHAR(10) NOT NULL DEFAULT ''",
    "ALTER TABLE embeds ADD COLUMN IF NOT EXISTS test_origins JSON",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('access_grants',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('created_by', sa.String(length=320), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    if_not_exists=True)
    op.create_table('ai_failures',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=100), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('status', sa.Integer(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_index(op.f('ix_ai_failures_created_at'), 'ai_failures', ['created_at'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_ai_failures_provider'), 'ai_failures', ['provider'], unique=False, if_not_exists=True)
    op.create_table('ai_providers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('base_url', sa.Text(), nullable=False),
    sa.Column('api_key_enc', sa.Text(), nullable=False),
    sa.Column('api_version', sa.String(length=40), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key'),
    if_not_exists=True)
    op.create_table('email_codes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('code_hash', sa.String(length=128), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_index(op.f('ix_email_codes_email'), 'email_codes', ['email'], unique=False, if_not_exists=True)
    op.create_table('plans',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('price_usd_month', sa.Float(), nullable=False),
    sa.Column('credit_usd_month', sa.Float(), nullable=False),
    sa.Column('max_bots', sa.Integer(), nullable=False),
    sa.Column('max_embeds', sa.Integer(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_table('provider_alerts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=100), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('failures', sa.Integer(), nullable=False),
    sa.Column('first_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('emailed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_index(op.f('ix_provider_alerts_provider'), 'provider_alerts', ['provider'], unique=False, if_not_exists=True)
    op.create_table('ai_models',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider_id', sa.Integer(), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('input_per_m', sa.Float(), nullable=False),
    sa.Column('output_per_m', sa.Float(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['provider_id'], ['ai_providers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_index(op.f('ix_ai_models_provider_id'), 'ai_models', ['provider_id'], unique=False, if_not_exists=True)
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('picture', sa.Text(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('username', sa.String(length=40), nullable=True),
    sa.Column('password_hash', sa.Text(), nullable=True),
    sa.Column('email_verified', sa.Boolean(), nullable=False),
    sa.Column('limit_usd', sa.Float(), nullable=False),
    sa.Column('plan_id', sa.Integer(), nullable=True),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username'),
    if_not_exists=True)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True, if_not_exists=True)
    op.create_table('sites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('domain', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('root_url', sa.Text(), nullable=False),
    sa.Column('favicon', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('include_pdfs', sa.Boolean(), nullable=False),
    sa.Column('full_crawl', sa.Boolean(), nullable=False),
    sa.Column('truncated', sa.Boolean(), nullable=False),
    sa.Column('live_pages', sa.Integer(), nullable=False),
    sa.Column('generation', sa.Integer(), nullable=False),
    sa.Column('pages_found', sa.Integer(), nullable=False),
    sa.Column('pages_done', sa.Integer(), nullable=False),
    sa.Column('pages_indexed', sa.Integer(), nullable=False),
    sa.Column('pages_login', sa.Integer(), nullable=False),
    sa.Column('pages_blocked', sa.Integer(), nullable=False),
    sa.Column('pages_failed', sa.Integer(), nullable=False),
    sa.Column('chunks_total', sa.Integer(), nullable=False),
    sa.Column('chunks_done', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('suggestions', sa.JSON(), nullable=True),
    sa.Column('resumes', sa.Integer(), nullable=False),
    sa.Column('reindex_schedule', sa.String(length=10), nullable=False),
    sa.Column('answer_model', sa.String(length=40), nullable=True),
    sa.Column('fast_model', sa.String(length=40), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_index(op.f('ix_sites_domain'), 'sites', ['domain'], unique=True, if_not_exists=True)
    op.create_table('chunks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('generation', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', Vector(settings.embedding_dim), nullable=True),
    sa.Column('tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('english', coalesce(title, '') || ' ' || content)", persisted=True), nullable=True),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_index('ix_chunks_site_gen', 'chunks', ['site_id', 'generation'], unique=False, if_not_exists=True)
    op.create_index('ix_chunks_tsv', 'chunks', ['tsv'], unique=False, postgresql_using='gin', if_not_exists=True)
    op.create_table('embeds',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=48), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('restrict_to_domain', sa.Boolean(), nullable=False),
    sa.Column('test_origins', sa.JSON(), nullable=True),
    sa.Column('color', sa.String(length=20), nullable=False),
    sa.Column('greeting', sa.Text(), nullable=False),
    sa.Column('position', sa.String(length=10), nullable=False),
    sa.Column('daily_cap_usd', sa.Float(), nullable=False),
    sa.Column('style', sa.JSON(), nullable=False),
    sa.Column('secret_hash', sa.String(length=64), nullable=True),
    sa.Column('secret_hint', sa.String(length=12), nullable=False),
    sa.Column('secret_created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('secret_last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reviewed_by', sa.String(length=320), nullable=False),
    sa.Column('verify_token', sa.String(length=64), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('verified_via', sa.String(length=10), nullable=False),
    sa.Column('weekly_report', sa.Boolean(), nullable=False),
    sa.Column('last_report_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_note', sa.Text(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_seen_origin', sa.String(length=300), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('secret_hash'),
    sa.UniqueConstraint('site_id', 'owner_id'),
    if_not_exists=True)
    op.create_index(op.f('ix_embeds_key'), 'embeds', ['key'], unique=True, if_not_exists=True)
    op.create_index(op.f('ix_embeds_owner_id'), 'embeds', ['owner_id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_embeds_site_id'), 'embeds', ['site_id'], unique=False, if_not_exists=True)
    op.create_table('hidden_sites',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'site_id'),
    if_not_exists=True)
    op.create_table('knowledge',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('chunks', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_index(op.f('ix_knowledge_site_id'), 'knowledge', ['site_id'], unique=False, if_not_exists=True)
    op.create_table('pages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('generation', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('rendered', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_index(op.f('ix_pages_site_id'), 'pages', ['site_id'], unique=False, if_not_exists=True)
    op.create_table('chats',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('embed_id', sa.Integer(), nullable=True),
    sa.Column('visitor_id', sa.String(length=64), nullable=True),
    sa.Column('origin', sa.String(length=300), nullable=False),
    sa.Column('is_test', sa.Boolean(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['embed_id'], ['embeds.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_index(op.f('ix_chats_embed_id'), 'chats', ['embed_id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_chats_site_id'), 'chats', ['site_id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_chats_user_id'), 'chats', ['user_id'], unique=False, if_not_exists=True)
    op.create_table('embed_members',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('embed_id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('invited_by', sa.String(length=320), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['embed_id'], ['embeds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('embed_id', 'email'),
    if_not_exists=True)
    op.create_index(op.f('ix_embed_members_email'), 'embed_members', ['email'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_embed_members_embed_id'), 'embed_members', ['embed_id'], unique=False, if_not_exists=True)
    op.create_table('usage_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('embed_id', sa.Integer(), nullable=True),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('provider', sa.String(length=100), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['embed_id'], ['embeds.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_index(op.f('ix_usage_events_embed_id'), 'usage_events', ['embed_id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_usage_events_user_id'), 'usage_events', ['user_id'], unique=False, if_not_exists=True)
    op.create_table('leads',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('embed_id', sa.Integer(), nullable=False),
    sa.Column('chat_id', sa.Integer(), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('origin', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['embed_id'], ['embeds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_index(op.f('ix_leads_embed_id'), 'leads', ['embed_id'], unique=False, if_not_exists=True)
    op.create_table('messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('chat_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('sources', sa.JSON(), nullable=False),
    sa.Column('grounded', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True)
    op.create_index(op.f('ix_messages_chat_id'), 'messages', ['chat_id'], unique=False, if_not_exists=True)
    op.create_table('feedback',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=False),
    sa.Column('embed_id', sa.Integer(), nullable=False),
    sa.Column('rating', sa.String(length=10), nullable=False),
    sa.Column('comment', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['embed_id'], ['embeds.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('message_id'),
    if_not_exists=True)
    op.create_index(op.f('ix_feedback_embed_id'), 'feedback', ['embed_id'], unique=False, if_not_exists=True)

    # Databases created before migrations existed were built table by table at startup, with columns added later by
    # these statements. They bring any such database up to this baseline; on a new one they change nothing.
    for statement in LEGACY_COLUMNS:
        op.execute(statement)
    # Older versions could leave duplicate chunks and pages inside the live index; remove them once.
    op.execute(
        "DELETE FROM chunks a USING chunks b WHERE a.id > b.id AND a.site_id = b.site_id "
        "AND a.generation = b.generation AND a.url = b.url AND a.content = b.content"
    )
    op.execute(
        "DELETE FROM pages a USING pages b WHERE a.id > b.id AND a.site_id = b.site_id "
        "AND a.generation = b.generation AND a.url = b.url"
    )
    op.execute("UPDATE chats SET is_test = true WHERE origin = 'SiteBot preview' AND NOT is_test")


def downgrade() -> None:
    # Undoing the baseline would drop every table. Restore a backup instead.
    raise NotImplementedError("The baseline migration can't be undone.")
