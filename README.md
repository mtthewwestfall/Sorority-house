# Greek Hollow

A small town deep in the pines, past the last highway exit. Every resident is an AI character with their own walls — players earn trust over real days. No pay-to-skip.

**Live:** https://lockeddoor.ai

## What lives where

| Piece | Where | Deploy |
|---|---|---|
| `main.py` — backend API, trust engine, chat, audits, avatars, admin console | Railway | Auto-deploys from `main` — just push |
| `web/` — frontend (landing, doors, chat, membership, area pages) | Netlify site `lockeddoor` | Manual — merging to `main` does NOT deploy it |

## Deploying the frontend

The Netlify site is not connected to GitHub. After frontend changes merge to `main`:

```bash
cd web && zip -qr /tmp/site.zip . && curl -sS \
  -H "Authorization: Bearer $NETLIFY_AUTH_TOKEN" \
  -H "Content-Type: application/zip" \
  --data-binary @/tmp/site.zip \
  https://api.netlify.com/api/v1/sites/9dea0cbb-c018-4a04-bcde-1fdd0487ef1f/deploys
```

Then verify: `curl https://lockeddoor.ai` and check the new markup is served.

The backend needs no manual step — pushing `main.py` to `main` redeploys Railway automatically.

## Backend (main.py)

Single-file FastAPI app. The important systems:

- **Trust engine** — every resident has their own trust scale: real days at each stage, remembered key points, and warm conduct. All three gates must pass together to deepen a stage.
- **Personas as data** — residents live in the `personas` table, editable from the admin console (`/admin` + `ADMIN_SECRET`). No redeploy to add or rewrite a character.
- **Psychological audits** — paid coaching reports (`POST /audit`), gender-neutral, honest to the raw chat record. Neighbor tier gets 2 free per month.
- **Pictures** — visitors get 0 free pictures (signup ploy); paid tiers start with 10 (`PICTURE_FREE_START`), then $0.99 per 5-pack via Shopify (`POST /image`).
- **Player avatars** — users describe a character, get a graphic-novel-style avatar. Private to the account, profile-only, never a chat character. Monthly contest entries via `POST /avatar/contest`; winners are copied into the game through the admin console only.
- **Tiers** — Visitor (free), Community Member, Resident, Neighbor. Subscriptions via Stripe Payment Links.
- **KEYHOLE** — her room on cam (`/keyhole/*`), pay per session, no subscription. Free preview 10 min once; packs Quick $2.99 (15 min / ~35 video replies / 100 texts), Standard $5.99 (30 / ~70 / 200), Extended $9.99 (45 / ~100 / 300), 1 Hour $12.99 (60 / ~135 / 400). A session ends when minutes or video replies run out; unused texts carry over. Video replies are clips from the tagged media library (`/media/character/...`). Packs are one-time Stripe Payment Links (`KEYHOLE_LINK_*`) credited by the webhook via price id (`KEYHOLE_PRICE_*`) or `metadata.keyhole_pack`; `POST /admin/grant-keyhole` credits by hand. Text-only pack exists but is hidden until priced.

Key environment variables (Railway): `DATABASE_URL`, `ADMIN_SECRET`, `GEMINI_API_KEY`, `STRIPE_WEBHOOK_SECRET`, `SHOPIFY_WEBHOOK_SECRET`, `MAIL_FROM`, `KEYHOLE_PRICE_{QUICK,STANDARD,EXTENDED,HOUR,TEXTS}`, `KEYHOLE_LINK_{QUICK,STANDARD,EXTENDED,HOUR,TEXTS}`.

## Frontend (web/)

- `index.html` — landing, doors, chat, membership, merch. The door cards are a fallback; `GET /roster` replaces them with live data.
- `areas/` — the four corners of town: Westfall, Pellegrin, Umina, Muse.
- `assets/` — portraits, area backgrounds, hangout shots, icons.
- `sw.js` + `manifest.webmanifest` — makes the site installable. Bump `SHELL` in `sw.js` when the shell changes.

## Standing rules

- **Never state how many residents the town has.** A fixed count breaks the moment someone new arrives.
- The word "sorority" never appears. The college backstory stays in the past tense only.
- No active romantic relationships between residents. Friendships are the star.
- Audit scores affect nothing. There is no leaderboard.
- A resident's private vulnerabilities are never leaked by another resident.
