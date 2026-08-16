"""blend — E4, the buy alternative, priced (WO-A3 §1; E-series WO §3-E4).

VOO core + SPMO tilt, arms {100/0, 90/10, 80/20}, weekly banded true-up per §2.1 mechanics —
check every PARK_CHECK_EVERY sessions, trade only when the tilt weight has drifted more than
PARK_BAND from target — with §2.2 costs selected from the spread curve by each ETF's own
50-session median dollar volume at the trade date. Dividends arrive through adjusted closes.

Two windows per arm: SPMO's full history (its bars begin 2015-10), and the window matched to
the E-series record (sessions from 2017-09-01), so the blend is comparable both on its own
terms and against every arm in the ledger. Each run row is scored §2.5-style on the spot (full
+ Aug-2025 OOS cuts via `finding`), with one deliberate absence: **no deflated Sharpe and no
param_hash** — these rows are benchmarks, not strategy trials, and must enter neither the
trial-Sharpe spread nor the configuration count.

Role, per the E-series WO: once run, the best blend joins §2.3 as the bar every active result
must clear. If nothing active clears it, the honest terminus is holding the blend.

    python src/blend.py          # runs all six (three arms x two windows)

DRY_RUN computes and prints, writes nothing. The 100/0 arm is the control: it must reproduce
the benchmark column to within costs, or the simulator is wrong.
"""
import os
import sys
import json
import hashlib
import pathlib
import datetime as dt

import numpy as np

from db import connect, dry, Heartbeat
from backtest import PARK_CHECK_EVERY, PARK_BAND, SPREAD_CURVE, BENCH
import finding

TILT = "SPMO.US"
# (VOO weight, SPMO weight). The first three are the WO's pre-registered arms. The last two are
# the CONTROLS the park-tilt ladder demands: a1v_b100 parks the whole idle account in SPMO and
# returns 21.17%, and the only way to know whether the momentum SLEEVE earned any of that is to
# price the same vehicle holding nothing else. A sleeve that cannot beat its own park is a sleeve
# doing nothing but adding turnover.
ARMS = ((1.0, 0.0), (0.9, 0.1), (0.8, 0.2), (0.5, 0.5), (0.0, 1.0))
ESERIES_START = dt.date(2017, 9, 1)                  # the record's matched window (runs 46+)
ADDV_WINDOW = 50                                     # §2.2 selects by 50-session median $vol


def spread_bps(addv):
    """§2.2: descending, first match wins, unknown falls to the worst bucket."""
    for floor, bps in SPREAD_CURVE:
        if addv >= floor:
            return bps
    return SPREAD_CURVE[-1][1]


def load_series(cur, ticker):
    cur.execute("""select d, coalesce(adj_close, close), close, volume
                     from prices where ticker = %s and coalesce(adj_close, close) > 0
                    order by d""", (ticker,))
    rows = cur.fetchall()
    if not rows:
        raise RuntimeError(f"no bars for {ticker} — E4 cannot price a blend without them")
    dates = [r[0] for r in rows]
    adj = np.array([float(r[1]) for r in rows])
    raw = np.array([float(r[2]) for r in rows])
    vol = np.array([float(r[3]) if r[3] is not None else np.nan for r in rows])
    # dollar volume on the raw print — the engine's ADDV uses adjusted x volume, but for an ETF
    # with no splits in-window the two agree; raw is used because both are current listings
    dollar = raw * vol
    addv = np.full(len(rows), np.nan)
    for i in range(len(rows)):
        k = max(0, i - (ADDV_WINDOW - 1))
        window = dollar[k:i + 1]
        addv[i] = np.nanmedian(window) if not np.all(np.isnan(window)) else np.nan
    return dates, adj, addv


def simulate_blend(dates, core_px, tilt_px, core_addv, tilt_addv, *,
                   core_w, tilt_w, start_nav, check_every=PARK_CHECK_EVERY, band=PARK_BAND):
    """One blend arm over one window. Pure — arrays in, path out.

    Costs are charged as half-spread per side on every traded dollar, each leg at its own ETF's
    §2.2 bucket, and they come out of the account AT the trade: the post-trade book is the exact
    target weights on (NAV − cost). No cash leg exists, so borrowing is impossible by
    construction — the identity NAV = core + tilt holds on every row. (Cost-on-cost second-order
    terms are ignored; at 5 bps on a handful of true-ups a decade they are sub-cent noise.)
    """
    bps = lambda addv: spread_bps(addv if np.isfinite(addv) else 0.0) / 10_000.0

    init_cost = start_nav * (core_w * bps(core_addv[0]) + tilt_w * bps(tilt_addv[0]))
    eff = start_nav - init_cost
    core_sh = eff * core_w / core_px[0]
    tilt_sh = eff * tilt_w / tilt_px[0] if tilt_w else 0.0
    cost_total, trueups = init_cost, 0

    equity = []
    for i in range(len(dates)):
        cv, tv = core_sh * core_px[i], tilt_sh * tilt_px[i]
        if tilt_w and i and i % check_every == 0:
            nav = cv + tv
            if abs(tv / nav - tilt_w) > band:
                cost = (abs(cv - nav * core_w) * bps(core_addv[i])
                        + abs(tv - nav * tilt_w) * bps(tilt_addv[i]))
                eff = nav - cost
                core_sh, tilt_sh = eff * core_w / core_px[i], eff * tilt_w / tilt_px[i]
                cost_total += cost
                trueups += 1
                cv, tv = core_sh * core_px[i], tilt_sh * tilt_px[i]
        equity.append((dates[i], cv + tv, core_px[i]))
    return equity, trueups, cost_total


