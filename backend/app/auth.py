from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AccessGrant, AppSetting, User, utcnow

COOKIE_NAME = "sitebot_session"
SESSION_DAYS = 7

# Approving someone on one of these domains grants only that address, never the whole domain.
PUBLIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
    "yahoo.com", "yahoo.co.in", "ymail.com", "icloud.com", "me.com", "mac.com", "aol.com",
    "proton.me", "protonmail.com", "zoho.com", "gmx.com", "mail.com", "rediffmail.com",
    "yandex.com", "qq.com",
}


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


def is_org_domain(domain: str) -> bool:
    return domain not in PUBLIC_EMAIL_DOMAINS


def approval_required(db: Session) -> bool:
    """Admin switch (Admin > Access). Off by default: anyone can sign in; on: only approved emails and domains."""
    row = db.get(AppSetting, "require_approval")
    return bool(row and row.value == "true")


def set_approval_required(db: Session, value: bool) -> None:
    row = db.get(AppSetting, "require_approval")
    if row:
        row.value = "true" if value else "false"
    else:
        db.add(AppSetting(key="require_approval", value="true" if value else "false"))
    db.commit()


def has_access(db: Session, email: str) -> bool:
    email = email.lower()
    if email in settings.admin_email_set or not approval_required(db):
        return True
    if db.scalar(select(AccessGrant.id).where(func.lower(AccessGrant.email) == email)):
        return True
    domain = email_domain(email)
    if is_org_domain(domain):
        return bool(
            db.scalar(select(AccessGrant.id).where(func.lower(AccessGrant.email).like(f"%@{domain}")))
        )
    return False


def login_user(
    db: Session, response: Response, email: str, name: str = "", picture: str = "", email_verified: bool = False
) -> User:
    email = email.lower().strip()
    if not has_access(db, email):
        raise HTTPException(403, "Your email has not been approved. Ask an admin for access.")
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = User(email=email, name=name or email.split("@")[0], picture=picture)
        db.add(user)
    else:
        user.name = name or user.name
        user.picture = picture or user.picture
    if email_verified:
        user.email_verified = True
    if email in settings.admin_email_set:
        user.role = "admin"
    user.last_seen_at = utcnow()
    db.commit()

    token = jwt.encode(
        {"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)},
        settings.secret_key,
        algorithm="HS256",
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not signed in")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired")
    user = db.get(User, int(payload["sub"]))
    # Re-check access on every request so revoking a grant takes effect immediately.
    if not user or not has_access(db, user.email):
        raise HTTPException(401, "Access revoked")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admins only")
    return user
