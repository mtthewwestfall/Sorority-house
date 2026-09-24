"""
KEYHOLE booking tests — scheduled private shows.
=================================================
Customer picks a character + package + time, pays through the package's Stripe
Payment Link (booking id as client_reference_id), the Stripe webhook confirms
the booking, and the character's webcam goes live in the booked window.
Admins see live + upcoming shows in the lives display.

DB is mocked; endpoint functions are called directly like the other keyhole tests.
"""

import hashlib
import hmac
import json
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from fastapi.exceptions import HTTPException

os.environ["ADMIN_SECRET"] = "test_admin_secret_123"
os.environ["TELEGRAM_BOT_SECRET"] = "test_bot_secret_123"
os.environ["SITE_PASSWORD"] = "test_pass"

import main
from fastapi.testclient import TestClient

client = TestClient(main.app)

CFG = {
    "intro_price": 19.99, "intro_webcam_minutes": 10,
    "quick_price": 29.99, "quick_webcam_minutes": 15,
    "standard_price": 49.99, "standard_webcam_minutes": 30,
    "long_price": 79.99, "long_webcam_minutes": 55,
    "premium_price": 99.99, "premium_webcam_minutes": 60,
}

ALICE = {"user_id": "usr_alice", "display_name": "Alice"}


def _mock_db():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = []
    return mock_conn, mock_cur


def _future_iso(minutes=90):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


class TestBookingPackages(unittest.TestCase):
    @patch("main.db")
    @patch("main.get_keyhole_config", return_value=dict(CFG))
    def test_packages_list_pay_links(self, _cfg, mock_db):
        mock_conn, _ = _mock_db()
        mock_db.return_value = mock_conn
        res = main.keyhole_booking_packages()
        by_pkg = {p["package"]: p for p in res["packages"]}
        self.assertIn("intro", by_pkg)
        self.assertTrue(by_pkg["intro"]["pay_link"].startswith("https://buy.stripe.com/"))
        self.assertEqual(by_pkg["intro"]["webcam_minutes"], 10)
        self.assertEqual(by_pkg["standard"]["price"], 49.99)


class TestBookingCreate(unittest.TestCase):
    @patch("main.get_keyhole_config", return_value=dict(CFG))
    @patch("main.db")
    def test_rejects_bad_package(self, mock_db, _cfg):
        mock_conn, _ = _mock_db()
        mock_db.return_value = mock_conn
        body = main.KeyholeBookingIn(character_id="chloe", package="nope", start_at=_future_iso())
        with self.assertRaises(HTTPException) as ctx:
            main.keyhole_bookings_create(body, ALICE)
        self.assertEqual(ctx.exception.status_code, 400)

    @patch("main.get_keyhole_config", return_value=dict(CFG))
    @patch("main.db")
    def test_rejects_unknown_character(self, mock_db, _cfg):
        mock_conn, mock_cur = _mock_db()
        mock_db.return_value = mock_conn
        mock_cur.fetchone.return_value = None  # personas miss
        body = main.KeyholeBookingIn(character_id="zoe", package="intro", start_at=_future_iso())
        with self.assertRaises(HTTPException) as ctx:
            main.keyhole_bookings_create(body, ALICE)
        self.assertEqual(ctx.exception.status_code, 400)

    @patch("main.get_keyhole_config", return_value=dict(CFG))
    @patch("main.db")
    def test_rejects_past_start(self, mock_db, _cfg):
        mock_conn, _ = _mock_db()
        mock_db.return_value = mock_conn
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        body = main.KeyholeBookingIn(character_id="chloe", package="intro", start_at=past)
        with self.assertRaises(HTTPException) as ctx:
            main.keyhole_bookings_create(body, ALICE)
        self.assertEqual(ctx.exception.status_code, 400)

    @patch("main.get_keyhole_config", return_value=dict(CFG))
    @patch("main.db")
    def test_create_returns_payment_url(self, mock_db, _cfg):
        mock_conn, mock_cur = _mock_db()
        mock_db.return_value = mock_conn
        start = datetime.now(timezone.utc) + timedelta(hours=2)
        row = {"show_id": "priv_test123", "scheduled_at": start, "duration_minutes": 10,
               "package": "intro", "price": 19.99, "status": "PAYMENT_PENDING", "character_id": "chloe"}
        mock_cur.fetchone.side_effect = [None, row]  # dedupe miss, then RETURNING
        body = main.KeyholeBookingIn(character_id="Chloe", package="intro", start_at=start.isoformat())
        out = main.keyhole_bookings_create(body, ALICE)
        self.assertEqual(out["status"], "PAYMENT_PENDING")
        self.assertEqual(out["character_id"], "chloe")
        self.assertIn("client_reference_id=priv_test123", out["payment_url"])
        self.assertTrue(out["payment_url"].startswith("https://buy.stripe.com/"))
        self.assertFalse(out["live_now"])
        self.assertGreater(out["starts_in_seconds"], 0)

    @patch("main.get_keyhole_config", return_value=dict(CFG))
    @patch("main.db")
    def test_create_is_idempotent_on_double_click(self, mock_db, _cfg):
        mock_conn, mock_cur = _mock_db()
        mock_db.return_value = mock_conn
        start = datetime.now(timezone.utc) + timedelta(hours=2)
        row = {"show_id": "priv_dup1", "scheduled_at": start, "duration_minutes": 10,
               "package": "intro", "price": 19.99, "status": "PAYMENT_PENDING", "character_id": "chloe"}
        mock_cur.fetchone.side_effect = [row]  # dedupe hit
        body = main.KeyholeBookingIn(character_id="chloe", package="intro", start_at=start.isoformat())
        out = main.keyhole_bookings_create(body, ALICE)
        self.assertEqual(out["show_id"], "priv_dup1")
        sqls = " ".join(str(c.args[0]) for c in mock_cur.execute.call_args_list)
        self.assertNotIn("INSERT INTO keyhole_shows", sqls)


