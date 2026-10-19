"""Email/password accounts: password hashing, one-time email codes, and sending them."""

import hashlib
import hmac
import logging
import re
import secrets
import smtplib
from datetime import timedelta
from email.message import EmailMessage

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .models import EmailCode, User, utcnow

log = logging.getLogger(__name__)

CODE_MINUTES = 10
MAX_CODE_ATTEMPTS = 5
RESEND_AFTER_SECONDS = 45
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- Passwords (scrypt, stdlib) ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, salt, digest = stored.split("$")
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(candidate.hex(), digest)


def validate_password(password: str) -> None:
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(400, "Use at least 8 characters, with at least one letter and one number.")


def find_account(db: Session, identifier: str) -> User | None:
    ident = identifier.strip().lower()
    return db.scalar(select(User).where(or_(func.lower(User.email) == ident, func.lower(User.username) == ident)))


# ---------- One-time codes ----------

def _code_hash(email: str, code: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def latest_code(db: Session, email: str) -> EmailCode | None:
    return db.scalar(select(EmailCode).where(EmailCode.email == email).order_by(EmailCode.id.desc()).limit(1))


def send_code(db: Session, email: str, payload: dict) -> None:
    latest = latest_code(db, email)
    if latest and latest.payload == payload and (utcnow() - latest.created_at).total_seconds() < RESEND_AFTER_SECONDS:
        return  # the same code was just sent; don't flood the inbox
    code = f"{secrets.randbelow(10**6):06d}"
    db.execute(delete(EmailCode).where(EmailCode.email == email))
    db.add(
        EmailCode(
            email=email, code_hash=_code_hash(email, code), payload=payload,
            expires_at=utcnow() + timedelta(minutes=CODE_MINUTES),
        )
    )
    db.commit()
    deliver_code(email, code)


def check_code(db: Session, email: str, code: str) -> dict:
    """Validates the code and returns the sign-up details it was issued for."""
    row = latest_code(db, email)
    if not row or row.expires_at < utcnow():
        raise HTTPException(400, "That code has expired. Request a new one.")
    if row.attempts >= MAX_CODE_ATTEMPTS:
        raise HTTPException(429, "Too many wrong attempts. Request a new code.")
    if not hmac.compare_digest(row.code_hash, _code_hash(email, code.strip())):
        row.attempts += 1
        db.commit()
        raise HTTPException(400, "That code isn't right. Check the email and try again.")
    payload = dict(row.payload or {})
    db.delete(row)
    db.commit()
    return payload


# ---------- Delivery ----------

def deliver_code(email: str, code: str) -> None:
    subject = f"{code} is your SiteBot verification code"
    body = (
        f"Your SiteBot verification code is {code}.\n\n"
        f"It expires in {CODE_MINUTES} minutes. If you didn't ask for it, you can ignore this email."
    )
    try:
        if settings.resend_api_key:
            r = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.mail_from, "to": [email], "subject": subject, "text": body},
                timeout=20,
            )
            r.raise_for_status()
        elif settings.smtp_host:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = settings.mail_from, email, subject
            msg.set_content(body)
            if settings.smtp_port == 465:
                server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20)
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
                server.starttls()
            with server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        else:
            log.warning("No email provider configured. Verification code for %s: %s", email, code)
    except (httpx.HTTPError, smtplib.SMTPException, OSError) as e:
        log.error("Could not send verification email to %s: %s", email, e)
        raise HTTPException(502, "We couldn't send the verification email. Please try again in a moment.")