def main():
    here = pathlib.Path(__file__).resolve().parent
    code = hashlib.sha256((here / "blend.py").read_bytes()).hexdigest()[:16]
    start_nav = float(os.environ.get("START_NAV", "200000"))

    with connect() as conn:
        with Heartbeat(conn, "blend") as hb:
            with conn.cursor() as cur:
                dates_c, core, addv_c = load_series(cur, BENCH)
                dates_t, tilt, addv_t = load_series(cur, TILT)
            common = sorted(set(dates_c) & set(dates_t))
            ic = {d: i for i, d in enumerate(dates_c)}
            it = {d: i for i, d in enumerate(dates_t)}
            windows = [("full", common),
                       ("e-series", [d for d in common if d >= ESERIES_START])]

            written = []
            for wname, days in windows:
                c_px = np.array([core[ic[d]] for d in days])
                t_px = np.array([tilt[it[d]] for d in days])
                c_ad = np.array([addv_c[ic[d]] for d in days])
                t_ad = np.array([addv_t[it[d]] for d in days])
                for core_w, tilt_w in ARMS:
                    equity, trueups, cost = simulate_blend(
                        days, c_px, t_px, c_ad, t_ad,
                        core_w=core_w, tilt_w=tilt_w, start_nav=start_nav)
                    nav = np.array([e[1] for e in equity])
                    dd = nav / np.maximum.accumulate(nav) - 1.0
                    years = max((days[-1] - days[0]).days / 365.25, 1e-9)
                    total = float(nav[-1] / nav[0] - 1)

                    rows = [(d, float(v), float(b)) for d, v, b in equity]
                    full = finding.score_cut(finding.cut(rows, []))
                    try:
                        oos = finding.score_cut(finding.cut(rows, [], since=finding.OOS_START))
                    except RuntimeError:
                        oos = None                     # a window ending before the cut has no OOS
                    label = (f"E4 · VOO/SPMO {int(core_w * 100)}/{int(tilt_w * 100)} · "
                             f"{wname} window")
                    stats = dict(
                        blend=dict(core=BENCH, tilt=TILT, core_w=core_w, tilt_w=tilt_w,
                                   check_every=PARK_CHECK_EVERY, band=PARK_BAND,
                                   trueups=trueups, cost_usd=round(cost, 2)),
                        bars_25=dict(source="wo-a3-2026-08-13 §1",
                                     full=full, oos=oos,
                                     dsr="not applicable — benchmark row, not a strategy trial"),
                        conformance_ok=True, exits={})
                    params = dict(variant=f"e4_{int(core_w * 100)}_{int(tilt_w * 100)}",
                                  hypothesis="e4", window=wname, currency="USD",
                                  benchmark=BENCH, start_nav=start_nav, code_stamp=code,
                                  blend=stats["blend"])
                    print(f"{label}: {total:+.2%} · CAGR {(1 + total) ** (1 / years) - 1:.2%} · "
                          f"maxDD {dd.min():+.1%} · true-ups {trueups} · cost ${cost:,.0f}")

                    if not dry():
                        with conn.cursor() as cur:
                            cur.execute("""insert into backtest_runs(label, params, start_date,
                                  end_date, trading_days, start_nav, end_nav, total_return, cagr,
                                  max_drawdown, max_dd_date, trades, stats)
                                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                                (label, json.dumps(params), days[0], days[-1], len(days),
                                 start_nav, float(nav[-1]), total,
                                 float((1 + total) ** (1 / years) - 1),
                                 float(dd.min()), days[int(np.argmin(dd))], trueups,
                                 json.dumps(stats, default=str)))
                            rid = cur.fetchone()[0]
                            cur.executemany("""insert into backtest_equity(run_id, d, nav,
                                  exposure, positions, gate, benchmark)
                                values (%s,%s,%s,%s,%s,%s,%s)""",
                                [(rid, d, v, tilt_w, 2 if tilt_w else 1, None, b)
                                 for d, v, b in rows])
                        conn.commit()
                        written.append(rid)
                        print(f"  run {rid} written and scored")

            hb.rows = len(written)
            hb.detail["runs"] = written
    return 0


if __name__ == "__main__":
    sys.exit(main())
