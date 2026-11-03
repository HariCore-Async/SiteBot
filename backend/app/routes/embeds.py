"""Website chatbots (embeds): settings, team, test websites, keys, conversations, insights and leads."""

import csv
import io
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import accounts, verify
from ..auth import current_user
from ..config import settings
from ..db import get_db
from ..embeds import (
    MAX_TEST_ORIGINS,
    clean_origin,
    embed_out,
    hash_secret,
    insights,
    new_key,
    new_secret,
    new_test_origin,
    parse_test_origin,
    sanitize_css,
)
from ..models import Chat, Embed, EmbedMember, Lead, Message, Site, User, utcnow
from ..schemas import (
    EmbedIn,
    EmbedUpdate,
    LeadUpdate,
    MemberIn,
    MemberUpdate,
    TestOriginIn,
    VerifyIn,
)
from ..xlsx import to_xlsx
from .common import ROLE_RANK, app_link, embed_role, messages_out, with_feedback

router = APIRouter()


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
    if not e.verify_token:
        e.verify_token = verify.new_token()
        db.commit()
    return {**embed_out(db, e, db.get(Site, e.site_id)), "my_role": embed_role(db, e, user)}


@router.post("/api/embeds/{embed_id}/verify")
def verify_domain(embed_id: int, body: VerifyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Checks the meta tag or DNS record. Once verified, a waiting request is approved without an admin."""
    e = own_embed(db, embed_id, user, "owner")
    site = db.get(Site, e.site_id)
    if not e.verify_token:
        e.verify_token = verify.new_token()
        db.commit()
    check = verify.check_meta if body.method == "meta" else verify.check_dns
    ok, problem = check(site.domain, e.verify_token)
    if not ok:
        raise HTTPException(400, f"Not verified yet: {problem}.")
    e.verified_at, e.verified_via = utcnow(), body.method
    # Approves a waiting request, unless an admin already reviewed it (e.g. rejected it): their decision stands.
    if e.status == "pending" and e.reviewed_at is None:
        e.status, e.reviewed_by, e.reviewed_at = "approved", "domain verification", utcnow()
        e.review_note = ""
    db.commit()
    return embed_view(db, e, user)


@router.get("/api/embeds")
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


@router.get("/api/embeds/{embed_id}/team")
def embed_team(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "viewer")
    owner = db.get(User, e.owner_id)
    members = db.scalars(select(EmbedMember).where(EmbedMember.embed_id == e.id).order_by(EmbedMember.created_at)).all()
    return {"owner": {"name": owner.name, "email": owner.email}, "members": [member_out(m, db) for m in members]}


@router.post("/api/embeds/{embed_id}/team")
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


@router.patch("/api/embeds/{embed_id}/team/{member_id}")
def change_member(embed_id: int, member_id: int, body: MemberUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "owner")
    m = db.get(EmbedMember, member_id)
    if not m or m.embed_id != e.id:
        raise HTTPException(404, "Not found")
    m.role = body.role
    db.commit()
    return member_out(m, db)


@router.delete("/api/embeds/{embed_id}/team/{member_id}")
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


@router.post("/api/embeds")
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


@router.patch("/api/embeds/{embed_id}")
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


# ---------- Test websites: extra places this bot may run while testing (e.g. http://localhost:5175) ----------

@router.post("/api/embeds/{embed_id}/test-origins")
def add_test_origin(embed_id: int, body: TestOriginIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "editor")
    origin = parse_test_origin(body.origin)
    before = next((t for t in e.test_origins or [] if t["origin"] == origin), None)
    entries = [t for t in (e.test_origins or []) if t["origin"] != origin]
    if len(entries) >= MAX_TEST_ORIGINS:
        raise HTTPException(400, f"You can have up to {MAX_TEST_ORIGINS} test websites. Remove one first.")
    # Adding one that's already there renews it (an approved one stays approved).
    entry = new_test_origin(origin, user, "approved" if before and before.get("status", "approved") == "approved" else None)
    e.test_origins = [*entries, entry]
    db.commit()
    if entry["status"] == "pending" and not before:
        site = db.get(Site, e.site_id)
        admins = list(db.scalars(select(User.email).where(User.role == "admin"))) + sorted(settings.admin_email_set)
        accounts.notify(
            admins,
            f"SiteBot: {user.name or user.email} wants to test {site.name} Chatbot on {origin}",
            f"{user.name} ({user.email}) added {origin} as a test website for {site.name} Chatbot.\n\n"
            f"Approve or remove it in SiteBot: Admin console > Embeds > Test websites.{app_link()}",
        )
    return embed_view(db, e, user)


@router.post("/api/embeds/{embed_id}/test-origins/renew")
def renew_test_origin(embed_id: int, body: TestOriginIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "editor")
    origin = parse_test_origin(body.origin)
    if not any(t["origin"] == origin for t in e.test_origins or []):
        raise HTTPException(404, "That test website isn't on the list.")
    e.test_origins = [new_test_origin(origin, user, t.get("status", "approved")) if t["origin"] == origin else t for t in e.test_origins]
    db.commit()
    return embed_view(db, e, user)


@router.delete("/api/embeds/{embed_id}/test-origins")
def remove_test_origin(embed_id: int, origin: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "editor")
    e.test_origins = [t for t in (e.test_origins or []) if t["origin"] != clean_origin(origin)]
    db.commit()
    return embed_view(db, e, user)


@router.post("/api/embeds/{embed_id}/rotate-key")
def rotate_embed_key(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Issues a new key; the old snippet stops working straight away."""
    e = own_embed(db, embed_id, user)
    e.key = new_key()
    db.commit()
    return embed_view(db, e, user)


@router.post("/api/embeds/{embed_id}/server-key")
def make_server_key(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Creates (or replaces) the secret key for the headless API. The key is returned this once and never again."""
    e = own_embed(db, embed_id, user)
    secret = new_secret()
    e.secret_hash, e.secret_hint, e.secret_created_at, e.secret_last_used_at = hash_secret(secret), secret[-4:], utcnow(), None
    db.commit()
    return {**embed_view(db, e, user), "secret": secret}


@router.delete("/api/embeds/{embed_id}/server-key")
def revoke_server_key(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user)
    e.secret_hash, e.secret_hint, e.secret_created_at, e.secret_last_used_at = None, "", None, None
    db.commit()
    return embed_view(db, e, user)


@router.delete("/api/embeds/{embed_id}")
def delete_embed(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(own_embed(db, embed_id, user))
    db.commit()
    return {"ok": True}


@router.get("/api/embeds/{embed_id}/chats")
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


@router.get("/api/embeds/{embed_id}/insights")
def embed_insights(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return insights(db, own_embed(db, embed_id, user, "viewer"))


@router.get("/api/embeds/{embed_id}/export")
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


@router.get("/api/embeds/{embed_id}/chats/{chat_id}/messages")
def embed_chat_messages(embed_id: int, chat_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "viewer")
    chat = db.get(Chat, chat_id)
    if not chat or chat.embed_id != e.id:
        raise HTTPException(404, "Chat not found")
    return with_feedback(db, messages_out(db, chat_id))


# ---------- Human handoff: visitors who leave their email ----------

def lead_out(lead: Lead) -> dict:
    return {
        "id": lead.id, "email": lead.email, "name": lead.name, "message": lead.message, "question": lead.question,
        "origin": lead.origin, "status": lead.status, "chat_id": lead.chat_id, "created_at": lead.created_at.isoformat(),
    }


@router.get("/api/embeds/{embed_id}/leads")
def embed_leads(embed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "viewer")
    return [lead_out(x) for x in db.scalars(select(Lead).where(Lead.embed_id == e.id).order_by(Lead.created_at.desc()).limit(500))]


@router.patch("/api/embeds/{embed_id}/leads/{lead_id}")
def update_lead(embed_id: int, lead_id: int, body: LeadUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = own_embed(db, embed_id, user, "editor")
    lead = db.get(Lead, lead_id)
    if not lead or lead.embed_id != e.id:
        raise HTTPException(404, "Not found")
    lead.status = body.status
    db.commit()
    return lead_out(lead)
