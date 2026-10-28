"""Background jobs on a timer inside the web process: scheduled re-indexing and weekly report emails.

Runs every SCHEDULER_INTERVAL_SECONDS (default 10 minutes); SCHEDULER_ENABLED=false turns it off. Like indexing, it
assumes one copy of the app (Railway: one replica).
"""

import logging
import threading
import time
from datetime import timedelta

from sqlalchemy import func, select

from . import accounts
from .config import settings
from .db import SessionLocal
from .embeds import insights
from .ingest import is_running, start_ingestion
from .models import Chat, Embed, Lead, Site, UsageEvent, User, utcnow

log = logging.getLogger(__name__)

PERIODS = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}
REPORT_EVERY = timedelta(days=7)


def due_reindexes(db) -> list[int]:
    """Bots on a schedule whose last successful index is older than their period, and that aren't already indexing."""
    now = utcnow()
    due = []
    for site in db.scalars(select(Site).where(Site.reindex_schedule.in_(PERIODS), Site.generation > 0)):
        last = site.indexed_at or site.created_at
        if now - last >= PERIODS[site.reindex_schedule] and not is_running(site.id) and site.status not in ("queued", "crawling", "embedding"):
            due.append(site.id)
    return due


def run_reindexes(db) -> int:
    started = 0
    for site_id in due_reindexes(db):
        site = db.get(Site, site_id)
        site.status, site.message = "queued", "Scheduled update in the background…"
        db.commit()
        if start_ingestion(site_id):
            started += 1
            log.info("Scheduled re-index started for site %s", site_id)
    return started


def report_text(db, e: Embed) -> str:
    site = db.get(Site, e.site_id)
    since = utcnow() - REPORT_EVERY
    chats = db.scalar(select(func.count(Chat.id)).where(Chat.embed_id == e.id, Chat.is_test.is_(False), Chat.updated_at >= since))
    spent = float(db.scalar(select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(UsageEvent.embed_id == e.id, UsageEvent.created_at >= since)))
    leads = db.scalar(select(func.count(Lead.id)).where(Lead.embed_id == e.id, Lead.created_at >= since))
    open_leads = db.scalar(select(func.count(Lead.id)).where(Lead.embed_id == e.id, Lead.status == "open"))
    ins = insights(db, e, days=7)
    lines = [
        f"Your week with {site.name} Chatbot on {site.domain}:",
        "",
        f"- Conversations: {chats}",
        f"- People who left their email: {leads} (open: {open_leads})",
        f"- Spend: ${spent:.4f}",
    ]
    if ins["top_questions"]:
        lines += ["", "Most asked:"] + [f"  {i}. {q['question']} ({q['count']}x)" for i, q in enumerate(ins["top_questions"][:5], 1)]
    if ins["unanswered"]:
        lines += ["", "Questions it couldn't answer (teach it on the Knowledge tab):"]
        lines += [f"  - {q['question']} ({q['count']}x)" for q in ins["unanswered"][:5]]
    lines += ["", "You can turn this email off on the chatbot's Usage & settings tab."]
    return "\n".join(lines)


def due_reports(db) -> list[int]:
    now = utcnow()
    return [
        e.id for e in db.scalars(select(Embed).where(Embed.weekly_report.is_(True), Embed.status == "approved"))
        if now - (e.last_report_at or e.created_at) >= REPORT_EVERY
    ]


def send_reports(db) -> int:
    sent = 0
    for embed_id in due_reports(db):
        e = db.get(Embed, embed_id)
        owner = db.get(User, e.owner_id)
        site = db.get(Site, e.site_id)
        # Quiet weeks don't get an email.
        if db.scalar(select(func.count(Chat.id)).where(Chat.embed_id == e.id, Chat.is_test.is_(False), Chat.updated_at >= utcnow() - REPORT_EVERY)):
            link = f"\n\n{settings.app_url.rstrip('/')}/#/website/{e.id}/usage" if settings.app_url else ""
            accounts.notify([owner.email], f"SiteBot: your week with {site.name} Chatbot", report_text(db, e) + link)
            sent += 1
        e.last_report_at = utcnow()
        db.commit()
    return sent


def tick() -> None:
    db = SessionLocal()
    try:
        run_reindexes(db)
        send_reports(db)
    except Exception:  # noqa: BLE001  (one bad run mustn't stop the timer)
        log.exception("Scheduled jobs failed")
    finally:
        db.close()


def start() -> None:
    if not settings.scheduler_enabled:
        log.info("Scheduler is off (SCHEDULER_ENABLED=false)")
        return

    def loop():
        time.sleep(30)  # let the app finish starting
        while True:
            tick()
            time.sleep(max(60, settings.scheduler_interval_seconds))

    threading.Thread(target=loop, daemon=True, name="scheduler").start()
