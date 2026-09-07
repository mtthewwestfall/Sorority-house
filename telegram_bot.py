"""Telegram front-end for the Sorority House HTTP API.

Run this module as a separate process. It never imports the FastAPI app or
accesses any of the product tables; the only persisted bot state is the
chat-to-bearer-token link in ``telegram_links``.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests


LOG = logging.getLogger("sorority.telegram")
API_BASE_URL = os.environ.get(
    "API_BASE_URL", "https://sorority-house-production-aeb5.up.railway.app"
).rstrip("/")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
REQUEST_TIMEOUT = 45
MAX_UPDATE_RETRIES = 3


class BackendError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class BackendClient:
    def __init__(self, base_url: str = API_BASE_URL, session: Any = requests):
        self.base_url = base_url.rstrip("/")
        self.session = session

    def _request(self, method: str, path: str, token: str | None = None, **kwargs: Any) -> dict:
        headers = kwargs.pop("headers", {}).copy()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self.session.request(
                method, self.base_url + path, headers=headers,
                timeout=REQUEST_TIMEOUT, **kwargs
            )
        except requests.RequestException as exc:
            raise BackendError(0, "The Sorority House backend is temporarily unreachable.") from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not response.ok:
            detail = payload.get("detail", "The backend returned an error.")
            raise BackendError(response.status_code, str(detail))
        return payload

    def signup(self, email: str, password: str, display_name: str) -> dict:
        return self._request(
            "POST", "/auth/signup",
            json={"email": email, "password": password, "display_name": display_name},
        )

    def login(self, email: str, password: str) -> dict:
        return self._request(
            "POST", "/auth/login",
            json={"email": email, "password": password},
        )

    def roster(self, token: str) -> list[dict]:
        try:
            payload = self._request("GET", "/roster", token)
        except BackendError as exc:
            if exc.status != 404:
                raise
            state = self._request("GET", "/state", token)
            return [
                {"slug": slug, "name": slug.title(), "open": info.get("open", False)}
                for slug, info in state.get("girls", {}).items()
            ]
        girls = payload if isinstance(payload, list) else payload.get("girls", [])
        return [
            {
                "slug": item.get("slug", item.get("girl", "")),
                "name": item.get("name", item.get("slug", item.get("girl", ""))).title(),
                "open": item.get("open", True),
            }
            for item in girls
            if item.get("slug", item.get("girl"))
        ]

    def chat(self, token: str, girl: str, message: str) -> dict:
        return self._request(
            "POST", "/chat", token, json={"girl": girl, "message": message}
        )

    def logout(self, token: str) -> dict:
        return self._request("POST", "/auth/logout", token)


class TelegramApi:
    def __init__(self, bot_token: str, session: Any = requests):
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.session = session

    def call(self, method: str, **params: Any) -> Any:
        for attempt in range(3):
            try:
                response = self.session.post(
                    f"{self.base_url}/{method}", json=params, timeout=REQUEST_TIMEOUT
                )
                payload = response.json()
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
                continue
            if response.status_code == 429:
                retry_after = payload.get("parameters", {}).get("retry_after", 1)
                time.sleep(min(int(retry_after), 30))
                continue
            if not payload.get("ok"):
                raise RuntimeError(payload.get("description", "Telegram API error"))
            return payload.get("result")
        raise RuntimeError("Telegram rate limit did not clear")

    def updates(self, offset: int | None) -> list[dict]:
        return self.call("getUpdates", offset=offset, timeout=30, allowed_updates=["message"])

    def send(self, chat_id: int, text: str) -> Any:
        return self.call("sendMessage", chat_id=chat_id, text=text)

    def typing(self, chat_id: int) -> Any:
        return self.call("sendChatAction", chat_id=chat_id, action="typing")


class LinkStore:
    def __init__(self, database_url: str = DATABASE_URL, connect: Callable | None = None):
        self.database_url = database_url
        self.connect = connect or self._connect

    def _dsn(self) -> str:
        """The connection string with TLS required, as the backend does it: the row
        this stores is a live session credential, so it must not cross the network
        in the clear because someone left sslmode off the URL."""
        url = self.database_url
        if url and "sslmode" not in url:
            url = url + ("&" if "?" in url else "?") + "sslmode=require"
        return url

    def _connect(self):
        import psycopg2

        return psycopg2.connect(self._dsn())

    def init(self) -> None:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS telegram_links (
                        chat_id BIGINT PRIMARY KEY,
                        token TEXT NOT NULL,
                        selected_girl TEXT NOT NULL DEFAULT '',
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            conn.commit()
        finally:
            conn.close()

    def get(self, chat_id: int) -> tuple[str, str] | None:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT token, selected_girl FROM telegram_links WHERE chat_id=%s",
                    (chat_id,),
                )
                row = cur.fetchone()
                return tuple(row) if row else None
        finally:
            conn.close()

    def put(self, chat_id: int, token: str, selected_girl: str = "") -> None:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO telegram_links (chat_id, token, selected_girl)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (chat_id) DO UPDATE SET
                        token=EXCLUDED.token,
                        selected_girl=EXCLUDED.selected_girl,
                        updated_at=now()
                    """,
                    (chat_id, token, selected_girl),
                )
            conn.commit()
        finally:
            conn.close()

    def select(self, chat_id: int, girl: str) -> None:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE telegram_links SET selected_girl=%s, updated_at=now() WHERE chat_id=%s",
                    (girl, chat_id),
                )
            conn.commit()
        finally:
            conn.close()

    def delete(self, chat_id: int) -> None:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM telegram_links WHERE chat_id=%s", (chat_id,))
            conn.commit()
        finally:
            conn.close()


