# AGENTS.md — Telegram bot

Starter briefing for a Telegram bot repo. Copy this file to the root of a new git repo as
`AGENTS.md`, edit the "What this bot does" section, drop `coder.py` next to it and run:

    export TELEGRAM_BOT_TOKEN=...      # from @BotFather, never in the repo
    python coder.py "create the bot: /start greets the user, every other message gets echoed back"

## What this bot does

(Describe the bot in a few lines: commands, who uses it, what it must never do.)

## Layout

- `bot.py` — the whole bot: handlers, startup, polling. Keep it one file until it hurts.
- `requirements.txt` — `python-telegram-bot>=21` and nothing else unless needed.
- `.env.example` — names of the environment variables, no values.
- `.gitignore` — must include `.env`, `__pycache__/`, `*.pyc`.

## Rules

- The token comes from `os.environ["TELEGRAM_BOT_TOKEN"]`. Never write a token, chat id or
  any other secret into a file. If a token is found in the diff, remove it before finishing.
- Use `python-telegram-bot` (async, `Application.builder().token(...).build()`, `run_polling()`).
  No webhooks unless the task asks for them.
- Every handler catches its own exceptions and replies with a short message instead of crashing
  the bot.
- Long-running work in a handler must not block the event loop (use `asyncio` or a thread).
- Do not talk to the Telegram API from tests or checks; unit-test handler logic by passing fake
  `update`/`context` objects.

## Smoke test (optional, uses the real token)

`python check_bot.py` should call `getMe` and print the bot username. Write this file if it does
not exist; it is the only script allowed to hit `api.telegram.org` during a task.

## Running it

    pip install -r requirements.txt
    TELEGRAM_BOT_TOKEN=... python bot.py

```checks
python -m py_compile bot.py
```

## Style

- Python 3.10+, type hints on handler signatures, no global mutable state except the
  `Application`.
- One command = one handler function named `cmd_<name>`; free-text messages go to `on_message`.
