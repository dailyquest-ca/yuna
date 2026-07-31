"""Unit tests for `yuna.policy` — the plan's rules, checked against the plan.

Every function in `policy` is pure, so every rule the plan states is exercisable
without a database, a vendor key or a clock. That is the whole reason the rules
were pulled out of the jobs: the defects this build has actually shipped were rule
defects wearing green, and a rule nobody can exercise is a rule nobody checks.

Assertions here are written against **docs/yuna_plan.md as of the 2026-07-31 16:37
stamp**, not against whatever the code happens to do. Where the code is stricter or
looser than the plan text, the test docstring names the deviation and the ledger
row (`yuna.rules.CLAUSES`) or open question that records it — a deviation that is
loud in three places is a deviation; a deviation nobody wrote down is a bug.

Two things this file deliberately does NOT test, because the plan deleted them on
2026-07-31 and the code correctly followed (changelog rounds S1-S5 and X4):

  * a largest-single-day-gain euphoria trigger — §3.2 now carries the euphoria rule
    on the 2 sigma test alone, and `test_euphoria_has_only_the_two_sigma_trigger`
    pins that the second trigger is gone rather than merely absent;
  * a 'forming' base state and the 15-session detection offset — §3.2's window is
    120 to 25 sessions back and every detected base is >= 25 sessions old *by
    construction*, which `test_pivot_window_edges` pins from both sides.
"""
from __future__ import annotations

import pytest

from yuna.policy import (
    BASE_MIN_AGE,
    MAX_STOP,
    ccn,
    classify_breakout,
    composite,
    effective_bets,
    engine_agrees,
    engine_growth,
    failed_breakout,
    holds_through_earnings,
    hurdle_price,
    in_blackout,
    initial_stop,
    is_euphoric,
    is_excluded_financial,
    momentum_size,
    pct_rank,
    pyramid_may_arm,
    ratchet_stop,
    scan_base,
    time_weighted_return,
    within_hurdle,
)

# The real §3.2 risk budgets, as config carries them. Kept here rather than imported
# so a config drift shows up as a failing test rather than as a test that moves with it.
BUDGETS = {"70": 0.007, "85": 0.009}


# ---------------------------------------------------------------------------
# §3.3 — composite scores and data confidence
# ---------------------------------------------------------------------------

def test_composite_renormalizes_rather_than_diluting() -> None:
    """§3.3: 'drop the component, renormalize remaining weights to 100.'

    The failure this pins is the easy one: summing three components and dividing by
    three regardless of how many are present, which drags every incomplete name
    toward zero and quietly makes missing data a penalty instead of a gap.
    """
    assert composite({"engine": 80.0, "cash_conv": 80.0, "size": None}) == (80.0, "2of3")
    assert composite({"engine": 90.0, "cash_conv": 60.0, "size": 30.0}) == (60.0, "full")


def test_composite_labels_full_and_partial_coverage() -> None:
    """§3.3: an incompletely-scored name is 'marked as scored on 2 of 3'.

    The label is load-bearing downstream — §3.3 caps a partial name at the bottom of
    its size band and demands manual sign-off — so it has to survive the scoring
    call, not be re-derived by whoever reads the row.
    """
    assert composite({"engine": 70.0, "cash_conv": 70.0, "size": 70.0})[1] == "full"
    assert composite({"engine": 70.0, "cash_conv": 70.0, "size": None})[1] == "2of3"
    assert composite({"engine": None, "cash_conv": 70.0, "size": 70.0})[1] == "2of3"


def test_composite_treats_zero_as_present() -> None:
    """§3.3: 'never assume a missing value' — and a measured zero is not missing.

    A 0.0 percentile is the worst engine in L0, which is information. Filtering on
    truthiness instead of `is not None` would read it as absent and hand the name a
    free renormalization onto its two better components.
    """
    score, conf = composite({"engine": 0.0, "cash_conv": None, "size": 90.0})
    assert (score, conf) == (45.0, "2of3")


def test_microcap_scoring_on_size_alone_is_refused() -> None:
    """The floor: two components, at least one of them a business measure.

    DEVIATION, recorded on ledger clause `3.3/data-confidence` and raised as D3 in
    docs/open-questions.md. §3.3 read literally ('drop the component, renormalize')
    lets a name score on *size* alone — and size is available to nearly everything
    and inverted, so the smallest name in the universe scores ~99. A $4 ethanol
    microcap topped the compounder bench exactly this way, on smallness and nothing
    else. The floor is stricter than the plan text and is awaiting Zak's ruling; it
    is tested here because shipping the literal reading is the known-bad outcome.
    """
    assert ccn(None, None, 99.0) == (None, "unscorable")          # the microcap
    assert ccn(None, None, None) == (None, "unscorable")
    # One business measure alone is still one component — two is the floor.
    assert ccn(88.0, None, None) == (None, "unscorable")
    # Size plus one business measure clears it; two business measures obviously do.
    assert ccn(88.0, None, 60.0) == (74.0, "2of3")
    assert ccn(None, 88.0, 60.0) == (74.0, "2of3")


def test_ccn_is_composite_over_the_three_named_components() -> None:
    """§3.1 CCN v1.0: engine, cash conversion, inverted log size — equal weight."""
    assert ccn(90.0, 60.0, 30.0) == composite(
        {"engine": 90.0, "cash_conv": 60.0, "size": 30.0})


# ---------------------------------------------------------------------------
# §3.0 — cross-sectional percentiles
# ---------------------------------------------------------------------------

def test_a_lone_observation_ranks_fifty() -> None:
    """§3.0: 'components are cross-sectional percentiles within L0.'

    One name is not the best of anything — a field of one has no cross-section, so
    the only defensible answer is the middle. Ranking it 100 would hand a size-cohort
    of one a perfect component score, which is how a thin cohort games the bench.
    """
    assert pct_rank([("a", 5.0)]) == {"a": 50.0}


