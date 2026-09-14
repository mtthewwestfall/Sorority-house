"""
SORORITY HOUSE — Telegram bot
================================

The Telegram "version" of Sorority House. Telegram is just another front-end onto
the *same* backend (`main.py`): accounts, the trust engine, the per-girl memory
stack, the message allowance and the model roles (MOUTH/BRAIN/AUDIT) all live
there. This bot is a thin chat client over the backend's public API, so whatever
a player did on the web or on Telegram is one shared account and one shared
conversation history.

Your Telegram id is your account: the first message opens a fresh one on the
backend (`/auth/telegram`, unlocked by the TELEGRAM_BOT_SECRET the bot shares with
`main.py`) — nobody types an email into a bot. `/login <email> <password>` is
optional and points this Telegram at an existing website account instead. Nothing
here weakens the backend — there are no admin back-doors, no client-side claims of
purchases; upgrades bought from the bot carry the user id to Stripe as
`client_reference_id` and land through the backend's Stripe webhook.

Commands
--------
/start   — welcome (opens the account on first use)
/login   — /login <email> <password>, joins this Telegram to your website account
/signup  — /signup <email> <password> <display_name>, creates an email account
           (email verification still happens, exactly like the web; then /login)
/girls   — the doors: which sisters are open to you right now; tap one to talk
/girl    — /girl <slug> (e.g. /girl dakota) to switch who you are talking to
/house   — leave her room and go back to the doors (also the keyboard button)
/audit   — run a psychological audit for the sister you are currently talking to
/state   — your tier, messages left, and every girl's trust stage
/history — the last messages with the girl you are talking to
/logout  — forget this chat's session (the next message reopens the same account)
/help    — this text

Env vars
--------
TELEGRAM_BOT_TOKEN   from @BotFather. Never put the value in any file.
PUBLIC_URL           the Sorority House backend base URL, e.g. the Railway app.
                     Required (no default), same across web and this bot.
TELEGRAM_BOT_SECRET  the same random string as on the backend; it unlocks
                     /auth/telegram. Required.
"""

import asyncio
import concurrent.futures
import json
import logging
import os
import time
import urllib.parse

try:
    import requests
    NetError = requests.exceptions.RequestException
except Exception:  # pragma: no cover - requirement listed in this folder
    requests = None
    NetError = Exception

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto,
                      KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update)
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
SECRET_ENV = "TELEGRAM_BOT_SECRET"   # shared with the backend; unlocks /auth/telegram
SITE_URL = os.environ.get("SITE_URL", "https://lockeddoor.ai").rstrip("/")
# Stripe Payment Links, one per paid tier (public URLs; checkout happens on Stripe).
PLAN_LINKS = [
    ("Starter · $7.99/mo", os.environ.get("PAY_LINK_SOPHOMORE", "https://buy.stripe.com/6oUfZh1jradL0he4098AE00")),
    ("Storyline challenge · $14.99/mo", os.environ.get("PAY_LINK_JUNIOR", "https://buy.stripe.com/5kQcN5aU13Pn4xu54d8AE01")),
    ("All site access · $19.99/mo", os.environ.get("PAY_LINK_SENIOR", "https://buy.stripe.com/3cI6oH4vD85D1li2W58AE02")),
]


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
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
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
    if not base.startswith("https://") and not base.startswith("http://localhost") \
            and not base.startswith("http://127.0.0.1"):
        raise RuntimeError(f"{URL_ENV} must be https:// — passwords and tokens travel over it.")
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
        raise BackendError("session expired", code="expired")
    return r


def _get(path, token=None, timeout=40):
    if requests is None:
        raise RuntimeError("Missing dependency 'requests'.")
    r = requests.get(_base() + path, headers=_headers(token), timeout=timeout)
    if r.status_code == 401 and token:
        raise BackendError("session expired", code="expired")
    return r


def _auth_payload(r):
    if r.status_code == 403:
        raise BackendError(
            "That email is not verified yet. Open the verification link the site sent "
            "you, then try again.", code="email_unverified")
    if r.status_code == 503:
        raise BackendError("The bot is not connected to the house yet "
                           f"({SECRET_ENV} is not set on the backend).")
    if r.status_code != 200:
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = ""
        raise BackendError(detail or f"Sign-in failed (HTTP {r.status_code})")
    data = r.json()
    return {"token": data["token"], "user_id": data["user_id"], "tier": data["tier"],
            "email": data.get("email") or "", "created": bool(data.get("created"))}


