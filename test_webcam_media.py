import json
import unittest
from unittest.mock import patch, MagicMock
from fastapi.exceptions import HTTPException
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

class TestWebcamMediaManager(unittest.TestCase):

    def setUp(self):
        main.ADMIN_SECRET = "test-admin-secret"

    def test_parse_tags_input(self):
        tags_list = main._parse_tags_input([" idle ", "talking ", "IDLE"])
        self.assertEqual(tags_list, ["idle", "talking"])

        tags_str = main._parse_tags_input('["sitting-bed", "desk"]')
        self.assertEqual(tags_str, ["sitting-bed", "desk"])

        tags_comma = main._parse_tags_input("chair, greeting, chair")
        self.assertEqual(tags_comma, ["chair", "greeting"])

    @patch("main.db")
    def test_admin_list_media(self, mock_db):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            {
                "id": 1,
                "character_id": "dakota",
                "title": "Dakota Idle",
                "media_type": "video",
                "url": "/media/files/dakota_idle.mp4",
                "file_path": "dakota_idle.mp4",
                "tags": ["idle"],
                "is_default": True,
                "is_fallback": False,
                "is_enabled": True,
                "created_at": "2026-09-01T00:00:00Z",
                "updated_at": "2026-09-01T00:00:00Z"
            }
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_db.return_value = mock_conn

        headers = {"X-Admin-Secret": "test-admin-secret"}
        res = client.get("/admin/media?character_id=dakota", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["assets"]), 1)
        self.assertEqual(data["assets"][0]["character_id"], "dakota")

    @patch("main.db")
    def test_admin_import_media_url(self, mock_db):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {
            "id": 10,
            "character_id": "zoe",
            "title": "Zoe Intro Video",
            "media_type": "video",
            "url": "https://cdn.example.com/zoe_intro.mp4",
            "file_path": "",
            "tags": ["greeting", "talking"],
            "is_default": True,
            "is_fallback": False,
            "is_enabled": True,
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z"
        }
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_db.return_value = mock_conn

        headers = {"X-Admin-Secret": "test-admin-secret"}
        payload = {
            "character_id": "zoe",
            "url": "https://cdn.example.com/zoe_intro.mp4",
            "title": "Zoe Intro Video",
            "media_type": "video",
            "tags": ["greeting", "talking"],
            "is_default": True,
            "is_enabled": True
        }
        res = client.post("/admin/media/import-url", headers=headers, json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["asset"]["character_id"], "zoe")
        self.assertEqual(data["asset"]["url"], "https://cdn.example.com/zoe_intro.mp4")

    @patch("main.db")
    def test_customer_get_default_media(self, mock_db):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {
            "id": 5,
            "character_id": "dakota",
            "title": "Dakota Idle Video",
            "media_type": "video",
            "url": "/media/files/dakota_default.mp4",
            "tags": ["idle"],
            "is_default": True,
            "is_fallback": False
        }
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_db.return_value = mock_conn

        res = client.get("/media/character/dakota/default")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["fallback"])
        self.assertEqual(data["asset"]["character_id"], "dakota")
        self.assertEqual(data["asset"]["url"], "/media/files/dakota_default.mp4")

    @patch("main.db")
    def test_customer_get_media_by_tag(self, mock_db):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {
            "id": 8,
            "character_id": "dakota",
            "title": "Dakota Sitting Bed",
            "media_type": "video",
            "url": "/media/files/dakota_bed.mp4",
            "tags": ["sitting-bed"],
            "is_default": False,
            "is_fallback": False
        }
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_db.return_value = mock_conn

        res = client.get("/media/character/dakota/tag/sitting-bed")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["asset"]["character_id"], "dakota")
        self.assertEqual(data["asset"]["url"], "/media/files/dakota_bed.mp4")

    @patch("main.db")
    def test_strict_character_isolation_when_no_media(self, mock_db):
        """Verify that when Character B has no media matching a tag, it falls back
        ONLY to Character B's default/fallback and NEVER returns Character A's media."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        # 1. First fetch for tag match returns None
        # 2. Second fetch for default returns None
        # 3. Third fetch for idle video returns None
        # 4. Fourth fetch for any video returns None
        # 5. Fallback query for fallback asset returns None
        # 6. Fallback persona avatar query returns persona info
        mock_cur.fetchone.side_effect = [
            None, # no tag match for character 'zoe'
            None, # no default for 'zoe'
            None, # no idle for 'zoe'
            None, # no video for 'zoe'
            None, # no explicit fallback asset for 'zoe'
            {"name": "Zoe", "avatar_url": "assets/zoe.jpg?v=3"} # persona avatar
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_db.return_value = mock_conn

        res = client.get("/media/character/zoe/tag/sitting-bed")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["fallback"])
        self.assertEqual(data["asset"]["character_id"], "zoe")
        self.assertEqual(data["asset"]["url"], "assets/zoe.jpg?v=3")

    @patch("main.db")
    def test_admin_update_set_default_delete(self, mock_db):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {
            "id": 12,
            "character_id": "dakota",
            "title": "Dakota Clip",
            "media_type": "video",
            "file_path": "",
            "is_default": True
        }
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_db.return_value = mock_conn

        headers = {"X-Admin-Secret": "test-admin-secret"}

        # Set default
        res_def = client.post("/admin/media/12/set-default", headers=headers)
        self.assertEqual(res_def.status_code, 200)
        self.assertTrue(res_def.json()["ok"])

        # Delete
        res_del = client.delete("/admin/media/12", headers=headers)
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(res_del.json()["deleted_asset_id"], 12)

    @patch("requests.get")
    def test_fetch_remote_media_html_scraping_and_headers(self, mock_get):
        # Mock HTML response with og:video tag
        html_resp = MagicMock()
        html_resp.headers = {"content-type": "text/html; charset=utf-8"}
        html_resp.text = '<html><head><meta property="og:video" content="https://example.com/stream.mp4"></head></html>'

        # Mock direct video response
        video_resp = MagicMock()
        video_resp.headers = {"content-type": "video/mp4"}
        video_resp.content = b"fake-mp4-video-stream-content"
        video_resp.url = "https://example.com/stream.mp4"

        mock_get.side_effect = [html_resp, video_resp]

        content, ext, mime, mtype = main._fetch_remote_media("https://example.com/webcam-page", target_format="original")
        self.assertEqual(content, b"fake-mp4-video-stream-content")
        self.assertEqual(ext, ".mp4")
        self.assertEqual(mtype, "video")
        self.assertEqual(mock_get.call_count, 2)

    def test_convert_image_bytes(self):
        from PIL import Image
        import io
        img = Image.new("RGB", (50, 50), color="blue")
        out_raw = io.BytesIO()
        img.save(out_raw, format="PNG")
        png_bytes = out_raw.getvalue()

        converted_bytes, ext, mime = main._convert_image_bytes(png_bytes, "webp")
        self.assertEqual(ext, ".webp")
        self.assertEqual(mime, "image/webp")
        self.assertTrue(len(converted_bytes) > 0)

if __name__ == "__main__":
    unittest.main()
