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
    eq, trades, costs, _ = cc.simulate(dates, tickers, adj, raw, dv, park,
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


# The grid is a tree: every cell names the cell it varies, and differs from it in exactly one
# key. Written out rather than inferred from the names — matching on a prefix let the whole
# `t250_*` family escape this check, and `t250_8_gated` moved two axes at once unnoticed.
PARENT = {
    "n8_semi": "n12_semi", "n20_semi": "n12_semi", "n12_quarterly": "n12_semi",
    "n12_annual": "n12_semi", "n12_semi_raw": "n12_semi", "n12_semi_half": "n12_semi",
    "n12_semi_third": "n12_semi",
    "lg12_semi": "n12_semi", "lg12_semi_third": "lg12_semi", "lg20_semi": "lg12_semi",
    "lg12_annual": "lg12_semi", "lg12_semi_gated": "lg12_semi",
    "t250_12_semi": "lg12_semi", "t250_12_gated": "t250_12_semi",
    "t250_8_gated": "t250_12_gated",
    "lg12_semi_trail": "lg12_semi", "lg8_semi_trail": "lg12_semi_trail",
    "lg12_semi_trail_third": "lg12_semi_trail", "t250_12_trail": "t250_12_semi",
    "lg12_semi_vt": "lg12_semi", "lg12_semi_trail_vt": "lg12_semi_trail",
    # WO-A5's ladder: every probe moves one axis off the champion it is probing
    "lad_n6": "lg8_semi_trail", "lad_n10": "lg8_semi_trail",
    "lad_p250": "lg8_semi_trail", "lad_p750": "lg8_semi_trail",
    "lad_quarter": "lg8_semi_trail", "lad_annual": "lg8_semi_trail",
    "lad_wide8": "lg8_semi_trail", "lad_wide12": "lg8_semi_trail",
    "lad_arm12": "lg8_semi_trail", "lad_arm18": "lg8_semi_trail",
    "lad_init6": "lg8_semi_trail", "lad_init10": "lg8_semi_trail",
    "lad_euph4": "lg8_semi_trail", "lad_euph6": "lg8_semi_trail",
    "lad_cost2x": "lg8_semi_trail", "lad_cost4x": "lg8_semi_trail",
    "lg8_trail_intraday": "lg8_semi_trail", "lg12_trail_intraday": "lg12_semi_trail",
    "lg8_trail_nextopen": "lg8_semi_trail", "lg12_trail_nextopen": "lg12_semi_trail",
    "clk_monthly": "lg8_trail_nextopen", "clk_bimonthly": "lg8_trail_nextopen",
    "clk_quarter": "lg8_trail_nextopen", "clk_annual": "lg8_trail_nextopen",
    "sec70_semi": "lg8_trail_nextopen", "sec70_monthly": "sec70_semi",
}


def test_every_announced_cell_moves_one_axis_off_its_own_parent():
    assert set(cc.CELLS) - {"n12_semi"} == set(PARENT), (
        "every cell but the root declares the cell it varies — a new cell states its parent")
    for name, parent in PARENT.items():
        base, spec = dict(cc.CELLS[parent]), cc.CELLS[name]
        merged = {**base, **spec}
        moved = {k for k in merged if merged[k] != base.get(k)}
        assert len(moved) == 1, f"{name} moves {moved} off {parent} — one axis at a time"


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
    eq, _, _, _ = cc.simulate(dates, tickers, adj, raw, dv, park, n=3, months=6,
                           risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)
    nav = np.array([v for _, v, _ in eq])
    worst = float((nav / np.maximum.accumulate(nav) - 1).min())
    assert worst > -0.5, f"a single dark holding collapsed the account: max drawdown {worst:.1%}"
    assert all(v > 0 for v in nav)


def test_the_gate_sells_the_book_when_the_market_breaks_its_trend():
    """The ungated cells hold through everything between rebalances and drew 54-63%. The gate is
    the cheapest exit there is: below the index's own 200-day, the sleeve waits in the park."""
    n = N_DAYS
    paths = {f"N{i:02d}.US": 100.0 * np.exp(np.linspace(0, 0.4 + i * 0.05, n)) for i in range(5)}
    dates, tickers, adj, raw, dv = grid(paths)
    park = np.full(n, 50.0)
    # the index rises for two thirds, then falls hard enough to break its own 200-day
    index = np.concatenate([np.linspace(100.0, 200.0, int(n * 0.7)),
                            np.linspace(200.0, 90.0, n - int(n * 0.7))])
    _, ungated, _, _ = cc.simulate(dates, tickers, adj, raw, dv, park, n=3, months=6,
                                risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)
    _, gated, _, _ = cc.simulate(dates, tickers, adj, raw, dv, park, n=3, months=6,
                              risk_adjusted=False, sleeve=1.0, start_nav=200_000.0,
                              index_px=index)
    assert not any(t.get("reason") == "gate_off" for t in ungated)
    assert any(t.get("reason") == "gate_off" for t in gated), (
        "the index fell through its own 200-day and the book was not sold")


def test_an_unevaluable_gate_keeps_the_book_out():
    """Not enough history is not permission. A gate that cannot be evaluated must not wave the
    book through — the same polarity every other guard in this repo uses."""
    index = np.full(50, 100.0)
    assert cc.regime_ok(10, index) is False
    rising = np.linspace(100.0, 200.0, 400)
    assert cc.regime_ok(399, rising) is True
    falling = np.linspace(200.0, 100.0, 400)
    assert cc.regime_ok(399, falling) is False


def test_the_book_is_paired_into_positions_for_the_ledger():
    """"Did it hold MRVL" has to be a query, not a belief — so entries and exits are paired into
    positions with prices, and a name still held at the end is recorded as open rather than lost."""
    dates = sessions(10)
    trades = [dict(ticker="A.US", entry_date=dates[0], price=10.0, qty=100.0, spend=1000.0),
              dict(ticker="A.US", exit_date=dates[5], price=15.0, qty=100.0, reason="rebalance"),
              dict(ticker="B.US", entry_date=dates[2], price=20.0, qty=50.0, spend=1000.0)]
    out = cc.pair_trades(trades, dates)
    closed = [t for t in out if t["exit_date"] is not None]
    still_open = [t for t in out if t["exit_date"] is None]
    assert len(closed) == 1 and len(still_open) == 1
    assert closed[0]["pnl"] == pytest.approx(500.0)
    assert closed[0]["pnl_pct"] == pytest.approx(0.5)
    assert closed[0]["bars"] == 5
    assert still_open[0]["ticker"] == "B.US" and still_open[0]["reason"] == "open_at_end"


# ---------------------------------------------------------------- §3.2's trail, on this book

def test_the_initial_stop_is_never_wider_than_eight_percent():
    """§3.2 Stops: 'Initial: ... entry - 8%. Never wider than 8%.' A rank book has no base, so
    the 8% half is the whole rule until the trail arms."""
    st = dict(entry=100.0, hi=100.0, stop=92.0, armed=False)
    assert cc.trail_stop(99.0, st, np.array([100.0])) == pytest.approx(92.0)
    # a name 14% up has not armed yet — still the initial stop, not a trail off the high
    st = dict(entry=100.0, hi=114.0, stop=92.0, armed=False)
    assert cc.trail_stop(114.0, st, np.array([100.0])) == pytest.approx(92.0)


def test_the_trail_arms_at_plus_fifteen_and_rides_ten_below_the_high():
    """'+15% from average cost -> trail 10% below highest close since entry.'"""
    steady = np.linspace(100.0, 115.0, 60)          # a normal climb: 115 is not 2sd above it
    st = dict(entry=100.0, hi=115.0, stop=92.0, armed=False)
    assert cc.trail_stop(115.0, st, steady) == pytest.approx(103.5)
    assert st["armed"], "once armed it stays armed — the plan ratchets up, never down"
    # and it does ratchet: a pullback cannot widen the stop it already set
    assert cc.trail_stop(104.0, st, steady) == pytest.approx(103.5)


def test_the_euphoria_rule_tightens_to_five_percent():
    """'closes > 2 standard deviations above its own 50-day -> trail tightens to 5%.'"""
    quiet = np.linspace(120.0, 140.0, 50)           # mean ~130, 2sd ~12 — 140 is inside the band
    hot = np.concatenate([np.full(49, 100.0), [140.0]])
    st = dict(entry=100.0, hi=140.0, stop=0.0, armed=True)
    assert cc.trail_stop(140.0, dict(st), quiet) == pytest.approx(126.0), (
        "10% below the high while the close is unremarkable against its own 50-day")
    assert cc.trail_stop(140.0, dict(st), hot) == pytest.approx(133.0), (
        "5% below the high once it is 2sd above its own 50-day")


def test_a_flat_window_is_not_euphoria():
    """A halted name printing one price for fifty sessions has no standard deviation to be two
    of; without the guard it comes back from the halt on a 5% leash."""
    st = dict(entry=100.0, hi=115.0, stop=0.0, armed=True)
    assert cc.trail_stop(115.0, st, np.full(60, 100.0)) == pytest.approx(103.5)


def test_the_trail_actually_sells_a_name_that_rolls_over():
    """The point of the family: a book with no exit between rebalances held from a 2025-10 peak
    to a 2026-07 trough. With the trail on, a name that breaks its stop leaves the book."""
    n = N_DAYS
    # one name doubles then collapses; the rest drift, so the collapse is not a rebalance signal
    crash = np.concatenate([np.linspace(100.0, 300.0, n - 120), np.linspace(300.0, 60.0, 120)])
    paths = {"CRASH.US": crash}
    for i in range(5):
        paths[f"N{i:02d}.US"] = np.linspace(100.0, 130.0 + i, n)
    dates, tickers, adj, raw, dv = grid(paths)
    park = np.full(n, 100.0)
    kw = dict(n=3, months=6, risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)
    held_trades = cc.simulate(dates, tickers, adj, raw, dv, park, **kw)[1]
    trail_trades = cc.simulate(dates, tickers, adj, raw, dv, park, trail=True, **kw)[1]
    assert not [t for t in held_trades if t.get("reason") == "trail_stop"]
    stops = [t for t in trail_trades if t.get("reason") == "trail_stop"]
    assert any(t["ticker"] == "CRASH.US" for t in stops), (
        "a name that gives back 80% of a double must hit §3.2's trail long before the rebalance")


def test_the_trailed_book_ends_richer_than_the_book_that_held_the_crash():
    n = N_DAYS
    crash = np.concatenate([np.linspace(100.0, 300.0, n - 120), np.linspace(300.0, 60.0, 120)])
    paths = {"CRASH.US": crash}
    for i in range(5):
        paths[f"N{i:02d}.US"] = np.linspace(100.0, 130.0 + i, n)
    dates, tickers, adj, raw, dv = grid(paths)
    park = np.full(n, 100.0)
    kw = dict(n=3, months=6, risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)
    plain = cc.simulate(dates, tickers, adj, raw, dv, park, **kw)[0]
    trailed = cc.simulate(dates, tickers, adj, raw, dv, park, trail=True, **kw)[0]
    assert trailed[-1][1] > plain[-1][1], "an exit that fires on a real collapse must pay for itself"


def test_a_stopped_name_is_sold_at_the_next_session_not_the_stop_price():
    """The tape has closes and no intraday range, so the stop cannot be filled at the stop. The
    fill is the NEXT close — strictly worse than a broker stop, never better."""
    n = N_DAYS
    gap = np.concatenate([np.linspace(100.0, 300.0, n - 60), np.full(60, 150.0)])
    paths = {"GAP.US": gap}
    for i in range(5):
        paths[f"N{i:02d}.US"] = np.linspace(100.0, 130.0 + i, n)
    dates, tickers, adj, raw, dv = grid(paths)
    park = np.full(n, 100.0)
    trades = cc.simulate(dates, tickers, adj, raw, dv, park, n=3, months=6, risk_adjusted=False,
                         sleeve=1.0, start_nav=200_000.0, trail=True)[1]
    stop = next(t for t in trades if t.get("reason") == "trail_stop" and t["ticker"] == "GAP.US")
    assert stop["price"] == pytest.approx(150.0), (
        "filled at the post-gap close, not at the 270 the trail was sitting on")


# ------------------------------------------------- Barroso-Santa-Clara, on the book's own vol

def test_the_governor_only_ever_shrinks():
    """The paper's symmetric version borrows; this account does not."""
    calm = list(100_000.0 * np.exp(np.linspace(0, 0.05, 400)))       # near-zero realized vol
    assert cc.vol_scalar(calm, 0.12) == 1.0
    rng = np.random.default_rng(0)
    wild = list(100_000.0 * np.exp(np.cumsum(rng.normal(0, 0.05, 400))))
    g = cc.vol_scalar(wild, 0.12)
    assert 0.0 < g < 0.35, f"5%/day is ~79% annualized — 0.12/0.79 is a hard shrink, got {g}"


def test_the_governor_declares_its_warmup_rather_than_guessing():
    assert cc.vol_scalar([100.0] * 50, 0.12) == 1.0
    assert cc.vol_scalar([], 0.12) == 1.0


def test_the_governor_cuts_the_book_when_the_book_itself_turns_violent():
    """The market gate failed because it watched the index. This watches the book: a violent
    book must end up holding less in names and more in the park than a calm one."""
    n = N_DAYS
    rng = np.random.default_rng(7)
    shocks = np.concatenate([np.zeros(400), rng.normal(0, 0.06, n - 400)])
    paths = {f"N{i:02d}.US": 100.0 * np.exp(np.cumsum(np.full(n, 0.0006) + shocks * (1 + 0.1 * i)))
             for i in range(5)}
    dates, tickers, adj, raw, dv = grid(paths)
    park = np.full(n, 100.0)
    kw = dict(n=3, months=6, risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)
    plain = cc.simulate(dates, tickers, adj, raw, dv, park, **kw)[1]
    gov = cc.simulate(dates, tickers, adj, raw, dv, park, vol_target=0.12, **kw)[1]
    assert not [t for t in plain if t.get("reason") == "vol_governor"]
    assert [t for t in gov if t.get("reason") == "vol_governor"], (
        "a book running six-percent daily moves must be cut back toward the park")


def test_pair_trades_matches_partial_exits_against_partial_lots():
    """The governor sells fractions of positions; FIFO must survive that."""
    dates = sessions(10)
    trades = [dict(ticker="A.US", entry_date=dates[0], price=100.0, qty=10.0, spend=1000.0),
              dict(ticker="A.US", exit_date=dates[2], price=110.0, qty=4.0, reason="vol_governor"),
              dict(ticker="A.US", exit_date=dates[5], price=120.0, qty=6.0, reason="rebalance")]
    out = cc.pair_trades(trades, dates)
    assert len(out) == 2
    assert sum(p["qty"] for p in out) == pytest.approx(10.0), "no shares invented or lost"
    assert [p["reason"] for p in out] == ["vol_governor", "rebalance"]
    assert sum(p["pnl"] for p in out) == pytest.approx(4 * 10.0 + 6 * 20.0)
    assert not [p for p in out if p["reason"] == "open_at_end"], "the lot closed — nothing is open"


def test_the_rebalance_sizes_from_the_whole_account_not_the_cash_it_freed():
    """Carried names are part of NAV. Reading NAV as cash alone sized every new slice out of an
    account missing its survivors and parked the difference — a sleeve=1.00 cell really running
    about 0.77."""
    n = N_DAYS
    # six names all trending up on out-of-phase cycles, so the 12-1 rank genuinely rotates: each
    # rebalance replaces part of the book and carries the rest. Partial turnover is the whole
    # point — a book that changes all of its names, or none, never exposes the defect.
    t = np.arange(n, dtype=float)
    paths = {f"N{i:02d}.US": 100.0 * np.exp(0.0008 * t
                                            + 0.35 * np.sin(2 * np.pi * t / 378.0 + i * np.pi / 3))
             for i in range(6)}
    dates, tickers, adj, raw, dv = grid(paths)
    park = np.full(n, 100.0)                      # a flat park: idle money earns nothing
    eq, trades, _, _ = cc.simulate(dates, tickers, adj, raw, dv, park, n=3, months=6,
                                risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)
    nav_on = {d: v for d, v, _ in eq}
    ti, di = {t: j for j, t in enumerate(tickers)}, {d: i for i, d in enumerate(dates)}
    rebals = sorted({t.get("entry_date") or t["exit_date"] for t in trades
                     if t.get("reason") != "open_at_end"})
    qty, checked, partial = {}, 0, 0
    for k, day in enumerate(rebals):
        opened = {t["ticker"] for t in trades if t.get("entry_date") == day}
        for tr in trades:
            if tr.get("reason") == "open_at_end":
                continue                          # a paper close, not a rebalance leg
            if tr.get("entry_date") == day:
                qty[tr["ticker"]] = qty.get(tr["ticker"], 0.0) + tr["qty"]
            elif tr.get("exit_date") == day:
                qty[tr["ticker"]] = qty.get(tr["ticker"], 0.0) - tr["qty"]
        live = {tk for tk, q in qty.items() if q > 1e-9}
        if k == 0:
            continue                              # nothing is carried into the first book
        checked += 1
        partial += bool(live - opened)            # at least one name carried through
        invested = sum(q * adj[di[day], ti[tk]] for tk, q in qty.items() if q > 1e-9)
        # sleeve=1.00 means the whole account rides the names. Sizing from the freed cash alone
        # left roughly a quarter of it in the park at exactly this moment.
        assert invested == pytest.approx(nav_on[day], rel=0.01), (
            f"{day}: ${invested:,.0f} invested out of ${nav_on[day]:,.0f} — a full sleeve that "
            "parks the difference is not a full sleeve")
    assert checked >= 2 and partial >= 2, (
        f"the fixture needs rebalances that carry names: {checked} books, {partial} partial")


# ------------------------------------------------------------------- the market calendar

def test_the_grid_takes_its_sessions_from_the_market_calendar_not_the_tape():
    """The store carries a couple of dozen junk listings that print on US market holidays. Taking
    the session list from the tape's own union of dates put New Year's Day in the grid; the first
    session of the half-year landed on it, and a rebalance there sold the whole book at its
    carried mark and bought nothing, because buying refuses a stale mark. The account then sat in
    the park until July. Half the window, invisibly."""
    real = sessions(10)
    holiday = dt.date(2024, 1, 1)
    tape = [("REAL.US", d, 10.0, 10.0, 1e6) for d in real]
    tape += [("JUNK.US", holiday, 1.0, 1.0, 5.0)]          # the only thing printing that day
    dates, tickers, adj, raw, dv, _op, _lo = cc.build_grid(tape, set(real))
    assert holiday not in dates, "a day the benchmark did not trade is not a session"
    assert dates == real


def test_a_grid_with_no_calendar_refuses_to_build():
    tape = [("REAL.US", d, 10.0, 10.0, 1e6) for d in sessions(5)]
    with pytest.raises(RuntimeError, match="calendar"):
        cc.build_grid(tape, set())


def test_a_rebalance_whose_rank_comes_up_empty_is_reported_not_swallowed():
    """The exact shape of the January defect: on a day nothing prints, no name clears the $5
    floor, the rank is empty, the whole book is sold and the account sits in the park until the
    next rebalance. It ran four times over nine years and nothing counted it."""
    n = N_DAYS
    paths = {f"N{i:02d}.US": np.linspace(100.0, 130.0 + i, n) for i in range(4)}
    dates, tickers, adj, raw, dv = grid(paths)
    rebals = cc.rebalance_dates(dates, 6, cc.FORMATION + 1)
    adj, raw = adj.copy(), raw.copy()
    adj[rebals[1], :] = np.nan
    raw[rebals[1], :] = np.nan                       # nothing prints: the rank cannot be built
    health = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), n=3, months=6,
                         risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)[3]
    assert dates[rebals[1]].isoformat() in health["empty_rebalances"], (
        "a rebalance that ends holding nothing must be on the record"
    )