def _bot_secret() -> str:
    secret = os.environ.get(SECRET_ENV, "").strip()
    if not secret:
        raise RuntimeError(f"{SECRET_ENV} is not set (same value as on the backend).")
    return secret


def _telegram_auth(telegram_id, display_name):
    """The Telegram id is the account: first call creates it, later ones re-open it."""
    return _auth_payload(_post("/auth/telegram", {
        "telegram_id": telegram_id, "display_name": display_name, "secret": _bot_secret()}))


def _login(telegram_id, email, password):
    """Point this Telegram id at an existing website account instead."""
    return _auth_payload(_post("/auth/telegram/link", {
        "telegram_id": telegram_id, "email": email, "password": password,
        "secret": _bot_secret()}))


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
    r = _post("/chat", {"girl": girl, "message": message}, token=token, timeout=150)
    if r.status_code != 200:
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = ""
        raise BackendError(str(detail) or f"chat failed (HTTP {r.status_code})",
                           code="out_of_messages" if r.status_code == 402 else None)
    return r.json()


def _send_audit(token, girl):
    r = _post("/audit", {"girl": girl}, token=token, timeout=150)
    if r.status_code != 200:
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = ""
        detail_msg = detail.split("|")[-1] if "|" in detail else detail
        raise BackendError(str(detail_msg) or f"audit failed (HTTP {r.status_code})")
    data = r.json()
    if not data or not data.get("ok") or not data.get("audit"):
        raise BackendError("No audit right now. Try again in a moment.")
    return data


async def login(*args):
    return await asyncio.to_thread(_login, *args)

async def telegram_auth(*args):
    return await asyncio.to_thread(_telegram_auth, *args)

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

async def send_audit(*args):
    return await asyncio.to_thread(_send_audit, *args)


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


# While the user is in a girl's room a one-key reply keyboard stays under the
# composer, so leaving is a tap instead of remembering a command.
BACK_TO_HOUSE = "\U0001F3E0 Back to the house"
ROOM_KEYBOARD = ReplyKeyboardMarkup([[KeyboardButton(BACK_TO_HOUSE)]],
                                    resize_keyboard=True, is_persistent=True)


async def _ensure_session(update, force: bool = False):
    """The session for this chat, opening one from the Telegram id when there is none
    (first time: a fresh account, no email asked). Returns the record or None after
    telling the user why."""
    rec = _rec(update)
    if rec and rec.get("token") and not force:
        return rec
    user = update.effective_user
    try:
        sess = await telegram_auth(user.id, (user.first_name or "Player")[:40])
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the house right now: {exc}")
        return None
    created = sess.pop("created", False)
    store.set(update.effective_chat.id, **sess,
              active_girl=(rec or {}).get("active_girl"))
    if created:
        await _txt(update,
             "🏛️ Welcome to Sorority House — your account is open, no sign-up needed. "
             "Your Telegram is your key here.\n\n"
             "Already have an account on the website? /login <email> <password> once "
             "and this chat joins it (same history, same allowance).")
    return _rec(update)


async def _require_login(update) -> bool:
    return await _ensure_session(update) is not None


