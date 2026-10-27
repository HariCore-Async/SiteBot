"""Website embeds: the domain lock, server keys, visitor rate limits and the shapes the embed APIs return."""

import hashlib
import re
import secrets
import threading
import time
from collections import deque
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Chat, Embed, Feedback, Site, UsageEvent, User
from .usage import embed_spent_today

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


def origin_allowed(site: Site, origin: str) -> bool:
    """A bot runs only on its own website: the domain itself, www. and any subdomain, over HTTPS."""
    origin = (origin or "").strip().rstrip("/").lower()
    if origin in settings.embed_dev_origin_list:
        return True
    p = urlparse(origin)
    host = (p.hostname or "").rstrip(".")
    return p.scheme == "https" and (host == site.domain or host.endswith("." + site.domain))


def frame_ancestors(site: Site) -> str:
    """CSP for the widget page, so browsers refuse to show it inside any other website."""
    sources = ["'self'", f"https://{site.domain}", f"https://*.{site.domain}", *settings.embed_dev_origin_list]
    return "frame-ancestors " + " ".join(sources)


def widget_csp(site: Site | None) -> str:
    """Owners can add custom CSS, so the widget page may load nothing from elsewhere except the bot's favicon."""
    favicon = urlparse(site.favicon or "") if site else None
    img = "'self' data:" + (f" https://{favicon.hostname}" if favicon and favicon.scheme == "https" and favicon.hostname else "")
    ancestors = frame_ancestors(site) if site else "frame-ancestors 'self'"
    return f"default-src 'self'; style-src 'self' 'unsafe-inline'; img-src {img}; connect-src 'self'; {ancestors}"


def check_visitor(visitor_id: str) -> str:
    if not VISITOR_RE.match(visitor_id or ""):
        raise HTTPException(400, "Please reload the page and try again.")
    return visitor_id


def effective_origin(request: Request, claimed: str) -> str:
    """The website a public-API request is for. Our widget runs on SiteBot's own origin and reports the website it's on;
    sitebot-client.js calls us straight from the website, so the browser's own Origin header is used instead."""
    if request.headers.get("sec-fetch-site", "same-origin") in ("same-origin", "none"):
        return claimed
    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(403, "Not allowed.")
    return origin


def is_cross_site(request: Request) -> bool:
    return request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none")


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
        "style": style_of(e),
        "server_key": {"hint": e.secret_hint, "created_at": e.secret_created_at.isoformat() if e.secret_created_at else None}
        if e.secret_hash else None,
        "feedback": {"up": ratings.get("up", 0), "down": ratings.get("down", 0)},
        "spent_today_usd": round(embed_spent_today(db, e.id), 6), "spent_total_usd": round(float(total), 6),
        "conversations": db.scalar(select(func.count(Chat.id)).where(Chat.embed_id == e.id)),
        "reviewed_by": e.reviewed_by, "reviewed_at": e.reviewed_at.isoformat() if e.reviewed_at else None,
        "created_at": e.created_at.isoformat(),
        "site": {"id": site.id, "name": site.name, "domain": site.domain, "favicon": site.favicon, "ready": site.generation > 0},
    }


def admin_embed_out(db: Session, e: Embed, site: Site, owner: User) -> dict:
    return {**embed_out(db, e, site), "owner": {"id": owner.id, "name": owner.name, "email": owner.email}}