def test_a_buy_refused_on_a_stale_mark_is_counted():
    """The other route to the same place: the rank is fine but the name did not print, so the
    buy is refused — correctly, it cannot be filled — and the slice goes unfunded."""
    n = N_DAYS
    paths = {f"N{i:02d}.US": np.linspace(100.0, 130.0 + i, n) for i in range(4)}
    dates, tickers, adj, raw, dv = grid(paths)
    rebals = cc.rebalance_dates(dates, 6, cc.FORMATION + 1)
    adj = adj.copy()
    adj[rebals[1], :] = np.nan                       # the rank still builds off older bars
    health = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), n=3, months=6,
                         risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)[3]
    assert health["stale_skips"] >= 3, "every refused buy is counted"


def test_a_healthy_run_reports_no_empty_rebalances():
    n = N_DAYS
    paths = {f"N{i:02d}.US": np.linspace(100.0, 130.0 + i, n) for i in range(4)}
    dates, tickers, adj, raw, dv = grid(paths)
    health = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), n=3, months=6,
                         risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)[3]
    assert health["empty_rebalances"] == [] and health["stale_skips"] == 0


def test_every_cell_carries_a_param_hash_that_moves_with_its_own_spec():
    """A grid of twenty-odd cells is exactly the search the deflated Sharpe prices. Without a
    param_hash these runs are invisible to `finding.trial_sharpes`, the trial count stays at the
    E-series total, and every cell in the grid is scored as though the grid had not happened."""
    import backtest as bt
    base = dict(variant="x", hypothesis="a4", currency="USD", benchmark="VOO.US",
                start_nav=200_000.0, park="SPMO.US", formation=cc.FORMATION, skip=cc.SKIP)
    hashes = {name: bt.param_digest(dict(spec), base) for name, spec in cc.CELLS.items()}
    assert len(set(hashes.values())) == len(cc.CELLS), (
        "two cells sharing a hash are one trial in the ledger and two experiments in fact")
    # and it moves on the axis that matters: a trail cell must not hash as its untrailed parent
    assert hashes["lg12_semi"] != hashes["lg12_semi_trail"]
    assert hashes["lg12_semi_trail"] != hashes["lg12_semi_trail_vt"]