def test_none_values_are_skipped_and_shift_nobody() -> None:
    """§3.3: 'never assume a missing value' — a missing name is not a low-ranked name.

    Read as a zero it would push everyone else up the field; read as a member with no
    value it would still consume a rank slot. Neither: it leaves the cross-section
    entirely, and the ranks of the names that *do* have values are unchanged.
    """
    without = pct_rank([("a", 1.0), ("b", 2.0), ("c", 3.0)])
    with_gap = pct_rank([("a", 1.0), ("b", 2.0), ("c", 3.0), ("d", None)])
    assert without == {"a": 0.0, "b": 50.0, "c": 100.0}
    assert with_gap == without and "d" not in with_gap


def test_pct_rank_ties_stay_ordered() -> None:
    """§3.0 states percentiles; it does not state tie handling, so this pins only
    what the plan does say — the ordering — and leaves the tie question open.

    (Reported, not resolved: two identical values currently receive different
    percentiles, split by input order. The plan has no line to test that against.)
    """
    r = pct_rank([("a", 1.0), ("b", 1.0), ("c", 2.0), ("d", 3.0)])
    assert set(r) == {"a", "b", "c", "d"}
    assert min(r.values()) == 0.0 and max(r.values()) == 100.0
    assert r["a"] <= r["c"] < r["d"] and r["b"] <= r["c"]      # ties never invert


@pytest.mark.parametrize("pairs", [[], [("a", None)], [("a", None), ("b", None)]])
def test_pct_rank_with_nothing_to_rank(pairs: list[tuple[str, float | None]]) -> None:
    """An empty cross-section produces no scores at all — not zeros, not 50s."""
    assert pct_rank(pairs) == {}


# ---------------------------------------------------------------------------
# §3.1 — engine reliability
# ---------------------------------------------------------------------------

def test_the_case_that_motivated_five_points() -> None:
    """§3.1: 'agreement (within 5 percentage points)' of observed 3-yr revenue growth.

    An engine of 16.3% against observed 7.1% is a 9.2pp gap. This is the real name
    that set the number, and it must not agree under any reading of the rule.
    """
    assert engine_agrees(0.163, 0.071) is False
    growth, agrees = engine_growth(0.163, 0.071)
    assert agrees is False
    assert growth == pytest.approx(0.071)


def test_the_tolerance_is_flat_five_points_not_a_relative_band() -> None:
    """§3.1 states the tolerance outright: five percentage points, flat.

    The superseded implementation used max(5pp, half the observed CAGR), which is
    looser on every fast grower — D4 in docs/open-questions.md, corrected to flat.
    A 30% engine against 22% observed is an 8pp gap: it fails flat 5pp, and it would
    have passed a half-CAGR band of 11pp. The gap must decide, not the growth rate.
    """
    assert engine_agrees(0.30, 0.22) is False
    assert engine_agrees(0.10, 0.06) is True                  # 4pp — inside
    assert engine_agrees(0.10, 0.05) is True                  # exactly 5pp — inside
    assert engine_agrees(0.10, 0.049) is False                # 5.1pp — outside


def test_no_revenue_cagr_means_no_agreement_verdict() -> None:
    """§3.1's cross-check is a comparison; with nothing to compare to there is no
    verdict. `None` is the third answer, and it is not 'agrees'."""
    assert engine_agrees(0.10, None) is None
    assert engine_agrees(None, 0.10) is None
    growth, agrees = engine_growth(0.10, None)
    assert agrees is None and growth == pytest.approx(0.10)


def test_divergence_caps_growth_down_and_never_up() -> None:
    """DEVIATION, raised as Q7: §3.1 routes a diverging engine down the data-confidence
    path — which governs the CCN — and is silent on what growth the *hurdle* should
    then use. The code's interim reading caps at observed revenue growth.

    What matters for the hurdle either way is the direction: the cap only ever
    reduces. An engine of 2% against observed 30% diverges, but honouring the
    observed 30% would underwrite a name at a growth rate its own cash flows do not
    produce — the cap is a ceiling, not a substitution.
    """
    assert engine_growth(0.02, 0.30)[0] == pytest.approx(0.02)   # capped down to itself
    assert engine_growth(0.163, 0.071)[0] == pytest.approx(0.071)  # capped down to observed


def test_divergence_never_yields_negative_growth() -> None:
    """The divergence cap floors at zero: with nothing trustworthy observed, no growth
    is claimed. Flooring a *disagreeing* engine cannot flatter the name, because the
    hurdle it produces is the one a zero-growth business deserves."""
    assert engine_growth(-0.10, -0.30)[0] == 0.0
    assert engine_growth(0.20, None, prior_agrees=False)[0] == 0.0


def test_an_agreeing_negative_engine_is_not_floored() -> None:
    """§3.1 caps engine growth at 25% and states no floor, so none is invented.

    A business whose engine is genuinely negative is shrinking and the expected
    return should say so; flooring at zero would *raise* its hurdle price, which
    flatters exactly the name that deserves it least.
    """
    growth, agrees = engine_growth(-0.05, -0.06)
    assert agrees is True and growth == pytest.approx(-0.05)


def test_the_twentyfive_percent_growth_cap_binds() -> None:
    """§3.1 entry hurdle: 'Engine growth capped at 25%.'"""
    growth, agrees = engine_growth(0.40, 0.42)
    assert agrees is True and growth == pytest.approx(0.25)


def test_a_stored_disagreement_survives_a_missing_input() -> None:
    """A row already judged untrustworthy must not be promoted back to full engine
    growth just because the revenue CAGR went missing this run — that is precisely
    the silent re-scoring §3.1's 'never silently score' forbids."""
    assert engine_growth(0.20, None, prior_agrees=False) == (0.0, False)
    growth, agrees = engine_growth(0.20, None, prior_agrees=True)
    assert agrees is True and growth == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# §3.1 — the hurdle
# ---------------------------------------------------------------------------

