import unittest
from unittest.mock import patch, MagicMock
from fastapi.exceptions import HTTPException

import main

EXACT_PROMPT = (
    "Ancient Greek cartoon-realistic portrait — a detailed semi-realistic digital illustration "
    "blending lifelike facial features with clean stylized cartoon art, the God's Greek house style. "
    "Subject in ancient Greek dress (toga or chiton with laurel accents), medium close-up from the "
    "chest up, looking directly at the viewer. Background: a Greek temple among tall pines, "
    "soft golden daylight. Fully clothed, tasteful, natural expression. No text, no watermarks."
)

class TestCompanionAndStyles(unittest.TestCase):

    def setUp(self):
        main.GEMINI_API_KEY = "dummy_test_key"

    def test_1_companion_portrait_style_variable(self):
        self.assertIn("Background: a Greek temple among tall pines, soft golden daylight.", main._COMPANION_PORTRAIT_STYLE)
        self.assertIn("Subject in ancient Greek dress (toga or chiton with laurel accents)", main._COMPANION_PORTRAIT_STYLE)
        self.assertIn("Use the photo ONLY as a likeness reference for the face.", main._COMPANION_PORTRAIT_STYLE)
        self.assertIn("Never reproduce the photo itself.", main._COMPANION_PORTRAIT_STYLE)

    def test_2_avatar_style_variable(self):
        self.assertIn(EXACT_PROMPT, main.AVATAR_STYLE)
        self.assertTrue(main.AVATAR_STYLE.endswith("The person depicted is: "))

    @patch("main.requests.post")
    def test_3_generate_avatar_from_photo(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "b64data"}}]}}]
        }
        mock_post.return_value = mock_resp

        mime, b64 = main.generate_avatar_from_photo(b"fakebytes", "image/png", "Athena", "female")
        self.assertEqual(b64, "b64data")

        payload = mock_post.call_args[1]["json"]
        parts = payload["contents"][0]["parts"]
        prompt_text = next(p["text"] for p in parts if "text" in p)
        self.assertIn("Ancient Greek cartoon-realistic portrait — a detailed semi-realistic digital illustration", prompt_text)
        self.assertIn("Use the photo ONLY as a likeness reference for the face.", prompt_text)

    @patch("main.requests.post")
    def test_4_switch_hairstyle(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "b64data"}}]}}]
        }
        mock_post.return_value = mock_resp

        with patch("main.db") as mock_db:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = {"portrait_url": "data:image/png;base64,ZmFrZWJ5dGVz"}
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_db.return_value = mock_conn

            res = main.switch_hairstyle(1, main.HairstyleIn(style_label="braided crown"), MagicMock(user_id="u1"))
            self.assertTrue(res["ok"])

            payload = mock_post.call_args[1]["json"]
            parts = payload["contents"][0]["parts"]
            prompt_text = next(p["text"] for p in parts if "text" in p)
            self.assertIn("Ancient Greek cartoon-realistic portrait — a detailed semi-realistic digital illustration", prompt_text)
            self.assertIn("change ONLY the hairstyle to: braided crown", prompt_text)

    @patch("main.requests.post")
    def test_5_generate_avatar(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "b64data"}}]}}]
        }
        mock_post.return_value = mock_resp

        mime, b64 = main.generate_avatar("tall warrior with shield")
        self.assertEqual(b64, "b64data")

        payload = mock_post.call_args[1]["json"]
        parts = payload["contents"][0]["parts"]
        prompt_text = next(p["text"] for p in parts if "text" in p)
        self.assertIn(EXACT_PROMPT, prompt_text)

    @patch("main.requests.post")
    @patch("main.moderate_companion_photo")
    def test_6_set_avatar_from_preset(self, mock_mod, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "b64data"}}]}}]
        }
        mock_post.return_value = mock_resp

        with patch("main.db") as mock_db:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_db.return_value = mock_conn

            res = main.set_avatar_from_preset(main.AvatarPresetIn(image_b64="ZmFrZWJ5dGVz"), MagicMock(user_id="u1"))
            self.assertTrue(res["ok"])

            payload = mock_post.call_args[1]["json"]
            parts = payload["contents"][0]["parts"]
            prompt_text = next(p["text"] for p in parts if "text" in p)
            self.assertIn(EXACT_PROMPT, prompt_text)
            self.assertIn("Redraw it fully in the God's Greek portrait style", prompt_text)

    @patch("main.requests.post")
    def test_7_generate_picture(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "b64data"}}]}}]
        }
        mock_post.return_value = mock_resp

        mime, b64 = main.generate_picture("dakota", "Dakota", None, portrait=("image/png", b"fakebytes"), scenes=["a custom test scene"])
        self.assertEqual(b64, "b64data")

        payload = mock_post.call_args[1]["json"]
        parts = payload["contents"][0]["parts"]
        prompt_text = next(p["text"] for p in parts if "text" in p)
        self.assertIn("Create a new picture of Dakota, the same person as in the reference image:", prompt_text)
        self.assertIn("Ancient Greek cartoon-realistic portrait — a detailed semi-realistic digital illustration", prompt_text)
        self.assertIn("Scene: a custom test scene.", prompt_text)
        self.assertNotIn("{scene}", prompt_text)
        self.assertIn("phone-camera framing", prompt_text)

    def test_8_companion_content_safety(self):
        with self.assertRaises(HTTPException):
            main.check_companion_content_safety("Contains sexual violence keyword")
        main.check_companion_content_safety("A friendly librarian from the town.")

    def test_9_companion_ratchet_gate_milestone(self):
        comp = {"milestone": 4, "stage_days": 2}
        res_lower = main.companion_gate_milestone(comp, 2, "cold")
        self.assertEqual(res_lower, 4)
        res_advance = main.companion_gate_milestone(comp, 5, "warm")
        self.assertEqual(res_advance, 5)

    def test_10_portrait_bytes_local_file(self):
        res = main._portrait_bytes("assets/dakota.jpg")
        self.assertIsNotNone(res)
        mime, buf = res
        self.assertEqual(mime, "image/jpeg")
        self.assertGreater(len(buf), 0)

if __name__ == "__main__":
    unittest.main()
