# Review Guidelines

## Hard rules (do not violate)

### 1. Never run things that aren't hooked up
A client (the web app `web/index.html` or the Telegram bot `telegram/bot.py`) must
never call, spend against, or expose a backend capability that isn't wired
end-to-end. If a feature is only half-connected, do not ship the trigger for it.

- Every metered/paid action must deliver its full result. Do not truncate or drop
  output the user already paid for. Example: audit reports must be sent in full
  (see the resident audit at `main.py:4446-4586`), not sliced to fit a message
  limit — split across messages instead.
- Do not add a command/button that hits an endpoint the client can't fully support
  (e.g. picking a subject, handling the response shape, and surfacing errors).

### 2. Characters (the 17 residents) are frozen
The resident/character audits are considered final and correct. Do not modify them.

- Off-limits: `AUDIT_INSTRUCTION` (`main.py:425`) and the resident `audit()`
  endpoint (`main.py:4446-4586`), plus anything they depend on.
- Only companion code may change: `companion_audit()` (`main.py:3908-3952`) and the
  companion client paths.

### 3. Never let characters and companions bleed into each other
Characters and companions must stay on strictly separate code paths, prompts, and
data. They are distinct at every layer:

- Characters: `POST /audit` reads `audit`; prompt `AUDIT_INSTRUCTION` (`main.py:425`).
- Companions: `POST /companions/{id}/audit` reads `report`; inline prompt
  (`main.py:3934-3945`); isolated `companions` table (`main.py:850-883`).

Never reuse the character `/audit` call for a companion (or vice versa). Mirror the
web app's strict branching (`web/index.html:2173-2182`).

## Telegram bot (`telegram/bot.py`)
- The bot is private. Access is gated by `TELEGRAM_ALLOWED_IDS`
  (`telegram/bot.py:353-356`); keep every authenticated path behind that gate.
- Each Telegram user maps to their own backend account (`main.py:2824-2854`); one
  user's actions never spend another user's credits.
