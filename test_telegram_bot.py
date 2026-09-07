import unittest

from telegram_bot import BackendError, BotApp


class FakeLinks:
    def __init__(self):
        self.rows = {}

    def init(self):
        pass

    def get(self, chat_id):
        return self.rows.get(chat_id)

    def put(self, chat_id, token, selected_girl=""):
        self.rows[chat_id] = (token, selected_girl)

    def select(self, chat_id, girl):
        token, _ = self.rows[chat_id]
        self.rows[chat_id] = (token, girl)

    def delete(self, chat_id):
        self.rows.pop(chat_id, None)


class FakeBackend:
    def __init__(self):
        self.messages = []
        self.locked = False
        self.limited = False

    def signup(self, email, password, display_name):
        return {"ok": True, "needs_verification": True, "email_sent": True}

    def login(self, email, password):
        return {"token": "token-1", "tier": "freshman"}

    def logout(self, token):
        return {"ok": True}

    def roster(self, token):
        return [
            {"slug": "dakota", "name": "Dakota", "open": True},
            {"slug": "veronica", "name": "Veronica", "open": False},
        ]

    def chat(self, token, girl, message):
        self.messages.append((token, girl, message))
        if self.locked:
            raise BackendError(403, "This door is locked for your tier")
        if self.limited:
            raise BackendError(402, "out_of_messages")
        return {"reply": f"{girl} says: {message}"}


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.actions = []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))

    def typing(self, chat_id):
        self.actions.append(chat_id)


class TelegramSmokeTest(unittest.TestCase):
    def setUp(self):
        self.telegram = FakeTelegram()
        self.backend = FakeBackend()
        self.links = FakeLinks()
        self.app = BotApp(self.telegram, self.backend, self.links)

    def update(self, text):
        self.app.handle({"message": {"chat": {"id": 7}, "text": text}})

    def test_link_roster_select_round_trip_and_errors(self):
        self.update("/login player@example.com password123")
        self.assertEqual(self.links.get(7), ("token-1", ""))

        self.update("/girls")
        self.assertIn("Dakota (dakota) — open", self.telegram.sent[-1][1])
        self.assertIn("Veronica (veronica) — locked", self.telegram.sent[-1][1])

        self.update("/talk Dakota")
        self.assertEqual(self.links.get(7), ("token-1", "dakota"))
        self.update("Hello Dakota")
        self.assertEqual(self.backend.messages[-1], ("token-1", "dakota", "Hello Dakota"))
        self.assertEqual(self.telegram.actions, [7])
        self.assertIn("dakota says: Hello Dakota", self.telegram.sent[-1][1])

        self.backend.locked = True
        self.update("Open up")
        self.assertEqual(self.telegram.sent[-1][1], "That door is locked for your tier.")

        self.backend.locked = False
        self.backend.limited = True
        self.update("One more")
        self.assertEqual(
            self.telegram.sent[-1][1],
            "You’ve reached your message limit. Upgrade your tier to keep chatting.",
        )

    def test_signup_without_token_is_not_linked(self):
        self.update("/signup player@example.com password123")
        self.assertIsNone(self.links.get(7))
        self.assertIn("Confirm the verification email", self.telegram.sent[-1][1])


if __name__ == "__main__":
    unittest.main()
