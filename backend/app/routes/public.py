"""What websites call: the widget page, its public API (pk_ keys) and the server API (/api/v1, sk_ keys)."""

import itertools
import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import accounts
from ..auth import current_user
from ..chat import answer_stream
from ..db import SessionLocal, get_db
from ..embeds import (
    check_visitor,
    clean_origin,
    client_ip,
    effective_origin,
    ip_limiter,
    is_cross_site,
    is_test_origin,
    note_seen,
    origin_allowed,
    read_limiter,
    server_key_embed,
    server_limiter,
    style_of,
    visitor_limiter,
    widget_csp,
)
from ..models import Chat, Embed, Feedback, Lead, Message, Site, User, utcnow
from ..schemas import (
    LeadIn,
    ServerAsk,
    ServerFeedback,
    VisitorAsk,
    VisitorFeedback,
)
from ..suggest import for_page, get_suggestions
from .common import STATIC_DIR, app_link, messages_out, with_feedback

router = APIRouter()


# ---------- Website embeds: answering visitors (shared by the widget, sitebot-client.js and the server API) ----------

def visitor_chat(db: Session, e: Embed, visitor_id: str) -> Chat | None:
    return db.scalar(
        select(Chat).where(Chat.embed_id == e.id, Chat.visitor_id == visitor_id).order_by(Chat.id.desc()).limit(1)
    )


def ready_or_unavailable(e: Embed, site: Site) -> None:
    if e.status != "approved" or not e.enabled or site.generation == 0:
        raise HTTPException(404, "This chatbot isn't available right now.")


def visitor_events(owner_id: int, chat_id: int, embed_id: int, question: str) -> Iterator[str]:
    # The request-scoped session may close before streaming ends, so the stream owns its own session.
    sdb = SessionLocal()
    try:
        yield from answer_stream(sdb, sdb.get(User, owner_id), sdb.get(Chat, chat_id), question, embed=sdb.get(Embed, embed_id))
    finally:
        sdb.close()


