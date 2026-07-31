"""Golden-value tests for every formula that moves money.

Each test names the section it pins. Where the plan states a worked example — four names at 0.85
correlation give 1.1 effective bets; an 8% stop on a 0.7% budget gives ~8.8% of NAV — the plan's
own number is the assertion. Fixtures are hand-built arrays: no database, no network, no vendor.
"""
import datetime as dt
import sys
import pathlib

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import signals as s                                                      # noqa: E402


# --------------------------------------------------------------------------- helpers

def flat_base(n=200, level=100.0, pivot_at=-40, pivot=110.0, noise=0.0):
    """A quiet series with one deliberate high `pivot_at` sessions from the end."""
    close = np.full(n, level) + (np.arange(n) % 3) * noise
    high, low = close * 1.01, close * 0.99
    high[pivot_at] = pivot
    return high, low, close


# --------------------------------------------------------------------------- §3.2 base detection

def test_base_pivot_must_be_at_least_25_sessions_old():
    """§3.2: the pivot is the highest high in the window 120 to 25 sessions ago. A spike inside
    the last 25 sessions is not a pivot — the pre-amendment scan took it and starved the sleeve."""
    high, low, close = flat_base(pivot_at=-40, pivot=110.0)
    high[-5] = 130.0                                # a fresher, higher high, too young to count
    out = s.base_scan(high, low, close)
    assert out["pivot"] == pytest.approx(110.0)
    assert out["base_len"] == 40


def test_valid_base_is_buy():
    out = s.base_scan(*flat_base(pivot_at=-40, pivot=110.0))
    assert out["state"] == "BUY" and out["valid"] and out["broken"] is None
    assert out["depth"] < 0.25


def test_close_above_pivot_breaks_the_base():
    """The breakout already happened — WAIT for the next base (§3.2, X3)."""
    high, low, close = flat_base(pivot_at=-40, pivot=110.0)
    close[-10] = 111.0
    high[-10] = 112.0
    out = s.base_scan(high, low, close)
    assert out["broken"] == "breakout" and out["state"] == "WAIT"


def test_high_beyond_the_grace_band_spends_the_pivot():
    """Tested and rejected: a high past pivot x 1.005 with no close above it (§3.2, X3)."""
    high, low, close = flat_base(pivot_at=-40, pivot=110.0)
    high[-8] = 110.0 * 1.02
    out = s.base_scan(high, low, close)
    assert out["broken"] == "spent" and out["state"] == "WAIT"


def test_shakeout_inside_the_grace_band_leaves_the_base_alive():
    """X4: a sub-noise poke is noise. The base survives and the same pivot may be re-entered."""
    high, low, close = flat_base(pivot_at=-40, pivot=110.0)
    high[-8] = 110.0 * 1.004
    out = s.base_scan(high, low, close)
    assert out["broken"] is None and out["valid"] and out["state"] == "BUY"


def test_base_deeper_than_25_percent_is_invalid():
    high, low, close = flat_base(pivot_at=-40, pivot=110.0)
    low[-20] = 70.0
    out = s.base_scan(high, low, close)
    assert out["depth"] > 0.25 and not out["valid"]


def test_contraction_low_is_the_last_ten_sessions():
    high, low, close = flat_base(pivot_at=-40, pivot=110.0)
    low[-3] = 95.5
    assert s.base_scan(high, low, close)["contraction_low"] == pytest.approx(95.5)


def test_short_history_scans_nothing():
    high, low, close = flat_base(n=60)
    assert s.base_scan(high, low, close)["state"] == "WAIT"


# --------------------------------------------------------------------------- §3.2 M2

def test_trend_template_passes_a_clean_uptrend():
    close = np.linspace(50, 120, 300)
    assert s.trend_template(close) is True


def test_trend_template_fails_below_the_50_day():
    close = np.concatenate([np.linspace(50, 120, 280), np.linspace(120, 95, 20)])
    assert s.trend_template(close) is False


def test_trend_template_needs_a_year_of_history():
    assert s.trend_template(np.linspace(50, 120, 100)) is False


# --------------------------------------------------------------------------- §3.2 MCN

def test_momentum_quality_rewards_a_steady_climb_over_a_noisy_one():
    steady = np.exp(np.linspace(0, 0.4, 200))
    noisy = steady * (1 + 0.08 * np.sin(np.arange(200)))
    assert s.momentum_quality(steady) > s.momentum_quality(noisy)


