import os
import unittest
from unittest.mock import MagicMock, patch

import main


class TestClipHistoryAndAssembly(unittest.TestCase):

    def setUp(self):
        main._IN_MEMORY_CLIP_HISTORY.clear()

    def test_1_clip_history_persisted(self):
        recorded = main.record_clip_history("user_123", "chloe", "clip_001", "show_abc")
        self.assertTrue(recorded)
        served = main.get_served_clip_ids("user_123", "chloe")
        self.assertIn("clip_001", served)

    def test_2_previously_served_clip_is_excluded(self):
        main.record_clip_history("user_123", "chloe", "clip_001")
        pool = [
            {"id": "clip_001", "title": "Clip 1"},
            {"id": "clip_002", "title": "Clip 2"},
            {"id": "clip_003", "title": "Clip 3"},
        ]
        res = main.assemble_clip_playlist("user_123", "chloe", 2, pool)
        served_ids = [c["id"] for c in res["playlist"]]
        self.assertNotIn("clip_001", served_ids)
        self.assertIn("clip_002", served_ids)

    def test_3_different_users_do_not_share_history(self):
        main.record_clip_history("user_A", "chloe", "clip_001")
        served_A = main.get_served_clip_ids("user_A", "chloe")
        served_B = main.get_served_clip_ids("user_B", "chloe")
        self.assertIn("clip_001", served_A)
        self.assertNotIn("clip_001", served_B)

    def test_4_different_characters_do_not_share_history(self):
        main.record_clip_history("user_123", "chloe", "clip_001")
        served_chloe = main.get_served_clip_ids("user_123", "chloe")
        served_bailey = main.get_served_clip_ids("user_123", "bailey")
        self.assertIn("clip_001", served_chloe)
        self.assertNotIn("clip_001", served_bailey)

    def test_5_85_15_assembly_ratio(self):
        pool = [{"id": f"banked_{i}"} for i in range(1, 20)]
        new_gen = lambda cid, idx: {"id": f"new_{idx}"}
        res = main.assemble_clip_playlist("user_123", "chloe", 10, pool, new_generator_fn=new_gen)
        self.assertEqual(res["total_clips"], 10)
        self.assertEqual(res["target_banked"], 9)
        self.assertEqual(res["target_new"], 1)
        self.assertEqual(res["banked_served"], 9)
        self.assertEqual(res["new_served"], 1)

    def test_6_small_playlist_sizes(self):
        sizes = [1, 2, 3, 5, 10]
        expected_splits = {
            1: (1, 0),
            2: (2, 0),
            3: (3, 0),
            5: (4, 1),
            10: (9, 1),
        }
        for size in sizes:
            banked, new_clips = main.calculate_85_15_counts(size)
            self.assertEqual((banked, new_clips), expected_splits[size], f"Failed for size {size}")

    def test_7_non_divisible_playlist_sizes(self):
        sizes = [7, 11, 13, 17, 23]
        for size in sizes:
            banked, new_clips = main.calculate_85_15_counts(size)
            self.assertEqual(banked + new_clips, size)
            self.assertGreaterEqual(banked, 1)

    def test_8_exhausted_banked_pool(self):
        # Pool has only 2 clips, but 10 are requested (target 9 banked, 1 new)
        pool = [{"id": "banked_1"}, {"id": "banked_2"}]
        new_gen = lambda cid, idx: {"id": f"new_{idx}"}
        res = main.assemble_clip_playlist("user_123", "chloe", 10, pool, new_generator_fn=new_gen)
        self.assertTrue(res["exhausted_banked"])
        self.assertEqual(res["total_clips"], 10)
        self.assertEqual(res["banked_served"], 2)

    def test_9_no_infinite_selection_loop(self):
        # Empty banked pool and no new generator function
        res = main.assemble_clip_playlist("user_123", "chloe", 10, [], new_generator_fn=None)
        self.assertEqual(res["total_clips"], 0)
        self.assertEqual(res["playlist"], [])

    def test_10_served_clips_are_recorded(self):
        pool = [{"id": "banked_A"}, {"id": "banked_B"}]
        main.assemble_clip_playlist("user_999", "bailey", 2, pool)
        served = main.get_served_clip_ids("user_999", "bailey")
        self.assertIn("banked_A", served)
        self.assertIn("banked_B", served)

    def test_11_history_uniqueness_prevents_duplicate_records(self):
        r1 = main.record_clip_history("user_123", "chloe", "clip_001")
        r2 = main.record_clip_history("user_123", "chloe", "clip_001")
        self.assertTrue(r1)
        self.assertTrue(r2)
        served = main.get_served_clip_ids("user_123", "chloe")
        self.assertEqual(len(served), 1)


if __name__ == "__main__":
    unittest.main()
