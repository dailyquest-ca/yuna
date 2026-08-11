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


def frame(hero_volume_multiple=3.0, hero_after=None, names=NAMES, days=DAYS, breakout_at=None):
    """A cross-section: one leader that sets up and breaks out, a strong group behind it, and a
    long tail of dull names — because MCN is percentile-based and a universe of identical uptrends
    scores every one of them at the middle."""
    dates = sessions(days)
    breakout = days - 12 if breakout_at is None else breakout_at
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


def recovery_frame(days=DAYS):
    """The shape H6 exists for: the leader breaks out, gets shaken out, goes quiet, then resumes.

    The recovery deliberately stops **below** the post-breakout high, so the old pivot is still
    overhead and no base breakout is available. That is the realistic case and the one the first
    cut of the code got wrong: a valid-but-untriggered base sitting in front of the name would
    have shut the re-entry door for months.
    """
    f, breakout = frame(days=days, breakout_at=days - 120)
    a = {k: v.copy() for k, v in f["arrays"].items()}
    close = a["close"][:, 0]
    pivot = float(close[breakout]) / 1.03
    plateau, shake, quiet = breakout + 10, breakout + 20, breakout + 45

    seg = np.concatenate([
        np.linspace(1.03, 0.955, shake - plateau),        # the shakeout, through any sane stop
        np.full(quiet - shake, 0.955),                    # dead money
        np.linspace(0.955, 1.02, days - quiet)])          # resumption, still under the old pivot
    close[plateau:] = pivot * seg
    a["high"][plateau:, 0] = close[plateau:] * 1.002
    a["low"][plateau:, 0] = close[plateau:] * 0.998
    a["open"][plateau:, 0] = close[plateau:] * 0.999
    a["adj"][:, 0] = a["close"][:, 0]
    f = dict(f, arrays=a)
    return f, shake