class TestBookingWindow(unittest.TestCase):
    def test_live_inside_window(self):
        show = {"status": "PAID",
                "scheduled_at": datetime.now(timezone.utc) - timedelta(minutes=2),
                "duration_minutes": 10}
        w = main._keyhole_booking_window(show)
        self.assertTrue(w["live_now"])
        self.assertGreater(w["ends_in_seconds"], 0)

    def test_not_live_before_start(self):
        show = {"status": "PAID",
                "scheduled_at": datetime.now(timezone.utc) + timedelta(hours=1),
                "duration_minutes": 10}
        w = main._keyhole_booking_window(show)
        self.assertFalse(w["live_now"])
        self.assertGreater(w["starts_in_seconds"], 3500)

    def test_not_live_after_end(self):
        show = {"status": "PAID",
                "scheduled_at": datetime.now(timezone.utc) - timedelta(hours=2),
                "duration_minutes": 10}
        w = main._keyhole_booking_window(show)
        self.assertFalse(w["live_now"])
        self.assertEqual(w["ends_in_seconds"], 0)

    def test_unpaid_never_live(self):
        show = {"status": "PAYMENT_PENDING",
                "scheduled_at": datetime.now(timezone.utc) - timedelta(minutes=2),
                "duration_minutes": 10}
        self.assertFalse(main._keyhole_booking_window(show)["live_now"])


class TestConfirmBooking(unittest.TestCase):
    @patch("main.db")
    def test_paid_webhook_confirms_booking(self, mock_db):
        mock_conn, mock_cur = _mock_db()
        mock_db.return_value = mock_conn
        show = {"show_id": "priv_b1", "show_type": "private", "status": "PAYMENT_PENDING",
                "customer_id": "usr_alice", "price": 19.99, "package": "intro"}
        mock_cur.fetchone.return_value = show
        session = {"id": "cs_test_1", "amount_total": 1999}
        out = main._confirm_keyhole_booking("stripe", "stripe:cs_test_1", "priv_b1", session)
        self.assertEqual(out["status"], "PAID")
        sqls = " ".join(str(c.args[0]) for c in mock_cur.execute.call_args_list)
        self.assertIn("SET status='PAID'", sqls)
        self.assertIn("INSERT INTO keyhole_payments", sqls)

    @patch("main.db")
    def test_confirm_is_idempotent(self, mock_db):
        mock_conn, mock_cur = _mock_db()
        mock_db.return_value = mock_conn
        show = {"show_id": "priv_b1", "show_type": "private", "status": "PAID",
                "customer_id": "usr_alice", "price": 19.99, "package": "intro"}
        mock_cur.fetchone.return_value = show
        out = main._confirm_keyhole_booking("stripe", "stripe:cs_test_1", "priv_b1", {"amount_total": 1999})
        self.assertEqual(out["already"], "PAID")
        sqls = " ".join(str(c.args[0]) for c in mock_cur.execute.call_args_list)
        self.assertNotIn("SET status='PAID'", sqls)

    @patch("main.db")
    def test_unknown_booking_ignored(self, mock_db):
        mock_conn, mock_cur = _mock_db()
        mock_db.return_value = mock_conn
        mock_cur.fetchone.return_value = None
        out = main._confirm_keyhole_booking("stripe", "stripe:cs_x", "priv_nope", {})
        self.assertEqual(out["ignored"], "unknown booking")


