import unittest
import os
from fastapi.testclient import TestClient
import main


class TestKeyholeAdminAPI(unittest.TestCase):
    def setUp(self):
        os.environ["ADMIN_SECRET"] = "test-admin-secret"
        self.headers = {"X-Admin-Secret": "test-admin-secret"}
        self.client = TestClient(main.app)
        # Reset demo shows state
        self.client.post("/admin/keyhole/shows/demo-simulate", json={"action": "reset"}, headers=self.headers)

    def test_get_shows(self):
        response = self.client.get("/admin/keyhole/shows", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertIn("shows", data)
        self.assertGreaterEqual(len(data["shows"]), 1)

    def test_unauthorized_access(self):
        # Incorrect secret
        response = self.client.get("/admin/keyhole/shows", headers={"X-Admin-Secret": "wrong-secret"})
        self.assertEqual(response.status_code, 403)

    def test_state_machine_validation(self):
        sim_resp = self.client.post("/admin/keyhole/shows/demo-simulate", json={"action": "private_request"}, headers=self.headers)
        shows = sim_resp.json()["shows"]
        show_id = [s for s in shows if s["show_type"] == "private"][-1]["id"]

        # Attempting to END a show that is READY (not LIVE) should fail with 400
        end_fail = self.client.post(f"/admin/keyhole/shows/{show_id}/end", headers=self.headers)
        self.assertEqual(end_fail.status_code, 400)

        # Attempting to PUBLISH a show that is READY (not PREVIEW_READY / approved) should fail with 400
        pub_fail = self.client.post(f"/admin/keyhole/shows/{show_id}/publish-preview", json={"publish_telegram": True}, headers=self.headers)
        self.assertEqual(pub_fail.status_code, 400)

    def test_private_show_workflow(self):
        # 1. Trigger private show request
        sim_resp = self.client.post("/admin/keyhole/shows/demo-simulate", json={"action": "private_request"}, headers=self.headers)
        self.assertEqual(sim_resp.status_code, 200)
        shows = sim_resp.json()["shows"]
        priv_show = [s for s in shows if s["show_type"] == "private"][-1]
        show_id = priv_show["id"]

        self.assertEqual(priv_show["character"], "Chloe")
        self.assertEqual(priv_show["status"], "READY")

        # 2. START SHOW
        start_resp = self.client.post(f"/admin/keyhole/shows/{show_id}/start", headers=self.headers)
        self.assertEqual(start_resp.status_code, 200)
        start_data = start_resp.json()
        self.assertEqual(start_data["show"]["status"], "LIVE")

        # 3. END SHOW
        end_resp = self.client.post(f"/admin/keyhole/shows/{show_id}/end", headers=self.headers)
        self.assertEqual(end_resp.status_code, 200)
        end_data = end_resp.json()
        self.assertEqual(end_data["show"]["status"], "PREVIEW_READY")
        self.assertFalse(end_data["show"]["preview_approved"])

        # Attempting to publish without approving preview first should fail with 400
        unapproved_pub = self.client.post(
            f"/admin/keyhole/shows/{show_id}/publish-preview",
            json={"publish_telegram": True, "publish_website": True},
            headers=self.headers
        )
        self.assertEqual(unapproved_pub.status_code, 400)

        # 4. PREVIEW CHOICE - YES
        choice_resp = self.client.post(f"/admin/keyhole/shows/{show_id}/preview-choice", json={"use_as_preview": True}, headers=self.headers)
        self.assertEqual(choice_resp.status_code, 200)
        self.assertTrue(choice_resp.json()["show"]["preview_approved"])

        # 5. PUBLISH PREVIEW
        pub_resp = self.client.post(
            f"/admin/keyhole/shows/{show_id}/publish-preview",
            json={"publish_telegram": True, "publish_website": True},
            headers=self.headers
        )
        self.assertEqual(pub_resp.status_code, 200)
        pub_data = pub_resp.json()
        self.assertEqual(pub_data["show"]["status"], "PUBLISHED")
        self.assertTrue(pub_data["show"]["published_telegram"])
        self.assertTrue(pub_data["show"]["published_website"])

    def test_public_show_workflow(self):
        # 1. Create Public Show
        create_resp = self.client.post(
            "/admin/keyhole/shows/create-public",
            json={
                "character": "Bailey",
                "scheduled_at": "Tonight — 9:00 PM",
                "price": "$4.99",
                "details": "Special Live Show"
            },
            headers=self.headers
        )
        self.assertEqual(create_resp.status_code, 200)
        show = create_resp.json()["show"]
        show_id = show["id"]
        self.assertEqual(show["character"], "Bailey")
        self.assertEqual(show["status"], "SCHEDULED")
        self.assertEqual(show["viewer_count"], 0)

        # 2. Start Public Show
        start_resp = self.client.post(f"/admin/keyhole/shows/{show_id}/start", headers=self.headers)
        self.assertEqual(start_resp.status_code, 200)
        self.assertEqual(start_resp.json()["show"]["status"], "LIVE")

        # 3. End Public Show
        end_resp = self.client.post(f"/admin/keyhole/shows/{show_id}/end", headers=self.headers)
        self.assertEqual(end_resp.status_code, 200)
        self.assertEqual(end_resp.json()["show"]["status"], "PREVIEW_READY")

        # 4. Reject Preview
        choice_resp = self.client.post(f"/admin/keyhole/shows/{show_id}/preview-choice", json={"use_as_preview": False}, headers=self.headers)
        self.assertEqual(choice_resp.status_code, 200)
        self.assertEqual(choice_resp.json()["show"]["status"], "ENDED")
        self.assertFalse(choice_resp.json()["show"]["preview_approved"])


if __name__ == "__main__":
    unittest.main()