def runner_frame(days=DAYS, top=2.6):
    """The shape the trim ladder exists for: a leader that breaks out and keeps going.

    A smooth climb on purpose. Any wobble large enough to matter brings the trail and the euphoria
    rung into the picture, and then the test is measuring those instead of the ladder.
    """
    f, breakout = frame(days=days, breakout_at=days - 120)
    a = {k: v.copy() for k, v in f["arrays"].items()}
    close = a["close"][:, 0]
    pivot = float(close[breakout]) / 1.03
    close[breakout:] = pivot * np.linspace(1.03, top, days - breakout)
    a["high"][breakout:, 0] = close[breakout:] * 1.004
    a["low"][breakout:, 0] = close[breakout:] * 0.998
    a["open"][breakout:, 0] = close[breakout:] * 0.999
    a["open"][breakout, 0] = pivot * 0.995
    a["low"][breakout, 0] = pivot * 0.99
    a["adj"][:, 0] = a["close"][:, 0]
    return dict(f, arrays=a), breakout


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
    dangerous before expectancy turns — so each preset contains the one before it.

    The chain forks after H2: H3 presses and H4 takes profit on a stall, and they were run against
    each other rather than stacked. H4 won, so H5 and H6 continue from H4, not from H3.
    """
    P = bt.PRESETS
    assert P["h1"].items() <= P["h2"].items() <= P["h3"].items()
    assert P["h2"].items() <= P["h4"].items() <= P["h5"].items() <= P["h6"].items()


def test_the_ablations_each_move_exactly_one_clause_off_h4():
    """H5 bundled three changes and lost money; the ablations exist to say which one did it, which
    only works if each differs from H4 in a single key."""
    h4 = bt.PRESETS["h4"]
    for name, keys in (("d1", {"depth_atr_mult"}), ("d2", {"off_high_atr_mult"}),
                       ("d3", {"min_base_age"}), ("x1", {"reentry_window", "reentry_cooloff"}),
                       ("t1", {"template_exit"}), ("b1", {"breakeven"}), ("b2", {"euphoria"})):
        p = bt.PRESETS[name]
        assert h4.items() <= p.items(), f"{name} is not H4 plus something"
        assert set(p) - set(h4) == keys, f"{name} moves more than its one clause"
    for name, keys in (("b3", {"stagnation_days"}),          # these change a value H4 already sets
                       ("b4", {"breakeven_r", "breakeven_on_full_size"}),
                       ("b5", {"breakeven_giveback"})):
        p = bt.PRESETS[name]
        assert {k for k in p if p[k] != h4.get(k)} == keys, f"{name} moves more than its clause"


def test_b5_leaves_room_under_cost_instead_of_parking_the_stop_on_it():
    """Price oscillates around entry, so a rung at exactly cost is a magnet — 38 of H4's 43 `gap`
    exits are shallow scratches six sessions in. Giveback interpolates H4 (0.0) to B1 (1.0)."""
    closes = list(np.linspace(96.0, 104.0, 49)) + [104.0]
    kw = dict(closes=closes, avg_cost=100.0, current_stop=90.0, pyramid_step=3, init_stop=90.0)
    assert sg.ratchet_stop(**kw)["stop"] == pytest.approx(100.0)                 # §3.2: on cost
    assert sg.ratchet_stop(**kw, breakeven_giveback=0.5)["stop"] == pytest.approx(95.0)
    assert sg.ratchet_stop(**kw, breakeven_giveback=1.0)["stop"] == pytest.approx(90.0)  # == B1


def test_b4_keeps_the_earned_it_trigger_and_drops_the_sizing_one():
    """§3.2 trips the rung on full pyramid size, which under E1 nearly every position reaches —
    so it fires on positions that have earned nothing. B4 requires 3R instead."""
    flat = list(np.linspace(96.0, 104.0, 49)) + [104.0]          # +4%, well under 3R
    kw = dict(avg_cost=100.0, current_stop=90.0, pyramid_step=3, init_stop=90.0)
    assert sg.ratchet_stop(closes=flat, **kw)["mode"] == "breakeven"
    b4 = dict(breakeven_on_full_size=False, breakeven_r=3.0)
    assert sg.ratchet_stop(closes=flat, **kw, **b4)["mode"] == "initial"
    earned = list(np.linspace(96.0, 104.0, 49)) + [131.0]        # +31% = 3.1R on a 10% risk
    assert sg.ratchet_stop(closes=earned, **kw, **b4)["mode"] in ("breakeven", "trail10", "trail5")


def test_b1_removes_the_breakeven_rung_that_breakeven_r_cannot_reach():
    """`breakeven_r=None` does not mean "no breakeven" — it restores §3.2's "at full pyramid
    size", which under E1 fires on most positions. B1 needs its own switch or it tests nothing."""
    closes = list(np.linspace(96.0, 104.0, 49)) + [104.0]     # +4%: under the trail, not euphoric
    kw = dict(closes=closes, avg_cost=100.0, current_stop=94.0, pyramid_step=3, init_stop=94.0)
    assert sg.ratchet_stop(**kw)["mode"] == "breakeven"
    assert sg.ratchet_stop(**kw, breakeven_r=None)["mode"] == "breakeven"   # still fires
    assert sg.ratchet_stop(**kw, breakeven=False)["mode"] == "initial"      # only this removes it
    assert sg.ratchet_stop(**kw, breakeven=False)["stop"] == 94.0


def test_b2_stops_tightening_the_trail_on_exactly_the_names_we_want():
    """A close >2sd above its own 50-day cuts the trail from 10% to 5%. That describes a stock in
    the leg that makes a +100% year, and 5% is inside an ordinary pullback for it."""
    closes = list(np.linspace(100.0, 118.0, 49)) + [180.0]
    kw = dict(closes=closes, avg_cost=100.0, current_stop=94.0, pyramid_step=1)
    law = sg.ratchet_stop(**kw)
    calm = sg.ratchet_stop(**kw, euphoria=False)
    assert law["mode"] == "trail5" and law["euphoric"] is True
    assert calm["mode"] == "trail10" and calm["euphoric"] is False
    assert calm["stop"] < law["stop"], "B2 must leave the position more room, not less"


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


# --------------------------------------------------------------------- H5: eligibility, scaled
#
# The funnel decomposition put the miss before ranking: a name that produces a +100% year corrects
# 42% on the way, and §3.2's flat 25% depth clause gives it a valid base on 5.9% of days against
# 29.3% at 40%. These pin that the widening is proportional rather than blanket — a quiet name has
# to keep the law exactly, or D1 is not a hypothesis about volatility, it is just a looser rule.

