"""The capture audit, run over hand-built tapes.

The audit exists because runs 54-56 each passed conformance and the accounting invariants while
measuring the wrong arm, and the question that exposed all four defects was "did it buy NVIDIA".
An audit that cannot be trusted to count a push is worse than none — it would bless the next
defective run with a number — so every clause of the push definition is pinned here the way the
engine's clauses are pinned in test_backtest_engine.py.
"""
import datetime as dt
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import capture_audit as ca                                                  # noqa: E402


def sessions(n, start=dt.date(2024, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


DAYS = 400
DATES = sessions(DAYS)


def name_arrays(closes, *, vol=200_000.0, raw=None):
    do = np.array([d.toordinal() for d in DATES[:len(closes)]], dtype=np.int64)
    adj = np.asarray(closes, dtype=float)
    return dict(dates_ord=do, upos=np.arange(len(closes)),
                raw=np.asarray(raw, dtype=float) if raw is not None else adj.copy(),
                adj=adj, vol=np.full(len(closes), vol))


def winner_closes():
    """Flat for a year, then two clean +50% legs, then a decline that breaks out nowhere."""
    return np.concatenate([np.full(260, 100.0),
                           np.linspace(101.0, 155.0, 40),
                           np.linspace(156.0, 240.0, 40),
                           np.linspace(230.0, 200.0, 60)])


def run_pushes(closes, **kw):
    a = name_arrays(closes, **{k: v for k, v in kw.items() if k in ("vol", "raw")})
    return ca.pushes_for_name(a["dates_ord"], a["upos"], a["raw"], a["adj"], a["vol"],
                              start_ord=DATES[253].toordinal(),
                              end_ord=DATES[len(closes) - 1].toordinal())


# ------------------------------------------------------------------------------- the definition

def test_a_fifty_percent_leg_off_a_252_high_is_one_push_and_legs_chain():
    """Two +50% legs = two pushes, not two hundred new-high days. The chaining is what makes the
    denominator honest — without it a single NVDA year would count as an uncatchable crowd."""
    pushes, unresolved = run_pushes(winner_closes())
    assert len(pushes) == 2
    assert unresolved == 0
    first, second = pushes
    assert first["gain"] >= 0.50 and second["gain"] >= 0.50
    assert first["e"] < second["b"], "the second episode must start after the first completes"


def test_a_breakout_that_gives_the_level_back_is_not_a_push():
    """+17% then back below the breakout level: a failed breakout, counted in neither column."""
    closes = np.concatenate([np.full(260, 50.0),
                             np.linspace(51.0, 60.0, 30),        # +17%, never near +50%
                             np.linspace(59.0, 49.0, 30),        # ... and back through the level
                             np.full(80, 49.5)])
    pushes, unresolved = run_pushes(closes)
    assert pushes == [] and unresolved == 0


def test_a_race_the_window_ends_before_deciding_is_unresolved():
    closes = np.concatenate([np.full(260, 100.0),
                             np.linspace(101.0, 130.0, 140)])    # +29% and still going at the end
    pushes, unresolved = run_pushes(closes)
    assert pushes == [] and unresolved == 1


def test_the_five_dollar_floor_reads_the_raw_print_not_the_adjusted_one():
    """A $3 stock making a textbook push is not catchable — the census never admits it. And the
    floor must read the actual print: a split-adjusted history can sit anywhere."""
    c = winner_closes()
    pushes, _ = run_pushes(c, raw=np.full(len(c), 3.0))
    assert pushes == []
    pushes, _ = run_pushes(c)                                    # same tape, honest price
    assert len(pushes) == 2


def test_the_addv_floor_excludes_what_the_engine_could_never_buy():
    thin, _ = run_pushes(winner_closes(), vol=50.0)              # ~$5k/day traded
    assert thin == []


def test_the_breakout_is_strict_and_reads_the_prior_window():
    """Equal to the old high is not a breakout — `signals.new_high_breakout` uses strict >, and
    the audit must count exactly the events the door can see."""
    closes = np.concatenate([np.full(300, 100.0), np.full(100, 100.0)])   # never exceeds
    pushes, unresolved = run_pushes(closes)
    assert pushes == [] and unresolved == 0


# ------------------------------------------------------------------------- net / ride / junk

def fixture_rows():
    rows = []
    series = {"FAIL.US": np.concatenate([np.full(260, 50.0),
                                         np.linspace(51.0, 60.0, 30),
                                         np.linspace(59.0, 49.0, 30),
                                         np.full(80, 49.5)]),
              "PENNY.US": winner_closes() * 0.03,                # a $3 print end to end
              "WINNER.US": winner_closes()}
    for tk in sorted(series):
        for d, px in zip(DATES, series[tk]):
            rows.append((tk, d, float(px), float(px), 200_000.0))
    return rows


def fixture_run():
    return dict(id=99, label="test", start_date=DATES[253], end_date=DATES[-1],
                hypothesis="a2")


def test_the_net_the_ride_and_the_junk():
    run = fixture_run()
    # one position riding most of WINNER's first push, one on FAIL that overlaps no push
    positions = [dict(ticker="WINNER.US", entry=DATES[270], exit=DATES[290], qty=10.0,
                      entry_price=115.0, pnl=470.0),
                 dict(ticker="FAIL.US", entry=DATES[262], exit=DATES[270], qty=20.0,
                      entry_price=51.0, pnl=-100.0)]
    out = ca.audit(run, positions, fixture_rows())

    # THE NET — WINNER pushed twice, the arm entered once; PENNY's pushes never count
    assert out["net"]["pushes"] == 2
    assert out["net"]["caught"] == 1
    assert out["net"]["fraction"] == pytest.approx(0.5)

    # THE RIDE — share kept is the position's P&L against holding its own entry to the +50% mark
    assert out["ride"]["pushes_measurable"] == 1
    caught = next(p for p in out["caught_top"])
    assert caught["ticker"] == "WINNER.US"
    assert caught["hold_to_end_pnl"] > 0
    assert caught["ride_share"] == pytest.approx(caught["actual_pnl"]
                                                 / caught["hold_to_end_pnl"], abs=1e-4)
    assert out["ride"]["dollar_share"] == pytest.approx(caught["ride_share"], abs=1e-4)

    # THE JUNK — the FAIL position overlapped nothing that qualified
    assert out["junk"]["positions"] == 2
    assert out["junk"]["junk"] == 1
    assert out["junk"]["junk_pnl_usd"] == pytest.approx(-100.0)

    # the "did it buy NVIDIA" table: the missed second leg is on it
    assert any(p["ticker"] == "WINNER.US" for p in out["missed_top"])
    assert all(p["gain"] >= 0.50 for p in out["missed_top"])


def test_a_position_entered_before_the_breakout_still_counts_as_caught():
    """A trend-holder that bought early and held through the push caught it by any honest
    reading — overlap is entry <= completion and exit >= breakout, not entry inside the window."""
    run = fixture_run()
    positions = [dict(ticker="WINNER.US", entry=DATES[255], exit=DATES[310], qty=10.0,
                      entry_price=100.0, pnl=3_000.0)]
    out = ca.audit(run, positions, fixture_rows())
    assert out["net"]["caught"] >= 1
    assert out["junk"]["junk"] == 0


def test_an_empty_book_is_all_net_and_no_ride():
    out = ca.audit(fixture_run(), [], fixture_rows())
    assert out["net"]["pushes"] == 2 and out["net"]["caught"] == 0
    assert out["ride"]["dollar_share"] is None
    assert out["junk"]["positions"] == 0
    assert out["junk"]["share"] is None
