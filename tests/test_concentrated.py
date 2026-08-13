"""The concentrated winner-catcher, on hand-built tapes.

This arm has no §3.2 machinery to inherit, so what has to be pinned is its own arithmetic: the
rank is 12-1 and look-ahead-free, the clock produces the trade count the day-job constraint
demands, and the book really is the top N rather than whatever survived.
"""
import datetime as dt
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import concentrated as cc                                                   # noqa: E402


def sessions(n, start=dt.date(2017, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


N_DAYS = 900


def grid(paths):
    """paths: dict ticker -> array of adjusted closes."""
    dates = sessions(N_DAYS)
    tickers = sorted(paths)
    adj = np.column_stack([paths[t] for t in tickers])
    raw = adj.copy()
    dv = np.full_like(adj, 5e8)                    # deep liquidity everywhere
    return dates, tickers, adj, raw, dv


def test_the_rank_is_twelve_minus_one_and_reads_no_future_bar():
    """The score must be the return from t-252 to t-21 — the last month is deliberately skipped,
    and nothing after t may touch it. The fixture makes the skipped month decisive: a name that
    doubled over the year then collapsed in the final three weeks must still rank first."""
    steady = np.concatenate([np.linspace(100.0, 130.0, N_DAYS)])
    spiker = np.concatenate([np.linspace(50.0, 200.0, N_DAYS - cc.SKIP),
                             np.linspace(200.0, 60.0, cc.SKIP)])       # collapses after the skip
    dates, tickers, adj, raw, dv = grid({"STEADY.US": steady, "SPIKE.US": spiker})
    order = cc.rank_at(N_DAYS - 1, adj, raw, dv, risk_adjusted=False)
    assert tickers[order[0]] == "SPIKE.US", (
        "the collapse sits inside the skipped month, so it must not affect the rank")

    # and the future truly cannot leak: mutating bars after the scoring index changes nothing
    a2 = adj.copy()
    a2[N_DAYS - 1, :] = 1.0
    assert cc.rank_at(N_DAYS - 200, a2, raw, dv, risk_adjusted=False) == \
           cc.rank_at(N_DAYS - 200, adj, raw, dv, risk_adjusted=False)


def test_the_risk_adjustment_prefers_the_smoother_of_two_equal_climbs():
    """SPMO's own adjustment: same 12-1 return, less volatility, higher rank."""
    n = N_DAYS
    smooth = 100.0 * np.exp(np.linspace(0, 0.7, n))
    rough = smooth * (1 + 0.08 * np.sin(np.arange(n) / 2.0))
    rough = rough * (smooth[-cc.SKIP - 1] / rough[-cc.SKIP - 1])      # match the 12-1 return
    dates, tickers, adj, raw, dv = grid({"SMOOTH.US": smooth, "ROUGH.US": rough})
    plain = cc.rank_at(n - 1, adj, raw, dv, risk_adjusted=False)
    adjusted = cc.rank_at(n - 1, adj, raw, dv, risk_adjusted=True)
    assert tickers[adjusted[0]] == "SMOOTH.US"
    assert set(plain) == set(adjusted), "both rank the same universe, only the order differs"


def test_the_liquidity_and_price_floors_bind():
    n = N_DAYS
    good = 100.0 * np.exp(np.linspace(0, 0.9, n))
    penny = good * 0.02                                  # a $2-4 stock: below the $5 floor
    dates, tickers, adj, raw, dv = grid({"GOOD.US": good, "PENNY.US": penny})
    order = cc.rank_at(n - 1, adj, raw, dv, risk_adjusted=False)
    assert [tickers[j] for j in order] == ["GOOD.US"], "the $5 floor must exclude the penny name"

    thin = dv.copy()
    thin[:, tickers.index("GOOD.US")] = 1e5              # $100k/day: below the $10M floor
    assert cc.rank_at(n - 1, adj, raw, thin, risk_adjusted=False) == []


def test_the_clock_sets_the_trade_count_the_day_job_allows():
    """The whole point of the slow clock: a dozen names changed twice a year is a dozen-odd
    decisions a year, not a full-time job."""
    dates = sessions(N_DAYS)
    semi = cc.rebalance_dates(dates, 6, cc.FORMATION + 1)
    quarterly = cc.rebalance_dates(dates, 3, cc.FORMATION + 1)
    annual = cc.rebalance_dates(dates, 12, cc.FORMATION + 1)
    years = (dates[-1] - dates[cc.FORMATION]).days / 365.25
    assert len(annual) < len(semi) < len(quarterly)
    assert 1.5 < len(semi) / years < 2.5, "semi-annual must mean about twice a year"


def test_the_book_is_the_top_n_and_the_rest_is_parked():
    """Concentration is the thesis: exactly N names, equal weight, remainder in the park."""
    n = N_DAYS
    paths = {f"N{i:02d}.US": 100.0 * np.exp(np.linspace(0, 0.2 + i * 0.05, n)) for i in range(10)}
    dates, tickers, adj, raw, dv = grid(paths)
    park = np.full(n, 50.0)
    eq, trades, costs = cc.simulate(dates, tickers, adj, raw, dv, park,
                                    n=3, months=6, risk_adjusted=False, sleeve=1.0,
                                    start_nav=200_000.0)
    entries = [t for t in trades if "entry_date" in t]
    assert entries, "nothing was ever bought"
    first_day = min(t["entry_date"] for t in entries)
    bought = {t["ticker"] for t in entries if t["entry_date"] == first_day}
    assert len(bought) == 3, f"the book must hold exactly three names, got {bought}"
    # the strongest climbers are the highest-numbered by construction
    assert bought == {"N09.US", "N08.US", "N07.US"}
    assert costs > 0, "trading is not free"
    assert all(v > 0 for _, v, _ in eq)


def test_a_half_sleeve_leaves_half_the_account_in_the_park():
    n = N_DAYS
    paths = {f"N{i:02d}.US": 100.0 * np.exp(np.linspace(0, 0.2 + i * 0.05, n)) for i in range(6)}
    dates, tickers, adj, raw, dv = grid(paths)
    park = np.full(n, 50.0)
    full = cc.simulate(dates, tickers, adj, raw, dv, park, n=3, months=6,
                       risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)[1]
    half = cc.simulate(dates, tickers, adj, raw, dv, park, n=3, months=6,
                       risk_adjusted=False, sleeve=0.5, start_nav=200_000.0)[1]
    spend_full = sum(t["spend"] for t in full if "entry_date" in t)
    spend_half = sum(t["spend"] for t in half if "entry_date" in t)
    assert spend_half < spend_full * 0.75, (
        "a half sleeve must put materially less into single names — the rest belongs to the park")


def test_every_announced_cell_moves_one_axis_off_its_own_centre():
    """Two families, each one axis at a time off its own centre: the full-universe cells off
    n12_semi, and the large-cap cells off lg12_semi."""
    for centre_name in ("n12_semi", "lg12_semi"):
        centre = dict(cc.CELLS[centre_name])
        prefix = centre_name.split("12")[0]
        for name, spec in cc.CELLS.items():
            if not name.startswith(prefix) or name == centre_name:
                continue
            merged = {**centre, **spec}
            moved = {k for k in merged if merged[k] != centre.get(k)}
            assert len(moved) == 1, f"{name} moves {moved} — one axis at a time"


def test_the_large_cap_pool_ranks_only_the_most_traded_names():
    """SPMO ranks inside the S&P 500. `top_by_addv` is that restriction, applied BEFORE the
    momentum rank so a thin rocket cannot outrank a liquid leader."""
    n = N_DAYS
    paths = {f"N{i:02d}.US": 100.0 * np.exp(np.linspace(0, 0.1 + i * 0.10, n)) for i in range(6)}
    dates, tickers, adj, raw, dv = grid(paths)
    # the strongest climber is the THINNEST name — deep enough to clear the floor, but nowhere
    # near the most-traded three
    rocket = tickers.index("N05.US")
    dv[:, rocket] = 2e7
    unrestricted = cc.rank_at(n - 1, adj, raw, dv, risk_adjusted=False)
    restricted = cc.rank_at(n - 1, adj, raw, dv, risk_adjusted=False, top_by_addv=3)
    assert tickers[unrestricted[0]] == "N05.US", "the fixture's rocket must top an open rank"
    assert rocket not in restricted, "the large-cap pool must exclude it before ranking"
    assert len(restricted) == 3


def test_a_name_that_goes_dark_does_not_zero_the_account():
    """Run 52's lesson, in new code: a holding that stops printing is carried at its last mark,
    not silently valued at zero. The tell was a -100.0% max drawdown on a long-only book — five
    of the first eight cells reported it before this was fixed."""
    n = N_DAYS
    paths = {f"N{i:02d}.US": 100.0 * np.exp(np.linspace(0, 0.3 + i * 0.05, n)) for i in range(5)}
    dates, tickers, adj, raw, dv = grid(paths)
    # the strongest name — the one the book will certainly hold — stops trading two thirds in
    dark = tickers.index("N04.US")
    adj[int(n * 0.75):, dark] = np.nan
    park = np.full(n, 50.0)
    eq, _, _ = cc.simulate(dates, tickers, adj, raw, dv, park, n=3, months=6,
                           risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)
    nav = np.array([v for _, v, _ in eq])
    worst = float((nav / np.maximum.accumulate(nav) - 1).min())
    assert worst > -0.5, f"a single dark holding collapsed the account: max drawdown {worst:.1%}"
    assert all(v > 0 for v in nav)
