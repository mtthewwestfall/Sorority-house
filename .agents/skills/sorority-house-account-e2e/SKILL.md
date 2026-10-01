---
name: sorority-house-account-e2e
description: Run local browser account and tier-access E2E checks against Sorority House FastAPI and Postgres without external email or AI providers.
---

## Environment
- Use an isolated local Postgres database; do not reset a shared database.
- For the existing development container `pg`, use `docker start pg` and DSN `postgresql://postgres:pw@localhost:5433/sh?sslmode=disable`.
- From the repo root run `DATABASE_URL='<local DSN>' PORT=8099 ADMIN_SECRET='<local test secret>' RESEND_API_KEY='' GEMINI_API_KEY='' VERIFY_LOG_LINKS=true PUBLIC_URL=http://localhost:8099 VERIFY_REDIRECT='http://localhost:8765/index.html?verified=1' python3 main.py`.
- Serve a temporary copy of `web/index.html` with only `API_BASE_URL` replaced by `http://localhost:8099`: `python3 -m http.server 8765 -d <temporary directory>`. Never commit the local override.
- Refresh that temporary copy after frontend commits.

## Account and tier fixtures
- Create a unique account via the browser with an 8+ character password.
- Without a Resend key, `VERIFY_LOG_LINKS=true` prints `[verify] email -> URL`. Logging counts as email-sent success in this development mode; it does not prove real email delivery.
- Navigate to the exact logged link to verify, then sign in through the frontend.
- Admin tier fixtures use `POST /admin/console/set-tier`, header `X-Admin-Secret`, and JSON `{"email":"<test account>","tier":"senior"}`. This is API-key authentication, not the browser user session.
- Reload after tier changes. Freshman should open Dakota/Zoe, senior all seven configured cards; sign-out should restore the default two.
- A missing Gemini key should produce a visible error from `/chat`, not an auth failure. Inspect only bearer presence and status, never expose the raw session token.
- Missing local portraits can leave broken images on newly unlocked cards; evaluate access behavior separately from asset availability.

## State race verification
For stale-response checks, hold a real authenticated `/state` fetch response in browser instrumentation without modifying its data. Sign out through the UI, release the held response, and verify the nav remains Sign in, only Dakota/Zoe are open, and the allowance remains blank. Clearly label any on-screen instrumentation as test instrumentation.

## Devin Secrets Needed
None for isolated auth/state/error-path testing. Real email delivery needs `RESEND_API_KEY`; successful AI replies need `GEMINI_API_KEY`. These external-provider paths must be explicitly requested and configured.
