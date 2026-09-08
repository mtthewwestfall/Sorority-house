# coder — your own coding agent for this repo

A single Python file that turns a sentence into a pull request, running on your machine with
your API key. It reads `AGENTS.md`, explores and edits the code with real tools, runs the repo
checks, reviews its own diff, then commits, pushes and opens the PR.

## Setup (once)

```
pip install requests
gh auth login                     # GitHub CLI, so it can open PRs
export GEMINI_API_KEY=...         # or CODER_API_KEY for any other provider
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

| Setting | Default | Notes |
|---|---|---|
| `CODER_MODEL` | `gemini-3.1-pro-preview` | strongest default; `gemini-2.5-flash` is far cheaper for small jobs |
| `CODER_BASE_URL` | Gemini's OpenAI-compatible endpoint | any OpenAI-compatible chat API with tool calling: `https://api.deepseek.com/v1`, `https://api.openai.com/v1`, a local vLLM/Ollama |
| `CODER_API_KEY` | falls back to `GEMINI_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY` | |
| `CODER_PRICE_IN` / `CODER_PRICE_OUT` | unset | $ per 1M tokens; when set, each run prints an estimated cost |

## Cost

A typical small task uses roughly 150k input tokens and 1.5k output tokens. Set the `CODER_PRICE_IN` and `CODER_PRICE_OUT` environment variables (in $ per 1M tokens) to see the estimated cost in dollars at the end of a run.

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
