# Things for Hari to do

Everything here is optional: SiteBot works as before without it. Set environment variables on Railway in the app
service's **Variables** tab (Railway redeploys automatically).

## Security
- [ ] **Replace `SECRET_KEY` with a long random value** (at least 32 characters; 64 is better). The current one is
      26 characters. Everyone is signed out once when it changes. To make one:
      `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- [ ] Your PC's clock was ~3 s behind; Windows Settings > Time & language > Date & time > *Sync now*. (Sign-in now
      tolerates 10 s of difference, so this is no longer required, just good practice.)

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

## GitHub
- [ ] Delete merged branches you no longer need (each merged PR page has a *Delete branch* button).
- [ ] Optional: in GitHub > Settings > Branches, require the **CI** checks to pass before merging to `main`.
- [ ] `MIGRATION.md` is uncommitted in your local folder: tell Claude whether to commit, move or delete it.