def test_setup_proximity_has_exactly_three_sub_scores():
    """S1-S5 cut pullback contraction. Four sub-scores means the module drifted back."""
    high, low, close = flat_base(n=300, noise=0.2)
    out = s.setup_proximity(high, low, close, np.full(300, 1e6))
    assert set(out) == {"atr_pct", "dryup", "near_high"}


def test_volume_dryup_prefers_the_quieter_name():
    high, low, close = flat_base(n=300, noise=0.2)
    quiet = np.concatenate([np.full(290, 1e6), np.full(10, 3e5)])
    loud = np.concatenate([np.full(290, 1e6), np.full(10, 3e6)])
    assert (s.setup_proximity(high, low, close, quiet)["dryup"]
            > s.setup_proximity(high, low, close, loud)["dryup"])


def test_mcn_is_the_mean_of_three_percentiles():
    assert s.mcn(90.0, 60.0, 30.0) == pytest.approx(60.0)


def test_pct_rank_is_nan_safe():
    out = s.pct_rank([1.0, np.nan, 3.0, 2.0])
    assert np.isnan(out[1]) and out[0] == 0.0 and out[2] == 100.0


# --------------------------------------------------------------------------- §3.2 confirmation

def test_confirmation_takes_any_of_the_first_three_sessions():
    assert s.breakout_confirmed([1.0e6, 1.1e6, 1.5e6], [1e6, 1e6, 1e6]) is True


def test_confirmation_ignores_a_fourth_session():
    assert s.breakout_confirmed([1e6, 1e6, 1e6, 9e6], [1e6] * 4) is False


def test_unknown_baseline_never_reads_as_confirmed():
    """The bug that turned a 29% confirmation rate into 2%: a NaN baseline silently confirmed."""
    assert s.breakout_confirmed([9e9], [float("nan")]) is False
    assert s.breakout_confirmed([9e9], [None]) is False


def test_pyramid_ships_two_adds_capped_at_the_ceiling():
    orders = s.pyramid_orders(100.0)
    assert [o["trigger"] for o in orders] == pytest.approx([102.0, 104.0])
    assert [o["limit"] for o in orders] == pytest.approx([105.0, 105.0])
    assert sum(o["fraction"] for o in orders) == pytest.approx(0.5)


# --------------------------------------------------------------------------- §3.2 stops

def test_initial_stop_is_never_wider_than_eight_percent():
    assert s.initial_stop(100.0, 85.0) == pytest.approx(92.0)


def test_initial_stop_prefers_the_contraction_low_when_it_is_tighter():
    assert s.initial_stop(100.0, 96.0) == pytest.approx(96.0)


def test_full_size_moves_the_stop_to_breakeven():
    out = s.ratchet_stop(closes=np.full(60, 101.0), avg_cost=100.0, current_stop=92.0,
                         pyramid_step=3)
    assert out["mode"] == "breakeven" and out["stop"] == pytest.approx(100.0)


def test_a_stalled_pyramid_keeps_its_initial_stop():
    out = s.ratchet_stop(closes=np.full(60, 101.0), avg_cost=100.0, current_stop=92.0,
                         pyramid_step=1)
    assert out["stop"] == pytest.approx(92.0) and out["mode"] == "initial"


def test_fifteen_percent_up_starts_the_ten_percent_trail():
    """A steady climb to +18%: past the trail threshold, but not 2 sigma above its own 50-day,
    so the 10% trail governs and euphoria stays out of it."""
    closes = np.linspace(100.0, 118.0, 60)
    out = s.ratchet_stop(closes=closes, avg_cost=100.0, current_stop=92.0, pyramid_step=3)
    assert out["euphoric"] is False
    assert out["mode"] == "trail10" and out["stop"] == pytest.approx(106.2)


def test_euphoria_outranks_the_ten_percent_trail():
    """Both conditions true — the tighter stop wins, because euphoria tightens (§3.2)."""
    closes = np.concatenate([np.full(59, 100.0), [120.0]])
    out = s.ratchet_stop(closes=closes, avg_cost=100.0, current_stop=92.0, pyramid_step=3)
    assert out["mode"] == "trail5" and out["stop"] == pytest.approx(114.0)


