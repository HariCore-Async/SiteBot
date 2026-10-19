from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import AppSetting, UsageEvent, User


def global_budget(db: Session) -> float:
    row = db.get(AppSetting, "global_budget_usd")
    return float(row.value) if row else settings.global_budget_usd


def set_global_budget(db: Session, value: float) -> None:
    row = db.get(AppSetting, "global_budget_usd")
    if row:
        row.value = str(value)
    else:
        db.add(AppSetting(key="global_budget_usd", value=str(value)))
    db.commit()


def user_spent(db: Session, user_id: int) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(UsageEvent.user_id == user_id)))


def total_spent(db: Session) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(UsageEvent.cost_usd), 0))))


def usage_summary(db: Session, user: User) -> dict:
    return {
        "user_spent": round(user_spent(db, user.id), 6),
        "user_limit": user.limit_usd,
        "global_spent": round(total_spent(db), 6),
        "global_budget": global_budget(db),
    }


def check_budget(db: Session, user: User) -> str | None:
    """Returns a reason string when the user may not make another LLM call."""
    s = usage_summary(db, user)
    if s["global_spent"] >= s["global_budget"]:
        return "The app's overall budget has been used up. Ask an admin to raise it."
    if s["user_spent"] >= s["user_limit"]:
        return "You've reached your usage limit. Ask an admin to raise it."
    return None


def record_usage(db: Session, user_id: int, kind: str, model: str, usage: dict | None) -> float:
    usage = usage or {}
    cost = float(usage.get("cost") or 0.0)
    db.add(
        UsageEvent(
            user_id=user_id,
            kind=kind,
            model=model,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cost_usd=cost,
        )
    )
    db.commit()
    return cost
