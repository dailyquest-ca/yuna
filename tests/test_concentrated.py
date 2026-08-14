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
    assert all(v > 0 for _, v, *_ in eq)


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
    "ph_semi_0": "lg8_trail_nextopen", "ph_semi_1": "ph_semi_0", "ph_semi_2": "ph_semi_0",
    "ph_semi_3": "ph_semi_0", "ph_semi_4": "ph_semi_0", "ph_semi_5": "ph_semi_0",
    "ph_qtr_1": "clk_quarter", "ph_qtr_2": "clk_quarter",
    "evt_hi8": "lg8_trail_nextopen", "evt_hi6": "evt_hi8", "evt_hi12": "evt_hi8",
    "evt_hi8_sec70": "evt_hi8", "evt_hi8_s1": "evt_hi8", "evt_hi8_s2": "evt_hi8",
    "evt_hi8_s3": "evt_hi8", "evt_hi8_s4": "evt_hi8",
    "mo_s1": "clk_monthly", "mo_s2": "clk_monthly", "mo_s3": "clk_monthly",
    "mo_s4": "clk_monthly",
    "bi_s1": "clk_bimonthly", "bi_s2": "clk_bimonthly", "bi_s3": "clk_bimonthly",
    "fq_d1": "clk_monthly", "fq_d1_s1": "fq_d1",
    "fq_w1": "fq_d1", "fq_w1_s1": "fq_w1", "fq_w1_s2": "fq_w1",
    "fq_f2": "fq_d1", "fq_f2_s1": "fq_f2", "fq_f2_s2": "fq_f2",
    "bi_ph1": "clk_bimonthly", "s42_p0": "clk_bimonthly",
    "s42_p7": "s42_p0", "s42_p14": "s42_p0", "s42_p21": "s42_p0",
    "s42_p28": "s42_p0", "s42_p35": "s42_p0",
    "s21_p0": "clk_monthly", "s21_p3": "s21_p0", "s21_p7": "s21_p0", "s21_p10": "s21_p0",
    "s21_p14": "s21_p0", "s21_p17": "s21_p0",
    "s5_p1": "fq_w1", "s5_p2": "fq_w1", "s5_p3": "fq_w1", "s5_p4": "fq_w1",
    "a6": "lg12_trail_nextopen", "a6_s10": "a6", "a6_s21": "a6", "a6_s42": "a6", "a6_s63": "a6",
    "a6_lag1": "a6", "a6_lag2": "a6", "a6_lag5": "a6",
    "a6_floor4": "a6", "a6_floor0": "a6",
    "a6f0_s21": "a6_floor0", "a6f0_s42": "a6_floor0", "a6f0_s63": "a6_floor0",
    "a6f0_lag1": "a6_floor0", "a6f0_lag5": "a6_floor0",
    # WO-A6 §2's rider priced, and §3's sensitivity grid — every one of them one axis off the
    # centre, which is the whole reason this tree exists.
    "a6f0_norider": "a6_floor0",
    "a6f0_x25": "a6_floor0", "a6f0_x60": "a6_floor0",
    "a6f0_n10": "a6_floor0", "a6f0_n15": "a6_floor0",
    "a6f0_atr": "a6_floor0", "a6f0_noeuph": "a6_floor0",
    "a6f0_path": "a6_floor0",
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
    nav = np.array([v for _, v, *_ in eq])
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
    nav_on = {d: v for d, v, *_ in eq}
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
    dates, tickers, adj, raw, dv, _op, _lo, _hi = cc.build_grid(tape, set(real))
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


# --------------------------------------------------------- the phase test's own arithmetic

def test_the_offset_shifts_the_calendar_by_whole_months():
    """The first session always opens a period — the walk has to start somewhere — so the offset
    is read off the STEADY-STATE cadence after it."""
    dates = sessions(1300, start=dt.date(2020, 1, 1))
    a = [dates[i].month for i in cc.rebalance_dates(dates, 6, 0, offset=0)]
    b = [dates[i].month for i in cc.rebalance_dates(dates, 6, 0, offset=1)]
    c = [dates[i].month for i in cc.rebalance_dates(dates, 6, 0, offset=2)]
    assert a[:4] == [1, 7, 1, 7], f"offset 0 is Jan/Jul, got {a[:4]}"
    assert b[1:5] == [2, 8, 2, 8], f"offset 1 must settle on Feb/Aug, got {b[1:5]}"
    assert c[1:5] == [3, 9, 3, 9], f"offset 2 must settle on Mar/Sep, got {c[1:5]}"