# A grower rich enough that the derating drag actually binds at the solved price —
# with a low growth rate the name solves below its fair multiple, the drag clamps to
# zero, and the test would exercise only half of §3.1's formula.
FCF, SHARES, GROWTH = 100_000_000.0, 50_000_000.0, 0.20


def _expected_return(price: float, fcf: float, shares: float,
                     growth: float, fair: float) -> float:
    """§3.1's expected-return decomposition, written out independently of the solver.

    Recomputing it here rather than importing the closure is the point: the test has
    to be able to disagree with the implementation, which it cannot do if it shares
    the arithmetic.
    """
    mcap = price * shares
    drag: float = max(0.0, 1.0 - (fair * fcf / mcap) ** 0.2)   # 5-yr slide, never a credit
    return fcf / mcap + growth - drag


def test_the_hurdle_price_sits_exactly_on_the_fifteen_percent_floor() -> None:
    """§3.1: 'Hurdle price = highest P where expected return >= 15%/yr.'

    Asserted by recomputing the expected return at the returned price rather than by
    hardcoding a number — a hardcoded hurdle passes forever, including after someone
    changes the drag exponent.
    """
    fair = 20.0
    price = hurdle_price(FCF, SHARES, GROWTH, fair)
    assert price is not None
    er = _expected_return(price, FCF, SHARES, GROWTH, fair)
    assert er == pytest.approx(0.15, abs=1e-6)
    assert er >= 0.15 - 1e-9                                    # 'expected return >= 15%'
    # and it is the *highest* such price: a hair above it, the floor is breached.
    assert _expected_return(price * 1.01, FCF, SHARES, GROWTH, fair) < 0.15
    assert price * SHARES / FCF > fair                          # rich enough that the drag bit


def test_a_richer_fair_multiple_gives_a_higher_hurdle() -> None:
    """§3.1: the drag is the annualized slide from the current multiple down to fair,
    so a higher fair multiple is a shorter slide, a smaller drag, and a price the
    name can carry while still clearing 15%. Monotone, with nothing else moving."""
    prices = [hurdle_price(FCF, SHARES, GROWTH, fair) for fair in (15.0, 20.0, 30.0)]
    assert all(p is not None for p in prices)
    assert prices[0] < prices[1] < prices[2]                   # type: ignore[operator]


def test_cheapness_earns_no_bonus() -> None:
    """§3.1: 'The drag is **never a credit** — cheapness earns no bonus. The margin of
    safety lives here.'

    The mirror of the monotonicity above, and the reason it is only weakly monotone: a
    slow grower solves *below* its fair multiple, so there is no slide left to pay for
    and the drag clamps at zero. Raising the fair multiple from 15x to 30x then buys
    the name exactly nothing — a rerating credit would move this price, and must not.
    """
    slow = 0.08
    cheap = hurdle_price(FCF, SHARES, slow, 15.0)
    richer_fair = hurdle_price(FCF, SHARES, slow, 30.0)
    assert cheap is not None
    assert cheap == richer_fair
    assert cheap * SHARES / FCF < 15.0                          # solved below fair — no drag


@pytest.mark.parametrize("fcf,shares,fair", [
    (None, SHARES, 20.0),      # no TTM free cash flow at all
    (0.0, SHARES, 20.0),       # zero FCF — no yield to underwrite
    (-5.0e7, SHARES, 20.0),    # negative FCF — C1 excludes it anyway; never a price
    (FCF, None, 20.0),         # no share count
    (FCF, 0.0, 20.0),
    (FCF, SHARES, None),       # no fair multiple — the drag is undefined
    (FCF, SHARES, 0.0),
])
def test_hurdle_declines_to_guess(fcf: float | None, shares: float | None,
                                  fair: float | None) -> None:
    """§3.3: 'never assume a missing value.' A hurdle is a price Zak may act on, so a
    missing or nonsensical input produces no number rather than a plausible one."""
    assert hurdle_price(fcf, shares, GROWTH, fair) is None


@pytest.mark.parametrize("price,expected", [
    (110.0, True),      # exactly 1.10 x hurdle — the band is inclusive
    (110.1, False),     # 1.101 x — outside
    (100.0, True),      # at the hurdle
    (70.0, True),       # 30% BELOW — a screaming buy, and inside the band
    (0.01, True),
])
def test_within_hurdle_is_a_ceiling_not_a_two_sided_band(price: float, expected: bool) -> None:
    """§3.0 L2 composition: 'every bench name within 10% of its hurdle (price <= 1.10 x
    hurdle)'. Zak's reading, 2026-07-31: the band sits above the hurdle only.

    A name 30% below its hurdle is not marginal, and the §3.1 eviction seatbelt that
    shares this test has no business dropping it.
    """
    assert within_hurdle(price, 100.0) is expected


@pytest.mark.parametrize("price,hurdle", [(None, 100.0), (100.0, None), (100.0, 0.0),
                                          (100.0, -5.0), (None, None)])
def test_within_hurdle_needs_both_numbers(price: float | None, hurdle: float | None) -> None:
    """No hurdle means no proximity claim — false, never a defaulted true, because a
    true here seats a name in L2 and protects it from eviction."""
    assert within_hurdle(price, hurdle) is False


# ---------------------------------------------------------------------------
# §3.1 — Gate C1's financial exclusion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("industry,excluded", [
    ("Banks - Regional", True),
    ("Banks - Diversified", True),
    ("Insurance - Life", True),
    ("Insurance - Property & Casualty", True),
    ("BANKS - REGIONAL", True),              # vendor casing drifts; the rule does not
    ("  banks - regional  ", True),          # nor does whitespace
    ("Financial Data & Stock Exchanges", False),   # the toll booths this sleeve wants
    ("Credit Services", False),
    ("Insurance Brokers", False),            # a fee business, not an underwriter
    ("Capital Markets", False),
    ("Banks", False),                        # the plan names the prefix with its dash
    ("Software - Application", False),
    (None, False),
    ("", False),
])
def test_only_banks_and_insurers_are_excluded(industry: str | None, excluded: bool) -> None:
    """§3.1 Gate C1: 'vendor industries named `Banks - ...` or `Insurance - ...`;
    Insurance Brokers, Credit Services, Capital Markets and the rest of Financial
    Services remain eligible.'

    By industry, not sector — the Financial Services *sector* also holds exchanges,
    ratings agencies and payment networks. The point-in-time backtest proved the cost
    of the other error: rebuilt from filings with no sector at all, a reinsurer and an
    asset manager took two of six slots. And 'a name with no vendor industry is not
    excludable by this test' — the gap is named on its C2 memo, not resolved here.
    """
    assert is_excluded_financial(industry) is excluded