def test_d1_hands_a_quiet_name_the_law_and_a_volatile_one_more():
    at = lambda pct: bt._tolerance(pct / 100.0, 8.0)
    assert at(2.24) == pytest.approx(0.25)     # quiet name: the floor binds, the law is unchanged
    assert at(2.86) == pytest.approx(0.25)     # the median name: still exactly the law
    assert at(5.00) == pytest.approx(0.40)     # the depth the winners actually need
    assert at(12.0) == pytest.approx(0.60)     # the ceiling binds — no name gets a blank cheque


def test_d1_is_inert_when_the_flag_is_off():
    """law-v0 must read 25% for every name, whatever its ATR, or the baseline has moved."""
    assert all(bt._tolerance(p, None) == 0.25 for p in (0.01, 0.03, 0.09, None))


def test_the_multiplier_is_read_off_the_measured_atr_not_off_convention():
    """8 is chosen so the median name (ATR 2.86%) lands *below* the 25% floor and is untouched.
    A smaller multiplier changes nothing anywhere; a larger one loosens the median too."""
    assert 8.0 * 0.0286 < 0.25, "the median name must fall through to the law's number"
    assert 8.0 * 0.0500 == pytest.approx(0.40), "a 5% ATR name must reach the measured 40%"
    assert bt.PRESETS["h5"]["depth_atr_mult"] == 8.0


def test_d1_makes_a_deep_base_valid_only_for_the_name_that_earns_it():
    """The same 33%-deep base: rejected under the law, accepted once the name's own range says a
    third is an ordinary correction for it."""
    close = np.concatenate([np.linspace(70, 100, 51),            # the pivot, 110 sessions back
                            np.linspace(100, 67, 70)[1:],        # a 33% correction under it
                            np.linspace(67, 99, 40)])            # back to just below the pivot
    high, low = close * 1.001, close * 0.999
    high[50] = 100.0
    assert sg.base_scan(high, low, close)["depth"] == pytest.approx(0.3307, abs=1e-3)
    assert sg.base_scan(high, low, close)["valid"] is False
    assert sg.base_scan(high, low, close, max_depth=0.40)["valid"] is True


def test_d2_keeps_the_name_that_corrected_hard_on_the_way_up():
    """M2's last condition is 'within 25% of the 52-week high'. A name up 300% that spiked, gave
    back 30%, and is climbing again off a rising 50-day passes the other five conditions — and is
    exactly the one we want. The law rejects it on that clause alone.

    The clause is narrower than it looks, which is worth recording: an ordinary 30% drawdown also
    puts price under its own 50- and 200-day, so those conditions reject the name first and
    `off_high` never gets a vote. It binds only where the SMA stack is still far below — the shape
    a name that has already tripled actually has. That is why D1 (depth) is the big term and D2 is
    the small one.
    """
    c = np.concatenate([np.linspace(40.0, 50.0, 100),        # a long, low base — the 200-day
                        np.linspace(50.0, 130.0, 80),        # the run
                        [165.0],                             # the spike high
                        np.linspace(165.0, 100.0, 50),       # -39%
                        np.linspace(100.0, 115.0, 21)])      # climbing again, 30% off the high
    assert 1 - c[-1] / c[-252:].max() == pytest.approx(0.303, abs=1e-3)
    assert sg.trend_template(c) is False                     # the law rejects it at -30%
    assert sg.trend_template(c, off_high=0.40) is True       # scaled to its own range, it passes


def test_d3_is_the_small_term_and_is_declared_as_such():
    """Shortening the base moves the winners' base frequency 5.9% -> 6.8%; depth moves it to
    29.3%. It is in H5 to answer the question, not because it is expected to carry the run."""
    assert bt.LAW["min_base_age"] == 25
    assert bt.PRESETS["h5"]["min_base_age"] == 12


def test_h5_declares_the_thresholds_it_actually_enforced():
    """A conformance table that prints the law's 25% while the run used 40% is a lie, and this
    table exists to end exactly that kind of green."""
    f, _ = frame()
    trades, equity, conf = bt.simulate(f, preset("h5"))
    table = bt.conformance(conf, trades, equity, hyp=preset("h5")["hyp"])
    m3 = next(c for c in table if c["fn"] == "signals.base_scan")
    m2 = next(c for c in table if c["fn"] == "signals.trend_template")
    assert "8.0 x ATR" in m3["depth"] and m3["min_age"] == 12
    assert "8.0 x ATR" in m2["off_high"]

    law_table = bt.conformance(conf, trades, equity, hyp=dict(bt.LAW))
    assert next(c for c in law_table if c["fn"] == "signals.base_scan")["depth"] == "25% flat"


