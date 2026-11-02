# End-to-end tests

The real backend and the built frontend in a real browser (Playwright's Chromium), against:

- a throwaway database (`sitebot_e2e`, dropped and recreated on every run; set `E2E_DATABASE_URL` to use another server),
- a stand-in AI (`mock_llm.py`): `mock-good` answers by quoting the top search result, `mock-down` fails with 503 and
  `mock-broke` says it's out of credit (402),
- a fictional outdoor shop ("Acme Outdoor", `seed.py`) indexed with the real embedding model, plus a dozen small bots so
  lists paginate,
- two small test websites on localhost: one the bots are allowed on (`EMBED_DEV_ORIGINS`), one they aren't.

## Run

```bash
docker compose up -d                       # Postgres + pgvector on :5433
cd frontend && npm run build && cd ..      # the backend serves the built frontend
.venv/Scripts/python -m playwright install chromium   # once
.venv/Scripts/python -m pytest e2e -q
```

It uses ports 8100 (backend), 5610 (stand-in AI), 5510 and 5511 (test websites); change them with `E2E_PORT`,
`E2E_AI_PORT`, `E2E_ALLOWED_PORT` and `E2E_BLOCKED_PORT`. The backend's log ends up in `e2e/.output/backend.log`.

## Writing a test

Each module starts from the seeded state (the `env` fixture resets it), then sets up what it needs through the API:

```python
def test_something(env, browser, check):
    A = env.api("admin")                                  # requests session, signed in
    e = A.post(f"{env.B}/api/embeds", json={"site_id": env.site_id}).json()
    env.write_pages(e["key"])                             # the test websites now carry this chatbot
    ctx, page, errors = login(browser, env, "member")     # a signed-in browser
    check("what should be true", condition, details)      # soft check: every failure is reported at the end
```

Not covered here: answers in another language and answer wording, which need a real AI model. They're checked by hand
before releases.
