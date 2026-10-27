"""Website embeds: the domain lock, visitor rate limits and the shapes the embed API returns."""

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
from .models import Chat, Embed, Site, UsageEvent, User
from .usage import embed_spent_today

VISITOR_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def new_key() -> str:
    return "pk_" + secrets.token_urlsafe(18)


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


def check_visitor(visitor_id: str) -> str:
    if not VISITOR_RE.match(visitor_id or ""):
        raise HTTPException(400, "Please reload the page and try again.")
    return visitor_id


def require_same_origin(request: Request) -> None:
    """The public API is only for our own widget page. Browsers say where a request came from; refuse other websites."""
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        raise HTTPException(403, "Not allowed.")


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


def embed_out(db: Session, e: Embed, site: Site) -> dict:
    total = db.scalar(select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(UsageEvent.embed_id == e.id))
    return {
        "id": e.id, "key": e.key, "site_id": e.site_id, "status": e.status, "enabled": e.enabled,
        "color": e.color, "greeting": e.greeting, "position": e.position, "daily_cap_usd": e.daily_cap_usd,
        "spent_today_usd": round(embed_spent_today(db, e.id), 6), "spent_total_usd": round(float(total), 6),
        "conversations": db.scalar(select(func.count(Chat.id)).where(Chat.embed_id == e.id)),
        "reviewed_by": e.reviewed_by, "reviewed_at": e.reviewed_at.isoformat() if e.reviewed_at else None,
        "created_at": e.created_at.isoformat(),
        "site": {"id": site.id, "name": site.name, "domain": site.domain, "favicon": site.favicon, "ready": site.generation > 0},
    }


def admin_embed_out(db: Session, e: Embed, site: Site, owner: User) -> dict:
    return {**embed_out(db, e, site), "owner": {"id": owner.id, "name": owner.name, "email": owner.email}}