def test_the_periods_stay_contiguous_across_a_year_boundary():
    """The old (year, month // n) bucket restarts every January, so any non-zero offset would
    produce a SHORT period every December — an extra rebalance the phase test would then read as
    a difference between phases rather than a bug in the phase test."""
    dates = sessions(1300, start=dt.date(2020, 1, 1))
    for off in range(6):
        idx = cc.rebalance_dates(dates, 6, 0, offset=off)[1:]     # skip the partial first period
        months = [dates[i].month for i in idx]
        gaps = {(b - a) % 12 for a, b in zip(months, months[1:])}
        assert gaps == {6}, f"offset {off} gave period lengths {gaps}, expected every gap to be 6"


def test_offset_zero_reproduces_the_original_calendar():
    dates = sessions(1300, start=dt.date(2020, 1, 1))
    for months in (1, 2, 3, 6, 12):
        old, seen = [], set()
        for i, d in enumerate(dates):
            key = (d.year, (d.month - 1) // months)
            if key not in seen:
                seen.add(key)
                old.append(i)
        assert cc.rebalance_dates(dates, months, 0, offset=0) == old, months


# ------------------------------------------------ WO-A6: the door that replaces the calendar

def test_a_new_high_reads_only_prior_sessions():
    """Strictly prior — comparing today against a window that includes today makes every session
    a new high, which would turn the door into no door at all."""
    n = 400
    adj = np.linspace(100.0, 200.0, n).reshape(-1, 1)
    assert cc.at_new_high(n - 1, 0, adj, window=252)
    flat = np.full((n, 1), 100.0)
    assert not cc.at_new_high(n - 1, 0, flat, window=252), "equal is not above"


def test_the_door_stays_shut_without_enough_history():
    adj = np.linspace(100.0, 200.0, 300).reshape(-1, 1)
    assert not cc.at_new_high(100, 0, adj, window=252), "a door that cannot be evaluated is shut"


def test_a_name_below_its_year_high_cannot_enter():
    n = 400
    path = np.concatenate([np.linspace(100.0, 300.0, 300), np.linspace(300.0, 200.0, 100)])
    adj = path.reshape(-1, 1)
    assert not cc.at_new_high(n - 1, 0, adj, window=252)


def test_the_door_prevents_re_buying_a_name_that_just_stopped_out():
    """The churn fix, and the reason this door was chosen over a tuned cooldown. On the monthly
    calendar the book re-bought a name within 45 days of a LOSING stop-out 213 times and 111 of
    those lost again. A stopped-out name is by construction below its recent high, so it cannot
    come back until it has climbed to a new one."""
    n = N_DAYS
    # one name climbs, breaks, and drifts sideways well under its old high; the others are flat
    broken = np.concatenate([np.linspace(100.0, 300.0, n - 200),
                             np.linspace(300.0, 180.0, 40),
                             np.full(160, 185.0)])
    paths = {"BROKE.US": broken}
    for i in range(4):
        paths[f"N{i:02d}.US"] = np.full(n, 100.0 + i)
    dates, tickers, adj, raw, dv = grid(paths)
    trades = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), n=3, months=6,
                         risk_adjusted=False, sleeve=1.0, start_nav=200_000.0,
                         trail=True, entry_rule="new_high")[1]
    legs = [t for t in trades if t["ticker"] == "BROKE.US"]
    stops = [t for t in legs if t.get("reason") == "trail_stop"]
    assert stops, "the fixture must actually stop the name out"
    after = [t for t in legs if "entry_date" in t and t["entry_date"] > stops[0]["exit_date"]]
    assert not after, f"re-bought {len(after)} times while still below its old high"


def test_the_event_book_holds_no_calendar():
    """No rebalance dates exist in this mode: every entry is a session a name printed a new high,
    and those are scattered rather than clustered on period boundaries."""
    n = N_DAYS
    rng = np.random.default_rng(3)
    paths = {f"N{i:02d}.US": 100.0 * np.exp(np.cumsum(rng.normal(0.0007, 0.02, n)))
             for i in range(8)}
    dates, tickers, adj, raw, dv = grid(paths)
    trades = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), n=3, months=6,
                         risk_adjusted=False, sleeve=1.0, start_nav=200_000.0,
                         trail=True, entry_rule="new_high")[1]
    entry_days = sorted({t["entry_date"] for t in trades if "entry_date" in t})
    assert len(entry_days) > 4, "the door must actually open more than a calendar would"
    firsts = sum(1 for d in entry_days if d.day <= 3)
    assert firsts < len(entry_days), "entries clustered on month starts would mean a calendar"


