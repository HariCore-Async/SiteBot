"""Sign-in (Google, email and password), the signed-in user's own account, and the public app config."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import accounts, auth
from ..auth import current_user, login_user
from ..config import settings
from ..db import get_db
from ..models import User
from ..schemas import (
    ChangePassword,
    ForgotPassword,
    GoogleLogin,
    PasswordLogin,
    ResendCode,
    ResetPassword,
    SetUsername,
    SignUp,
    VerifyCode,
    user_out,
)
from ..usage import usage_summary

router = APIRouter()


# ---------- Auth ----------

@router.get("/api/config")
def public_config(db: Session = Depends(get_db)):
    return {
        "google_client_id": settings.google_client_id,
        "require_approval": auth.approval_required(db),
        "email_enabled": accounts.email_enabled(),
        "billing_enabled": settings.billing_enabled,
        "sentry": {"dsn": settings.sentry_browser_dsn, "environment": settings.sentry_environment} if settings.sentry_browser_dsn else None,
    }


@router.post("/api/auth/google")
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


@router.post("/api/auth/signup")
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


@router.post("/api/auth/verify")
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


@router.post("/api/auth/resend")
def resend_code(body: ResendCode, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    row = accounts.latest_code(db, email)
    if not row:
        raise HTTPException(400, "Please start again.")
    accounts.send_code(db, email, dict(row.payload or {}))
    return {"ok": True}


@router.post("/api/auth/login")
def password_login(body: PasswordLogin, response: Response, db: Session = Depends(get_db)):
    user = accounts.find_account(db, body.identifier)
    if user and not user.password_hash:
        raise HTTPException(
            401, "This account signs in with Google and has no password yet. Continue with Google, or use Forgot password to set one."
        )
    if not user or not accounts.check_password(body.password, user.password_hash):
        raise HTTPException(401, "That email/username and password don't match.")
    return user_out(login_user(db, response, user.email))


@router.post("/api/auth/forgot")
def forgot_password(body: ForgotPassword, db: Session = Depends(get_db)):
    """Emails a reset code. Always answers the same way, so it can't be used to check who has an account."""
    accounts.require_email()
    user = accounts.find_account(db, body.identifier)
    if user:
        accounts.send_code(db, user.email, {"purpose": "reset"})
    return {"ok": True}


@router.post("/api/auth/reset")
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


@router.post("/api/me/password")
def change_password(body: ChangePassword, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.password_hash and not accounts.check_password(body.current_password or "", user.password_hash):
        raise HTTPException(400, "Your current password isn't right.")
    accounts.validate_password(body.password)
    if body.password != body.confirm_password:
        raise HTTPException(400, "The passwords don't match.")
    user.password_hash = accounts.hash_password(body.password)
    db.commit()
    return user_out(user)


@router.post("/api/me/username")
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


@router.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@router.post("/api/auth/logout-everywhere")
def logout_everywhere(response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Ends every session of this account, on every device, including this one."""
    auth.sign_out_everywhere(db, user)
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@router.get("/api/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {**user_out(user), "usage": usage_summary(db, user)}


@router.get("/api/usage")
def my_usage(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return usage_summary(db, user)