def test_euphoria_tightens_to_five_percent_and_only_on_two_sigma():
    closes = np.concatenate([np.full(49, 100.0), [130.0]])
    out = s.ratchet_stop(closes=closes, avg_cost=100.0, current_stop=92.0, pyramid_step=3)
    assert out["euphoric"] and out["mode"] == "trail5" and out["stop"] == pytest.approx(123.5)


def test_a_new_high_alone_is_not_euphoria():
    """The second euphoria trigger was deleted in S1-S5. A best-day-so-far must not tighten."""
    closes = np.concatenate([np.linspace(100, 108, 59), [108.5]])
    out = s.ratchet_stop(closes=closes, avg_cost=100.0, current_stop=92.0, pyramid_step=3)
    assert out["euphoric"] is False


def test_stops_never_ratchet_down():
    out = s.ratchet_stop(closes=np.full(60, 100.0), avg_cost=100.0, current_stop=99.0,
                         pyramid_step=0)
    assert out["stop"] == pytest.approx(99.0)


# --------------------------------------------------------------------------- §3.2 sizing

def test_eight_percent_stop_sizes_to_the_plans_worked_numbers():
    """§3.2: 'At an 8% stop these budgets yield ~8.8% and ~11.3% positions.'"""
    lo = s.momentum_size(nav=200_000, mcn_score=75, stop_distance=0.08)
    hi = s.momentum_size(nav=200_000, mcn_score=90, stop_distance=0.08)
    assert lo["size_pct"] == pytest.approx(0.0875, abs=0.001)
    assert hi["size_pct"] == pytest.approx(0.1125, abs=0.001)


def test_a_tight_stop_clips_at_the_band_ceiling():
    out = s.momentum_size(nav=200_000, mcn_score=90, stop_distance=0.03)
    assert out["size_pct"] == pytest.approx(0.12)


def test_start_low_may_size_below_the_band_floor():
    out = s.momentum_size(nav=200_000, mcn_score=75, stop_distance=0.08, start_low=True)
    assert out["size_pct"] == pytest.approx(0.0625, abs=0.001)


# --------------------------------------------------------------------------- §3.1 compounders

def test_ccn_averages_three_components():
    out = s.ccn(dict(engine=90.0, cash_conv=60.0, size=30.0))
    assert out["score"] == pytest.approx(60.0) and out["confidence"] == "full"


def test_ccn_renormalizes_around_one_missing_component():
    out = s.ccn(dict(engine=90.0, cash_conv=60.0, size=None))
    assert out["score"] == pytest.approx(75.0) and out["confidence"] == "2of3"


def test_size_alone_is_unscorable():
    """Without the floor a $4 microcap tops the bench on smallness (learnings #14)."""
    out = s.ccn(dict(engine=None, cash_conv=None, size=99.0))
    assert out["score"] is None and out["confidence"] == "unscorable"


def test_engine_agreement_is_a_flat_five_points():
    assert s.engine_agrees(0.20, 0.16) is True         # 4pp
    assert s.engine_agrees(0.20, 0.14) is False        # 6pp
    assert s.engine_agrees(0.40, 0.20) is False        # 20pp — the old relative rule allowed this
    assert s.engine_agrees(None, 0.10) is None


def test_effective_shares_come_from_the_vendor_cap():
    assert s.effective_shares(1_000_000_000, 50.0) == pytest.approx(20_000_000)
    assert s.effective_shares(None, 50.0) is None


def test_expected_return_at_the_hurdle_equals_the_floor():
    kw = dict(fcf_ttm=100e6, shares=50e6, growth=0.10, fair_multiple=20.0)
    px = s.hurdle_price(floor=0.15, **kw)
    assert s.expected_return(px, **kw) == pytest.approx(0.15, abs=1e-4)


def test_cheapness_earns_no_credit():
    """§3.1: the drag is never a credit — a stock below fair value gets zero bonus."""
    rich = s.expected_return(100.0, fcf_ttm=10e6, shares=1e6, growth=0.0, fair_multiple=5.0)
    cheap = s.expected_return(20.0, fcf_ttm=10e6, shares=1e6, growth=0.0, fair_multiple=50.0)
    assert rich < 0.10                          # 10x paying down to 5x is a real drag
    assert cheap == pytest.approx(10e6 / 20e6)  # 2x against a 50x fair — yield only, no bonus


