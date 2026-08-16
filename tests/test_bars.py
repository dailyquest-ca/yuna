"""§2.5 statistical bars.

Tested against closed-form or hand-computable answers rather than against the implementation's own
output — these functions decide whether a number is allowed to be called a finding, so a test that
merely agrees with the code would certify nothing.
"""
import math
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import bars                                                              # noqa: E402


# ------------------------------------------------------------------------ the normal distribution
def test_the_inverse_normal_round_trips():
    """No scipy here, so the approximation is ours and has to be shown to be worth trusting."""
    for p in (0.001, 0.01, 0.025, 0.1, 0.5, 0.9, 0.975, 0.99, 0.999, 0.9999):
        assert bars.norm_cdf(bars.norm_ppf(p)) == pytest.approx(p, abs=1e-9)


def test_the_normal_matches_known_quantiles():
    assert bars.norm_ppf(0.975) == pytest.approx(1.959963985, abs=1e-6)
    assert bars.norm_ppf(0.5) == pytest.approx(0.0, abs=1e-12)
    assert bars.norm_cdf(0.0) == pytest.approx(0.5, abs=1e-12)


# ------------------------------------------------------------------------------ path statistics
def test_cagr_is_the_compound_rate_not_the_average():
    # exactly doubling over two years is 41.42%, not 50%
    assert bars.cagr(100.0, 200.0, int(2 * bars.SESSIONS_PER_YEAR)) == pytest.approx(
        math.sqrt(2) - 1, abs=1e-9)


def test_max_drawdown_measures_peak_to_trough_not_start_to_end():
    """A path that ends higher than it started still had a drawdown, and the number that matters
    is the worst one an account actually lived through."""
    assert bars.max_drawdown([100, 150, 75, 200]) == pytest.approx(-0.5, abs=1e-12)
    assert bars.max_drawdown([100, 101, 102]) == pytest.approx(0.0, abs=1e-12)


def test_a_non_positive_nav_is_refused_rather_than_priced():
    with pytest.raises(ValueError):
        bars.daily_returns([100.0, 0.0, 50.0])


# ---------------------------------------------------------------------- §2.5(b) winner exclusion
def test_the_jackknife_removes_the_largest_winners():
    pnls = [100.0, 50.0, 25.0, 10.0, 5.0, -20.0, -30.0]      # total 140
    out = bars.jackknife_arithmetic(pnls, start_nav=1000.0)
    assert out["all"] == pytest.approx(0.140)
    assert out["ex_top_1"] == pytest.approx(0.040)           # drop 100
    assert out["ex_top_3"] == pytest.approx(-0.035)          # drop 100+50+25 -> -35
    assert out["ex_top_5"] == pytest.approx(-0.050)          # -> -50


def test_the_jackknife_turns_a_one_trade_result_negative():
    """The A1 shape: one enormous winner carrying a book of small losers. Ex-top-1 must expose it,
    which is the entire reason §2.5 makes single-name exclusion the FIRST robustness check."""
    pnls = [80_000.0] + [-500.0] * 60
    out = bars.jackknife_arithmetic(pnls, start_nav=200_000.0)
    assert out["all"] > 0
    assert out["ex_top_1"] < 0


# ------------------------------------------------------------------------ §2.5(c) block bootstrap
def test_the_bootstrap_is_reproducible_and_brackets_the_truth():
    rng = np.random.default_rng(11)
    r = rng.normal(0.0004, 0.01, size=2000)                  # ~10%/yr drift
    a = bars.block_bootstrap(r, draws=500, seed=7)
    b = bars.block_bootstrap(r, draws=500, seed=7)
    assert a == b, "same seed must give the same answer or the bar is an opinion"
    realised = np.prod(1 + r) ** (bars.SESSIONS_PER_YEAR / r.size) - 1
    assert a["cagr"]["p5"] < realised < a["cagr"]["p95"]
    assert a["cagr"]["p5"] < a["cagr"]["p50"] < a["cagr"]["p95"]
    assert a["max_drawdown"]["p5"] < a["max_drawdown"]["p95"] <= 0.0


def test_the_bootstrap_refuses_a_series_shorter_than_one_block():
    with pytest.raises(ValueError):
        bars.block_bootstrap(np.zeros(10) + 0.001, draws=10)


# --------------------------------------------------------------------------------- §2.5(d) DSR
def test_more_trials_demand_a_higher_sharpe():
    """The point of deflation. The same observed Sharpe must look less impressive once you admit
    how many configurations were tried to find it."""
    few = bars.expected_max_sharpe(0.5, 50)
    many = bars.expected_max_sharpe(0.5, 500)
    assert many > few > 0


def test_the_trial_floor_binds():
    """Zak ruled the count runs forward only; the WO's >=50 floor keeps the deflation honest when
    the forward count is small."""
    assert bars.expected_max_sharpe(0.5, 3) == bars.expected_max_sharpe(0.5, bars.MIN_TRIALS)


def test_a_single_trial_is_refused_rather_than_assumed():
    """With no spread of Sharpes across trials there is nothing to deflate against. Failing closed
    beats inventing a variance — see the no-assumed-values doctrine."""
    with pytest.raises(ValueError):
        bars.expected_max_sharpe(0.0, 50)


