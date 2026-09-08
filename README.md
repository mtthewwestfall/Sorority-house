# Sorority-house

# 🏛️ Sorority AI Empire: Backend Engine

## 📌 Project Overview
This is the core intelligence layer for a high-fidelity AI sorority experience. It manages 28 distinct female personalities, a dynamic trust-progression system, autonomous image generation, and a dual-payment architecture (Stripe + Shopify).

**Architecture:** FastAPI (Python) 
**Database:** PostgreSQL (via Supabase)
**Deployment:** Railway.app
**Payments:** Stripe (Subscriptions) & Shopify (Merchandise)

---

## ⚙️ System Core Logic

### 1. The Trust Engine (Psychological Progression)
The system doesn't just track messages; it tracks *emotional depth*.
- **Stages:** Stranger $\rightarrow$ Acquaintance $\rightarrow$ Friend $\rightarrow$ Close Friend $\rightarrow$ Intimate $\rightarrow$ Devoted.
- **Three gates, all required:** a stage only deepens when the user has (1) actually talked to her on enough distinct real days at the current stage (`stage_days`, per girl; days of silence don't count), (2) demonstrably remembered enough of her key points (`stage_kept`, per girl), and (3) been graded `warm` on conduct for that stretch by her own standards (`conduct_note`, per girl). Any single refresh can climb at most one stage; `cold` conduct always costs at least one.
- **Memory Probes:** The AI occasionally tests the user on past conversations. Correct recall = Trust $\uparrow$, Forgetting = Trust $\downarrow$.

### 2. Persona Engine (The 28 Girls)
Each girl has a "Development Bible" containing:
- **Core Wound:** The psychological trauma that defines her.
- **The Moat:** The emotional barrier she uses to keep people out.
- **Boaster Trap:** Specific triggers that cause her to lose respect for the user (e.g., arrogance, fake wealth).
- **Visual DNA:** Specific prompts and ID references for consistent image generation.

### 3. The Payment & Trial Flow
- **Accounts:** Every player signs up with email + password (`/auth/signup`, `/auth/login`) and sends the returned token as `Authorization: Bearer <token>`. The free trial and all subscriptions are bound to that account, so allowances cannot be reset by clearing the browser or inventing a new id. Stripe webhooks link subscriptions via `/admin/set-tier {email, tier}`.
- **Free Trial:** One per account. Ends at message 25 and never refills.
- **The Promise:** At message 23, the AI promises a photo.
- **The Paywall:** Triggered at message 25.
- **The Delivery:** Once subscribed, the promised photo is delivered at message 10 of the paid tier.

### 4. The Mouth and the Brain (how a reply is produced)
Two model roles, deliberately unequal in speed, so replies land instantly without thinning her memory:
- **The mouth** (`POST /chat/stream`) is the streaming chat call, paced **server-side** to a human typing rate (`CHAT_CPS`). Generation is throttled to the typing, not buffered ahead of it: the emitter owns the clock and the generator blocks once the untyped backlog hits `CHAT_LEAD_CHARS`. That is what stops her from getting a growing head start she can never give back.
- **The brain** is the Layer-2 memory refresh (rolling summary + milestone re-grade + conduct grade). It runs in a worker thread **one turn behind**: fired on turn N over turn N-1, committing state the mouth reads on turn N+1. A reply never waits on it, and one relationship only ever has one brain digesting at a time.
- **Tail revision** (`TAIL_REVISION`, on by default): typed characters are immutable, the rest is not. If the brain lands mid-reply and moves the stage, the untyped remainder is dropped and regenerated from the new memory, continuing the sentence she was on. The user never sees a rewrite - only the part she hadn't typed yet changes.
- **What was seen is what is remembered:** the transcript logs the text that actually reached the screen, so a dropped connection cannot leave her remembering a paragraph the user never read.
- `POST /chat` still returns whole replies for any client that doesn't stream, and the web frontend falls back to it automatically.
- **Each role picks its own model.** The mouth, the brain and the auditor are configured separately (`MOUTH_*`, `BRAIN_*`, `AUDIT_*`), and any OpenAI-compatible endpoint works: an open-weights voice you serve yourself (vLLM / Ollama / llama.cpp running Mistral or Llama), Mistral La Plateforme, DeepSeek, Together, Groq. A role with no endpoint set stays on Gemini (`GEMINI_API_KEY`), so nothing breaks while you move one role at a time. `GET /health` reports what each role is running on.

### 5. Admin Console
Open `https://<your-app>/admin` and enter `ADMIN_SECRET`. From there you can:
- **Accounts:** search by email / name / id, see tier, messages left, audits, girls & stages, and leave a private admin note.
- **Free time:** comp any account to a paid tier for N days (`/admin/grant-time {email, tier, days}`). They get a fresh allowance immediately; when the time is up they drop back to whatever tier they had before (a used-up trial stays used up). Granting again extends; "End now" cuts it short; a real Stripe tier change cancels the comp.
- **Complaints:** players file them with `POST /complaints {subject, body}` (logged in) and see status/notes at `GET /complaints`. Admin reads the inbox, adds a note and resolves/reopens.
- **Doors:** opened by progression, not by tier. The first pair in roster order (Dakota and Zoe) is open from the start; each next pair unlocks once the player reaches stage M4 with either girl of the pair directly before it. A girl's `min_tier` is only a paywall on top of that — by default everyone is on Freshman except Veronica (Senior).
- **Roster:** the girls are data, not code. Add a sister, rewrite her character doc, change her door text or art, move her in the order, or change which paid tier she needs — all from the Roster tab, live on the next page load, no deploy (`POST /admin/console/girl`). Retiring her (`POST /admin/console/girl/{girl}/active?active=false`) takes her off the doors and keeps every message, so bringing her back resumes each conversation where it stopped. `GET /roster` is what the frontend renders the doors from; the cards in `web/index.html` are only the fallback for when the API can't be reached.
- **Difficulty:** each sister has a difficulty (`easy` · `normal` · `hard` · `ice`) on the same Roster form. It multiplies the real-day floor of every trust stage (×0.5, ×1, ×1.75, ×3, never below one day) — so an ice queen takes weeks of showing up where an easy sister takes days. It does not touch the rest of the engine: conduct still has to be warm and she still has to be remembered before she opens up, and the number is never shown to the player.
- **Backup:** "Download backup" (`GET /admin/console/export`) saves the whole roster — every door and every character doc — as JSON. Roster only: no accounts, tokens or keys. Keep a copy; it is enough to rebuild the house on an empty database.

---

## 🛠️ Configuration (Environment Variables)
These must be set in the **Railway "Variables" tab** for the app to function:

| Variable | Description | Source |
| :--- | :--- | :--- |
| `DATABASE_URL` | Connection string for Supabase | Supabase Settings |
| `ADMIN_SECRET` | Password for `/admin` and all entitlement endpoints (required) | You choose it |
| `STRIPE_WEBHOOK_SECRET` | Signing secret of the `/webhooks/stripe` endpoint (`whsec_…`); `invoice.paid` upgrades the account remembered for the customer (else the one with the customer's email), `checkout.session.completed` with a `client_reference_id` upgrades that user (Telegram purchases), a deleted/unpaid subscription drops it to freshman | Stripe Dashboard → Webhooks |
| `STRIPE_API_KEY` | Restricted key (Customers: read, Subscriptions: read). Required for purchases started from the Telegram bot (the tier is read from the subscription); also matches cancellations of customers that never paid through this webhook | Stripe Dashboard → API keys |
| `TELEGRAM_BOT_SECRET` | Shared secret between the backend and `telegram/bot.py`; `/auth/telegram*` refuse until it is set. Same value on both services | You choose it (long random string) |
| `STRIPE_PRICE_SOPHOMORE` / `STRIPE_PRICE_JUNIOR` / `STRIPE_PRICE_SENIOR` | Price ids behind the three Payment Links (defaults are the live ones) | Stripe Dashboard → Products |
| `IMAGE_API_KEY` | Key for autonomous photo generation | Image Provider API |
| `SHOPIFY_API_KEY` | Integration for merch store | Shopify Admin |
| `GEMINI_API_KEY` / `CHAT_MODEL` | Gemini fallback for any role without its own endpoint (default model `gemini-3.1-flash-lite`) | Google AI Studio |
| `MOUTH_BASE_URL` / `MOUTH_MODEL` / `MOUTH_API_KEY` | The voice that types. e.g. `https://api.mistral.ai/v1` + `mistral-small-latest`, or your own vLLM box | Mistral / your server |
| `BRAIN_BASE_URL` / `BRAIN_MODEL` / `BRAIN_API_KEY` | The memory digest a turn behind. e.g. `https://api.deepseek.com/v1` + `deepseek-v4-flash` (about 3 s a digest; `deepseek-v4-pro` thinks for minutes) | DeepSeek |
| `AUDIT_BASE_URL` / `AUDIT_MODEL` / `AUDIT_API_KEY` | Optional own endpoint for the paid audit; otherwise audits ride the mouth (same voice as chat) | You choose it |
| `MODEL_TIMEOUT_S` | Per-call timeout for every provider (default `120`) | You choose it |
| `BRAIN_MAX_TOKENS` | Token budget for the memory digest (default `4000`); reasoning models bill their thinking against it | You choose it |
| `CHAT_CPS` | Her typing speed on `/chat/stream`, characters per second (default `14`) | You choose it |
| `CHAT_LEAD_CHARS` | How far generation may run ahead of the screen (default `240`) | You choose it |
| `TAIL_REVISION` | `true` (default) lets a mid-reply brain rewrite only the untyped tail | You choose it |

---

## 📂 File Structure
- `main.py`: The entire backend logic, API endpoints, and trust calculators.
- `requirements.txt`: List of Python dependencies for Railway to install.
- `README.md`: This documentation.
- `web/index.html`: The whole front end — doors, chat, membership, merch.
- `web/manifest.webmanifest`, `web/sw.js`: What makes the site installable (see below).
- `web/assets/`: Roster art and the app icons.
- `telegram/bot.py`: The house on Telegram — a thin client over the same API (see below).

---

## 📱 The app
The site is installable — there is no separate app to build and no store involved. Chrome and Edge offer it, and on iPhone the Share sheet's "Add to Home Screen" does it; either way the house opens full screen from the home screen with its own icon, signed in as the same account. A one-time bar invites the install and "Install the app" in the footer brings it back if it was dismissed; a copy that is already installed is never asked.

`web/sw.js` caches **only the shipped shell** (the page and the icons) so an installed copy still opens with no signal, and never the API — a girl, a message or a roster change is always live, never a stale cached copy. The page itself is fetched from the network first, so a deploy lands on the next open. Change anything in the shell list and bump `SHELL` in `web/sw.js` (`house-shell-v1` → `-v2`) or installed copies keep serving the old files.

Requirements: the front end must be served over **HTTPS** (a service worker will not register otherwise, `localhost` excepted), and `manifest.webmanifest`, `sw.js` and `index.html` must sit on the same origin, which they do when `web/` is deployed as-is.

## 💬 Telegram
`telegram/bot.py` is the house as a Telegram bot: the same girls, trust clock and message allowance, because it only talks to the backend's public API (`/auth/telegram`, `/roster`, `/state`, `/history`, `/chat`). The Telegram id is the account: the first message opens one (no email, no password), `/girls` shows the doors that are open as buttons, and from then on plain messages go to the girl they picked. Someone who already has a website account can `/login <email> <password>` once to point their Telegram at it (one history, one allowance on both). Per-chat session tokens live in `telegram/sessions.json` next to the bot (git-ignored; if it is lost the bot just reopens sessions from the Telegram id).

Run it as a second Railway service from this repo: start command `python telegram/bot.py`, variables `TELEGRAM_BOT_TOKEN` (a new bot from @BotFather), `PUBLIC_URL` (the backend URL) and `TELEGRAM_BOT_SECRET` (the same value as on the backend). Optional: `SITE_URL` (default `https://lockeddoor.ai`, used for portraits and the `/menu` website + "Get the app" buttons) and `PAY_LINK_SOPHOMORE` / `PAY_LINK_JUNIOR` / `PAY_LINK_SENIOR` (the Stripe Payment Links behind `/upgrade`; the live ones are the defaults). Payments never happen inside Telegram — the `/upgrade` buttons open the Stripe Payment Links with `client_reference_id=<user_id>`, the backend's webhook upgrades that account from `checkout.session.completed` (needs `STRIPE_API_KEY`) and the bot sees the new tier at once. It polls Telegram, so no public port. Passwords typed into `/login` stay in that Telegram chat's history — the bot refuses them in groups, and users can delete the message afterwards.

## 🚀 Deployment Steps
1. Push `main.py` and `requirements.txt` to GitHub.
2. Connect GitHub Repo to **Railway.app**.
3. Add the **Environment Variables** listed above in Railway.
4. Deploy and copy the **Live URL** (provided by Railway) to connect to the Frontend HTML.

---

## 📝 Admin Notes: Current Active Personas
- **Brittany:** High energy, boaster trap active.
- **Zoe:** Intellectual shield, requires depth to unlock.
- **Willow:** Quiet observer, plant shop aesthetic.
- **Dakota:** Quiet strength, authenticity filter.
- **Sasha:** Strategic power, rewards respectful friction.
- **Piper:** Emotional catalyst, avoidant flight response.
