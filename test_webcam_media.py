import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from fastapi.exceptions import HTTPException
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

class TestWebcamMediaManager(unittest.TestCase):

    def setUp(self):
        os.environ["ADMIN_SECRET"] = "test-admin-secret"
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

    @patch("socket.getaddrinfo")
    @patch("main.db")
    def test_admin_import_media_url(self, mock_db, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
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
            "is_enabled": True,
            "download_remote": False,
            "key1": "Westfall13!",
            "key2": "Saintkiller13!"
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

    @patch("main._safe_http_get")
    def test_fetch_remote_media_html_scraping_and_headers(self, mock_safe_get):
        # Mock HTML response with og:video tag
        html_resp = MagicMock()
        html_resp.headers = {"content-type": "text/html; charset=utf-8"}
        html_resp.text = '<html><head><meta property="og:video" content="https://example.com/stream.mp4"></head></html>'

        # Mock direct video response with valid MP4 header (ftyp)
        mp4_bytes = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"fake-video-payload"
        video_resp = MagicMock()
        video_resp.headers = {"content-type": "video/mp4"}
        video_resp.iter_content.return_value = [mp4_bytes]
        video_resp.url = "https://example.com/stream.mp4"

        mock_safe_get.side_effect = [html_resp, video_resp]

        content, ext, mime, mtype = main._fetch_remote_media("https://example.com/webcam-page", target_format="original")
        self.assertEqual(content, mp4_bytes)
        self.assertEqual(ext, ".mp4")
        self.assertEqual(mtype, "video")
        self.assertEqual(mock_safe_get.call_count, 2)

    @patch("socket.getaddrinfo")
    def test_ssrf_ip_validation(self, mock_getaddrinfo):
        # Mock getaddrinfo returning private/loopback IP 127.0.0.1
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 80))]
        with self.assertRaises(HTTPException) as ctx:
            main._validate_media_url("http://localhost/admin/secret")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("internal network address", ctx.exception.detail)

    def test_remote_media_size_limit(self):
        mock_resp = MagicMock()
        # Stream chunks exceeding MAX_MEDIA_UPLOAD_BYTES
        mock_resp.iter_content.return_value = [b"A" * (64 * 1024) for _ in range(2000)]
        with patch("main.MAX_MEDIA_UPLOAD_BYTES", 1024 * 1024):  # 1MB limit for test
            with self.assertRaises(ValueError) as ctx:
                main._download_stream(mock_resp)
            self.assertIn("exceeds maximum allowed size", str(ctx.exception))

    def test_file_signature_validation(self):
        invalid_bytes = b"THIS IS NOT A MEDIA FILE TEXT PLAIN CONTENT"
        with self.assertRaises(ValueError) as ctx:
            main._detect_and_validate_media_signature(invalid_bytes, file_url="https://example.com/fake.txt")
        self.assertIn("Invalid media signature", str(ctx.exception))

    def test_generic_mime_mp4_classification(self):
        # Valid mp4 magic signature with ftyp box
        mp4_content = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"video-data"
        m_type, ext, mime = main._detect_and_validate_media_signature(mp4_content, file_url="https://cdn.example.com/stream.mp4")
        self.assertEqual(m_type, "video")
        self.assertEqual(ext, ".mp4")
        self.assertEqual(mime, "video/mp4")

    @patch("main.db")
    def test_import_url_needs_only_admin_secret(self, mock_db):
        # 1. Reject without the admin secret
        res_fail = client.post("/admin/media/import-url", json={
            "character_id": "zoe",
            "url": "https://example.com/video.mp4"
        })
        self.assertEqual(res_fail.status_code, 403)

        # 2. Accept with ADMIN_SECRET alone (no second password)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {
            "id": 20,
            "character_id": "zoe",
            "title": "Zoe Video",
            "media_type": "video",
            "url": "https://example.com/video.mp4",
            "file_path": "",
            "tags": [],
            "is_default": False,
            "is_fallback": False,
            "is_enabled": True
        }
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_db.return_value = mock_conn

        res_ok = client.post("/admin/media/import-url", headers={"X-Admin-Secret": "test-admin-secret"}, json={
            "character_id": "zoe",
            "url": "https://example.com/video.mp4",
            "download_remote": False
        })
        self.assertEqual(res_ok.status_code, 200)
        self.assertTrue(res_ok.json()["ok"])

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

    def test_ftyp_later_in_the_header_is_video(self):
        content = b"\x00" * 16 + b"ftypisom" + b"\x00" * 32
        m_type, ext, mime = main._detect_and_validate_media_signature(
            content, file_url="https://cdn.example.com/clip.mp4")
        self.assertEqual(m_type, "video")
        self.assertEqual(ext, ".mp4")
        self.assertEqual(mime, "video/mp4")

    @patch("main._fetch_remote_media")
    @patch("main.db")
    def test_remote_reference_is_cached_locally(self, mock_db, mock_fetch):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
        mock_fetch.return_value = (png, ".png", "image/png", "image")
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = {
            "id": 7, "character_id": "chloe",
            "url": "https://cdn.example.com/chloe-skin.png",
            "file_path": "", "media_type": "image", "tags": ["skin", "reference"],
        }
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(main, "UPLOAD_DIR", folder):
                data = main._character_reference("chloe", 7)
            self.assertEqual(data[0], png)
            self.assertEqual(data[1], "image/png")
            names = os.listdir(folder)
        self.assertTrue(any(name.startswith("skin_chloe_") and name.endswith(".png") for name in names))
        mock_fetch.assert_called_once()
        self.assertEqual(mock_fetch.call_args.kwargs.get("prefer"), "image")

    def test_disk_skin_satisfies_explicit_reference_without_database(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            Image.new("RGB", (4, 4), color="red").save(os.path.join(folder, "skin_chloe_saved.png"))
            with patch.object(main, "UPLOAD_DIR", folder):
                with patch.object(main, "db", side_effect=HTTPException(status_code=500, detail="DATABASE_URL not set")):
                    data = main._character_reference("chloe", 44)
        self.assertTrue(data[0].startswith(b"\x89PNG"))
        self.assertEqual(data[1], "image/png")

    @patch("main._character_reference", return_value=(b"skin", "image/png"))
    def test_video_import_stays_video_and_marks_skin(self, _ref):
        content, ext, mime, media_type, skinned = main._apply_character_skin_bytes(
            "chloe", b"video-bytes", ".mp4", "video/mp4", "video")
        self.assertEqual(content, b"video-bytes")
        self.assertEqual(media_type, "video")
        self.assertEqual(ext, ".mp4")
        self.assertTrue(skinned)

    @patch("main._save_generated_asset", return_value={"id": 3, "url": "/media/files/chloe_loop.mp4"})
    @patch("main._apply_character_skin_bytes", return_value=(b"vid", ".mp4", "video/mp4", "video", True))
    @patch("main._fetch_remote_media", return_value=(b"vid", ".mp4", "video/mp4", "video"))
    @patch("main._validate_media_url", side_effect=lambda url: url)
    def test_content_record_keeps_video_and_applies_skin(self, _valid, mock_fetch, mock_skin, mock_save):
        res = client.post("/admin/keyhole/content/record", headers={"X-Admin-Secret": "test-admin-secret"}, json={
            "character_id": "chloe",
            "url": "https://cdn.example.com/loop.mp4",
            "tag": "tease",
            "loop_seconds": 120,
        })
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["media_type"], "video")
        self.assertTrue(body["skinned"])
        self.assertEqual(body["loop_seconds"], 120)
        self.assertEqual(mock_skin.call_args.args[0], "chloe")
        saved_tags = mock_save.call_args.args[5]
        self.assertIn("skinned", saved_tags)
        self.assertIn("loop:120", saved_tags)
        self.assertIn("download", saved_tags)


if __name__ == "__main__":
    unittest.main()
