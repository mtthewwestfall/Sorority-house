"""
SORORITY HOUSE — Telegram bot
================================

The Telegram "version" of Sorority House. Telegram is just another front-end onto
the *same* backend (`main.py`): accounts, the trust engine, the per-girl memory
stack, the message allowance and the model roles (MOUTH/BRAIN/AUDIT) all live
there. This bot is a thin chat client over the backend's public API, so whatever
a player did on the web or on Telegram is one shared account and one shared
conversation history.

This is deliberately the same account model as the web: you `/login` with the
email + password of your Sorority House account (the one you signed up and
verified on the website). Nothing here weakens the backend — there are no admin
back-doors, no client-side claims of purchases. If you do not have an account
yet, sign up on the website once (it emails a verification link) and come back.

Commands
--------
/start   — welcome + how to sign in
/login   — /login <email> <password>, binds this Telegram chat to your account
/signup  — /signup <email> <password> <display_name>, creates a NEW account
           (email verification still happens, exactly like the web — a token is
           only issued after you click the link we tell you to watch for)
/girls   — the doors: which sisters are open to you right now; tap one to talk
/girl    — /girl <slug> (e.g. /girl dakota) to switch who you are talking to
/state   — your tier, messages left, and every girl's trust stage
/history — the last messages with the girl you are talking to
/logout  — drop this chat's session (your account + history stay on Sorority House)
/help    — this text

Env vars
--------
TELEGRAM_BOT_TOKEN   from @BotFather. Never put the value in any file.
PUBLIC_URL           the Sorority House backend base URL, e.g. the Railway app.
                     Required (no default), same across web and this bot.
"""

import asyncio
import json
import logging
import os

try:
    import requests
    NetError = requests.exceptions.RequestException
except Exception:  # pragma: no cover - requirement listed in this folder
    requests = None
    NetError = Exception

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # its request lines include the token
logger = logging.getLogger("sorority_tg")

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
URL_ENV = "PUBLIC_URL"

# ---------------------------------------------------------------------------
# Tiny per-chat store (a local JSON file; tokens live here, never in git).
# ---------------------------------------------------------------------------
def _state_file() -> str:
    return os.environ.get("SORORITY_STATE_FILE",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "sessions.json"))


class Store:
    def __init__(self, path=None):
        self.path = path or _state_file()
        self._data = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                self._data = json.load(fh)
        except (OSError, ValueError):
            self._data = {}

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def get(self, chat_id):
        return self._data.get(str(chat_id))

    def set(self, chat_id, **fields) -> None:
        rec = self._data.setdefault(str(chat_id), {})
        rec.update(fields)
        self._save()

    def forget(self, chat_id) -> None:
        self._data.pop(str(chat_id), None)
        self._save()


store = Store()

# ---------------------------------------------------------------------------
# Backend client (plain requests over the shared HTTP API).
# ---------------------------------------------------------------------------
def _base() -> str:
    base = os.environ.get(URL_ENV, "").strip().rstrip("/")
    if not base:
        raise RuntimeError(f"{URL_ENV} is not set (the Sorority House backend).")
    return base


