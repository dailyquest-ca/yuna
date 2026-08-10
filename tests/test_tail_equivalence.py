"""The backtest driver passes tails, not whole histories — this pins that it is allowed to.

`backtest.py` becomes a driver over `signals.py` (docs/backtest-plan-2026-08-10.md, Phase 2), and
it calls every rule once per name per rank date: ~1.5M evaluations over a ten-year window. Handing
each call the whole series to date makes the cost grow with the window; handing it a fixed 280-bar
tail makes the cost constant. That is only sound if the tail returns the *identical* verdict, so
the equivalence is an invariant of the design, not an optimisation detail.

280 is not arbitrary: the deepest window any rule reads is `setup_proximity`'s 252-session ATR
percentile plus ATR(14)'s own 14 bars = 266. `WARMUP = 280` in the backtest already carries this
number. A rule that starts reading deeper than 280 breaks the driver, and it breaks it silently —
the run still completes, with quietly different answers. These tests are the alarm.
"""
import sys
import pathlib

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import signals as s                                                      # noqa: E402

TAIL = 280
DEEPEST_WINDOW = 266            # setup_proximity's 252 + atr(14)'s 14


def history(n=2520, seed=7):
    """A decade of plausible OHLCV. Shape is what is under test, not distribution."""
    rng = np.random.default_rng(seed)
    close = 50.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.018, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.008, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.008, n)))
    volume = rng.lognormal(13.5, 0.5, n)
    return high, low, close, volume


@pytest.fixture(params=[7, 11, 42, 1234, 99991])
def paths(request):
    """Several unrelated paths — one lucky series proves nothing about a slicing invariant."""
    return history(seed=request.param)


def test_the_tail_is_deeper_than_the_deepest_window_any_rule_reads():
    assert TAIL >= DEEPEST_WINDOW


def test_trend_template_reads_no_deeper_than_the_tail(paths):
    """§3.2 M2 — the 200-day and its value 21 sessions ago, so 221 bars, inside 280."""
    h, l, c, v = paths
    assert s.trend_template(c) == s.trend_template(c[-TAIL:])


def test_base_scan_reads_no_deeper_than_the_tail(paths):
    """§3.2 M3 — the pivot window reaches 120 sessions back; depth and contraction are shallower."""
    h, l, c, v = paths
    full, tail = s.base_scan(h, l, c), s.base_scan(h[-TAIL:], l[-TAIL:], c[-TAIL:])
    assert full["valid"] == tail["valid"]
    assert full["state"] == tail["state"]
    assert full["broken"] == tail["broken"]
    assert full["pivot"] == pytest.approx(tail["pivot"])
    assert full["depth"] == pytest.approx(tail["depth"])
    assert full["contraction_low"] == pytest.approx(tail["contraction_low"])


def test_momentum_quality_reads_no_deeper_than_the_tail(paths):
    """§3.2 MCN — a 90-day regression on 91 bars of log price."""
    h, l, c, v = paths
    assert s.momentum_quality(c) == pytest.approx(s.momentum_quality(c[-TAIL:]))


def test_setup_proximity_reads_no_deeper_than_the_tail(paths):
    """§3.2 MCN — the deepest of the three: a 252-session ATR percentile over ATR(14)."""
    h, l, c, v = paths
    full = s.setup_proximity(h, l, c, v)
    tail = s.setup_proximity(h[-TAIL:], l[-TAIL:], c[-TAIL:], v[-TAIL:])
    for k in ("atr_pct", "dryup", "near_high"):
        assert full[k] == pytest.approx(tail[k]), k


def test_a_tail_one_bar_short_of_the_deepest_window_does_diverge(paths):
    """The guard has teeth: truncate below 266 and `setup_proximity` genuinely answers differently.

    Without this, the tests above would pass just as happily on a rule that reads nothing at all.
    """
    h, l, c, v = paths
    short = DEEPEST_WINDOW - 40
    full = s.setup_proximity(h, l, c, v)
    cut = s.setup_proximity(h[-short:], l[-short:], c[-short:], v[-short:])
    assert full["atr_pct"] != pytest.approx(cut["atr_pct"])