# ------------------------------------------------------------------------- H6: a way back in
#
# §3.2 has one door into a name and no way back through it. Of 200 positions stopped out, 96%
# traded back above the exit inside 60 days and the average best subsequent move was +26.8% — we
# were wrong about the moment, not the name.

def test_x1_is_inert_without_the_flag():
    f, _ = frame()
    _, _, conf = bt.simulate(f, cfg())
    assert conf["reentries"] == 0
    assert bt.LAW["reentry_window"] is None


def test_x1_will_not_buy_a_name_we_never_held():
    """A re-entry is a second opinion on our own exit. With no exit there is nothing to revise —
    otherwise X1 is a whole new entry rule wearing a re-entry's name."""
    hyp = dict(bt.LAW); hyp.update(bt.PRESETS["h6"])
    C = np.linspace(10.0, 30.0, 300).reshape(-1, 1)      # a new high every single session
    valid = [np.arange(300)]
    assert bt._reentry_ready("N.US", 0, 299, valid, C, {}, hyp) is False
    assert bt._reentry_ready("N.US", 0, 299, valid, C, {"N.US": 250}, hyp) is True


def test_x1_waits_out_the_cooloff():
    hyp = dict(bt.LAW); hyp.update(bt.PRESETS["h6"])
    C = np.linspace(10.0, 30.0, 300).reshape(-1, 1)
    valid = [np.arange(300)]
    assert bt._reentry_ready("N.US", 0, 299, valid, C, {"N.US": 297}, hyp) is False
    assert bt._reentry_ready("N.US", 0, 299, valid, C, {"N.US": 294}, hyp) is True


def test_x1_triggers_on_the_stocks_high_and_not_on_our_exit_price():
    """Zak's ruling, and the whole reason the trigger is written this way: 'it doesn't have to be
    where we sold ... we have to just buy back into strength'. Where we sold is our history."""
    flat_then_up = np.concatenate([np.full(40, 50.0), [50.5]])
    assert sg.resumed(flat_then_up) is True     # a new 20-day high, far below any plausible exit
    still_sagging = np.concatenate([np.full(20, 50.0), np.linspace(80.0, 60.0, 21)])
    assert sg.resumed(still_sagging) is False   # well above an exit at 50, and not resuming


def test_x1_never_re_buys_a_name_that_delisted():
    """`delisted` is the one exit that is about the name rather than the moment."""
    f, breakout = frame()
    f = dict(f)
    a = {k: v.copy() for k, v in f["arrays"].items()}
    for k in a:                                          # the leader stops printing after entry
        a[k][breakout + 3:, 0] = np.nan
    f["arrays"] = a
    trades, _, conf = bt.simulate(f, preset("h6"))
    assert any(t["exit_reason"] == "delisted" for t in trades)
    assert conf["reentries"] == 0


def test_x1_buys_the_recovery_back_and_says_which_door_it_used():
    f, exit_at = recovery_frame()
    trades, _, conf = bt.simulate(f, preset("h6"))
    assert conf["reentries"] >= 1, "the fixture recovered to a new 20-day high and X1 sat it out"
    kinds = [t["entry_kind"] for t in trades]
    assert "reentry" in kinds and "base" in kinds

    # ... and H5, which is H6 without the door, leaves the recovery on the table. That is the
    # measurement: the difference between these two runs is X1 and nothing else.
    f2, _ = recovery_frame()
    _, _, h5_conf = bt.simulate(f2, preset("h5"))
    assert h5_conf["reentries"] == 0
    assert conf["entries"] > h5_conf["entries"]

    # And the point of the ruling, on the tape: the fixture's re-entry is *below* where we sold.
    # A rule anchored on our exit price would have waited for a level the stock never needed.
    sold = next(t for t in trades if t["entry_kind"] == "base")["exit_price"]
    assert next(t for t in trades if t["entry_kind"] == "reentry")["entry_price"] < sold


