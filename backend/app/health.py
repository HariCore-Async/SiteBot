"""AI provider health: failed calls are recorded; a provider that runs out of credit, or fails again and again, raises an
alert that admins see in the Admin console and get by email (at most once an hour). It clears when the provider works
again or an admin dismisses it. None of this may ever break answering, so every step swallows its own errors."""

import logging
from datetime import timedelta

from sqlalchemy import delete, func, select

from .config import settings
from .models import AIFailure, ProviderAlert, UsageEvent, User, utcnow

log = logging.getLogger(__name__)

FAILING_COUNT = 5
FAILING_WINDOW = timedelta(minutes=10)
EMAIL_EVERY = timedelta(hours=1)
KEEP_FAILURES = timedelta(days=7)
# Providers with an open alert, so a success only touches the database when there's something to clear.
_open: set[tuple[str, str]] | None = None


def _session():
    from .db import SessionLocal

    return SessionLocal()


def _open_providers(db) -> set[tuple[str, str]]:
    global _open
    if _open is None:
        _open = set(db.execute(select(ProviderAlert.provider, ProviderAlert.model).where(ProviderAlert.resolved_at.is_(None), ProviderAlert.dismissed_at.is_(None))).tuples())
    return _open


def is_out_of_credit(status: int, message: str) -> bool:
    text = message.lower()
    return status == 402 or "requires more credits" in text or "insufficient_quota" in text or "credit balance is too low" in text


def record_failure(provider: str, model: str, status: int, message: str) -> None:
    try:
        with _session() as db:
            now = utcnow()
            db.add(AIFailure(provider=provider, model=model, status=status, message=message[:1000]))
            db.execute(delete(AIFailure).where(AIFailure.created_at < now - KEEP_FAILURES))
            db.commit()
            recent = db.scalar(
                select(func.count(AIFailure.id)).where(AIFailure.provider == provider, AIFailure.model == model, AIFailure.created_at >= now - FAILING_WINDOW)
            )
            kind = "credit" if is_out_of_credit(status, message) else "failing" if recent >= FAILING_COUNT else None
            if kind:
                _raise_alert(db, provider, model, kind, message, recent)
    except Exception as e:  # noqa: BLE001
        log.warning("Couldn't record an AI failure: %s", e)


def _raise_alert(db, provider: str, model: str, kind: str, message: str, recent: int) -> None:
    now = utcnow()
    alert = db.scalar(
        select(ProviderAlert)
        .where(ProviderAlert.provider == provider, ProviderAlert.model == model, ProviderAlert.resolved_at.is_(None), ProviderAlert.dismissed_at.is_(None))
        .order_by(ProviderAlert.id.desc())
    )
    if alert:
        alert.last_at, alert.message, alert.failures = now, message[:1000], alert.failures + 1
        if kind == "credit":
            alert.kind = "credit"
    else:
        alert = ProviderAlert(provider=provider, model=model, kind=kind, message=message[:1000], failures=recent, first_at=now, last_at=now)
        db.add(alert)
    send = alert.emailed_at is None or now - alert.emailed_at >= EMAIL_EVERY
    if send:
        alert.emailed_at = now
    db.commit()
    _open_providers(db).add((provider, model))
    if send:
        _email_admins(db, alert)


def _email_admins(db, alert: ProviderAlert) -> None:
    from . import accounts

    admins = set(db.scalars(select(User.email).where(User.role == "admin"))) | settings.admin_email_set
    what = (
        f"{alert.provider} says it's out of credit (model {alert.model})"
        if alert.kind == "credit"
        else f"{alert.provider} ({alert.model}) has failed {alert.failures} times in the last {int(FAILING_WINDOW.total_seconds() // 60)} minutes"
    )
    link = f"\n\n{settings.app_url.rstrip('/')}/" if settings.app_url else ""
    accounts.notify(
        sorted(admins),
        f"SiteBot: AI provider problem ({alert.provider})",
        f"{what}. Chatbots fall back to the next model if one is set; otherwise they can't answer.\n\n"
        f"Last error: {alert.message[:400]}\n\n"
        "Check the provider's account (credit, key, limits). The alert clears by itself once it works again; "
        f"see Admin console > AI providers.{link}",
    )


def record_success(provider: str, model: str) -> None:
    try:
        with _session() as db:
            if (provider, model) not in _open_providers(db):
                return
            # Only the same model working clears it: a provider can still afford small calls while bigger ones fail.
            for a in db.scalars(select(ProviderAlert).where(ProviderAlert.provider == provider, ProviderAlert.model == model, ProviderAlert.resolved_at.is_(None))):
                a.resolved_at = utcnow()
            db.commit()
            _open_providers(db).discard((provider, model))
    except Exception as e:  # noqa: BLE001
        log.warning("Couldn't clear AI provider alerts: %s", e)


def dismiss(db, alert_id: int) -> bool:
    a = db.get(ProviderAlert, alert_id)
    if not a:
        return False
    a.dismissed_at = utcnow()
    db.commit()
    _open_providers(db).discard((a.provider, a.model))
    return True


def alert_out(a: ProviderAlert) -> dict:
    return {
        "id": a.id, "provider": a.provider, "model": a.model, "kind": a.kind, "message": a.message, "failures": a.failures,
        "first_at": a.first_at.isoformat(), "last_at": a.last_at.isoformat(),
    }


def open_alerts(db) -> list[dict]:
    rows = db.scalars(
        select(ProviderAlert).where(ProviderAlert.resolved_at.is_(None), ProviderAlert.dismissed_at.is_(None)).order_by(ProviderAlert.last_at.desc())
    )
    return [alert_out(a) for a in rows]


def summary(db) -> dict:
    """The last 24 hours per provider: calls that worked, failures, spend, and the latest error."""
    since = utcnow() - timedelta(hours=24)
    stats: dict[str, dict] = {}
    for provider, calls, spend in db.execute(
        select(UsageEvent.provider, func.count(UsageEvent.id), func.coalesce(func.sum(UsageEvent.cost_usd), 0))
        .where(UsageEvent.created_at >= since)
        .group_by(UsageEvent.provider)
    ):
        stats[provider or "Unknown"] = {"provider": provider or "Unknown", "ok": calls, "errors": 0, "spend_usd": round(float(spend), 6), "last_error": None}
    for provider, errors in db.execute(
        select(AIFailure.provider, func.count(AIFailure.id)).where(AIFailure.created_at >= since).group_by(AIFailure.provider)
    ):
        row = stats.setdefault(provider, {"provider": provider, "ok": 0, "errors": 0, "spend_usd": 0.0, "last_error": None})
        row["errors"] = errors
        last = db.scalar(select(AIFailure).where(AIFailure.provider == provider).order_by(AIFailure.id.desc()))
        row["last_error"] = {"message": last.message[:300], "status": last.status, "at": last.created_at.isoformat()} if last else None
    for row in stats.values():
        row["requests"] = row["ok"] + row["errors"]
    return {"providers": sorted(stats.values(), key=lambda r: -r["requests"]), "alerts": open_alerts(db)}
