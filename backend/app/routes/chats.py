"""The signed-in user's own chats with a bot."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..chat import answer_stream
from ..db import SessionLocal, get_db
from ..models import Chat, Message, Site, User, utcnow
from ..schemas import (
    Ask,
    NewChat,
)
from .common import messages_out, unhide

router = APIRouter()


# ---------- Chats ----------

def own_chat(db: Session, chat_id: int, user: User) -> Chat:
    chat = db.get(Chat, chat_id)
    if not chat or chat.user_id != user.id:
        raise HTTPException(404, "Chat not found")
    return chat


def chat_out(c: Chat) -> dict:
    return {"id": c.id, "site_id": c.site_id, "title": c.title, "updated_at": c.updated_at.isoformat()}


@router.get("/api/chats")
def list_chats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    chats = db.scalars(select(Chat).where(Chat.user_id == user.id).order_by(Chat.updated_at.desc())).all()
    return [chat_out(c) for c in chats]


@router.post("/api/chats")
def new_chat(body: NewChat, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = db.get(Site, body.site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    # Each user has one conversation per bot; reuse it if it exists.
    chat = db.scalar(
        select(Chat).where(Chat.user_id == user.id, Chat.site_id == site.id).order_by(Chat.updated_at.desc()).limit(1)
    )
    if not chat:
        chat = Chat(user_id=user.id, site_id=site.id)
        db.add(chat)
    unhide(db, user, site.id)
    db.commit()
    return chat_out(chat)


@router.post("/api/chats/{chat_id}/reset")
def reset_chat(chat_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Start fresh: clears the conversation (and with it the bot's memory of it)."""
    chat = own_chat(db, chat_id, user)
    db.execute(delete(Message).where(Message.chat_id == chat.id))
    chat.title = "New chat"
    chat.updated_at = utcnow()
    db.commit()
    return chat_out(chat)


@router.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(own_chat(db, chat_id, user))
    db.commit()
    return {"ok": True}


@router.get("/api/chats/{chat_id}/messages")
def chat_messages(chat_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    own_chat(db, chat_id, user)
    return messages_out(db, chat_id)


@router.post("/api/chats/{chat_id}/messages")
def ask(chat_id: int, body: Ask, user: User = Depends(current_user), db: Session = Depends(get_db)):
    own_chat(db, chat_id, user)
    user_id = user.id

    def gen():
        # The request-scoped session may close before streaming ends, so the stream owns its own session.
        sdb = SessionLocal()
        try:
            yield from answer_stream(sdb, sdb.get(User, user_id), sdb.get(Chat, chat_id), body.content.strip())
        finally:
            sdb.close()

    return StreamingResponse(
        gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