def test_the_start_offset_delays_the_first_entry():
    """The phase analogue. An event rule has no calendar to shift, so the arbitrary choice being
    tested is when you started watching."""
    n = N_DAYS
    paths = {f"N{i:02d}.US": 100.0 * np.exp(np.linspace(0, 0.9 + 0.02 * i, n)) for i in range(5)}
    dates, tickers, adj, raw, dv = grid(paths)
    kw = dict(n=3, months=6, risk_adjusted=False, sleeve=1.0, start_nav=200_000.0,
              trail=True, entry_rule="new_high")
    a = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), **kw)[1]
    b = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), start_offset=3, **kw)[1]
    first_a = min(t["entry_date"] for t in a if "entry_date" in t)
    first_b = min(t["entry_date"] for t in b if "entry_date" in t)
    assert first_b > first_a, "a three-month offset must delay the first purchase"
    assert (first_b - first_a).days >= 80


def test_the_sector_cap_counts_names_already_held():
    """In event mode slots fill one at a time, so a cap that ignores the current book would let a
    sector accumulate a name at a time up to the whole book."""
    ranked = [10, 11, 12, 13]
    sectors = {10: "Tech", 11: "Tech", 12: "Gold", 13: "Gold"}
    secs = [None] * 14
    for k, v in sectors.items():
        secs[k] = v
    take = cc.pick_book(ranked, 2, secs, 0.70, held_sectors={"Tech": 5})
    assert all(secs[j] != "Tech" for j in take), "Tech is already full and must be skipped"


# ------------------------------------------------- the frequency axis, past calendar months

def test_a_session_schedule_hits_every_nth_session():
    dates = sessions(60)
    assert cc.session_rebalances(dates, 1, 0) == list(range(60)), "daily is every session"
    assert cc.session_rebalances(dates, 5, 0)[:4] == [0, 5, 10, 15]
    assert cc.session_rebalances(dates, 10, 10)[:3] == [10, 20, 30], "nothing before the warmup"


def test_the_session_offset_shifts_the_whole_schedule():
    dates = sessions(60)
    assert cc.session_rebalances(dates, 5, 0, offset=2)[:3] == [2, 7, 12]


def test_a_daily_schedule_has_no_offset_left_to_shift():
    """At every=1 every session is a rebalance, so the only thing an offset can do is start a day
    later. A daily book has no date luck available to it — that is the point of measuring it."""
    dates = sessions(60)
    a = cc.session_rebalances(dates, 1, 0, offset=0)
    b = cc.session_rebalances(dates, 1, 0, offset=1)
    assert a[1:] == b, "shifting a daily schedule can only drop its first session"


def test_a_zero_interval_is_not_a_schedule():
    with pytest.raises(ValueError, match="not a schedule"):
        cc.session_rebalances(sessions(10), 0, 0)


def test_daily_rebalancing_costs_more_than_monthly_on_the_same_tape():
    """The mechanism that decides this axis: turnover. Whatever daily does to return, it cannot
    do it for free, and a run where it did would mean the spread curve was not being charged."""
    n = N_DAYS
    rng = np.random.default_rng(11)
    paths = {f"N{i:02d}.US": 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n)))
             for i in range(12)}
    dates, tickers, adj, raw, dv = grid(paths)
    kw = dict(n=3, months=1, risk_adjusted=False, sleeve=1.0, start_nav=200_000.0, trail=True)
    daily = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0),
                        every_sessions=1, **kw)[2]
    monthly = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0),
                          every_sessions=21, **kw)[2]
    assert daily > monthly, f"daily costs ${daily:,.0f} against monthly's ${monthly:,.0f}"


