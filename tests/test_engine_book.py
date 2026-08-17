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


def test_the_latch_walked_forward_never_flips_on_a_single_green():
    """The latch derived over a whole series must obey the same asymmetry as one evaluated by hand:
    it can turn OFF in one session and can never turn ON in fewer than three.

    Derived rather than stored on purpose — §3.4 says an unevaluable gate reads OFF, and a stored
    flag that survives a failed ingest would say ON while the data behind it is missing.
    """
    rng = np.random.default_rng(4)
    px = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.02, 1500)))
    state = engine.gate_history(px)
    assert state.shape == px.shape
    assert not state[:engine.GATE_SMA - 1].any(), "before the window can be evaluated it is OFF"

    flips_on = [i for i in range(1, len(state)) if state[i] and not state[i - 1]]
    for i in flips_on:
        greens = sum(engine.gate_green(k, px) for k in range(i - engine.LATCH_IN + 1, i + 1))
        assert greens == engine.LATCH_IN, (
            f"session {i} turned ON without {engine.LATCH_IN} consecutive greens")

    flips_off = [i for i in range(1, len(state)) if not state[i] and state[i - 1]]
    for i in flips_off:
        assert not engine.gate_green(i, px), f"session {i} turned OFF on a green session"
    assert flips_on and flips_off, "the fixture must actually exercise both directions"


# ---- §3.7(3): at most one of a twin pair ------------------------------------------------------
#
# "Dual-listed / share-class twins inside the top 12: hold at most one of a pair; prefer the
# higher-ADDV line."
#
# This went unimplemented in the live engine until 2026-08-16 — `engine.orders` filled slots by
# rank with no pair test at all, so one company could take two of five slots at 1.25x the intended
# weight with every cap counting it twice. `verify_run.py` B7 found exactly that in run 589, seven
# times, which is what makes this a defect the register already knows about rather than a theory.

def test_a_twin_of_a_queued_buy_is_skipped():
    """The case the register was written for: both lines arrive together in the top 12."""
    ranked = [0, 1, 2, 3, 4, 5]
    twins = {(0, 1), (1, 0)}                       # ranks 1 and 2 are one company
    sells, buys = engine.orders(ranked, [], gate_on=True,
                                twin_of=lambda a, b: (a, b) in twins)
    assert buys == [0, 2, 3, 4, 5], "the better-ranked line fills; its twin is passed over"
    assert 1 not in buys


def test_a_twin_of_a_held_name_is_not_bought():
    """A pair can also arrive one at a time, with the second showing up while the first is held."""
    ranked = [0, 1, 2, 3, 4, 5]
    twins = {(1, 0), (0, 1)}
    sells, buys = engine.orders(ranked, [0], gate_on=True,
                                twin_of=lambda a, b: (a, b) in twins)
    assert 0 not in sells, "rank 1 is nowhere near §3.5's exit rank of 12"
    assert 1 not in buys, "and its twin must not join it"
    assert buys == [2, 3, 4, 5]


def test_the_skipped_twin_does_not_cost_the_slot():
    """§3.5 fills free slots "from the top 12 by rank" — skipping a twin means reaching further
    down the band, not leaving a slot empty. A book of four when five were available is a real cost
    and nothing in the plan asks for it."""
    ranked = list(range(12))
    twins = {(0, 1), (1, 0)}
    _, buys = engine.orders(ranked, [], gate_on=True, twin_of=lambda a, b: (a, b) in twins)
    assert len(buys) == engine.SLOTS == 5


def test_the_pair_test_never_reaches_past_the_fill_band():
    """A twin sitting at rank 40 is irrelevant: §3.5 only ever fills from the top 12, so the rule
    must not be able to veto a candidate on the strength of something the book cannot buy."""
    ranked = list(range(20))
    # every candidate "twins" a name far outside the band — which must change nothing
    _, buys = engine.orders(ranked, [], gate_on=True, twin_of=lambda a, b: {a, b} == {0, 19})
    assert buys == [0, 1, 2, 3, 4]


def test_without_the_relation_the_rule_is_inert():
    """`twin_of=None` is the pre-§3.7(3) behaviour, and the sim's own cell exposes the same switch
    as `dedupe_pairs`. Keeping them symmetrical is what lets the two be compared."""
    ranked = [0, 1, 2, 3, 4, 5]
    _, buys = engine.orders(ranked, [], gate_on=True, twin_of=None)
    assert buys == [0, 1, 2, 3, 4]
