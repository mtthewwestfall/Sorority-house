#!/usr/bin/env python3
"""
coder — a self-hosted coding agent for this repo.

    python coder/coder.py "add a /version endpoint that returns the git sha"
    python coder/coder.py --plan "make the login form remember the email"
    python coder/coder.py --no-pr --yes "fix the typo in the plans copy"

It reads AGENTS.md, works on a fresh branch, edits files with real tools
(read / search / edit / run), runs the repo's checks, reviews its own diff,
then commits, pushes and opens a PR with `gh`. Your machine, your API key.

Any OpenAI-compatible chat endpoint that supports tool calling works:
  CODER_API_KEY   falls back to GEMINI_API_KEY, then OPENAI_API_KEY, then DEEPSEEK_API_KEY
  CODER_BASE_URL  default https://generativelanguage.googleapis.com/v1beta/openai
  CODER_MODEL     default gemini-3.1-pro-preview
  CODER_PRICE_IN / CODER_PRICE_OUT   optional $ per 1M tokens, to print a cost estimate

Only dependency: requests.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                           text=True, check=True).stdout.strip())
GUIDE = ROOT / "AGENTS.md"

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-3.1-pro-preview"
MAX_TOOL_OUTPUT = 12_000       # chars of a single tool result the model gets to see
MAX_STEPS = 60                 # tool calls before we stop and ask
VERIFY_ROUNDS = 3              # how many times failing checks are fed back
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
# Commands the model may run without asking. Anything else prompts you first (or is refused
# under --yes). Shell syntax that hides a command (backticks, $(...), eval, sh -c, redirects
# outside the repo) is never auto-approved.
ALLOWED = {"python", "python3", "pytest", "pip", "uvicorn", "node", "npm", "npx", "rg", "grep",
           "ls", "cat", "head", "tail", "wc", "find", "diff", "sort", "uniq", "echo", "curl",
           "sleep", "true", "env", "printf", "test", "which"}
GIT_READ_ONLY = {"diff", "status", "log", "show", "blame", "rev-parse", "ls-files", "grep", "branch"}
# Interpreters run whatever they're given; inline code and package installs always prompt.
INLINE_CODE = {"python": {"-c"}, "python3": {"-c"}, "node": {"-e", "-p", "--eval", "--print"}}
SCRIPT_EXT = (".py", ".js", ".mjs", ".cjs", ".ts")
INSTALLERS = {"pip": {"install", "download", "uninstall"}, "npm": {"install", "i", "exec", "x", "run", "ci"}}
NEVER_AUTO = {"npx", "curl"}
HIDDEN_SYNTAX = re.compile(r"`|\$\(|\beval\b|\bexec\b|\bsh\s+-c|\bbash\s+-c|\bsudo\b|>\s*/")
RUN_POLICY = {"yes": False}    # set from --yes at startup


def runs_inline_code(words: list[str], flags: set[str]) -> bool:
    """True if an inline-code flag appears before the script path (or `-m module` / `--`).
    Everything up to that point is scanned, so option values (`-W ignore`) and combined
    short flags (`-qc`) can't hide it; anything after the script belongs to the script."""
    short = {f[1] for f in flags if len(f) == 2}
    long = {f for f in flags if len(f) > 2}
    for w in words[1:]:
        if w in ("-m", "--") or w.lower().endswith(SCRIPT_EXT):
            return False
        if w.startswith("--"):
            if w.split("=")[0] in long:
                return True
        elif w.startswith("-") and len(w) > 1 and short & set(w[1:]):
            return True
    return False


