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


class DevLogin(BaseModel):
    email: str


class AddSite(BaseModel):
    url: str = Field(min_length=3, max_length=2000)
    include_pdfs: bool = False


class NewChat(BaseModel):
    site_id: int


class Ask(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class UserUpdate(BaseModel):
    limit_usd: float | None = Field(default=None, ge=0, le=10000)
    role: str | None = Field(default=None, pattern="^(admin|member)$")


class GrantIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class BudgetIn(BaseModel):
    global_budget_usd: float = Field(ge=0, le=100000)


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
        "limit_usd": u.limit_usd,
    }