def test_growth_moves_the_hurdle_up():
    kw = dict(fcf_ttm=100e6, shares=50e6, fair_multiple=20.0)
    assert s.hurdle_price(growth=0.20, **kw) > s.hurdle_price(growth=0.05, **kw)


def test_a_name_that_cannot_clear_the_floor_has_no_hurdle():
    assert s.hurdle_price(fcf_ttm=-5e6, shares=50e6, growth=0.1, fair_multiple=20.0) is None
    assert s.hurdle_price(fcf_ttm=100e6, shares=50e6, growth=0.1, fair_multiple=None) is None


def test_averaging_down_uses_fixed_tiers():
    """S1-S5 replaced the 25-50% range with fixed 50% / 100% tiers."""
    assert s.compounder_add(ccn_score=75, price=90.0, hurdle=100.0, adds_this_year=0)["fraction"] \
        == pytest.approx(0.5)
    assert s.compounder_add(ccn_score=75, price=80.0, hurdle=100.0, adds_this_year=0)["fraction"] \
        == pytest.approx(1.0)
    assert s.compounder_add(ccn_score=75, price=98.0, hurdle=100.0, adds_this_year=0) is None
    assert s.compounder_add(ccn_score=60, price=80.0, hurdle=100.0, adds_this_year=0) is None
    assert s.compounder_add(ccn_score=75, price=80.0, hurdle=100.0, adds_this_year=2)["fraction"] \
        is None


# --------------------------------------------------------------------------- §2.2 independence

def test_four_names_at_085_correlation_give_about_eleven_tenths_of_a_bet():
    """§2.2's own worked check: 'four equal names at 0.85 correlation -> 1.1 bets.'"""
    rng = np.random.default_rng(7)
    factor = rng.normal(size=4000)
    rho = 0.85
    rets = {f"N{i}": np.sqrt(rho) * factor + np.sqrt(1 - rho) * rng.normal(size=4000)
            for i in range(4)}
    bets = s.effective_bets({k: 0.25 for k in rets}, rets, window=4000)
    assert bets == pytest.approx(1.1, abs=0.05)


def test_four_independent_names_give_four_bets():
    rng = np.random.default_rng(11)
    rets = {f"N{i}": rng.normal(size=4000) for i in range(4)}
    bets = s.effective_bets({k: 0.25 for k in rets}, rets, window=4000)
    assert bets == pytest.approx(4.0, abs=0.2)


def test_a_name_with_too_little_history_is_dropped_not_guessed():
    rng = np.random.default_rng(3)
    rets = {"A": rng.normal(size=200), "B": rng.normal(size=10)}
    bets = s.effective_bets({"A": 0.5, "B": 0.5}, rets)
    assert bets == pytest.approx(1.0, abs=0.01)          # B is absent, A alone is one bet


# --------------------------------------------------------------------------- §3.3 calendars

def test_trading_days_skip_the_weekend():
    friday, monday = dt.date(2026, 7, 31), dt.date(2026, 8, 3)
    assert s.trading_days_between(friday, monday) == 1


def test_blackout_is_five_trading_days_including_the_report():
    today = dt.date(2026, 8, 3)                                   # Monday
    assert s.in_blackout(today, dt.date(2026, 8, 3)) is True      # reports today
    assert s.in_blackout(today, dt.date(2026, 8, 7)) is True      # Friday — the fifth session
    assert s.in_blackout(today, dt.date(2026, 8, 10)) is False    # next Monday — sixth
    assert s.in_blackout(today, dt.date(2026, 7, 31)) is False    # already reported: lifted
    assert s.in_blackout(today, None) is False


def test_calendar_day_arithmetic_would_have_been_wrong():
    """The old `days * 1.6 + 1` fudge put a report nine calendar days out inside the blackout."""
    today = dt.date(2026, 8, 3)
    nine_days_out = today + dt.timedelta(days=9)
    assert s.in_blackout(today, nine_days_out) is False


def test_holding_through_earnings_needs_the_cushion():
    assert s.holds_through_earnings(109.0, 100.0) is True
    assert s.holds_through_earnings(107.0, 100.0) is False
    assert s.holds_through_earnings(107.0, None) is None


# --------------------------------------------------------------------------- §3.2 M1

def _weekly_series(values, start=dt.date(2020, 1, 3)):
    return [start + dt.timedelta(days=7 * i) for i in range(len(values))], list(values)


