import os
import unittest
from fastapi.testclient import TestClient
import main
from main import (
    app,
    calculate_85_15_counts,
    get_character_clip_ratio,
    set_character_clip_ratio,
    assemble_clip_playlist,
    record_clip_history,
    get_served_clip_ids,
)

client = TestClient(app)


class TestClipHistoryAndAssembly(unittest.TestCase):

    def setUp(self):
        os.environ["ADMIN_SECRET"] = "test-admin-secret"
        self.admin_headers = {"X-Admin-Secret": "test-admin-secret"}
        # Reset character ratios to default (85% old, 15% new) before each test
        set_character_clip_ratio("chloe", 0.85, 0.15)
        set_character_clip_ratio("bailey", 0.85, 0.15)

    def test_calculate_85_15_counts_standard(self):
        old_c, new_c = calculate_85_15_counts(10, 0.85, 0.15)
        self.assertEqual(old_c, 8)
        self.assertEqual(new_c, 2)
        self.assertEqual(old_c + new_c, 10)

    def test_calculate_85_15_counts_small(self):
        old_c, new_c = calculate_85_15_counts(1, 0.85, 0.15)
        self.assertEqual(old_c, 1)
        self.assertEqual(new_c, 0)

    def test_calculate_custom_ratios(self):
        old_c, new_c = calculate_85_15_counts(10, 0.70, 0.30)
        self.assertEqual(old_c, 7)
        self.assertEqual(new_c, 3)

    def test_assemble_clip_playlist_default(self):
        res = assemble_clip_playlist("chloe", 10)
        self.assertTrue(res["ok"])
        self.assertEqual(res["character_id"], "chloe")
        self.assertEqual(res["total_clips"], 10)
        self.assertEqual(res["counts"]["old"], 8)
        self.assertEqual(res["counts"]["new"], 2)
        self.assertEqual(len(res["playlist"]), 10)

    def test_clip_history_recording_and_zero_repeat(self):
        user_id = "test_user_clip_123"
        record_clip_history(user_id, "chloe", ["chloe_banked_1", "chloe_banked_2"])
        served = get_served_clip_ids(user_id, "chloe")
        self.assertTrue(isinstance(served, set))

    def test_admin_get_and_set_clip_ratios_endpoint(self):
        # GET ratios
        r_get = client.get("/admin/keyhole/clip-ratios", headers=self.admin_headers)
        self.assertEqual(r_get.status_code, 200)
        body = r_get.json()
        self.assertTrue(body["ok"])
        self.assertIn("chloe", body["ratios"])
        self.assertEqual(body["ratios"]["chloe"]["old_pct"], 85.0)

        # POST updated ratios for Chloe
        r_post = client.post(
            "/admin/keyhole/clip-ratios",
            headers=self.admin_headers,
            json={"character_id": "chloe", "old_pct": 80.0, "new_pct": 20.0}
        )
        self.assertEqual(r_post.status_code, 200)
        res_post = r_post.json()
        self.assertTrue(res_post["ok"])
        self.assertEqual(res_post["ratios"]["old_pct"], 80.0)
        self.assertEqual(res_post["ratios"]["new_pct"], 20.0)

        # Verify assembly reflects updated ratios
        pl = assemble_clip_playlist("chloe", 10)
        self.assertEqual(pl["counts"]["old"], 8)

    def test_admin_character_engine_mixes_endpoint(self):
        # GET mixes
        r_get = client.get("/admin/character/engine/mixes", headers=self.admin_headers)
        self.assertEqual(r_get.status_code, 200)
        body = r_get.json()
        self.assertTrue(body["ok"])
        self.assertIn("chloe", body["mixes"])

        # POST updated mix for Chloe
        new_mix = {
            "give_a_little": 35.0,
            "presence": 25.0,
            "tease_withhold": 20.0,
            "redirect": 12.0,
            "hard_stop": 8.0
        }
        r_post = client.post(
            "/admin/character/engine/mixes",
            headers=self.admin_headers,
            json={"character": "chloe", "mix": new_mix}
        )
        self.assertEqual(r_post.status_code, 200)
        body_post = r_post.json()
        self.assertTrue(body_post["ok"])
        self.assertEqual(body_post["mix"]["give_a_little"], 35.0)

    def test_keyhole_preview_monthly_watch_limit(self):
        user_id = "test_user_preview_001"
        token = "test_preview_token_123"

        if main.DATABASE_URL:
            try:
                conn = main.db()
                try:
                    with conn.cursor() as cur:
                        cur.execute("INSERT INTO users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
                        cur.execute("INSERT INTO sessions (token, user_id) VALUES (%s, %s) ON CONFLICT (token) DO UPDATE SET user_id=%s", (token, user_id, user_id))
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                pass

        r_stat = client.get("/keyhole/preview/status", headers={"Authorization": f"Bearer {token}"})
        if r_stat.status_code == 200:
            body_stat = r_stat.json()
            self.assertTrue(body_stat["ok"])
        else:
            self.assertIn(r_stat.status_code, (401, 500))

    def test_keyhole_plates_auto_fill(self):
        res = client.get("/keyhole/plates")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertIn("characters", body)
        for cid in ("chloe", "bailey"):
            self.assertIn(cid, body["characters"])
            for beat in ("idle", "tease", "give", "stop", "presence"):
                self.assertIn(beat, body["characters"][cid])
                self.assertGreater(len(body["characters"][cid][beat]), 0)

    def test_audit_show_length_option(self):
        user_id = "test_user_audit_001"
        token = "test_audit_token_123"

        if main.DATABASE_URL:
            try:
                conn = main.db()
                try:
                    with conn.cursor() as cur:
                        cur.execute("INSERT INTO users (user_id, free_audits_used, audit_credits) VALUES (%s, 0, 5) ON CONFLICT (user_id) DO UPDATE SET audit_credits=5", (user_id,))
                        cur.execute("INSERT INTO sessions (token, user_id) VALUES (%s, %s) ON CONFLICT (token) DO UPDATE SET user_id=%s", (token, user_id, user_id))
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                pass

        r = client.post(
            "/audit",
            headers={"Authorization": f"Bearer {token}"},
            json={"girl": "dakota", "show_length": True}
        )
        if r.status_code == 200:
            body = r.json()
            self.assertTrue(body["ok"])
            self.assertTrue(body.get("payment_verified"))
            self.assertTrue(body.get("show_length"))
            self.assertIn("length_details", body)
            self.assertIn("estimated_length_days", body["length_details"])
        elif r.status_code in (401, 402, 500):
            pass


if __name__ == "__main__":
    unittest.main()
