import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse

from . import scheduler
from .config import settings
from .db import init_db
from .embeddings import warm_up
from .ingest import resume_interrupted
from .routes import admin, billing, chats, embeds, public, sites
from .routes import auth as auth_routes
from .routes import knowledge as knowledge_routes
from .routes.common import STATIC_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if settings.sentry_dsn:
    try:
        import sentry_sdk

        # Errors only, and no visitor data: no request bodies, cookies or IPs.
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.sentry_environment, send_default_pii=False, traces_sample_rate=0)
    except ImportError:
        logging.getLogger(__name__).warning("SENTRY_DSN is set but sentry-sdk isn't installed; error monitoring is off.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    # Load the embedding model in the background so the first question isn't slow.
    threading.Thread(target=warm_up, daemon=True).start()
    scheduler.start()
    resume_interrupted()
    yield


app = FastAPI(title="SiteBot", lifespan=lifespan)


@app.middleware("http")
async def public_api_cors(request: Request, call_next):
    """sitebot-client.js calls the public API straight from a customer's website. Any origin may read the replies
    (no cookies are involved); each route checks that origin against the bot's own domain."""
    origin = request.headers.get("origin")
    if not origin or not request.url.path.startswith("/api/public/"):
        return await call_next(request)
    if request.method == "OPTIONS":
        response = Response(status_code=204)
        response.headers["Access-Control-Allow-Methods"] = "GET, POST"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "600"
    else:
        response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return response
app.include_router(auth_routes.router)
app.include_router(sites.router)
app.include_router(chats.router)
app.include_router(embeds.router)
app.include_router(knowledge_routes.router)
app.include_router(public.router)
app.include_router(admin.router)
app.include_router(billing.router)


# ---------- Frontend ----------


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    target = (STATIC_DIR / path).resolve()
    if path and target.is_file() and STATIC_DIR.resolve() in target.parents:
        return FileResponse(target)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return Response("Frontend not built. Run `npm run build` in frontend/.", media_type="text/plain")
