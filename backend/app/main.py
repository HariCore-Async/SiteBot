import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import accounts, auth
from .auth import admin_user, current_user, email_domain, is_org_domain, login_user
from .chat import answer_stream
from .config import settings
from .crawler import Crawler, CrawlError, normalize_input_url
from .db import SessionLocal, get_db, init_db
from .embeddings import warm_up
from .embeds import (
    admin_embed_out, check_visitor, client_ip, embed_out, frame_ancestors, ip_limiter, new_key, origin_allowed, read_limiter,
    require_same_origin, visitor_limiter,
)
from .ingest import is_running, request_stop, start_ingestion
from .models import AccessGrant, Chat, Embed, HiddenSite, Message, Page, Site, UsageEvent, User, utcnow
from .suggest import get_suggestions
from .schemas import (
    AddSite, AdminSettingsIn, Ask, BudgetIn, ChangePassword, EmbedIn, EmbedReview, EmbedUpdate, ForgotPassword, ReindexIn, ResetPassword, SetUsername, GoogleLogin, GrantIn, NewChat, PasswordLogin, ResendCode, SignUp, UserUpdate,
    VerifyCode, VisitorAsk, site_out, user_out,
)
from .usage import global_budget, set_global_budget, usage_summary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    # Load the embedding model in the background so the first question isn't slow.
    threading.Thread(target=warm_up, daemon=True).start()
    yield


app = FastAPI(title="SiteBot", lifespan=lifespan)


# ---------- Auth ----------

@app.get("/api/config")
def public_config(db: Session = Depends(get_db)):
    return {
        "google_client_id": settings.google_client_id,
        "require_approval": auth.approval_required(db),
        "email_enabled": accounts.email_enabled(),
    }


@app.post("/api/auth/google")
def google_login(body: GoogleLogin, response: Response, db: Session = Depends(get_db)):
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    if not settings.google_client_id:
        raise HTTPException(500, "Google sign-in is not configured.")
    try:
        info = id_token.verify_oauth2_token(body.credential, google_requests.Request(), settings.google_client_id)
    except ValueError:
        raise HTTPException(401, "Google sign-in failed. Please try again.")
    if not info.get("email_verified"):
        raise HTTPException(401, "Your Google email is not verified.")
    user = login_user(db, response, info["email"], info.get("name", ""), info.get("picture", ""), email_verified=True)
    return user_out(user)


@app.post("/api/auth/signup")
def signup(body: SignUp, db: Session = Depends(get_db)):
    """Step 1 of creating an account: validate, then email a code. Nothing is saved until the code is confirmed."""
    accounts.require_email()
    email = body.email.strip().lower()
    username = body.username.strip()
    if not accounts.EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    if not accounts.USERNAME_RE.match(username):
        raise HTTPException(400, "Usernames are 3–30 characters: letters, numbers, dots and underscores.")
    accounts.validate_password(body.password)
    if body.password != body.confirm_password:
        raise HTTPException(400, "The passwords don't match.")
    if not auth.has_access(db, email):
        raise HTTPException(403, "This email hasn't been approved yet. Ask an admin for access, then create your account.")
    existing = db.scalar(select(User).where(User.email == email))
    if existing and existing.password_hash:
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    taken = accounts.find_account(db, username)
    if taken and taken.email != email:
        raise HTTPException(409, "That username is taken. Try another.")
    payload = {"name": body.name.strip(), "username": username, "password_hash": accounts.hash_password(body.password)}
    accounts.send_code(db, email, payload)
    return {"otp_required": True, "email": email}


@app.post("/api/auth/verify")
def verify_email(body: VerifyCode, response: Response, db: Session = Depends(get_db)):
    """Step 2: the emailed code proves the address exists. Creates the account and signs in."""
    email = body.email.strip().lower()
    payload = accounts.check_code(db, email, body.code)
    if not payload.get("password_hash"):
        raise HTTPException(400, "Please start again.")
    taken = accounts.find_account(db, payload["username"])
    if taken and taken.email != email:
        raise HTTPException(409, "That username was just taken. Please sign up again with another.")
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = User(email=email, name=payload["name"])
        db.add(user)
    user.username = payload["username"]
    user.password_hash = payload["password_hash"]
    db.commit()
    return user_out(login_user(db, response, email, payload["name"], email_verified=True))


