"""A7: §3.2's dollar volume is one rule, on the code of record's basis. No database.

Three constructions of it exist, and they must not become three rules: `desk.grid` (what the
nightly sheet ranks on), `concentrated.build_grid` (the cell of record's grid), and
`shadow.sim_dollar_volume` (§6.4's sim side, built apart from the live arrays so the shadow can see
a difference between them). Fed the same bars in the vendor's shapes — a re-pulled 2:1 split, a
re-pulled 1:10 reverse split, a dividend history, a zero-padded delisting tail, missing volume and
a print on a day the market was shut — they must agree bar for bar, and a split may not move a
name's dollar volume at all, because it moves nothing about how much traded.
"""
import datetime as dt
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import concentrated                                                       # noqa: E402
import desk                                                               # noqa: E402
import engine                                                             # noqa: E402
import shadow                                                             # noqa: E402

TURNOVER = 30_000_000.0          # dollars a session, every session, for every name below
SPLIT_AT = 70


def _bars(n=120):
    """`desk.tape`'s rows — (ticker, d, adj_close-or-close, close, volume) — and the calendar."""
    sessions, d = [], dt.date(2025, 1, 6)
    while len(sessions) < n:
        if d.weekday() < 5:
            sessions.append(d)
        d += dt.timedelta(days=1)
    rng = np.random.default_rng(5)
    rows = []

    def series(drift):
        return 40.0 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))

    # A re-pulled split: the raw close prints `ratio` times the adjusted close before SPLIT_AT,
    # and the volume is restated in post-split shares. 2.0 is a 2:1; 0.1 is a 1:10 reverse.
    for ticker, ratio in (("FWD.US", 2.0), ("REV.US", 0.1)):
        adj = series(0.001)
        for k, day in enumerate(sessions):
            close = adj[k] * ratio if k < SPLIT_AT else adj[k]
            rows.append((ticker, day, float(adj[k]), float(close), int(round(TURNOVER / adj[k]))))
    # A dividend history: the adjusted close sits a little under the print before each ex-date,
    # and the volume is the print's.
    close = series(0.0005)
    factor = np.ones(n)
    for ex in (30, 90):
        factor[:ex] *= 0.985
    for k, day in enumerate(sessions):
        rows.append(("DIV.US", day, float(close[k] * factor[k]), float(close[k]),
                     int(round(TURNOVER / close[k]))))
    # A takeover's tail: the vendor pads the last bars with 0.0000 (learning 33).
    adj = series(0.0)
    for k, day in enumerate(sessions):
        px = 0.0 if k >= n - 3 else float(adj[k])
        rows.append(("ZERO.US", day, px, px, 0 if px == 0.0 else int(round(TURNOVER / px))))
    # Missing volume on a few bars, and a print on a Saturday.
    adj = series(0.0002)
    for k, day in enumerate(sessions):
        rows.append(("GAP.US", day, float(adj[k]), float(adj[k]),
                     None if k % 17 == 0 else int(round(TURNOVER / adj[k]))))
    rows.append(("GAP.US", sessions[50] + dt.timedelta(days=5), 1.0, 1.0, 10 ** 9))
    return sessions, rows


def test_the_live_grid_the_cell_of_records_grid_and_the_shadows_sim_side_are_one_rule():
    sessions, rows = _bars()
    tickers = sorted({r[0] for r in rows})
    dates, kept, _, _, record, *_ = concentrated.build_grid(
        [(t, d, close, a, v) for t, d, a, close, v in rows], set(sessions))
    assert dates == sessions and kept == tickers, "clean series: nothing dropped or quarantined"
    _, _, live = desk.grid(sessions, tickers, rows)
    np.testing.assert_array_equal(live, record, err_msg="the live grid is not the cell of record's")
    sim = shadow.sim_dollar_volume(sessions, tickers, rows)
    np.testing.assert_array_equal(sim, record, err_msg="the shadow's sim side is not build_grid's")


def test_a_split_does_not_move_a_names_dollar_volume():
    sessions, rows = _bars()
    tickers = sorted({r[0] for r in rows})
    adj, raw, dv = desk.grid(sessions, tickers, rows)
    for ticker, ratio in (("FWD.US", 2.0), ("REV.US", 0.1)):
        j = tickers.index(ticker)
        np.testing.assert_allclose(dv[:, j], TURNOVER, rtol=1e-5, err_msg=f"{ticker}: per bar")
        addv = [engine.median_addv(dv, i)[j] for i in range(SPLIT_AT - 5, len(sessions))]
        np.testing.assert_allclose(addv, TURNOVER, rtol=1e-5, err_msg=f"{ticker}: §3.2's median")
        # and the print is still the print: §3.2's $5 floor reads what actually traded
        assert abs(raw[SPLIT_AT - 1, j] / adj[SPLIT_AT - 1, j] - ratio) < 1e-12
        assert raw[SPLIT_AT, j] == adj[SPLIT_AT, j]