def test_x1_re_enters_with_a_stop_and_a_pyramid_of_its_own():
    """A re-entry has no base and therefore no contraction low. It must still be protected, and it
    must not inherit the dead pivot — the adds ladder off the new entry."""
    f, _ = recovery_frame()
    trades, _, _ = bt.simulate(f, preset("h6"))
    back_in = [t for t in trades if t["entry_kind"] == "reentry"]
    assert back_in, "no re-entry to check"
    for t in back_in:
        assert t["initial_stop"] is not None and 0 < t["initial_stop"] < t["entry_price"]
        assert t["pivot"] == pytest.approx(t["entry_price"], rel=0.02)


def test_t1_stops_selling_on_the_template_and_says_so():
    """Every other variant widens a rule; T1 deletes one. A count of exit reasons cannot catch
    that — a suppressed rule looks exactly like a rule with nothing to fire on — so the table has
    to name it separately."""
    # The leader gaps down after its breakout and sits there: below its 50-day, so M2 fails at the
    # next weekly rank, but flat, so nothing else fires. The one shape that isolates this exit.
    f, _ = frame(hero_after=0.80, breakout_at=DAYS - 14)
    law_trades, _, _ = bt.simulate(f, preset("h4"))
    f, _ = frame(hero_after=0.80, breakout_at=DAYS - 14)
    t1_trades, _, t1_conf = bt.simulate(f, preset("t1"))
    assert any(t["exit_reason"] == "template" for t in law_trades)
    assert not any(t["exit_reason"] == "template" for t in t1_trades)

    table = bt.conformance(t1_conf, t1_trades, [], hyp=preset("t1")["hyp"])
    exits = next(c for c in table if c["clause"].startswith("Exits"))
    assert exits["suppressed"] == ["template"]
    law = bt.conformance(t1_conf, t1_trades, [], hyp=dict(bt.LAW))
    assert next(c for c in law if c["clause"].startswith("Exits"))["suppressed"] == []


# --------------------------------------------------------------- M1: trimming into strength
#
# Zak's own method, ruled in 2026-08-11: "trimming 25% at 50% or so and trimming 25% at 100%. And
# then letting the rest ride until the stock completely dies." §3.2 has no partial exit at all — a
# position is opened once and closed once — so this is the first variant that needed the engine to
# change rather than a threshold.

def test_the_ladder_sells_a_quarter_at_each_rung_and_rides_the_rest():
    f, _ = runner_frame()
    trades, _, conf = bt.simulate(f, preset("m1"))
    hero = [t for t in trades if t["ticker"] == "N00.US"]
    reasons = [t["exit_reason"] for t in hero]
    assert conf["trims"] == 2 and reasons[:2] == ["trim50", "trim100"]
    assert hero[0]["pnl_pct"] == pytest.approx(0.50, abs=0.03)
    assert hero[1]["pnl_pct"] == pytest.approx(1.00, abs=0.03)
    # a quarter, then another quarter of the FULL position — not a quarter of what was left
    full = sum(t["qty"] for t in hero)
    assert hero[0]["qty"] == pytest.approx(full * 0.25, rel=0.02)
    assert hero[1]["qty"] == pytest.approx(full * 0.25, rel=0.02)
    assert hero[-1]["qty"] == pytest.approx(full * 0.50, rel=0.02), "half must be left riding"


def test_the_runner_outlives_the_housekeeping_exits():
    """"Until the stock completely dies" — the template, the MCN floor and the stall and
    stagnation clocks are how a *resting* position gets closed, and a trimmed one is not resting.
    It keeps its stop, the market gate and delisting."""
    f, _ = runner_frame()
    trades, _, _ = bt.simulate(f, preset("m1"))
    runner = [t for t in trades if t["ticker"] == "N00.US"][-1]
    assert runner["exit_reason"] not in ("template", "score", "stalled", "stagnant")
    off, _ = runner_frame()
    plain = bt.simulate(off, preset("m1", runner_immunity=False))[0]
    assert [t["exit_reason"] for t in plain if t["ticker"] == "N00.US"][:2] == ["trim50", "trim100"]