def test_the_book_still_held_at_the_end_is_closed_on_paper_with_a_real_pnl():
    """A winner the arm is still holding is IN the equity curve's return. If the ledger records it
    with a NULL P&L it is invisible to the jackknife, so the one test that asks 'does this survive
    without its biggest winners' can never reach the biggest winner. It also crashed both
    consumers on float(None)."""
    n = N_DAYS
    paths = {f"N{i:02d}.US": np.linspace(100.0, 200.0 + i, n) for i in range(4)}
    dates, tickers, adj, raw, dv = grid(paths)
    eq, trades, _, _ = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0),
                                   n=3, months=6, risk_adjusted=False, sleeve=1.0,
                                   start_nav=200_000.0)
    closing = [t for t in trades if t.get("reason") == "open_at_end"]
    assert closing, "the book is still held at the end — it must be closed on paper"
    assert all(t["exit_date"] == dates[-1] and t["price"] > 0 for t in closing)
    positions = cc.pair_trades(trades, dates)
    assert not [p for p in positions if p["pnl"] is None], "no position may carry a NULL P&L"
    assert all(p["exit_date"] is not None for p in positions)


def test_the_paper_close_moves_neither_the_equity_path_nor_the_costs():
    """It is bookkeeping. A fee or a mark here would be a trade the arm never made."""
    n = N_DAYS
    paths = {f"N{i:02d}.US": np.linspace(100.0, 200.0 + i, n) for i in range(4)}
    dates, tickers, adj, raw, dv = grid(paths)
    eq, trades, costs, _ = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0),
                                       n=3, months=6, risk_adjusted=False, sleeve=1.0,
                                       start_nav=200_000.0)
    assert eq[-1][0] == dates[-1], "the equity path still ends on the last session"
    spent = sum(t["spend"] for t in trades if "entry_date" in t)
    # costs are the sum of the spreads actually paid; a paper close adds none
    assert costs < spent * 0.01, "the paper close must not charge a spread"