# ---------------------------------------------------------------------------
# §3.2 — stops
# ---------------------------------------------------------------------------

def test_initial_stop_takes_the_higher_of_the_two() -> None:
    """§3.2 Stops: 'higher of the base's final-contraction low, or entry - 8%.'

    'Higher' is what makes 8% a ceiling on the *risk* rather than the stop itself: a
    tight base gives a tighter stop and therefore a bigger position, which is the
    entire point of sizing on risk (§2.3).
    """
    assert initial_stop(100.0, 95.0) == 95.0        # the contraction low binds — tighter
    assert initial_stop(100.0, 88.0) == pytest.approx(92.0)   # the 8% floor binds
    assert initial_stop(100.0, None) == pytest.approx(92.0)   # no base low — 8% it is


@pytest.mark.parametrize("low", [None, 0.0, 50.0, 88.0, 91.99, 92.0, 95.0, 99.9, 120.0])
def test_the_initial_stop_is_never_wider_than_eight_percent(low: float | None) -> None:
    """§3.2: '**Never wider than 8%.**' — the one invariant, over every base shape."""
    entry = 100.0
    assert initial_stop(entry, low) >= entry * (1.0 - MAX_STOP) - 1e-9


# ---------------------------------------------------------------------------
# §3.2 — the euphoria ratchet
# ---------------------------------------------------------------------------

EUPHORIC = [100.0] * 49 + [130.0]     # 50 closes: mean 100.6, sd 4.2, threshold 109.0
CHOPPY = [98.0, 102.0] * 25           # 50 closes: mean 100.0, sd 2.0, threshold 104.0


def test_euphoria_is_two_sd_above_the_own_fifty_day() -> None:
    """§3.2 Euphoria rule: 'when price closes > 2 standard deviations above its own
    50-day (std dev of closes, 50-day window)'.

    Strictly above, on exactly the last 50 closes — CHOPPY's last close is 102 against
    a 104 threshold and is a perfectly ordinary strong tape, not euphoria.
    """
    assert is_euphoric(EUPHORIC) is True
    assert is_euphoric(CHOPPY) is False


def test_the_window_is_exactly_the_last_fifty_closes() -> None:
    """§3.2 pins the window at 50. A spike 51 sessions back is outside it and must not
    inflate the standard deviation that today's close is judged against."""
    assert is_euphoric([1000.0, *EUPHORIC]) is True      # 51 closes; the 1000 is ignored


def test_a_flat_series_is_never_euphoric() -> None:
    """Zero dispersion has no 2-sd band. Without the guard, `close > mean + 0` makes
    every up-tick in a dead-flat tape euphoric and ratchets a live stop to -5%."""
    assert is_euphoric([100.0] * 50) is False


def test_under_fifty_closes_the_test_is_unavailable() -> None:
    """§3.2 measures against a 50-day window, so under 50 bars there is nothing to
    measure — and a position that young has not had time to get euphoric."""
    assert is_euphoric([100.0] * 48 + [130.0]) is False      # 49 closes
    assert is_euphoric([]) is False


def test_euphoria_has_only_the_two_sigma_trigger() -> None:
    """§3.2's euphoria rule is one trigger, not two.

    The largest-single-day-gain trigger was deleted from the plan on 2026-07-31
    (changelog S1-S5): it needed per-position running-max state, which meant the
    ratchet could not be recomputed from bars alone. A 40% single-day gain with no
    50-day window behind it therefore tightens nothing — pinned so that re-adding the
    deleted trigger turns this red rather than passing silently.
    """
    assert is_euphoric([100.0] * 20 + [140.0]) is False


# ---------------------------------------------------------------------------
# §3.2 — the ratchet
# ---------------------------------------------------------------------------

def test_euphoria_outranks_the_fifteen_percent_trail() -> None:
    """§3.2: euphoria tightens to 5% below the highest close, the +15% rule to 10%.

    EUPHORIC's last close is +30% on a 100 cost, so both rules qualify. These are
    protection rules and the tighter one always binds — 123.50, not 117.00.
    """
    stop, mode, high = ratchet_stop(EUPHORIC, 100.0, 1, 92.0, None)
    assert (mode, high) == ("trail5", 130.0)
    assert stop == pytest.approx(123.5)


def test_fifteen_percent_from_cost_trails_ten_below_the_highest_close() -> None:
    """§3.2 Ratchet: '+15% from average cost -> trail 10% below highest close since
    entry.' Measured on the close, against average cost, not against the entry fill."""
    stop, mode, high = ratchet_stop([100.0, 120.0], 100.0, 1, 92.0, None)
    assert (mode, high) == ("trail10", 120.0)
    assert stop == pytest.approx(108.0)


def test_full_size_moves_the_stop_to_breakeven() -> None:
    """§3.2 pyramid schedule: 'Full -> Stop moves to breakeven.' Step 3 is full size,
    and breakeven is average cost — the risk on the name goes to zero, which is what
    pays for the two adds."""
    stop, mode, high = ratchet_stop([100.0, 105.0], 100.0, 3, 92.0, None)
    assert (stop, mode, high) == (100.0, "breakeven", 105.0)