def ndjson(events: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(
        events, media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


def save_feedback(db: Session, e: Embed, message: Message | None, rating: str, comment: str) -> dict:
    if not message or message.role != "assistant":
        raise HTTPException(404, "Answer not found")
    fb = db.scalar(select(Feedback).where(Feedback.message_id == message.id))
    if not fb:
        fb = Feedback(message_id=message.id, embed_id=e.id, rating=rating)
        db.add(fb)
    fb.rating, fb.comment = rating, comment.strip()
    db.commit()
    return {"ok": True}


# ---------- Website embeds: public API (pk_ key, locked to the bot's website) ----------

def optional_user(request: Request, db: Session) -> User | None:
    try:
        return current_user(request, db)
    except HTTPException:
        return None


def live_embed(db: Session, request: Request, key: str, origin: str, preview: bool) -> tuple[Embed, Site, User]:
    """The embed a widget or sitebot-client.js request is for, if it may answer.
    A preview is the owner (or an admin) trying it inside SiteBot."""
    e = db.scalar(select(Embed).where(Embed.key == key))
    site = db.get(Site, e.site_id) if e else None
    owner = db.get(User, e.owner_id) if e else None
    if not e or not site or not owner:
        raise HTTPException(404, "This chatbot isn't available.")
    if preview and not is_cross_site(request):
        viewer = optional_user(request, db)
        if not viewer or (viewer.id != owner.id and viewer.role != "admin"):
            raise HTTPException(403, "Sign in to SiteBot to preview this chatbot.")
        return e, site, owner
    ready_or_unavailable(e, site)
    if not origin_allowed(e, site, effective_origin(request, origin)):
        where = site.domain if e.restrict_to_domain else "secure (https) websites"
        raise HTTPException(403, f"This chatbot only works on {where}.")
    return e, site, owner


def limit_reads(request: Request) -> None:
    if not read_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many requests. Please wait a moment.")


def bot_info(db: Session, e: Embed, site: Site, owner: User) -> dict:
    return {
        "name": site.name, "domain": site.domain, "favicon": site.favicon,
        "greeting": e.greeting or f"Hi, welcome to {site.name}! Ask me anything about {site.name}.",
        "suggestions": get_suggestions(db, site, owner)[:4],
    }


@router.get("/api/public/{key}/config")
def widget_config(
    key: str, request: Request, origin: str = "", preview: bool = False, page: str = "", db: Session = Depends(get_db)
):
    limit_reads(request)
    e, site, owner = live_embed(db, request, key, origin, preview)
    # Every page load on a website asks for this, so it doubles as "Check installation". Previews don't count.
    # Test websites don't count either, so "installed" means the real website.
    seen_at = effective_origin(request, origin)
    if not (preview and not is_cross_site(request)) and not is_test_origin(e, seen_at):
        note_seen(db, e, seen_at)
    info = bot_info(db, e, site, owner)
    if page:
        # Page-aware suggestions: the questions closest to the page the visitor is reading come first.
        info["suggestions"] = for_page(db, site, get_suggestions(db, site, owner), page[:500])[:4]
    return {**info, "color": e.color, "position": e.position, "style": style_of(e)}


@router.get("/api/public/{key}/messages")
def widget_history(
    key: str, request: Request, visitor_id: str, origin: str = "", preview: bool = False, db: Session = Depends(get_db)
):
    limit_reads(request)
    check_visitor(visitor_id)
    e, _, _ = live_embed(db, request, key, origin, preview)
    chat = visitor_chat(db, e, visitor_id)
    return with_feedback(db, messages_out(db, chat.id)) if chat else []


@router.post("/api/public/{key}/messages")
def widget_ask(key: str, body: VisitorAsk, request: Request, db: Session = Depends(get_db)):
    check_visitor(body.visitor_id)
    e, site, owner = live_embed(db, request, key, body.origin, body.preview)
    if not visitor_limiter.allow(f"{e.id}:{body.visitor_id}") or not ip_limiter.allow(client_ip(request)):
        raise HTTPException(429, "You're sending messages quickly. Please wait a moment and try again.")
    chat = visitor_chat(db, e, body.visitor_id)
    if not chat:
        chat = Chat(user_id=None, site_id=site.id, embed_id=e.id, visitor_id=body.visitor_id)
        db.add(chat)
    # Where the visitor is chatting from, so owners can see which websites use their bot.
    testing = body.preview and not is_cross_site(request)
    chat.origin = "SiteBot preview" if testing else clean_origin(effective_origin(request, body.origin))
    # Chats from a test website are the owner trying it, so they're kept out of visitor numbers like previews.
    chat.is_test = chat.is_test or testing or is_test_origin(e, chat.origin)
    db.commit()
    return ndjson(visitor_events(owner.id, chat.id, e.id, body.content.strip()))


@router.post("/api/public/{key}/leads")
def widget_lead(key: str, body: LeadIn, request: Request, db: Session = Depends(get_db)):
    """A visitor leaves their email after a question the bot couldn't answer. The owner is emailed and sees it listed."""
    check_visitor(body.visitor_id)
    e, site, owner = live_embed(db, request, key, body.origin, False)
    email = body.email.strip()
    if not accounts.EMAIL_RE.match(email):
        raise HTTPException(400, "Please enter a valid email address.")
    if not visitor_limiter.allow(f"lead:{e.id}:{body.visitor_id}") or not ip_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Please wait a moment and try again.")
    chat = visitor_chat(db, e, body.visitor_id)
    question = ""
    if chat:
        msgs = db.scalars(select(Message).where(Message.chat_id == chat.id).order_by(Message.id.desc()).limit(10)).all()
        # The latest question the bot couldn't answer, or else the latest question.
        for i, m in enumerate(msgs):
            if m.role == "assistant" and not m.grounded and i + 1 < len(msgs) and msgs[i + 1].role == "user":
                question = msgs[i + 1].content
                break
        question = question or next((m.content for m in msgs if m.role == "user"), "")
    lead = Lead(embed_id=e.id, chat_id=chat.id if chat else None, email=email, name=body.name.strip(), message=body.message.strip(),
                question=question[:2000], origin=clean_origin(effective_origin(request, body.origin)))
    db.add(lead)
    db.commit()
    lines = [f"A visitor on {lead.origin or site.domain} asked {site.name} Chatbot something it couldn't answer, and left their details."]
    if question:
        lines.append(f"\nTheir question: {question}")
    lines.append(f"\nName: {lead.name or '(not given)'}\nEmail: {email}")
    if lead.message:
        lines.append(f"\nMessage: {lead.message}")
    lines.append("\nReply to them directly. The conversation is on the chatbot's page in SiteBot (Conversations and Leads).")
    accounts.notify([owner.email], f"SiteBot: a visitor wants to hear from you ({site.name})", "\n".join(lines) + app_link(f"#/website/{e.id}/leads"))
    return {"ok": True}


@router.post("/api/public/{key}/feedback")
def widget_feedback(key: str, body: VisitorFeedback, request: Request, db: Session = Depends(get_db)):
    limit_reads(request)
    check_visitor(body.visitor_id)
    e, _, _ = live_embed(db, request, key, body.origin, False)
    msg = db.get(Message, body.message_id)
    chat = db.get(Chat, msg.chat_id) if msg else None
    if not chat or chat.embed_id != e.id or chat.visitor_id != body.visitor_id:
        raise HTTPException(404, "Answer not found")
    return save_feedback(db, e, msg, body.rating, body.comment)


# ---------- Website embeds: server API (sk_ key, for customers who build their own UI on their backend) ----------

def server_embed(request: Request, db: Session) -> tuple[Embed, Site, User]:
    e = server_key_embed(db, request)
    site, owner = db.get(Site, e.site_id), db.get(User, e.owner_id)
    # "Last used", so owners can tell whether a key is in use before revoking it. Written at most once a minute.
    now = utcnow()
    if not e.secret_last_used_at or (now - e.secret_last_used_at).total_seconds() > 60:
        e.secret_last_used_at = now
        db.commit()
    ready_or_unavailable(e, site)
    if not server_limiter.allow(str(e.id)):
        raise HTTPException(429, "Too many requests for this chatbot. Please slow down.")
    return e, site, owner


def server_chat(db: Session, e: Embed, visitor_id: str, conversation_id: int) -> Chat:
    chat = db.get(Chat, conversation_id)
    if not chat or chat.embed_id != e.id or chat.visitor_id != visitor_id:
        raise HTTPException(404, "Conversation not found for this visitor_id.")
    return chat


@router.get("/api/v1/bot")
def server_bot(request: Request, db: Session = Depends(get_db)):
    e, site, owner = server_embed(request, db)
    return bot_info(db, e, site, owner)


@router.get("/api/v1/suggestions")
def server_suggestions(request: Request, db: Session = Depends(get_db)):
    e, site, owner = server_embed(request, db)
    return {"questions": get_suggestions(db, site, owner)}


@router.get("/api/v1/conversations")
def server_conversations(request: Request, visitor_id: str, db: Session = Depends(get_db)):
    e, _, _ = server_embed(request, db)
    chats = db.scalars(
        select(Chat).where(Chat.embed_id == e.id, Chat.visitor_id == visitor_id).order_by(Chat.updated_at.desc()).limit(100)
    ).all()
    return [{"conversation_id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat()} for c in chats]


@router.get("/api/v1/conversations/{conversation_id}/messages")
def server_messages(conversation_id: int, request: Request, visitor_id: str, db: Session = Depends(get_db)):
    e, _, _ = server_embed(request, db)
    return with_feedback(db, messages_out(db, server_chat(db, e, visitor_id, conversation_id).id))


@router.post("/api/v1/messages")
def server_ask(body: ServerAsk, request: Request, db: Session = Depends(get_db)):
    """Asks on behalf of one of the customer's users. Streams NDJSON events by default; `"stream": false` returns one JSON object."""
    e, site, owner = server_embed(request, db)
    if not visitor_limiter.allow(f"{e.id}:{body.visitor_id}"):
        raise HTTPException(429, "This visitor is sending messages quickly. Please wait a moment and try again.")
    if body.conversation_id:
        chat = server_chat(db, e, body.visitor_id, body.conversation_id)
    else:
        chat = None if body.new_conversation else visitor_chat(db, e, body.visitor_id)
        if not chat:
            chat = Chat(user_id=None, site_id=site.id, embed_id=e.id, visitor_id=body.visitor_id)
            db.add(chat)
            db.commit()
    events = visitor_events(owner.id, chat.id, e.id, body.content.strip())
    conversation = json.dumps({"type": "conversation", "conversation_id": chat.id}) + "\n"
    if body.stream:
        return ndjson(itertools.chain([conversation], events))

    answer, final = "", None
    for line in events:
        ev = json.loads(line)
        if ev["type"] == "token":
            answer += ev["text"]
        elif ev["type"] == "replace":
            answer = ev["text"]
        elif ev["type"] in ("done", "error"):
            final = ev
    if not final or final["type"] == "error":
        message = final["message"] if final else "Something went wrong while answering. Please try again."
        raise HTTPException(503, message)
    return {
        "conversation_id": chat.id, "message_id": final["message_id"], "answer": answer,
        "sources": final["sources"], "grounded": final["grounded"],
    }


@router.post("/api/v1/feedback")
def server_feedback(body: ServerFeedback, request: Request, db: Session = Depends(get_db)):
    e, _, _ = server_embed(request, db)
    msg = db.get(Message, body.message_id)
    chat = db.get(Chat, msg.chat_id) if msg else None
    if not chat or chat.embed_id != e.id:
        raise HTTPException(404, "Answer not found")
    return save_feedback(db, e, msg, body.rating, body.comment)


@router.get("/widget/{key}", include_in_schema=False)
def widget_page(key: str, db: Session = Depends(get_db)):
    """The chat window that embed.js opens in an iframe. Its CSP lets only the bot's own website show it."""
    e = db.scalar(select(Embed).where(Embed.key == key))
    site = db.get(Site, e.site_id) if e else None
    page = STATIC_DIR / "widget.html"
    headers = {"Content-Security-Policy": widget_csp(e, site), "Cache-Control": "no-cache"}
    if not page.exists():
        return Response("Frontend not built. Run `npm run build` in frontend/.", media_type="text/plain", headers=headers)
    return FileResponse(page, headers=headers)
