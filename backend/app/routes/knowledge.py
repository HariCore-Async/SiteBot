"""What owners teach a bot by hand (answers and documents), and its re-index schedule."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import knowledge
from ..auth import current_user
from ..db import get_db
from ..knowledge import knowledge_out
from ..models import Embed, Knowledge, Site, User
from ..schemas import (
    AnswerIn,
    DocumentIn,
    ScheduleIn,
    site_out,
)
from .common import ROLE_RANK, embed_role

router = APIRouter()


# ---------- Teaching a bot: the owner's own answers and documents ----------

def own_site(db: Session, site_id: int, user: User, need: str = "editor") -> Site:
    """A bot this user may teach (or, with need="viewer", see what it was taught): its creator, an admin, or a teammate
    on one of its website embeds with at least that role. Bots are shared, so this isn't everyone who chats with it."""
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Bot not found")
    if site.created_by == user.id or user.role == "admin":
        return site
    for e in db.scalars(select(Embed).where(Embed.site_id == site.id)):
        role = embed_role(db, e, user)
        if role and ROLE_RANK[role] >= ROLE_RANK[need]:
            return site
    raise HTTPException(403, "Only the person who added this chatbot, its editors, or an admin can teach it.")


def own_knowledge(db: Session, site: Site, knowledge_id: int) -> Knowledge:
    k = db.get(Knowledge, knowledge_id)
    if not k or k.site_id != site.id:
        raise HTTPException(404, "Not found")
    return k


@router.get("/api/sites/{site_id}/knowledge")
def list_knowledge(site_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = own_site(db, site_id, user, "viewer")
    items = db.scalars(select(Knowledge).where(Knowledge.site_id == site.id).order_by(Knowledge.updated_at.desc())).all()
    return [knowledge_out(k) for k in items]


@router.patch("/api/sites/{site_id}/schedule")
def set_schedule(site_id: int, body: ScheduleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Re-read the website off / daily / weekly. Only changed content is re-embedded, so updates are cheap."""
    site = own_site(db, site_id, user)
    site.reindex_schedule = body.reindex_schedule
    db.commit()
    return site_out(site)


@router.post("/api/sites/{site_id}/knowledge/answers")
def add_answer(site_id: int, body: AnswerIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = own_site(db, site_id, user)
    return knowledge_out(knowledge.save_answer(db, site, body.question, body.answer, user.id))


@router.patch("/api/sites/{site_id}/knowledge/{knowledge_id}")
def edit_answer(site_id: int, knowledge_id: int, body: AnswerIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = own_site(db, site_id, user)
    k = own_knowledge(db, site, knowledge_id)
    if k.kind != "answer":
        raise HTTPException(400, "Documents can't be edited; remove it and upload the new version.")
    return knowledge_out(knowledge.save_answer(db, site, body.question, body.answer, user.id, k))


@router.post("/api/sites/{site_id}/knowledge/documents")
def add_document(site_id: int, body: DocumentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = own_site(db, site_id, user)
    return knowledge_out(knowledge.save_document(db, site, body.filename, body.data_b64, user.id))


@router.delete("/api/sites/{site_id}/knowledge/{knowledge_id}")
def delete_knowledge(site_id: int, knowledge_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    site = own_site(db, site_id, user)
    knowledge.remove(db, site, own_knowledge(db, site, knowledge_id))
    return {"ok": True}
