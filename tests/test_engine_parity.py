"""§3's rule in `engine.py` must be the rule `concentrated.py` actually backtested.

`docs/yuna_plan.md` §3 names `b5_12_2_L1_3` as the cell of record and says "the engine's authority
is the code at that stamp". §6.3 builds a nightly job from that authority — so if `engine.rank`
and `concentrated.rank_at` ever disagree, the shadow (§6.4) diverges by construction and the live
book is not the book that was measured.

This repo has paid for two-copies-of-one-rule three times already: M4 acceleration, breakout
confirmation, and the duplicate-pair test that lived in SQL and numpy at once. This is the test
that stops it happening a fourth time, on the rule that IS the strategy.

Random tapes rather than hand-built ones, because the disagreements that matter are at the edges —
a tie, a name that just fails the bar count, an all-NaN column — and those are found by volume.
"""
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import engine                                                             # noqa: E402
import concentrated as cc                                                 # noqa: E402


def _tape(seed, n_names=40, n_days=700):
    """A tape with the awkward cases in it on purpose: dead names, penny names, thin names,
    a duplicate pair carrying an identical series, and gaps."""
    rng = np.random.default_rng(seed)
    adj = np.full((n_days, n_names), np.nan)
    dv = np.full((n_days, n_names), np.nan)
    for j in range(n_names):
        start = int(rng.integers(0, 120)) if j % 7 == 0 else 0
        px = 10 ** rng.uniform(-0.5, 2.2) * np.exp(np.cumsum(rng.normal(0.0004, 0.02, n_days - start)))
        adj[start:, j] = px
        dv[start:, j] = 10 ** rng.uniform(5.0, 9.0)
        if j % 11 == 0:                       # holes, so the bar count bites
            holes = rng.choice(np.arange(start, n_days), size=60, replace=False)
            adj[holes, j] = np.nan
            dv[holes, j] = np.nan
    if n_names > 2:                           # an exact duplicate: identical score, tie at the sort
        adj[:, 1] = adj[:, 0]
        dv[:, 1] = dv[:, 0]
    return adj, adj.copy(), dv             # raw == adj here; the screen reads raw only for the $5 bar


@pytest.mark.parametrize("seed", range(40))
def test_engine_rank_matches_the_backtested_rule(seed):
    adj, raw, dv = _tape(seed)
    i = adj.shape[0] - 1
    mine = engine.rank(i, adj, raw, dv)
    theirs = cc.rank_at(i, adj, raw, dv, risk_adjusted=True, top_by_addv=engine.POOL)
    assert mine == theirs, (
        f"seed {seed}: engine.rank and concentrated.rank_at disagree.\n"
        f"  engine  {mine[:12]}\n  backtest {theirs[:12]}")


def test_the_constants_are_the_ones_the_backtest_ran():
    """§3.6's table against the engine that produced the numbers in §3.1. A constant that drifted
    between the two would make every §3.1 figure a claim about a different strategy."""
    assert engine.FORMATION == cc.FORMATION
    assert engine.SKIP == cc.SKIP
    assert engine.VOL_WINDOW == cc.VOL_WINDOW
    assert engine.ADDV_WINDOW == cc.ADDV_WINDOW
    assert engine.SCREEN_MIN_BARS == cc.L0_MIN_BARS
    assert engine.SCREEN_MIN_PRICE == cc.L0_MIN_RAW
    assert engine.SCREEN_MIN_ADDV == cc.L0_MIN_ADDV


def test_a_tape_too_short_to_score_ranks_nobody():
    adj, raw, dv = _tape(0, n_days=200)
    assert engine.rank(199, adj, raw, dv) == []
