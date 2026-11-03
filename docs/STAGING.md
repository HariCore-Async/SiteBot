# A staging copy on Railway

A second copy of SiteBot with **its own database**, deployed from a `staging` branch. Try changes there before they
reach the live site. Nothing in the code needs to change; this is all set up in Railway.

## One-time setup (about 10 minutes)

1. **Create the environment.** Open the SiteBot project on Railway → the environment menu at the top (it says
   *production*) → **New Environment** → name it `staging` → **Duplicate** production. Railway copies the services and
   their variables. Make sure you're now looking at *staging*.
2. **Give staging its own database.** The *staging* environment gets its own pgvector service, which starts empty.
   Open the app service → **Variables** and check that `DATABASE_URL` is the reference `${{pgvector.DATABASE_URL}}`
   (this environment's database) and **not** a pasted copy of the live database's address. The app creates all tables
   on its first start.
3. **Deploy from the `staging` branch.** App service → **Settings** → **Source** → branch `staging`. (On GitHub, create
   the branch from `main` once: *branches* → *New branch* → `staging`.)
4. **Change these variables** on the staging app service. Everything else can stay as copied:

   | Variable | Staging value | Why |
   |---|---|---|
   | `SECRET_KEY` | a new long random string | staging sessions mustn't work on the live site |
   | `PROVIDER_KEYS_SECRET` | a new long random string | its own encryption for saved AI keys |
   | `APP_URL` | the staging address (step 5) | links in emails |
   | `SENTRY_ENVIRONMENT` | `staging` | tells staging errors apart in Sentry |
   | `GLOBAL_BUDGET_USD` | e.g. `2` | a small AI spending limit |
   | `OPENROUTER_API_KEY` | ideally a separate key with its own small limit | staging can't use up the live credit |
   | `SECRET_KEY_PREVIOUS` | remove it | not needed |

   Make each random string with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
5. **Address.** App service → **Settings** → **Networking** → **Generate Domain**. Add it to the Google sign-in client
   (Google Cloud Console → Credentials → your OAuth client → *Authorized JavaScript origins*) so Google sign-in works there.
6. **Sign in** on the staging address with your `ADMIN_EMAILS` account. Staging starts empty: add a bot to try things.

## Using it

- To try a pull request on staging: on GitHub, merge (or push) its branch into `staging`. Railway deploys it there
  only. When it looks right, merge the pull request into `main` as usual (that deploys to the live site).
- Keep `staging` close to `main`: after a release, update `staging` from `main` (*Compare & pull request* from `main`
  into `staging`, or ask Claude to do it).
- Daily backups aren't needed for staging.

## Costs

Staging runs a second app and database, so the Railway bill grows by roughly that much. Turning on *Serverless* (app
sleeping) in the staging app's settings stops it while nobody is using it.
