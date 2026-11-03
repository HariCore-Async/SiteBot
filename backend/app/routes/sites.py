"""Bots: adding a website, indexing progress, the user's list."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import settings
from ..crawler import Crawler, CrawlError, normalize_input_url
from ..db import get_db
from ..ingest import is_running, request_stop, start_ingestion
from ..models import Chat, HiddenSite, Page, Site, User
from ..schemas import (
    AddSite,
    site_out,
)
from ..suggest import get_suggestions
from .common import unhide

router = APIRouter()


# ---------- Sites (bots) ----------

@router.get("/api/sites")
def list_sites(user: User = Depends(current_user), db: Session = Depends(get_db)):
    sites = db.scalars(select(Site).order_by(Site.name)).all()
    hidden = set(db.scalars(select(HiddenSite.site_id).where(HiddenSite.user_id == user.id)))
    return [{**site_out(s), "hidden": s.id in hidden} for s in sites]


@router.post("/api/sites/{site_id}/remove")
def remove_from_my_list(site_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Removes a bot from the user's own list and deletes their conversation with it. Other users are unaffected."""
    if not db.get(Site, site_id):
        raise HTTPException(404, "Bot not found")
    db.execute(delete(Chat).where(Chat.user_id == user.id, Chat.site_id == site_id))
    if not db.get(HiddenSite, (user.id, site_id)):
        db.add(HiddenSite(user_id=user.id, site_id=site_id))
    db.commit()
    return {"ok": True}


@router.post("/api/sites")
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


@router.get("/api/sites/{site_id}")
def get_site(site_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    return site_out(site)


@router.post("/api/sites/{site_id}/stop")
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


@router.post("/api/sites/{site_id}/read-all")
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


@router.get("/api/sites/{site_id}/suggestions")
def site_suggestions(site_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    return {"questions": get_suggestions(db, site, user)}


@router.get("/api/sites/{site_id}/pages")
def site_pages(site_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    gen = db.scalar(select(func.max(Page.generation)).where(Page.site_id == site_id)) or 0
    pages = db.scalars(select(Page).where(Page.site_id == site_id, Page.generation == gen).order_by(Page.id)).all()
    return [{"url": p.url, "title": p.title, "status": p.status, "rendered": p.rendered} for p in pages]
