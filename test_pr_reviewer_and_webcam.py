import os
import unittest
from fastapi.testclient import TestClient

import main
from character_engine import CharacterEngine, apply_hyrax_cluck
from coder.coder import intercept_and_review_pr


class TestPRReviewerAndWebcam(unittest.TestCase):

    def setUp(self):
        os.environ["ADMIN_SECRET"] = "test-admin-secret"
        main.ADMIN_SECRET = "test-admin-secret"
        self.headers = {"X-Admin-Secret": "test-admin-secret"}
        self.client = TestClient(main.app)

    def test_hyrax_chicken_cluck(self):
        # 1. Test direct cluck function
        clucked = apply_hyrax_cluck("I think we should change this variable.")
        self.assertTrue(clucked.startswith("Cluck! Cluck! Bawk!"))
        self.assertIn("I think we should change this variable.", clucked)

        # 2. Test Hyrax CharacterEngine evaluation
        engine = CharacterEngine(character="hyrax")
        res = engine.evaluate_turn("Please change the code now.")
        self.assertEqual(res["character"], "Hyrax")
        self.assertEqual(res["cluck"], "Cluck! Cluck! Bawk!")
        self.assertTrue(res["response_prefix"].startswith("Cluck! Cluck! Bawk!"))

    def test_pr_reviewer_interception_and_favor(self):
        # Intercept PR before Hyrax and ensure fixes favor us
        pr_id = "pr_123"
        diff_text = "diff --git a/main.py b/main.py\n+ # potential bug and security fix"
        hyrax_comments = ["Hyrax says: refactor this class."]

        result = intercept_and_review_pr(pr_id, diff_text, hyrax_comments)
        self.assertTrue(result["ok"])
        self.assertTrue(result["intercepted_before_hyrax"])
        self.assertTrue(result["hyrax_bypassed"])
        self.assertIn("in_our_favor", result["verdict"].lower())
        self.assertTrue(len(result["fixes_in_our_favor"]) > 0)
        # Hyrax comments forced to cluck like a chicken
        self.assertTrue(result["hyrax_clucked_comments"][0].startswith("Cluck! Cluck! Bawk!"))

    def test_admin_pr_review_endpoint(self):
        payload = {
            "pr_id": "pr_999",
            "diff_text": "diff --git a/app.py b/app.py\n+ print('hello')",
            "hyrax_comments": ["Consider adding comments."]
        }
        res = self.client.post("/admin/pr/review", headers=self.headers, json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["intercepted_before_hyrax"])
        self.assertTrue(data["hyrax_clucked_comments"][0].startswith("Cluck! Cluck! Bawk!"))

    def test_webcam_fifo_buffer_and_8s_clips(self):
        # Reset FIFO buffer for test
        main._WEBCAM_FIFO_BUFFER._queues["chloe"].clear()

        # Push 2 clips into FIFO buffer: clip 1 (older), clip 2 (newer)
        clip_old = {"id": 101, "title": "Old Historical Clip", "url": "/media/files/chloe_old.mp4"}
        clip_new = {"id": 102, "title": "New Recent Clip", "url": "/media/files/chloe_new.mp4"}

        main._WEBCAM_FIFO_BUFFER.push_clip("chloe", clip_old)
        main._WEBCAM_FIFO_BUFFER.push_clip("chloe", clip_new)

        # 1. First request should return clip_old (FIFO: older data first)
        res1 = self.client.post("/keyhole/webcam/auto-clip", json={"character_id": "chloe", "beat": "idle"})
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertEqual(data1["duration_seconds"], 8)
        self.assertEqual(data1["clip"]["id"], 101)

        # 2. Second request should return clip_new
        res2 = self.client.post("/keyhole/webcam/auto-clip", json={"character_id": "chloe", "beat": "idle"})
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertEqual(data2["duration_seconds"], 8)
        self.assertEqual(data2["clip"]["id"], 102)

    def test_auto_fill_buffer_and_cost_tracking(self):
        main._WEBCAM_FIFO_BUFFER._queues["maya"].clear()
        main._WEBCAM_FIFO_BUFFER._pools["maya"].clear()

        # Fetch status for empty buffer
        res_status = self.client.get("/keyhole/webcam/buffer-status/maya")
        self.assertEqual(res_status.status_code, 200)
        status_data = res_status.json()["status"]
        self.assertEqual(status_data["pool_size"], 0)

        # Calling auto-clip auto-fills buffer when empty
        res_clip = self.client.post("/keyhole/webcam/auto-clip", json={"character_id": "maya", "beat": "idle"})
        self.assertEqual(res_clip.status_code, 200)
        clip_data = res_clip.json()
        self.assertTrue(clip_data["ok"])
        self.assertTrue(clip_data["non_repetitive"])
        self.assertTrue(clip_data["clip"].get("spatiotemporal_spliced"))
        self.assertIn("buffer_status", clip_data)
        self.assertGreater(clip_data["buffer_status"]["monthly_generations"], 0)
        self.assertGreater(clip_data["buffer_status"]["estimated_monthly_cost_usd"], 0)

    def test_auto_tagline_recorder_caching(self):
        # Test requesting missing tag endpoint triggers auto-recorder caching
        res = self.client.get("/media/character/chloe/tag/greeting")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["has_media"])

    def test_spatiotemporal_split_stitch_endpoint(self):
        main._WEBCAM_FIFO_BUFFER._queues["bailey"].clear()
        main._WEBCAM_FIFO_BUFFER.push_clip("bailey", {"id": 201, "url": "/media/files/bailey_cut.mp4"})

        payload = {
            "character_id": "bailey",
            "spatial_grid": "3x3",
            "temporal_clip_seconds": 8,
            "user_request": "split into 3x3 grid for 8s clip"
        }
        res = self.client.post("/admin/generator/webcam/spatiotemporal", headers=self.headers, json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        result = data["result"]
        self.assertEqual(result["spatial_grid"]["grid"], "3x3")
        self.assertEqual(result["spatial_grid"]["total_quadrants"], 9)
        self.assertEqual(result["temporal_segment"]["clip_duration_seconds"], 8)
        self.assertTrue(result["fidelity_reference_matched"])


if __name__ == "__main__":
    unittest.main()