async def _call(update, fn, *args):
    """Backend call with the chat's token; a dead session (the bot was redeployed, or
    the site logged everyone out) is reopened from the Telegram id and retried once."""
    rec = await _ensure_session(update)
    if rec is None:
        raise BackendError("could not reopen your session — try again in a moment")
    try:
        return await fn(rec["token"], *args)
    except BackendError as exc:
        if exc.code != "expired":
            raise
    rec = await _ensure_session(update, force=True)
    if rec is None:
        raise BackendError("could not reopen your session — try again in a moment")
    return await fn(rec["token"], *args)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    had = bool(_rec(update) and _rec(update).get("token"))
    rec = await _ensure_session(update)
    if rec is None:
        return
    await _txt(update,
         ("Welcome back to the house. 💛\n\n" if had else
          "This is the Telegram way to talk to the same sisters as the website — one "
          "account, one history, one shared allowance. Doors open by trust, not by "
          "asking.\n\n")
         + "• /girls — knock on the doors that are open to you\n"
         "• just type a message to talk to whoever you're with\n"
         "• /audit — run a psychological audit for who you're talking to\n"
         "• /state — your allowance + where you stand with each sister\n"
         "• /menu — upgrade, the website, get the app\n"
         "• /help — everything")


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
        sess = await login(update.effective_user.id, email, password)
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not sign in: {exc}")
        return
    sess.pop("created", None)
    store.set(update.effective_chat.id, **sess, active_girl=None)
    await update.effective_message.reply_text(
         f"This Telegram is now {sess['email']}'s account — same history, same allowance "
         "here and on the site.\n\n/girls to knock on a door, /state for your allowance.",
         reply_markup=ReplyKeyboardRemove())


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store.forget(update.effective_chat.id)
    await update.effective_message.reply_text(
        "Forgot this chat's session. Your account stays where it is — the "
        "next message reopens it from your Telegram.", reply_markup=ReplyKeyboardRemove())


PORTRAIT_MAX_BYTES = 5 * 1024 * 1024  # Telegram's own sendPhoto ceiling is 10 MB
PORTRAIT_DEADLINE_S = 8.0  # end-to-end per download, not per socket read
# Portrait downloads get their own small pool so a slow image host can never occupy the
# default executor that login / roster / chat calls run on.
_portrait_pool = concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="portrait")


def _portrait_url(g) -> str:
    """Roster avatar_url is site-relative (assets/zoe.jpg) or absolute; only the site
    itself is fetched, so a roster edit cannot point the bot at internal hosts."""
    url = (g.get("avatar_url") or "").strip()
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url if url.startswith(SITE_URL + "/") else ""
    if url.startswith("//") or ".." in url:
        return ""
    return SITE_URL + "/" + url.lstrip("/")


def _fetch_bytes(url: str):
    deadline = time.monotonic() + PORTRAIT_DEADLINE_S
    with requests.get(url, timeout=(4, 4), stream=True, allow_redirects=False) as r:
        r.raise_for_status()
        if int(r.headers.get("Content-Length") or 0) > PORTRAIT_MAX_BYTES:
            raise ValueError("portrait too large")
        if time.monotonic() > deadline:
            raise TimeoutError("portrait download too slow")
        buf = bytearray()
        for chunk in r.iter_content(65536):
            buf.extend(chunk)
            if len(buf) > PORTRAIT_MAX_BYTES:
                raise ValueError("portrait too large")
            if time.monotonic() > deadline:
                raise TimeoutError("portrait download too slow")
    return bytes(buf)


def _fetch_portrait(url: str):
    return asyncio.get_running_loop().run_in_executor(_portrait_pool, _fetch_bytes, url)


async def _send_portrait(update, g, caption: str) -> bool:
    """Best effort: the portrait is decoration, never a reason to fail the command."""
    url = _portrait_url(g)
    if not url or requests is None:
        return False
    try:
        data = await _fetch_portrait(url)
        await update.effective_message.reply_photo(data, caption=caption[:1024])
        return True
    except Exception as exc:  # network, bad image, telegram refusing the format
        logger.info("portrait for %s skipped: %s", g.get("girl"), exc)
        return False


async def _send_album(update, girls) -> None:
    girls = [g for g in girls[:10] if _portrait_url(g) and requests is not None]
    if not girls:
        return
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(_fetch_portrait(_portrait_url(g)) for g in girls),
                           return_exceptions=True),
            timeout=PORTRAIT_DEADLINE_S * 4)
    except asyncio.TimeoutError:
        logger.info("album skipped: portraits took too long")
        return
    media = []
    for g, data in zip(girls, results):
        if isinstance(data, BaseException):
            logger.info("portrait for %s skipped: %s", g.get("girl"), data)
            continue
        media.append(InputMediaPhoto(data, caption=g.get("name", g.get("girl", ""))))
    if not media:
        return
    try:
        if len(media) == 1:
            await update.effective_message.reply_photo(media[0].media, caption=media[0].caption)
        else:
            await update.effective_message.reply_media_group(media)
    except Exception as exc:
        logger.info("album skipped: %s", exc)


