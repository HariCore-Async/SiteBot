# Things for Hari to do

Everything here is optional: SiteBot works as before without it. Set environment variables on Railway in the app
service's **Variables** tab (Railway redeploys automatically).

## Security
- [ ] **Replace `SECRET_KEY` with a long random value** (at least 32 characters; 64 is better). The current one is
      26 characters. Everyone is signed out once when it changes. To make one:
      `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- [ ] Your PC's clock was ~3 s behind; Windows Settings > Time & language > Date & time > *Sync now*. (Sign-in now
      tolerates 10 s of difference, so this is no longer required, just good practice.)

## AI providers (Admin console > AI providers), optional
- [ ] **Before adding any provider API key on Railway, set `PROVIDER_KEYS_SECRET`** to a long random string (same command
      as above). Saved keys are encrypted with it. Without it they're encrypted with a key derived from `SECRET_KEY`, so
      if you then change `SECRET_KEY`, saved provider keys stop working and must be re-entered. Easiest order:
      1) set `PROVIDER_KEYS_SECRET`, 2) change `SECRET_KEY`, 3) add provider keys.
- Your existing `OPENROUTER_API_KEY` keeps working as the default; nothing to do unless you want other providers.

## Error monitoring (Sentry), optional
1. Create a free account at sentry.io and two projects: one **Python/FastAPI**, one **Browser JavaScript**.
2. On Railway set:
   - `SENTRY_DSN` = the Python project's DSN (server errors)
   - `SENTRY_BROWSER_DSN` = the JavaScript project's DSN (errors in people's browsers)
   - `SENTRY_ENVIRONMENT` = `production` (default)
   Without these, nothing is sent anywhere.

## Emails (approval notices), optional
- Already supported: set `RESEND_API_KEY` (recommended) or the `SMTP_*` variables, plus `MAIL_FROM`.
- Set `APP_URL` to the app's public address (e.g. `https://sitebot-production-79aa.up.railway.app`) so emails link back.

## OpenRouter credit (urgent)
- [ ] The key in `OPENROUTER_API_KEY` ran out of credit on 28 Oct (OpenRouter answered "402: requires more credits").
      On openrouter.ai → Keys, raise this key's limit or add credit. If Railway uses the same key, its bots can't answer
      until then.

## Backups (recommended)
- [ ] Railway → pgvector service → **Backups** → turn on daily backups.
- [ ] Optional: add `BACKUP_DATABASE_URL` and `BACKUP_PASSPHRASE` as GitHub repository secrets to switch on the daily
      encrypted backup workflow. Details in `docs/BACKUPS.md`.

## Scaling, only if you run more than one copy of the app
- `REDIS_URL` (e.g. Railway's Redis template) makes rate limits shared between copies. Not needed with one replica.
- Indexing and the scheduler still assume one replica; keep Railway at one replica for now.

## Billing (not started; nothing to set)
- [ ] Answer the questions in `docs/BILLING.md` (prices, trial, what happens at a limit, Stripe account). Until then
      leave `BILLING_ENABLED` unset: no plans screen, no charges, nothing visible to users.

## GitHub
- [ ] Delete merged branches you no longer need (each merged PR page has a *Delete branch* button).
- [ ] Optional: in GitHub > Settings > Branches, require the **CI** checks to pass before merging to `main`.
- [ ] `MIGRATION.md` is uncommitted in your local folder: tell Claude whether to commit, move or delete it.
