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


class EmbedUpdate(BaseModel):
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    greeting: str | None = Field(default=None, max_length=300)
    position: str | None = Field(default=None, pattern="^(right|left)$")
    enabled: bool | None = None


class EmbedReview(BaseModel):
    status: str | None = Field(default=None, pattern="^(approved|rejected|pending)$")
    daily_cap_usd: float | None = Field(default=None, ge=0, le=1000)


class VisitorAsk(BaseModel):
    visitor_id: str = Field(min_length=16, max_length=64)
    content: str = Field(min_length=1, max_length=1000)
    # The website the widget is on, as embed.js reported it. The CSP on the widget page is the real lock.
    origin: str = Field(default="", max_length=300)
    preview: bool = False


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
        "created_at": s.created_at.isoformat(),
    }


def user_out(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "username": u.username, "name": u.name, "picture": u.picture, "role": u.role,
        "limit_usd": u.limit_usd, "has_password": bool(u.password_hash),
    }
