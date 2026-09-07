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
- **Three gates, all required:** a stage only deepens when the user has (1) lived enough real days at the current stage (`stage_days`, per girl), (2) demonstrably remembered enough of her key points (`stage_kept`, per girl), and (3) been graded `warm` on conduct for that stretch by her own standards (`conduct_note`, per girl). Any single refresh can climb at most one stage; `cold` conduct always costs at least one.
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

### 4. Admin Console
Open `https://<your-app>/admin` and enter `ADMIN_SECRET`. From there you can:
- **Accounts:** search by email / name / id, see tier, messages left, audits, girls & stages, and leave a private admin note.
- **Free time:** comp any account to a paid tier for N days (`/admin/grant-time {email, tier, days}`). They get a fresh allowance immediately; when the time is up they drop back to whatever tier they had before (a used-up trial stays used up). Granting again extends; "End now" cuts it short; a real Stripe tier change cancels the comp.
- **Complaints:** players file them with `POST /complaints {subject, body}` (logged in) and see status/notes at `GET /complaints`. Admin reads the inbox, adds a note and resolves/reopens.

### 5. Ava — Sales / Personal Assistant
A public chat bubble (bottom-right of the site) that sells for you and takes messages while you are away.
- **Knows the products:** plans, prices, extra messages, audits, "suggest a girl", merch — the catalogue lives in `ASSISTANT_CATALOGUE` in `main.py`. Save a persona named `assistant` from the Personas tab to add personality, extra products or a current offer without redeploying.
- **Honest closer:** may talk the product up, never invents prices/discounts/refunds. Asks for the sale and suggests a next step.
- **Intake:** logs **leads** (buying intent), **messages for you** (name / contact / what they want), and **red flags** (underage claims, chargeback threats, fishing for freebies, explicit requests, prompt injection). All land in **Admin → Ava**, where you can read the full conversation and mark items handled.
- **Daily report:** **Admin → Ava → Run report** shows sales by tier, sign-ups, active users, messages, complaints and Ava's inbox, with a plain-English write-up. Set `REPORT_EMAIL_TO` (plus `RESEND_API_KEY`) and it is emailed to you every day at `REPORT_HOUR_UTC`.
- **Any site:** paste `<script src="https://<your-api>/assistant/widget.js"></script>` before `</body>` on any page you own.
- **Model:** Gemini by default; set `DEEPSEEK_API_KEY` to run Ava on DeepSeek instead (the girls always stay on Gemini).

---

## 🛠️ Configuration (Environment Variables)
These must be set in the **Railway "Variables" tab** for the app to function:

| Variable | Description | Source |
| :--- | :--- | :--- |
| `DATABASE_URL` | Connection string for Supabase | Supabase Settings |
| `ADMIN_SECRET` | Password for `/admin` and all entitlement endpoints (required) | You choose it |
| `STRIPE_SECRET_KEY` | API key for subscription billing | Stripe Dashboard |
| `STRIPE_WEBHOOK_SECRET` | Key to verify payment events | Stripe Dashboard |
| `IMAGE_API_KEY` | Key for autonomous photo generation | Image Provider API |
| `SHOPIFY_API_KEY` | Integration for merch store | Shopify Admin |
| `DEEPSEEK_API_KEY` | Optional — runs Ava (sales assistant) on DeepSeek instead of Gemini | DeepSeek Platform |
| `REPORT_EMAIL_TO` | Optional — your email for Ava's daily report (needs `RESEND_API_KEY`) | You choose it |
| `REPORT_HOUR_UTC` | Optional — hour (0-23 UTC) the daily report goes out; default 13 | You choose it |
| `ASSISTANT_SESSION_SECRET` | Optional — signs Ava's visitor session ids; auto-generated and stored in the database if unset | Any long random string |

---

## 📂 File Structure
- `main.py`: The entire backend logic, API endpoints, and trust calculators.
- `requirements.txt`: List of Python dependencies for Railway to install.
- `README.md`: This documentation.

---

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
