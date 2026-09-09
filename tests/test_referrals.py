"""Referral / Wingman rules, run against a real Postgres (DATABASE_URL).

    DATABASE_URL=postgresql://... ADMIN_SECRET=x python -m pytest tests/test_referrals.py
"""
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")

import main  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def _schema():
    main.init_db()
    main.set_referral_program(True)


@pytest.fixture(autouse=True)
def _clean_referrals():
    yield
    conn = main.db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM referrals")
            cur.execute("UPDATE users SET shirt_eligible_at=NULL")
        conn.commit()
    finally:
        conn.close()
    main.set_referral_program(True)


def _sql(q, params=()):
    conn = main.db()
    try:
        with conn.cursor() as cur:
            cur.execute(q, params)
            rows = cur.fetchall() if cur.description else None
        conn.commit()
        return rows
    finally:
        conn.close()


def _user(tier="freshman", msg_used=0, audits=0, comp=None):
    uid = "t_" + secrets.token_hex(6)
    _sql("""INSERT INTO users (user_id, display_name, tier, msg_used, free_audits_used,
                               plan_reset_at, comp_until, comp_prev_tier)
            VALUES (%s,'T',%s,%s,%s, now() + interval '10 days', %s, %s)""",
         (uid, tier, msg_used, audits, comp, "sophomore" if comp else None))
    return uid


def _row(uid):
    return _sql("SELECT * FROM users WHERE user_id=%s", (uid,))[0]


def _signup_via(referrer):
    code = _code(referrer)
    uid = _user()
    conn = main.db()
    try:
        with conn.cursor() as cur:
            assert main._attribute_referral(cur, uid, code) == referrer
        conn.commit()
    finally:
        conn.close()
    return uid


def _code(uid):
    conn = main.db()
    try:
        with conn.cursor() as cur:
            c = main._referral_code(cur, uid)
        conn.commit()
        return c
    finally:
        conn.close()


def _pairs():
    return _sql("SELECT count(*) AS n FROM referrals WHERE wingman_at IS NOT NULL")[0]["n"]


def _about(days):
    return datetime.now(timezone.utc) + timedelta(days=days)


def _close(a, b, hours=1):
    return abs((a - b).total_seconds()) < hours * 3600


# --- codes / attribution -------------------------------------------------------

def test_code_is_stable_unique_and_in_link():
    a, b = _user(), _user()
    ca, cb = _code(a), _code(b)
    assert ca == _code(a) and ca != cb and len(ca) == main.REFERRAL_CODE_LEN
    assert main.referral_status(a)["link"].endswith("/?ref=" + ca)


def test_attribution_ignores_bad_or_own_code():
    a = _user()
    conn = main.db()
    with conn.cursor() as cur:
        assert main._attribute_referral(cur, a, "nope1234") == ""
        assert main._attribute_referral(cur, a, _code(a)) == ""
    conn.close()
    assert _row(a)["referred_by"] is None


# --- qualification -------------------------------------------------------------

def test_sophomore_does_not_qualify():
    ref = _user("junior")
    buyer = _signup_via(ref)
    out = main.referral_purchase(buyer, "sophomore")
    assert out["qualified"] is False
    assert main.referral_status(ref)["qualified"] == 0
    assert _row(ref)["tier"] == "junior" and _row(buyer)["tier"] == "freshman"


@pytest.mark.parametrize("tier", ["junior", "senior"])
def test_junior_and_senior_qualify(tier):
    ref = _user("sophomore")
    buyer = _signup_via(ref)
    out = main.referral_purchase(buyer, tier)
    assert out["qualified"] is True and out["qualified_total"] == 1
    assert main.referral_status(ref) | {"qualified": 1, "signups": 1} == main.referral_status(ref)


def test_unreferred_and_renewal_do_not_count():
    assert main.referral_purchase(_user(), "senior")["qualified"] is False
    ref = _user("sophomore")
    buyer = _signup_via(ref)
    assert main.referral_purchase(buyer, "junior")["qualified"] is True
    assert main.referral_purchase(buyer, "junior")["qualified"] is False   # renewal
    assert main.referral_purchase(buyer, "senior")["qualified"] is False   # upgrade
    assert main.referral_status(ref)["qualified"] == 1
    assert _pairs() == 1


def test_program_off_blocks_everything():
    ref = _user("sophomore")
    buyer = _signup_via(ref)
    main.set_referral_program(False)
    out = main.referral_purchase(buyer, "senior")
    assert out == {"qualified": False, "reason": "program off"}
    assert main.referral_status(ref)["qualified"] == 0 and _pairs() == 0
    assert _row(ref)["tier"] == "sophomore"
    # nothing was consumed: the next Junior+ invoice after switching back on qualifies
    main.set_referral_program(True)
    assert main.referral_purchase(buyer, "senior")["qualified"] is True
    assert main.referral_status(ref)["qualified"] == 1 and _pairs() == 1


# --- wingman: non-senior referrer swaps tier and reverts -----------------------

