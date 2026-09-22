import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "telegram"))

import main
import bot


class TestTelegramBotWebcamShow(unittest.TestCase):

    def setUp(self):
        os.environ["ADMIN_SECRET"] = "test-admin-secret"
        main.ADMIN_SECRET = "test-admin-secret"

    def test_allowed_models_restriction(self):
        """Verify that ALLOWED_MODELS is strictly restricted to Chloe and Bailey."""
        self.assertEqual(bot.ALLOWED_MODELS, {"chloe", "bailey"})

    def test_cmd_args_parsing(self):
        update = MagicMock()
        update.message.text = "/model chloe"
        self.assertEqual(bot._cmd_args(update), ["chloe"])

        update.message.text = "/start"
        self.assertEqual(bot._cmd_args(update), [])

    def test_active_model_filter(self):
        rec_valid = {"active_girl": "chloe"}
        self.assertEqual(bot._active_model(rec_valid), "chloe")

        rec_bailey = {"active_girl": "bailey"}
        self.assertEqual(bot._active_model(rec_bailey), "bailey")

        rec_disallowed = {"active_girl": "carmen"}
        self.assertIsNone(bot._active_model(rec_disallowed))

        rec_none = {}
        self.assertIsNone(bot._active_model(rec_none))

    @patch("bot._get")
    def test_fetch_roster_filters_disallowed_models(self, mock_get):
        """Verify that _fetch_roster strictly filters the roster to Chloe and Bailey."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "girls": [
                {"girl": "bailey", "name": "Bailey"},
                {"girl": "carmen", "name": "Carmen"},
                {"girl": "chloe", "name": "Chloe"},
                {"girl": "valentina", "name": "Valentina"},
            ]
        }
        mock_get.return_value = mock_resp

        res = bot._fetch_roster("fake-token")
        girls = res.get("girls", [])
        girl_slugs = [g["girl"] for g in girls]

        self.assertIn("chloe", girl_slugs)
        self.assertIn("bailey", girl_slugs)
        self.assertNotIn("carmen", girl_slugs)
        self.assertNotIn("valentina", girl_slugs)
        self.assertEqual(len(girls), 2)

    def test_send_chat_disallowed_model_raises(self):
        """Verify _send_chat rejects disallowed models."""
        with self.assertRaises(bot.BackendError) as ctx:
            bot._send_chat("fake-token", "carmen", "Hello")
        self.assertIn("Only Chloe and Bailey are available", str(ctx.exception))

    def test_plan_links_match_rooms_packages(self):
        """Telegram sells the same sessions, at the same prices, through the site's Stripe links."""
        saved = {key: os.environ.get(key) for key in (
            "PAY_LINK_15", "PAY_LINK_30", "PAY_LINK_45", "PAY_LINK_55",
            "PAY_LINK_60", "PAY_LINK_75", "PAY_LINK_PUBLIC", "SITE_URL",
        )}
        for key in saved:
            os.environ.pop(key, None)
        os.environ["SITE_URL"] = "https://lockeddoor.ai"
        try:
            links = bot.plan_links()
        finally:
            for key, val in saved.items():
                if val is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = val
        # plan_links reads SITE_URL from the module global, which was set at import.
        # Re-read with the module's current SITE_URL so the 45-minute fallback matches the bot.
        rooms = bot.SITE_URL + "/rooms.html"
        by_url = {url: label for label, url in links}
        self.assertEqual(len(links), 7)
        labels = [label for label, _url in links]
        self.assertEqual(labels[0], "15 min · $7.99")
        self.assertNotIn("100 texts", labels[0])
        self.assertNotIn("Preview", labels[0])
        self.assertIn("https://buy.stripe.com/00w14gav1bFddlR6jLdjO09", by_url)
        self.assertIn("https://buy.stripe.com/bJeeV67iPdNl2Hd8rTdjO08", by_url)
        self.assertIn("https://buy.stripe.com/4gM9AM46DbFda9F23vdjO03", by_url)
        self.assertIn("https://buy.stripe.com/9B600c0UrcJh4Pl0ZrdjO07", by_url)
        self.assertIn("https://buy.stripe.com/5kQ5kw0UrfVtepVaA1djO04", by_url)
        self.assertIn("https://buy.stripe.com/6oUfZh1jradL0he4098AE00", by_url)
        self.assertIn(("45 min · $14.99 · 100 texts", rooms), links)
        self.assertTrue(any("30 min" in label and "$11.99" in label and "100 texts" in label for label in labels))
        self.assertTrue(any("60 min" in label and "$19.99" in label for label in labels))
        self.assertTrue(any("75 min" in label and "$23.99" in label for label in labels))
        self.assertTrue(any("Public Lounge" in label and "$4.99" in label for label in labels))
        self.assertNotIn("https://buy.stripe.com/3cI6oH4vD85D1li2W58AE02", by_url)

    def test_plan_link_env_override(self):
        with patch.dict(os.environ, {"PAY_LINK_15": "https://buy.stripe.com/override15"}, clear=False):
            urls = [url for _label, url in bot.plan_links()]
        self.assertIn("https://buy.stripe.com/override15", urls)

    def test_send_audit_disallowed_model_raises(self):
        """Verify _send_audit rejects disallowed models."""
        with self.assertRaises(bot.BackendError) as ctx:
            bot._send_audit("fake-token", "valentina")
        self.assertIn("Audit is only available for Chloe and Bailey", str(ctx.exception))

    @patch("main.db")
    def test_admin_accounts_account_type_filter(self, mock_db):
        """Verify the /admin/accounts endpoint handles account_type filtering."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            {
                "email": "tg:123456",
                "created_at": "2026-09-01T00:00:00Z",
                "verified_at": "2026-09-01T00:00:00Z",
                "telegram_id": 123456,
                "user_id": "u_tg123",
                "display_name": "Viewer1",
                "tier": "visitor",
                "msg_used": 0,
                "audit_credits": 0,
                "total_audits_used": 0,
                "plan_reset_at": "2026-10-01T00:00:00Z",
                "comp_until": None,
                "comp_prev_tier": None,
                "admin_note": "",
                "webcam_minutes_left": 15,
                "text_balance": 100,
                "account_type": "webcam",
                "open_complaints": 0
            }
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_db.return_value = mock_conn

        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        headers = {"X-Admin-Secret": "test-admin-secret"}

        res = client.get("/admin/accounts?account_type=webcam", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["account_type"], "webcam")
        self.assertEqual(data[0]["webcam_minutes_left"], 15)


if __name__ == "__main__":
    unittest.main()
