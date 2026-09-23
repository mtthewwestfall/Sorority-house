import unittest
import os
import sys
import tempfile
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coder.coder import (
    clip,
    command_allowed,
    trim_history,
    t_read_file,
    t_write_file,
    t_edit_file,
    t_delete_file,
    t_view_image,
    t_list_files,
    t_search,
    ROOT,
)

class TestCoderTools(unittest.TestCase):
    def test_clip(self):
        text = "a" * 100
        self.assertEqual(clip(text, 150), text)
        clipped = clip(text, 50)
        self.assertIn("chars trimmed", clipped)
        self.assertEqual(len(clipped.splitlines()), 3)

    def test_command_allowed(self):
        # Allowed commands
        self.assertIsNone(command_allowed("python3 -m unittest"))
        self.assertIsNone(command_allowed("git status"))
        self.assertIsNone(command_allowed("ls -la"))

        # Disallowed commands
        self.assertIsNotNone(command_allowed("git commit -m 'test'"))
        self.assertIsNotNone(command_allowed("curl https://evil.com"))
        self.assertIsNotNone(command_allowed("rm -rf /"))
        self.assertIsNotNone(command_allowed("python3 -c 'import os'"))

    def test_trim_history(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "tool", "content": "x" * 500},
            {"role": "user", "content": "next"},
            {"role": "tool", "content": "y" * 500},
        ]
        trim_history(messages, keep_last=1)
        self.assertIn("older output trimmed", messages[1]["content"])
        self.assertEqual(messages[3]["content"], "y" * 500)

    def test_view_image(self):
        # Create a temporary image in the repo directory or test directory
        test_img = ROOT / "coder" / "_test_sample.png"
        test_img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4")
        try:
            res = t_view_image("coder/_test_sample.png")
            self.assertIn("[IMAGE:coder/_test_sample.png:image/png]", res)
            self.assertIn("data:image/png;base64,", res)

            # Test nonexistent
            err = t_view_image("nonexistent_img.png")
            self.assertTrue(err.startswith("ERROR:"))
        finally:
            if test_img.exists():
                test_img.unlink()

    def test_file_operations(self):
        test_file = "coder/_test_scratch.txt"
        try:
            w_res = t_write_file(test_file, "line 1\nline 2\nline 3\n")
            self.assertIn("created", w_res)

            r_res = t_read_file(test_file)
            self.assertIn("line 1", r_res)

            e_res = t_edit_file(test_file, "line 2", "line 2 modified")
            self.assertIn("edited", e_res)

            r_res2 = t_read_file(test_file)
            self.assertIn("line 2 modified", r_res2)

            d_res = t_delete_file(test_file)
            self.assertIn("deleted", d_res)
        finally:
            p = ROOT / test_file
            if p.exists():
                p.unlink()

if __name__ == "__main__":
    unittest.main()