def test_no_rule_firing_leaves_the_stop_alone_but_still_advances_the_high() -> None:
    """§3.2 trails run from the 'highest close since entry', so the high has to keep
    climbing on nights when no ratchet fires — otherwise the first night a trail does
    fire, it measures from a stale high and sits too low."""
    stop, mode, high = ratchet_stop([100.0, 105.0], 100.0, 2, 92.0, 100.0)
    assert (stop, mode, high) == (92.0, "initial", 105.0)


def test_stops_ratchet_up_never_down() -> None:
    """§3.2: 'stops ratchet up, never down.'

    This clamp is the only reason a trail can be safely recomputed from scratch every
    night: the +15% trail here computes 108.00 against a stop already at 115.00, and a
    system that recomputes without clamping would hand 7 points of protection back.
    """
    stop, mode, high = ratchet_stop([100.0, 120.0], 100.0, 1, 115.0, None)
    assert (stop, mode, high) == (115.0, "trail10", 120.0)


def test_a_full_size_position_with_no_cost_basis_is_labeled_not_guessed() -> None:
    """Breakeven is average cost, and §3.3's 'never assume a missing value' rules out
    inventing one. The branch reports itself so the caller can amber on it — a step-3
    position with no cost basis is a data defect that must be visible."""
    stop, mode, high = ratchet_stop([100.0, 105.0], None, 3, 92.0, None)
    assert (stop, mode, high) == (92.0, "no-cost-basis", 105.0)


def test_ratchet_with_no_closes_touches_nothing() -> None:
    """No bars tonight means no information, so the live stop stands exactly as
    placed — the broker GTC (§4.6) is protection that must not be moved on silence."""
    assert ratchet_stop([], 100.0, 3, 92.0, 130.0) == (92.0, "initial", 130.0)
    assert ratchet_stop([], None, 3, None, None) == (None, "initial", 0.0)


# ---------------------------------------------------------------------------
# §3.2 — momentum sizing
# ---------------------------------------------------------------------------

def test_the_two_risk_budget_tiers() -> None:
    """§3.2 Sizing: 'risk budget — 0.7% of NAV at MCN 70-84, 0.9% at 85+ ... size =
    budget / stop.'

    The plan does the arithmetic itself: 'at an 8% stop these budgets yield ~8.8% and
    ~11.3% positions — inside the band, so the formula genuinely governs.' 85 is the
    boundary and belongs to the upper tier (§3.3 thresholds: '>= 85').
    """
    assert momentum_size(100.0, 92.0, 75.0, BUDGETS)[0] == pytest.approx(0.0875)
    assert momentum_size(100.0, 92.0, 84.9, BUDGETS)[0] == pytest.approx(0.0875)
    assert momentum_size(100.0, 92.0, 85.0, BUDGETS)[0] == pytest.approx(0.1125)
    assert momentum_size(100.0, 92.0, 90.0, BUDGETS)[0] == pytest.approx(0.1125)


def test_a_stop_wider_than_eight_percent_is_moved_not_sized_around() -> None:
    """§3.2: 'Never wider than 8%.' The 8% ceiling is on the stop *width*, so a base
    whose contraction low sits 15% away is simply not honoured — the position sizes
    as though the stop were at 8%, and the risk budget is spent as budgeted.

    Sizing down against the wider distance instead would produce a 4.7% position, half
    the intended risk, and quietly turn the ceiling into a de-facto position penalty.
    """
    weight, dist, budget = momentum_size(100.0, 85.0, 75.0, BUDGETS)
    assert dist == pytest.approx(MAX_STOP)
    assert weight == pytest.approx(0.0875)
    assert budget == pytest.approx(0.007)


def test_a_tighter_stop_buys_a_bigger_position_until_the_band_caps_it() -> None:
    """§3.2: 'Wide stop -> smaller position; tight stop -> bigger ... capped by the
    Section 2 bands' — momentum's entry band tops out at 12% (§2.1).

    'Genuinely tight stops still clip at the 12% ceiling', which the 3% stop does.
    """
    wide = momentum_size(100.0, 92.0, 75.0, BUDGETS)[0]     # 8% stop -> 8.75%
    tight = momentum_size(100.0, 94.0, 75.0, BUDGETS)[0]    # 6% stop -> 11.67%
    assert tight > wide
    capped, dist, _ = momentum_size(100.0, 97.0, 75.0, BUDGETS)   # 3% stop -> 23.3%
    assert dist == pytest.approx(0.03)
    assert capped == pytest.approx(0.12)


# ---------------------------------------------------------------------------
# §2.2 — independence
# ---------------------------------------------------------------------------

def test_the_plans_own_worked_check() -> None:
    """§2.2: 'Worked check: four equal names at 0.85 correlation -> 1.1 bets.'

    The plan states the answer to one decimal place, so that is what is asserted —
    this is the one number in the section that can be checked without judgment.
    """
    names = ["a", "b", "c", "d"]
    weights = {n: 0.10 for n in names}
    rho = {(x, y): 0.85 for x in names for y in names if x != y}
    bets = effective_bets(weights, rho)
    assert bets is not None
    assert round(bets, 1) == 1.1


def test_one_name_is_one_bet() -> None:
    """The degenerate case of 1 / sum(wi wj rho_ij): a single name normalizes to
    weight 1 against its own correlation of 1."""
    assert effective_bets({"a": 0.10}, {}) == pytest.approx(1.0)


def test_a_missing_pair_is_read_as_perfectly_correlated() -> None:
    """Unknown correlation must make the book look *more* concentrated, never less —
    otherwise a name with too little history (§2.2 wants 126 sessions, minimum 60)
    silently improves the independence count that R1 prints on every draft ticket.
    """
    assert effective_bets({"a": 0.1, "b": 0.1}, {}) == pytest.approx(1.0)
    # ... and a known-independent pair is genuinely two bets, so the default is a
    # default and not a hardcoded answer.
    assert effective_bets({"a": 0.1, "b": 0.1}, {("a", "b"): 0.0}) == pytest.approx(2.0)
    # symmetric lookup: rho is a pair, not an ordered pair
    assert effective_bets({"a": 0.1, "b": 0.1}, {("b", "a"): 0.0}) == pytest.approx(2.0)


