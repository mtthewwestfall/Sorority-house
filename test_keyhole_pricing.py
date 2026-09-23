"""
Unit tests for Keyhole pricing, package entitlements, and additive text credit accounting.
"""

import unittest
from unittest.mock import MagicMock, patch
from fastapi.exceptions import HTTPException

import main


class TestKeyholePricingAndEntitlements(unittest.TestCase):

    def test_default_config_pricing_values(self):
        cfg = main.KEYHOLE_DEFAULT_CONFIG
        self.assertEqual(cfg["intro_price"], 5.99)
        self.assertEqual(cfg["intro_webcam_minutes"], 10)
        self.assertEqual(cfg["intro_text_included"], 100)

        self.assertEqual(cfg["text_only_price"], 5.99)
        self.assertEqual(cfg["text_only_included"], 300)

        self.assertEqual(cfg["public_price"], 4.99)

    @patch("main.db")
    def test_grant_text_only_package_additive(self, mock_db):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.side_effect = [
            {"user_id": "usr_test", "text_only_bought_this_month": 0, "text_balance": 50},
            {"text_balance": 350, "message_credits": 100, "webcam_minutes_left": 0,
             "video_replies_left": 0, "fresh_videos_left": 0, "pic_credits": 0,
             "paid_keyhole_purchases": 1}
        ]

        res = main.grant_keyhole_package("usr_test", "text_only")
        self.assertTrue(res["ok"])
        self.assertEqual(res["entitlements"]["text_balance"], 350)

        sqls = [c.args[0] for c in mock_cur.execute.call_args_list]
        update_sqls = [s for s in sqls if "UPDATE users" in s and "text_balance = text_balance + %s" in s]
        self.assertTrue(len(update_sqls) > 0)

    @patch("main.db")
    def test_keyhole_end_show_grants_text_credits_for_paid_private_show(self, mock_db):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.side_effect = [
            {
                "show_id": "priv_100",
                "show_type": "private",
                "character_id": "chloe",
                "customer_id": "usr_client",
                "price": 19.99,
                "status": "LIVE",
            },
            {
                "show_id": "priv_100",
                "show_type": "private",
                "character_id": "chloe",
                "customer_id": "usr_client",
                "price": 19.99,
                "status": "PREVIEW_READY",
            }
        ]

        ended = main.keyhole_end_show("priv_100")
        self.assertEqual(ended["status"], "PREVIEW_READY")

        sqls = [c.args[0] for c in mock_cur.execute.call_args_list]
        grant_sqls = [s for s in sqls if "UPDATE users" in s and "text_balance = text_balance +" in s]
        self.assertTrue(len(grant_sqls) > 0)


if __name__ == "__main__":
    unittest.main()