def test_market_gate_turns_on_above_a_rising_average():
    dates, closes = _weekly_series(np.linspace(100, 200, 60))
    assert s.market_gate(dates, closes)["state"] == "ON"


def test_market_gate_turns_off_below_the_average():
    dates, closes = _weekly_series(np.concatenate([np.linspace(100, 200, 55), np.full(5, 120.0)]))
    assert s.market_gate(dates, closes, previous="ON")["state"] == "OFF"


def test_the_gate_latches_above_a_falling_average():
    """§3.2: 'price above a *falling* average changes nothing.'"""
    closes = np.concatenate([np.linspace(200, 100, 50), np.linspace(100, 130, 10)])
    dates, closes = _weekly_series(closes)
    out = s.market_gate(dates, closes, previous="OFF")
    assert out["spx"] > out["sma"] and out["sma"] < out["sma_lookback"]
    assert out["state"] == "OFF" and out["flipped"] is False


def test_the_gate_reports_its_flip():
    dates, closes = _weekly_series(np.linspace(100, 200, 60))
    assert s.market_gate(dates, closes, previous="OFF")["flipped"] is True


# --------------------------------------------------------------------------- §3.3 displacement

def test_displacement_needs_ten_points_over_the_weakest_incumbent():
    """§3.3: the challenger is measured against the WEAKEST incumbent, not the average."""
    incumbents = [("A", 72.0), ("B", 80.0), ("C", 65.0)]
    assert s.displaceable(75.0, incumbents)["ticker"] == "C"      # 75 >= 65 + 10
    assert s.displaceable(74.9, incumbents) is None               # one tenth short
    assert s.displaceable(90.0, incumbents)["margin"] == pytest.approx(25.0)


def test_displacement_ignores_unscored_incumbents():
    """An incumbent with no score cannot be displaced by a number — it is not 'weak', it is
    unmeasured, and treating null as zero would evict the wrong name."""
    assert s.displaceable(75.0, [("A", None), ("B", 70.0)]) is None
    assert s.displaceable(85.0, [("A", None), ("B", 70.0)])["ticker"] == "B"


def test_displacement_on_an_empty_sleeve_is_not_a_swap():
    assert s.displaceable(90.0, []) is None


# --------------------------------------------------------------------------- §2.3 size bounds

def test_a_wide_stop_can_size_below_the_four_percent_minimum_and_says_so():
    """§2.3's 4% minimum applies to intended full size, and the start-low rule does not waive it.
    The caller must be able to see that a position would be too small to matter."""
    out = s.momentum_size(nav=200_000, mcn_score=75, stop_distance=0.08, start_low=True,
                          start_low_budgets=(0.002, 0.003))
    assert out["size_pct"] == pytest.approx(0.025, abs=0.001)
    assert out["below_floor"] is True


def test_a_normal_size_is_not_flagged_below_floor():
    out = s.momentum_size(nav=200_000, mcn_score=75, stop_distance=0.08)
    assert out["below_floor"] is False


def test_a_zero_stop_distance_sizes_nothing_rather_than_infinity():
    assert s.momentum_size(nav=200_000, mcn_score=90, stop_distance=0) is None
    assert s.momentum_size(nav=200_000, mcn_score=90, stop_distance=-0.01) is None


# --------------------------------------------------------------------------- §3.2 entry mechanic

def test_the_first_position_is_half_of_full_size():
    """§3.2: 'First position 50%, pyramid to full.' The entry ticket must buy half, or the pyramid
    schedule is meaningless and the position is instantly at full size on an unconfirmed breakout."""
    first = s.entry_order(100.0, 96.0)
    assert first["fraction"] == pytest.approx(0.5)
    assert first["trigger"] == pytest.approx(100.0)
    assert first["limit"] == pytest.approx(102.0)          # §5.1 limit = pivot + 2%
    assert first["stop"] == pytest.approx(96.0)
    assert sum(o["fraction"] for o in s.pyramid_orders(100.0)) + first["fraction"] == \
        pytest.approx(1.0)                                  # 50 + 25 + 25 = full size


def test_the_entry_stop_is_never_wider_than_eight_percent_even_on_a_deep_base():
    first = s.entry_order(100.0, 70.0)
    assert first["stop"] == pytest.approx(92.0)
    assert first["stop_distance"] == pytest.approx(0.08)