def test_an_empty_book_has_no_bet_count() -> None:
    """No positions is not 'zero independent bets' — it is a number that does not
    exist, and R1 prints nothing rather than a warning about concentration."""
    assert effective_bets({}, {}) is None
    assert effective_bets({"a": 0.0}, {}) is None


# ---------------------------------------------------------------------------
# §5.6 / §2.0 — performance
# ---------------------------------------------------------------------------

def test_a_deposit_creates_no_return() -> None:
    """The whole point of time-weighting: the 30% bar measures the machine, not Zak's
    paycheque (§1 'Thirty percent a year is the target'; §2.0 NAV is the scorecard).

    NAV rises from 100k to 105k purely because 5k arrived. Nothing was earned, so the
    return is exactly zero — a money-weighted read would print +5%.
    """
    assert time_weighted_return([100_000.0, 105_000.0], [0.0, 5_000.0]) == pytest.approx(0.0)


def test_a_real_gain_plus_a_deposit_reports_only_the_gain() -> None:
    """Two sub-periods, chain-linked: +10% earned, then 50k deposited, then +10%
    earned again. The honest answer is 1.10 x 1.10 - 1 = 21%.

    The naive NAV-to-NAV read is (176k - 100k) / 100k = 76%, which is the deposit
    wearing a performance badge — and the reason Zak ruled time-weighted return.
    """
    navs = [100_000.0, 110_000.0, 176_000.0]
    flows = [0.0, 0.0, 50_000.0]
    twr = time_weighted_return(navs, flows)
    assert twr is not None
    assert twr == pytest.approx(0.21)
    assert twr < (navs[-1] - navs[0]) / navs[0]


def test_a_withdrawal_creates_no_loss() -> None:
    """The mirror image, and the one that matters when Zak takes money out: NAV falls
    from 100k to 90k because 10k left. Nothing was lost, so the return is zero."""
    assert time_weighted_return([100_000.0, 90_000.0], [0.0, -10_000.0]) == pytest.approx(0.0)
    # a withdrawal on top of a real loss still reports only the loss
    assert time_weighted_return([100_000.0, 81_000.0], [0.0, -10_000.0]) == pytest.approx(-0.10)


@pytest.mark.parametrize("navs,flows", [([], []), ([100_000.0], [0.0])])
def test_fewer_than_two_observations_has_no_return(navs: list[float],
                                                   flows: list[float]) -> None:
    """A return is a change between two observations. One NAV is a balance, not a
    performance number, and §4.7's freshness discipline would rather print nothing."""
    assert time_weighted_return(navs, flows) is None


# ---------------------------------------------------------------------------
# §3.3 — blackout and the earnings cushion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sessions,blacked", [
    (0, True),      # the report session itself — glossary: 'the report session included'
    (1, True),
    (5, True),      # 'within 5 trading days' — the far edge is inside
    (6, False),     # one session clear of the window
    (-1, False),    # the report already printed; the window lifts the next session
    (-30, False),
    (None, False),  # no scheduled report on the calendar
])
def test_blackout_window_bounds(sessions: int | None, blacked: bool) -> None:
    """§3.3: 'no new entries and no adds within 5 trading days of a scheduled report.
    Both sleeves ... The blackout lifts the first session after the report session.'

    Trading days from the session calendar, never calendar days scaled by a fudge
    factor — two parts of the same nightly once disagreed about whether a name was
    enterable because one approximated and the other counted.

    (Q3 in docs/open-questions.md asks Zak to confirm the window is six sessions —
    five before plus the report — rather than five inclusive. The plain text of §3.3
    is what is asserted here; the ambiguity is reported, not resolved.)
    """
    assert in_blackout(sessions) is blacked


def test_a_breakout_confirming_inside_a_blackout_arms_nothing() -> None:
    """§3.3: 'no new entries and no adds' is unconditional inside the window, and §3.2
    pyramid adds are adds. Confirmation and blackout are independent questions and the
    blackout wins — the name can confirm on volume, unlock its pyramid in principle,
    and still arm nothing until the window lifts."""
    assert pyramid_may_arm(True, 3) is False       # confirmed, but inside
    assert pyramid_may_arm(True, 5) is False       # the far edge is still inside
    assert pyramid_may_arm(True, 6) is True        # clear of the window
    assert pyramid_may_arm(True, None) is True     # no scheduled report
    assert pyramid_may_arm(False, 30) is False     # unconfirmed arms nothing anyway


def test_the_earnings_cushion_is_one_full_stop_width() -> None:
    """§3.3: 'a position holds through the print only with a cushion — last close >=
    1.08 x average cost (one full stop-width of profit absorbs the gap). Below that
    cushion -> exit ticket that evening.'

    The boundary is written as `1.08 * avg_cost` rather than a decimal literal on
    purpose: the cushion is inclusive, and hardcoding 108.0 against 1.08 * 100.0 tests
    binary float representation instead of the rule.
    """
    avg_cost = 100.0
    assert holds_through_earnings(1.08 * avg_cost, avg_cost) is True      # exactly the cushion
    assert holds_through_earnings(1.09 * avg_cost, avg_cost) is True
    assert holds_through_earnings(1.079 * avg_cost, avg_cost) is False    # a hair short
    assert holds_through_earnings(avg_cost, avg_cost) is False            # flat — no cushion
    assert holds_through_earnings(0.0, avg_cost) is False
    assert holds_through_earnings(200.0, 0.0) is False                    # no cost basis, no hold


# ---------------------------------------------------------------------------
# §3.2 — base detection
# ---------------------------------------------------------------------------

N = 60                 # sessions in the synthetic tape
PIVOT_I = 10           # where the base's defining high sits
PIVOT = 110.0


def _tape(n: int = N) -> tuple[list[float], list[float], list[float]]:
    """A featureless sideways tape — the canvas each base test paints one feature on.

    Deliberately boring: every assertion below should be traceable to the single bar
    the test moved, not to noise the fixture happened to contain.
    """
    return [101.0] * n, [99.0] * n, [100.0] * n


