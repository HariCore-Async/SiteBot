import csv
import io
import itertools
import json
import logging
import re
import threading
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import accounts, auth, knowledge, llm, providers, scheduler
from .auth import admin_user, current_user, email_domain, is_org_domain, login_user
from .chat import answer_stream
from .config import settings
from .crawler import Crawler, CrawlError, normalize_input_url
from .db import SessionLocal, get_db, init_db
from .embeddings import warm_up
from .embeds import (
    admin_embed_out, check_visitor, clean_origin, client_ip, effective_origin, embed_out, hash_secret, ip_limiter, is_cross_site,
    insights, new_key, new_secret, note_seen, origin_allowed, read_limiter, sanitize_css, server_key_embed, server_limiter, style_of, visitor_limiter, widget_csp,
)
from .ingest import is_running, request_stop, start_ingestion
from .models import AccessGrant, AIModel, AIProvider, Chat, Embed, EmbedMember, Feedback, Knowledge, Lead, HiddenSite, Message, Page, Site, UsageEvent, User, utcnow
from .knowledge import knowledge_out
from .providers import encrypt_key, provider_out
from .suggest import for_page, get_suggestions
from .schemas import (
    AddSite, AdminSettingsIn, AIDefaults, AITest, AnswerIn, Ask, DocumentIn, LeadIn, LeadUpdate, MemberIn, MemberUpdate, ScheduleIn, ModelIn, ModelUpdate, ProviderIn, ProviderUpdate, SiteModels, BudgetIn, ChangePassword, EmbedIn, EmbedReview, EmbedUpdate, ForgotPassword, ReindexIn, ResetPassword, SetUsername, GoogleLogin, GrantIn, NewChat, PasswordLogin, ResendCode, SignUp, UserUpdate,
    ServerAsk, ServerFeedback, VerifyCode, VisitorAsk, VisitorFeedback, site_out, user_out,
)
from .xlsx import to_xlsx
from .usage import global_budget, set_global_budget, usage_summary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if settings.sentry_dsn:
    try:
        import sentry_sdk

        # Errors only, and no visitor data: no request bodies, cookies or IPs.
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.sentry_environment, send_default_pii=False, traces_sample_rate=0)
    except ImportError:
        logging.getLogger(__name__).warning("SENTRY_DSN is set but sentry-sdk isn't installed; error monitoring is off.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    # Load the embedding model in the background so the first question isn't slow.
    threading.Thread(target=warm_up, daemon=True).start()
    scheduler.start()
    yield


app = FastAPI(title="SiteBot", lifespan=lifespan)


@app.middleware("http")
async def public_api_cors(request: Request, call_next):
    """sitebot-client.js calls the public API straight from a customer's website. Any origin may read the replies
    (no cookies are involved); each route checks that origin against the bot's own domain."""
    origin = request.headers.get("origin")
    if not origin or not request.url.path.startswith("/api/public/"):
        return await call_next(request)
    if request.method == "OPTIONS":
        response = Response(status_code=204)
        response.headers["Access-Control-Allow-Methods"] = "GET, POST"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "600"
    else:
        response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return response


# ---------- Auth ----------

@app.get("/api/config")
def public_config(db: Session = Depends(get_db)):
    return {
        "google_client_id": settings.google_client_id,
        "require_approval": auth.approval_required(db),
        "email_enabled": accounts.email_enabled(),
        "sentry": {"dsn": settings.sentry_browser_dsn, "environment": settings.sentry_environment} if settings.sentry_browser_dsn else None,
    }


@app.post("/api/auth/google")
def google_login(body: GoogleLogin, response: Response, db: Session = Depends(get_db)):
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    if not settings.google_client_id:
        raise HTTPException(500, "Google sign-in is not configured.")
    try:
        # Allow a few seconds of clock difference: a PC whose clock runs slightly behind Google's otherwise rejects
        # every fresh token as "used too early".
        info = id_token.verify_oauth2_token(
            body.credential, google_requests.Request(), settings.google_client_id, clock_skew_in_seconds=10
        )
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

ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}


def embed_role(db: Session, e: Embed, user: User) -> str | None:
    """owner, or the role a teammate was given (by email), or None."""
    if e.owner_id == user.id:
        return "owner"
    return db.scalar(select(EmbedMember.role).where(EmbedMember.embed_id == e.id, EmbedMember.email == user.email.lower()))