def test_a_two_month_bucket_has_exactly_two_month_phases():
    """Why the calendar phase test on bi-monthly is thin, and why the 42-session clock exists.
    Shifting a two-month bucket by two months lands back where it started."""
    dates = sessions(1300, start=dt.date(2020, 1, 1))
    phases = {}
    for off in range(4):
        idx = cc.rebalance_dates(dates, 2, 0, offset=off)[1:]
        phases[off] = tuple(dates[i].month for i in idx[:6])
    assert phases[0] == phases[2], "offset 2 is offset 0 on a two-month clock"
    assert phases[1] == phases[3]
    assert phases[0] != phases[1], "and there are exactly two distinct phases"


def test_a_forty_two_session_clock_carries_forty_two_phases():
    """The honest phase test for a ~2-month cadence: same interval, every distinct start."""
    dates = sessions(600)
    seen = {tuple(cc.session_rebalances(dates, 42, 0, offset=o)[:3]) for o in range(42)}
    assert len(seen) == 42, "every session offset must give a distinct schedule"


# ------------------------------------- WO-A6 Q1: the deployed fraction must be measured

def test_the_equity_row_reports_the_real_deployed_fraction_not_the_declared_sleeve():
    """Writing the cell's declared `sleeve` and `n` into these columns made "how much of this
    return belongs to the park" unanswerable — and a book that is mostly in SPMO is mostly
    reporting SPMO. The columns now carry what was actually held."""
    n = N_DAYS
    # a name that stops out early and is never replaced: the book must show itself emptying
    crash = np.concatenate([np.linspace(100.0, 300.0, n - 300), np.linspace(300.0, 40.0, 300)])
    paths = {"CRASH.US": crash}
    for i in range(3):
        paths[f"N{i:02d}.US"] = np.linspace(100.0, 105.0 + i, n)
    dates, tickers, adj, raw, dv = grid(paths)
    eq = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), n=2, months=6,
                     risk_adjusted=False, sleeve=1.0, start_nav=200_000.0, trail=True)[0]
    deployed = [row[3] for row in eq]
    counts = [row[4] for row in eq]
    assert len(eq[0]) == 5, "each row carries date, nav, park mark, deployed fraction, positions"
    assert all(0.0 <= d <= 1.0001 for d in deployed), "a fraction of NAV, not a spec constant"
    assert max(counts) <= 2, "never more positions than the book allows"
    assert min(counts) < max(counts), "the count must move — it is a measurement, not a label"


def test_a_fully_parked_book_reports_zero_deployed():
    n = N_DAYS
    # nothing clears the $5 floor, so no name is ever bought and everything sits in the park
    paths = {f"N{i:02d}.US": np.full(n, 1.0 + 0.01 * i) for i in range(4)}
    dates, tickers, adj, raw, dv = grid(paths)
    eq = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), n=2, months=6,
                     risk_adjusted=False, sleeve=1.0, start_nav=200_000.0)[0]
    assert all(row[3] == 0.0 and row[4] == 0 for row in eq)


# ============================ WO-A6: the banded continuous book ============================

def test_the_base_state_needs_all_three_conditions():
    """Near its highs AND above its 50-day AND that 50-day rising. Any one alone is not a state."""
    n = 400
    rising = np.linspace(100.0, 200.0, n).reshape(-1, 1)
    assert cc.base_state(n - 1, 0, rising)
    # 25% off the high fails the proximity clause even though the trend is up
    faded = np.concatenate([np.linspace(100.0, 200.0, n - 30),
                            np.linspace(200.0, 150.0, 30)]).reshape(-1, 1)
    assert not cc.base_state(n - 1, 0, faded)
    # right at the highs but the 50-day is rolling over
    rolling = np.concatenate([np.linspace(100.0, 200.0, n - 60),
                              np.full(60, 199.0)]).reshape(-1, 1)
    assert not cc.base_state(n - 1, 0, rolling), "a flat 50-day is not a rising one"


def test_the_base_state_reads_no_future_bar():
    n = 400
    adj = np.linspace(100.0, 200.0, n).reshape(-1, 1)
    a2 = adj.copy()
    a2[300:] = 1.0
    assert cc.base_state(280, 0, adj) == cc.base_state(280, 0, a2)


def test_effective_bets_matches_the_plans_worked_example():
    """§2.2 states it: four equal names at 0.85 correlation give 1.1 bets."""
    c = np.full((4, 4), 0.85)
    np.fill_diagonal(c, 1.0)
    assert cc.effective_bets(c) == pytest.approx(1.1, abs=0.05)
    assert cc.effective_bets(np.eye(6)) == pytest.approx(6.0), "independent names are n bets"


