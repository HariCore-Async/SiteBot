from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from .config import settings
from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    picture: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(String(20), default="member")  # admin | member
    # Email/password accounts. Google-only users have no password and no username.
    username: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Proven by a Google sign-in or by entering the one-time code we emailed.
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    limit_usd: Mapped[float] = mapped_column(Float, default=settings.default_user_limit_usd)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccessGrant(Base):
    """An approved email. Approving a company email also opens access to its whole domain."""

    __tablename__ = "access_grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    created_by: Mapped[str] = mapped_column(String(320), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailCode(Base):
    """A one-time code emailed to prove the address exists. Only a hash of the code is stored."""

    __tablename__ = "email_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    # The sign-up details (name, username, password hash); the account is only created once the code is confirmed.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    root_url: Mapped[str] = mapped_column(Text)
    favicon: Mapped[str] = mapped_column(Text, default="")
    # queued | crawling | embedding | ready | failed
    status: Mapped[str] = mapped_column(String(20), default="queued")
    message: Mapped[str] = mapped_column(Text, default="")
    include_pdfs: Mapped[bool] = mapped_column(Boolean, default=False)
    # The user agreed to read the whole site (up to MAX_PAGES); otherwise indexing stops at LARGE_SITE_PAGES.
    full_crawl: Mapped[bool] = mapped_column(Boolean, default=False)
    # The last index stopped at the page limit with pages still unread.
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    # Pages in the live index. Unlike pages_indexed (a progress counter), this only changes when a new index swaps in.
    live_pages: Mapped[int] = mapped_column(Integer, default=0)
    # Generation that chat reads from; 0 means never indexed. A re-index builds generation+1, then swaps.
    generation: Mapped[int] = mapped_column(Integer, default=0)
    pages_found: Mapped[int] = mapped_column(Integer, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    pages_indexed: Mapped[int] = mapped_column(Integer, default=0)
    pages_login: Mapped[int] = mapped_column(Integer, default=0)
    pages_blocked: Mapped[int] = mapped_column(Integer, default=0)
    pages_failed: Mapped[int] = mapped_column(Integer, default=0)
    chunks_total: Mapped[int] = mapped_column(Integer, default=0)
    chunks_done: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Suggested starter questions, generated from the indexed pages on first request. None = not generated yet.
    suggestions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Admin's per-bot model choice (a providers "ref" such as "m:3"); None uses the default.
    answer_model: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fast_model: Mapped[str | None] = mapped_column(String(40), nullable=True)


# Chunks in this generation are the owner's own knowledge (answers they taught, documents they uploaded). Crawled pages
# start at generation 1, and re-indexing never touches generation 0, so this knowledge survives every update.
KNOWLEDGE_GENERATION = 0


class Knowledge(Base):
    """Something the bot's owner taught it: an answer to a question, or an uploaded document."""

    __tablename__ = "knowledge"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # answer | document
    title: Mapped[str] = mapped_column(Text, default="")  # the question, or the file name
    content: Mapped[str] = mapped_column(Text, default="")  # the answer, or the document's text
    filename: Mapped[str] = mapped_column(String(255), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    # indexed | login | blocked | failed | empty
    status: Mapped[str] = mapped_column(String(20))
    rendered: Mapped[bool] = mapped_column(Boolean, default=False)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    generation: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=True)
    tsv = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(title, '') || ' ' || content)", persisted=True),
    )

    __table_args__ = (
        Index("ix_chunks_site_gen", "site_id", "generation"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )


class HiddenSite(Base):
    """A bot the user removed from their own list. The shared index is untouched; adding it again un-hides it."""

    __tablename__ = "hidden_sites"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Embed(Base):
    """A bot placed on its own website with a script tag. Visitors chat anonymously; usage is charged to the owner."""

    __tablename__ = "embeds"
    __table_args__ = (UniqueConstraint("site_id", "owner_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Public: it appears in the website's HTML. The domain lock and limits are what protect it.
    key: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # pending | approved | rejected. Only approved embeds answer visitors.
    status: Mapped[str] = mapped_column(String(20), default="pending")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # On: only the bot's own domain (and subdomains) may use it. Only an admin can turn this off.
    restrict_to_domain: Mapped[bool] = mapped_column(Boolean, default=True)
    color: Mapped[str] = mapped_column(String(20), default="#2563eb")
    greeting: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[str] = mapped_column(String(10), default="right")  # right | left
    daily_cap_usd: Mapped[float] = mapped_column(Float, default=settings.embed_daily_cap_usd)
    # The rest of the widget's look (launcher, title, font, corner radius, theme, custom CSS); see schemas.EmbedStyle.
    style: Mapped[dict] = mapped_column(JSON, default=dict)
    # Server key for the headless API. Only its SHA-256 is kept; the key itself is shown to the owner once.
    secret_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    secret_hint: Mapped[str] = mapped_column(String(12), default="")
    secret_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    secret_last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(320), default="")
    # Shown to the owner when an admin rejects the request.
    review_note: Mapped[str] = mapped_column(Text, default="")
    # The last page load seen from a website (widget or sitebot-client.js), for "Check installation".
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_origin: Mapped[str] = mapped_column(String(300), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    # None for a website visitor's chat through an embed; those are found by (embed_id, visitor_id).
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    embed_id: Mapped[int | None] = mapped_column(ForeignKey("embeds.id", ondelete="CASCADE"), index=True, nullable=True)
    visitor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The website a visitor's chat happened on, so owners can see where their bot is used.
    origin: Mapped[str] = mapped_column(String(300), default="")
    # Chats from the owner's own preview or "Test it" page: labelled, and left out of visitor counts.
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    grounded: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Lead(Base):
    """A website visitor who left their email because the bot couldn't answer (human handoff)."""

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    embed_id: Mapped[int] = mapped_column(ForeignKey("embeds.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int | None] = mapped_column(ForeignKey("chats.id", ondelete="SET NULL"), nullable=True)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    question: Mapped[str] = mapped_column(Text, default="")  # what the bot couldn't answer
    origin: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIProvider(Base):
    """An AI service an admin connected (OpenAI, Anthropic, Gemini, Azure, Hugging Face, any OpenAI-compatible URL…)."""

    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30))  # see providers.KINDS
    base_url: Mapped[str] = mapped_column(Text, default="")
    # Encrypted with Fernet (providers.encrypt_key); never returned by the API.
    api_key_enc: Mapped[str] = mapped_column(Text, default="")
    api_version: Mapped[str] = mapped_column(String(40), default="")  # Azure only
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIModel(Base):
    """A model offered by a provider (for Azure, a deployment name), with prices for when the provider doesn't report cost."""

    __tablename__ = "ai_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("ai_providers.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(200), default="")
    input_per_m: Mapped[float] = mapped_column(Float, default=0.0)  # USD per 1M input tokens
    output_per_m: Mapped[float] = mapped_column(Float, default=0.0)  # USD per 1M output tokens
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Feedback(Base):
    """A website visitor's thumbs up or down on one answer, from the widget or the developer APIs."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), unique=True)
    embed_id: Mapped[int] = mapped_column(ForeignKey("embeds.id", ondelete="CASCADE"), index=True)
    rating: Mapped[str] = mapped_column(String(10))  # up | down
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageEvent(Base):
    """One OpenRouter call. Kept separately from messages so spend survives chat or bot deletion."""

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # answer | rewrite | verify
    # Set when a website visitor's question caused the call; user_id is then the embed's owner.
    embed_id: Mapped[int | None] = mapped_column(ForeignKey("embeds.id", ondelete="SET NULL"), index=True, nullable=True)
    model: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(100), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