# --------------------------------------------------------------------------- base-window bounds

def test_the_pivot_window_boundary_is_exactly_25_sessions():
    """§3.2's window is 120 to 25 sessions ago, inclusive. A high exactly 25 sessions back is a
    valid pivot; one 24 sessions back is too young and must be ignored."""
    high, low, close = flat_base(n=200, pivot_at=-25, pivot=110.0)
    at_25 = s.base_scan(high, low, close)
    assert at_25["pivot"] == pytest.approx(110.0) and at_25["base_len"] == 25

    high2, low2, close2 = flat_base(n=200, pivot_at=-24, pivot=110.0)
    at_24 = s.base_scan(high2, low2, close2)
    assert at_24["pivot"] != pytest.approx(110.0)


def test_the_pivot_window_reaches_back_120_sessions_and_no_further():
    high, low, close = flat_base(n=300, pivot_at=-120, pivot=110.0)
    assert s.base_scan(high, low, close)["pivot"] == pytest.approx(110.0)
    high2, low2, close2 = flat_base(n=300, pivot_at=-121, pivot=110.0)
    assert s.base_scan(high2, low2, close2)["pivot"] != pytest.approx(110.0)


def test_base_depth_boundary_is_exactly_25_percent():
    # the fixture's ordinary highs sit at close x 1.01, so the pivot must be above them to be the
    # window's highest high — 110 against a 101 backdrop
    high, low, close = flat_base(pivot_at=-40, pivot=110.0)
    low[-30] = 110.0 * 0.75                          # exactly 25% deep
    assert s.base_scan(high, low, close)["valid"] is True
    low[-30] = 110.0 * 0.75 - 0.1                    # a hair deeper
    assert s.base_scan(high, low, close)["valid"] is False


def test_grace_band_boundary_is_exactly_half_a_percent():
    high, low, close = flat_base(pivot_at=-40, pivot=110.0)
    high[-8] = 110.0 * 1.005                         # exactly at pivot x 1.005 — still noise
    assert s.base_scan(high, low, close)["broken"] is None
    high[-8] = 110.0 * 1.005 + 0.01                  # beyond the band — pivot spent
    assert s.base_scan(high, low, close)["broken"] == "spent"


# --------------------------------------------------------------------------- confirmation bounds

def test_confirmation_boundary_is_exactly_one_point_four_times():
    assert s.breakout_confirmed([1.4e6], [1e6]) is True
    assert s.breakout_confirmed([1.39e6], [1e6]) is False


def test_each_session_is_measured_against_its_own_baseline():
    """§3.2 (N-round): 'each session measured against its own trailing 50-day average.' A rising
    baseline must not be judged against the first day's."""
    assert s.breakout_confirmed([1.0e6, 1.5e6], [1e6, 2e6]) is False
    assert s.breakout_confirmed([1.0e6, 3.0e6], [1e6, 2e6]) is True


def test_the_band_is_a_ceiling_and_never_raises_a_size():
    """§3.2's budget is the law: the risk budget divided by the stop *is* the size. Raising it to
    the 8% band floor would put more NAV at risk than the budget allows."""
    out = s.momentum_size(nav=200_000, mcn_score=75, stop_distance=0.10, band=(0.08, 0.12))
    assert out["size_pct"] == pytest.approx(0.07)          # 0.7% / 10% — not lifted to 8%
    assert out["below_floor"] is False                     # 7% still clears the §2.3 minimum


def test_at_the_widest_legal_stop_the_size_still_clears_the_band_floor():
    """Which is why the floor can never bind in steady state: stops cap at 8%, so the smallest
    position the formula can produce is 0.7 / 8 = 8.75%."""
    out = s.momentum_size(nav=200_000, mcn_score=75, stop_distance=0.08)
    assert out["size_pct"] >= 0.08


def test_risk_is_the_budget_whatever_the_stop():
    """The invariant behind all of it: size x stop distance == the risk budget."""
    for stop in (0.03, 0.05, 0.08):
        out = s.momentum_size(nav=200_000, mcn_score=75, stop_distance=stop)
        if out["size_pct"] < 0.12:                          # unless the band ceiling clipped it
            assert out["size_pct"] * stop == pytest.approx(0.007, abs=1e-6)
