"""Admin console: users, access, settings, budget, website chatbot reviews, AI providers and bots."""

import re
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import accounts, auth, health, llm, providers
from ..auth import admin_user, email_domain, is_org_domain
from ..config import settings
from ..db import get_db
from ..embeds import (
    admin_embed_out,
    clean_origin,
    test_origin_active,
)
from ..ingest import is_running, start_ingestion
from ..models import AccessGrant, AIModel, AIProvider, Embed, Site, UsageEvent, User, utcnow
from ..providers import encrypt_key, provider_out
from ..schemas import (
    AdminSettingsIn,
    AIDefaults,
    AITest,
    BudgetIn,
    EmbedReview,
    GrantIn,
    ModelIn,
    ModelUpdate,
    ProviderIn,
    ProviderUpdate,
    ReindexIn,
    SiteModels,
    TestOriginIn,
    UserUpdate,
    site_out,
    user_out,
)
from ..usage import global_budget, set_global_budget
from .common import app_link

router = APIRouter()


# ---------- Admin ----------

@router.get("/api/admin/users")
def admin_users(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    spent = dict(db.execute(select(UsageEvent.user_id, func.sum(UsageEvent.cost_usd)).group_by(UsageEvent.user_id)).all())
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return [
        {**user_out(u), "spent_usd": round(float(spent.get(u.id) or 0), 6),
         "locked_admin": u.email in settings.admin_email_set, "last_seen_at": u.last_seen_at.isoformat()}
        for u in users
    ]


@router.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, body: UserUpdate, me: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if body.limit_usd is not None:
        u.limit_usd = body.limit_usd
    if body.role is not None:
        if body.role == "member" and u.email in settings.admin_email_set:
            raise HTTPException(400, "This is a permanent admin and can't be demoted.")
        u.role = body.role
    db.commit()
    return user_out(u)


@router.get("/api/admin/access")
def admin_access(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    # Admins from ADMIN_EMAILS are listed once, as admins, even if they were also granted access by email.
    grants = [
        g for g in db.scalars(select(AccessGrant).order_by(AccessGrant.created_at.desc()))
        if g.email.lower() not in settings.admin_email_set
    ]
    return {
        "grants": [
            {"id": g.id, "email": g.email, "created_by": g.created_by, "created_at": g.created_at.isoformat(),
             "domain_access": email_domain(g.email) if is_org_domain(email_domain(g.email)) else None}
            for g in grants
        ],
        "admin_emails": sorted(settings.admin_email_set),
    }


@router.post("/api/admin/access")
def admin_grant(body: GrantIn, me: User = Depends(admin_user), db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Enter a valid email address.")
    if email in settings.admin_email_set:
        raise HTTPException(400, "That email is already an admin, so it already has access.")
    if not db.scalar(select(AccessGrant).where(AccessGrant.email == email)):
        db.add(AccessGrant(email=email, created_by=me.email))
        db.commit()
    return {"ok": True}


@router.delete("/api/admin/access/{grant_id}")
def admin_revoke(grant_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    db.execute(delete(AccessGrant).where(AccessGrant.id == grant_id))
    db.commit()
    return {"ok": True}


@router.get("/api/admin/settings")
def admin_get_settings(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return {"require_approval": auth.approval_required(db)}


@router.put("/api/admin/settings")
def admin_set_settings(body: AdminSettingsIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    auth.set_approval_required(db, body.require_approval)
    return {"require_approval": body.require_approval}


@router.get("/api/admin/budget")
def admin_get_budget(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return {"global_budget_usd": global_budget(db)}


@router.put("/api/admin/budget")
def admin_set_budget(body: BudgetIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    set_global_budget(db, body.global_budget_usd)
    return {"global_budget_usd": body.global_budget_usd}


@router.post("/api/admin/users/{user_id}/sign-out")
def admin_sign_out_user(user_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Ends every session of that user (they can sign in again unless their access is also removed)."""
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    auth.sign_out_everywhere(db, u)
    return {"ok": True}


@router.get("/api/admin/test-origins")
def admin_test_origins(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Every chatbot's test websites, waiting ones first."""
    rows = []
    for e in db.scalars(select(Embed).where(Embed.test_origins.isnot(None))):
        site, owner = db.get(Site, e.site_id), db.get(User, e.owner_id)
        for t in e.test_origins or []:
            rows.append({
                **t, "status": t.get("status", "approved"), "active": test_origin_active(t), "embed_id": e.id,
                "bot": site.name if site else "", "owner": owner.email if owner else "",
            })
    return sorted(rows, key=lambda r: (r["status"] != "pending", r["bot"], r["origin"]))


def admin_embed_entry(db: Session, embed_id: int, origin: str) -> tuple[Embed, str]:
    e = db.get(Embed, embed_id)
    origin = clean_origin(origin)
    if not e or not any(t["origin"] == origin for t in e.test_origins or []):
        raise HTTPException(404, "That test website isn't on the list.")
    return e, origin


@router.post("/api/admin/embeds/{embed_id}/test-origins/approve")
def admin_approve_test_origin(embed_id: int, body: TestOriginIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    e, origin = admin_embed_entry(db, embed_id, body.origin)
    e.test_origins = [{**t, "status": "approved"} if t["origin"] == origin else t for t in e.test_origins]
    db.commit()
    return {"ok": True}


@router.delete("/api/admin/embeds/{embed_id}/test-origins")
def admin_remove_test_origin(embed_id: int, origin: str, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    e, origin = admin_embed_entry(db, embed_id, origin)
    e.test_origins = [t for t in e.test_origins if t["origin"] != origin]
    db.commit()
    return {"ok": True}


@router.get("/api/admin/embeds")
def admin_embeds(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    embeds = db.scalars(select(Embed).order_by(Embed.created_at.desc())).all()
    order = {"pending": 0, "approved": 1, "rejected": 2}
    embeds = sorted(embeds, key=lambda e: order.get(e.status, 3))
    return [admin_embed_out(db, e, db.get(Site, e.site_id), db.get(User, e.owner_id)) for e in embeds]


@router.patch("/api/admin/embeds/{embed_id}")
def admin_review_embed(embed_id: int, body: EmbedReview, me: User = Depends(admin_user), db: Session = Depends(get_db)):
    e = db.get(Embed, embed_id)
    if not e:
        raise HTTPException(404, "Embed not found")
    decided = body.status is not None and body.status != e.status
    if decided:
        e.status, e.reviewed_by, e.reviewed_at = body.status, me.email, utcnow()
        e.review_note = (body.note or "").strip() if body.status == "rejected" else ""
    if body.daily_cap_usd is not None:
        e.daily_cap_usd = body.daily_cap_usd
    if body.restrict_to_domain is not None:
        e.restrict_to_domain = body.restrict_to_domain
    db.commit()
    site, owner = db.get(Site, e.site_id), db.get(User, e.owner_id)
    if decided and e.status in ("approved", "rejected") and owner.id != me.id:
        if e.status == "approved":
            subject = f"SiteBot: {site.name} Chatbot is approved for your website"
            text = (
                f"Good news: {site.name} Chatbot is approved, so it now answers visitors on {site.domain}.\n\n"
                "If you haven't yet, paste its snippet into your website: Add a chatbot to your website > Install."
            )
        else:
            subject = f"SiteBot: {site.name} Chatbot wasn't approved"
            text = f"An admin didn't approve putting {site.name} Chatbot on {site.domain}."
            text += f"\n\nReason: {e.review_note}" if e.review_note else ""
            text += "\n\nYou can change things and ask again from the chatbot's page."
        accounts.notify([owner.email], subject, text + app_link(f"#/website/{e.id}"))
    return admin_embed_out(db, e, site, owner)


# ---------- Admin: AI providers and models ----------

def ai_overview(db: Session) -> dict:
    providers_list = db.scalars(select(AIProvider).order_by(AIProvider.created_at)).all()
    models = db.scalars(select(AIModel).order_by(AIModel.id)).all()
    return {
        "providers": [provider_out(p, [m for m in models if m.provider_id == p.id]) for p in providers_list],
        "env": {"available": providers.env_available(), "models": providers.env_models()},
        "defaults": providers.defaults(db),
        "kinds": [{"kind": k, **v} for k, v in providers.KINDS.items()],
    }


def check_base_url(kind: str, base_url: str) -> str:
    base_url = base_url.strip().rstrip("/")
    if base_url and not re.match(r"^https?://[^\s]+$", base_url):
        raise HTTPException(400, "The base URL must start with http:// or https://.")
    if kind in ("azure", "openai_compatible") and not base_url:
        raise HTTPException(400, "This kind of provider needs its base URL.")
    return base_url


@router.get("/api/admin/ai/health")
def admin_ai_health(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return health.summary(db)


@router.post("/api/admin/ai/alerts/{alert_id}/dismiss")
def admin_dismiss_alert(alert_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if not health.dismiss(db, alert_id):
        raise HTTPException(404, "Alert not found")
    return {"ok": True}


@router.get("/api/admin/ai")
def admin_ai(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return ai_overview(db)


@router.post("/api/admin/ai/providers")
def admin_add_provider(body: ProviderIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    p = AIProvider(name=body.name.strip(), kind=body.kind, base_url=check_base_url(body.kind, body.base_url),
                   api_key_enc=encrypt_key(body.api_key.strip()), api_version=body.api_version.strip(), enabled=True)
    db.add(p)
    db.commit()
    return ai_overview(db)


@router.patch("/api/admin/ai/providers/{provider_id}")
def admin_update_provider(provider_id: int, body: ProviderUpdate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    p = db.get(AIProvider, provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    if body.name is not None:
        p.name = body.name.strip()
    if body.base_url is not None:
        p.base_url = check_base_url(p.kind, body.base_url)
    if body.api_key is not None:
        p.api_key_enc = encrypt_key(body.api_key.strip())
    if body.api_version is not None:
        p.api_version = body.api_version.strip()
    if body.enabled is not None:
        p.enabled = body.enabled
    db.commit()
    return ai_overview(db)


@router.delete("/api/admin/ai/providers/{provider_id}")
def admin_delete_provider(provider_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    p = db.get(AIProvider, provider_id)
    if not p:
        raise HTTPException(404, "Provider not found")
    refs = [f"m:{m.id}" for m in db.scalars(select(AIModel).where(AIModel.provider_id == p.id))]
    db.delete(p)
    db.commit()
    for ref in refs:
        providers.clear_references(db, ref)
    return ai_overview(db)


@router.post("/api/admin/ai/providers/{provider_id}/models")
def admin_add_model(provider_id: int, body: ModelIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if not db.get(AIProvider, provider_id):
        raise HTTPException(404, "Provider not found")
    db.add(AIModel(provider_id=provider_id, model=body.model.strip(), label=body.label.strip(),
                   input_per_m=body.input_per_m, output_per_m=body.output_per_m, enabled=True))
    db.commit()
    return ai_overview(db)


@router.patch("/api/admin/ai/models/{model_id}")
def admin_update_model(model_id: int, body: ModelUpdate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    m = db.get(AIModel, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    for field in ("label", "input_per_m", "output_per_m", "enabled"):
        value = getattr(body, field)
        if value is not None:
            setattr(m, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    return ai_overview(db)


@router.delete("/api/admin/ai/models/{model_id}")
def admin_delete_model(model_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    m = db.get(AIModel, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    db.delete(m)
    db.commit()
    providers.clear_references(db, f"m:{model_id}")
    return ai_overview(db)


@router.put("/api/admin/ai/defaults")
def admin_ai_defaults(body: AIDefaults, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    for ref in [body.answer, body.fast, *body.fallbacks]:
        if not providers.target_for(db, ref):
            raise HTTPException(400, f"{ref} isn't usable: it's missing, turned off, or its provider has no API key.")
    providers.set_defaults(db, body.answer, body.fast, body.fallbacks)
    return ai_overview(db)


@router.post("/api/admin/ai/test")
def admin_ai_test(body: AITest, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    """Sends a tiny prompt to one model (no fallback) and reports whether it answered."""
    t = providers.target_for(db, body.ref)
    if not t:
        return {"ok": False, "error": "This model isn't usable: it's turned off, or its provider has no API key."}
    started = time.monotonic()
    try:
        text, usage = llm.complete_with(t, [{"role": "user", "content": "Reply with the single word OK."}], max_tokens=10)
    except llm.LLMError as e:
        return {"ok": False, "error": str(e)[:500]}
    return {"ok": True, "reply": text.strip()[:100], "ms": round((time.monotonic() - started) * 1000), "cost": usage["cost"]}


@router.patch("/api/admin/sites/{site_id}/models")
def admin_site_models(site_id: int, body: SiteModels, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    for field in ("answer_model", "fast_model"):
        ref = getattr(body, field)
        if ref and not providers.target_for(db, ref):
            raise HTTPException(400, f"{ref} isn't usable: it's missing, turned off, or its provider has no API key.")
        setattr(site, field, ref or None)
    db.commit()
    return site_out(site)


@router.post("/api/admin/sites/{site_id}/reindex")
def admin_reindex(
    site_id: int, body: ReindexIn | None = None, _: User = Depends(admin_user), db: Session = Depends(get_db)
):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    if is_running(site_id):
        raise HTTPException(409, "This bot is already being indexed.")
    if body and body.include_pdfs is not None:
        site.include_pdfs = body.include_pdfs
    site.status = "queued"
    site.message = "Updating in the background…"
    db.commit()
    start_ingestion(site_id)
    return site_out(site)


@router.delete("/api/admin/sites/{site_id}")
def admin_delete_site(site_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    if is_running(site_id):
        raise HTTPException(409, "Wait for indexing to finish before deleting this bot.")
    db.delete(site)
    db.commit()
    return {"ok": True}