def _milestone_label(milestone):
    stages = {1: "Stranger", 2: "Noticing", 3: "Opening", 4: "Opening",
              5: "Trusted", 6: "Confided", 7: "Confided", 8: "Different"}
    return stages.get(int(milestone or 1), "Stranger")


async def cmd_girls(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    rec = _rec(update)
    try:
        roster = (await _call(update, fetch_roster))["girls"]
        state = (await _call(update, fetch_state))["girls"]
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
        await _send_album(update, [g for g in sorted(roster, key=lambda x: x.get("girl", ""))
                                   if state.get(g["girl"], {}).get("open")])
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
        rosters = (await _call(update, fetch_roster))["girls"]
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the house: {exc}")
        return
    if sl not in [g["girl"] for g in rosters]:
        await _txt(update, "I don't recognise that sister. Try one of: "
                     + ", ".join(g["girl"] for g in rosters))
        return
    try:
        state = (await _call(update, fetch_state))["girls"].get(sl, {})
        if not state.get("open"):
            await _txt(update, f"That door is currently shut — {state.get('locked_reason', 'keep talking on the web and it may open.')}")
            return
        history = await _call(update, fetch_history, sl)
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the house: {exc}")
        return
    store.set(update.effective_chat.id, active_girl=sl)
    girl = next(g for g in rosters if g["girl"] == sl)
    await _send_portrait(update, girl, girl.get("door_title") or girl.get("name", sl))
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
    await update.effective_message.reply_text(msg[:4000], reply_markup=ROOM_KEYBOARD)


async def cmd_house(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Leave her room: forget the active girl, drop the room keyboard, show the doors."""
    if not await _require_login(update):
        return
    store.set(update.effective_chat.id, active_girl=None)
    await update.effective_message.reply_text("Back in the hallway.",
                                              reply_markup=ReplyKeyboardRemove())
    await cmd_girls(update, context)


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
        st = await _call(update, fetch_state)
        roster = (await _call(update, fetch_roster))["girls"]
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
        history = await _call(update, fetch_history, slug)
        rosters = (await _call(update, fetch_roster))["girls"]
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the house: {exc}")
        return
    if not history:
        await _txt(update, f"No history with {_girl_name(rosters, slug)} yet.")
        return
    parts = [_girl_name(rosters, slug) + " — recent messages:"]
    for m in history[-8:]:
        who = "You" if m["sender"] == "user" else "Her"
        body = m["message"]
        if len(body) > 450:
            body = body[:450] + " …"
        parts.append(f"{who}: {body}")
    await _txt(update, "\n\n".join(parts)[:4000])


async def cmd_audit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    rec = _rec(update)
    slug = rec.get("active_girl")
    if not slug:
        await _txt(update, "Pick someone first: /girls or /girl <slug>")
        return
    try:
        rosters = (await _call(update, fetch_roster))["girls"]
    except Exception:
        rosters = []
    girl_name = _girl_name(rosters, slug) if rosters else slug.replace("-", " ").title()
    await _txt(update, f"Compiling psychological audit for {girl_name}…")
    try:
        out = await _call(update, send_audit, slug)
    except BackendError as exc:
        await _txt(update, str(exc))
        return
    except (RuntimeError, NetError) as exc:
        await _txt(update, f"Could not compile audit right now: {exc}")
        return
    report = out.get("audit") or ""
    message = f"📋 Psychological Audit — {girl_name}\n\n{report}"
    for offset in range(0, len(message), 4000):
        await _txt(update, message[offset:offset + 4000])


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    await q.answer()
    data = q.data or ""
    if update.effective_chat.type != "private":
        return
    if data == "menu:upgrade":
        await cmd_upgrade(update, context)
        return
    if not await _require_login(update):
        return
    if data == "menu:girls":
        await cmd_girls(update, context)
    elif data.startswith("girl:"):
        await _open_girl(update, data.split(":", 1)[1])


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    rec = _rec(update)
    text = update.message.text or ""
    if text.strip() == BACK_TO_HOUSE:
        await cmd_house(update, context)
        return
    slug = rec.get("active_girl")
    if not slug:
        await _txt(update, "Who do you want to talk to?  Tap one on /girls, or  /girl <slug>.")
        return
    if not text.strip():
        return
    try:
        out = await _call(update, send_chat, slug, text)
    except BackendError as exc:
        msg = str(exc)
        if exc.code == "out_of_messages" or msg == "out_of_messages" or \
                "trial" in msg.lower() or "remaining" in msg.lower() or "allowance" in msg.lower():
            await update.effective_message.reply_text(
                "Your message allowance is spent. Upgrade or renew and you can keep "
                "talking here right away.",
                reply_markup=_plans_markup(_rec(update)))
            return
        await _txt(update, msg)
        return
    except (RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the house right now: {exc}")
        return
    rem = out.get("remaining")
    reply = out.get("reply") or "…"
    tail = f"\n\n(Messages left: {rem})" if isinstance(rem, int) else ""
    await _txt(update, reply + tail)


async def on_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A session is bound to a chat, so the house only talks one-to-one: in a group every
    member would share (and could log out) whoever signed in."""
    if update.effective_message and update.effective_message.text and \
            update.effective_message.text.startswith("/"):
        await _txt(update, "I only talk in private — message me directly.")


def _pay_url(url: str, rec) -> str:
    """Payment Link for this account: client_reference_id tells the backend's Stripe
    webhook which user paid (Telegram accounts have no email to match on), and a known
    email is prefilled so checkout is one screen."""
    if not rec or not rec.get("user_id"):
        return url
    q = {"client_reference_id": rec["user_id"]}
    if rec.get("email"):
        q["prefilled_email"] = rec["email"]
    return url + ("&" if "?" in url else "?") + urllib.parse.urlencode(q)


def _plans_markup(rec=None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("💳 " + label, url=_pay_url(url, rec))] for label, url in PLAN_LINKS])