# ------------------------------------------------- WO-A5 §2.1: how a resting stop actually fills

def test_a_stop_inside_the_days_range_fills_at_the_stop():
    assert cc.stop_fill(90.0, op=100.0, lo=85.0) == pytest.approx(90.0)


def test_a_session_that_gaps_through_the_stop_fills_at_the_open_not_the_stop():
    """The case a close-based test cannot see at all, and the one that costs real money."""
    assert cc.stop_fill(90.0, op=72.0, lo=70.0) == pytest.approx(72.0)


def test_a_low_that_never_reaches_the_stop_does_not_fill():
    assert cc.stop_fill(90.0, op=100.0, lo=95.0) is None


def test_an_undecidable_bar_falls_back_rather_than_inventing_a_fill():
    assert cc.stop_fill(90.0, op=np.nan, lo=85.0) is None
    assert cc.stop_fill(90.0, op=100.0, lo=np.nan) is None


def test_intraday_fills_are_never_better_than_the_stop():
    """A stop-market order cannot execute above its trigger. Any model that lets it is inventing
    money on exactly the trades that hurt."""
    for op, lo in ((100.0, 85.0), (72.0, 70.0), (90.0, 88.0), (89.9, 60.0)):
        f = cc.stop_fill(90.0, op=op, lo=lo)
        if f is not None:
            assert f <= 90.0 + 1e-9, f"filled at {f} on a stop of 90 (open {op}, low {lo})"


