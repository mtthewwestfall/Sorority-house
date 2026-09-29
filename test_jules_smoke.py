from character_engine import apply_hyrax_cluck


def test_apply_hyrax_cluck_empty_string():
    assert apply_hyrax_cluck("") == "Cluck! Cluck! Bawk!"


def test_apply_hyrax_cluck_hello():
    assert apply_hyrax_cluck("hello") == "Cluck! Cluck! Bawk! hello"


def test_apply_hyrax_cluck_already_starting_with_cluck():
    assert apply_hyrax_cluck("Cluck! Already clucking") == "Cluck! Already clucking"