def command_allowed(command: str) -> str | None:
    """None if every piece of the pipeline is on the allowlist, else the reason it isn't."""
    if HIDDEN_SYNTAX.search(command):
        return "uses shell syntax that can hide another command"
    try:
        tokens = list(shlex.shlex(command, posix=True, punctuation_chars=True))
    except ValueError as e:
        return f"unparseable: {e}"
    segments, words, skip = [], [], False
    for tok in tokens:
        if skip:                       # the target of a redirect, not a command
            skip = False
        elif tok in ("|", "||", "&&", ";", "&", "(", ")"):
            segments.append(words); words = []
        elif tok.startswith(">") or tok.startswith("<"):
            skip = True
        else:
            words.append(tok)
    segments.append(words)
    for words in segments:
        # skip leading VAR=value assignments
        while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
            words.pop(0)
        if not words:
            continue
        prog = os.path.basename(words[0])
        if prog == "git":
            if len(words) < 2 or words[1] not in GIT_READ_ONLY:
                return f"`git {words[1] if len(words) > 1 else ''}` writes to the repo; the harness handles commits/pushes"
        elif prog not in ALLOWED:
            return f"`{prog}` is not on the allowlist"
        elif prog in NEVER_AUTO:
            return f"`{prog}` fetches or runs arbitrary code"
        elif prog in INLINE_CODE and runs_inline_code(words, INLINE_CODE[prog]):
            return f"inline `{prog}` code runs unrestricted; put it in a file under the repo"
        elif prog in INSTALLERS and INSTALLERS[prog] & set(words[1:]):
            return f"`{prog}` would install or execute packages"
    return None

# --------------------------------------------------------------------------- output

def say(msg: str, *, dim: bool = False) -> None:
    if dim and sys.stdout.isatty():
        print(f"\033[2m{msg}\033[0m", flush=True)
    else:
        print(msg, flush=True)


def clip(text: str, n: int = MAX_TOOL_OUTPUT) -> str:
    if len(text) <= n:
        return text
    half = n // 2
    return text[:half] + f"\n... [{len(text) - n} chars trimmed] ...\n" + text[-half:]


# --------------------------------------------------------------------------- tools

def _safe(path: str) -> Path:
    p = (ROOT / path).resolve()
    if ROOT not in p.parents and p != ROOT:
        raise ValueError(f"{path} is outside the repo")
    return p


def t_list_files(path: str = ".", pattern: str = "*") -> str:
    base = _safe(path)
    out = []
    for p in sorted(base.rglob("*")):
        if any(part in IGNORED_DIRS for part in p.relative_to(ROOT).parts):
            continue
        if p.is_file() and fnmatch.fnmatch(p.name, pattern):
            out.append(f"{p.relative_to(ROOT)}  ({p.stat().st_size} bytes)")
        if len(out) >= 400:
            out.append("... (truncated at 400 files, narrow the pattern)")
            break
    return "\n".join(out) or "(no files)"


def t_read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
    p = _safe(path)
    if not p.is_file():
        return f"ERROR: {path} does not exist"
    lines = p.read_text(errors="replace").splitlines()
    end = end_line or len(lines)
    chunk = lines[max(start_line, 1) - 1:end]
    body = "\n".join(f"{i:>5}| {l}" for i, l in enumerate(chunk, start=max(start_line, 1)))
    return f"{path} ({len(lines)} lines total, showing {max(start_line, 1)}-{min(end, len(lines))})\n{body}"


def t_search(pattern: str, path: str = ".", glob: str = "") -> str:
    cmd = ["rg", "-n", "--no-heading", "-S", "--max-columns", "300", "-e", pattern]
    for d in IGNORED_DIRS:
        cmd += ["-g", f"!{d}"]
    if glob:
        cmd += ["-g", glob]
    cmd.append(str(_safe(path)))
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if r.returncode == 1:
        return "(no matches)"
    if r.returncode not in (0, 1):
        # fall back to grep if ripgrep isn't installed
        g = subprocess.run(["grep", "-rn", "-E", pattern, str(_safe(path))] +
                           [f"--exclude-dir={d}" for d in IGNORED_DIRS],
                           capture_output=True, text=True, cwd=ROOT)
        return g.stdout.replace(str(ROOT) + "/", "") or "(no matches)"
    return r.stdout.replace(str(ROOT) + "/", "")


