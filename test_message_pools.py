"""
Unit tests for message-spend parity: girl chat and custom companions must draw
from the same pools (preview -> paid credits -> package text_balance -> tier cap),
so Keyhole text purchases top up both chat types.
"""

import unittest
from unittest.mock import MagicMock, patch

import main


class _FakeCursor:
    """Queue-based fake cursor: each execute() queues the row its fetchone should
    return next (statements without RETURNING queue nothing)."""

    def __init__(self, comp=None, pools=None, text_left=None, credits_left=None,
                 preview_left=None, tier_row=None):
        self._comp = comp
        self._pools = pools or {}
        self._returning = {"preview": preview_left, "credits": credits_left,
                           "text": text_left, "tier": tier_row}
        self._queue = []
        self._comp_read = False
        self.executed = []

    def execute(self, sql, *a, **k):
        s = " ".join(sql.split())
        self.executed.append(s)
        if s.startswith("SELECT * FROM companions"):
            self._queue.append(self._comp)
            self._comp_read = True
        elif s.startswith("SELECT preview_message_credits"):
            self._queue.append(self._pools)
        elif "RETURNING preview_message_credits" in s:
            self._queue.append(self._returning["preview"])
        elif "RETURNING message_credits" in s:
            self._queue.append(self._returning["credits"])
        elif "RETURNING text_balance" in s:
            self._queue.append(self._returning["text"])
        elif "RETURNING msg_used" in s:
            self._queue.append(self._returning["tier"])
        # everything else (UPDATE companions etc.): fetchone returns None

    def fetchone(self):
        return self._queue.pop(0) if self._queue else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestSpendCascadeShared(unittest.TestCase):

    def test_text_balance_spends_before_tier_cap(self):
        cur = _FakeCursor(text_left={"text_balance": 299})
        self.assertEqual(main.spend_one_message(cur, "u1", limit=2), 299)

    def test_credits_spent_before_text_balance(self):
        cur = _FakeCursor(credits_left={"message_credits": 10}, text_left={"text_balance": 299})
        self.assertEqual(main.spend_one_message(cur, "u1", limit=2), 10)

    def test_preview_spends_first_while_playing(self):
        pools = {"free_preview_claimed_at": "t", "paid_keyhole_purchases": 0,
                 "webcam_minutes_left": 5, "webcam_session_started_at": None,
                 "preview_message_credits": 50}
        cur = _FakeCursor(pools=pools, preview_left={"preview_message_credits": 49},
                          credits_left={"message_credits": 10}, text_left={"text_balance": 299})
        self.assertEqual(main.spend_one_message(cur, "u1", limit=2), 49)

    def test_tier_cap_402_when_no_balances(self):
        from fastapi.exceptions import HTTPException
        cur = _FakeCursor(tier_row=None)
        with self.assertRaises(HTTPException) as ctx:
            main.spend_one_message(cur, "u1", limit=2)
        self.assertEqual(ctx.exception.status_code, 402)
        self.assertEqual(ctx.exception.detail, "out_of_messages")

    def test_tier_cap_counts_down(self):
        cur = _FakeCursor(tier_row={"msg_used": 1})
        self.assertEqual(main.spend_one_message(cur, "u1", limit=2), 1)


class TestCompanionPoolParity(unittest.TestCase):
    """_companion_preflight must spend the same pools as girl chat."""

    def _comp_row(self):
        return {"id": 7, "user_id": "u1", "first_name": "Rey", "milestone": 1,
                "last_session": None, "stage_since": None, "stage_days": 0}

    def test_companion_uses_text_balance(self):
        user = {"user_id": "u1", "tier": "visitor"}
        cur = _FakeCursor(comp=self._comp_row(), text_left={"text_balance": 299})
        with patch.object(main, "db", return_value=MagicMock(cursor=lambda: cur)), \
             patch.object(main, "_today", return_value="2026-09-23"):
            comp, remaining = main._companion_preflight(user, 7)
        self.assertEqual(remaining, 299)
        self.assertEqual(comp["id"], 7)

    def test_companion_uses_paid_credits_before_text(self):
        user = {"user_id": "u1", "tier": "visitor"}
        cur = _FakeCursor(comp=self._comp_row(), credits_left={"message_credits": 4},
                          text_left={"text_balance": 299})
        with patch.object(main, "db", return_value=MagicMock(cursor=lambda: cur)), \
             patch.object(main, "_today", return_value="2026-09-23"):
            _, remaining = main._companion_preflight(user, 7)
        self.assertEqual(remaining, 4)

    def test_companion_402_when_all_pools_empty(self):
        from fastapi.exceptions import HTTPException
        user = {"user_id": "u1", "tier": "visitor"}
        cur = _FakeCursor(comp=self._comp_row())
        with patch.object(main, "db", return_value=MagicMock(cursor=lambda: cur)), \
             patch.object(main, "_today", return_value="2026-09-23"):
            with self.assertRaises(HTTPException) as ctx:
                main._companion_preflight(user, 7)
        self.assertEqual(ctx.exception.status_code, 402)
        self.assertEqual(ctx.exception.detail, "out_of_messages")


if __name__ == "__main__":
    unittest.main()