def _menu_markup(signed_in: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("💳 Upgrade / renew", callback_data="menu:upgrade")],
        [InlineKeyboardButton("🌐 Open the website", url=SITE_URL),
         InlineKeyboardButton("📱 Get the app", url=SITE_URL + "/#hero-install")],
    ]
    if signed_in:
        rows.append([InlineKeyboardButton("💬 Pick a girl", callback_data="menu:girls")])
    return InlineKeyboardMarkup(rows)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rec = await _ensure_session(update)
    await update.effective_message.reply_text(
        "Sorority House — where to?\n\n"
        "Payments go through Stripe and your tier shows up in this chat and on the site. "
        "The app installs from the site — no app store.",
        reply_markup=_menu_markup(rec is not None))


async def cmd_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rec = await _ensure_session(update)
    if rec is None:
        return
    await update.effective_message.reply_text(
        "Pick a plan — checkout opens on Stripe (any email works there; the payment is "
        "tied to this Telegram). The house unlocks here, on the site and in the app.",
        reply_markup=_plans_markup(rec))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _txt(update,
         "Sorority House on Telegram — commands:\n"
         "/login <email> <password> — join this Telegram to your website account\n"
         "/signup <email> <password> <name> — make an email account (to use the site too)\n"
         "/girls — knock on the doors that are open\n"
         "/girl <slug> — switch who you're talking to\n"
         "/house — leave her room and go back to the doors\n"
         "/audit — run a psychological audit for her\n"
         "/state — tier, messages left, where you stand\n"
         "/history — the recent thread with her\n"
         "/menu — upgrade, open the website, get the app\n"
         "/upgrade — plans and the link to pay\n"
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
        _bot_secret()
    except RuntimeError as exc:
        raise SystemExit(f"{exc}")

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(~filters.ChatType.PRIVATE, on_group))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("signup", cmd_signup))
    app.add_handler(CommandHandler("login", cmd_login))
    app.add_handler(CommandHandler("logout", cmd_logout))
    app.add_handler(CommandHandler("girls", cmd_girls))
    app.add_handler(CommandHandler("girl", cmd_girl))
    app.add_handler(CommandHandler("house", cmd_house))
    app.add_handler(CommandHandler("audit", cmd_audit))
    app.add_handler(CommandHandler("state", cmd_state))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("upgrade", cmd_upgrade))
    app.add_handler(CallbackQueryHandler(on_button))  # buttons only exist in private chats
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    logger.info("Sorority House Telegram bot starting (backend: %s)", _base())
    app.run_polling()


if __name__ == "__main__":
    main()