def test_the_ladder_probes_vary_only_the_bands_and_the_defaults_are_the_plans():
    """§3.2's four numbers are the law. A probe may move them to map the surface; the DEFAULTS
    must stay exactly what the plan says, or the ladder has quietly become the strategy."""
    assert cc.TRAIL_DEFAULTS == dict(initial=0.08, arm=0.15, wide=0.10, euphoria=0.05)
    champ = cc.CELLS["lg8_semi_trail"]
    assert "trail_cfg" not in champ, "the champion runs the plan's own numbers, unparameterised"
    for name, spec in cc.CELLS.items():
        if not name.startswith("lad_") or "trail_cfg" not in spec:
            continue
        moved = {k for k, v in spec["trail_cfg"].items() if v != cc.TRAIL_DEFAULTS[k]}
        assert len(moved) == 1, f"{name} moves {moved} — one band at a time"


def test_a_cost_multiplier_scales_every_fee_and_does_not_leak():
    base = cc.spread_frac(1e9)
    cc.COST_MULT = 4.0
    try:
        assert cc.spread_frac(1e9) == pytest.approx(base * 4)
        assert cc.spread_frac(1.0) == pytest.approx(
            cc.SPREAD_CURVE[-1][1] / 10_000.0 * 4)
    finally:
        cc.COST_MULT = 1.0
    assert cc.spread_frac(1e9) == pytest.approx(base), "the dial must reset"