class TestBookingsMine(unittest.TestCase):
    @patch("main.db")
    def test_mine_lists_with_windows(self, mock_db):
        mock_conn, mock_cur = _mock_db()
        mock_db.return_value = mock_conn
        now = datetime.now(timezone.utc)
        mock_cur.fetchall.return_value = [
            {"show_id": "priv_live1", "scheduled_at": now - timedelta(minutes=2),
             "duration_minutes": 10, "package": "intro", "price": 19.99,
             "status": "PAID", "character_id": "chloe"},
            {"show_id": "priv_soon1", "scheduled_at": now + timedelta(hours=3),
             "duration_minutes": 30, "package": "standard", "price": 49.99,
             "status": "PAYMENT_PENDING", "character_id": "bailey"},
        ]
        out = main.keyhole_bookings_mine(ALICE)
        self.assertEqual(len(out["bookings"]), 2)
        self.assertTrue(out["bookings"][0]["live_now"])
        self.assertFalse(out["bookings"][1]["live_now"])


class TestAdminLives(unittest.TestCase):
    @patch("main.db")
    def test_splits_live_and_upcoming(self, mock_db):
        mock_conn, mock_cur = _mock_db()
        mock_db.return_value = mock_conn
        now = datetime.now(timezone.utc)
        mock_cur.fetchall.return_value = [
            {"show_id": "priv_live1", "scheduled_at": now - timedelta(minutes=2),
             "duration_minutes": 10, "package": "intro", "price": 19.99, "status": "PAID",
             "character_id": "chloe", "customer_id": "usr_alice", "created_at": now,
             "customer_email": "alice@example.com"},
            {"show_id": "priv_next1", "scheduled_at": now + timedelta(hours=2),
             "duration_minutes": 30, "package": "standard", "price": 49.99, "status": "PAID",
             "character_id": "bailey", "customer_id": "usr_bob", "created_at": now,
             "customer_email": "bob@example.com"},
        ]
        out = main.admin_keyhole_shows_live()
        self.assertEqual(len(out["live"]), 1)
        self.assertEqual(len(out["upcoming"]), 1)
        self.assertEqual(out["live"][0]["show_id"], "priv_live1")
        self.assertEqual(out["live"][0]["customer_email"], "alice@example.com")
        self.assertEqual(out["upcoming"][0]["show_id"], "priv_next1")


class TestStripeWebhookBooking(unittest.TestCase):
    @patch("main.db")
    def test_webhook_confirms_booking_payment(self, mock_db):
        mock_conn, mock_cur = _mock_db()
        mock_db.return_value = mock_conn
        show = {"show_id": "priv_wh1", "show_type": "private", "status": "PAYMENT_PENDING",
                "customer_id": "usr_alice", "price": 19.99, "package": "intro"}
        mock_cur.fetchone.return_value = show

        main.STRIPE_WEBHOOK_SECRET = "whsec_test_123"
        try:
            event = {
                "id": "evt_test_1",
                "type": "checkout.session.completed",
                "created": int(time.time()),
                "data": {"object": {
                    "id": "cs_test_webhook",
                    "mode": "payment",
                    "payment_status": "paid",
                    "amount_total": 1999,
                    "currency": "usd",
                    "client_reference_id": "priv_wh1",
                    "metadata": {},
                    "customer_details": {"email": "alice@example.com"},
                }},
            }
            raw = json.dumps(event).encode()
            ts = int(time.time())
            sig = hmac.new(b"whsec_test_123", f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
            resp = client.post("/webhooks/stripe", content=raw,
                               headers={"Stripe-Signature": f"t={ts},v1={sig}",
                                        "Content-Type": "application/json"})
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body.get("status"), "PAID")
            self.assertEqual(body.get("booking"), "priv_wh1")
            sqls = " ".join(str(c.args[0]) for c in mock_cur.execute.call_args_list)
            self.assertIn("SET status='PAID'", sqls)
        finally:
            main.STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")


if __name__ == "__main__":
    unittest.main()