def test_single_linkage_merges_through_a_chain():
    """Pre-registered as single-linkage precisely because it merges readily — a rider meant to
    stop a 1.84-bet book should err toward calling names related."""
    c = np.eye(3)
    c[0, 1] = c[1, 0] = 0.8
    c[1, 2] = c[2, 1] = 0.8      # 0 and 2 are uncorrelated but chained through 1
    assert max(cc.clusters_at(c).values()) == 3


def test_the_rider_blocks_a_third_name_from_one_cluster():
    n = 300
    rng = np.random.default_rng(5)
    base = rng.normal(0, 0.02, n)
    adj = np.column_stack([100 * np.exp(np.cumsum(base + rng.normal(0, 0.002, n)))
                           for _ in range(3)]                       # three near-identical names
                          + [100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))])
    ok, why = cc.rider_ok(n - 1, [0, 1], adj)
    assert ok, "two from a cluster is allowed"
    ok, why = cc.rider_ok(n - 1, [0, 1, 2], adj)
    assert not ok and why == "cluster cap", f"three should be blocked, got {why}"


def test_the_effective_bets_floor_only_binds_once_it_could_be_met():
    """Stated interpretation: a three-name book cannot have five effective bets under any
    correlation structure, so a literal floor would refuse every entry and the book would never
    fill. Below five names only the cluster cap binds."""
    n = 300
    rng = np.random.default_rng(9)
    adj = np.column_stack([100 * np.exp(np.cumsum(rng.normal(0, 0.02, n))) for _ in range(4)])
    ok, _ = cc.rider_ok(n - 1, [0, 1, 2], adj)
    assert ok, "four-name-or-fewer books are not held to a five-bet floor"


def test_the_rider_abstains_rather_than_blocking_when_it_cannot_measure():
    n = 300
    adj = np.full((n, 2), np.nan)
    adj[:, 0] = np.linspace(100, 200, n)
    ok, why = cc.rider_ok(n - 1, [0, 1], adj)
    assert ok and "unmeasurable" in why


def test_the_rank_band_holds_through_flicker_and_sells_on_travel():
    """The whole point of 15/40: a name drifting between them generates no trades at all."""
    n = N_DAYS
    # twelve climbers; one decays hard enough late to fall past rank 40 in a wide pool
    paths = {f"N{i:02d}.US": 100.0 * np.exp(np.linspace(0, 0.9 - 0.01 * i, n)) for i in range(60)}
    paths["FALLER.US"] = np.concatenate([100.0 * np.exp(np.linspace(0, 1.2, n - 260)),
                                         100.0 * np.exp(1.2) * np.linspace(1.0, 0.45, 260)])
    dates, tickers, adj, raw, dv = grid(paths)
    trades = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), n=12, months=6,
                         risk_adjusted=False, sleeve=1.0, start_nav=200_000.0,
                         trail=True, entry_rule="banded")[1]
    assert [t for t in trades if "entry_date" in t], "the door must open at all"
    entries = {t["ticker"] for t in trades if "entry_date" in t}
    assert "FALLER.US" in entries, "it was the strongest name for most of the window"


def test_the_banded_book_never_exceeds_its_slot_count():
    n = N_DAYS
    paths = {f"N{i:02d}.US": 100.0 * np.exp(np.linspace(0, 0.9 - 0.005 * i, n)) for i in range(40)}
    dates, tickers, adj, raw, dv = grid(paths)
    eq = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), n=12, months=6,
                     risk_adjusted=False, sleeve=1.0, start_nav=200_000.0,
                     trail=True, entry_rule="banded")[0]
    assert max(row[4] for row in eq) <= 12


def test_the_rank_lag_changes_which_observation_the_rule_acts_on():
    """The second falsifier. A start offset only moves where the walk begins; this moves the
    observation the rule reads, every session."""
    n = N_DAYS
    rng = np.random.default_rng(21)
    paths = {f"N{i:02d}.US": 100.0 * np.exp(np.cumsum(rng.normal(0.0006, 0.02, n)))
             for i in range(40)}
    dates, tickers, adj, raw, dv = grid(paths)
    kw = dict(n=12, months=6, risk_adjusted=False, sleeve=1.0, start_nav=200_000.0,
              trail=True, entry_rule="banded")
    a = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), **kw)[0]
    b = cc.simulate(dates, tickers, adj, raw, dv, np.full(n, 100.0), rank_lag=5, **kw)[0]
    assert a[-1][1] != b[-1][1], "a five-session lag must produce a different book"


