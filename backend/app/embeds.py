"""Website embeds: the domain lock, server keys, visitor rate limits and the shapes the embed APIs return."""

import hashlib
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Chat, Embed, Feedback, Message, Site, UsageEvent, User
from .usage import embed_spent_today, start_of_today

# Our widget and sitebot-client.js make their own random ids; server callers may pass their own user ids.
VISITOR_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
SERVER_VISITOR_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,64}$")

STYLE_DEFAULTS = {
    "launcher_icon": "chat", "launcher_label": "", "title": "", "font": "system", "radius": 16, "theme": "light", "custom_css": "",
}


def new_key() -> str:
    return "pk_" + secrets.token_urlsafe(18)


def new_secret() -> str:
    return "sk_" + secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def sanitize_css(css: str) -> str:
    """Owners' custom CSS for the widget. It only applies inside our iframe; this strips anything that could load
    other resources (and so leak visitors' activity) or run code in old browsers."""
    css = (css or "")[:5000].replace("\\", "").replace("<", "")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@import[^;]*;?", "", css, flags=re.I)
    css = re.sub(r"(?:-webkit-)?image-set\s*\([^)]*\)?|url\s*\([^)]*\)?", "none", css, flags=re.I)
    css = re.sub(r"expression\s*\(|javascript\s*:|behavior\s*:|-moz-binding", "", css, flags=re.I)
    return css.strip()


def style_of(e: Embed) -> dict:
    return {**STYLE_DEFAULTS, **(e.style or {})}


def clean_origin(origin: str) -> str:
    return (origin or "").strip().rstrip("/").lower()[:300]


def origin_allowed(e: Embed, site: Site, origin: str) -> bool:
    """By default a bot runs only on its own website: the domain itself, www. and any subdomain, over HTTPS.
    An admin can lift that for one embed (restrict_to_domain off); then any HTTPS website may use it."""
    origin = clean_origin(origin)
    if origin in settings.embed_dev_origin_list:
        return True
    p = urlparse(origin)
    host = (p.hostname or "").rstrip(".")
    if p.scheme != "https" or not host:
        return False
    return not e.restrict_to_domain or host == site.domain or host.endswith("." + site.domain)


def frame_ancestors(e: Embed, site: Site) -> str:
    """CSP for the widget page, so browsers refuse to show it inside any other website."""
    if not e.restrict_to_domain:
        return "frame-ancestors 'self' https: " + " ".join(settings.embed_dev_origin_list)
    sources = ["'self'", f"https://{site.domain}", f"https://*.{site.domain}", *settings.embed_dev_origin_list]
    return "frame-ancestors " + " ".join(sources)


def widget_csp(e: Embed | None, site: Site | None) -> str:
    """Owners can add custom CSS, so the widget page may load nothing from elsewhere except the bot's favicon."""
    favicon = urlparse(site.favicon or "") if site else None
    img = "'self' data:" + (f" https://{favicon.hostname}" if favicon and favicon.scheme == "https" and favicon.hostname else "")
    ancestors = frame_ancestors(e, site) if e and site else "frame-ancestors 'self'"
    return f"default-src 'self'; style-src 'self' 'unsafe-inline'; img-src {img}; connect-src 'self'; {ancestors}"


def check_visitor(visitor_id: str) -> str:
    if not VISITOR_RE.match(visitor_id or ""):
        raise HTTPException(400, "Please reload the page and try again.")
    return visitor_id


def effective_origin(request: Request, claimed: str) -> str:
    """The website a public-API request is for. Our widget runs on SiteBot's own origin and reports the website it's on;
    sitebot-client.js calls us straight from the website, so the browser's own Origin header is used instead."""
    fetch_site = request.headers.get("sec-fetch-site")
    origin = request.headers.get("origin")
    if fetch_site in ("same-origin", "none"):
        return claimed
    if fetch_site is None:
        # Older browsers don't send Sec-Fetch-Site; a call from another website still carries that website's Origin.
        return origin if origin and urlparse(origin).hostname != request.url.hostname else claimed
    if not origin:
        raise HTTPException(403, "Not allowed.")
    return origin


def is_cross_site(request: Request) -> bool:
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is None:
        origin = request.headers.get("origin")
        return bool(origin) and urlparse(origin).hostname != request.url.hostname
    return fetch_site not in ("same-origin", "none")


def server_key_embed(db: Session, request: Request) -> Embed:
    """The embed a headless-API call is for, from its `Authorization: Bearer sk_...` header."""
    if request.headers.get("origin"):
        raise HTTPException(403, "Server keys are secret: call this API from your server, never from a browser. Use sitebot-client.js with your pk_ key in browsers.")
    auth = request.headers.get("authorization", "")
    secret = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    e = db.scalar(select(Embed).where(Embed.secret_hash == hash_secret(secret))) if secret.startswith("sk_") else None
    if not e:
        raise HTTPException(401, "Missing or invalid server key. Send it as: Authorization: Bearer sk_...")
    return e


def client_ip(request: Request) -> str:
    # Railway's proxy puts the visitor's address first.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "")


