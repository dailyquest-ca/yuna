"""The push study's arithmetic, on hand-built paths.

The study's verdicts feed A3's spec, so its own math is pinned the way the engine's is: the
regression, the ATR, and the exit autopsy each against inputs whose right answer is computable
by hand.
"""
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import push_study as ps                                                     # noqa: E402


def test_the_regression_reads_a_clean_exponential_exactly():
    """A price compounding mu per session must return slope exp(mu*252)-1 with R² of 1 —
    anything else and the 'how fast times how clean' score is measuring the fitter, not the
    trend."""
    mu = 0.002
    c = 50.0 * np.exp(mu * np.arange(200))
    slope, r2 = ps.exp_regression(c)
    assert slope == pytest.approx(np.exp(mu * 252) - 1.0, rel=1e-9)
    assert r2 == pytest.approx(1.0, abs=1e-12)


def test_noise_costs_r_squared_but_not_the_slope():
    rng = np.random.default_rng(7)
    mu = 0.002
    c = 50.0 * np.exp(mu * np.arange(200) + rng.normal(0, 0.02, 200))
    slope, r2 = ps.exp_regression(c)
    assert 0.5 < r2 < 1.0
    assert slope == pytest.approx(np.exp(mu * 252) - 1.0, rel=0.35)


def test_the_regression_declines_short_or_degenerate_windows():
    assert ps.exp_regression(np.full(50, 10.0)) == (None, None)
    assert ps.exp_regression(np.full(200, 10.0)) == (None, None)   # zero variance: no R²


def test_atr_reads_the_true_range():
    """Flat closes with a constant 2-point daily range: ATR is exactly 2."""
    n = 40
    close = np.full(n, 100.0)
    high, low = np.full(n, 101.0), np.full(n, 99.0)
    assert ps.atr20(high, low, close) == pytest.approx(2.0)
    assert ps.atr20(high[:10], low[:10], close[:10]) is None, "a short window is not an ATR"


def test_the_exit_autopsy_measures_the_pullback_the_push_actually_needed():
    """A push that runs 100 -> 130, gives back to 117 (10% off the high), then completes at 150:
    the needed trail is 10% of the high, and 13 dollars is 6.5 ATRs when ATR is 2. A 3xATR trail
    (6 dollars) dies on that pullback; a 100-session MA far below survives it."""
    path = np.concatenate([np.linspace(100.0, 130.0, 31),      # the first leg
                           np.linspace(129.0, 117.0, 13),      # the pullback: 13 off the high
                           np.linspace(118.0, 150.0, 33)])     # the completion
    adj = np.concatenate([np.full(150, 100.0), path])          # long flat history before it
    b, e = 150, len(adj) - 1
    out = ps.exit_autopsy(b, e, 2.0, adj)
    assert out["needed_trail_frac"] == pytest.approx(13.0 / 130.0, abs=1e-9)
    assert out["needed_trail_atr"] == pytest.approx(6.5, abs=1e-9)
    assert out["survives_trail_3atr"] is False, "a 6-dollar trail cannot hold a 13-dollar pullback"
    assert out["survives_ma100"] is True, "the 100-session MA sits far under a fresh breakout"


def test_a_straight_run_survives_everything():
    adj = np.concatenate([np.full(150, 100.0), np.linspace(100.0, 151.0, 40)])
    out = ps.exit_autopsy(150, len(adj) - 1, 2.0, adj)
    assert out["needed_trail_frac"] == pytest.approx(0.0, abs=1e-9)
    assert out["survives_trail_3atr"] and out["survives_ma10"] and out["survives_ma20"] \
        and out["survives_ma100"]


def test_the_regime_gate_reads_the_index_against_its_own_average():
    dates = np.arange(1000, 1000 + 300, dtype=np.int64)
    close = np.linspace(100.0, 200.0, 300)                     # rising: above its SMA
    sma = np.full(300, np.nan)
    kernel = np.ones(200) / 200
    sma[199:] = np.convolve(close, kernel, mode="valid")
    assert ps.regime_on(dates, close, sma, 1000 + 250) is True
    assert ps.regime_on(dates, close, sma, 1000 + 100) is None, (
        "no SMA yet means unknown, never a guessed True or False")
    falling = close[::-1].copy()
    sma_f = np.full(300, np.nan)
    sma_f[199:] = np.convolve(falling, kernel, mode="valid")
    assert ps.regime_on(dates, falling, sma_f, 1000 + 250) is False
