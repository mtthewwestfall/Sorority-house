# coder — your own coding agent for this repo

A single Python file that turns a sentence into a pull request, running on your machine with
your API key. It reads `AGENTS.md`, explores and edits the code with real tools, runs the repo
checks, reviews its own diff, then commits, pushes and opens the PR.

## Setup (once)

```
pip install requests
gh auth login                     # GitHub CLI, so it can open PRs
export DEEPSEEK_API_KEY=...       # primary (cheapest)
export GEMINI_API_KEY=...         # backup: used automatically if DeepSeek fails
```

## Use

```
python coder/coder.py "add a /version endpoint that returns the git sha"
python coder/coder.py --plan "make the login form remember the email"     # shows a plan first
python coder/coder.py --no-pr "fix the typo in the plans copy"            # commit only
python coder/coder.py -y "..."                                             # no questions asked
```

It works on a fresh `coder/<timestamp>-<slug>` branch off whatever you have checked out, so
start from an up-to-date `main`. Before committing it prints the diffstat, its PR summary and
the token usage; press `d` to read the full diff, `n` to leave the changes uncommitted.

## Choosing a model

Providers are tried in this order, using whichever keys you have set; if the current one keeps
failing mid-task (outage, rate limit, bad key) the run carries on with the next:

| Order | Key | Model |
|---|---|---|
| 1 | `DEEPSEEK_API_KEY` | `deepseek-chat` — cents per task |
| 2 | `GEMINI_API_KEY` | `gemini-3.1-pro-preview` — more careful; ~$0.20-0.40 per small task |
| 3 | `OPENAI_API_KEY` | `gpt-4.1` |

To force a specific model (any OpenAI-compatible endpoint with tool calling, incl. local
vLLM/Ollama), set `CODER_BASE_URL` + `CODER_MODEL` (+ `CODER_API_KEY` if it isn't one of the
above); it goes first, the chain stays as backup (an override identical to a built-in entry is
not repeated).

## Cost

A typical small task uses roughly 150k input tokens and 1.5k output tokens. Every run ends with
token counts per model. For a dollar figure give prices ($ per 1M input/output tokens) for the
models you use, e.g. `CODER_PRICES="deepseek-chat=0.28/0.42,gemini-3.1-pro-preview=2/12"`
(check your providers' current price lists); the estimate is only shown when every model that
took part in the run has a price. `CODER_PRICE_IN` / `CODER_PRICE_OUT` still work for the
primary model alone.

DeepSeek (the default when its key is set) did a /help command for the Telegram bot in 13k tokens,
well under a cent. For anything touching trust logic or payments, force Gemini:
`CODER_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai CODER_MODEL=gemini-3.1-pro-preview`.

## What it does well / where to keep an eye on it

Good at: well-described changes to `main.py` or `web/index.html` — a new route, a copy change,
a bug you can point at, a new env var, small features. It reads the code before editing, uses
exact-match edits (so it can't silently clobber unrelated lines), and won't ship a diff that
fails `py_compile` or the HTML parse.

Watch it on: anything that needs the app running to judge (visual layout, chat feel), anything
touching payments or the trust engine, and big multi-file features. Read every diff before
merging — it opens PRs, it does not merge them.

Guardrails: it can only touch files inside the repo; shell commands run only if every part of
the pipeline is on an allowlist (`python`, `pytest`, `pip`, `uvicorn`, `curl`, `rg`, `ls`, read-only
`git`, ...) and free of hidden-command syntax (backticks, `$(...)`, `eval`, `sh -c`, `sudo`,
writes outside the repo) — anything else asks you first, or is refused under `-y`. Inline code
(`python -c`, `node -e`), `pip install`/`npm install`, `npx` and `curl` always ask. It never
commits, pushes or opens PRs itself (the harness does, after you confirm), and it stops to ask
after 60 tool calls.

This is not a sandbox: `python some_script.py` can do anything your user can, and the model
writes the scripts. Interactive runs show you every command; for unattended `-y` runs, use a
container or VM with a throwaway checkout and a scoped `gh` token.

## Teaching it

`AGENTS.md` is its briefing. When it gets something wrong twice, add the rule there. The
```` ```checks ```` block in that file is the list of commands it must pass before finishing.

## Using it on another project

Nothing here is specific to this repo. Copy `coder/coder.py` into any git repository and run it
from there: it finds that repo's root, reads its `AGENTS.md` if there is one (otherwise it works
without a briefing and falls back to `python -m py_compile` on changed `.py` files as the check),
and opens PRs against that repo with `gh`. Write a short `AGENTS.md` there with a
```` ```checks ```` block and it will be as careful as it is here.

Starter briefings live in `coder/templates/`. For a Telegram bot:

```bash
mkdir mybot && cd mybot && git init
cp /path/to/Sorority-house/coder/coder.py .
cp /path/to/Sorority-house/coder/templates/telegram-bot.AGENTS.md AGENTS.md   # edit "What this bot does"
git add -A && git commit -m "scaffold"
export TELEGRAM_BOT_TOKEN=...   # from @BotFather; never goes in the repo
python coder.py --no-pr "create the bot described in AGENTS.md, plus requirements.txt, .env.example, .gitignore and check_bot.py"
```

That exact run, unattended (`-y`), produced a working bot (/start, /roll, echo) with the token
read from the environment and verified via `getMe`, in 28 tool calls / ~176k input tokens.