class RateLimiter:
    """Sliding-window limits kept in memory. Good enough for one server; resets on restart."""

    def __init__(self, rules: list[tuple[int, int]]):
        self.rules = rules  # (max requests, window seconds)
        self.hits: dict[str, deque] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        longest = max(w for _, w in self.rules)
        with self.lock:
            q = self.hits.setdefault(key, deque())
            while q and q[0] <= now - longest:
                q.popleft()
            if any(sum(1 for t in q if t > now - window) >= limit for limit, window in self.rules):
                return False
            q.append(now)
            if len(self.hits) > 50000:  # forget idle keys so memory stays bounded
                for k in [k for k, v in self.hits.items() if not v or v[-1] <= now - longest]:
                    del self.hits[k]
            return True


# Questions cost money, so they're limited per visitor and per network address.
visitor_limiter = RateLimiter([(6, 60), (60, 3600)])
ip_limiter = RateLimiter([(20, 60), (300, 86400)])
# Cheap reads (opening the widget, loading history) get a looser limit.
read_limiter = RateLimiter([(60, 60)])
# A customer's server sends all its users' questions from one address, so server keys are limited per embed instead.
server_limiter = RateLimiter([(120, 60), (3000, 3600)])


def embed_out(db: Session, e: Embed, site: Site) -> dict:
    total = db.scalar(select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(UsageEvent.embed_id == e.id))
    ratings = dict(db.execute(select(Feedback.rating, func.count(Feedback.id)).where(Feedback.embed_id == e.id).group_by(Feedback.rating)).all())
    return {
        "id": e.id, "key": e.key, "site_id": e.site_id, "status": e.status, "enabled": e.enabled,
        "color": e.color, "greeting": e.greeting, "position": e.position, "daily_cap_usd": e.daily_cap_usd,
        "style": style_of(e), "restrict_to_domain": e.restrict_to_domain,
        "server_key": {
            "hint": e.secret_hint,
            "created_at": e.secret_created_at.isoformat() if e.secret_created_at else None,
            "last_used_at": e.secret_last_used_at.isoformat() if e.secret_last_used_at else None,
        } if e.secret_hash else None,
        "feedback": {"up": ratings.get("up", 0), "down": ratings.get("down", 0)},
        "spent_today_usd": round(embed_spent_today(db, e.id), 6), "spent_total_usd": round(float(total), 6),
        # Visitor counts leave out the owner's own test chats.
        "conversations": db.scalar(select(func.count(Chat.id)).where(Chat.embed_id == e.id, Chat.is_test.is_(False))),
        "chats_today": db.scalar(
            select(func.count(Chat.id)).where(Chat.embed_id == e.id, Chat.is_test.is_(False), Chat.updated_at >= start_of_today())
        ),
        "last_seen": {"origin": e.last_seen_origin, "at": e.last_seen_at.isoformat()} if e.last_seen_at else None,
        "reviewed_by": e.reviewed_by, "reviewed_at": e.reviewed_at.isoformat() if e.reviewed_at else None,
        "review_note": e.review_note,
        "created_at": e.created_at.isoformat(),
        "site": {"id": site.id, "name": site.name, "domain": site.domain, "favicon": site.favicon, "ready": site.generation > 0},
    }


def admin_embed_out(db: Session, e: Embed, site: Site, owner: User) -> dict:
    return {**embed_out(db, e, site), "owner": {"id": owner.id, "name": owner.name, "email": owner.email}}


def note_seen(db: Session, e: Embed, origin: str) -> None:
    """Remembers that a website loaded this bot, for "Check installation". Written at most once a minute per website."""
    origin = clean_origin(origin)
    now = datetime.now(timezone.utc)
    if not origin or (origin == e.last_seen_origin and e.last_seen_at and (now - e.last_seen_at).total_seconds() < 60):
        return
    e.last_seen_origin, e.last_seen_at = origin, now
    db.commit()


def normalize_question(text: str) -> str:
    """Groups the same question asked slightly differently: case, punctuation and spacing don't count."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def insights(db: Session, e: Embed, days: int = 30) -> dict:
    """Chats per day, the most asked questions and the ones the bot couldn't answer, over the last `days` days."""
    since = start_of_today() - timedelta(days=days - 1)
    chats = db.scalars(select(Chat).where(Chat.embed_id == e.id, Chat.is_test.is_(False), Chat.updated_at >= since)).all()
    per_day = {(since + timedelta(days=i)).date().isoformat(): 0 for i in range(days)}
    for c in chats:
        day = c.created_at.date().isoformat()
        if day in per_day:
            per_day[day] += 1
    ids = [c.id for c in chats]
    msgs = db.scalars(
        select(Message).where(Message.chat_id.in_(ids), Message.created_at >= since).order_by(Message.chat_id, Message.id).limit(20000)
    ).all() if ids else []
    asked: dict[str, dict] = {}
    missed: dict[str, dict] = {}
    for prev, cur in zip(msgs, msgs[1:]):
        if prev.role != "user" or cur.role != "assistant" or prev.chat_id != cur.chat_id:
            continue
        key = normalize_question(prev.content)
        if not key:
            continue
        for bucket, hit in ((asked, True), (missed, not cur.grounded)):
            if hit:
                row = bucket.setdefault(key, {"question": prev.content.strip()[:200], "count": 0, "last_at": None})
                row["count"] += 1
                row["last_at"] = max(row["last_at"] or "", prev.created_at.isoformat())
    top = lambda d, n: sorted(d.values(), key=lambda r: (-r["count"], r["question"]))[:n]
    return {
        "days": [{"date": d, "chats": n} for d, n in per_day.items()],
        "top_questions": top(asked, 10),
        "unanswered": top(missed, 20),
    }