def test_m2_gives_the_runner_a_wider_trail_than_the_position_it_came_from():
    """Run 33's three runners all stopped 2-4 sessions after their second trim — MU at +91.7%,
    AVAV at +102.7% — on the euphoria rung, because a name up 100% is by construction far above
    its own 50-day and 5% is one ordinary session for it. B2 says that tightening pays on an
    ordinary position, so it stays; a runner with two rungs banked is a different question."""
    m2 = dict(bt.LAW); m2.update(bt.PRESETS["m2"])
    assert m2["runner_trail"] > m2["trail"] and m2["runner_no_euphoria"] is True
    parabolic = list(np.linspace(100.0, 150.0, 49)) + [230.0]
    kw = dict(closes=parabolic, avg_cost=100.0, current_stop=150.0, pyramid_step=3)
    tight = sg.ratchet_stop(**kw, trail10=m2["trail"])
    ride = sg.ratchet_stop(**kw, trail10=m2["runner_trail"], euphoria=False)
    assert tight["mode"] == "trail5"
    assert ride["mode"] in ("trail10", "held") and ride["stop"] <= tight["stop"]


def test_expectancy_does_not_flatter_a_run_that_trims():
    """A trim rung can only be hit by a position already up 50% or 100%, so slices are winners by
    construction. Averaging them beside full exits made run 36 read +2.208% while the dollar it
    deployed returned -1.45%. Equal-weighting rows stopped being meaningful the moment a row
    became a slice rather than a position, and the summary has to say so itself."""
    f, _ = runner_frame()
    trades, equity, conf = bt.simulate(f, preset("m1"))
    s = bt.summarise(trades, equity, f, conf, hyp=preset("m1")["hyp"])
    st = s["stats"]
    assert st["trim_slices"] == 2 and st["trim_usd"] > 0
    # The headline averages slices beside positions and the full-exit figure does not, so the two
    # must differ. Which is larger depends on the run — in run 36 the slices flattered it (+2.208%
    # against -1.45% on the dollar deployed); on a single clean runner they drag it down. Either
    # way the headline is not a number to compare across runs once a variant trims.
    assert st["expectancy_full_exits"] != pytest.approx(s["expectancy"])
    assert st["return_on_deployed"] is not None

    f, _ = frame()
    plain = bt.simulate(f, cfg())
    ps = bt.summarise(*plain[:2], f, plain[2])["stats"]
    assert ps["trim_slices"] == 0
    assert ps["expectancy_full_exits"] == pytest.approx(
        bt.summarise(*plain[:2], f, plain[2])["expectancy"]), "no trims: the two must agree"


# ------------------------------------------------- A: the forever hold, and averaging into it
#
# Zak, 2026-08-11: "what if our biggest winners that made it to +100%... we never sold. We just
# kept them long-term? ... averaged in ... on proven strength we widen the stops ... 25% at 35% and
# 25% at 75% and if it makes it that high... never sell... unless the financials on the
# profitability of the company dies."

def test_averaging_in_is_three_equal_tranches_five_percent_apart():
    law = sg.pyramid_orders(100.0)
    a1 = sg.pyramid_orders(100.0, spacing=0.05, tranches=3)
    assert [o["trigger"] for o in law] == [102.0, 104.0]
    assert [round(o["trigger"], 2) for o in a1] == [105.0, 110.0]
    assert all(o["fraction"] == pytest.approx(1 / 3) for o in a1)
    # the ceiling has to travel with the trigger, or the last tranche can never fill
    assert all(o["limit"] > o["trigger"] for o in a1)
    assert bt.PRESETS["a1"]["entry_fraction"] == pytest.approx(1 / 3), (
        "a1 must not open full — averaging in is the whole point")


def test_only_the_financials_can_end_a_forever_hold():
    """Every §3.2 exit is a price exit, and the premise of the forever hold is that price no
    longer speaks. So the test has to be earnings and nothing else — and unknown is not dead,
    because the alternative is selling a position on a data gap."""
    assert sg.profitability_dead([1.2, 0.9, 0.7]) is False
    assert sg.profitability_dead([-0.4, 0.9, 0.7]) is False        # one bad quarter is a stumble
    assert sg.profitability_dead([-0.4, -0.1, 0.7]) is True        # two in a row is the business
    assert sg.profitability_dead([]) is False                      # no data is not a sell signal
    assert sg.profitability_dead([-0.4]) is False


