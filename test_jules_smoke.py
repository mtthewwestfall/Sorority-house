import unittest
from character_engine import apply_hyrax_cluck


class TestJulesSmoke(unittest.TestCase):
    def test_apply_hyrax_cluck_empty_string(self):
        self.assertEqual(apply_hyrax_cluck(""), "Cluck! Cluck! Bawk!")

    def test_apply_hyrax_cluck_hello(self):
        self.assertEqual(apply_hyrax_cluck("hello"), "Cluck! Cluck! Bawk! hello")

    def test_apply_hyrax_cluck_already_starting_with_cluck(self):
        self.assertEqual(apply_hyrax_cluck("Cluck! Already clucking"), "Cluck! Already clucking")
