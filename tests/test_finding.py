"""The §2.5 driver, on hand-built equity paths.

`bars.py` is pinned in test_bars.py; these pin the DRIVER's arithmetic — the cuts, the account-
level jackknife, and the 90/10 counterfactual whose construction was validated against run 53's
recorded +222.10% before it was written down here.
"""
import datetime as dt
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import finding                                                              # noqa: E402
import bars                                                                 # noqa: E402


def sessions(n, start=dt.date(2024, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def equity_rows(n=700, drift=0.0006, bench_drift=0.0005, dark_every=None):
    dates = sessions(n)
    nav = 200_000.0 * np.exp(np.cumsum(np.full(n, drift)))
    bench = 400.0 * np.exp(np.cumsum(np.full(n, bench_drift)))
    rows = []
    for i, d in enumerate(dates):
        b = None if (dark_every and i and i % dark_every == 0) else float(bench[i])
        rows.append((d, float(nav[i]), b))
    return rows, dates


def test_the_cut_slices_sessions_and_realized_trades_together():
    rows, dates = equity_rows()
    pnls = [(dates[100], 1_000.0), (dates[400], 2_000.0), (dates[600], -500.0)]
    full = finding.cut(rows, pnls)
    late = finding.cut(rows, pnls, since=dates[399])
    assert full["sessions"] == 700 and len(full["trade_pnls"]) == 3
    assert late["sessions"] == 301
    assert late["trade_pnls"] == [2_000.0, -500.0], (
        "a trade belongs to the cut its exit realized in")
    assert late["nav"][0] == pytest.approx(float(rows[399][1]))


def test_a_cut_with_nothing_in_it_refuses_to_measure():
    rows, dates = equity_rows(n=100)
    with pytest.raises(RuntimeError, match="nothing to measure"):
        finding.cut(rows, [], since=dates[-1] + dt.timedelta(days=30))


def test_the_ninety_ten_counterfactual_is_the_recorded_construction():
    """Daily-rebalanced 0.9 x benchmark, cash earning nothing — the arithmetic that reproduces
    the ledger's +222.10% on run 53's window. Pinned here against a hand-computable path."""
    rows, _ = equity_rows(n=300, bench_drift=0.001)
    c = finding.cut(rows, [])
    s = finding.score_cut(c)
    br = bars.daily_returns(c["bench"])
    assert s["counterfactual_90_10"]["total_return"] == pytest.approx(
        float(np.prod(1 + 0.9 * br) - 1), abs=1e-6)
    # 90% of a rising benchmark must land between cash and the benchmark itself
    assert 0 < s["counterfactual_90_10"]["total_return"] < s["benchmark"]["total_return"]


def test_the_account_jackknife_subtracts_the_winners_from_the_runs_own_return():
    """Trade-level jackknife alone would misread a parked run — the park's P&L is not in the
    trade list. The account-level figure starts from the run's actual total return and removes
    only the excluded winners' contribution."""
    rows, dates = equity_rows(n=300)
    pnls = [(dates[i], p) for i, p in ((50, 8_000.0), (80, 4_000.0), (120, 2_000.0),
                                       (160, 1_000.0), (200, -3_000.0))]
    c = finding.cut(rows, pnls)
    s = finding.score_cut(c)
    total = s["total_return"]
    start = float(c["nav"][0])
    assert s["jackknife"]["account_ex_top"]["ex_top_1"] == pytest.approx(
        total - 8_000.0 / start, abs=1e-6)
    assert s["jackknife"]["account_ex_top"]["ex_top_3"] == pytest.approx(
        total - 14_000.0 / start, abs=1e-6)


def test_dark_benchmark_days_do_not_poison_the_cut():
    """The engine writes None on days the benchmark did not print (run 52's lesson, the other way
    round) — the driver must skip them, not crash or read them as zero."""
    rows, _ = equity_rows(dark_every=97)
    s = finding.score_cut(finding.cut(rows, []))
    assert s["benchmark"]["total_return"] > 0


def test_the_bootstrap_is_reproducible_or_it_is_an_opinion():
    rows, _ = equity_rows()
    c = finding.cut(rows, [])
    a, b = finding.score_cut(c), finding.score_cut(c)
    assert a["bootstrap"] == b["bootstrap"]
    assert a["bootstrap"]["seed"] == 0 and a["bootstrap"]["draws"] == 10_000


def test_the_oos_boundary_is_the_work_orders_month():
    assert finding.OOS_START == dt.date(2025, 8, 1), (
        "§2.5(a) names Aug-2025; moving the boundary is a work-order edit, not a code edit")
