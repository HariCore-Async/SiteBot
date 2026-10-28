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
- Website embeds: put a bot you created on its own website with one script tag (see below).

## Website embeds

Home → **Add a chatbot to your website** (or the sidebar's **Add to your website**). Pick one of your chatbots, set its colour, position and greeting with a live preview, and copy the snippet:

```html
<script src="https://<your-app>/embed.js" data-bot="pk_..." async></script>
```

- **Approval:** a member's request waits for an admin (**Admin → Embeds**); admins' own are approved at once. Admins can revoke one at any time.
- **Domain lock:** by default a bot only shows on its own domain, `www.` and subdomains, over HTTPS. An admin can switch this off per embed ("Only allow on <domain>", on the embed page or in Admin console → Embeds); then any HTTPS website can use it, still charged to the owner with the same limits. Conversations record which website they came from. The widget page sends a `Content-Security-Policy: frame-ancestors` header for that domain, so browsers refuse to show it anywhere else, and the public API also checks the website it reports.
- **Cost:** visitors' questions are charged to the owner's credits (their normal limit and the global budget still apply), plus a per-embed daily limit (`EMBED_DAILY_CAP_USD`, editable per embed in Admin). When a limit is reached, visitors see a polite "taking a short break" message. Each visitor is limited to 6 questions a minute (60 an hour), and each network address to 20 a minute (300 a day).
- **Visitors** are anonymous: a random id in their browser keeps their conversation. Owners can read their visitors' conversations on the embed page.
- **Managing them:** Home → *Add a chatbot to your website* lists your website chatbots; each has Design (live preview), Install (snippet with platform guides for WordPress, Shopify, Wix, Webflow, Squarespace and Google Tag Manager, a "Test it" page and an installation check, plus the browser and server APIs), Conversations (filters, "couldn't answer", Excel/CSV export) and Usage & settings (spend, chats per day, most-asked and unanswered questions, keys).
- **Knowledge (teach the bot):** the bot's creator (or an admin) can add answers to questions, often straight from the
  "Couldn't answer" list with **Teach the bot**, and upload documents (PDF, Word .docx, text, Markdown; 10 MB each, 50 per
  bot). They're indexed next to the website's pages, cited as "Answer from the … team" or by file name, and kept when
  the website is re-indexed.
- **Human handoff (leads):** when the bot can't answer, the widget offers "Leave your email"; the owner is emailed and
  sees it under **Leads**. `sitebot-client.js` has `bot.contact({ email, name, message })`.
- **Languages:** the bot replies in the visitor's language (searching the website in English behind the scenes), with
  citations as usual. Fixed texts (greeting, "I don't know") are still in English.
- **Emails:** admins get an email for each new request, and owners when theirs is approved or not (with the admin's reason). Uses the same email settings as sign-up codes; without them, nothing is sent and it's only logged. Set `APP_URL` for links in these emails.
- **Your own UI:** instead of the widget, use `sitebot-client.js` in the browser (public key, same domain lock) or the server API at `/api/v1` with a secret `sk_` key from the Embed page. See [docs/API.md](docs/API.md).
- **Styling:** theme (light, dark or auto), font, corner rounding, header title, launcher icon and label, and custom CSS, which applies only inside the widget and has imports and `url()` removed.
- **Testing locally:** a bot's real domain isn't `localhost`, so set `EMBED_DEV_ORIGINS=http://localhost:5500` for the backend, put the snippet (with `src="http://localhost:8000/embed.js"`) in a plain HTML page, serve it with `python -m http.server 5500`, and run `npm run build` so the backend serves the widget. Never set `EMBED_DEV_ORIGINS` on Railway.

## AI providers

Out of the box, answers use OpenRouter with `OPENROUTER_API_KEY` and the `OPENROUTER_MODEL` / `OPENROUTER_FAST_MODEL`
models. Admins can connect other services in **Admin console → AI providers**:

- **Providers:** OpenRouter, OpenAI, Anthropic, Google Gemini, Azure OpenAI, Hugging Face, or any OpenAI-compatible
  server (Ollama, vLLM, LM Studio…) by its base URL. API keys are encrypted at rest (`PROVIDER_KEYS_SECRET`), write-only
  in the UI (only the last 4 characters are shown), and each model has a **Test connection** button.
- **Models:** add model IDs (Azure: deployment names) with their price per 1M input/output tokens, used to work out
  cost when a provider doesn't report it (OpenRouter does).
- **Which model answers:** a default model for answers and one for fast tasks (rewriting follow-ups, checking answers,
  suggestions), plus an ordered **fallback** list tried when a model fails. **Admin console → Bots** can pick a different
  answer model per bot. Streaming falls back only before the first word, so visitors never see two half-answers.
- Usage records the provider and model of every call. Embeddings stay local (fastembed).

## Run locally

```bash
docker compose up -d                       # Postgres + pgvector on :5433
python -m venv .venv && .venv/Scripts/pip install -r backend/requirements.txt   # (Linux/mac: .venv/bin/pip)
.venv/Scripts/playwright install chromium
cp backend/.env.example backend/.env       # fill in OPENROUTER_API_KEY, ADMIN_EMAILS, GOOGLE_CLIENT_ID
cd backend && ../.venv/Scripts/uvicorn app.main:app --reload --port 8000
# in another terminal
cd frontend && npm install && npm run dev  # http://localhost:5173 (proxies /api to :8000)
```

### Tests

```bash
cd backend && ../.venv/Scripts/pip install pytest && ../.venv/Scripts/python -m pytest tests -q
```

The tests use a separate database (`sitebot_test` on the docker compose Postgres, created automatically; override with
`TEST_DATABASE_URL`) and fake the AI and embedding calls, so they need no API keys and download nothing. GitHub Actions
runs them, plus a frontend build, on every pull request (`.github/workflows/ci.yml`).


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
| `EMBED_DAILY_CAP_USD` | `0.5` | default daily spend limit for each website embed |
| `EMBED_DEV_ORIGINS` | *(empty)* | local testing only: extra origins every embed may run on, comma-separated |
| `APP_URL` | *(empty)* | public address, for links in notification emails |
| `SENTRY_DSN` / `SENTRY_BROWSER_DSN` | *(empty)* | error monitoring for the server / browsers; off when empty |

## Limits

- Only public pages are read. Pages behind a login are skipped, and sites with aggressive bot protection (Cloudflare challenges, CAPTCHAs) may index partially or not at all. SiteBot reports these counts rather than working around them.
- Very large sites (e.g. Amazon) are covered only up to `MAX_PAGES` pages.
- Subdomains are separate bots (`docs.example.com` ≠ `example.com`).
