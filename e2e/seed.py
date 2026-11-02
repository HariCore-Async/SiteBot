"""Test data for the end-to-end tests: a fictional outdoor shop with real embeddings, a dozen small bots (so lists
paginate), an admin and a member, and the stand-in AI as the only AI provider."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import sqlalchemy as sa
from sqlalchemy import delete, select

from app import providers
from app.db import SessionLocal, engine, init_db
from app.embeddings import embed_passages
from app.embeds import new_key
from app.models import (
    AccessGrant, AIFailure, AIModel, AIProvider, AppSetting, Chat, Chunk, Embed, HiddenSite, Knowledge, Page, Plan,
    ProviderAlert, Site, UsageEvent, User, KNOWLEDGE_GENERATION,
)

ACME_DOMAIN = "acme-outdoor.example"
ACME = {
    "Home": "Acme Outdoor sells hiking boots, tents, sleeping bags and rain jackets for every season. "
            "We have been outfitting hikers and campers since 2009.",
    "Shipping": "Shipping is free on orders over 50 euros within the EU. Orders leave our warehouse in Lyon within two working days. "
                "We also ship to the United Kingdom and Switzerland for a flat fee of 12 euros.",
    "Returns": "You can return unused items within 30 days for a full refund. Start a return from your account page and print the free label.",
    "Contact": "Our shop and office are at 12 Rue des Alpes, 69002 Lyon, France. Call us on +33 4 00 00 00 00 or email help@acme-outdoor.example.",
    "Opening hours": "The Lyon shop is open Monday to Saturday from 9:00 to 19:00. Customer support answers emails within one working day.",
    "Tents": "Our tents range from the ultralight Summit 1 (1.1 kg) to the family-size Basecamp 6. Every tent comes with a five-year warranty.",
    "Boots": "Acme hiking boots are waterproof, resoleable and made in Portugal. Find your size with the fitting guide on each product page.",
    "Privacy": "We only use your data to process orders and never sell it. You can ask us to delete your account at any time.",
}
SEED_PROVIDER = "Local test model"
SEED_MODELS = ("mock-good", "mock-down", "mock-broke")


def fresh_database(url: str, ai_base: str, admin: str, member: str) -> dict:
    """Drops and recreates the e2e database, runs migrations and seeds it. Returns the ids the tests need."""
    u = sa.engine.make_url(url)
    root = sa.create_engine(u.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with root.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{u.database}" WITH (FORCE)'))
        conn.execute(sa.text(f'CREATE DATABASE "{u.database}"'))
    root.dispose()
    engine.dispose()
    init_db()

    with SessionLocal() as db:
        a = User(email=admin, name="Admin Tester", role="admin", email_verified=True)
        m = User(email=member, name="Member Tester", role="member", email_verified=True)
        db.add_all([a, m])
        db.commit()

        texts = list(ACME.values())
        fillers = [(f"Demo Shop {n:02d}", f"demo-shop-{n:02d}.example") for n in range(1, 13)]
        filler_texts = [t for name, _ in fillers for t in (f"{name} sells handmade goods online.", f"{name} ships worldwide within a week.")]
        vectors = embed_passages(texts + filler_texts)

        # Nobody "created" the main bot, so only admins can put it on a website (members can only embed their own).
        acme = _site(db, "Acme Outdoor", ACME_DOMAIN, None, list(ACME.items()), vectors[: len(texts)], f"https://{ACME_DOMAIN}/favicon.ico")
        site_ids = [acme]
        for i, (name, domain) in enumerate(fillers):
            pair = filler_texts[2 * i : 2 * i + 2]
            site_ids.append(_site(db, name, domain, a.id, [(f"{name} page {j}", t) for j, t in enumerate(pair)], vectors[len(texts) + 2 * i : len(texts) + 2 * i + 2]))

        p = AIProvider(name=SEED_PROVIDER, kind="openai_compatible", base_url=ai_base, api_key_enc="", enabled=True)
        db.add(p)
        db.commit()
        models = {}
        for name in SEED_MODELS:
            mod = AIModel(provider_id=p.id, model=name, label=name, input_per_m=1, output_per_m=2, enabled=True)
            db.add(mod)
            db.commit()
            models[name] = mod.id
        ids = {"acme": acme, "sites": site_ids, "admin": a.id, "member": m.id, "provider": p.id, "models": models}
    reset(ids)
    return ids


def _site(db, name: str, domain: str, owner: int | None, pages: list[tuple[str, str]], vectors, favicon: str = "") -> int:
    site = Site(
        domain=domain, name=name, root_url=f"https://{domain}/", favicon=favicon, status="ready",
        message="Ready", generation=1, live_pages=len(pages), pages_found=len(pages), pages_done=len(pages),
        pages_indexed=len(pages), created_by=owner, indexed_at=datetime.now(timezone.utc),
    )
    db.add(site)
    db.commit()
    for (title, text), vec in zip(pages, vectors):
        url = f"https://{domain}/{title.lower().replace(' ', '-')}"
        db.add(Page(site_id=site.id, generation=1, url=url, title=title, status="indexed"))
        db.add(Chunk(site_id=site.id, generation=1, url=url, title=title, content=text, embedding=vec))
    db.commit()
    return site.id


def reset(ids: dict) -> None:
    """Undo whatever earlier tests did: back to the seeded bots, users, AI setup and chats."""
    with SessionLocal() as db:
        for table in (Embed, Plan, ProviderAlert, AIFailure, UsageEvent, AccessGrant, HiddenSite, Chat):
            db.execute(delete(table))
        db.execute(delete(Knowledge))
        db.execute(delete(Chunk).where(Chunk.generation == KNOWLEDGE_GENERATION))
        db.execute(delete(AppSetting))
        db.execute(delete(AIProvider).where(AIProvider.id != ids["provider"]))
        db.execute(delete(AIModel).where(AIModel.provider_id == ids["provider"], AIModel.id.notin_(ids["models"].values())))
        db.execute(sa.update(AIModel).where(AIModel.id.in_(ids["models"].values())).values(enabled=True))
        db.execute(sa.update(AIProvider).where(AIProvider.id == ids["provider"]).values(enabled=True))
        seeded_users = (ids["admin"], ids["member"])
        db.execute(delete(Site).where(Site.id.notin_(ids["sites"])))
        db.execute(delete(User).where(User.id.notin_(seeded_users)))
        db.execute(sa.update(User).where(User.id == ids["admin"]).values(role="admin", token_version=0, limit_usd=5))
        db.execute(sa.update(User).where(User.id == ids["member"]).values(role="member", token_version=0, limit_usd=5))
        db.execute(sa.update(Site).values(answer_model=None, fast_model=None, reindex_schedule="off", suggestions=None, status="ready"))
        db.commit()
        good = f"m:{ids['models']['mock-good']}"
        providers.set_defaults(db, good, good, [])
        # Both testers have a chat with every bot, so their "Your chatbots" lists are long enough to paginate.
        for site_id in db.scalars(select(Site.id)):
            for user in seeded_users:
                db.add(Chat(user_id=user, site_id=site_id))
        db.commit()


def member_embeds(ids: dict) -> None:
    """The member gets a website chatbot on every bot, cycling Pending / Live / Off (skipping the usual approval)."""
    with SessionLocal() as db:
        db.execute(delete(Embed).where(Embed.owner_id == ids["member"]))
        sites = db.scalars(select(Site).order_by(Site.name)).all()
        for i, s in enumerate(sites):
            db.add(Embed(key=new_key(), site_id=s.id, owner_id=ids["member"], status=("pending", "approved", "approved")[i % 3], enabled=(i % 3 != 2)))
        db.commit()


def member_site(ids: dict, name="Member Test Site", domain="member-test-site.example") -> int:
    with SessionLocal() as db:
        s = Site(domain=domain, name=name, root_url=f"https://{domain}/", status="ready", generation=1, created_by=ids["member"])
        db.add(s)
        db.commit()
        return s.id


def token_for(email: str, secret: str) -> str:
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        return jwt.encode({"sub": str(u.id), "tv": u.token_version or 0, "exp": datetime.now(timezone.utc) + timedelta(hours=6)}, secret, algorithm="HS256")


def set_role(user_id: int, role: str) -> None:
    with SessionLocal() as db:
        db.execute(sa.update(User).where(User.id == user_id).values(role=role))
        db.commit()


def write_pages(directory: Path, key: str, backend: str) -> None:
    """A customer's website with the snippet (index.html) and one with its own chat UI via sitebot-client.js."""
    (directory / "index.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>Widget test</title></head>"
        "<body style='font-family:sans-serif;padding:40px;background:#f4f1ea'><h1>A customer's website</h1><p>Uses the SiteBot widget.</p>"
        f"<script src='{backend}/embed.js' data-bot='{key}' async></script></body></html>",
        encoding="utf-8",
    )
    (directory / "client.html").write_text(
        f"""<!doctype html><html><head><meta charset='utf-8'><title>Custom UI test</title></head>
<body><h1>Our own chat UI (no SiteBot widget)</h1><div id='status'>connecting...</div><div id='sugg'></div><div id='log'></div>
<form id='f'><input id='q' size='50' value='Where are you located?'><button>Ask</button></form>
<script src='{backend}/sitebot-client.js'></script>
<script>
const bot = SiteBot.connect({{ key: '{key}' }});
const log = document.getElementById('log'), status = document.getElementById('status');
bot.config().then(c => {{ status.textContent = 'Connected to ' + c.name; document.getElementById('sugg').textContent = 'Suggestions: ' + c.suggestions.join(' | '); }})
  .catch(e => {{ status.textContent = 'ERROR: ' + e.message; }});
document.getElementById('f').onsubmit = async (e) => {{
  e.preventDefault();
  const q = document.getElementById('q').value;
  log.insertAdjacentHTML('beforeend', '<p class=me>You: ' + q + '</p><p class=bot id=cur></p>');
  const cur = document.getElementById('cur'); let tokens = 0;
  try {{
    const r = await bot.ask(q, {{ onToken: (t, all) => {{ tokens++; cur.textContent = 'Bot: ' + all; }} }});
    cur.textContent = 'Bot: ' + r.answer; cur.dataset.tokens = tokens; cur.dataset.sources = r.sources.length; cur.id = 'done';
    await bot.feedback(r.messageId, 'up'); cur.dataset.rated = 'yes';
  }} catch (err) {{ cur.textContent = 'ERROR: ' + err.message; cur.id = 'done'; }}
}};
</script></body></html>""",
        encoding="utf-8",
    )
