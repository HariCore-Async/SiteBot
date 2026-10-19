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
    """What the usage meter shows. Members see only their own spend; admins also see the overall budget and every user."""
    summary = {"user_spent": round(user_spent(db, user.id), 6), "user_limit": user.limit_usd}
    if user.role != "admin":
        return summary
    spent = dict(db.execute(select(UsageEvent.user_id, func.sum(UsageEvent.cost_usd)).group_by(UsageEvent.user_id)).all())
    users = db.scalars(select(User).order_by(User.created_at)).all()
    summary.update(
        global_spent=round(total_spent(db), 6),
        global_budget=global_budget(db),
        users=sorted(
            (
                {"id": u.id, "name": u.name or u.email, "spent": round(float(spent.get(u.id) or 0), 6), "limit": u.limit_usd}
                for u in users
            ),
            key=lambda r: (r["id"] != user.id, -r["spent"]),
        ),
    )
    return summary


def check_budget(db: Session, user: User) -> str | None:
    """Returns a reason string when the user may not make another LLM call."""
    s = {
        "user_spent": user_spent(db, user.id),
        "user_limit": user.limit_usd,
        "global_spent": total_spent(db),
        "global_budget": global_budget(db),
    }
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
