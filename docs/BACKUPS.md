# Database backups

SiteBot keeps everything in Postgres: accounts, bots and their indexes, website chatbots, conversations, leads, taught
answers and documents, usage. Back it up daily.

## 1. Railway's own backups (easiest)

In Railway, open the **pgvector** (Postgres) service → **Backups** → turn on scheduled backups (daily). Restoring is a
click in the same place. Check your Railway plan's retention.

## 2. A copy you hold yourself (recommended as well)

From any computer with Docker, using the database's **public** connection URL (Railway → pgvector service → Connect →
*Public Network* → `DATABASE_PUBLIC_URL`):

```bash
docker run --rm -e PGURL="$DATABASE_PUBLIC_URL" postgres:16 sh -c 'pg_dump --no-owner --format=custom "$PGURL"' > sitebot-$(date +%F).dump
```

Restore into an empty database (e.g. a new Railway Postgres with the pgvector template):

```bash
docker run --rm -i -e PGURL="$NEW_DATABASE_URL" postgres:16 sh -c 'pg_restore --no-owner --dbname="$PGURL"' < sitebot-2026-10-28.dump
```

## 3. Automatic daily copies on GitHub (optional)

`.github/workflows/backup.yml` dumps the database every day at 03:00 UTC, **encrypts it**, and keeps it as a workflow
artifact for 14 days. It does nothing until you add two repository secrets (GitHub → Settings → Secrets and variables →
Actions):

- `BACKUP_DATABASE_URL`: the public connection URL above
- `BACKUP_PASSPHRASE`: a long random passphrase (keep it somewhere safe: without it the backups can't be opened)

To open a backup: download the artifact, then
`gpg --decrypt --batch --passphrase "$BACKUP_PASSPHRASE" sitebot.dump.gpg > sitebot.dump` and restore as above.

The dumps contain personal data (emails, visitors' conversations), which is why they're encrypted. Delete old copies
you no longer need.
