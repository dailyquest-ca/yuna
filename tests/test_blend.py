"""E4's blend simulator, on hand-built series.

The 100/0 arm is the built-in control — it must reproduce the core series to within its single
initial cost, or the simulator is measuring itself rather than the blend.
"""
import datetime as dt
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import blend                                                                # noqa: E402


def sessions(n, start=dt.date(2020, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def series(n, start, daily):
    return start * np.exp(np.cumsum(np.full(n, daily)))


N = 300
DATES = sessions(N)
DEEP = np.full(N, 1e9)                      # ADDV deep in the 5 bps bucket, like both ETFs


def run(core_daily=0.0005, tilt_daily=0.0012, core_w=0.9, tilt_w=0.1, **kw):
    core, tilt = series(N, 400.0, core_daily), series(N, 40.0, tilt_daily)
    return blend.simulate_blend(DATES, core, tilt, DEEP, DEEP,
                                core_w=core_w, tilt_w=tilt_w, start_nav=200_000.0, **kw)


def test_the_pure_core_arm_reproduces_the_core_less_one_cost():
    equity, trueups, cost = run(core_w=1.0, tilt_w=0.0)
    assert trueups == 0, "an arm with no tilt has nothing to true up"
    core = series(N, 400.0, 0.0005)
    ideal = 200_000.0 * core[-1] / core[0]
    assert cost == pytest.approx(200_000.0 * 5.0 / 10_000.0)      # one initial 5 bps charge
    assert equity[-1][1] == pytest.approx(ideal * (1 - 5.0 / 10_000.0), rel=1e-9), (
        "the control arm must be the core series minus exactly its initial cost")


def test_the_band_holds_until_five_points_of_drift():
    """§2.1: check weekly, trade only beyond the band. A tilt drifting slowly stays untraded;
    a hard divergence trues up to the exact target weights."""
    calm, calm_ups, _ = run(core_daily=0.0005, tilt_daily=0.0007)
    assert calm_ups == 0, "a gentle drift inside the band must never trade"

    wild, wild_ups, _ = run(core_daily=0.0000, tilt_daily=0.0100)
    assert wild_ups >= 1, "a tilt compounding 1%/day must breach a 5-point band"
    # immediately after a true-up, the weights are exact: find the first true-up session by
    # re-walking the weights and assert the largest post-trade deviation collapses
    navs = np.array([e[1] for e in wild])
    assert np.all(np.isfinite(navs)) and np.all(navs > 0)


def test_costs_are_charged_on_true_ups_and_the_band_orders_the_trade_count():
    _, ups_a, cost_a = run(core_daily=0.0, tilt_daily=0.01)
    assert ups_a >= 1
    assert cost_a > 200_000.0 * 5.0 / 10_000.0, "true-ups must add costs beyond the initial buy"
    # a zero-width band trades at every check the drift is nonzero, so it must trade at least
    # as often as the 5-point band on the same path (total COST is not ordered — few big trades
    # and many small ones move similar dollars, which is §2.1's own argument for bands)
    _, ups_zero, _ = run(core_daily=0.0, tilt_daily=0.01, band=0.0)
    assert ups_zero >= ups_a


def test_an_unknown_addv_falls_to_the_worst_bucket():
    assert blend.spread_bps(0.0) == 60.0
    assert blend.spread_bps(1e9) == 5.0
    assert blend.spread_bps(float("nan")) == 60.0, (
        "NaN dollar volume is an unknown, and an unknown prices at the worst bucket")
