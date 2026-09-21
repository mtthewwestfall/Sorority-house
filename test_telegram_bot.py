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
