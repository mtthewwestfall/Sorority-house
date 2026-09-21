"""
KEYHOLE — Live WebCam Show Telegram Bot
=======================================

The Telegram front-end for the KEYHOLE Live WebCam Show backend (`main.py`).
Allows users to watch live previews, interact, and chat 1-on-1 with featured WebCam
models (Chloe and Bailey).

Your Telegram id is your account: the first message opens a fresh one on the
backend (`/auth/telegram`, unlocked by the TELEGRAM_BOT_SECRET shared with `main.py`).
`/login <email> <password>` points this Telegram at an existing website account.

Commands
--------
/start   — Welcome & WebCam lounge introduction
/login   — /login <email> <password>, join this Telegram to your website account
/signup  — /signup <email> <password> <display_name>, create an account
/models  — Show available WebCam show models (Chloe & Bailey)
/model   — /model <chloe|bailey>, switch who you are chatting with
/preview — View a live video/photo preview of your active model
/show    — Leave model chat room & return to the main lounge
/audit   — View model profile & status audit
/state   — Your account tier, webcam minutes & message balance
/history — Last messages with the current model
/menu    — Upgrade packages, WebCam show link & app
/logout  — Forget session (next message reopens same Telegram account)
/help    — Command reference

Env vars
--------
TELEGRAM_BOT_TOKEN   from @BotFather. Never put the value in any file.
PUBLIC_URL           the KEYHOLE backend base URL, e.g. Railway app URL.
                     Required (no default).
TELEGRAM_BOT_SECRET  shared secret with the backend; unlocks /auth/telegram.
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
except Exception:  # pragma: no cover
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
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("keyhole_tg")

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
URL_ENV = "PUBLIC_URL"
SECRET_ENV = "TELEGRAM_BOT_SECRET"
SITE_URL = os.environ.get("SITE_URL", "https://lockeddoor.ai").rstrip("/")

# Restrict available models strictly to Chloe and Bailey
ALLOWED_MODELS = {"chloe", "bailey"}

# Stripe Payment Links for WebCam show packages & tiers
PLAN_LINKS = [
    ("Keyhole Private Pass · $19.99", os.environ.get("PAY_LINK_PRIVATE", "https://buy.stripe.com/3cI6oH4vD85D1li2W58AE02")),
    ("Keyhole Lounge Pass · $4.99", os.environ.get("PAY_LINK_PUBLIC", "https://buy.stripe.com/6oUfZh1jradL0he4098AE00")),
]

# ---------------------------------------------------------------------------
# Session store
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
# Backend client
# ---------------------------------------------------------------------------
def _base() -> str:
    base = os.environ.get(URL_ENV, "").strip().rstrip("/")
    if not base:
        raise RuntimeError(f"{URL_ENV} is not set (the KEYHOLE backend).")
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
            "That email is not verified yet. Open the verification link sent to your email, "
            "then try again.", code="email_unverified")
    if r.status_code == 503:
        raise BackendError("The bot is not connected to the lounge yet "
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
    return _auth_payload(_post("/auth/telegram", {
        "telegram_id": telegram_id, "display_name": display_name, "secret": _bot_secret()}))


def _login(telegram_id, email, password):
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
        raise BackendError(f"Could not load the models (HTTP {r.status_code})")
    data = r.json()
    girls = data.get("girls", [])
    # Strictly filter roster to Chloe and Bailey for WebCam show
    filtered = [g for g in girls if g.get("girl") in ALLOWED_MODELS]
    return {"girls": filtered}


def _fetch_state(token):
    r = _get("/state", token=token)
    if r.status_code != 200:
        raise BackendError(f"Could not load your state (HTTP {r.status_code})")
    return r.json()


def _fetch_history(token, girl):
    if girl not in ALLOWED_MODELS:
        return []
    r = _get(f"/history?girl={girl}", token=token)
    if r.status_code != 200:
        raise BackendError(f"Could not load history (HTTP {r.status_code})")
    return r.json().get("messages", [])


def _send_chat(token, girl, message):
    if girl not in ALLOWED_MODELS:
        raise BackendError("Only Chloe and Bailey are available on the WebCam show.")
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
    if girl not in ALLOWED_MODELS:
        raise BackendError("Audit is only available for Chloe and Bailey.")
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
        raise BackendError("No audit available right now. Try again in a moment.")
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


# Roster & presentation helpers ------------------------------------------------
def _girl_name(girls, slug):
    for g in girls:
        if g["girl"] == slug:
            return g["name"]
    return slug.replace("-", " ").title()


def _cmd_args(update) -> list:
    text = (update.message or update.effective_message).text or ""
    parts = text.split()
    return parts[1:] if len(parts) > 1 else []


def _active_model(rec) -> str | None:
    slug = (rec or {}).get("active_girl")
    if slug and slug.lower() in ALLOWED_MODELS:
        return slug.lower()
    return None


# WebCam room keyboard controls
BACK_TO_LOUNGE = "🎥 Main Lounge"
PREVIEW_BTN = "📷 Live Preview"
ROOM_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton(PREVIEW_BTN), KeyboardButton(BACK_TO_LOUNGE)]],
    resize_keyboard=True, is_persistent=True
)


async def _txt(update, text) -> None:
    await update.effective_message.reply_text(text)


async def _ensure_session(update, force: bool = False):
    rec = store.get(update.effective_chat.id)
    if rec and rec.get("token") and not force:
        return rec
    user = update.effective_user
    try:
        sess = await telegram_auth(user.id, (user.first_name or "Viewer")[:40])
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the WebCam show server: {exc}")
        return None
    created = sess.pop("created", False)
    active = (rec or {}).get("active_girl")
    if active not in ALLOWED_MODELS:
        active = None
    store.set(update.effective_chat.id, **sess, active_girl=active)
    if created:
        await _txt(update,
             "📹 Welcome to KEYHOLE Live WebCam Show — your account is open!\n"
             "Your Telegram id is your instant pass.\n\n"
             "Already have a web account? Use /login <email> <password> to link it.")
    return store.get(update.effective_chat.id)


async def _require_login(update) -> bool:
    return await _ensure_session(update) is not None


async def _call(update, fn, *args):
    rec = await _ensure_session(update)
    if rec is None:
        raise BackendError("Could not reopen session — please try again.")
    try:
        return await fn(rec["token"], *args)
    except BackendError as exc:
        if exc.code != "expired":
            raise
    rec = await _ensure_session(update, force=True)
    if rec is None:
        raise BackendError("Could not reopen session — please try again.")
    return await fn(rec["token"], *args)


# Portrait & Media Fetching ----------------------------------------------------
PORTRAIT_MAX_BYTES = 10 * 1024 * 1024
PORTRAIT_DEADLINE_S = 8.0
_portrait_pool = concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="portrait")


def _portrait_url(g) -> str:
    url = (g.get("avatar_url") or "").strip()
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url if url.startswith(SITE_URL + "/") or url.startswith(_base() + "/") else ""
    if url.startswith("//") or ".." in url:
        return ""
    return SITE_URL + "/" + url.lstrip("/")


def _fetch_bytes(url: str):
    deadline = time.monotonic() + PORTRAIT_DEADLINE_S
    with requests.get(url, timeout=(4, 4), stream=True, allow_redirects=False) as r:
        r.raise_for_status()
        if int(r.headers.get("Content-Length") or 0) > PORTRAIT_MAX_BYTES:
            raise ValueError("media file too large")
        if time.monotonic() > deadline:
            raise TimeoutError("media download timed out")
        buf = bytearray()
        for chunk in r.iter_content(65536):
            buf.extend(chunk)
            if len(buf) > PORTRAIT_MAX_BYTES:
                raise ValueError("media file too large")
            if time.monotonic() > deadline:
                raise TimeoutError("media download timed out")
    return bytes(buf)


def _fetch_portrait(url: str):
    return asyncio.get_running_loop().run_in_executor(_portrait_pool, _fetch_bytes, url)


async def _send_portrait(update, g, caption: str) -> bool:
    url = _portrait_url(g)
    if not url or requests is None:
        return False
    try:
        data = await _fetch_portrait(url)
        await update.effective_message.reply_photo(data, caption=caption[:1024])
        return True
    except Exception as exc:
        logger.info("Portrait send for %s skipped: %s", g.get("girl"), exc)
        return False


async def _send_preview(update, slug: str, token: str | None = None) -> None:
    sl = slug.strip().lower()
    if sl not in ALLOWED_MODELS:
        await _txt(update, "Live preview is available for Chloe and Bailey.")
        return

    await _txt(update, f"📹 Fetching live preview for {sl.capitalize()}...")

    asset_url = ""
    media_type = "photo"

    try:
        if token:
            r = await asyncio.to_thread(_get, f"/media/character/{sl}/default", token)
            if r.status_code == 200 and r.json().get("ok") and r.json().get("asset"):
                ast = r.json()["asset"]
                asset_url = ast.get("url", "")
                if ast.get("media_type") == "video":
                    media_type = "video"
    except Exception as exc:
        logger.info("Media endpoint fetch error for preview: %s", exc)

    if not asset_url:
        try:
            roster = (await _call(update, fetch_roster))["girls"]
            for g in roster:
                if g.get("girl") == sl:
                    asset_url = _portrait_url(g)
                    break
        except Exception:
            pass

    if not asset_url:
        await _txt(update, f"Preview for {sl.capitalize()} is currently offline. Try again in a moment!")
        return

    parsed = urllib.parse.urlparse(asset_url)
    if parsed.scheme not in ("http", "https"):
        await _txt(update, "Invalid preview media URL.")
        return

    caption = f"🎥 Live WebCam Preview — {sl.capitalize()}"

    try:
        if media_type == "video" and asset_url.endswith((".mp4", ".webm")):
            await update.effective_message.reply_video(asset_url, caption=caption)
            return
        elif asset_url.startswith("http://") or asset_url.startswith("https://"):
            data = await _fetch_portrait(asset_url)
            await update.effective_message.reply_photo(data, caption=caption)
            return
    except Exception as exc:
        logger.info("Direct media delivery skipped for preview (%s): %s", asset_url, exc)

    await _txt(update, f"{caption}\n🔗 Stream: {asset_url}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    had = bool(store.get(update.effective_chat.id) and store.get(update.effective_chat.id).get("token"))
    rec = await _ensure_session(update)
    if rec is None:
        return
    await _txt(update,
         ("Welcome back to KEYHOLE Live WebCam Show. 📹\n\n" if had else
          "Welcome to KEYHOLE Live WebCam Show! Chat live 1-on-1 and watch interactive shows with our featured models.\n\n")
         + "• /models — view models live right now (Chloe & Bailey)\n"
         "• /model <chloe|bailey> — connect with a model\n"
         "• /preview — view live webcam preview\n"
         "• /show — return to main lounge\n"
         "• /state — check your webcam minutes & messages left\n"
         "• /menu — view packages and web app link\n"
         "• /help — list all commands")


async def cmd_signup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        await _txt(update, "Please sign up in a private chat.")
        return
    args = _cmd_args(update)
    if len(args) < 3:
        await _txt(update, "Usage:  /signup <email> <password> <your name>")
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
             "Account created. 🎉 Check your email for verification, then /login <email> <password>.")
    else:
        await _txt(update, "Account created & verified! Use /models to connect with Chloe or Bailey.")


async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        await _txt(update, "Please login in a private chat.")
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
         f"Logged in as {sess['email']}. Use /models to start watching!",
         reply_markup=ReplyKeyboardRemove())


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store.forget(update.effective_chat.id)
    await update.effective_message.reply_text(
        "Logged out. Your session is cleared.", reply_markup=ReplyKeyboardRemove())


async def cmd_models(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    try:
        roster = (await _call(update, fetch_roster))["girls"]
        state = (await _call(update, fetch_state))["girls"]
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not fetch models: {exc}")
        return

    open_btns = []
    for g in roster:
        slug = g["girl"]
        if slug in ALLOWED_MODELS:
            st = state.get(slug, {})
            label = f"📹 {g.get('name', slug.title())} · Live WebCam"
            open_btns.append([InlineKeyboardButton(label, callback_data=f"girl:{slug}")])

    await update.effective_message.reply_text(
        "📹 Featured WebCam Models — Live Now:",
        reply_markup=InlineKeyboardMarkup(open_btns) if open_btns else None)


async def _open_girl(update, slug) -> None:
    sl = slug.strip().lower()
    if sl not in ALLOWED_MODELS:
        await _txt(update, "Only Chloe and Bailey are available on the WebCam show right now. Use /models to connect!")
        return

    try:
        rosters = (await _call(update, fetch_roster))["girls"]
        history = await _call(update, fetch_history, sl)
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not connect to model: {exc}")
        return

    store.set(update.effective_chat.id, active_girl=sl)
    girl = next((g for g in rosters if g["girl"] == sl), {"girl": sl, "name": sl.capitalize()})
    await _send_portrait(update, girl, f"📹 Connected live with {girl.get('name', sl.capitalize())}")

    if history:
        parts = [f"💬 Live chat thread with {girl.get('name', sl.capitalize())}:"]
        for m in history[-6:]:
            who = "You" if m["sender"] == "user" else girl.get('name', sl.capitalize())
            parts.append(f"{who}: {m['message'][:240]}")
        msg = "\n\n".join(parts)
    else:
        msg = f"You are now live with {girl.get('name', sl.capitalize())}! Say hi or tap 📷 Live Preview."

    await update.effective_message.reply_text(msg[:4000], reply_markup=ROOM_KEYBOARD)


async def cmd_girl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    args = _cmd_args(update)
    if not args:
        await _txt(update, "Usage: /model <chloe|bailey>")
        return
    await _open_girl(update, args[0])


async def cmd_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    rec = store.get(update.effective_chat.id)
    slug = _active_model(rec)
    args = _cmd_args(update)
    if args and args[0].lower() in ALLOWED_MODELS:
        slug = args[0].lower()
    if not slug:
        await _txt(update, "Select a model first: /models or /model <chloe|bailey>")
        return
    await _send_preview(update, slug, token=(rec or {}).get("token"))


async def cmd_house(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    store.set(update.effective_chat.id, active_girl=None)
    await update.effective_message.reply_text("Returned to the Main WebCam Lounge.",
                                              reply_markup=ReplyKeyboardRemove())
    await cmd_models(update, context)


async def cmd_state(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    try:
        st = await _call(update, fetch_state)
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not load state: {exc}")
        return
    lines = [f"🏷️ Account Tier: {st.get('tier', 'Visitor')}"]
    rem = st.get("remaining")
    lines.append(f"💬 Message balance: {rem}" if isinstance(rem, int) else "💬 Balance: Active")
    webcam_mins = st.get("webcam_minutes_left", 0)
    lines.append(f"📹 WebCam show minutes left: {webcam_mins}")
    lines.append("\nFeatured Live Models:\n• Chloe\n• Bailey")
    await _txt(update, "\n".join(lines))


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    rec = store.get(update.effective_chat.id)
    slug = _active_model(rec)
    if not slug:
        await _txt(update, "Select a model first: /models or /model <chloe|bailey>")
        return
    try:
        history = await _call(update, fetch_history, slug)
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not load history: {exc}")
        return
    if not history:
        await _txt(update, f"No previous messages with {slug.capitalize()}.")
        return
    parts = [f"Recent chat with {slug.capitalize()}:"]
    for m in history[-8:]:
        who = "You" if m["sender"] == "user" else slug.capitalize()
        parts.append(f"{who}: {m['message'][:450]}")
    await _txt(update, "\n\n".join(parts)[:4000])


async def cmd_audit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    rec = store.get(update.effective_chat.id)
    slug = _active_model(rec)
    if not slug:
        await _txt(update, "Select a model first: /models or /model <chloe|bailey>")
        return
    await _txt(update, f"Compiling profile audit for {slug.capitalize()}…")
    try:
        out = await _call(update, send_audit, slug)
    except (BackendError, RuntimeError, NetError) as exc:
        await _txt(update, f"Could not load audit: {exc}")
        return
    report = out.get("audit") or ""
    await _txt(update, f"📋 Profile Audit — {slug.capitalize()}\n\n{report}"[:4000])


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
    if data == "menu:models":
        await cmd_models(update, context)
    elif data.startswith("girl:"):
        await _open_girl(update, data.split(":", 1)[1])


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_login(update):
        return
    rec = store.get(update.effective_chat.id)
    text = (update.message.text or "").strip()

    if text == BACK_TO_LOUNGE or text == "\U0001F3E0 Back to the house":
        await cmd_house(update, context)
        return

    slug = _active_model(rec)

    if text == PREVIEW_BTN:
        if not slug:
            await _txt(update, "Select a model first: /models")
            return
        await _send_preview(update, slug, token=(rec or {}).get("token"))
        return

    if not slug:
        await _txt(update, "Who would you like to chat with? Tap /models or /model <chloe|bailey>.")
        return

    try:
        out = await _call(update, send_chat, slug, text)
    except BackendError as exc:
        msg = str(exc)
        if exc.code == "out_of_messages" or "remaining" in msg.lower() or "allowance" in msg.lower():
            await update.effective_message.reply_text(
                "You need additional WebCam show minutes or message balance to continue.",
                reply_markup=_plans_markup(store.get(update.effective_chat.id)))
            return
        await _txt(update, msg)
        return
    except (RuntimeError, NetError) as exc:
        await _txt(update, f"Could not reach the WebCam show server: {exc}")
        return

    rem = out.get("remaining")
    reply = out.get("reply") or "…"
    tail = f"\n\n(Messages left: {rem})" if isinstance(rem, int) else ""
    await _txt(update, reply + tail)


async def on_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message and update.effective_message.text and update.effective_message.text.startswith("/"):
        await _txt(update, "KEYHOLE WebCam Show bot operates in private chats only.")


def _pay_url(url: str, rec) -> str:
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
        [InlineKeyboardButton("💳 WebCam Show Packages", callback_data="menu:upgrade")],
        [InlineKeyboardButton("🌐 KEYHOLE Web Lounge", url=SITE_URL + "/community-cam.html")],
    ]
    if signed_in:
        rows.append([InlineKeyboardButton("📹 Select Model (Chloe / Bailey)", callback_data="menu:models")])
    return InlineKeyboardMarkup(rows)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rec = await _ensure_session(update)
    await update.effective_message.reply_text(
        "KEYHOLE Live WebCam Show Menu:\n\n"
        "Unlock 1-on-1 private webcam shows and lounge access instantly.",
        reply_markup=_menu_markup(rec is not None))


async def cmd_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rec = await _ensure_session(update)
    if rec is None:
        return
    await update.effective_message.reply_text(
        "Select a WebCam show package:",
        reply_markup=_plans_markup(rec))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _txt(update,
         "KEYHOLE WebCam Show — Command Reference:\n"
         "/models — view featured live models (Chloe & Bailey)\n"
         "/model <chloe|bailey> — connect with a model\n"
         "/preview — view live webcam media preview\n"
         "/show — return to the main lounge\n"
         "/audit — view model profile & state\n"
         "/state — check account balance & webcam minutes\n"
         "/history — view recent chat thread\n"
         "/login <email> <password> — link your website account\n"
         "/signup <email> <password> <name> — create an account\n"
         "/menu — view WebCam show packages & link\n"
         "/upgrade — purchase webcam show passes\n"
         "/logout — end session\n"
         "/help — list commands")


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
    app.add_handler(CommandHandler(["models", "girls"], cmd_models))
    app.add_handler(CommandHandler(["model", "girl"], cmd_girl))
    app.add_handler(CommandHandler("preview", cmd_preview))
    app.add_handler(CommandHandler(["show", "house"], cmd_house))
    app.add_handler(CommandHandler("audit", cmd_audit))
    app.add_handler(CommandHandler("state", cmd_state))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("upgrade", cmd_upgrade))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    logger.info("KEYHOLE WebCam Show Telegram Bot starting (backend: %s)", _base())
    app.run_polling()


if __name__ == "__main__":
    main()