def test_the_intraday_model_sells_on_a_gap_the_close_model_rides_down():
    """End to end: a name that gaps far below its stop and stays there. The close-based model
    cannot fill until the next close; the broker model fills at the open it gapped to."""
    n = N_DAYS
    path = np.concatenate([np.linspace(100.0, 300.0, n - 80), np.full(80, 120.0)])
    paths = {"GAP.US": path}
    for i in range(5):
        paths[f"N{i:02d}.US"] = np.linspace(100.0, 130.0 + i, n)
    dates, tickers, adj, raw, dv = grid(paths)
    park = np.full(n, 100.0)
    j = tickers.index("GAP.US")
    op, lo = adj.copy(), adj.copy()
    gap = n - 80
    op[gap, j], lo[gap, j] = 118.0, 115.0        # the session opens far through the trail
    kw = dict(n=3, months=6, risk_adjusted=False, sleeve=1.0, start_nav=200_000.0, trail=True)
    closed = cc.simulate(dates, tickers, adj, raw, dv, park, **kw)[1]
    intra = cc.simulate(dates, tickers, adj, raw, dv, park, intraday=(op, lo), **kw)[1]
    c_stop = next(t for t in closed if t.get("reason") == "trail_stop" and t["ticker"] == "GAP.US")
    i_stop = next(t for t in intra if t.get("reason") == "trail_stop" and t["ticker"] == "GAP.US")
    assert i_stop["exit_date"] <= c_stop["exit_date"], "the broker order cannot fill later"
    assert i_stop["price"] == pytest.approx(118.0), "it fills at the open it gapped to"


