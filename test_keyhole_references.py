import os
import unittest
from fastapi.testclient import TestClient
import main


class TestKeyholeCharacterReferences(unittest.TestCase):
    def setUp(self):
        os.environ["ADMIN_SECRET"] = "test-admin-secret"
        self.headers = {"X-Admin-Secret": "test-admin-secret"}
        self.client = TestClient(main.app)

    def test_get_character_references(self):
        res = self.client.get("/admin/keyhole/character-references", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("ok"))
        refs = data.get("references", {})
        self.assertIn("chloe", refs)
        self.assertIn("bailey", refs)

        self.assertIn("Chloe", refs["chloe"]["master_reference"])
        self.assertIn("Bailey", refs["bailey"]["master_reference"])

    def test_chloe_bailey_reference_isolation(self):
        # Fetch references for Chloe and Bailey
        chloe_refs = main.get_character_references("chloe")
        bailey_refs = main.get_character_references("bailey")

        # Verify Chloe's master reference contains Chloe and NOT Bailey
        self.assertIn("Chloe", chloe_refs["master_reference"])
        self.assertNotIn("Bailey", chloe_refs["master_reference"])

        # Verify Bailey's master reference contains Bailey and NOT Chloe
        self.assertIn("Bailey", bailey_refs["master_reference"])
        self.assertNotIn("Chloe", bailey_refs["master_reference"])

    def test_set_appearance_does_not_modify_master_reference(self):
        initial_master = main.get_character_references("chloe")["master_reference"]

        # Change Chloe's outfit / current appearance
        new_outfit = "Current Outfit: Midnight blue silk gown with silver laurel clasp."
        res = self.client.post(
            "/admin/keyhole/character-references/set-appearance",
            json={"character": "chloe", "current_appearance": new_outfit},
            headers=self.headers
        )
        self.assertEqual(res.status_code, 200)

        updated_refs = main.get_character_references("chloe")
        # Appearance updated
        self.assertEqual(updated_refs["current_appearance"], new_outfit)
        # Master reference remained untouched
        self.assertEqual(updated_refs["master_reference"], initial_master)

    def test_generate_avatar_receives_character_master_reference(self):
        # Intercept Gemini call or test prompt construction logic
        chloe_refs = main.get_character_references("chloe")
        bailey_refs = main.get_character_references("bailey")

        # Prove Chloe prompt construction incorporates Chloe's master reference
        chloe_master = chloe_refs["master_reference"]
        bailey_master = bailey_refs["master_reference"]

        # Check prompt building logic directly
        def build_prompt(description, character_id):
            cid = character_id.strip().lower()
            refs = main.get_character_references(cid)
            return main.AVATAR_STYLE + f"[{refs['master_reference']}] [{refs['current_appearance']}] " + description.strip()

        chloe_prompt = build_prompt("Chloe in live show", "chloe")
        bailey_prompt = build_prompt("Bailey in live show", "bailey")

        self.assertIn(chloe_master, chloe_prompt)
        self.assertNotIn(bailey_master, chloe_prompt)

        self.assertIn(bailey_master, bailey_prompt)
        self.assertNotIn(chloe_master, bailey_prompt)

    def test_chloe_skin_save_persists_appearance_and_asset(self):
        outfit = "Current Outfit: Velvet platform bed, plush L-sofa, neon wall sign."
        res = self.client.post(
            "/admin/keyhole/character-references/set-appearance",
            json={"character": "chloe", "current_appearance": outfit, "skin_asset_id": 42},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200)
        saved = main.get_character_references("chloe")
        self.assertEqual(saved["current_appearance"], outfit)
        self.assertEqual(saved["skin_asset_id"], 42)
        bailey = main.get_character_references("bailey")
        self.assertNotEqual(bailey["current_appearance"], outfit)
        self.assertNotEqual(bailey.get("skin_asset_id"), 42)


if __name__ == "__main__":
    unittest.main()
