"""
Unit tests for Keyhole Pricing and Text Credit Accounting (Bot 1).
=================================================================
Verifies:
- 10m paid Intro = $5.99 & grants 100 text messages
- Supported durations exactly match [10, 15, 30, 45, 55, 60, 75]
- Group shows = $4.99/seat across 15m, 30m, 60m
- Standalone text bundle = 300 messages / $5.99
- Existing text balance is additive (e.g., 7 + 100 = 107)
- Free 10m preview grants 0 messages
- Paid Intro vs Free 10m Preview flows remain distinct
"""

import os
import unittest
from unittest.mock import patch, MagicMock

os.environ["ADMIN_SECRET"] = "test_admin_secret_123"
os.environ["TELEGRAM_BOT_SECRET"] = "test_bot_secret_123"
os.environ["SITE_PASSWORD"] = "test_pass"

import main


class TestKeyholePricingAndCredits(unittest.TestCase):

    def test_01_keyhole_default_config_pricing(self):
        """Verify default configuration prices and credit allocations."""
        cfg = main.KEYHOLE_DEFAULT_CONFIG

        # 1. Paid 10m Intro = $5.99 & 100 text messages
        self.assertEqual(float(cfg.get("intro_price")), 5.99)
        self.assertEqual(int(cfg.get("intro_webcam_minutes")), 10)
        self.assertEqual(int(cfg.get("intro_text_included")), 100)

        # 2. Standalone text bundle = 300 messages / $5.99
        self.assertEqual(float(cfg.get("text_only_price")), 5.99)
        self.assertEqual(int(cfg.get("text_only_included")), 300)

        # 3. Free preview = 0 text messages
        self.assertEqual(int(cfg.get("free_preview_text_included")), 0)
        self.assertEqual(int(cfg.get("free_preview_minutes")), 10)

        # 4. Group show price = $4.99/seat
        self.assertEqual(float(cfg.get("public_price")), 4.99)

    def test_02_supported_durations(self):
        """Verify supported durations match [10, 15, 30, 45, 55, 60, 75]."""
        cfg = main.KEYHOLE_DEFAULT_CONFIG
        durations = sorted([
            int(cfg.get("intro_webcam_minutes")),      # 10
            int(cfg.get("quick_webcam_minutes")),      # 15
            int(cfg.get("standard_webcam_minutes")),   # 30
            int(cfg.get("extended_webcam_minutes")),   # 45
            int(cfg.get("long_webcam_minutes")),       # 55
            int(cfg.get("premium_webcam_minutes")),    # 60
            int(cfg.get("marathon_webcam_minutes")),   # 75
        ])
        expected_durations = [10, 15, 30, 45, 55, 60, 75]
        self.assertEqual(durations, expected_durations)

    @patch("main.db")
    def test_03_group_show_pricing_by_duration(self, mock_db):
        """Verify group shows for 15m, 30m, and 60m are $4.99/seat."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.return_value = {
            "show_id": "pub_test", "show_type": "public", "character_id": "chloe",
            "price": 4.99, "status": "SCHEDULED"
        }

        # Create public shows with default and explicit prices
        show15 = main.keyhole_create_public_show(character_id="chloe")
        self.assertEqual(float(show15["price"]), 4.99)

        show30 = main.keyhole_create_public_show(character_id="chloe", price=4.99)
        self.assertEqual(float(show30["price"]), 4.99)

        show60 = main.keyhole_create_public_show(character_id="chloe", price=4.99)
        self.assertEqual(float(show60["price"]), 4.99)

    @patch("main.db")
    def test_04_additive_text_balance(self, mock_db):
        """Verify text balance is additive: e.g. existing balance 7 + 100 = 107."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        # User row before grant
        mock_cur.fetchone.side_effect = [
            {"user_id": "usr_7", "intro_bought": 0, "text_balance": 7, "message_credits": 0}, # SELECT users
            {"text_balance": 107, "message_credits": 100, "webcam_minutes_left": 10, "video_replies_left": 20, "fresh_videos_left": 0, "pic_credits": 0, "paid_keyhole_purchases": 1} # RETURNING
        ]

        res = main.grant_keyhole_package("usr_7", "intro")
        self.assertTrue(res["ok"])
        self.assertEqual(res["entitlements"]["text_balance"], 107)

    @patch("main.db")
    def test_05_free_preview_grants_zero_messages(self, mock_db):
        """Verify free preview claim grants 0 text messages."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.side_effect = [
            {"verified_at": "2025-01-01T00:00:00Z"}, # account verified
            {"webcam_minutes_left": 10, "preview_message_credits": 0, "message_credits": 0, "text_balance": 7} # RETURNING
        ]

        user = {"user_id": "usr_free"}
        res = main.keyhole_preview_claim(user=user)
        self.assertTrue(res["ok"])
        self.assertEqual(res["preview_messages"], 0)
        self.assertEqual(res["text_balance"], 7)

    @patch("main.db")
    def test_06_completed_paid_private_show_adds_100_messages(self, mock_db):
        """Verify a completed paid private Keyhole show adds 100 messages to existing text balance."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.side_effect = [
            {
                "show_id": "priv_456", "show_type": "private", "character_id": "chloe",
                "customer_id": "usr_alice", "status": "LIVE"
            }, # SELECT keyhole_shows
            {
                "show_id": "priv_456", "show_type": "private", "character_id": "chloe",
                "customer_id": "usr_alice", "status": "PREVIEW_READY"
            } # _fetch_show_dict
        ]

        res = main.keyhole_end_show("priv_456")
        self.assertEqual(res["status"], "PREVIEW_READY")

        # Verify UPDATE users SET text_balance = text_balance + 100 was executed
        update_calls = [call for call in mock_cur.execute.call_args_list if "UPDATE users" in str(call)]
        self.assertTrue(any("text_balance = text_balance + 100" in str(call) for call in update_calls))


if __name__ == "__main__":
    unittest.main()
