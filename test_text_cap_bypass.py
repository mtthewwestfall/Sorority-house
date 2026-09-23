"""
Unit tests for the Text-Only pack monthly cap: self-serve (api) purchases are
capped per month, but Shopify order webhooks are completed sales — refusing one
would strand the customer's money, so those packs always stack.
"""

import unittest
from unittest.mock import MagicMock, patch

import main


def _grant_cursor(text_only_bought=1):
    """Fake cursor covering grant_keyhole_package's reads/writes for text_only:
    user fetch, cap read, entitlement UPDATE ... RETURNING."""
    cur = MagicMock()
    state = {"n": 0}

    def execute(sql, *a, **k):
        s = " ".join(sql.split())
        if s.startswith("SELECT * FROM users"):
            state["n"] = 0
            cur.fetchone.return_value = {"user_id": "u1", "text_only_bought_this_month": text_only_bought}
        elif s.startswith("SELECT key, value FROM house_rules"):
            cur.fetchone.return_value = None
            cur.fetchall.return_value = []
        elif s.startswith("UPDATE users SET text_balance"):
            cur.fetchone.return_value = {"text_balance": 600, "message_credits": 0,
                                         "webcam_minutes_left": 0, "video_replies_left": 0,
                                         "fresh_videos_left": 0, "pic_credits": 0,
                                         "paid_keyhole_purchases": 1}

    cur.execute.side_effect = execute
    return cur


def _conn(cur):
    m = MagicMock()
    m.cursor.return_value.__enter__.return_value = cur
    return m


class TestTextOnlyCap(unittest.TestCase):

    @patch.object(main, "db")
    def test_api_purchase_capped_after_one_this_month(self, mock_db):
        cur = _grant_cursor(text_only_bought=1)
        mock_db.return_value = _conn(cur)
        from fastapi.exceptions import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            main.grant_keyhole_package("u1", "text_only", source="api")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Monthly limit", ctx.exception.detail)

    @patch.object(main, "db")
    def test_shopify_order_bypasses_cap(self, mock_db):
        cur = _grant_cursor(text_only_bought=1)
        mock_db.return_value = _conn(cur)
        res = main.grant_keyhole_package("u1", "text_only", source="shopify")
        self.assertTrue(res["ok"])

    @patch.object(main, "db")
    def test_first_api_purchase_still_fine(self, mock_db):
        cur = _grant_cursor(text_only_bought=0)
        mock_db.return_value = _conn(cur)
        res = main.grant_keyhole_package("u1", "text_only", source="api")
        self.assertTrue(res["ok"])


if __name__ == "__main__":
    unittest.main()