def test_a_position_cannot_be_stopped_on_the_session_it_was_bought():
    """Entry fills at the CLOSE, so that session's own open and low printed while the account was
    still in cash. Testing the resting stop against them stops a name out at a price it traded at
    before the position existed — a backwards look-ahead that reads as a devastating result.

    Measured when it was live: ENPH bought 2020-01-02 was 'stopped' on 2020-01-02 at -10.1%, and
    MRNA bought 2020-07-01 on 2020-07-02, each surrendering a move the close-based model kept.
    """
    n = N_DAYS
    # every name's session has a low far below its close, so any same-session test fires at once
    paths = {f"N{i:02d}.US": np.linspace(100.0, 300.0 + i, n) for i in range(5)}
    dates, tickers, adj, raw, dv = grid(paths)
    op, lo = adj.copy(), adj * 0.5          # every session's low is half its close
    trades = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), n=3, months=6,
                         risk_adjusted=False, sleeve=1.0, start_nav=200_000.0,
                         trail=True, intraday=(op, lo))[1]
    entries = {(t["ticker"], t["entry_date"]) for t in trades if "entry_date" in t}
    same_day = [t for t in trades if t.get("reason") == "trail_stop"
                and (t["ticker"], t["exit_date"]) in entries]
    assert not same_day, f"{len(same_day)} names stopped on their own entry session"


