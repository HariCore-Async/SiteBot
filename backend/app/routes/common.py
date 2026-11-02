"""Helpers shared by several route modules: who may see or change a chatbot, chat history shapes, the public widget's checks."""

from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Embed, EmbedMember, Feedback, HiddenSite, Message, User

# The built frontend: copied to /app/static in the Docker image, or frontend/dist when running from the repo.
STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
if not STATIC_DIR.exists():
    STATIC_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def unhide(db: Session, user: User, site_id: int) -> None:
    db.execute(delete(HiddenSite).where(HiddenSite.user_id == user.id, HiddenSite.site_id == site_id))


def messages_out(db: Session, chat_id: int) -> list[dict]:
    msgs = db.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.id)).all()
    return [
        {"id": m.id, "role": m.role, "content": m.content, "sources": m.sources or [], "grounded": m.grounded,
         "created_at": m.created_at.isoformat()}
        for m in msgs
    ]


ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}


def embed_role(db: Session, e: Embed, user: User) -> str | None:
    """owner, or the role a teammate was given (by email), or None."""
    if e.owner_id == user.id:
        return "owner"
    return db.scalar(select(EmbedMember.role).where(EmbedMember.embed_id == e.id, EmbedMember.email == user.email.lower()))


def app_link(path: str = "") -> str:
    """A link for notification emails, when APP_URL is set."""
    return f"\n\n{settings.app_url.rstrip('/')}/{path}" if settings.app_url else ""


def with_feedback(db: Session, msgs: list[dict]) -> list[dict]:
    ids = [m["id"] for m in msgs if m["role"] == "assistant"]
    rated = {f.message_id: f for f in db.scalars(select(Feedback).where(Feedback.message_id.in_(ids)))} if ids else {}
    return [
        {**m, "feedback": {"rating": rated[m["id"]].rating, "comment": rated[m["id"]].comment} if m["id"] in rated else None}
        for m in msgs
    ]