@dataclass
class BotApp:
    telegram: Any
    backend: Any
    links: Any

    def send(self, chat_id: int, text: str) -> None:
        self.telegram.send(chat_id, text[:4096])

    def notify(self, chat_id: int, text: str) -> None:
        try:
            self.send(chat_id, text)
        except Exception:
            LOG.exception("Telegram delivery failed")

    def handle(self, update: dict) -> None:
        message = update.get("message", {})
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None or not text:
            return
        if chat.get("type", "private") != "private":
            self.send(chat_id, "For account privacy, please message Mia bot directly instead of using a group.")
            return
        if text.startswith("/"):
            command, _, args = text.partition(" ")
            self.command(chat_id, command.split("@", 1)[0].lower(), args.strip())
        else:
            self.talk(chat_id, text)

    @staticmethod
    def credentials(args: str) -> tuple[str, str] | None:
        email, separator, password = args.partition(" ")
        if not separator or not email or not password:
            return None
        return email, password

    def command(self, chat_id: int, command: str, args: str) -> None:
        try:
            if command in ("/start", "/help"):
                self.send(chat_id, "Welcome to Mia bot. Use /signup email password or /login email password, then /girls and /talk <name>.")
            elif command == "/signup":
                credentials = self.credentials(args)
                if credentials is None:
                    self.send(chat_id, "Usage: /signup email password (password must be at least 8 characters).")
                    return
                result = self.backend.signup(credentials[0], credentials[1], "Telegram Player")
                self.notify(
                    chat_id,
                    "Account created. Confirm the verification email, then use /login email password.",
                )
                if not result.get("email_sent", True):
                    self.notify(
                        chat_id,
                        "The backend could not send the verification email; ask the owner to verify this account in admin.",
                    )
            elif command == "/login":
                credentials = self.credentials(args)
                if credentials is None:
                    self.send(chat_id, "Usage: /login email password")
                    return
                result = self.backend.login(credentials[0], credentials[1])
                self.links.put(chat_id, result["token"])
                self.notify(chat_id, "You’re logged in. Use /girls, then /talk <name>.")
            elif command in ("/girls", "/roster"):
                self.show_roster(chat_id)
            elif command == "/talk":
                self.select_girl(chat_id, args)
            elif command == "/logout":
                link = self.links.get(chat_id)
                if link:
                    try:
                        self.backend.logout(link[0])
                    finally:
                        self.links.delete(chat_id)
                self.notify(chat_id, "You’re logged out.")
            else:
                self.send(chat_id, "Unknown command. Try /start, /login, /girls, or /talk <name>.")
        except BackendError as exc:
            self.send(chat_id, self.error_text(exc))

    def show_roster(self, chat_id: int) -> None:
        link = self.require_login(chat_id)
        if not link:
            return
        rows = self.backend.roster(link[0])
        if not rows:
            self.send(chat_id, "No characters are available right now.")
            return
        lines = ["Characters:"]
        for row in rows:
            status = "open" if row["open"] else "locked"
            lines.append(f"- {row['name']} ({row['slug']}) — {status}")
        self.send(chat_id, "\n".join(lines))

    def select_girl(self, chat_id: int, name: str) -> None:
        link = self.require_login(chat_id)
        if not link:
            return
        slug = name.strip().lower().replace(" ", "-")
        rows = self.backend.roster(link[0])
        match = next((row for row in rows if row["slug"] == slug or row["name"].lower() == name.lower()), None)
        if not match:
            self.send(chat_id, "I don’t know that character. Use /girls.")
        elif not match["open"]:
            self.send(chat_id, "That door is locked for your tier.")
        else:
            self.links.select(chat_id, match["slug"])
            self.send(chat_id, f"You’re now talking with {match['name']}. Send a message.")

    def talk(self, chat_id: int, text: str) -> None:
        link = self.require_login(chat_id)
        if not link:
            return
        token, girl = link
        if not girl:
            self.send(chat_id, "Choose someone first with /talk <name>.")
            return
        try:
            self.telegram.typing(chat_id)
            result = self.backend.chat(token, girl, text)
            try:
                self.send(chat_id, result["reply"])
            except Exception:
                LOG.exception("Chat reply was generated but Telegram delivery failed")
        except BackendError as exc:
            self.send(chat_id, self.error_text(exc))

    def require_login(self, chat_id: int) -> tuple[str, str] | None:
        link = self.links.get(chat_id)
        if not link:
            self.send(chat_id, "Please use /login email password first.")
        return link

    def error_text(self, error: BackendError) -> str:
        if error.status == 401:
            return "Your login expired. Please use /login email password again."
        if error.status == 403:
            if error.detail.startswith("email_unverified"):
                return "Check your inbox and confirm your verification email before logging in."
            return "That door is locked for your tier."
        if error.status == 402 or error.detail == "out_of_messages":
            return "You’ve reached your message limit. Upgrade your tier to keep chatting."
        return error.detail


def process_updates(
    app: BotApp,
    updates: list[dict],
    offset: int | None,
    failures: dict[int, int] | None = None,
) -> tuple[int | None, bool, dict[int, int]]:
    failures = failures if failures is not None else {}
    for update in updates:
        update_id = update["update_id"]
        try:
            app.handle(update)
        except Exception:
            failures[update_id] = failures.get(update_id, 0) + 1
            if failures[update_id] < MAX_UPDATE_RETRIES:
                LOG.exception("Unhandled Telegram update; retry %d", failures[update_id])
                return offset, False, failures
            LOG.exception("Dropping Telegram update after %d failures", failures[update_id])
            failures.pop(update_id)
        offset = update_id + 1
    return offset, True, failures


def run() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required")
    links = LinkStore()
    links.init()
    app = BotApp(TelegramApi(TELEGRAM_BOT_TOKEN), BackendClient(), links)
    offset = None
    failures: dict[int, int] = {}
    while True:
        try:
            updates = app.telegram.updates(offset)
        except Exception:
            LOG.exception("Telegram polling failed")
            time.sleep(5)
            continue
        offset, processed, failures = process_updates(app, updates, offset, failures)
        if not processed:
            time.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    run()