def test_a_five_bet_floor_makes_the_fifth_name_arithmetically_impossible():
    """The defect this diagnostic exists for. Effective bets on k equal-weight names cannot
    exceed k, so requiring 5 from a 5-name book demands ZERO correlation between all of them —
    unreachable in equities, which share a market factor. The book caps at four names forever."""
    assert cc.effective_bets(np.eye(5)) == pytest.approx(5.0), "5 is the ceiling at k=5"
    c = np.eye(5)
    c[c == 0] = 0.05                              # a whisper of correlation
    np.fill_diagonal(c, 1.0)
    assert cc.effective_bets(c) < 5.0, "any positive correlation puts a 5-name book under 5"


def test_the_floor_is_overridable_so_the_ruling_can_rest_on_measurements():
    n = 300
    rng = np.random.default_rng(4)
    # a shared market factor, which is what makes the floor unreachable in real equities
    mkt = rng.normal(0, 0.012, n)
    adj = np.column_stack([100 * np.exp(np.cumsum(mkt + rng.normal(0, 0.016, n)))
                           for _ in range(5)])
    bets = cc.effective_bets(cc.return_corr(n - 1, [0, 1, 2, 3, 4], adj))
    assert bets < 5.0, f"a book with a market factor cannot reach 5 bets at k=5 (got {bets:.2f})"
    blocked, why = cc.rider_ok(n - 1, [0, 1, 2, 3, 4], adj, floor=5.0)
    allowed, _ = cc.rider_ok(n - 1, [0, 1, 2, 3, 4], adj, floor=0.0)
    assert not blocked and why == "effective bets below floor"
    assert allowed, "floor 0 disables the clause and leaves the cluster cap in charge"


# ---------------------------------------------------------------------------------------------
# WO-A6 §3's sensitivity machinery. Every one of these axes is a knob that a cell claims to turn,
# and the `lad_init10` lesson is that a knob wired to nothing produces a cell that varies nothing
# and reports a "robust" result. The last three tests here exist to prove each knob MOVES.


def test_atr_is_true_range_and_counts_the_gap_terms():
    """TR = max(high-low, |high - prev close|, |prev close - low|). The two gap terms are the
    reason to use ATR rather than the bar's own range: a name that gaps 20% and then trades a
    quiet session has NOT had a quiet session."""
    n = 30
    adj = np.full((n, 1), 100.0)
    hi = np.full((n, 1), 101.0)
    lo = np.full((n, 1), 99.0)
    assert cc.atr(n - 1, 0, hi, lo, adj, 20) == pytest.approx(2.0), "no gaps: TR is the bar range"

    # one session gaps: prev close 100, bar trades 120-121. Range is 1, but the gap term is 21.
    hi2, lo2 = hi.copy(), lo.copy()
    hi2[n - 1, 0], lo2[n - 1, 0] = 121.0, 120.0
    got = cc.atr(n - 1, 0, hi2, lo2, adj, 20)
    assert got == pytest.approx((2.0 * 19 + 21.0) / 20), "the gap enters the average, not the range"


def test_atr_refuses_an_incomplete_window_rather_than_averaging_what_is_there():
    """A stop sized off four bars of a twenty-bar window is a number with a spurious precision.
    None makes the caller fall back to a rule it can state; a partial mean does not."""
    n = 30
    adj, hi, lo = np.full((n, 1), 100.0), np.full((n, 1), 101.0), np.full((n, 1), 99.0)
    hi[n - 5:, 0] = np.nan
    assert cc.atr(n - 1, 0, hi, lo, adj, 20) is None
    assert cc.atr(5, 0, np.full((n, 1), 101.0), lo, adj, 20) is None, "not enough history yet"
    assert cc.atr(n - 1, 0, None, lo, adj, 20) is None, "no highs loaded at all"


