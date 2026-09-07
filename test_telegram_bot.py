import unittest

from telegram_bot import BackendError, BotApp, LinkStore, process_updates


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
        self.login_args = []
        self.locked = False
        self.limited = False

    def signup(self, email, password, display_name):
        return {"ok": True, "needs_verification": True, "email_sent": True}

    def login(self, email, password):
        self.login_args.append((email, password))
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

    def test_login_preserves_spaces_in_password(self):
        self.update("/login player@example.com pass word 123")
        self.assertEqual(self.backend.login_args, [("player@example.com", "pass word 123")])

    def test_login_delivery_failure_does_not_replay_backend_login(self):
        class FailingTelegram(FakeTelegram):
            def send(self, chat_id, text):
                raise RuntimeError("delivery failed")

        app = BotApp(FailingTelegram(), self.backend, self.links)
        with self.assertLogs("sorority.telegram", level="ERROR"):
            offset, processed, failures = process_updates(
                app,
                [{"update_id": 1, "message": {
                    "chat": {"id": 7},
                    "text": "/login player@example.com password123",
                }}],
                None,
            )
        self.assertEqual(offset, 2)
        self.assertTrue(processed)
        self.assertEqual(failures, {})
        self.assertEqual(self.backend.login_args, [("player@example.com", "password123")])
        self.assertEqual(self.links.get(7), ("token-1", ""))

    def test_group_messages_cannot_use_a_linked_account(self):
        self.app.handle({"message": {
            "chat": {"id": 7, "type": "group"},
            "text": "/login player@example.com password123",
        }})
        self.assertIsNone(self.links.get(7))
        self.assertIn("message Mia bot directly", self.telegram.sent[-1][1])

    def test_failed_update_stops_batch_without_skipping_it(self):
        class FailingApp:
            def __init__(self):
                self.seen = []

            def handle(self, update):
                self.seen.append(update["update_id"])
                if update["update_id"] == 2:
                    raise RuntimeError("temporary failure")

        app = FailingApp()
        with self.assertLogs("sorority.telegram", level="ERROR"):
            offset, processed, failures = process_updates(
                app,
                [{"update_id": 1}, {"update_id": 2}, {"update_id": 3}],
                1,
            )
        self.assertEqual(app.seen, [1, 2])
        self.assertEqual(offset, 2)
        self.assertFalse(processed)
        self.assertEqual(failures, {2: 1})

    def test_permanent_update_failure_is_dropped_after_retries(self):
        class FailingApp:
            def handle(self, update):
                if update["update_id"] == 2:
                    raise RuntimeError("permanent failure")

        app = FailingApp()
        failures = {}
        for attempt in range(2):
            with self.assertLogs("sorority.telegram", level="ERROR"):
                offset, processed, failures = process_updates(
                    app, [{"update_id": 2}, {"update_id": 3}], 2, failures
                )
            self.assertEqual(offset, 2)
            self.assertFalse(processed)
            self.assertEqual(failures, {2: attempt + 1})

        with self.assertLogs("sorority.telegram", level="ERROR"):
            offset, processed, failures = process_updates(
                app, [{"update_id": 2}, {"update_id": 3}], 2, failures
            )
        self.assertEqual(offset, 4)
        self.assertTrue(processed)
        self.assertEqual(failures, {})

    def test_recovered_update_clears_retry_state(self):
        class RecoveringApp:
            def __init__(self):
                self.attempts = 0

            def handle(self, update):
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("temporary failure")

        app = RecoveringApp()
        with self.assertLogs("sorority.telegram", level="ERROR"):
            offset, processed, failures = process_updates(
                app, [{"update_id": 2}], 2
            )
        self.assertEqual((offset, processed, failures), (2, False, {2: 1}))

        offset, processed, failures = process_updates(
            app, [{"update_id": 2}], 2, failures
        )
        self.assertEqual((offset, processed, failures), (3, True, {}))


class LinkStoreDsnTest(unittest.TestCase):
    def test_tls_is_required_even_if_the_url_omits_it(self):
        store = LinkStore("postgres://u:p@host:5432/db")
        self.assertEqual(store._dsn(), "postgres://u:p@host:5432/db?sslmode=require")
        store = LinkStore("postgres://u:p@host:5432/db?application_name=mia")
        self.assertTrue(store._dsn().endswith("&sslmode=require"))

    def test_an_explicit_sslmode_is_left_alone(self):
        for url in ["postgres://u:p@h/db?sslmode=verify-full", ""]:
            self.assertEqual(LinkStore(url)._dsn(), url)


if __name__ == "__main__":
    unittest.main()
