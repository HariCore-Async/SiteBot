"""Billing scaffolding (plans), off unless BILLING_ENABLED."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import admin_user
from ..config import settings
from ..db import get_db
from ..models import Plan, User
from ..schemas import (
    PlanIn,
    UserPlanIn,
)

router = APIRouter()


# ---------- Admin: plans (billing scaffolding, off unless BILLING_ENABLED) ----------

def billing_on() -> None:
    if not settings.billing_enabled:
        raise HTTPException(404, "Not found")


def plan_out(p: Plan, db: Session) -> dict:
    users = db.scalar(select(func.count(User.id)).where(User.plan_id == p.id))
    return {"id": p.id, "name": p.name, "price_usd_month": p.price_usd_month, "credit_usd_month": p.credit_usd_month,
            "max_bots": p.max_bots, "max_embeds": p.max_embeds, "active": p.active, "users": users}


@router.get("/api/admin/plans")
def admin_plans(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    billing_on()
    return [plan_out(p, db) for p in db.scalars(select(Plan).order_by(Plan.price_usd_month, Plan.id))]


@router.post("/api/admin/plans")
def admin_add_plan(body: PlanIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    billing_on()
    p = Plan(**body.model_dump())
    db.add(p)
    db.commit()
    return plan_out(p, db)


@router.put("/api/admin/plans/{plan_id}")
def admin_update_plan(plan_id: int, body: PlanIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    billing_on()
    p = db.get(Plan, plan_id)
    if not p:
        raise HTTPException(404, "Plan not found")
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return plan_out(p, db)


@router.delete("/api/admin/plans/{plan_id}")
def admin_delete_plan(plan_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    billing_on()
    p = db.get(Plan, plan_id)
    if not p:
        raise HTTPException(404, "Plan not found")
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.patch("/api/admin/users/{user_id}/plan")
def admin_user_plan(user_id: int, body: UserPlanIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    billing_on()
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if body.plan_id is not None and not db.get(Plan, body.plan_id):
        raise HTTPException(400, "That plan doesn't exist.")
    u.plan_id = body.plan_id
    db.commit()
    return {"id": u.id, "plan_id": u.plan_id}
