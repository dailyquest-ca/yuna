"""The backtest engine, run over hand-built bars.

`simulate()` is pure — no database, no clock — so the properties that matter can be asserted
instead of hoped for. These are not performance tests. Every assertion here is a §3.2 clause the
old engine violated on real data, and each one is phrased so that the old engine would fail it:

  * 211 of run 5's 296 trades entered below MCN 70, which "never tickets".
  * 171 of them exited on `volume unconfirmed`, a rule the plan replaced with the freeze.
  * Pyramid adds fired at +2.5%/+4.5% with no ceiling.

A conformance table that no run can fail is decoration, so the last test builds a book the law
forbids and asserts the table says so.
"""
import datetime as dt
import sys
import pathlib

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import backtest as bt                                                    # noqa: E402
import signals as sg                                                     # noqa: E402

DAYS = 460
NAMES = 40
LEGAL_EXITS = {"stop", "gap", "gate_off", "unconfirmed", "template", "score",
               "earnings", "stalled", "delisted", "end_of_test"}


def sessions(n=DAYS, start=dt.date(2024, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def rising(n, start=20.0, daily=0.0016, wobble=0.0):
    """A clean uptrend — passes the trend template at every point past its warm-up."""
    drift = start * np.exp(np.cumsum(np.full(n, daily)))
    if wobble:
        drift = drift * (1 + wobble * np.sin(np.arange(n) / 7.0))
    return drift


def with_base(n, breakout_at, *, base_len=30, depth=0.04):
    """A strong rise, a peak that becomes the pivot, a short shallow base, then a breakout.

    The base is deliberately short. §3.2 needs the pivot 25-120 sessions back on the breakout day,
    and MCN reads a 90-day regression ending 10 sessions ago — a long flat base drags that slope
    to zero and the name ranks below its own floor, which is realistic and useless as a fixture.
    """
    peak_at = breakout_at - base_len
    close = rising(n, start=20.0, daily=0.0050)
    pivot = float(close[peak_at])
    shape = pivot * (1 - depth * np.sin(np.linspace(0, np.pi, base_len)) - 0.003)
    close[peak_at + 1:breakout_at + 1] = shape
    close[breakout_at:] = pivot * 1.03
    high = close * 1.002
    high[peak_at] = pivot                                            # the defining high
    high[peak_at + 1:breakout_at] = np.minimum(high[peak_at + 1:breakout_at], pivot * 1.002)
    high[breakout_at:] = close[breakout_at:] * 1.004
    return high, close * 0.996, close, pivot


def frame(hero_volume_multiple=3.0, hero_after=None, names=NAMES, days=DAYS):
    """A cross-section: one leader that sets up and breaks out, a strong group behind it, and a
    long tail of dull names — because MCN is percentile-based and a universe of identical uptrends
    scores every one of them at the middle."""
    dates = sessions(days)
    breakout = days - 12
    cols = [f"N{i:02d}.US" for i in range(names)]
    industry = {}
    O, H, L, C, A, V = ({} for _ in range(6))

    for i, tk in enumerate(cols):
        if i == 0:
            h, l, c, pivot = with_base(days, breakout)
            industry[tk] = "Steel"
        elif i < 10:
            c = rising(days, start=20.0 + i, daily=0.0026 + i * 1e-5)    # the leader's group
            h, l = c * 1.004, c * 0.996
            industry[tk] = "Steel"
        else:
            # dull: drifting sideways or down, and well off their own highs
            c = rising(days, start=15.0 + i, daily=-0.0004 + (i % 3) * 0.0002, wobble=0.01)
            h, l = c * 1.004, c * 0.996
            industry[tk] = ["Utilities", "Tobacco", "Rails"][i % 3]
        vol = np.full(days, 1_000_000.0 + i * 10_000)
        if i == 0:
            # A quiet base is half of what §3.2's setup score is looking for, and it is the
            # difference between this name ranking 65 and ranking 77 — without the dry-up the
            # leader never clears its own MCN floor and the fixture proves nothing.
            #
            # It stays quiet afterwards too. Letting volume revert to normal makes the *baseline*
            # the dried-out one, so an ordinary session prints 1.6x it and the breakout confirms
            # late — which is the rule behaving correctly and the fixture testing the wrong thing.
            vol[breakout - 30:] *= 0.4
            vol[breakout] = 1_000_000.0 * hero_volume_multiple
            if hero_after is not None:
                c, h, l = c.copy(), h.copy(), l.copy()
                c[breakout + 1:] = hero_after * pivot
                h[breakout + 1:] = c[breakout + 1:] * 1.002
                l[breakout + 1:] = c[breakout + 1:] * 0.998
        o = c * 0.999
        if i == 0:
            # The breakout day opens *below* the pivot and trades up through it, which is what a
            # resting stop-limit is for. Opening above pivot x 1.02 is a gap through the limit and
            # fills nothing — correct behaviour, and useless as a fixture for everything after it.
            o[breakout] = pivot * 0.995
            l[breakout] = pivot * 0.99
        O[tk], H[tk], L[tk], C[tk], A[tk], V[tk] = o, h, l, c, c, vol

    arrays = {k: np.column_stack([d[tk] for tk in cols])
              for k, d in (("open", O), ("high", H), ("low", L),
                           ("close", C), ("adj", A), ("vol", V))}
    spx = pd.Series(rising(days, start=4000.0, daily=0.0006), index=dates)

    # every name reports quarterly, always accelerating, always long before the window
    eps_rd = np.array([dt.date(2023, 12, 1).toordinal() - 90 * k for k in range(12)])
    eps_v = [40.0 - 2.0 * k for k in range(12)]
    return dict(dates=dates, cols=cols, arrays=arrays, spx=spx,
                bench_by_day={d: v for d, v in zip(dates, rising(days, 400.0, 0.0006))},
                industry=industry, reports={}, gate_source="TEST",
                eps={tk: (eps_rd, eps_v) for tk in cols}), breakout


def cfg(**over):
    hyp = dict(bt.LAW)
    hyp.update(over.pop("hyp", {}))
    base = dict(start_nav=200_000.0, max_names=int(hyp["max_names"] or 4), sleeve_cap=0.40,
                min_mcn=70.0, mcn_exit=55.0, cushion=1.08, max_stop=hyp["max_stop"],
                limit_over=0.02, pyramid_ceiling=1.05, confirm_limit=1.05,
                spread_bps=(5.0, 15.0), addv_break=50_000_000.0,
                hair_trigger_while_pending=False,      # ruled 2026-08-10: wait out the window
                hyp=hyp)
    base.update(over)
    return base


def preset(name, **over):
    """A hypothesis preset, exactly as the dispatched run would resolve it."""
    h = dict(bt.LAW); h.update(bt.PRESETS[name]); h.update(over)
    return cfg(hyp=h)


@pytest.fixture(scope="module")
def confirmed_run():
    f, breakout = frame(hero_volume_multiple=3.0)
    return bt.simulate(f, cfg()) + (breakout,)


# --------------------------------------------------------------------------- it runs at all

def test_the_engine_takes_the_breakout_it_is_given(confirmed_run):
    trades, equity, conf, _ = confirmed_run
    assert len(equity) == DAYS - bt.WARMUP
    assert conf["entries"] >= 1, "the fixture's breakout was never taken — the fixture is wrong"


def test_every_exit_reason_is_one_the_law_names(confirmed_run):
    """§3.2 lists the exits. `volume unconfirmed` was invented by the old engine and cost 4.7%
    of NAV over two years before anyone noticed it was not a rule."""
    trades, *_ = confirmed_run
    assert {t["exit_reason"] for t in trades} <= LEGAL_EXITS
    assert "volume unconfirmed" not in {t["exit_reason"] for t in trades}


def test_nothing_enters_below_mcn_seventy(confirmed_run):
    """§3.2 Sizing. The old engine had no floor at all and 71.3% of run 5 was below it."""
    trades, *_ = confirmed_run
    assert [t for t in trades if t["mcn"] is not None and t["mcn"] < 70.0] == []


def test_no_position_is_ever_larger_than_the_sleeve_allows(confirmed_run):
    trades, equity, *_ = confirmed_run
    assert max(e[2] for e in equity) <= 0.40 + 1e-9


def test_costs_are_charged_and_gross_beats_net(confirmed_run):
    """WO-12: a frictionless verdict is not a verdict."""
    trades, *_ = confirmed_run
    assert all(t["cost_usd"] > 0 for t in trades)
    assert all(t["pnl_gross_usd"] > t["pnl_usd"] for t in trades)


# --------------------------------------------------------------------------- the union date grid

def test_a_name_that_missed_a_session_is_still_ranked():
    """Rules read a name's own bars, never a slice of the union date grid.

    The grid holds every date any US ticker printed, so a name is NaN on sessions it did not
    trade. The first real run of this engine demanded a hole-free 280-row grid window and got
    **zero rank dates in 2,310 days** — every name in the universe failed it, silently, and the
    run came back with a clean 0 trades and no error.
    """
    f, breakout = frame()
    j = f["cols"].index("N00.US")
    for k in (breakout - 200, breakout - 150, breakout - 120):
        for key in ("open", "high", "low", "close", "adj", "vol"):
            f["arrays"][key][k, j] = np.nan               # three sessions it simply did not trade
    trades, equity, conf = bt.simulate(f, cfg())
    assert conf["rank_dates"] > 0, "the ranker produced nothing at all"
    assert conf["entries"] >= 1, "a name with three missing sessions fell out of the universe"


# --------------------------------------------------------------------------- the freeze

def test_an_unconfirmed_breakout_that_holds_the_pivot_is_not_exited():
    """§3.2 as ratified: below 1.4x volume the pyramid freezes at 50% — it does not sell. The
    engine this replaces sold 171 positions at the next open on exactly this condition."""
    f, breakout = frame(hero_volume_multiple=0.5)
    trades, equity, conf = bt.simulate(f, cfg())
    early = [t for t in trades if t["bars_held"] <= 2 and t["exit_reason"] == "unconfirmed"]
    assert early == [], "an unconfirmed breakout was sold while it was still above its pivot"


def test_an_unconfirmed_breakout_that_closes_back_below_the_pivot_exits():
    """The hair-trigger, and the only exit volume has any part in (§3.2)."""
    f, breakout = frame(hero_volume_multiple=0.5, hero_after=0.97)
    trades, equity, conf = bt.simulate(f, cfg())
    assert any(t["exit_reason"] == "unconfirmed" for t in trades), \
        "a failed breakout closed back below its pivot and the engine held it"


def test_the_ruling_makes_the_position_wait_a_session_longer():
    """Ruled 2026-08-10. The same failed breakout, both readings — the ruling holds it through the
    confirmation window and exits a session later, so a name that confirms late is not thrown away
    for dipping under its pivot on day two. The stop is what bounds the wait."""
    f, _ = frame(hero_volume_multiple=0.5, hero_after=0.97)
    ruled, _, _ = bt.simulate(f, cfg())
    f, _ = frame(hero_volume_multiple=0.5, hero_after=0.97)
    cut, _, _ = bt.simulate(f, cfg(hair_trigger_while_pending=True))
    assert [t["exit_reason"] for t in ruled] == [t["exit_reason"] for t in cut] == ["unconfirmed"]
    assert ruled[0]["bars_held"] > cut[0]["bars_held"]


def test_a_frozen_position_never_pyramids(confirmed_run):
    """Unconfirmed means half size until it confirms late or the stall rule resolves it."""
    f, breakout = frame(hero_volume_multiple=0.5)
    trades, equity, conf = bt.simulate(f, cfg())
    assert all(t["pyramid_steps"] == 1 for t in trades if t["confirmed"] is not True)


# --------------------------------------------------------------------------- the conformance table

def test_the_conformance_table_passes_a_lawful_run(confirmed_run):
    trades, equity, conf, _ = confirmed_run
    table = bt.conformance(conf, trades, equity)
    assert not any(c.get("violations") for c in table)
    assert not any(c.get("unknown_reasons") for c in table)
    assert {c["clause"] for c in table} >= {"MCN < 70 never tickets",
                                            "M4 earnings acceleration",
                                            "Earnings blackout — 5 trading days"}


def test_the_conformance_table_catches_a_run_the_law_forbids(confirmed_run):
    """A table nothing can fail is decoration. Feed it a sub-70 entry and an invented exit."""
    _, equity, conf, _ = confirmed_run
    bad = [dict(mcn=15.1, exit_reason="volume unconfirmed"),
           dict(mcn=88.0, exit_reason="stop")]
    table = bt.conformance(conf, bad, equity)
    floor = next(c for c in table if c["clause"] == "MCN < 70 never tickets")
    exits = next(c for c in table if c["clause"].startswith("Exits"))
    assert floor["violations"] == 1
    assert exits["unknown_reasons"] == ["volume unconfirmed"]


# --------------------------------------------------------------------------- the hypothesis set
#
# The 2026-08-10 variants. Every one is opt-in and law-v0 is the baseline until a run earns the
# change, so the first thing to pin is that the machinery is inert by default — and the second is
# that each flag actually does something, because a dead flag reads exactly like a tested one.

def test_the_hypothesis_machinery_is_inert_by_default(monkeypatch):
    monkeypatch.delenv("HYPOTHESIS", raising=False)
    for k in bt.LAW:
        monkeypatch.delenv(k.upper(), raising=False)
    assert bt.hypothesis() == bt.LAW


def test_the_presets_stage_the_changes_in_dependency_order():
    """Widening risk is pointless while unconfirmed breakouts are still bought, and pressing is
    dangerous before expectancy turns — so each preset contains the one before it."""
    h1, h2, h3 = (bt.PRESETS[k] for k in ("h1", "h2", "h3"))
    assert h1.items() <= h2.items() <= h3.items()


def test_e1_refuses_the_breakout_the_law_buys():
    """The whole point of confirming first: a breakout with no volume is never bought at all,
    instead of bought and then discovered. On the fixture the law takes it and E1 does not."""
    f, _ = frame(hero_volume_multiple=0.5)
    law, _, law_conf = bt.simulate(f, cfg())
    f, _ = frame(hero_volume_multiple=0.5)
    e1, _, e1_conf = bt.simulate(f, preset("h1"))
    assert law_conf["entries"] >= 1
    assert e1_conf["entries"] == 0


def test_e1_positions_are_confirmed_the_moment_they_are_opened():
    f, _ = frame(hero_volume_multiple=3.0)
    trades, _, conf = bt.simulate(f, preset("h1"))
    assert conf["entries"] >= 1
    assert all(t["confirmed"] is True for t in trades)


def test_r1_scales_the_stop_to_the_name_and_widens_the_ones_that_matter():
    """65% of entries breach -8% within 125 sessions, so the law's stop and a multi-month hold are
    mutually exclusive. ATR(14) on the names this system trades runs 2.24% / 2.86% / 3.78% / 4.90%
    of price across the quartiles — the multiplier has to be read off that, not off convention.

    A first attempt used 2.5x, which lands a median name at 7.2% — the law's 7.57% stop with a new
    name on it. It would have tested nothing.
    """
    at = lambda pct: 100.0 - sg.volatility_stop(100.0, pct)
    assert at(2.86) == pytest.approx(14.3)        # median name: genuinely wider than 8%
    assert at(2.24) == pytest.approx(11.2)        # quiet name: still tighter than the cap
    assert at(4.90) == pytest.approx(20.0)        # volatile name: the cap binds
    assert all(at(p) <= 20.0 + 1e-9 for p in (2.24, 2.86, 3.78, 4.90, 12.0))
    assert at(2.86) > 7.57, "the multiplier must beat the stop it is replacing"


def test_r1_never_floors_the_stop_at_the_contraction_low():
    """The contraction low is what makes the law's stop tight; flooring at it would undo R1."""
    tight = sg.initial_stop(100.0, 96.0)                 # law: the contraction low wins
    loose = sg.volatility_stop(100.0, 2.86)              # R1: the name's own noise
    assert tight == pytest.approx(96.0)
    assert loose < tight


def test_s1_and_s2_change_which_names_rank():
    """Dropping the volatility divisor and the tightness sub-score is the difference between
    ranking the calmest name near its high and ranking the strongest."""
    f, _ = frame()
    law = bt.rank(f, DAYS - 12, f["cols"], f["arrays"],
                  [np.flatnonzero(~np.isnan(f["arrays"]["close"][:, j]))
                   for j in range(len(f["cols"]))], bt.LAW)
    hyp = dict(bt.LAW); hyp.update(bt.PRESETS["h1"])
    loud = bt.rank(f, DAYS - 12, f["cols"], f["arrays"],
                   [np.flatnonzero(~np.isnan(f["arrays"]["close"][:, j]))
                    for j in range(len(f["cols"]))], hyp)
    assert law["l1m"] != loud["l1m"], "S1+S2 produced an identical ranking — the flags are dead"


def test_the_press_counter_exists_so_the_branch_cannot_crash_or_hide():
    """`conf['pressed'] += 1` on an uninitialised key is a KeyError waiting for the first press.

    H3 ran green with the key missing, which is the tell: the branch never executed once in 285
    trades. A counter that is absent rather than zero cannot distinguish "P1 did not pay" from
    "P1 never ran", and those need very different responses.
    """
    f, _ = frame()
    _, _, conf = bt.simulate(f, cfg())
    assert conf["pressed"] == 0
    assert "press_windows" in conf and "press_expired" in conf


def test_the_press_gives_the_next_base_a_window_to_arrive_in():
    """P1's first cut demanded a valid base AND a breakout on the exact session the four-week
    clock expired — a coincidence, not a rule. §3.2 says "completes on the next base", and the
    next base needs time to form."""
    assert bt.LAW["press_grace"] >= 20, "one session is not a window"
    f, _ = frame()
    _, _, conf = bt.simulate(f, preset("h3"))
    assert conf["press_windows"] >= 0        # the machinery is reachable
    assert conf["pressed"] + conf["press_expired"] <= conf["press_windows"]


def test_s3_lets_a_loss_to_profit_swing_pass_m4():
    """MU went -$1.07 to +$1.18 and scored no growth rate at all, because you cannot divide by a
    negative base. It was invisible through the whole recovery, then ran +1,029%."""
    eps = [1.18, -0.95, -1.07, -1.43, -1.91]     # newest first: latest positive, base a year ago
    assert s_m4(eps, swing=False) is False
    assert s_m4(eps, swing=True) is True


def s_m4(eps, **kw):
    return sg.m4_acceleration(eps, **kw)["passes"]


# --------------------------------------------------------------------------- the law, written once
#
# The whole point of the rewrite. `backtest_compounders.py` records what happens without this
# guard: "a private copy with its own constants ... meant the backtest silently measured a
# different formula than production priced — the exact failure mode a backtest exists to rule
# out." The momentum engine had drifted in nine places before anyone diffed it against §3.2.

SHARED_RULES = ["market_gate", "trend_template", "base_scan", "momentum_quality",
                "setup_proximity", "mcn", "m4_acceleration", "confirmation_state",
                "pyramid_orders", "entry_order", "ratchet_stop", "momentum_size",
                "enterable", "stalled_pyramid", "in_blackout", "holds_through_earnings",
                "pct_rank", "weekly_closes"]


@pytest.mark.parametrize("rule", SHARED_RULES)
def test_the_driver_calls_the_law_rather_than_restating_it(rule):
    source = (ROOT / "src" / "backtest.py").read_text()
    assert f"sg.{rule}(" in source, (
        f"backtest.py no longer calls signals.{rule} — either the rule moved, or the driver has "
        f"started deriving it again")


def test_the_driver_defines_no_function_that_shadows_a_rule():
    """A helper named like a rule is how the second implementation gets back in."""
    import ast
    tree = ast.parse((ROOT / "src" / "backtest.py").read_text())
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    public = {n for n in dir(sg) if not n.startswith("_") and callable(getattr(sg, n))}
    assert defined & public == set(), f"backtest.py redefines: {sorted(defined & public)}"


def test_unknown_m4_coverage_is_reported_not_assumed():
    """A clause with no data is not a passing clause (learnings #19 — green is not a result)."""
    f, breakout = frame()
    f["eps"] = {}                                    # nothing was knowable
    trades, equity, conf = bt.simulate(f, cfg())
    table = bt.conformance(conf, trades, equity)
    m4 = next(c for c in table if c["clause"] == "M4 earnings acceleration")
    assert m4["coverage"] == 0.0
    assert trades == [], "M4 was unknown for every name, so L1-M should have been empty"
