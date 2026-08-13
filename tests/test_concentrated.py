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
    eq, _, _ = cc.simulate(dates, tickers, adj, raw, dv, park, n=3, months=6,
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
    _, ungated, _ = cc.simulate(dates, tickers, adj, raw, dv, park, n=3, months=6,
                                risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)
    _, gated, _ = cc.simulate(dates, tickers, adj, raw, dv, park, n=3, months=6,
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
    eq, trades, _ = cc.simulate(dates, tickers, adj, raw, dv, park, n=3, months=6,
                                risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)
    nav_on = {d: v for d, v, _ in eq}
    ti, di = {t: j for j, t in enumerate(tickers)}, {d: i for i, d in enumerate(dates)}
    rebals = sorted({t.get("entry_date") or t["exit_date"] for t in trades})
    qty, checked, partial = {}, 0, 0
    for k, day in enumerate(rebals):
        opened = {t["ticker"] for t in trades if t.get("entry_date") == day}
        for tr in trades:
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