def test_the_atr_trail_arms_at_one_r_and_then_rides_the_chandelier():
    """WO-A6 §3: '3xATR(20) initial, +1R arm, 8xATR(22) Chandelier.' R is the INITIAL risk and is
    fixed at entry; the Chandelier reads today's ATR."""
    cfg = cc.TRAIL_ATR
    st = dict(entry=100.0, hi=100.0, stop=94.0, armed=False, atr_init=2.0)
    assert cc.trail_stop_atr(101.0, st, cfg) == pytest.approx(94.0), "3xATR(20) = 6 below entry"
    assert not st["armed"], "+1R is +2.0 here — 101 has not reached it"

    st = dict(entry=100.0, hi=102.0, stop=94.0, armed=False, atr_init=2.0, atr_chand=1.0)
    assert st and cc.trail_stop_atr(102.0, st, cfg) == pytest.approx(94.0)
    assert st["armed"], "+1R reached: 102 >= 100 + 1 x 2.0"
    # armed, so the Chandelier applies: high 102 minus 8 x ATR(22)=1.0 is 94, which ties the
    # initial. Push the high up and it takes over.
    st["hi"] = 110.0
    assert cc.trail_stop_atr(110.0, st, cfg) == pytest.approx(102.0)


def test_the_atr_trail_ratchets_and_never_widens():
    """Same clause §3.2 carries for the percentage trail: the stop moves up, never down. A falling
    ATR must not be able to give a losing position more room."""
    cfg = cc.TRAIL_ATR
    st = dict(entry=100.0, hi=120.0, stop=110.0, armed=True, atr_init=2.0, atr_chand=1.0)
    # The ratchet lives in the CALLER's assignment, exactly as it does for the percentage trail:
    # both functions return the stop and neither writes it. A caller that forgets this line has a
    # trail that recomputes from scratch every session, which is silent and would not throw.
    st["stop"] = cc.trail_stop_atr(120.0, st, cfg)
    assert st["stop"] == pytest.approx(112.0)
    st["atr_chand"] = 4.0                      # volatility quadruples
    assert cc.trail_stop_atr(115.0, st, cfg) == pytest.approx(112.0), (
        "a wider Chandelier cannot lower a stop that already ratcheted to 112")


def test_open_state_stamps_r_at_entry_and_falls_back_when_atr_is_unmeasurable():
    n = 40
    adj, hi, lo = np.full((n, 1), 100.0), np.full((n, 1), 102.0), np.full((n, 1), 98.0)
    st = cc.open_state(100.0, n - 1, 0, cc.TRAIL_ATR, (hi, lo), adj)
    assert st["atr_init"] == pytest.approx(4.0)
    assert st["stop"] == pytest.approx(88.0), "entry - 3 x ATR(20)"

    # no bars at all: the name still enters, on §3.2's own 8% initial rather than with no stop
    bare = cc.open_state(100.0, n - 1, 0, cc.TRAIL_ATR, None, adj)
    assert "atr_init" not in bare
    assert bare["stop"] == pytest.approx(92.0)

    # and the default path is untouched by any of this
    plain = cc.open_state(100.0, n - 1, 0, None, (hi, lo), adj)
    assert plain["stop"] == pytest.approx(92.0) and "atr_init" not in plain


def test_path_quality_is_the_share_of_up_days_and_the_gate_is_relative():
    """A6-F carries no invented threshold: the bar is the pool's own median, so it moves with
    whatever the market is offering instead of asserting a level."""
    n = 300
    grind = 100.0 * np.cumprod(np.where(np.arange(n) % 4 == 0, 0.99, 1.006))   # up 3 of 4
    lumpy = 100.0 * np.cumprod(np.where(np.arange(n) % 4 == 0, 1.05, 0.995))   # up 1 of 4
    adj = np.column_stack([grind, lumpy, grind, lumpy, grind, lumpy])
    q_grind = cc.path_quality(n - 1, 0, adj)
    q_lumpy = cc.path_quality(n - 1, 1, adj)
    assert q_grind > q_lumpy > 0.0

    pool = [0, 1, 2, 3, 4, 5]
    assert cc.path_gate(n - 1, 0, adj, pool), "the grinder clears its own pool's median"
    assert not cc.path_gate(n - 1, 1, adj, pool), "the lumpy name does not"
    # unmeasurable is admitted, not blocked — the alternative is a history filter in disguise
    short = np.full((10, 1), 100.0)
    assert cc.path_gate(9, 0, short, [0]), "too little history admits rather than blocks"