def test_the_ladder_moves_the_initial_stop_that_is_actually_set():
    """`lad_init6` and `lad_init10` vary §3.2's initial stop. If the stop set at entry is hard-
    wired to the module constant, those probes vary nothing and the ladder reports a plateau it
    never tested."""
    n = N_DAYS
    paths = {}
    for i in range(4):
        path = np.linspace(100.0, 130.0 + i, n)
        # a 20% dip just after the first rebalance, then recovery: a 2% initial stop must exit
        # into it and a 40% one must ride through, so the two cannot agree
        path[cc.FORMATION + 5:cc.FORMATION + 25] *= 0.80
        paths[f"N{i:02d}.US"] = path
    dates, tickers, adj, raw, dv = grid(paths)
    kw = dict(n=3, months=6, risk_adjusted=False, sleeve=1.0, start_nav=200_000.0, trail=True)
    tight = dict(initial=0.02, arm=0.15, wide=0.10, euphoria=0.05)
    loose = dict(initial=0.40, arm=0.15, wide=0.10, euphoria=0.05)
    a = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), trail_cfg=tight, **kw)[0]
    b = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), trail_cfg=loose, **kw)[0]
    assert a[-1][1] != b[-1][1], "a 2% initial stop and a 40% one cannot produce one number"


def test_the_next_open_model_fills_at_the_open_after_the_close_that_broke_the_stop():
    """The third execution path: trigger judged on the close, order placed that night, filled at
    the next open. Neither the same-session intraday fill nor the next CLOSE."""
    n = N_DAYS
    path = np.concatenate([np.linspace(100.0, 300.0, n - 80), np.full(80, 200.0)])
    paths = {"DROP.US": path}
    for i in range(5):
        paths[f"N{i:02d}.US"] = np.linspace(100.0, 130.0 + i, n)
    dates, tickers, adj, raw, dv = grid(paths)
    op = adj.copy()
    j = tickers.index("DROP.US")
    op[:, j] = adj[:, j] * 0.97                  # every open sits 3% under its own close
    kw = dict(n=3, months=6, risk_adjusted=False, sleeve=1.0, start_nav=200_000.0, trail=True)
    closes = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), **kw)[1]
    opens = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), next_open=op, **kw)[1]
    c = next(t for t in closes if t.get("reason") == "trail_stop" and t["ticker"] == "DROP.US")
    o = next(t for t in opens if t.get("reason") == "trail_stop" and t["ticker"] == "DROP.US")
    assert o["exit_date"] == c["exit_date"], "same trigger session — only the fill price differs"
    assert o["price"] == pytest.approx(c["price"] * 0.97), "filled at that session's open"


# --------------------------------------------------------------- the loose sector cap

def test_without_a_cap_the_book_is_whatever_the_rank_says():
    ranked = list(range(20))
    sectors = ["Tech"] * 20
    assert cc.pick_book(ranked, 8, sectors, None) == list(range(8))
    assert cc.pick_book(ranked, 8, None, 0.7) == list(range(8))


def test_a_seventy_percent_cap_lets_five_of_eight_ride_one_sector():
    """Zak's ruling: go hard on a theme, but not the whole book. At eight names 0.7 is five."""
    ranked = list(range(20))
    sectors = ["Tech"] * 10 + ["Gold"] * 10
    book = cc.pick_book(ranked, 8, sectors, 0.70)
    assert len(book) == 8, "the slot passes to the next eligible name — the book stays n deep"
    assert sum(1 for j in book if sectors[j] == "Tech") == 5
    assert book[:5] == [0, 1, 2, 3, 4], "the five it keeps are the five highest-ranked"


def test_the_cap_would_have_trimmed_the_july_2026_book():
    """That book was seven of eight Technology and every name stopped inside three days."""
    july = ["Technology"] * 7 + ["Industrials"]        # MU SNDK WDC STX LITE CIEN AXTI + BE
    ranked = list(range(len(july) + 6))
    sectors = july + ["Healthcare", "Energy", "Utilities", "Gold", "Gold", "Healthcare"]
    book = cc.pick_book(ranked, 8, sectors, 0.70)
    assert sum(1 for j in book if sectors[j] == "Technology") == 5
    assert len(book) == 8


def test_an_unlabelled_name_is_its_own_bucket_not_a_free_pass():
    """95.7% of the census carries a sector. The rest must not all pile into one book unchecked
    OR be excluded — they share the '?' bucket, which caps them like any other."""
    ranked = list(range(20))
    sectors = [None] * 20
    book = cc.pick_book(ranked, 8, sectors, 0.70)
    assert len(book) == 5, "unlabelled names share one bucket and hit the same ceiling"
