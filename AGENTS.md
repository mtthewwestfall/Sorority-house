# Working in this repo (for any coding agent)

Lockeddoor.ai / Sorority House: an AI companion chat. One FastAPI backend, one static page.

## Layout

- `main.py` — the whole backend: routes, Postgres schema (created on startup with
  `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`), the trust engine,
  model calls, Stripe + Shopify. The file's docstring at the top is the API + env-var reference;
  keep it in sync when you add a route or a variable.
- `web/index.html` — the entire frontend (HTML + CSS + JS in one file). `API_BASE_URL` near
  line 560 is hardcoded to the Railway production URL. Deployed as a static site (Netlify).
  `web/assets/` holds portraits and icons; `web/sw.js` + `web/manifest.webmanifest` make it
  installable (bump `SHELL` in `sw.js` whenever the shell file list changes).
- `README.md` — product/architecture docs. `requirements.txt` — Python deps (Railway installs).
- `telegram/bot.py` — the house on Telegram: a thin client over the public API, one shared
  account and history with the web. Never talks to the DB or admin routes.
- `coder/` — the self-hosted coding agent (`coder/README.md`).

## Concepts you must not break

- **Trust engine / milestones**: a girl's stage climbs at most one step per refresh and only
  when three gates pass (distinct real days talked at this stage, memory kept, warm conduct).
  Days count only when the user actually talked to *that* girl. Never count calendar days.
- **Three model roles**: MOUTH (types the reply), BRAIN (memory digest, a turn behind),
  AUDIT (paid report). Each is an OpenAI-compatible endpoint with a Gemini fallback via
  `GEMINI_API_KEY`. Anything the user reads comes from the MOUTH, never the BRAIN.
- **Tiers gate message limits and doors**; `/admin/*` mutation endpoints refuse with 503 unless
  `ADMIN_SECRET` is set. Do not loosen that.
- **Chat history**: reopening a chat shows the last 8 messages and continues the conversation;
  no reset, no greeting unless the user has never talked to her.
- **Payments**: Stripe for subscriptions, Shopify for picture packs (webhook-gated). Never
  trust client-side claims about purchases.

## Run locally

```
sudo service postgresql start          # any Postgres works
export DATABASE_URL="postgresql://postgres:devinlocal@127.0.0.1:5432/sorority?sslmode=require"
export GEMINI_API_KEY=...  ADMIN_SECRET=devinlocal-admin  PUBLIC_URL=http://localhost:8000
uvicorn main:app --host 0.0.0.0 --port 8000
(cd web && python -m http.server 8001)   # then point API_BASE_URL at :8000 — restore before committing
```

No email provider locally: verify a test signup from `/admin` instead of waiting for a link.

## Checks

Every change must pass these (the coder runs them automatically):

```checks
python -m py_compile main.py
python -c "import html.parser,sys; p=html.parser.HTMLParser(); p.feed(open('web/index.html').read())"
```

Then, for backend changes, start uvicorn and hit the route with curl; for frontend changes,
open `web/index.html` and click through the flow you touched.

## Style

- Small, focused diffs in the style of the surrounding code. Python is plain stdlib +
  FastAPI + psycopg2 + requests; the frontend is vanilla JS — do not add frameworks or build steps.
- New env vars: document them in the `main.py` docstring and the README table.
- New routes: add them to the docstring route list. New DB columns: add via
  `ADD COLUMN IF NOT EXISTS` in the schema block so existing deployments migrate on boot.
- Never commit secrets, and never change `API_BASE_URL` in a commit.