def test_negative_skew_and_fat_tails_reduce_the_deflated_sharpe():
    """Both terms have to bite, and in the right direction. This family is violently right-skewed
    and fat-tailed, and the classical Sharpe standard error assumes neither."""
    base = dict(n_obs=2000, trial_sharpe_sd=0.5, n_trials=50)
    plain = bars.deflated_sharpe(1.2, skew=0.0, kurtosis=3.0, **base)["dsr"]
    fat = bars.deflated_sharpe(1.2, skew=0.0, kurtosis=12.0, **base)["dsr"]
    left = bars.deflated_sharpe(1.2, skew=-1.5, kurtosis=3.0, **base)["dsr"]
    assert fat < plain, "fat tails must widen the error and lower confidence"
    assert left < plain, "negative skew must lower confidence"


def test_the_dsr_reports_the_trial_count_it_actually_used():
    out = bars.deflated_sharpe(1.0, n_obs=1000, skew=0.0, kurtosis=3.0,
                               trial_sharpe_sd=0.4, n_trials=7)
    assert out["n_trials_logged"] == 7
    assert out["n_trials_used"] == bars.MIN_TRIALS


# ------------------------------------------------------------------------------------- verdict
def test_a_broken_drawdown_bar_kills_outright():
    """The guard is unchanged in intent — a broken drawdown bar kills, whatever the returns say.
    Only the statistic it reads moved, from the bootstrap tail to the bootstrap median, because
    the benchmark itself fails a -34% bar at the p5 (VOO: median -33.99%, p5 -45.7%)."""
    out = bars.verdict(ex_top_3_beats_benchmark=True, bootstrap_median_cagr=0.20,
                       benchmark_cagr=0.15, dsr=0.99, dd_bar=-0.34,
                       bootstrap_median_drawdown=-0.55, bootstrap_p5_drawdown=-0.70)
    assert out["verdict"] == "dead"


def test_losing_the_edge_ex_top_three_is_unproven_not_dead():
    """E0's interpretation note: barred from scaling, not necessarily dead."""
    out = bars.verdict(ex_top_3_beats_benchmark=False, bootstrap_median_cagr=0.20,
                       benchmark_cagr=0.15, dsr=0.99)
    assert out["verdict"] == "unproven"
    assert any("top 3" in r for r in out["reasons"])


def test_everything_clearing_is_proven():
    out = bars.verdict(ex_top_3_beats_benchmark=True, bootstrap_median_cagr=0.20,
                       benchmark_cagr=0.15, dsr=0.99, dd_bar=-0.34,
                       bootstrap_p5_drawdown=-0.30)
    assert out["verdict"] == "proven"
    assert out["reasons"] == []


# ---------------------------------------------- the drawdown bar reads a median-scale statistic
#
# Measured on the real tape, VOO's own bootstrap 5th-percentile drawdown is -45.7% and the 80/20
# blend's is -45.0%, while both realize -34%/-33%. A -34% bar tested against the p5 is therefore
# unpassable by the benchmark itself, and it killed every arm in the programme for a while. E3's
# -34% is VOO's realized -33.99% rounded — a median-scale number.

def test_the_drawdown_bar_is_tested_against_the_median_not_the_tail():
    """The benchmark's own numbers: median -33.99%, tail -45.7%. A bar of -34% must pass an arm
    whose median is shallower than the index, whatever its tail says."""
    v = bars.verdict(ex_top_3_beats_benchmark=True, bootstrap_median_cagr=0.18,
                     benchmark_cagr=0.1545, dsr=0.99, dd_bar=-0.34,
                     bootstrap_median_drawdown=-0.2955,      # shallower than VOO's -33.99%
                     bootstrap_p5_drawdown=-0.4295)          # deeper than the bar, by design
    assert v["verdict"] == "proven", v


def test_a_genuinely_deep_arm_still_dies():
    """A3d realized -52% and bootstrapped a -55% median: the bar must still kill that."""
    v = bars.verdict(ex_top_3_beats_benchmark=True, bootstrap_median_cagr=0.18,
                     benchmark_cagr=0.1545, dsr=0.99, dd_bar=-0.34,
                     bootstrap_median_drawdown=-0.55, bootstrap_p5_drawdown=-0.776)
    assert v["verdict"] == "dead"
    assert "median" in v["reasons"][0] and "5th percentile" in v["reasons"][0], (
        "the tail belongs on the record even when the median is what killed the arm")


def test_the_benchmark_itself_would_pass_its_own_bar():
    """The sanity check the first cut failed: run 62's VOO — median -33.99%, tail -46.3%."""
    v = bars.verdict(ex_top_3_beats_benchmark=True, bootstrap_median_cagr=0.1592,
                     benchmark_cagr=0.1545, dsr=0.99, dd_bar=-0.34,
                     bootstrap_median_drawdown=-0.3399, bootstrap_p5_drawdown=-0.4632)
    assert v["verdict"] != "dead", "a bar the benchmark fails is a broken bar, not a strict one"