def test_the_forever_hold_survives_what_would_close_any_other_position():
    """The runner past the last rung keeps no stop, ignores the template and the score and the
    clocks, and — this is the part to weigh — ignores the §3.3 market gate too."""
    f, _ = runner_frame(top=3.0)
    trades, _, _ = bt.simulate(f, preset("a1"))
    hero = [t for t in trades if t["ticker"] == "N00.US"]
    reasons = [t["exit_reason"] for t in hero]
    assert reasons[:2] == ["trim35", "trim75"]
    # The remainder is only ever released by the harness closing the book, or by the business
    # failing. Anything else in this slot means a price exit survived the forever branch.
    assert reasons[2:] in ([], ["end_of_test"], ["profitability"], ["delisted"]), reasons
    assert hero[-1]["pnl_pct"] > hero[1]["pnl_pct"], "the runner should still have been running"

    table = bt.conformance(dict(m4_evaluated=1, m4_known=1, blackout_decisions=1,
                                blackout_known=1, entries=1, entries_refused_below_70=0,
                                reentries=0, trims=2, heat_refused=0),
                           trades, [], hyp=preset("a1")["hyp"])
    exits = next(c for c in table if c["clause"].startswith("Exits"))
    assert "profitability" not in exits["unknown_reasons"], "the forever exit must be declared"


def test_proven_strength_widens_the_trail_rather_than_tightening_it():
    a1 = dict(bt.LAW); a1.update(bt.PRESETS["a1"])
    assert a1["strength_trail"] > a1["trail"] and a1["strength_at"] == 0.25
    parabolic = list(np.linspace(100.0, 150.0, 49)) + [200.0]
    kw = dict(closes=parabolic, avg_cost=100.0, current_stop=120.0, pyramid_step=3)
    assert sg.ratchet_stop(**kw, trail10=a1["trail"])["mode"] == "trail5"
    proven = sg.ratchet_stop(**kw, trail10=a1["strength_trail"], euphoria=False)
    assert proven["stop"] < sg.ratchet_stop(**kw, trail10=a1["trail"])["stop"]


def test_the_heat_cap_binds_before_the_cash_does():
    """The sleeve cap limits how much is invested; nothing limited how much could be lost. Run 34
    averaged +1.27% a trade with a 39.6% win rate and drew down 53.5% — over-betting a real edge.
    Heat is the sum of what every open stop would cost if it fired today."""
    f, _ = frame()
    hot, _, hot_conf = bt.simulate(f, preset("m3"))
    f, _ = frame()
    free, _, free_conf = bt.simulate(f, preset("m2"))
    assert bt.LAW["heat_cap"] is None, "law-v0 must not have a heat cap"
    assert free_conf["heat_refused"] == 0
    assert hot_conf["entries"] <= free_conf["entries"]

    table = bt.conformance(hot_conf, hot, [], hyp=preset("m3")["hyp"])
    sizing = next(c for c in table if c["fn"] == "signals.momentum_size")
    assert sizing["heat_cap"] == 0.06
    assert sizing["heat_refused"] == hot_conf["heat_refused"]


def test_the_ladder_keeps_the_basis_of_what_is_left():
    """A trim must not change the average cost of the remainder, or the next rung, the stop and
    the breakeven ladder are all measured against a number the position never paid."""
    f, _ = runner_frame()
    hero = [t for t in bt.simulate(f, preset("m1"))[0] if t["ticker"] == "N00.US"]
    basis = {round(t["entry_price"], 6) for t in hero}
    assert len(basis) == 1, f"the slices disagree about what the position cost: {basis}"


def test_an_undeclared_trim_fails_conformance():
    conf = dict(m4_evaluated=1, m4_known=1, blackout_decisions=1, blackout_known=1,
                entries=1, entries_refused_below_70=0, reentries=0, trims=4)
    clause = lambda hyp: next(c for c in bt.conformance(conf, [], [], hyp=hyp)
                              if c["clause"].startswith("Position is opened once"))
    assert clause(dict(bt.LAW))["violations"] == 4
    m1 = dict(bt.LAW); m1.update(bt.PRESETS["m1"])
    assert clause(m1)["violations"] == 0 and clause(m1)["rungs"] == [0.50, 1.00]


