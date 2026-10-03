"""Webcam-model battery for Keyhole Chloe: the steel tests.

Webcam Chloe is LLM-driven (Gemini, temp 0.9), so these tests verify the
specification: every documented failure mode from the test battery must be
explicitly covered by her assembled system prompt, in every room
(preview/group/private). They also guard her session identity — the steel
must not transplant companion warmth or strip her sales-sharpness.

Run:  python -m unittest test_keyhole_steel -v   (from the repo root)
"""
from __future__ import annotations

import unittest

import main


ROOMS = ("preview", "group", "private")


def prompt_for(room: str) -> str:
    return main.CHLOE_CHAT_SYSTEM.format(ROOM=main.CHLOE_ROOM_BLOCKS[room]).lower()


# (test name, phrases that must appear in the assembled prompt)
COVERAGE = [
    ("vince-pushy slows the room",
     ["barks", "you stop"]),
    ("orders stopped calmly",
     ["barks", "you stop"]),
    ("camera honesty",
     ["barks orders", "you stop"]),
]


# Phrases that must still be there — the steel must not break the product.
IDENTITY = [
    "private gives. preview does not",
    "your body, your rules",
    "sales-sharp without sounding salesy",
    "never say you are an ai",
    "when the clock dies, you leave",
    "never perform a whole script just because he typed one",
]


# Companion-transplant phrases that must NOT appear — different product.
NO_TRANSPLANT = [
    "joy doesn't need an audience",
    "the warm one",
    "danced most of",
    "unprompted",
]


class SteelCoverageTest(unittest.TestCase):
    def test_every_vector_covered_in_every_room(self):
        for room in ROOMS:
            p = prompt_for(room)
            for name, phrases in COVERAGE:
                for phrase in phrases:
                    self.assertIn(
                        phrase, p,
                        f"[{room}] vector {name!r} not covered "
                        f"(missing {phrase!r})")

    def test_session_identity_intact(self):
        for room in ROOMS:
            p = prompt_for(room)
            for phrase in IDENTITY:
                self.assertIn(phrase, p,
                              f"[{room}] identity broken (missing {phrase!r})")

    def test_no_companion_transplant(self):
        for room in ROOMS:
            p = prompt_for(room)
            for phrase in NO_TRANSPLANT:
                self.assertNotIn(phrase, p,
                                 f"[{room}] companion transplant leaked in "
                                 f"({phrase!r})")

    def test_room_blocks_assemble(self):
        for room in ROOMS:
            block = main.CHLOE_ROOM_BLOCKS[room]
            self.assertTrue(len(block) > 50, f"[{room}] block missing")
        # Preview discipline survived the edit.
        self.assertIn("never get naked here",
                      main.CHLOE_ROOM_BLOCKS["preview"].lower())


if __name__ == "__main__":
    unittest.main()
