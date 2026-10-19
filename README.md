# SiteBot

Give it a website link; it reads the site's public pages and becomes a chatbot ("Amazon Chatbot") that answers **only** from that site, with sources.

**Stack:** FastAPI · React (Vite) · Postgres + pgvector · OpenRouter · Playwright · local embeddings (fastembed, `bge-small-en-v1.5`)

## How it works

1. **Ingest:** robots.txt + sitemap + same-domain link crawl (up to `MAX_PAGES`, depth 3). Main text is extracted with trafilatura; pages that come back nearly empty are rendered with headless Chromium (Playwright). Login walls and bot-protection pages are detected and **skipped**, never bypassed.
2. **Index:** text is split into ~1,400-character chunks with overlap and embedded locally (free). It is stored in Postgres with pgvector plus a full-text index.
3. **One index per website:** links are normalized to the host (minus `www.`), so `example.com/about` and `example.com` share one index across all users. Re-indexing builds a new copy and swaps it in, so the bot keeps working meanwhile.
4. **Answer** (anti-hallucination layers):
   - Follow-ups are rewritten into standalone questions using the last few turns.
   - Hybrid retrieval: vector search plus keyword search, fused with reciprocal rank fusion.
   - **Relevance gate:** if the best match is below `MIN_SIMILARITY`, the bot replies "not on this site" without calling the LLM.
   - A strict system prompt with temperature 0. Every fact must cite an excerpt `[n]`; otherwise the model must reply `NOT_FOUND`.
   - Answers without valid citations are rejected in code.
   - A verifier model checks that the answer is supported by the cited excerpts (`VERIFY_ANSWERS`).
   - Sources are shown under every answer.

## Features

- Google sign-in, by invitation. Approving a company email (e.g. `someone@virtualansoftware.com`) admits that whole domain; Gmail, Outlook and other public domains admit only the one address.
- Roles: **admin** (chat + admin panel) and **member** (chat and add sites).
- WhatsApp-style chats: bots in the sidebar, many chats per bot; continue an old chat or start a new one.
- Usage bar with a hover tooltip showing your spend vs. your limit, and all users' spend vs. the global budget. The actual OpenRouter cost of each call is recorded.
- Admin panel: users (role, per-user limit, spend), access approvals, bots (re-index, delete), global budget.
- Dark/light mode, mobile layout.

## Run locally

```bash
docker compose up -d                       # Postgres + pgvector on :5433
python -m venv .venv && .venv/Scripts/pip install -r backend/requirements.txt   # (Linux/mac: .venv/bin/pip)
.venv/Scripts/playwright install chromium
cp backend/.env.example backend/.env       # fill in OPENROUTER_API_KEY, ADMIN_EMAILS; DEV_AUTH=true for local login
cd backend && ../.venv/Scripts/uvicorn app.main:app --reload --port 8000
# in another terminal
cd frontend && npm install && npm run dev  # http://localhost:5173 (proxies /api to :8000)
```

With `DEV_AUTH=true` the login page also lets you sign in by typing an email. Use this locally only.

## Deploy to Railway

1. **Database:** in a Railway project, click **New → Template → "pgvector"** (a Postgres image with the `vector` extension). The default Railway Postgres may not ship pgvector.
2. **App:** click **New → GitHub Repo → this repo**. Railway builds the `Dockerfile` (see `railway.json`).
3. **Variables** on the app service:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | `${{pgvector.DATABASE_URL}}` (reference the DB service; any `postgres://` URL works) |
   | `SECRET_KEY` | a long random string |
   | `ADMIN_EMAILS` | your email(s), comma-separated |
   | `GOOGLE_CLIENT_ID` | from step 4 |
   | `OPENROUTER_API_KEY` | your OpenRouter key |
   | `COOKIE_SECURE` | `true` |
   | `GLOBAL_BUDGET_USD` | `10` (optional; editable in Admin) |

4. **Google OAuth client:** in Google Cloud Console → APIs & Services → Credentials → **Create credentials → OAuth client ID → Web application**.
   - **Authorized JavaScript origins:** `https://<your-app>.up.railway.app` and `http://localhost:5173`.
   - No redirect URI is needed (the app uses Google Identity Services ID tokens).
   - Copy the **Client ID** into `GOOGLE_CLIENT_ID`. Set up the OAuth consent screen if prompted (External, add yourself as a test user while in testing).
5. **Domain:** in Settings → Networking → **Generate Domain**. Sign in with an `ADMIN_EMAILS` account and approve others under **Admin → Access**.

Keep one replica: indexing jobs run inside the web process.

## Configuration

| Env var | Default | Notes |
|---|---|---|
| `OPENROUTER_MODEL` | `anthropic/claude-haiku-5.5` | answering model |
| `OPENROUTER_FAST_MODEL` | `anthropic/claude-haiku-5.5` | rewrite + verification |
| `VERIFY_ANSWERS` | `true` | second-pass grounding check |
| `MIN_SIMILARITY` | `0.55` | refusal gate (on-topic questions scored 0.60–0.73 in testing; off-topic 0.43–0.51) |
| `DEFAULT_USER_LIMIT_USD` | `1` | each new user's limit |
| `GLOBAL_BUDGET_USD` | `10` | initial overall budget |
| `MAX_PAGES` | `100` | pages per site |
| `ENABLE_PLAYWRIGHT` | `true` | JS rendering fallback |

## Limits

- Only public pages are read. Pages behind a login are skipped, and sites with aggressive bot protection (Cloudflare challenges, CAPTCHAs) may index partially or not at all. SiteBot reports these counts rather than working around them.
- Very large sites (e.g. Amazon) are covered only up to `MAX_PAGES` pages.
- Subdomains are separate bots (`docs.example.com` ≠ `example.com`).
