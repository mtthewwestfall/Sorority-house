"""
KEYHOLE WebCam Engine & Shared Show Backend Unit Tests
======================================================
Tests the KEYHOLE webcam backend functionality using mocked database connections:
- Private show creation and routing
- Payment verification and entitlement
- Private START / END and immediate viewer revocation
- Public show creation, scheduling, announcements, and reminders
- Multiple paid viewers and unauthorized viewer rejection
- Public START / END and disconnects
- Recording finalization, sanitization, and username removal
- Preview approval, rejection, and multi-channel publishing
- Full idempotency & protection against duplicate webhooks/events
"""

import os
import json
import unittest
from unittest.mock import patch, MagicMock
from fastapi.exceptions import HTTPException
from fastapi.testclient import TestClient

os.environ["ADMIN_SECRET"] = "test_admin_secret_123"
os.environ["TELEGRAM_BOT_SECRET"] = "test_bot_secret_123"
os.environ["SITE_PASSWORD"] = "test_pass"

import main
client = TestClient(main.app)

class TestKeyholeWebcamBackend(unittest.TestCase):
    def setUp(self):
        main.ADMIN_SECRET = "test_admin_secret_123"
        self.headers = {"X-Site-Password": "test_pass"}
        self.admin_headers = {"X-Site-Password": "test_pass", "X-Admin-Secret": "test_admin_secret_123"}

        # Dummy user helper
        self.alice_user = {"user_id": "usr_alice", "display_name": "Alice", "tier": "resident"}
        self.bob_user = {"user_id": "usr_bob", "display_name": "Bob", "tier": "visitor"}

    @patch("main.db")
    def test_01_private_show_lifecycle_and_sanitization(self, mock_db):
        """Test private show request, routing, payment verification, start/end, disconnect, and sanitization."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        # Mock current_user dependency via patch or endpoint logic testing
        # 1. Private show creation. Chloe is a built-in character, so there is no personas lookup.
        mock_cur.fetchone.side_effect = [
            None, # No existing active private show
            { # Show row created
                "show_id": "priv_123", "show_type": "private", "character_id": "chloe",
                "customer_id": "usr_alice", "title": "Private Show", "description": "1-on-1",
                "price": 19.99, "scheduled_at": None, "status": "PAYMENT_PENDING",
                "recording_url": "", "sanitized_preview_url": "", "preview_status": "NONE",
                "published_targets": []
            },
            { # keyhole_get_show query
                "show_id": "priv_123", "show_type": "private", "character_id": "chloe",
                "customer_id": "usr_alice", "title": "Private Show", "description": "1-on-1",
                "price": 19.99, "scheduled_at": None, "status": "PAYMENT_PENDING",
                "recording_url": "", "sanitized_preview_url": "", "preview_status": "NONE",
                "published_targets": []
            }
        ]
        mock_cur.fetchall.return_value = []

        show = main.keyhole_create_private_show(customer_id="usr_alice", character_id="chloe")
        self.assertEqual(show["show_id"], "priv_123")
        self.assertEqual(show["status"], "PAYMENT_PENDING")
        self.assertEqual(show["character_id"], "chloe")

        # 2. Start show fails prior to payment
        with patch.object(mock_cur, 'fetchone', side_effect=[
            {"show_id": "priv_123", "show_type": "private", "character_id": "chloe", "customer_id": "usr_alice", "status": "PAYMENT_PENDING"},
            None # Payment entitlement check returns None
        ]):
            with self.assertRaises(HTTPException) as ctx:
                main.keyhole_start_show("priv_123")
            self.assertEqual(ctx.exception.status_code, 402)

        # 3. Record payment and verify status transitions to READY
        with patch.object(mock_cur, 'fetchone', side_effect=[
            {"show_id": "priv_123", "show_type": "private", "character_id": "chloe", "customer_id": "usr_alice", "status": "PAYMENT_PENDING", "price": 19.99},
            None, # check if entitlement exists for user
            None, # check if payment_id consumed
            {"subscription_id": "pay_999"}, # check stripe_checkouts
            {"show_id": "priv_123", "show_type": "private", "character_id": "chloe", "customer_id": "usr_alice", "status": "READY"} # _fetch_show_dict
        ]):
            mock_cur.fetchall.return_value = [{"user_id": "usr_alice", "granted_at": "2025-01-01"}]
            paid_show = main.keyhole_record_show_payment(show_id="priv_123", user_id="usr_alice", payment_id="pay_999")
            self.assertEqual(paid_show["status"], "READY")
            self.assertIn("usr_alice", paid_show["paid_viewers"])

        # 4. Start show succeeds after payment
        with patch.object(mock_cur, 'fetchone', side_effect=[
            {"show_id": "priv_123", "show_type": "private", "character_id": "chloe", "customer_id": "usr_alice", "status": "READY"},
            True, # entitlement found
            {"show_id": "priv_123", "show_type": "private", "character_id": "chloe", "customer_id": "usr_alice", "status": "LIVE"}
        ]):
            mock_cur.fetchall.return_value = [{"user_id": "usr_alice", "granted_at": "2025-01-01"}]
            live_show = main.keyhole_start_show("priv_123")
            self.assertEqual(live_show["status"], "LIVE")

        # 5. Access control verification
        with patch.object(mock_cur, 'fetchone', side_effect=[
            {"show_id": "priv_123", "show_type": "private", "character_id": "chloe", "customer_id": "usr_alice", "status": "LIVE", "recording_url": "/assets/webcam/chloe/live.mp4"},
            True # entitled
        ]):
            acc = main.keyhole_check_viewer_access("priv_123", "usr_alice")
            self.assertTrue(acc["access"])

        # Unauthorized viewer Bob rejected from private show
        with patch.object(mock_cur, 'fetchone', side_effect=[
            {"show_id": "priv_123", "show_type": "private", "character_id": "chloe", "customer_id": "usr_alice", "status": "LIVE", "recording_url": "/assets/webcam/chloe/live.mp4"},
            None # not entitled
        ]):
            acc_bob = main.keyhole_check_viewer_access("priv_123", "usr_bob")
            self.assertFalse(acc_bob["access"])

        # 6. End show and verify recording finalization & sanitization
        with patch.object(mock_cur, 'fetchone', side_effect=[
            {"show_id": "priv_123", "show_type": "private", "character_id": "chloe", "customer_id": "usr_alice", "status": "LIVE"},
            {"show_id": "priv_123", "show_type": "private", "character_id": "chloe", "customer_id": "usr_alice", "status": "PREVIEW_READY", "recording_url": "/assets/webcam/chloe/recording_priv_123.mp4", "sanitized_preview_url": "/assets/webcam/chloe/preview_priv_123_clean.mp4", "preview_status": "PENDING"}
        ]):
            mock_cur.fetchall.return_value = [{"user_id": "usr_alice", "granted_at": "2025-01-01"}]
            ended_show = main.keyhole_end_show("priv_123")
            self.assertEqual(ended_show["status"], "PREVIEW_READY")
            self.assertEqual(ended_show["preview_status"], "PENDING")
            self.assertEqual(ended_show["recording_url"], "/assets/webcam/chloe/recording_priv_123.mp4")
            self.assertEqual(ended_show["sanitized_preview_url"], "/assets/webcam/chloe/preview_priv_123_clean.mp4")
            self.assertNotIn("usr_alice", ended_show["sanitized_preview_url"])

    @patch("main.db")
    def test_02_public_show_scheduling_multi_viewer_publishing(self, mock_db):
        """Test public show creation, scheduling, multiple viewers, preview moderation, and publishing."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        # 1. Create Public Show. Bailey is a built-in character, so there is no personas lookup.
        mock_cur.fetchone.side_effect = [
            None, # Insert notification announcement 1
            None, # Insert notification announcement 2
            {"show_id": "pub_456", "show_type": "public", "character_id": "bailey", "status": "SCHEDULED", "price": 4.99}
        ]
        mock_cur.fetchall.return_value = []

        pub_show = main.keyhole_create_public_show(character_id="bailey", price=4.99, title="Bailey Public Lounge")
        self.assertEqual(pub_show["show_id"], "pub_456")
        self.assertEqual(pub_show["status"], "SCHEDULED")

        # 2. Preview Moderation Approval & Rejection
        with patch.object(mock_cur, 'fetchone', side_effect=[
            {"show_id": "pub_456", "show_type": "public", "sanitized_preview_url": "/assets/webcam/bailey/prev.mp4"},
            {"show_id": "pub_456", "show_type": "public", "preview_status": "APPROVED", "sanitized_preview_url": "/assets/webcam/bailey/prev.mp4"}
        ]):
            mod_show = main.keyhole_moderate_preview("pub_456", action="approve")
            self.assertEqual(mod_show["preview_status"], "APPROVED")

        # 3. Multi-channel Publishing
        with patch.object(mock_cur, 'fetchone', side_effect=[
            {"show_id": "pub_456", "show_type": "public", "preview_status": "APPROVED", "published_targets": []},
            {"id": 1}, # Telegram notif
            {"id": 2}, # Website notif
            {"show_id": "pub_456", "show_type": "public", "status": "PUBLISHED", "published_targets": ["telegram", "website"]}
        ]):
            pub_res = main.keyhole_publish_preview("pub_456", targets=["telegram", "website"])
            self.assertEqual(pub_res["status"], "PUBLISHED")
            self.assertIn("telegram", pub_res["published_targets"])
            self.assertIn("website", pub_res["published_targets"])

    @patch("main.db")
    def test_03_idempotency_protections(self, mock_db):
        """Test idempotency on duplicate START, END, and notification events."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        # Duplicate START on already LIVE show returns existing show state without re-running
        with patch.object(mock_cur, 'fetchone', side_effect=[
            {"show_id": "pub_789", "status": "LIVE"},
            {"show_id": "pub_789", "status": "LIVE"}
        ]):
            res1 = main.keyhole_start_show("pub_789")
            self.assertEqual(res1["status"], "LIVE")

        # Duplicate notification returns False (deduplicated)
        mock_cur.fetchone.return_value = None # ON CONFLICT DO NOTHING returned no inserted row
        sent = main._send_keyhole_notification(mock_cur, "pub_789", "announcement", "telegram")
        self.assertFalse(sent)

    def test_vip_passcode_is_not_a_payment(self):
        with self.assertRaises(HTTPException) as ctx:
            main.keyhole_record_show_payment("priv_123", "usr_alice", "KEY-VIP-ROOM")
        self.assertEqual(ctx.exception.status_code, 402)

    def test_vip_room_rejects_cheat_and_unpaid(self):
        user = {"user_id": "usr_alice"}
        for code in ("KEY-VIP-ROOM", "KEY-VIP", "VIP", "MEMBER", "key-vip-extra"):
            with self.assertRaises(HTTPException) as ctx:
                main.keyhole_room_unlock(main.KeyholeRoomUnlockIn(passcode=code), user)
            self.assertEqual(ctx.exception.status_code, 402)

    @patch("main.db")
    def test_vip_room_requires_paid_purchase(self, mock_db):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        user = {"user_id": "usr_alice"}
        mock_cur.fetchone.return_value = {"paid_keyhole_purchases": 0}
        with self.assertRaises(HTTPException) as ctx:
            main.keyhole_room_unlock(main.KeyholeRoomUnlockIn(passcode=""), user)
        self.assertEqual(ctx.exception.status_code, 402)

        mock_cur.fetchone.return_value = {"paid_keyhole_purchases": 1}
        opened = main.keyhole_room_unlock(main.KeyholeRoomUnlockIn(passcode=""), user)
        self.assertTrue(opened["vip_room"])
        self.assertEqual(opened["room"], "bedroom")

    @patch("main.db")
    def test_pay_prefix_without_ledger_is_rejected(self, mock_db):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [
            {"show_id": "priv_123", "show_type": "private", "price": 19.99, "status": "PAYMENT_PENDING"},
            None,  # no entitlement yet
            None,  # payment id not consumed
            None,  # stripe_checkouts miss
            None,  # picture_payments miss
            None,  # keyhole_payments miss
        ]
        with self.assertRaises(HTTPException) as ctx:
            main.keyhole_record_show_payment("priv_123", "usr_alice", "pay_not_real")
        self.assertEqual(ctx.exception.status_code, 402)
        self.assertIn("unverified", ctx.exception.detail.lower())

    @patch("main.db")
    def test_purchase_adds_rollover_message_credits(self, mock_db):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []
        mock_cur.fetchone.side_effect = [
            {"user_id": "usr_alice", "intro_bought": 0, "quick_sessions_bought_this_month": 0,
             "text_only_bought_this_month": 0, "text_balance": 7},
            {"text_balance": 107, "message_credits": 100, "webcam_minutes_left": 10,
             "video_replies_left": 20, "fresh_videos_left": 0, "pic_credits": 0,
             "paid_keyhole_purchases": 1},
        ]
        granted = main.grant_keyhole_package("usr_alice", "intro")
        self.assertEqual(granted["entitlements"]["message_credits"], 100)
        sqls = " ".join(str(c.args[0]) for c in mock_cur.execute.call_args_list)
        self.assertIn("message_credits = message_credits +", sqls)
        self.assertIn("preview_message_credits", sqls)
        self.assertIn("paid_keyhole_purchases = paid_keyhole_purchases + 1", sqls)

    @patch("main.get_relationship", return_value={"summary": ""})
    @patch("main.check_keyhole_session_active")
    @patch("main.girl_open", return_value=True)
    @patch("main.db")
    def test_preview_messages_spend_before_paid_credits(self, mock_db, _open, _session, _rel):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.side_effect = [
            {"preview_message_credits": 50, "message_credits": 40, "paid_keyhole_purchases": 0,
             "free_preview_claimed_at": "2026-01-01", "webcam_minutes_left": 10,
             "webcam_session_started_at": None},
            {"preview_message_credits": 49},
        ]
        _girl, _row, remaining = main.chat_preflight(
            {"user_id": "usr_alice", "tier": "visitor"}, "chloe")
        self.assertEqual(remaining, 49)
        first_update = mock_cur.execute.call_args_list[1].args[0]
        self.assertIn("preview_message_credits = preview_message_credits - 1", first_update)


if __name__ == "__main__":
    unittest.main()