class BackendError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def _headers(token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _post(path, payload, token=None, timeout=40):
    if requests is None:
        raise RuntimeError("Missing dependency 'requests'.")
    r = requests.post(_base() + path, json=payload,
                      headers=_headers(token), timeout=timeout)
    if r.status_code == 401 and token:
        raise BackendError("Your session has expired — /login <email> <password> again.")
    return r


def _get(path, token=None, timeout=40):
    if requests is None:
        raise RuntimeError("Missing dependency 'requests'.")
    r = requests.get(_base() + path, headers=_headers(token), timeout=timeout)
    if r.status_code == 401 and token:
        raise BackendError("Your session has expired — /login <email> <password> again.")
    return r


def _login(email, password):
    r = _post("/auth/login", {"email": email, "password": password})
    if r.status_code == 403:
        raise BackendError(
            "Your email is not verified yet. Open the verification link we sent "
            "you (on the web sign-up) before logging in.", code="email_unverified")
    if r.status_code != 200:
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = ""
        raise BackendError(detail or f"Login failed (HTTP {r.status_code})")
    data = r.json()
    return {"token": data["token"], "user_id": data["user_id"],
            "tier": data["tier"], "email": email}


def _signup(email, password, display_name):
    r = _post("/auth/signup",
              {"email": email, "password": password,
               "display_name": display_name})
    if r.status_code != 200:
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = ""
        raise BackendError(detail or f"Signup failed (HTTP {r.status_code})")
    data = r.json()
    return {
        "needs_verification": data.get("needs_verification", True),
        "email_sent": data.get("email_sent", False),
    }


def _fetch_roster(token):
    r = _get("/roster", token=token)
    if r.status_code != 200:
        raise BackendError(f"Could not load the roster (HTTP {r.status_code})")
    return r.json()


def _fetch_state(token):
    r = _get("/state", token=token)
    if r.status_code != 200:
        raise BackendError(f"Could not load your state (HTTP {r.status_code})")
    return r.json()


def _fetch_history(token, girl):
    r = _get(f"/history?girl={girl}", token=token)
    if r.status_code != 200:
        raise BackendError(f"Could not load history (HTTP {r.status_code})")
    return r.json().get("messages", [])


def _send_chat(token, girl, message):
    r = _post("/chat", {"girl": girl, "message": message}, token=token)
    if r.status_code != 200:
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = ""
        raise BackendError(str(detail) or f"chat failed (HTTP {r.status_code})")
    return r.json()


async def login(*args):
    return await asyncio.to_thread(_login, *args)

async def signup(*args):
    return await asyncio.to_thread(_signup, *args)

async def fetch_roster(*args):
    return await asyncio.to_thread(_fetch_roster, *args)

async def fetch_state(*args):
    return await asyncio.to_thread(_fetch_state, *args)

async def fetch_history(*args):
    return await asyncio.to_thread(_fetch_history, *args)

async def send_chat(*args):
    return await asyncio.to_thread(_send_chat, *args)


# Roster presentation helpers --------------------------------------------------
def _girl_name(girls, slug):
    for g in girls:
        if g["girl"] == slug:
            return g["name"]
    return slug.replace("-", " ").title()


def _cmd_args(update) -> list:
    text = (update.message or update.effective_message).text or ""
    parts = text.split()
    return parts[1:] if len(parts) > 1 else []


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def _rec(update) -> dict:
    return store.get(update.effective_chat.id)


async def _txt(update, text) -> None:
    await update.effective_message.reply_text(text)


async def _require_login(update) -> bool:
    rec = _rec(update)
    if not rec or not rec.get("token"):
        await _txt(update,
             "You're not signed in yet.\n\n"
             "• new here?  /signup <email> <password> <name>  (accounts are verified by "
             "email, exactly like the web)\n"
             "• already have a Sorority House account?  /login <email> <password>")
        return False
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rec = _rec(update)
    if rec and rec.get("token"):
        await _txt(update,
             "Welcome back to the house. 💛\n\n"
             "• /girls — knock on the doors that are open to you\n"
             "• just type a message to talk to whoever you're with\n"
             "• /state — your allowance + where you stand with each sister\n"
             "• /help — everything")
        return
    await _txt(update,
         "🏛️ Welcome to Sorority House.\n\n"
         "This is the Telegram way to talk to the same sisters as the website — one "
         "account, one history, one shared allowance. The girls are real the same way "
         "they are there: doors open by trust, not by asking.\n\n"
         "• already have a Sorority House account:  /login <email> <password>\n"
         "• new here:                             /signup <email> <password> <name>\n"
         "                                          (then watch the inbox for the "
         "verification link, like the web)\n\n/help for commands.")


async def cmd_signup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        await _txt(update, "Do this in private, please — I'd rather not take your password in a group.")
        return
    args = _cmd_args(update)
    if len(args) < 3:
        await _txt(update, "Usage:  /signup <email> <password> <your name>\n"
                     "e.g. /signup friend@x.com hunter2 Jessica")
        return
    email, password = args[0], args[1]
    name = " ".join(args[2:])
    try:
        out = await signup(email, password, name)
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not sign up: {exc}")
        return
    if out.get("needs_verification"):
        await _txt(update,
             "Account created. 🎉 Sorority House verifies by email (same as the web) so "
             "I can't hand out a token until the link is clicked.\n\n"
             + ("Check your inbox for the verification link — then come back and "
                "/login <email> <password>."
                if out.get("email_sent")
                else "No verification email was sent by this instance (there is no mail "
                     "provider configured). Ask an admin to verify your account, then "
                     "/login <email> <password>."))
    else:
        await _txt(update, "Account created — and already verified. Your next step is "
                     "/girls to knock on a door.")


async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        await _txt(update, "Do this in private, please — I don't want your password in a group.")
        return
    args = _cmd_args(update)
    if len(args) < 2:
        await _txt(update, "Usage:  /login <email> <password>")
        return
    email, password = args[0], " ".join(args[1:])
    try:
        sess = await login(email, password)
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not sign in: {exc}")
        return
    store.set(update.effective_chat.id, **sess, active_girl=None)
    await _txt(update,
         f"Signed in as {sess['email']} — welcome back, and the house remembers you.\n\n"
         "/girls to knock on a door, /state for your allowance.")


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store.forget(update.effective_chat.id)
    await _txt(update, "Signed out of this chat. Your account and every conversation stay "
                 "on Sorority House — come back any time with /login.")


def _milestone_label(milestone):
    stages = {1: "Stranger", 2: "Noticing", 3: "Opening", 4: "Opening",
              5: "Trusted", 6: "Confided", 7: "Confided", 8: "Different"}
    return stages.get(int(milestone or 1), "Stranger")


async def cmd_girls(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    rec = _rec(update)
    try:
        roster = (await fetch_roster(rec["token"]))["girls"]
        state = (await fetch_state(rec["token"]))["girls"]
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the house: {exc}")
        return
    open_btns, closed = [], []
    for g in sorted(roster, key=lambda x: x.get("girl", "")):
        slug = g["girl"]
        st = state.get(slug, {})
        if st.get("open"):
            stage = st.get("band") or _milestone_label(st.get("milestone"))
            label = f"{g.get('name', slug)} · {stage} · open"
            open_btns.append([InlineKeyboardButton(label, callback_data=f"girl:{slug}")])
        else:
            reason = st.get("locked_reason", "door still shut")
            closed.append((g.get("name", slug), reason))

    intro = "The doors of the house:\n" if (open_btns or closed) else "The house is empty right now."
    await update.effective_message.reply_text(intro)

    if open_btns:
        await update.effective_message.reply_text(
            "✅ Open — tap one to talk:",
            reply_markup=InlineKeyboardMarkup(open_btns))
    else:
        await update.effective_message.reply_text(
            "No doors are open to you yet — trust opens them, and it builds on real "
            "days of talking on the site. Keep showing up.")

    if closed:
        shown = closed[:6]
        await update.effective_message.reply_text(
            "🔒 Still shut for you:\n• "
            + "\n• ".join(f"{name} — {reason}" for name, reason in shown)
            + (f"\n\n…plus {len(closed) - len(shown)} more." if len(closed) > len(shown) else ""))


async def _open_girl(update, slug) -> None:
    """Rec is data held per chat. Passed 'update' may be a command or a callback
    query — both expose .effective_chat / .effective_message."""
    sl = slug.strip().lower()
    rec = _rec(update)
    try:
        rosters = (await fetch_roster(rec["token"]))["girls"]
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the house: {exc}")
        return
    if sl not in [g["girl"] for g in rosters]:
        await _txt(update, "I don't recognise that sister. Try one of: "
                     + ", ".join(g["girl"] for g in rosters))
        return
    store.set(update.effective_chat.id, active_girl=sl)
    try:
        state = (await fetch_state(rec["token"]))["girls"].get(sl, {})
        if not state.get("open"):
            await _txt(update, f"That door is currently shut — {state.get('locked_reason', 'keep talking on the web and it may open.')}")
            return
        history = await fetch_history(rec["token"], sl)
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the house: {exc}")
        return
    if history:
        parts = [_girl_name(rosters, sl) + " — here's where you two left off:"]
        for m in history[-6:]:
            who = "You" if m["sender"] == "user" else "Her"
            tail = " …" if len(m["message"]) > 240 else ""
            parts.append(f"{who}: {m['message'][:240]}{tail}")
        msg = "\n\n".join(parts)
    else:
        msg = _girl_name(rosters, sl) + " — nothing between you yet."
    msg += "\n\nSay something. She'll answer 💬"
    await _txt(update, msg[:4000])


async def cmd_girl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    args = _cmd_args(update)
    if not args:
        await _txt(update, "Usage:  /girl <slug>  — e.g.  /girl dakota")
        return
    await _open_girl(update, args[0])


async def cmd_state(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    rec = _rec(update)
    try:
        st = await fetch_state(rec["token"])
        roster = (await fetch_roster(rec["token"]))["girls"]
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the house: {exc}")
        return
    names = {g["girl"]: g["name"] for g in roster}
    lines = [f"🏷️ Tier: {st.get('tier', '?')}"]
    rem = st.get("remaining")
    lines.append(f"💬 Messages left: {rem}" if isinstance(rem, int) else "💬 —")
    if isinstance(rem, int) and rem <= 0:
        lines.append("You're out of free messages this cycle — renew on the web to keep talking.")
    lines.append("")
    girls = st.get("girls") or {}
    open_list = []
    for slug, d in girls.items():
        if d.get("open"):
            stage = d.get("band") or _milestone_label(d.get("milestone"))
            open_list.append(f"✅ {names.get(slug, slug)} — {stage}")
    if open_list:
        lines.append("Open to you:\n" + "\n".join(open_list))
    else:
        lines.append("No doors open yet — trust unlocks them over real days.")
    await _txt(update, "\n".join(lines))


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    rec = _rec(update)
    slug = rec.get("active_girl")
    if not slug:
        await _txt(update, "Pick someone first:  /girls  or  /girl <slug>")
        return
    try:
        history = await fetch_history(rec["token"], slug)
        rosters = (await fetch_roster(rec["token"]))["girls"]
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the house: {exc}")
        return
    if not history:
        await _txt(update, f"No history with {_girl_name(rosters, slug)} yet.")
        return
    parts = [_girl_name(rosters, slug) + " — recent messages:"]
    for m in history[-8:]:
        who = "You" if m["sender"] == "user" else "Her"
        parts.append(f"{who}: {m['message']}")
    await _txt(update, "\n\n".join(parts)[:4000])


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    await q.answer()
    data = q.data or ""
    if not data.startswith("girl:"):
        return
    if not _rec(update) or not _rec(update).get("token"):
        await _txt(update, "Not signed in — /login <email> <password> first.")
        return
    await _open_girl(update, data.split(":", 1)[1])


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    rec = _rec(update)
    slug = rec.get("active_girl")
    if not slug:
        await _txt(update, "Who do you want to talk to?  Tap one on /girls, or  /girl <slug>.")
        return
    text = update.message.text or ""
    if not text.strip():
        return
    try:
        out = await send_chat(rec["token"], slug, text)
    except BackendError as exc:
        msg = str(exc)
        if "trial" in msg.lower() or "remaining" in msg.lower() or "allowance" in msg.lower():
            msg = "Your message allowance is spent. Renew your tier on the website to keep talking here."
        await _txt(update, msg)
        return
    except (RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the house right now: {exc}")
        return
    rem = out.get("remaining")
    reply = out.get("reply") or "…"
    tail = f"\n\n(Messages left: {rem})" if isinstance(rem, int) else ""
    await _txt(update, reply + tail)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _txt(update,
         "Sorority House on Telegram — commands:\n"
         "/signup <email> <password> <name> — new account (email-verified like the web)\n"
         "/login <email> <password> — sign into a Sorority House account\n"
         "/girls — knock on the doors that are open\n"
         "/girl <slug> — switch who you're talking to\n"
         "/state — tier, messages left, where you stand\n"
         "/history — the recent thread with her\n"
         "/logout — stop this chat session\n"
         "/help — this\n\n"
         "Just type normally to talk. Doors open by trust — showing up across real days "
         "counts, and the website and this bot share that clock.")


def main():
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise SystemExit(f"{TOKEN_ENV} is not set (from @BotFather).")
    try:
        _base()
    except RuntimeError as exc:
        raise SystemExit(f"{exc}")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("signup", cmd_signup))
    app.add_handler(CommandHandler("login", cmd_login))
    app.add_handler(CommandHandler("logout", cmd_logout))
    app.add_handler(CommandHandler("girls", cmd_girls))
    app.add_handler(CommandHandler("girl", cmd_girl))
    app.add_handler(CommandHandler("state", cmd_state))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    logger.info("Sorority House Telegram bot starting (backend: %s)", _base())
    app.run_polling()


if __name__ == "__main__":
    main()
