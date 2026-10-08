"""A34: the window `desk.tape` loads covers every read of the tape it feeds. No database.

`desk.tape` loads only the sessions §3 reads, derived from `desk.reads()` — and, for the shadow,
`shadow.sim_reads()` too. That is safe exactly as long as the declarations are complete, so every
row before the window is poisoned here and every function the tape feeds must answer as it did on
the whole tape. A read added deeper than the declarations fails this test instead of reading NaN in
production, where a NaN looks exactly like a name that never printed: the screen drops it and
nothing is raised anywhere.
"""
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import concentrated                                                       # noqa: E402
import desk                                                               # noqa: E402
import engine                                                             # noqa: E402
import shadow                                                             # noqa: E402


def _tape(n=700, names=60, seed=11):
    """A tape with a spread of drifts and volatilities, holes, and some names on a raw basis that
    is not the adjusted one, so every clause of the screen and the score has something to decide."""
    rng = np.random.default_rng(seed)
    drift = np.linspace(-0.001, 0.002, names)
    vol = rng.uniform(0.008, 0.03, names)
    adj = 50.0 * np.exp(np.cumsum(rng.normal(drift, vol, (n, names)), axis=0))
    adj[rng.random((n, names)) < 0.03] = np.nan
    raw = adj * np.where(np.arange(names) % 4 == 0, 2.0, 1.0)
    dv = adj * rng.uniform(5e4, 5e6, (n, names))
    return adj, raw, dv


def _answers(i, adj, raw, dv):
    return dict(
        rank=engine.rank(i, adj, raw, dv),
        survivors=[int(j) for j in engine.screen(i, adj, raw, dv, pool=None)],
        pool=[int(j) for j in engine.screen(i, adj, raw, dv, pool=20)],
        addv=engine.median_addv(dv, i).tolist(),
        sim=concentrated.rank_at(i, adj, raw, dv, risk_adjusted=True, top_by_addv=20))


def _poisoned(arrays, upto, how):
    out = []
    for k, a in enumerate(arrays):
        b = a.copy()
        if how == "nan":                        # what the bounded load actually leaves there
            b[:upto] = np.nan
        else:                                   # what no read could pass through unchanged
            b[:upto] = np.random.default_rng(k).uniform(1e-3, 1e6, b[:upto].shape)
        out.append(b)
    return out


def test_every_read_of_the_tape_lies_inside_the_window_and_the_window_is_not_padded():
    adj, raw, dv = _tape()
    need = {**desk.reads(), **shadow.sim_reads()}
    for i in (adj.shape[0] - 1, adj.shape[0] - 40, 400):
        first = i - max(need.values())
        whole = _answers(i, adj, raw, dv)
        assert whole["rank"] and whole["sim"], "the tape must rank something, or this proves nothing"
        for how in ("nan", "wild"):
            got = _answers(i, *_poisoned((adj, raw, dv), first, how))
            assert got == whole, f"session {i}: a read reached before the window ({how})"
        # and the window is the reads, not a margin: poison its first row too and the rank moves
        got = _answers(i, *_poisoned((adj, raw, dv), first + 1, "wild"))
        assert got["rank"] != whole["rank"], f"session {i}: the window's first row is never read"


def test_a_window_that_falls_short_of_a_read_halts_and_names_it():
    """`desk.tape` derives the window from the reads, so this guard cannot fire as written — it is
    there for the day the window is narrowed by hand. It has to halt rather than warn."""
    with pytest.raises(SystemExit, match=r"§3.3 vol \(252 back\)"):
        desk.covered({"§3.3 vol": 252, "§3.2 ADDV": 49}, i=1000, lo=800)
    desk.covered({"§3.3 vol": 252}, i=1000, lo=748)      # exactly enough
    desk.covered({"§3.3 vol": 252}, i=100, lo=0)         # a short history is the whole history