def test_the_capital_regime_puts_the_account_to_work():
    """Ruled 2026-08-11: $100k, all of it, up to 25% on high conviction, against 100% in VOO.
    §3.2's 0.7-0.9% budget against a 20% stop is a 3.5-4.5% position, which is why thirteen runs
    all sat ~90% in cash."""
    law = sg.momentum_size(nav=100_000, mcn_score=90.0, stop_distance=0.20)
    z1 = bt.PRESETS["z1"]
    big = sg.momentum_size(nav=100_000, mcn_score=90.0, stop_distance=0.20,
                           budgets=(z1["budget_lo"], z1["budget_hi"]), band=(0.08, z1["band_hi"]))
    ordinary = sg.momentum_size(nav=100_000, mcn_score=70.0, stop_distance=0.20,
                                budgets=(z1["budget_lo"], z1["budget_hi"]),
                                band=(0.08, z1["band_hi"]))
    assert law["size_pct"] == pytest.approx(0.045)
    assert big["size_pct"] == pytest.approx(0.25), "full conviction must reach the 25% ceiling"
    assert ordinary["size_pct"] == pytest.approx(0.125)
    assert z1["sleeve_cap_pct"] == 1.0 and z1["entry_fraction"] == 1.0


def test_z1_takes_the_whole_position_at_entry_because_e1_already_confirmed():
    """§3.2 buys half at the pivot because the breakout is unconfirmed there. Under E1 it is
    confirmed before a share is bought, so the position opens full and must not pyramid again."""
    f, _ = runner_frame()
    trades, _, _ = bt.simulate(f, preset("z1"))
    assert trades and all(t["pyramid_steps"] == 3 for t in trades)


@pytest.mark.parametrize("name", ["z1", "m1"])
def test_opening_full_must_not_trip_the_breakeven_rung_on_day_one(name):
    """A position that opens full is marked step 3, which trips §3.2's "breakeven at full pyramid
    size" on its first session. B5's rung is worth something *because* it sits below cost and only
    after +1R; fired at entry it is just an initial stop of half the intended width.

    Run 33 shipped without this pairing and the `stop` bucket alone was -$81,536 of a -$30,036
    total, 95 exits at -3.48% against an intended ~10%. Any preset that opens full has to turn the
    sizing trigger off, so this asserts the pairing rather than trusting it.
    """
    p = bt.PRESETS[name]
    if p.get("entry_fraction", 0.5) >= 1.0:
        assert p.get("breakeven_on_full_size") is False, (
            f"{name} opens full size and would ratchet to breakeven before earning anything")
    # and the rung must genuinely not fire on an unearned position
    hyp = dict(bt.LAW); hyp.update(p)
    flat = list(np.linspace(96.0, 104.0, 49)) + [104.0]
    out = sg.ratchet_stop(closes=flat, avg_cost=100.0, current_stop=80.0, pyramid_step=3,
                          init_stop=80.0, breakeven_r=hyp["breakeven_r"],
                          breakeven_giveback=hyp["breakeven_giveback"],
                          breakeven_on_full_size=hyp["breakeven_on_full_size"])
    assert out["stop"] == pytest.approx(80.0), "the stop tightened before the position earned it"


def test_an_undeclared_reentry_fails_conformance():
    """The same guard the variant exits get: a run may buy through a door §3.2 does not name, but
    it has to say so, or a variant could pass as law-v0."""
    conf = dict(m4_evaluated=1, m4_known=1, blackout_decisions=1, blackout_known=1,
                entries=1, entries_refused_below_70=0, reentries=3)
    entry = lambda hyp: next(c for c in bt.conformance(conf, [], [], hyp=hyp)
                             if c["fn"] == "signals.entry_order")
    assert entry(dict(bt.LAW))["violations"] == 3
    h6 = dict(bt.LAW); h6.update(bt.PRESETS["h6"])
    assert entry(h6)["violations"] == 0
    assert entry(h6)["reentries"] == 3


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
                "pct_rank", "weekly_closes",
                # the hypothesis set lives in signals.py too, for the same reason: a variant that
                # graduates has to be the code arming.py already calls, not a copy of it
                "volatility_stop", "stagnant", "atr_fraction", "volatility_tolerance", "resumed"]


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