def _based() -> tuple[list[float], list[float], list[float]]:
    """The tape with a clean, valid base: a lone high at session 10, unbroken since."""
    highs, lows, closes = _tape()
    highs[PIVOT_I], closes[PIVOT_I] = PIVOT, 108.0
    return highs, lows, closes


def test_a_clean_unbroken_shallow_base_is_valid() -> None:
    """§3.2: 'the pivot is the highest high in the window 120 to 25 sessions ago ... An
    unbroken base is valid when depth (pivot to lowest low) <= 25%.'"""
    out = scan_base(*_based())
    assert out["state"] == "valid"
    assert out["pivot"] == PIVOT
    assert out["age"] == N - 1 - PIVOT_I                      # 49 sessions old
    assert out["depth"] == pytest.approx((PIVOT - 99.0) / PIVOT)
    assert out["contraction_low"] == 99.0


@pytest.mark.parametrize("spike_at,pivot,age", [
    (34, 200.0, 25),      # 25 sessions back — the oldest edge of the excluded window, IN
    (35, PIVOT, 49),      # 24 sessions back — excluded, so the old 110 stays the pivot
])
def test_pivot_window_edges(spike_at: int, pivot: float, age: int) -> None:
    """§3.2: 'every detected base is >= 25 sessions by construction' — the window ends
    25 sessions back, so a younger high can never become a pivot and there is no age
    test to apply afterwards.

    The 2026-07-31 simplification pass (changelog S1-S5) deleted the forming state,
    the 15-session offset and the age partition on exactly this ground: validity was
    being checked twice, once by the window and once by an invented threshold. A
    24-session-old high of 200 is invisible to the scan; a 25-session-old one is the
    pivot. Nothing this function returns is ever 'forming'.
    """
    highs, lows, closes = _based()
    highs[spike_at] = 200.0
    out = scan_base(highs, lows, closes)
    assert out["pivot"] == pivot
    assert out["age"] == age
    assert out["age"] >= BASE_MIN_AGE
    assert out["state"] in {"none", "valid", "broken"}         # no 'forming' state exists


def test_a_later_close_above_the_pivot_breaks_the_base() -> None:
    """§3.2: a base is broken by 'any later session **closing** above the pivot — the
    breakout happened'. That base is spent; the next one has to form."""
    highs, lows, closes = _based()
    highs[40], closes[40] = 110.3, 110.2           # high inside the grace, close above
    out = scan_base(highs, lows, closes)
    assert out["state"] == "broken"
    assert "close" in str(out["why"])


def test_a_later_high_inside_the_grace_does_not_break_the_base() -> None:
    """§3.2: 'Highs within the 0.5% grace are noise' — a high *above the pivot* that
    closes back below leaves the base standing.

    This is the X4 ruling with its consequence accepted with eyes open: a sub-noise
    shakeout exits through the unconfirmed-breakout hair-trigger while the base itself
    survives, which is the classic same-pivot re-entry.
    """
    highs, lows, closes = _based()
    highs[40] = PIVOT * 1.004                      # above the pivot, inside the 0.5% band
    out = scan_base(highs, lows, closes)
    assert out["state"] == "valid"
    assert out["pivot"] == PIVOT


def test_a_later_high_beyond_the_grace_spends_the_pivot() -> None:
    """§3.2: 'any later session's high exceeding pivot x 1.005 without such a close —
    the pivot was tested and rejected, spent.'

    This is what stops the exit-and-instantly-re-arm churn loop: any poke beyond the
    noise band forces a new base rather than re-arming the same trigger.
    """
    highs, lows, closes = _based()
    highs[40] = PIVOT * 1.006
    out = scan_base(highs, lows, closes)
    assert out["state"] == "broken"
    assert "grace" in str(out["why"]) or "spent" in str(out["why"])


@pytest.mark.parametrize("trough,state", [
    (82.5, "valid"),      # exactly 25% deep — '<= 25%' is inclusive
    (82.4, "none"),       # a hair past 25%
    (80.0, "none"),       # 27.3% — a correction, not a base
])
def test_depth_over_twentyfive_percent_is_not_a_base(trough: float, state: str) -> None:
    """§3.2 M3: a base is '<= 25% deep'. Depth runs pivot to lowest low.

    Note what a failure returns: state 'none', not 'broken'. The pivot survives and is
    still reported — the base is simply not tradeable at this depth, and a shallower
    contraction can still resolve it.
    """
    highs, lows, closes = _based()
    lows[20] = trough
    out = scan_base(highs, lows, closes)
    assert out["state"] == state
    assert out["depth"] == pytest.approx((PIVOT - trough) / PIVOT)


def test_the_contraction_low_is_the_lowest_low_of_the_last_ten_sessions() -> None:
    """§3.2: 'Final-contraction low = the lowest low of the last 10 sessions' — the
    natural stop shelf under a breakout, and the tighter half of the §3.2 initial stop.

    Explicitly NOT the base's own trough: the 90.00 at session 30 is deeper and older,
    and using it would hand back the tight stop the contraction just earned.
    """
    highs, lows, closes = _based()
    lows[30], lows[55] = 90.0, 95.5
    out = scan_base(highs, lows, closes)
    assert out["state"] == "valid"
    assert out["contraction_low"] == 95.5
    assert out["depth"] == pytest.approx((PIVOT - 90.0) / PIVOT)   # depth still sees the trough


def test_too_little_history_yields_no_base_and_says_so() -> None:
    """A base is >= 25 sessions by construction, so a name with 25 bars cannot have
    one. §4.7's discipline: the reason is carried, not swallowed."""
    out = scan_base(*_tape(BASE_MIN_AGE))
    assert out["state"] == "none"
    assert out["pivot"] is None
    assert out["why"] == "not enough history"


