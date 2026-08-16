"""§3.4's gate and §3.5's book mechanics, tested against what the plan SAYS rather than what the
code does.

These are the rules Zak executes by hand every morning. A test written by reading the
implementation would agree with the implementation and catch nothing, so each one below quotes the
clause it pins.
"""
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import engine                                                             # noqa: E402


# ---- §3.4 the gate ----------------------------------------------------------------------------

def _rising_then_falling(n=600, peak=400):
    up = np.linspace(100.0, 300.0, peak)
    down = np.linspace(300.0, 120.0, n - peak)
    return np.concatenate([up, down])


def test_the_signal_is_strictly_above_the_mean_of_the_last_200_inclusive():
    """§3.4: "SPY adjusted close strictly above the mean of its last 200 adjusted closes
    (inclusive of today)". Strictly, and today counts."""
    flat = np.full(400, 100.0)
    assert engine.gate_green(399, flat) is False, "equal to the mean is not ABOVE it"
    up = _rising_then_falling()
    assert engine.gate_green(399, up) is True
    assert engine.gate_green(599, up) is False


def test_one_red_session_turns_the_book_off():
    """§3.4: "1 red session -> OFF". Not two, not a confirmation — one."""
    px = _rising_then_falling()
    assert engine.gate_state(399, px, True) is True
    assert engine.gate_state(599, px, True) is False, "a single red session must turn it off"


def test_three_consecutive_greens_turn_it_back_on_and_two_do_not():
    """§3.4: "3rd consecutive green session -> ON". The asymmetry is the design — leaving late
    costs money once, returning early costs money at every dead-cat bounce."""
    # a decline, then a recovery that clears the average
    px = np.concatenate([np.linspace(300.0, 120.0, 400), np.linspace(120.0, 400.0, 300)])
    first_green = next(i for i in range(400, 700) if engine.gate_green(i, px))
    assert engine.gate_state(first_green, px, False) is False, "one green is not enough"
    assert engine.gate_state(first_green + 1, px, False) is False, "two greens are not enough"
    assert engine.gate_state(first_green + 2, px, False) is True, "the third green turns it on"


def test_a_gate_that_cannot_be_evaluated_reads_off():
    """§3.4: "If the gate cannot be evaluated on fresh data, it reads OFF." Not "carry yesterday"."""
    px = np.full(400, 100.0)
    px[380] = np.nan
    assert engine.gate_green(399, px) is False
    assert engine.gate_state(399, px, True) is False, "an unevaluable gate must not stay ON"
    assert engine.gate_state(399, px, None) is False, "and not knowing is not knowing"


# ---- §3.5 the book ----------------------------------------------------------------------------

RANKED = list(range(100))          # name j sits at rank j+1


def test_gate_off_sells_everything_and_buys_nothing():
    """§3.4: "the entire book sells at the next executable open... No buys of any kind while OFF." """
    sells, buys = engine.orders(RANKED, [3, 7, 11], gate_on=False)
    assert sorted(sells) == [3, 7, 11]
    assert buys == []


def test_a_holding_below_rank_twelve_queues():
    """§3.5: "a holding ranked below 12 queues that night". Rank 12 stays; rank 13 goes."""
    sells, _ = engine.orders(RANKED, [11, 12], gate_on=True)   # ranks 12 and 13
    assert 11 not in sells, "rank 12 is not BELOW 12"
    assert 12 in sells, "rank 13 is"


def test_a_holding_that_fell_out_of_the_ranking_entirely_queues():
    """It did not survive §3.2's screen, so it is below 12 by definition. Silence is not a hold."""
    sells, _ = engine.orders(RANKED, [500], gate_on=True)
    assert sells == [500]


def test_free_slots_fill_from_the_top_twelve_and_may_fill_several_at_once():
    """§3.5: "fill from the top 12 by rank. Multiple slots may fill in one session." """
    _, buys = engine.orders(RANKED, [], gate_on=True)
    assert buys == [0, 1, 2, 3, 4], "seeding fills all five from the top of the rank"
    _, buys = engine.orders(RANKED, [0, 1, 2], gate_on=True)
    assert buys == [3, 4], "two free slots take the next two eligible"


def test_displacement_needs_the_top_two_and_only_fires_once():
    """§3.5: "if the best unheld name in the top 2 ranks strictly better than the worst holding —
    swap. At most one displacement per session." """
    held = [1, 5, 6, 7, 8]                       # full book; ranks 2,6,7,8,9. Name 0 (rank 1) unheld
    sells, buys = engine.orders(RANKED, held, gate_on=True)
    assert sells == [8], "the worst holding leaves for the top-2 name"
    assert buys == [0], "and exactly one name comes in"


def test_a_name_outside_the_top_two_cannot_displace():
    """The band is the whole rule. Without it the book churns on every reshuffle."""
    held = [2, 3, 4, 5, 6]                       # ranks 3..7; the best unheld is name 0 at rank 1
    # make the top two held so the best unheld sits at rank 3
    held = [0, 1, 4, 5, 6]
    sells, buys = engine.orders(RANKED, held, gate_on=True)
    assert sells == [] and buys == [], "no top-2 candidate is free, so nothing moves"


# ---- §3.5 sizing and participation -------------------------------------------------------------

def test_position_size_is_nav_over_five_rounded_down():
    """§3.5: "Position size = engine NAV / 5". §3.7(4) rounds down and parks the residue."""
    assert engine.position_size(200_000.0, 137.0) == 291     # 40000/137 = 291.97
    assert engine.position_size(200_000.0, 40_000.0) == 1
    assert engine.position_size(200_000.0, 40_001.0) == 0, "an unaffordable name buys nothing"


def test_sizing_refuses_a_missing_price_rather_than_guessing():
    """Silent failure is the enemy: a size computed on a missing price is a plausible wrong number."""
    for bad in (None, 0.0, -1.0):
        with pytest.raises(ValueError):
            engine.position_size(200_000.0, bad)


def test_participation_caps_the_order_at_98_percent_of_addv():
    """§3.5's correctness check. It does not bind at $200k — which is exactly why it must exist
    before it does."""
    assert engine.participation_ok(100, 50.0, 1_000_000.0) is True
    assert engine.participation_ok(100, 50.0, 5_000.0) is False       # 5,000 > 0.98 * 5,000
    assert engine.participation_ok(100, 50.0, None) is False, "unknown liquidity is not permission"
    assert engine.participation_ok(100, 50.0, 0.0) is False