def own_embed(db: Session, embed_id: int, user: User, need: str = "owner") -> Embed:
    """The embed, if this user may do what `need` says: "viewer" reads, "editor" changes design, knowledge and leads,
    "owner" handles keys, the team and removal."""
    e = db.get(Embed, embed_id)
    role = embed_role(db, e, user) if e else None
    if not role:
        raise HTTPException(404, "Embed not found")
    if ROLE_RANK[role] < ROLE_RANK[need]:
        raise HTTPException(403, "Your role on this chatbot can't do that. Ask its owner.")
    return e


def embed_view(db: Session, e: Embed, user: User) -> dict:
    return {**embed_out(db, e, db.get(Site, e.site_id)), "my_role": embed_role(db, e, user)}


@app.get("/api/embeds")
def list_embeds(user: User = Depends(current_user), db: Session = Depends(get_db)):
    shared = select(EmbedMember.embed_id).where(EmbedMember.email == user.email.lower())
    embeds = db.scalars(
        select(Embed).where((Embed.owner_id == user.id) | Embed.id.in_(shared)).order_by(Embed.created_at.desc())
    ).all()
    return [embed_view(db, e, user) for e in embeds]


# ---------- Website embeds: the team ----------

def member_out(m: EmbedMember, db: Session) -> dict:
    u = db.scalar(select(User).where(User.email == m.email))
    return {"id": m.id, "email": m.email, "role": m.role, "name": u.name if u else "", "joined": bool(u),
            "invited_by": m.invited_by, "created_at": m.created_at.isoformat()}


@app.get("/api/embeds/{embed_id}/team")
def embed_team(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "viewer")
    owner = db.get(User, e.owner_id)
    members = db.scalars(select(EmbedMember).where(EmbedMember.embed_id == e.id).order_by(EmbedMember.created_at)).all()
    return {"owner": {"name": owner.name, "email": owner.email}, "members": [member_out(m, db) for m in members]}


@app.post("/api/embeds/{embed_id}/team")
def invite_member(embed_id: int, body: MemberIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "owner")
    email = body.email.strip().lower()
    if not accounts.EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    if email == db.get(User, e.owner_id).email.lower():
        raise HTTPException(400, "That's the owner.")
    m = db.scalar(select(EmbedMember).where(EmbedMember.embed_id == e.id, EmbedMember.email == email))
    new = m is None
    if new:
        if db.scalar(select(func.count(EmbedMember.id)).where(EmbedMember.embed_id == e.id)) >= 50:
            raise HTTPException(400, "A chatbot can have up to 50 teammates.")
        m = EmbedMember(embed_id=e.id, email=email, invited_by=user.email)
        db.add(m)
    m.role = body.role
    db.commit()
    if new:
        site = db.get(Site, e.site_id)
        accounts.notify(
            [email],
            f"SiteBot: {user.name or user.email} added you to {site.name} Chatbot",
            f"{user.name} ({user.email}) gave you {body.role} access to {site.name} Chatbot on SiteBot. Sign in with this email "
            "address and open Add a chatbot to your website to find it." + app_link(f"#/website/{e.id}"),
        )
    return member_out(m, db)


@app.patch("/api/embeds/{embed_id}/team/{member_id}")
def change_member(embed_id: int, member_id: int, body: MemberUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "owner")
    m = db.get(EmbedMember, member_id)
    if not m or m.embed_id != e.id:
        raise HTTPException(404, "Not found")
    m.role = body.role
    db.commit()
    return member_out(m, db)