def test_ragged_input_is_refused_rather_than_zipped() -> None:
    """Mismatched OHLC lengths mean the bars are wrong, and a scan that silently used
    the shortest would price a pivot against the wrong session."""
    highs, lows, closes = _based()
    assert scan_base(highs[:-1], lows, closes)["state"] == "none"
    assert scan_base(highs, lows[:-3], closes)["why"] == "not enough history"


# ---------------------------------------------------------------------------
# §3.2 — breakout confirmation
# ---------------------------------------------------------------------------

BASE_VOL: list[float | None] = [1_000_000.0, 1_000_000.0, 1_000_000.0]


def test_volume_on_the_breakout_day_confirms() -> None:
    """§3.2: 'session volume >= 1.4x the 50-day average -> confirmed, and pyramid steps
    2-3 arm per schedule.' 1.4x exactly is confirmation — the plan's '>=' is inclusive."""
    out = classify_breakout([1_400_000.0, 900_000.0, 900_000.0], BASE_VOL)
    assert out["confirmed"] is True
    assert out["on_breakout_day"] is True
    assert out["late"] is False
    assert out["unknown_baseline"] is False
    assert out["pyramid_ceiling"] == 1.0            # full size unlocked


@pytest.mark.parametrize("session", [1, 2])
def test_late_confirmation_on_session_two_or_three(session: int) -> None:
    """§3.2: 'If any of the first three sessions (breakout day included) prints >= 1.4x
    — each session measured against its own trailing 50-day average — the name confirms
    late and the pyramid unlocks.'

    Measuring each session against its own baseline is what makes late confirmation
    meaningful rather than a rerun of the same test.
    """
    vols = [900_000.0, 900_000.0, 900_000.0]
    vols[session] = 1_500_000.0
    out = classify_breakout(vols, BASE_VOL)
    assert out["confirmed"] is True
    assert out["late"] is True
    assert out["on_breakout_day"] is False
    assert out["pyramid_ceiling"] == 1.0


def test_only_the_first_three_sessions_can_confirm() -> None:
    """§3.2 gives 'three sessions to confirm late'. A fourth-session volume surge is a
    different event — the name that never confirmed 'stays at half size under normal
    stops, and the stalled-pyramid rule resolves it.'"""
    out = classify_breakout([9.0e5, 9.0e5, 9.0e5, 5.0e6], [*BASE_VOL, 1_000_000.0])
    assert out["confirmed"] is False
    assert len(out["ratios"]) == 3                  # type: ignore[arg-type]
    assert out["pyramid_ceiling"] == 0.5            # 'the pyramid freezes at step 1 (50%)'


def test_a_genuinely_low_volume_breakout_is_unconfirmed() -> None:
    """The control case for the test below: every baseline known, every ratio under
    1.4x. This is a *tested and failed* breakout, and it is the only shape that should
    ever read that way."""
    out = classify_breakout([9.0e5, 1.0e6, 1.1e6], BASE_VOL)
    assert out["confirmed"] is False
    assert out["unknown_baseline"] is False
    assert out["pyramid_ceiling"] == 0.5


@pytest.mark.parametrize("baselines", [
    [None, None, None],                 # no 50-day average at all
    [0.0, 0.0, 0.0],                    # a zero denominator is not a small denominator
    [None, 1_000_000.0, 1_000_000.0],   # partially unknown
])
def test_an_unknown_baseline_is_carried_as_unknown(baselines: list[float | None]) -> None:
    """§3.2 measures volume 'against its own trailing 50-day average'. A missing
    denominator means the test could not be run — it does not mean the test failed.

    This is the exact defect that made a simulation report 2% confirmation where the
    raw bars showed 29.2%: NaN baselines were read as 'not confirmed', so a data gap
    scored against every position that had one. The unknown has to reach the caller.
    """
    out = classify_breakout([5_000_000.0, 900_000.0, 900_000.0], baselines)
    assert out["unknown_baseline"] is True
    assert out["confirmed"] is False          # an unknown alone never sets confirmed
    assert out["on_breakout_day"] is False
    assert out["late"] is False


def test_unknown_and_failed_are_distinguishable() -> None:
    """Both leave `confirmed` False, and that is exactly why the flag exists — the
    caller decides, rather than the scan silently scoring against the position."""
    failed = classify_breakout([9.0e5, 9.0e5, 9.0e5], BASE_VOL)
    unknown = classify_breakout([9.0e5, 9.0e5, 9.0e5], [None, None, None])
    assert failed["confirmed"] == unknown["confirmed"] is False
    assert failed["unknown_baseline"] is False and unknown["unknown_baseline"] is True


def test_a_known_confirmation_beside_an_unknown_still_confirms() -> None:
    """One session that genuinely printed 1.4x confirms the breakout; the neighbouring
    gap is reported alongside rather than cancelling it."""
    out = classify_breakout([1_500_000.0, 9.0e5, 9.0e5], [1_000_000.0, None, None])
    assert out["confirmed"] is True
    assert out["on_breakout_day"] is True
    assert out["unknown_baseline"] is True


# ---------------------------------------------------------------------------
# §3.2 — the failed breakout
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("confirmed,close,fires", [
    (False, 99.0, True),     # unconfirmed and back below the pivot — exit next morning
    (False, 100.0, False),   # at the pivot is not below it
    (False, 101.0, False),
    (True, 99.0, False),     # confirmed: ordinary stops own this name now
    (True, 50.0, False),
])
def test_the_hair_trigger_only_applies_while_unconfirmed(confirmed: bool, close: float,
                                                         fires: bool) -> None:
    """§3.2: 'While unconfirmed, one hair-trigger applies — a close back below the
    pivot -> exit next morning; that is a failed breakout by the only judge that
    matters.'

    Not a volume exit: 'volume decides how much money rides, price decides whether you
    stay.' A confirmed name falls back to ordinary stops and this never fires — which
    is what keeps a confirmed breakout from being stopped out by its first pullback.
    """
    assert failed_breakout(confirmed, close, 100.0) is fires
