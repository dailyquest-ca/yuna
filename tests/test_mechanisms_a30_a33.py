"""WO-A30..A33 — four mechanisms on the cell of record (docs/wo-a30-a33-four-mechanisms.md).

Each test states the documented rule, not the current output: residual momentum prefers the
stock-specific climb over the market-driven one; the crash state needs BOTH a two-year fall and
high volatility; the January veto empties the book for January and lets it refill in February;
the breadth gate reads the majority of names, not the index.
"""
import datetime as dt
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import concentrated as cc  # noqa: E402

N = 900


def sessions(n, start=dt.date(2017, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def grid(paths):
    dates = sessions(N)
    tickers = sorted(paths)
    adj = np.column_stack([paths[t] for t in tickers])
    return dates, tickers, adj, adj.copy(), np.full_like(adj, 5e8)


def test_residual_momentum_prefers_the_alpha_climb_over_the_beta_climb():
    """A30. BETA2 rides the market with beta two and no return of its own; ALPHA has beta zero
    and a stock-specific drift that accelerated in the last year. Raw 12-1 ranks BETA2 first
    because the bull market doubled through it; residual momentum ranks ALPHA first because
    BETA2's return is entirely explained and ALPHA's recent residual is above its own average."""
    t = np.arange(N)
    late = t >= N - 300
    market = 100.0 * np.exp(np.cumsum(np.where(late, 0.0015, 0.0006)) + 0.01 * np.sin(t / 3.0))
    beta2 = 100.0 * (market / market[0]) ** 2 * (1 + 0.003 * np.sin(t / 1.7))
    alpha = 100.0 * np.exp(np.cumsum(np.where(late, 0.0025, 0.0002)) + 0.006 * np.sin(t / 2.3))
    dates, tickers, adj, raw, dv = grid({"ALPHA.US": alpha, "BETA2.US": beta2})
    raw_order = cc.rank_at(N - 1, adj, raw, dv, risk_adjusted=False)
    res_order = cc.rank_at(N - 1, adj, raw, dv, risk_adjusted=True, residual_vs=market)
    assert tickers[raw_order[0]] == "BETA2.US", "the fixture's raw rank must prefer the beta climb"
    assert tickers[res_order[0]] == "ALPHA.US", "residual momentum sees through the market"
    # too little history scores nothing rather than a guess
    assert cc.rank_at(cc.SKIP + 100, adj, raw, dv, risk_adjusted=True, residual_vs=market) == []


def test_the_crash_state_needs_both_a_two_year_fall_and_high_volatility():
    t = np.arange(N)
    bear_wild = 100.0 * np.exp(-0.0004 * t) * (1 + 0.03 * np.sin(t))   # ~32% annualized
    bear_calm = 100.0 * np.exp(-0.0004 * t) * (1 + 0.002 * np.sin(t))  # ~2%
    bull_wild = 100.0 * np.exp(0.0006 * t) * (1 + 0.03 * np.sin(t))
    assert cc.crash_state(N - 1, bear_wild) is True
    assert cc.crash_state(N - 1, bear_calm) is False, "a quiet bear is not the crash state"
    assert cc.crash_state(N - 1, bull_wild) is False, "a wild bull is not the crash state"
    assert cc.crash_state(cc.CRASH_LOOKBACK - 1, bear_wild) is False, "unknown is False"
    assert cc.market_vol(N - 1, bear_wild) > cc.CRASH_VOL_ANNUAL > cc.market_vol(N - 1, bear_calm)


def test_the_breadth_gate_reads_the_majority_of_names():
    up = lambda k: 100.0 + np.linspace(0, 20 + k, N)
    down = lambda k: 120.0 - np.linspace(0, 20 + k, N)
    six_up = {f"U{k}.US": up(k) for k in range(6)} | {f"D{k}.US": down(k) for k in range(4)}
    four_up = {f"U{k}.US": up(k) for k in range(4)} | {f"D{k}.US": down(k) for k in range(6)}
    b6 = cc.breadth_series(grid(six_up)[2])
    b4 = cc.breadth_series(grid(four_up)[2])
    assert np.isnan(b6[cc.BREADTH_WINDOW - 2]), "no vote before the window has printed"
    assert b6[N - 1] == 0.6 and b6[N - 1] >= cc.BREADTH_ON
    assert b4[N - 1] == 0.4 and b4[N - 1] < cc.BREADTH_ON


def test_the_january_veto_empties_the_book_for_january_and_refills_it_in_february():
    t = np.arange(N)
    market = 100.0 * np.exp(0.0006 * t) * (1 + 0.002 * np.sin(t / 5))
    paths = {f"N{k}.US": 100.0 * np.exp((0.0004 + 0.0002 * k) * t) * (1 + 0.003 * np.sin(t / (2 + k)))
             for k in range(3)}
    dates, tickers, adj, raw, dv = grid(paths)
    park = np.full(N, 50.0)
    eq, trades, _, health = cc.simulate(dates, tickers, adj, raw, dv, park, n=2, months=6,
                                        risk_adjusted=False, sleeve=1.0, start_nav=200_000.0,
                                        every_sessions=1, index_px=market, latch=(1, 1),
                                        market_px=market, jan_veto=True)
    jan = [npos for d, v, b, dep, npos in eq if d.year == 2019 and d.month == 1]
    mar = [npos for d, v, b, dep, npos in eq if d.year == 2019 and d.month == 3]
    assert jan and max(jan) == 0, "nothing is held in January"
    assert mar and max(mar) == 2, "the book refills once the veto lifts"
    assert any(x.get("reason") == "jan_off" for x in trades)
    assert health["mechanisms"]["jan_off_sessions"] > 0
    assert health["mechanisms"]["crash_off_sessions"] == 0