def test_book_diversification_reports_the_left_tail_not_just_the_mean():
    """§2 says continuous effective bets is REPORTED. A mean over a decade hides exactly the
    sessions the rider exists for, so p5 and the below-thresholds shares are the payload."""
    bets = [10.0] * 90 + [1.5] * 10
    got = cc.book_diversification(bets, [2] * 90 + [9] * 10)
    assert got["mean"] == pytest.approx(9.15)
    assert got["p5"] == pytest.approx(1.5), "the 5th percentile sees the bad sessions"
    assert got["min"] == pytest.approx(1.5)
    assert got["frac_below_5"] == pytest.approx(0.10)
    assert got["frac_below_3"] == pytest.approx(0.10)
    assert got["max_cluster_max"] == 9
    assert cc.book_diversification([], []) is None


def _banded_world(n=N_DAYS, k=20, seed=7):
    """A banded-mode world with enough names to make a rank band and a rider mean something.

    A shared market factor, because the correlation rider is being tested and independent series
    would hand it a book that is already diversified — the fixture would prove the rider harmless
    by never letting it bind. Each name adds an idiosyncratic drift so the RANK has an order.
    """
    rng = np.random.default_rng(seed)
    mkt = np.cumsum(rng.normal(0.0004, 0.010, n))
    paths = {}
    for i in range(k):
        idio = np.cumsum(rng.normal(0.00005 * i, 0.006, n))
        paths[f"B{i:02d}.US"] = 100.0 * np.exp(mkt + idio)
    dates, tickers, adj, raw, dv = grid(paths)
    return dates, tickers, adj, raw, dv, np.full(n, 50.0)


BANDED = dict(n=5, months=6, risk_adjusted=True, sleeve=1.0, start_nav=200_000.0,
              trail=True, entry_rule="banded", rider_bets=0.0)


def test_the_exit_band_is_wired_to_something():
    """`lad_init10` was a cell that varied nothing: the initial stop it claimed to move was read
    from a module constant, so the cell reported a robust plateau it had never left. Any parameter
    a cell turns must be provable to MOVE the result, or the cell is measuring its own defaults."""
    d, t, adj, raw, dv, park = _banded_world()
    tight = cc.simulate(d, t, adj, raw, dv, park, exit_rank=6, **BANDED)[1]
    loose = cc.simulate(d, t, adj, raw, dv, park, exit_rank=19, **BANDED)[1]
    n_tight = len([x for x in tight if "entry_date" in x])
    n_loose = len([x for x in loose if "entry_date" in x])
    assert n_tight > n_loose, (
        f"a tighter exit band must churn the book more, got {n_tight} vs {n_loose} entries")


def test_the_rider_switch_is_wired_to_something():
    """`rider=False` is the cell that prices §2. If it changed nothing, that cell would report the
    rider as free when it had never been turned off."""
    d, t, adj, raw, dv, park = _banded_world()
    on = cc.simulate(d, t, adj, raw, dv, park, rider=True, **BANDED)[3]
    off = cc.simulate(d, t, adj, raw, dv, park, rider=False, **BANDED)[3]
    assert on["rider_blocks"], "the fixture shares a market factor — the cluster cap must bind"
    assert not off["rider_blocks"], "rider=False must not consult the rider at all"


def test_the_held_book_diversification_is_reported_on_every_run():
    """WO-A6 §2: continuous effective bets is reported, not enforced. It has to be THERE."""
    d, t, adj, raw, dv, park = _banded_world()
    health = cc.simulate(d, t, adj, raw, dv, park, **BANDED)[3]
    hb = health["held_book"]
    assert hb and hb["sessions"] > 0
    assert 1.0 <= hb["p5"] <= hb["median"] <= BANDED["n"] + 1e-9, (
        f"effective bets cannot exceed the number of names held: {hb}")
    assert hb["max_cluster_max"] >= 1


def test_the_path_quality_gate_is_wired_to_something():
    d, t, adj, raw, dv, park = _banded_world()
    open_door = cc.simulate(d, t, adj, raw, dv, park, path_quality_gate=False, **BANDED)[3]
    gated = cc.simulate(d, t, adj, raw, dv, park, path_quality_gate=True, **BANDED)[3]
    assert "path quality" not in open_door["rider_blocks"]
    assert gated["rider_blocks"].get("path quality", 0) > 0, (
        "half the pool sits below its own median by construction — the gate must refuse someone")
