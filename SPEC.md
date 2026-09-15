# THOUGHTSPACE — MVP Spec

## What it is
Thoughtspace — an app where you build your own AI through conversation. Not a game. Not companion AI. You teach it what you need — a personal assistant, a coding helper, a sales coach — and it learns permanently.

## MVP scope: consumer builder first
Sequencing: consumers first, businesses second. Consumers buy fast and test it — that gives us cash flow and live proof. Businesses won't hand their customers to an unproven AI; the business app follows once we have case studies in hand. One lane at a time.

## Timeline: about a week, not months
Blank to working AI in about a week of teaching. The months-long raising arc belongs to Parent Space (the game) — not this.

## Platform
Web app first, mobile-first and phone-friendly. iOS wrapper after MVP.

## Code
Private repo: mtthewwestfall/Thoughtspace. Spec committed as SPEC.md.

## Core loop
1. **Start blank**: the user's AI starts knowing nothing.
2. **Teach**: the user teaches through conversation — what they do, how they work, what they need. Show it real examples; it absorbs tone, process, knowledge.
3. **Permanent learning**: everything sticks. Corrections don't erase — it remembers the first version.
4. **Grade**: the audit scores the trained AI — evidence-based, from the training conversations. The user sees exactly how good their AI is.
5. **Use**: the AI works for the user daily — assistant tasks, coding help, whatever they trained it for.
6. **Keep learning**: it keeps absorbing from ongoing use.

## Memory
Persistent across sessions. It never forgets what you taught it.

## The audit (hard boundary)
Build the frontend and the API call — NOT the audit engine. The audit machinery lives in the founder's private backend and stays there. The app sends data to his endpoint and renders the returned report. Do not reimplement, copy, or ask for the audit internals.

## Ship rule
Nothing ships until it's plugged in and tested end-to-end. Fully functional, not a demo.

## Phase 2 (after proof): the business app
Business owners train an AI on their company the same way, QA it with the audit, and deploy it to their website/app as a 24/7 employee. Separate phase, separate push — not in MVP.

## Out of scope for MVP
- Parent Space (the game version — separate product, separate design, later).
- iOS native build.
- Pricing/payments — pricing TBD after market research.

## Design
Clean, modern, consumer-app feel — this should feel like the future, not enterprise software. Not gamey, not companion-app.