def test_wingman_swaps_both_to_senior_and_reverts_exactly():
    ref = _user("sophomore", msg_used=123, audits=1)
    before = _row(ref)
    buyer = _signup_via(ref)
    # the purchase itself was applied first (as the Stripe path does)
    _sql("UPDATE users SET tier='junior', msg_used=5 WHERE user_id=%s", (buyer,))
    out = main.referral_purchase(buyer, "junior")
    assert out["wingman"] == {"referrer": "upgraded", "buyer": "upgraded"}
    assert _pairs() == 1

    r, b = _row(ref), _row(buyer)
    for u, prev_tier, prev_used, prev_aud in ((r, "sophomore", 123, 1), (b, "junior", 5, 0)):
        assert u["tier"] == "senior" and u["msg_used"] == 0
        assert u["comp_prev_tier"] == prev_tier
        assert u["comp_prev_msg_used"] == prev_used
        assert u["comp_prev_free_audits"] == prev_aud
        assert _close(u["comp_until"], _about(main.WINGMAN_DAYS))
    assert r["comp_prev_reset_at"] == before["plan_reset_at"]

    # 30 days pass: _ensure_user puts each back where they were, not on freshman
    _sql("UPDATE users SET comp_until = now() - interval '1 minute' WHERE user_id IN (%s,%s)",
         (ref, buyer))
    r, b = main._ensure_user(ref), main._ensure_user(buyer)
    assert (r["tier"], r["msg_used"], r["free_audits_used"]) == ("sophomore", 123, 1)
    assert r["plan_reset_at"] == before["plan_reset_at"]
    assert (b["tier"], b["msg_used"]) == ("junior", 5)
    assert r["comp_until"] is None and b["comp_until"] is None


def test_only_first_qualifying_referral_is_a_wingman():
    ref = _user("junior")
    b1, b2 = _signup_via(ref), _signup_via(ref)
    assert main.referral_purchase(b1, "junior")["wingman"]["referrer"] == "upgraded"
    out = main.referral_purchase(b2, "senior")
    assert out["qualified"] is True and out["qualified_total"] == 2 and out["wingman"] == ""
    assert _row(b2)["comp_until"] is None
    assert _pairs() == 1


# --- wingman: already-senior referrer gets 30 more days ------------------------

def test_paid_senior_referrer_gets_free_month_on_plan_reset():
    ref = _user("senior", msg_used=77)
    before = _row(ref)
    buyer = _signup_via(ref)
    out = main.referral_purchase(buyer, "junior")
    assert out["wingman"] == {"referrer": "extended_paid", "buyer": "upgraded"}
    r = _row(ref)
    assert r["tier"] == "senior" and r["msg_used"] == 77 and r["comp_until"] is None
    assert r["plan_reset_at"] == before["plan_reset_at"] + timedelta(days=main.WINGMAN_DAYS)
    b = _row(buyer)
    assert b["tier"] == "senior" and b["comp_prev_tier"] == "freshman"
    assert _close(b["comp_until"], _about(main.WINGMAN_DAYS))


def test_comped_senior_referrer_gets_comp_until_extended():
    ref = _user("senior", comp=_about(5))
    before = _row(ref)
    buyer = _signup_via(ref)
    out = main.referral_purchase(buyer, "senior")
    assert out["wingman"]["referrer"] == "extended_comp"
    r = _row(ref)
    assert r["tier"] == "senior" and r["comp_prev_tier"] == "sophomore"
    assert r["comp_until"] == before["comp_until"] + timedelta(days=main.WINGMAN_DAYS)
    assert r["plan_reset_at"] == before["plan_reset_at"]


def test_stripe_change_during_window_supersedes_wingman():
    ref = _user("sophomore")
    buyer = _signup_via(ref)
    main.referral_purchase(buyer, "junior")
    assert _row(ref)["tier"] == "senior"
    main._apply_tier(_row(ref), "junior")          # referrer buys Junior for real
    r = _row(ref)
    assert r["tier"] == "junior" and r["comp_until"] is None and r["comp_prev_tier"] is None
    assert _pairs() == 1                           # and nothing re-fired


# --- shirt + cap ---------------------------------------------------------------

def test_five_qualifying_referrals_flag_the_shirt():
    ref = _user("junior")
    for i in range(main.SHIRT_REFERRALS):
        assert _row(ref)["shirt_eligible_at"] is None
        out = main.referral_purchase(_signup_via(ref), "junior")
        assert out["shirt"] is (i == main.SHIRT_REFERRALS - 1)
    assert _row(ref)["shirt_eligible_at"] is not None
    assert main.referral_status(ref)["shirt_eligible"] is True
    # a sixth keeps the original timestamp
    at = _row(ref)["shirt_eligible_at"]
    assert main.referral_purchase(_signup_via(ref), "senior")["shirt"] is False
    assert _row(ref)["shirt_eligible_at"] == at


def test_pair_cap_holds_under_concurrency(monkeypatch):
    monkeypatch.setattr(main, "WINGMAN_PAIR_CAP", 3)
    pairs = [(r, _signup_via(r)) for r in (_user("sophomore") for _ in range(8))]
    results, errors = [], []

    def go(buyer):
        try:
            results.append(main.referral_purchase(buyer, "senior"))
        except Exception as e:      # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=go, args=(b,)) for _, b in pairs]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    granted = [o for o in results if isinstance(o["wingman"], dict)]
    capped = [o for o in results if o["wingman"] == "cap reached"]
    assert len(granted) == 3 and len(capped) == 5
    assert _pairs() == 3
    # every referral still qualified and counted, cap or not
    assert all(o["qualified"] for o in results)
    assert sum(_row(r)["tier"] == "senior" for r, _ in pairs) == 3
