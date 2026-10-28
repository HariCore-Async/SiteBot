from pydantic import BaseModel, Field

from .models import Site, User
from .ingest import is_running


class GoogleLogin(BaseModel):
    credential: str


class SignUp(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    username: str = Field(min_length=3, max_length=30)
    password: str = Field(min_length=1, max_length=200)
    confirm_password: str = Field(min_length=1, max_length=200)


class VerifyCode(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(min_length=6, max_length=6)


class ResendCode(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordLogin(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class ForgotPassword(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)


class ResetPassword(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    code: str = Field(min_length=6, max_length=6)
    password: str = Field(min_length=1, max_length=200)
    confirm_password: str = Field(min_length=1, max_length=200)


class ChangePassword(BaseModel):
    current_password: str | None = Field(default=None, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    confirm_password: str = Field(min_length=1, max_length=200)


class SetUsername(BaseModel):
    username: str = Field(min_length=3, max_length=30)


class AddSite(BaseModel):
    url: str = Field(min_length=3, max_length=2000)
    include_pdfs: bool = False
    # Set after the user has seen the large-site warning and chosen to go ahead.
    confirm_large: bool = False


class NewChat(BaseModel):
    site_id: int


class Ask(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class UserUpdate(BaseModel):
    limit_usd: float | None = Field(default=None, ge=0, le=10000)
    role: str | None = Field(default=None, pattern="^(admin|member)$")


class GrantIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ReindexIn(BaseModel):
    # None keeps the bot's current setting.
    include_pdfs: bool | None = None


class AdminSettingsIn(BaseModel):
    require_approval: bool


class BudgetIn(BaseModel):
    global_budget_usd: float = Field(ge=0, le=100000)


class EmbedIn(BaseModel):
    site_id: int


class EmbedStyle(BaseModel):
    launcher_icon: str = Field(default="chat", pattern="^(chat|help|sparkle|none)$")  # none: label only
    launcher_label: str = Field(default="", max_length=30)
    title: str = Field(default="", max_length=60)  # empty: the bot's name
    font: str = Field(default="system", pattern="^(system|sans|serif|rounded|mono)$")
    radius: int = Field(default=16, ge=0, le=28)
    theme: str = Field(default="light", pattern="^(light|dark|auto)$")
    custom_css: str = Field(default="", max_length=5000)
    # Pop the greeting up next to the bubble after this many seconds (0: don't); shown once per visit.
    proactive_seconds: int = Field(default=0, ge=0, le=120)
    proactive_text: str = Field(default="", max_length=200)  # empty: the greeting


class EmbedUpdate(BaseModel):
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    greeting: str | None = Field(default=None, max_length=300)
    position: str | None = Field(default=None, pattern="^(right|left)$")
    enabled: bool | None = None
    style: EmbedStyle | None = None
    restrict_to_domain: bool | None = None  # admins only
    weekly_report: bool | None = None


class EmbedReview(BaseModel):
    status: str | None = Field(default=None, pattern="^(approved|rejected|pending)$")
    daily_cap_usd: float | None = Field(default=None, ge=0, le=1000)
    restrict_to_domain: bool | None = None
    note: str | None = Field(default=None, max_length=500)  # rejection reason, shown to the owner


class VisitorAsk(BaseModel):
    visitor_id: str = Field(min_length=16, max_length=64)
    content: str = Field(min_length=1, max_length=1000)
    # The website the widget is on, as embed.js reported it. The CSP on the widget page is the real lock.
    origin: str = Field(default="", max_length=300)
    preview: bool = False


class VisitorFeedback(BaseModel):
    visitor_id: str = Field(min_length=16, max_length=64)
    message_id: int
    rating: str = Field(pattern="^(up|down)$")
    comment: str = Field(default="", max_length=1000)
    origin: str = Field(default="", max_length=300)


class ServerAsk(BaseModel):
    """Headless API: a question from the customer's server on behalf of one of their users."""

    visitor_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:@-]+$")
    content: str = Field(min_length=1, max_length=1000)
    # Continue this conversation; without it, the visitor's latest one continues (or a new one starts).
    conversation_id: int | None = None
    new_conversation: bool = False
    stream: bool = True


class ServerFeedback(BaseModel):
    message_id: int
    rating: str = Field(pattern="^(up|down)$")
    comment: str = Field(default="", max_length=1000)


class AnswerIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=5000)


class DocumentIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    # The file's bytes, base64-encoded (10 MB at most once decoded).
    data_b64: str = Field(min_length=1, max_length=14_500_000)


class LeadIn(BaseModel):
    visitor_id: str = Field(min_length=16, max_length=64)
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(default="", max_length=200)
    message: str = Field(default="", max_length=2000)
    origin: str = Field(default="", max_length=300)


class MemberIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = Field(default="viewer", pattern="^(viewer|editor)$")


class MemberUpdate(BaseModel):
    role: str = Field(pattern="^(viewer|editor)$")


class ScheduleIn(BaseModel):
    reindex_schedule: str = Field(pattern="^(off|daily|weekly)$")


class LeadUpdate(BaseModel):
    status: str = Field(pattern="^(open|done)$")


MODEL_REF = r"^(env:answer|env:fast|m:\d+)$"


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern="^(openrouter|openai|anthropic|gemini|azure|huggingface|openai_compatible)$")
    base_url: str = Field(default="", max_length=500)
    api_key: str = Field(default="", max_length=2000)
    api_version: str = Field(default="", max_length=40)


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=2000)  # replaces the saved key; "" removes it
    api_version: str | None = Field(default=None, max_length=40)
    enabled: bool | None = None


class ModelIn(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    label: str = Field(default="", max_length=200)
    input_per_m: float = Field(default=0, ge=0, le=10000)
    output_per_m: float = Field(default=0, ge=0, le=10000)


class ModelUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    input_per_m: float | None = Field(default=None, ge=0, le=10000)
    output_per_m: float | None = Field(default=None, ge=0, le=10000)
    enabled: bool | None = None


class AIDefaults(BaseModel):
    answer: str = Field(pattern=MODEL_REF)
    fast: str = Field(pattern=MODEL_REF)
    fallbacks: list[str] = Field(default_factory=list, max_length=10)


class AITest(BaseModel):
    ref: str = Field(pattern=MODEL_REF)


class SiteModels(BaseModel):
    # None (or "") means "use the default".
    answer_model: str | None = Field(default=None, pattern=r"^(|env:answer|env:fast|m:\d+)$")
    fast_model: str | None = Field(default=None, pattern=r"^(|env:answer|env:fast|m:\d+)$")


def site_out(s: Site) -> dict:
    return {
        "id": s.id,
        "domain": s.domain,
        "name": s.name,
        "root_url": s.root_url,
        "favicon": s.favicon,
        "status": s.status,
        "running": is_running(s.id),
        "message": s.message,
        "include_pdfs": s.include_pdfs,
        "full_crawl": s.full_crawl,
        "truncated": s.truncated,
        "live_pages": s.live_pages,
        "created_by": s.created_by,
        "ready": s.generation > 0,
        "pages_found": s.pages_found,
        "pages_done": s.pages_done,
        "pages_indexed": s.pages_indexed,
        "pages_login": s.pages_login,
        "pages_blocked": s.pages_blocked,
        "pages_failed": s.pages_failed,
        "chunks_total": s.chunks_total,
        "chunks_done": s.chunks_done,
        "indexed_at": s.indexed_at.isoformat() if s.indexed_at else None,
        "answer_model": s.answer_model,
        "reindex_schedule": s.reindex_schedule,
        "fast_model": s.fast_model,
        "created_at": s.created_at.isoformat(),
    }


def user_out(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "username": u.username, "name": u.name, "picture": u.picture, "role": u.role,
        "limit_usd": u.limit_usd, "has_password": bool(u.password_hash),
    }