@app.delete("/api/embeds/{embed_id}/team/{member_id}")
def remove_member(embed_id: int, member_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The owner removes a teammate, or a teammate leaves."""
    e = own_embed(db, embed_id, user, "viewer")
    m = db.get(EmbedMember, member_id)
    if not m or m.embed_id != e.id:
        raise HTTPException(404, "Not found")
    if embed_role(db, e, user) != "owner" and m.email != user.email.lower():
        raise HTTPException(403, "Only the owner can remove teammates.")
    db.delete(m)
    db.commit()
    return {"ok": True}


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
        e.status, e.review_note = "pending", ""
    if user.role == "admin" and e.status == "pending":
        e.status, e.reviewed_by, e.reviewed_at = "approved", user.email, utcnow()
    db.commit()
    if e.status == "pending":
        admins = [*settings.admin_email_set, *db.scalars(select(User.email).where(User.role == "admin"))]
        accounts.notify(
            admins,
            f"SiteBot: {user.name or user.email} wants to add {site.name} Chatbot to a website",
            f"{user.name} ({user.email}) asked to put {site.name} Chatbot on {site.domain}.\n\n"
            f"Approve or reject it in SiteBot: Admin console > Embeds.{app_link('#/website')}",
        )
    return embed_view(db, e, user)


def app_link(path: str = "") -> str:
    """A link for notification emails, when APP_URL is set."""
    return f"\n\n{settings.app_url.rstrip('/')}/{path}" if settings.app_url else ""


@app.patch("/api/embeds/{embed_id}")
def update_embed(embed_id: int, body: EmbedUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "editor")
    if body.restrict_to_domain is not None:
        # Lifting the domain lock lets any website spend the owner's credits, so it's an admin's call.
        if user.role != "admin":
            raise HTTPException(403, "Only an admin can change which websites may use this chatbot.")
        e.restrict_to_domain = body.restrict_to_domain
    for field in ("color", "greeting", "position", "enabled", "weekly_report"):
        value = getattr(body, field)
        if value is not None:
            setattr(e, field, value.strip() if isinstance(value, str) else value)
    if body.style is not None:
        style = body.style.model_dump()
        style["launcher_label"], style["title"] = style["launcher_label"].strip(), style["title"].strip()
        style["custom_css"] = sanitize_css(style["custom_css"])
        if style["launcher_icon"] == "none" and not style["launcher_label"]:
            style["launcher_icon"] = "chat"
        e.style = style
    db.commit()
    return embed_view(db, e, user)


@app.post("/api/embeds/{embed_id}/rotate-key")
def rotate_embed_key(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Issues a new key; the old snippet stops working straight away."""
    e = own_embed(db, embed_id, user)
    e.key = new_key()
    db.commit()
    return embed_view(db, e, user)


@app.post("/api/embeds/{embed_id}/server-key")
def make_server_key(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Creates (or replaces) the secret key for the headless API. The key is returned this once and never again."""
    e = own_embed(db, embed_id, user)
    secret = new_secret()
    e.secret_hash, e.secret_hint, e.secret_created_at, e.secret_last_used_at = hash_secret(secret), secret[-4:], utcnow(), None
    db.commit()
    return {**embed_view(db, e, user), "secret": secret}


@app.delete("/api/embeds/{embed_id}/server-key")
def revoke_server_key(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user)
    e.secret_hash, e.secret_hint, e.secret_created_at, e.secret_last_used_at = None, "", None, None
    db.commit()
    return embed_view(db, e, user)


@app.delete("/api/embeds/{embed_id}")
def delete_embed(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(own_embed(db, embed_id, user))
    db.commit()
    return {"ok": True}


@app.get("/api/embeds/{embed_id}/chats")
def embed_chats(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "viewer")
    return [
        {"id": c.id, "title": c.title, "visitor": (c.visitor_id or "")[:6], "origin": c.origin, "is_test": c.is_test,
         "messages": n, "unanswered": missed, "updated_at": c.updated_at.isoformat()}
        for c, n, missed in embed_chat_rows(db, e)
    ]


def embed_chat_rows(db: Session, e: Embed, limit: int = 500, since=None, until=None, unanswered_only=False, include_tests=True):
    """(chat, messages, answers it couldn't give) for an embed's conversations, newest first."""
    counts = (
        select(
            Message.chat_id,
            func.count(Message.id).label("n"),
            func.count(Message.id).filter(Message.role == "assistant", Message.grounded.is_(False)).label("missed"),
        )
        .group_by(Message.chat_id)
        .subquery()
    )
    q = select(Chat, counts.c.n, counts.c.missed).join(counts, counts.c.chat_id == Chat.id).where(Chat.embed_id == e.id)
    if since:
        q = q.where(Chat.updated_at >= since)
    if until:
        q = q.where(Chat.updated_at < until)
    if unanswered_only:
        q = q.where(counts.c.missed > 0)
    if not include_tests:
        q = q.where(Chat.is_test.is_(False))
    return db.execute(q.order_by(Chat.updated_at.desc()).limit(limit)).all()


@app.get("/api/embeds/{embed_id}/insights")
def embed_insights(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return insights(db, own_embed(db, embed_id, user, "viewer"))


@app.get("/api/embeds/{embed_id}/export")
def export_conversations(
    embed_id: int, format: str = "csv", start: str = "", end: str = "", unanswered: bool = False, tests: bool = False,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    """Every message of the matching conversations, one row each, as CSV or Excel. Dates are YYYY-MM-DD, end inclusive."""
    e = own_embed(db, embed_id, user, "viewer")
    try:
        since = datetime.fromisoformat(start).replace(tzinfo=timezone.utc) if start else None
        until = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) + timedelta(days=1) if end else None
    except ValueError:
        raise HTTPException(400, "Dates must look like 2026-10-28.")
    if format not in ("csv", "xlsx"):
        raise HTTPException(400, "Format must be csv or xlsx.")
    chats = embed_chat_rows(db, e, limit=5000, since=since, until=until, unanswered_only=unanswered, include_tests=tests)
    header = ["Conversation", "Visitor", "Website", "Test chat", "Time (UTC)", "From", "Message", "Answered from the website", "Sources", "Rating", "Rating comment"]
    rows = [header]
    for chat, _, _ in chats:
        for m in with_feedback(db, messages_out(db, chat.id)):
            fb = m.get("feedback") or {}
            rows.append([
                chat.id, (chat.visitor_id or "")[:6], chat.origin, "yes" if chat.is_test else "", m["created_at"][:19].replace("T", " "),
                "Visitor" if m["role"] == "user" else "Bot", m["content"],
                "" if m["role"] == "user" else ("yes" if m["grounded"] else "no"),
                " ".join(s["url"] for s in m["sources"]), fb.get("rating", ""), fb.get("comment", ""),
            ])
    site = db.get(Site, e.site_id)
    name = f"{re.sub(r'[^A-Za-z0-9]+', '-', site.name).strip('-').lower() or 'chatbot'}-conversations"
    if format == "xlsx":
        return Response(
            to_xlsx(rows, "Conversations"),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
        )
    buf = io.StringIO()
    # Visitors write these messages: stop spreadsheet apps from running text that starts like a formula.
    csv.writer(buf).writerows([[f"'{v}" if isinstance(v, str) and v[:1] in "=+-@" else v for v in row] for row in rows])
    # A byte-order mark so Excel opens non-English text correctly.
    return Response(
        "﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )


def with_feedback(db: Session, msgs: list[dict]) -> list[dict]:
    ids = [m["id"] for m in msgs if m["role"] == "assistant"]
    rated = {f.message_id: f for f in db.scalars(select(Feedback).where(Feedback.message_id.in_(ids)))} if ids else {}
    return [
        {**m, "feedback": {"rating": rated[m["id"]].rating, "comment": rated[m["id"]].comment} if m["id"] in rated else None}
        for m in msgs
    ]


@app.get("/api/embeds/{embed_id}/chats/{chat_id}/messages")
def embed_chat_messages(embed_id: int, chat_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "viewer")
    chat = db.get(Chat, chat_id)
    if not chat or chat.embed_id != e.id:
        raise HTTPException(404, "Chat not found")
    return with_feedback(db, messages_out(db, chat_id))


# ---------- Teaching a bot: the owner's own answers and documents ----------

def own_site(db: Session, site_id: int, user: User, need: str = "editor") -> Site:
    """A bot this user may teach (or, with need="viewer", see what it was taught): its creator, an admin, or a teammate
    on one of its website embeds with at least that role. Bots are shared, so this isn't everyone who chats with it."""
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    if site.created_by == user.id or user.role == "admin":
        return site
    for e in db.scalars(select(Embed).where(Embed.site_id == site.id)):
        role = embed_role(db, e, user)
        if role and ROLE_RANK[role] >= ROLE_RANK[need]:
            return site
    raise HTTPException(403, "Only the person who added this chatbot, its editors, or an admin can teach it.")


def own_knowledge(db: Session, site: Site, knowledge_id: int) -> Knowledge:
    k = db.get(Knowledge, knowledge_id)
    if not k or k.site_id != site.id:
        raise HTTPException(404, "Not found")
    return k


@app.get("/api/sites/{site_id}/knowledge")
def list_knowledge(site_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = own_site(db, site_id, user, "viewer")
    items = db.scalars(select(Knowledge).where(Knowledge.site_id == site.id).order_by(Knowledge.updated_at.desc())).all()
    return [knowledge_out(k) for k in items]


@app.patch("/api/sites/{site_id}/schedule")
def set_schedule(site_id: int, body: ScheduleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Re-read the website off / daily / weekly. Only changed content is re-embedded, so updates are cheap."""
    site = own_site(db, site_id, user)
    site.reindex_schedule = body.reindex_schedule
    db.commit()
    return site_out(site)


@app.post("/api/sites/{site_id}/knowledge/answers")
def add_answer(site_id: int, body: AnswerIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = own_site(db, site_id, user)
    return knowledge_out(knowledge.save_answer(db, site, body.question, body.answer, user.id))


@app.patch("/api/sites/{site_id}/knowledge/{knowledge_id}")
def edit_answer(site_id: int, knowledge_id: int, body: AnswerIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = own_site(db, site_id, user)
    k = own_knowledge(db, site, knowledge_id)
    if k.kind != "answer":
        raise HTTPException(400, "Documents can't be edited; remove it and upload the new version.")
    return knowledge_out(knowledge.save_answer(db, site, body.question, body.answer, user.id, k))


@app.post("/api/sites/{site_id}/knowledge/documents")
def add_document(site_id: int, body: DocumentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = own_site(db, site_id, user)
    return knowledge_out(knowledge.save_document(db, site, body.filename, body.data_b64, user.id))


@app.delete("/api/sites/{site_id}/knowledge/{knowledge_id}")
def delete_knowledge(site_id: int, knowledge_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = own_site(db, site_id, user)
    knowledge.remove(db, site, own_knowledge(db, site, knowledge_id))
    return {"ok": True}


# ---------- Human handoff: visitors who leave their email ----------

def lead_out(lead: Lead) -> dict:
    return {
        "id": lead.id, "email": lead.email, "name": lead.name, "message": lead.message, "question": lead.question,
        "origin": lead.origin, "status": lead.status, "chat_id": lead.chat_id, "created_at": lead.created_at.isoformat(),
    }


@app.get("/api/embeds/{embed_id}/leads")
def embed_leads(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "viewer")
    return [lead_out(x) for x in db.scalars(select(Lead).where(Lead.embed_id == e.id).order_by(Lead.created_at.desc()).limit(500))]


@app.patch("/api/embeds/{embed_id}/leads/{lead_id}")
def update_lead(embed_id: int, lead_id: int, body: LeadUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "editor")
    lead = db.get(Lead, lead_id)
    if not lead or lead.embed_id != e.id:
        raise HTTPException(404, "Not found")
    lead.status = body.status
    db.commit()
    return lead_out(lead)


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


@app.get("/api/public/{key}/config")
def widget_config(
    key: str, request: Request, origin: str = "", preview: bool = False, page: str = "", db: Session = Depends(get_db)
):
    limit_reads(request)
    e, site, owner = live_embed(db, request, key, origin, preview)
    # Every page load on a website asks for this, so it doubles as "Check installation". Previews don't count.
    if not (preview and not is_cross_site(request)):
        note_seen(db, e, effective_origin(request, origin))
    info = bot_info(db, e, site, owner)
    if page:
        # Page-aware suggestions: the questions closest to the page the visitor is reading come first.
        info["suggestions"] = for_page(db, site, get_suggestions(db, site, owner), page[:500])[:4]
    return {**info, "color": e.color, "position": e.position, "style": style_of(e)}


@app.get("/api/public/{key}/messages")
def widget_history(
    key: str, request: Request, visitor_id: str, origin: str = "", preview: bool = False, db: Session = Depends(get_db)
):
    limit_reads(request)
    check_visitor(visitor_id)
    e, _, _ = live_embed(db, request, key, origin, preview)
    chat = visitor_chat(db, e, visitor_id)
    return with_feedback(db, messages_out(db, chat.id)) if chat else []


@app.post("/api/public/{key}/messages")
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
    chat.is_test = chat.is_test or testing
    db.commit()
    return ndjson(visitor_events(owner.id, chat.id, e.id, body.content.strip()))


@app.post("/api/public/{key}/leads")
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


@app.post("/api/public/{key}/feedback")
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


@app.get("/api/v1/bot")
def server_bot(request: Request, db: Session = Depends(get_db)):
    e, site, owner = server_embed(request, db)
    return bot_info(db, e, site, owner)


@app.get("/api/v1/suggestions")
def server_suggestions(request: Request, db: Session = Depends(get_db)):
    e, site, owner = server_embed(request, db)
    return {"questions": get_suggestions(db, site, owner)}


@app.get("/api/v1/conversations")
def server_conversations(request: Request, visitor_id: str, db: Session = Depends(get_db)):
    e, _, _ = server_embed(request, db)
    chats = db.scalars(
        select(Chat).where(Chat.embed_id == e.id, Chat.visitor_id == visitor_id).order_by(Chat.updated_at.desc()).limit(100)
    ).all()
    return [{"conversation_id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat()} for c in chats]


@app.get("/api/v1/conversations/{conversation_id}/messages")
def server_messages(conversation_id: int, request: Request, visitor_id: str, db: Session = Depends(get_db)):
    e, _, _ = server_embed(request, db)
    return with_feedback(db, messages_out(db, server_chat(db, e, visitor_id, conversation_id).id))


@app.post("/api/v1/messages")
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


@app.post("/api/v1/feedback")
def server_feedback(body: ServerFeedback, request: Request, db: Session = Depends(get_db)):
    e, _, _ = server_embed(request, db)
    msg = db.get(Message, body.message_id)
    chat = db.get(Chat, msg.chat_id) if msg else None
    if not chat or chat.embed_id != e.id:
        raise HTTPException(404, "Answer not found")
    return save_feedback(db, e, msg, body.rating, body.comment)


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
    decided = body.status is not None and body.status != e.status
    if decided:
        e.status, e.reviewed_by, e.reviewed_at = body.status, me.email, utcnow()
        e.review_note = (body.note or "").strip() if body.status == "rejected" else ""
    if body.daily_cap_usd is not None:
        e.daily_cap_usd = body.daily_cap_usd
    if body.restrict_to_domain is not None:
        e.restrict_to_domain = body.restrict_to_domain
    db.commit()
    site, owner = db.get(Site, e.site_id), db.get(User, e.owner_id)
    if decided and e.status in ("approved", "rejected") and owner.id != me.id:
        if e.status == "approved":
            subject = f"SiteBot: {site.name} Chatbot is approved for your website"
            text = (
                f"Good news: {site.name} Chatbot is approved, so it now answers visitors on {site.domain}.\n\n"
                "If you haven't yet, paste its snippet into your website: Add a chatbot to your website > Install."
            )
        else:
            subject = f"SiteBot: {site.name} Chatbot wasn't approved"
            text = f"An admin didn't approve putting {site.name} Chatbot on {site.domain}."
            text += f"\n\nReason: {e.review_note}" if e.review_note else ""
            text += "\n\nYou can change things and ask again from the chatbot's page."
        accounts.notify([owner.email], subject, text + app_link(f"#/website/{e.id}"))
    return admin_embed_out(db, e, site, owner)


# ---------- Admin: AI providers and models ----------

def ai_overview(db: Session) -> dict:
    providers_list = db.scalars(select(AIProvider).order_by(AIProvider.created_at)).all()
    models = db.scalars(select(AIModel).order_by(AIModel.id)).all()
    return {
        "providers": [provider_out(p, [m for m in models if m.provider_id == p.id]) for p in providers_list],
        "env": {"available": providers.env_available(), "models": providers.env_models()},
        "defaults": providers.defaults(db),
        "kinds": [{"kind": k, **v} for k, v in providers.KINDS.items()],
    }


def check_base_url(kind: str, base_url: str) -> str:
    base_url = base_url.strip().rstrip("/")
    if base_url and not re.match(r"^https?://[^\s]+$", base_url):
        raise HTTPException(400, "The base URL must start with http:// or https://.")
    if kind in ("azure", "openai_compatible") and not base_url:
        raise HTTPException(400, "This kind of provider needs its base URL.")
    return base_url


@app.get("/api/admin/ai")
def admin_ai(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return ai_overview(db)


@app.post("/api/admin/ai/providers")
def admin_add_provider(body: ProviderIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    p = AIProvider(name=body.name.strip(), kind=body.kind, base_url=check_base_url(body.kind, body.base_url),
                   api_key_enc=encrypt_key(body.api_key.strip()), api_version=body.api_version.strip(), enabled=True)
    db.add(p)
    db.commit()
    return ai_overview(db)


@app.patch("/api/admin/ai/providers/{provider_id}")
def admin_update_provider(provider_id: int, body: ProviderUpdate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    p = db.get(AIProvider, provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    if body.name is not None:
        p.name = body.name.strip()
    if body.base_url is not None:
        p.base_url = check_base_url(p.kind, body.base_url)
    if body.api_key is not None:
        p.api_key_enc = encrypt_key(body.api_key.strip())
    if body.api_version is not None:
        p.api_version = body.api_version.strip()
    if body.enabled is not None:
        p.enabled = body.enabled
    db.commit()
    return ai_overview(db)


@app.delete("/api/admin/ai/providers/{provider_id}")
def admin_delete_provider(provider_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    p = db.get(AIProvider, provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    refs = [f"m:{m.id}" for m in db.scalars(select(AIModel).where(AIModel.provider_id == p.id))]
    db.delete(p)
    db.commit()
    for ref in refs:
        providers.clear_references(db, ref)
    return ai_overview(db)


@app.post("/api/admin/ai/providers/{provider_id}/models")
def admin_add_model(provider_id: int, body: ModelIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if not db.get(AIProvider, provider_id):
        raise HTTPException(404, "Provider not found")
    db.add(AIModel(provider_id=provider_id, model=body.model.strip(), label=body.label.strip(),
                   input_per_m=body.input_per_m, output_per_m=body.output_per_m, enabled=True))
    db.commit()
    return ai_overview(db)


@app.patch("/api/admin/ai/models/{model_id}")
def admin_update_model(model_id: int, body: ModelUpdate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    m = db.get(AIModel, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    for field in ("label", "input_per_m", "output_per_m", "enabled"):
        value = getattr(body, field)
        if value is not None:
            setattr(m, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    return ai_overview(db)


@app.delete("/api/admin/ai/models/{model_id}")
def admin_delete_model(model_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    m = db.get(AIModel, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    db.delete(m)
    db.commit()
    providers.clear_references(db, f"m:{model_id}")
    return ai_overview(db)


@app.put("/api/admin/ai/defaults")
def admin_ai_defaults(body: AIDefaults, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    for ref in [body.answer, body.fast, *body.fallbacks]:
        if not providers.target_for(db, ref):
            raise HTTPException(400, f"{ref} isn't usable: it's missing, turned off, or its provider has no API key.")
    providers.set_defaults(db, body.answer, body.fast, body.fallbacks)
    return ai_overview(db)


@app.post("/api/admin/ai/test")
def admin_ai_test(body: AITest, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Sends a tiny prompt to one model (no fallback) and reports whether it answered."""
    t = providers.target_for(db, body.ref)
    if not t:
        return {"ok": False, "error": "This model isn't usable: it's turned off, or its provider has no API key."}
    started = time.monotonic()
    try:
        text, usage = llm.complete_with(t, [{"role": "user", "content": "Reply with the single word OK."}], max_tokens=10)
    except llm.LLMError as e:
        return {"ok": False, "error": str(e)[:500]}
    return {"ok": True, "reply": text.strip()[:100], "ms": round((time.monotonic() - started) * 1000), "cost": usage["cost"]}


@app.patch("/api/admin/sites/{site_id}/models")
def admin_site_models(site_id: int, body: SiteModels, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    for field in ("answer_model", "fast_model"):
        ref = getattr(body, field)
        if ref and not providers.target_for(db, ref):
            raise HTTPException(400, f"{ref} isn't usable: it's missing, turned off, or its provider has no API key.")
        setattr(site, field, ref or None)
    db.commit()
    return site_out(site)


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
    headers = {"Content-Security-Policy": widget_csp(e, site), "Cache-Control": "no-cache"}
    if not page.exists():
        return Response("Frontend not built. Run `npm run build` in frontend/.", media_type="text/plain", headers=headers)
    return FileResponse(page, headers=headers)


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