@app.post("/api/auth/resend")
def resend_code(body: ResendCode, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    row = accounts.latest_code(db, email)
    if not row:
        raise HTTPException(400, "Please start again.")
    accounts.send_code(db, email, dict(row.payload or {}))
    return {"ok": True}


@app.post("/api/auth/login")
def password_login(body: PasswordLogin, response: Response, db: Session = Depends(get_db)):
    user = accounts.find_account(db, body.identifier)
    if user and not user.password_hash:
        raise HTTPException(
            401, "This account signs in with Google and has no password yet. Continue with Google, or use Forgot password to set one."
        )
    if not user or not accounts.check_password(body.password, user.password_hash):
        raise HTTPException(401, "That email/username and password don't match.")
    return user_out(login_user(db, response, user.email))


@app.post("/api/auth/forgot")
def forgot_password(body: ForgotPassword, db: Session = Depends(get_db)):
    """Emails a reset code. Always answers the same way, so it can't be used to check who has an account."""
    accounts.require_email()
    user = accounts.find_account(db, body.identifier)
    if user:
        accounts.send_code(db, user.email, {"purpose": "reset"})
    return {"ok": True}


@app.post("/api/auth/reset")
def reset_password(body: ResetPassword, response: Response, db: Session = Depends(get_db)):
    accounts.validate_password(body.password)
    if body.password != body.confirm_password:
        raise HTTPException(400, "The passwords don't match.")
    user = accounts.find_account(db, body.identifier)
    if not user:
        raise HTTPException(400, "That code isn't right. Check the email and try again.")
    payload = accounts.check_code(db, user.email, body.code)
    if payload.get("purpose") != "reset":
        raise HTTPException(400, "Please request a new code.")
    user.password_hash = accounts.hash_password(body.password)
    db.commit()
    return user_out(login_user(db, response, user.email, email_verified=True))


@app.post("/api/me/password")
def change_password(body: ChangePassword, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.password_hash and not accounts.check_password(body.current_password or "", user.password_hash):
        raise HTTPException(400, "Your current password isn't right.")
    accounts.validate_password(body.password)
    if body.password != body.confirm_password:
        raise HTTPException(400, "The passwords don't match.")
    user.password_hash = accounts.hash_password(body.password)
    db.commit()
    return user_out(user)


@app.post("/api/me/username")
def set_username(body: SetUsername, user: User = Depends(current_user), db: Session = Depends(get_db)):
    username = body.username.strip()
    if not accounts.USERNAME_RE.match(username):
        raise HTTPException(400, "Usernames are 3–30 characters: letters, numbers, dots and underscores.")
    taken = accounts.find_account(db, username)
    if taken and taken.id != user.id:
        raise HTTPException(409, "That username is taken. Try another.")
    user.username = username
    db.commit()
    return user_out(user)


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {**user_out(user), "usage": usage_summary(db, user)}


@app.get("/api/usage")
def my_usage(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return usage_summary(db, user)


# ---------- Sites (bots) ----------

@app.get("/api/sites")
def list_sites(user: User = Depends(current_user), db: Session = Depends(get_db)):
    sites = db.scalars(select(Site).order_by(Site.name)).all()
    hidden = set(db.scalars(select(HiddenSite.site_id).where(HiddenSite.user_id == user.id)))
    return [{**site_out(s), "hidden": s.id in hidden} for s in sites]


def unhide(db: Session, user: User, site_id: int) -> None:
    db.execute(delete(HiddenSite).where(HiddenSite.user_id == user.id, HiddenSite.site_id == site_id))


@app.post("/api/sites/{site_id}/remove")
def remove_from_my_list(site_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Removes a bot from the user's own list and deletes their conversation with it. Other users are unaffected."""
    if not db.get(Site, site_id):
        raise HTTPException(404, "Bot not found")
    db.execute(delete(Chat).where(Chat.user_id == user.id, Chat.site_id == site_id))
    if not db.get(HiddenSite, (user.id, site_id)):
        db.add(HiddenSite(user_id=user.id, site_id=site_id))
    db.commit()
    return {"ok": True}


@app.post("/api/sites")
def add_site(body: AddSite, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        domain, start_url = normalize_input_url(body.url)
    except CrawlError as e:
        raise HTTPException(400, str(e))

    site = db.scalar(select(Site).where(Site.domain == domain))
    if site:
        # Already in the library: reuse the index and put the bot in this user's list.
        unhide(db, user, site.id)
        if not db.scalar(select(Chat.id).where(Chat.user_id == user.id, Chat.site_id == site.id)):
            db.add(Chat(user_id=user.id, site_id=site.id))
        db.commit()
        # Same website, any page: reuse the index. Only a failed first attempt is retried.
        if site.status == "failed" and not is_running(site.id):
            site.root_url, site.include_pdfs, site.status = start_url, body.include_pdfs, "queued"
            db.commit()
            start_ingestion(site.id)
            return {"site": site_out(site), "existing": False}
        return {"site": site_out(site), "existing": True}

    if not body.confirm_large:
        pages, exact = Crawler(domain, start_url, body.include_pdfs, lambda r: None, lambda f, d: None).estimate()
        if pages > settings.large_site_pages:
            return {
                "needs_confirm": True,
                "domain": domain,
                "estimated_pages": pages,
                "exact": exact,
                "capped": pages >= settings.max_pages,
                "max_pages": settings.max_pages,
                # Rough: crawling ~4 pages/s plus local embedding.
                "estimated_minutes": max(1, round(pages / 150)),
            }

    label = domain.split(".")[-2] if "." in domain else domain
    site = Site(
        domain=domain, name=label.replace("-", " ").title(), root_url=start_url,
        include_pdfs=body.include_pdfs, created_by=user.id, message="Queued…", full_crawl=body.confirm_large,
    )
    db.add(site)
    try:
        db.commit()
    except IntegrityError:
        # Another user submitted the same site at the same moment.
        db.rollback()
        site = db.scalar(select(Site).where(Site.domain == domain))
        return {"site": site_out(site), "existing": True}
    start_ingestion(site.id)
    return {"site": site_out(site), "existing": False}


@app.get("/api/sites/{site_id}")
def get_site(site_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    return site_out(site)


@app.post("/api/sites/{site_id}/stop")
def stop_indexing(site_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Stops a running index. Only the person who added the bot, or an admin, can stop it (the index is shared)."""
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    if user.role != "admin" and site.created_by != user.id:
        raise HTTPException(403, "Only the person who added this chatbot, or an admin, can stop it.")
    if not is_running(site_id):
        raise HTTPException(409, "This chatbot isn't being indexed right now.")
    request_stop(site_id)
    site.message = "Stopping…"
    db.commit()
    return {"ok": True}


@app.post("/api/sites/{site_id}/read-all")
def read_whole_site(site_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Re-indexes a bot that stopped at the page limit, this time reading the whole site. The old index keeps working."""
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    if is_running(site_id):
        raise HTTPException(409, "This bot is already being indexed.")
    site.full_crawl = True
    site.status = "queued"
    site.message = "Reading the rest of the website in the background…"
    db.commit()
    start_ingestion(site_id)
    return site_out(site)


@app.get("/api/sites/{site_id}/suggestions")
def site_suggestions(site_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    return {"questions": get_suggestions(db, site, user)}


@app.get("/api/sites/{site_id}/pages")
def site_pages(site_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    gen = db.scalar(select(func.max(Page.generation)).where(Page.site_id == site_id)) or 0
    pages = db.scalars(select(Page).where(Page.site_id == site_id, Page.generation == gen).order_by(Page.id)).all()
    return [{"url": p.url, "title": p.title, "status": p.status, "rendered": p.rendered} for p in pages]


# ---------- Chats ----------

def own_chat(db: Session, chat_id: int, user: User) -> Chat:
    chat = db.get(Chat, chat_id)
    if not chat or chat.user_id != user.id:
        raise HTTPException(404, "Chat not found")
    return chat


def chat_out(c: Chat) -> dict:
    return {"id": c.id, "site_id": c.site_id, "title": c.title, "updated_at": c.updated_at.isoformat()}


@app.get("/api/chats")
def list_chats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    chats = db.scalars(select(Chat).where(Chat.user_id == user.id).order_by(Chat.updated_at.desc())).all()
    return [chat_out(c) for c in chats]


@app.post("/api/chats")
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


@app.post("/api/chats/{chat_id}/reset")
def reset_chat(chat_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Start fresh: clears the conversation (and with it the bot's memory of it)."""
    chat = own_chat(db, chat_id, user)
    db.execute(delete(Message).where(Message.chat_id == chat.id))
    chat.title = "New chat"
    chat.updated_at = utcnow()
    db.commit()
    return chat_out(chat)


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(own_chat(db, chat_id, user))
    db.commit()
    return {"ok": True}


def messages_out(db: Session, chat_id: int) -> list[dict]:
    msgs = db.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.id)).all()
    return [
        {"id": m.id, "role": m.role, "content": m.content, "sources": m.sources or [], "grounded": m.grounded,
         "created_at": m.created_at.isoformat()}
        for m in msgs
    ]


@app.get("/api/chats/{chat_id}/messages")
def chat_messages(chat_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    own_chat(db, chat_id, user)
    return messages_out(db, chat_id)


@app.post("/api/chats/{chat_id}/messages")
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


# ---------- Website embeds (owner) ----------

def own_embed(db: Session, embed_id: int, user: User) -> Embed:
    e = db.get(Embed, embed_id)
    if not e or e.owner_id != user.id:
        raise HTTPException(404, "Embed not found")
    return e


@app.get("/api/embeds")
def list_embeds(user: User = Depends(current_user), db: Session = Depends(get_db)):
    embeds = db.scalars(select(Embed).where(Embed.owner_id == user.id).order_by(Embed.created_at.desc())).all()
    return [embed_out(db, e, db.get(Site, e.site_id)) for e in embeds]


@app.post("/api/embeds")
def request_embed(body: EmbedIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Asks to put a bot on its own website. An admin approves it before the snippet works; admins' own are approved at once."""
    site = db.get(Site, body.site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    if site.created_by != user.id and user.role != "admin":
        raise HTTPException(403, "You can only add chatbots you created to a website.")
    if site.generation == 0:
        raise HTTPException(409, "This chatbot isn't ready yet. Wait for it to finish learning the website.")
    e = db.scalar(select(Embed).where(Embed.site_id == site.id, Embed.owner_id == user.id))
    if not e:
        e = Embed(key=new_key(), site_id=site.id, owner_id=user.id, status="pending")
        db.add(e)
    elif e.status == "rejected":
        e.status = "pending"
    if user.role == "admin" and e.status == "pending":
        e.status, e.reviewed_by, e.reviewed_at = "approved", user.email, utcnow()
    db.commit()
    return embed_out(db, e, site)


@app.patch("/api/embeds/{embed_id}")
def update_embed(embed_id: int, body: EmbedUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user)
    for field in ("color", "greeting", "position", "enabled"):
        value = getattr(body, field)
        if value is not None:
            setattr(e, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    return embed_out(db, e, db.get(Site, e.site_id))


@app.post("/api/embeds/{embed_id}/rotate-key")
def rotate_embed_key(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Issues a new key; the old snippet stops working straight away."""
    e = own_embed(db, embed_id, user)
    e.key = new_key()
    db.commit()
    return embed_out(db, e, db.get(Site, e.site_id))


@app.delete("/api/embeds/{embed_id}")
def delete_embed(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(own_embed(db, embed_id, user))
    db.commit()
    return {"ok": True}


@app.get("/api/embeds/{embed_id}/chats")
def embed_chats(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user)
    counts = (
        select(Message.chat_id, func.count(Message.id).label("n")).group_by(Message.chat_id).subquery()
    )
    rows = db.execute(
        select(Chat, counts.c.n).join(counts, counts.c.chat_id == Chat.id)
        .where(Chat.embed_id == e.id).order_by(Chat.updated_at.desc()).limit(200)
    ).all()
    return [
        {"id": c.id, "title": c.title, "visitor": (c.visitor_id or "")[:6], "messages": n, "updated_at": c.updated_at.isoformat()}
        for c, n in rows
    ]


@app.get("/api/embeds/{embed_id}/chats/{chat_id}/messages")
def embed_chat_messages(embed_id: int, chat_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user)
    chat = db.get(Chat, chat_id)
    if not chat or chat.embed_id != e.id:
        raise HTTPException(404, "Chat not found")
    return messages_out(db, chat_id)


# ---------- Website embeds (public, used by the widget) ----------

def optional_user(request: Request, db: Session) -> User | None:
    try:
        return current_user(request, db)
    except HTTPException:
        return None


def live_embed(db: Session, request: Request, key: str, origin: str, preview: bool) -> tuple[Embed, Site, User]:
    """The embed a widget request is for, if it may answer. A preview is the owner (or an admin) trying it inside SiteBot."""
    e = db.scalar(select(Embed).where(Embed.key == key))
    site = db.get(Site, e.site_id) if e else None
    owner = db.get(User, e.owner_id) if e else None
    if not e or not site or not owner:
        raise HTTPException(404, "This chatbot isn't available.")
    if preview:
        viewer = optional_user(request, db)
        if not viewer or (viewer.id != owner.id and viewer.role != "admin"):
            raise HTTPException(403, "Sign in to SiteBot to preview this chatbot.")
        return e, site, owner
    if e.status != "approved" or not e.enabled or site.generation == 0:
        raise HTTPException(404, "This chatbot isn't available right now.")
    if not origin_allowed(site, origin):
        raise HTTPException(403, f"This chatbot only works on {site.domain}.")
    return e, site, owner


def visitor_chat(db: Session, e: Embed, visitor_id: str) -> Chat | None:
    return db.scalar(
        select(Chat).where(Chat.embed_id == e.id, Chat.visitor_id == visitor_id).order_by(Chat.id.desc()).limit(1)
    )


def limit_reads(request: Request) -> None:
    require_same_origin(request)
    if not read_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many requests. Please wait a moment.")


@app.get("/api/public/{key}/config")
def widget_config(key: str, request: Request, origin: str = "", preview: bool = False, db: Session = Depends(get_db)):
    limit_reads(request)
    e, site, owner = live_embed(db, request, key, origin, preview)
    return {
        "name": site.name, "domain": site.domain, "favicon": site.favicon,
        "color": e.color, "position": e.position,
        "greeting": e.greeting or f"Hi, welcome to {site.name}! Ask me anything about {site.name}.",
        "suggestions": get_suggestions(db, site, owner)[:4],
    }


@app.get("/api/public/{key}/messages")
def widget_history(
    key: str, request: Request, visitor_id: str, origin: str = "", preview: bool = False, db: Session = Depends(get_db)
):
    limit_reads(request)
    check_visitor(visitor_id)
    e, _, _ = live_embed(db, request, key, origin, preview)
    chat = visitor_chat(db, e, visitor_id)
    return messages_out(db, chat.id) if chat else []


@app.post("/api/public/{key}/messages")
def widget_ask(key: str, body: VisitorAsk, request: Request, db: Session = Depends(get_db)):
    require_same_origin(request)
    check_visitor(body.visitor_id)
    e, site, owner = live_embed(db, request, key, body.origin, body.preview)
    if not visitor_limiter.allow(f"{e.id}:{body.visitor_id}") or not ip_limiter.allow(client_ip(request)):
        raise HTTPException(429, "You're sending messages quickly. Please wait a moment and try again.")
    chat = visitor_chat(db, e, body.visitor_id)
    if not chat:
        chat = Chat(user_id=None, site_id=site.id, embed_id=e.id, visitor_id=body.visitor_id)
        db.add(chat)
        db.commit()
    owner_id, chat_id, embed_id, question = owner.id, chat.id, e.id, body.content.strip()

    def gen():
        sdb = SessionLocal()
        try:
            yield from answer_stream(sdb, sdb.get(User, owner_id), sdb.get(Chat, chat_id), question, embed=sdb.get(Embed, embed_id))
        finally:
            sdb.close()

    return StreamingResponse(
        gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ---------- Admin ----------

@app.get("/api/admin/users")
def admin_users(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    spent = dict(db.execute(select(UsageEvent.user_id, func.sum(UsageEvent.cost_usd)).group_by(UsageEvent.user_id)).all())
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return [
        {**user_out(u), "spent_usd": round(float(spent.get(u.id) or 0), 6),
         "locked_admin": u.email in settings.admin_email_set, "last_seen_at": u.last_seen_at.isoformat()}
        for u in users
    ]


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, body: UserUpdate, me: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if body.limit_usd is not None:
        u.limit_usd = body.limit_usd
    if body.role is not None:
        if body.role == "member" and u.email in settings.admin_email_set:
            raise HTTPException(400, "This is a permanent admin and can't be demoted.")
        u.role = body.role
    db.commit()
    return user_out(u)


@app.get("/api/admin/access")
def admin_access(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    # Admins from ADMIN_EMAILS are listed once, as admins, even if they were also granted access by email.
    grants = [
        g for g in db.scalars(select(AccessGrant).order_by(AccessGrant.created_at.desc()))
        if g.email.lower() not in settings.admin_email_set
    ]
    return {
        "grants": [
            {"id": g.id, "email": g.email, "created_by": g.created_by, "created_at": g.created_at.isoformat(),
             "domain_access": email_domain(g.email) if is_org_domain(email_domain(g.email)) else None}
            for g in grants
        ],
        "admin_emails": sorted(settings.admin_email_set),
    }


@app.post("/api/admin/access")
def admin_grant(body: GrantIn, me: User = Depends(admin_user), db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Enter a valid email address.")
    if email in settings.admin_email_set:
        raise HTTPException(400, "That email is already an admin, so it already has access.")
    if not db.scalar(select(AccessGrant).where(AccessGrant.email == email)):
        db.add(AccessGrant(email=email, created_by=me.email))
        db.commit()
    return {"ok": True}


@app.delete("/api/admin/access/{grant_id}")
def admin_revoke(grant_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    db.execute(delete(AccessGrant).where(AccessGrant.id == grant_id))
    db.commit()
    return {"ok": True}


@app.get("/api/admin/settings")
def admin_get_settings(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return {"require_approval": auth.approval_required(db)}


@app.put("/api/admin/settings")
def admin_set_settings(body: AdminSettingsIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    auth.set_approval_required(db, body.require_approval)
    return {"require_approval": body.require_approval}


@app.get("/api/admin/budget")
def admin_get_budget(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return {"global_budget_usd": global_budget(db)}


@app.put("/api/admin/budget")
def admin_set_budget(body: BudgetIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    set_global_budget(db, body.global_budget_usd)
    return {"global_budget_usd": body.global_budget_usd}


@app.get("/api/admin/embeds")
def admin_embeds(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    embeds = db.scalars(select(Embed).order_by(Embed.created_at.desc())).all()
    order = {"pending": 0, "approved": 1, "rejected": 2}
    embeds = sorted(embeds, key=lambda e: order.get(e.status, 3))
    return [admin_embed_out(db, e, db.get(Site, e.site_id), db.get(User, e.owner_id)) for e in embeds]


@app.patch("/api/admin/embeds/{embed_id}")
def admin_review_embed(embed_id: int, body: EmbedReview, me: User = Depends(admin_user), db: Session = Depends(get_db)):
    e = db.get(Embed, embed_id)
    if not e:
        raise HTTPException(404, "Embed not found")
    if body.status is not None and body.status != e.status:
        e.status, e.reviewed_by, e.reviewed_at = body.status, me.email, utcnow()
    if body.daily_cap_usd is not None:
        e.daily_cap_usd = body.daily_cap_usd
    db.commit()
    return admin_embed_out(db, e, db.get(Site, e.site_id), db.get(User, e.owner_id))


@app.post("/api/admin/sites/{site_id}/reindex")
def admin_reindex(
    site_id: int, body: ReindexIn | None = None, _: User = Depends(admin_user), db: Session = Depends(get_db)
):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    if is_running(site_id):
        raise HTTPException(409, "This bot is already being indexed.")
    if body and body.include_pdfs is not None:
        site.include_pdfs = body.include_pdfs
    site.status = "queued"
    site.message = "Updating in the background…"
    db.commit()
    start_ingestion(site_id)
    return site_out(site)


@app.delete("/api/admin/sites/{site_id}")
def admin_delete_site(site_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    if is_running(site_id):
        raise HTTPException(409, "Wait for indexing to finish before deleting this bot.")
    db.delete(site)
    db.commit()
    return {"ok": True}


# ---------- Frontend ----------

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if not STATIC_DIR.exists():
    STATIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@app.get("/widget/{key}", include_in_schema=False)
def widget_page(key: str, db: Session = Depends(get_db)):
    """The chat window that embed.js opens in an iframe. Its CSP lets only the bot's own website show it."""
    e = db.scalar(select(Embed).where(Embed.key == key))
    site = db.get(Site, e.site_id) if e else None
    page = STATIC_DIR / "widget.html"
    if not page.exists():
        return Response("Frontend not built. Run `npm run build` in frontend/.", media_type="text/plain")
    csp = frame_ancestors(site) if site else "frame-ancestors 'self'"
    return FileResponse(page, headers={"Content-Security-Policy": csp, "Cache-Control": "no-cache"})


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    target = (STATIC_DIR / path).resolve()
    if path and target.is_file() and STATIC_DIR.resolve() in target.parents:
        return FileResponse(target)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return Response("Frontend not built. Run `npm run build` in frontend/.", media_type="text/plain")