def t_write_file(path: str, content: str) -> str:
    p = _safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(content)
    return f"{'overwrote' if existed else 'created'} {path} ({len(content.splitlines())} lines)"


def t_edit_file(path: str, old: str, new: str) -> str:
    p = _safe(path)
    if not p.is_file():
        return f"ERROR: {path} does not exist"
    text = p.read_text()
    n = text.count(old)
    if n == 0:
        return ("ERROR: `old` was not found in the file. Re-read the file and copy the "
                "exact text, including whitespace and indentation.")
    if n > 1:
        return f"ERROR: `old` matches {n} places; include more surrounding lines so it is unique."
    p.write_text(text.replace(old, new, 1))
    return f"edited {path}"


def t_run(command: str, timeout: int = 180) -> str:
    why = command_allowed(command)
    if why:
        if RUN_POLICY["yes"] or not sys.stdin.isatty():
            return f"BLOCKED ({why}). Rephrase using allowed tools: {', '.join(sorted(ALLOWED))}, git read-only."
        say(f"\n  model wants to run: {command}\n  ({why})")
        if input("  allow? [y/N] ").strip().lower() != "y":
            return "BLOCKED: the user declined to run this command. Find another way or explain in finish."
    return shell(command, timeout)


def shell(command: str, timeout: int) -> str:
    try:
        r = subprocess.run(command, shell=True, cwd=ROOT, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"ERROR: timed out after {timeout}s"
    out = (r.stdout or "") + (("\nSTDERR:\n" + r.stderr) if r.stderr else "")
    return f"exit {r.returncode}\n{clip(out) if out.strip() else '(no output)'}"


TOOLS = {
    "list_files": (t_list_files, "List files under a directory (recursive), optionally filtered "
                   "by a filename glob like '*.py'.",
                   {"path": {"type": "string"}, "pattern": {"type": "string"}}, []),
    "read_file": (t_read_file, "Read a file with line numbers. Use start_line/end_line for big files.",
                  {"path": {"type": "string"}, "start_line": {"type": "integer"},
                   "end_line": {"type": "integer"}}, ["path"]),
    "search": (t_search, "Regex search across the repo (ripgrep). Returns file:line: text.",
               {"pattern": {"type": "string"}, "path": {"type": "string"},
                "glob": {"type": "string", "description": "e.g. '*.py' or 'web/**'"}}, ["pattern"]),
    "edit_file": (t_edit_file, "Replace ONE exact, unique occurrence of `old` with `new`. Copy `old` "
                  "verbatim from read_file output (without the line-number prefix).",
                  {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
                  ["path", "old", "new"]),
    "write_file": (t_write_file, "Create a new file or fully overwrite an existing one.",
                   {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    "run": (t_run, "Run a shell command in the repo root (tests, py_compile, curl, git diff...). "
            "Commits/pushes are done for you later; don't run them.",
            {"command": {"type": "string"}, "timeout": {"type": "integer"}}, ["command"]),
    "finish": (None, "Call when the task is complete and verified. `summary` is a short PR-style "
               "description of what changed and why; `title` is a one-line PR title.",
               {"title": {"type": "string"}, "summary": {"type": "string"}}, ["title", "summary"]),
}


def tool_schemas() -> list[dict]:
    return [{"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": req}}}
        for name, (_, desc, props, req) in TOOLS.items()]


# --------------------------------------------------------------------------- model

class Model:
    def __init__(self, model: str, base_url: str, api_key: str):
        self.model, self.base_url, self.api_key = model, base_url.rstrip("/"), api_key
        self.prompt_tokens = self.completion_tokens = self.calls = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        body = {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto"}
        for attempt in range(4):
            try:
                r = requests.post(f"{self.base_url}/chat/completions", json=body, timeout=300,
                                  headers={"Authorization": f"Bearer {self.api_key}"})
            except requests.RequestException as e:
                err = str(e)
            else:
                if r.status_code == 200:
                    data = r.json()
                    usage = data.get("usage") or {}
                    self.prompt_tokens += usage.get("prompt_tokens", 0)
                    self.completion_tokens += usage.get("completion_tokens", 0)
                    self.calls += 1
                    msg = data["choices"][0]["message"]
                    if "googleapis" not in self.base_url:
                        # Gemini's thought signatures ride in extra_content; other providers reject it
                        for c in msg.get("tool_calls") or []:
                            c.pop("extra_content", None)
                    return msg
                err = f"HTTP {r.status_code}: {r.text[:500]}"
                if r.status_code in (400, 401, 403, 404):
                    raise SystemExit(f"model call failed: {err}")
            wait = 2 ** attempt * 3
            say(f"  model error ({err[:120]}), retrying in {wait}s", dim=True)
            time.sleep(wait)
        raise SystemExit("model call failed repeatedly; giving up")

    def cost(self) -> str:
        pin, pout = os.environ.get("CODER_PRICE_IN"), os.environ.get("CODER_PRICE_OUT")
        s = f"{self.calls} calls, {self.prompt_tokens:,} in / {self.completion_tokens:,} out tokens"
        if pin and pout:
            usd = self.prompt_tokens / 1e6 * float(pin) + self.completion_tokens / 1e6 * float(pout)
            s += f", ~${usd:.3f}"
        return s


# --------------------------------------------------------------------------- git

def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr}")
    return r.stdout.strip()


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "task"


def stage_all() -> str:
    """Stage everything (new files included) and return the staged diffstat."""
    git("add", "-A", "--", ".")
    return git("diff", "--cached", "--stat")


def repo_checks() -> list[str]:
    """Verification commands: a ```checks``` block in AGENTS.md, else py_compile."""
    if GUIDE.exists():
        m = re.search(r"```checks\n(.*?)```", GUIDE.read_text(), re.S)
        if m:
            return [l.strip() for l in m.group(1).splitlines() if l.strip() and not l.startswith("#")]
    changed = [f for f in git("diff", "--name-only", "HEAD").splitlines() if f.endswith(".py")]
    changed += [f for f in git("ls-files", "--others", "--exclude-standard").splitlines()
                if f.endswith(".py")]
    return [f"python -m py_compile {shlex.quote(f)}" for f in changed if (ROOT / f).exists()]


# --------------------------------------------------------------------------- agent

SYSTEM = """You are an expert software engineer working autonomously inside a git repository.
You have real tools: explore with list_files / search / read_file, change code with edit_file /
write_file, and verify with run. Work like a careful senior engineer:

1. Read AGENTS.md (given below) and the code you are about to touch BEFORE editing. Never guess
   at file contents; read them.
2. Make the smallest change that fully solves the task, in the style of the surrounding code.
   No drive-by refactors, no new dependencies unless unavoidable, no commented-out code.
3. Verify. Run the repo checks and any relevant test or quick script after editing. If a check
   fails, fix it. Read error output carefully instead of guessing.
4. Do not commit, push, or open PRs yourself; call `finish` with a title and summary and the
   harness will do it after showing the diff to the user.
5. If the task is impossible, ambiguous in a way that matters, or would need secrets you don't
   have, say so plainly in `finish` instead of inventing something.

Repo root: {root}

=== AGENTS.md ===
{guide}
"""

REVIEW = """The task is done and the checks pass. Before it ships, review your own diff below as a
strict reviewer would: bugs, missed call sites, broken edge cases, inconsistent behaviour with
the rest of the code, anything the task asked for that is missing, leftover debug output.
If you find a problem, fix it with the tools and re-run the checks. Then call `finish` again
(with the final title/summary). If it is genuinely fine, just call `finish`.

```diff
{diff}
```"""


def trim_history(messages: list[dict], keep_last: int = 24) -> None:
    """Replace old tool outputs with stubs so the context stays bounded on long tasks."""
    tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    for i in tool_idx[:-keep_last]:
        if len(messages[i]["content"]) > 200:
            messages[i]["content"] = messages[i]["content"][:160] + "\n... [older output trimmed]"


def run_agent(model: Model, messages: list[dict], max_steps: int, yes: bool) -> dict | None:
    """Drive the tool loop until the model calls finish. Returns finish args or None."""
    steps = 0
    while True:
        trim_history(messages)
        msg = model.chat(messages, tool_schemas())
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if msg.get("content") and msg["content"].strip():
            say(f"\n{msg['content'].strip()}")
        if not calls:
            # A bare text answer with no finish: nudge once, then accept as done/blocked.
            messages.append({"role": "user", "content":
                             "If the task is complete, call `finish`. Otherwise continue with tools."})
            steps += 1
            if steps > max_steps:
                return None
            continue
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == "finish":
                return {"title": args.get("title", "Update"), "summary": args.get("summary", "")}
            fn = TOOLS.get(name, (None,))[0]
            preview = args.get("command") or args.get("path") or args.get("pattern") or ""
            say(f"  > {name} {preview}", dim=True)
            if fn is None:
                result = f"ERROR: unknown tool {name}"
            else:
                try:
                    result = fn(**args)
                except TypeError as e:
                    result = f"ERROR: bad arguments: {e}"
                except Exception as e:  # tool bugs must not kill the run
                    result = f"ERROR: {type(e).__name__}: {e}"
            messages.append({"role": "tool", "tool_call_id": call["id"], "name": name,
                             "content": clip(str(result))})
            steps += 1
        if steps >= max_steps:
            if yes or not sys.stdin.isatty():
                return None
            ans = input(f"\n{steps} steps used. Keep going? [y/N] ").strip().lower()
            if ans != "y":
                return None
            max_steps += MAX_STEPS // 2


def verify(model: Model, messages: list[dict], yes: bool) -> bool:
    checks = repo_checks()
    for _ in range(VERIFY_ROUNDS):
        failures = []
        for c in checks:
            say(f"  $ {c}", dim=True)
            out = shell(c, timeout=600)
            if not out.startswith("exit 0"):
                failures.append(f"$ {c}\n{out}")
        if not failures:
            return True
        say("  checks failed, sending back to the model", dim=True)
        messages.append({"role": "user", "content":
                         "These repo checks failed. Fix the cause (not the check) and call finish "
                         "again:\n\n" + "\n\n".join(failures)})
        if run_agent(model, messages, MAX_STEPS // 2, yes) is None:
            return False
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="self-hosted coding agent for this repo")
    ap.add_argument("task", nargs="*", help="what to do (or pipe it on stdin)")
    ap.add_argument("--plan", action="store_true", help="show a plan and ask before editing")
    ap.add_argument("--no-pr", action="store_true", help="commit on a branch but don't push/open a PR")
    ap.add_argument("--yes", "-y", action="store_true", help="don't ask for confirmation")
    ap.add_argument("--model", default=os.environ.get("CODER_MODEL", DEFAULT_MODEL))
    ap.add_argument("--base-url", default=os.environ.get("CODER_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS)
    ap.add_argument("--no-review", action="store_true", help="skip the self-review pass")
    a = ap.parse_args()
    RUN_POLICY["yes"] = a.yes

    task = " ".join(a.task).strip() or (sys.stdin.read().strip() if not sys.stdin.isatty() else "")
    if not task:
        ap.error("give me a task")
    api_key = (os.environ.get("CODER_API_KEY") or os.environ.get("GEMINI_API_KEY")
               or os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY"))
    if not api_key:
        raise SystemExit("set CODER_API_KEY (or GEMINI_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY)")
    if git("status", "--porcelain"):
        raise SystemExit("working tree is dirty; commit or stash first so the PR only has my changes")

    base = git("rev-parse", "--abbrev-ref", "HEAD")
    branch = f"coder/{int(time.time())}-{slug(task)}"
    git("checkout", "-b", branch)
    say(f"branch {branch} (from {base}); model {a.model}")

    model = Model(a.model, a.base_url, api_key)
    guide = GUIDE.read_text() if GUIDE.exists() else "(no AGENTS.md in this repo)"
    messages = [{"role": "system", "content": SYSTEM.format(root=ROOT, guide=guide)},
                {"role": "user", "content": f"Task:\n{task}"}]

    if a.plan:
        messages[-1]["content"] += ("\n\nFirst, explore as needed and then reply in plain text with "
                                    "a short numbered plan (files you'll touch, what changes). Do "
                                    "NOT edit anything yet and do NOT call finish.")
        while True:
            msg = model.chat(messages, tool_schemas())
            messages.append(msg)
            if not msg.get("tool_calls"):
                break
            for call in msg["tool_calls"]:
                name, args = call["function"]["name"], json.loads(call["function"]["arguments"] or "{}")
                fn = TOOLS.get(name, (None,))[0]
                if name in ("edit_file", "write_file", "finish") or fn is None:
                    result = "ERROR: planning only; no edits yet"
                else:
                    result = fn(**args)
                messages.append({"role": "tool", "tool_call_id": call["id"], "name": name,
                                 "content": clip(str(result))})
        say(f"\nPLAN:\n{msg.get('content', '').strip()}\n")
        if not a.yes and input("Go ahead? [Y/n] ").strip().lower() not in ("", "y"):
            git("checkout", base); git("branch", "-D", branch)
            raise SystemExit("aborted")
        messages.append({"role": "user", "content": "Approved. Implement the plan now."})

    say("\nworking...")
    done = run_agent(model, messages, a.max_steps, a.yes)
    if done is None:
        say(f"\nstopped without finishing. Branch {branch} keeps whatever was changed.\n{model.cost()}")
        return
    say(f"\nmodel says done: {done['title']}\nverifying...")
    if not verify(model, messages, a.yes):
        say(f"\nchecks still failing; leaving branch {branch} for you to look at.\n{model.cost()}")
        return

    if not a.no_review and stage_all():
        say("self-review...")
        messages.append({"role": "user", "content":
                         REVIEW.format(diff=clip(git("diff", "--cached"), 40_000))})
        reviewed = run_agent(model, messages, a.max_steps // 2, a.yes)
        if reviewed:
            done = reviewed
        if not verify(model, messages, a.yes):
            say(f"\nchecks failing after review; leaving branch {branch}.\n{model.cost()}")
            return

    stat = stage_all()
    if not stat:
        say(f"\nno changes were made.\n{done['summary']}\n{model.cost()}")
        git("checkout", base); git("branch", "-D", branch)
        return
    say(f"\n{stat}\n\n{done['title']}\n\n{done['summary']}\n\n{model.cost()}")
    if not a.yes and sys.stdin.isatty():
        ans = input("\nCommit" + ("" if a.no_pr else " and open a PR") + "? [Y/n/d(iff)] ").strip().lower()
        while ans == "d":
            print(git("diff", "--cached"))
            ans = input("Commit? [Y/n] ").strip().lower()
        if ans not in ("", "y"):
            say(f"left uncommitted on branch {branch}")
            return

    git("commit", "-q", "-m", done["title"], "-m", done["summary"] + "\n\nMade with coder/coder.py")
    if a.no_pr:
        say(f"committed on {branch} (not pushed)")
        return
    git("push", "-q", "-u", "origin", branch)
    r = subprocess.run(["gh", "pr", "create", "--base", base, "--head", branch, "--title", done["title"],
                        "--body", done["summary"] + "\n\n---\nOpened by `coder/coder.py` "
                        f"({a.model}). Task:\n\n> {task}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        say(f"pushed {branch}, but `gh pr create` failed:\n{r.stderr}\nOpen the PR by hand:\n"
            f"  gh pr create --base {shlex.quote(base)} --head {shlex.quote(branch)}")
    else:
        say(r.stdout.strip())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\ninterrupted")
