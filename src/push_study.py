"""push_study — every episode on the census, with its gates and its autopsy (WO-A3 §2).

The capture audit counts what a RUN caught. This writes down the market side of the ledger:
one row per episode — push, failed breakout, unresolved race — sharing the audit's own walk
(`capture_audit.episodes_for_name`, one definition, never two), decorated with:

  * every candidate gate's value AT the breakout, computed on bars <= b so a look-ahead is
    impossible by construction rather than by care;
  * for completed pushes, the exit autopsy: the deepest pullback from the running high on the
    way to +50% (the trail width the push actually NEEDED, in fraction and in ATR multiples),
    and whether each candidate exit — a 3xATR trailing stop, the 10- and 20-session MA trails,
    the name's own 100-session MA — would have survived to the target.

Gates are then measured with SQL against the table. A gate that shows no lift on our own nine
years dies without costing a trial; the ones that survive become A3's pre-registered spec.

    python src/push_study.py            # window: E-series (2017-09-01 -> last bar)
    START_DATE / END_DATE               # override the window

Idempotent per window: existing rows for the same (window_start, window_end) are replaced.
DRY_RUN walks and prints the totals, writes nothing.
"""
import os
import sys
import datetime as dt

import numpy as np

from db import connect, dry, Heartbeat
from capture_audit import episodes_for_name, load_tape, LOOKBACK
import signals as sg

DEFAULT_START = dt.date(2017, 9, 1)      # the E-series record's window (runs 46+)
GATE_INDEX = "GSPC.INDX"                 # Clenow's regime gate reads the index itself
REGIME_SMA = 200                         # ... above its 200-session SMA (wo-a3 §2)
SLOPE_WINDOW = 90                        # Clenow's regression window
SMOOTH_WINDOW = 126                      # frog-in-the-pan's formation half-year
VOL_WINDOW = 90
ATR_WINDOW = 20                          # the engine's own A2 stop window
SESSIONS_PER_YEAR = 252


def exp_regression(closes):
    """Annualized exponential regression slope and R² — `signals.regression_momentum`, which is
    the law's home for the formula. A second implementation here is how the study's lifts and
    the engine's ranking would silently measure two different scores."""
    out = sg.regression_momentum(closes, window=SLOPE_WINDOW,
                                 sessions_per_year=SESSIONS_PER_YEAR)
    return (out["slope_ann"], out["r2"]) if out else (None, None)


def atr20(high, low, close):
    """ATR(20) in dollars on the last bar, Wilder-free simple mean of true ranges — the study
    needs a magnitude, not the engine's smoothing; the engine's own ATR stays in signals.py."""
    h, l, c = (np.asarray(a, dtype=float) for a in (high, low, close))
    if len(c) < ATR_WINDOW + 1:
        return None
    prev = c[-(ATR_WINDOW + 1):-1]
    hh, ll = h[-ATR_WINDOW:], l[-ATR_WINDOW:]
    tr = np.maximum(hh - ll, np.maximum(np.abs(hh - prev), np.abs(ll - prev)))
    return float(tr.mean())


def features_at(b, adj, high, low, raw, prior_push_e):
    """Every candidate gate at own-bar index b, on bars <= b only."""
    c = adj[:b + 1]
    rets = np.diff(c[-(SMOOTH_WINDOW + 1):]) / c[-(SMOOTH_WINDOW + 1):-1] \
        if len(c) >= SMOOTH_WINDOW + 1 else np.diff(c) / c[:-1]
    r90 = rets[-VOL_WINDOW:] if len(rets) >= VOL_WINDOW else rets
    slope, r2 = exp_regression(c)
    atr = atr20(high[:b + 1], low[:b + 1], c)
    out = dict(
        slope_ann_90=slope, r2_90=r2,
        slope_r2_90=(slope * r2) if slope is not None and r2 is not None else None,
        up_share_126=float((rets > 0).mean()) if len(rets) else None,
        ret_vol_90=float(r90.std(ddof=1)) if len(r90) > 2 else None,
        max_move_90=float(np.abs(r90).max()) if len(r90) else None,
        atr_frac_20=(atr / float(c[-1])) if atr else None,
        raw_close=float(raw[b]),
        prior_gain_126=float(c[-1] / c[-127] - 1.0) if len(c) >= 127 else None,
        prior_gain_252=float(c[-1] / c[-253] - 1.0) if len(c) >= 253 else None,
        dist_50dma=float(c[-1] / c[-50:].mean() - 1.0) if len(c) >= 50 else None,
        sessions_since_push=(b - prior_push_e) if prior_push_e is not None else None,
        atr_dollars=atr)
    return out


def exit_autopsy(b, e, atr_dollars, adj):
    """For a completed push: what the ride demanded, and which exits survive it.

    All series are the name's own closes over (b, e]. The trail and both short MAs are judged
    the way the practitioners state them — a CLOSE below the line, checked before the target
    bar; the target bar itself counts as arrival, not as an exit."""
    path = adj[b:e + 1]                                  # includes b and e
    if atr_dollars is None or len(path) < 2:
        return dict(needed_trail_frac=None, needed_trail_atr=None, survives_trail_3atr=None,
                    survives_ma10=None, survives_ma20=None, survives_ma100=None)
    run_max = np.maximum.accumulate(path)
    give = run_max - path
    needed_frac = float((give / run_max).max())
    needed_atr = float((give / atr_dollars).max())

    def survives_trail(mult):
        for k in range(1, len(path) - 1):                # the final bar is arrival
            if path[k] < run_max[k] - mult * atr_dollars:
                return False
        return True

    def survives_ma(window):
        for k in range(1, len(path) - 1):
            j = b + k
            if j + 1 >= window and path[k] < float(adj[j - window + 1:j + 1].mean()):
                return False
        return True

    return dict(needed_trail_frac=needed_frac, needed_trail_atr=needed_atr,
                survives_trail_3atr=survives_trail(3.0),
                survives_ma10=survives_ma(10), survives_ma20=survives_ma(20),
                survives_ma100=survives_ma(100))


def regime_series(cur):
    cur.execute("select d, close from prices where ticker = %s order by d", (GATE_INDEX,))
    rows = cur.fetchall()
    if len(rows) < REGIME_SMA:
        raise RuntimeError(f"{GATE_INDEX} holds {len(rows)} bars — the regime gate cannot be "
                           f"computed, and a study without it would silently drop a column")
    dates = np.array([r[0].toordinal() for r in rows], dtype=np.int64)
    close = np.array([float(r[1]) for r in rows])
    sma = np.full(len(close), np.nan)
    kernel = np.ones(REGIME_SMA) / REGIME_SMA
    sma[REGIME_SMA - 1:] = np.convolve(close, kernel, mode="valid")
    return dates, close, sma


def regime_on(dates, close, sma, day_ord):
    i = int(np.searchsorted(dates, day_ord, side="right")) - 1
    if i < 0 or not np.isfinite(sma[i]):
        return None
    return bool(close[i] > sma[i])


def main():
    start = (dt.date.fromisoformat(os.environ["START_DATE"])
             if os.environ.get("START_DATE") else DEFAULT_START)
    end_env = os.environ.get("END_DATE")

    with connect() as conn:
        with Heartbeat(conn, "push_study") as hb:
            with conn.cursor() as cur:
                tape = load_tape(cur, with_range=True)
                g_dates, g_close, g_sma = regime_series(cur)
            end = dt.date.fromisoformat(end_env) if end_env else max(d for _, d, *_ in tape)
            start_ord, end_ord = start.toordinal(), end.toordinal()

            all_dates = sorted({d for _, d, *_ in tape})
            union = np.array([d.toordinal() for d in all_dates], dtype=np.int64)

            rows_out, counts = [], {"push": 0, "failed": 0, "unresolved": 0}
            current, buf = None, None

            def flush():
                if current is None or not buf["d"]:
                    return
                do = np.array(buf["d"], dtype=np.int64)
                adj = np.array(buf["adj"], dtype=float)
                keep = adj > 0.0
                do, adj = do[keep], adj[keep]
                raw = np.array(buf["raw"], dtype=float)[keep]
                vol = np.array(buf["vol"], dtype=float)[keep]
                # the engine rescales the whole bar by the day's adj/close factor so the bar
                # keeps its geometry across splits — the ATR here must see the same tape
                factor = np.where(raw > 0, adj / raw, 1.0)
                high = np.array(buf["high"], dtype=float)[keep] * factor
                low = np.array(buf["low"], dtype=float)[keep] * factor
                upos = np.searchsorted(union, do)
                eps = episodes_for_name(do, upos, raw, adj, vol,
                                        start_ord=start_ord, end_ord=end_ord)
                prior_e = None
                for ep in eps:
                    counts[ep["kind"]] += 1
                    b, e = ep["b"], ep["e"]
                    f = features_at(b, adj, high, low, raw, prior_e)
                    autopsy = (exit_autopsy(b, e, f["atr_dollars"], adj)
                               if ep["kind"] == "push" else
                               dict(needed_trail_frac=None, needed_trail_atr=None,
                                    survives_trail_3atr=None, survives_ma10=None,
                                    survives_ma20=None, survives_ma100=None))
                    if ep["kind"] == "push":
                        prior_e = e
                    rows_out.append(dict(
                        window_start=start, window_end=end, ticker=current,
                        b=dt.date.fromordinal(int(do[b])), outcome=ep["kind"],
                        e=dt.date.fromordinal(int(do[e])) if e is not None else None,
                        level=ep["level"], gain=ep["gain"],
                        sessions_to_resolve=(e - b) if e is not None else None,
                        addv_50=ep["addv"],
                        regime_on=regime_on(g_dates, g_close, g_sma, int(do[b])),
                        **{k: v for k, v in f.items() if k != "atr_dollars"},
                        **autopsy))

            for tk, d, close, adj, vol, high, low in tape:
                if tk != current:
                    flush()
                    current = tk
                    buf = dict(d=[], raw=[], adj=[], vol=[], high=[], low=[])
                buf["d"].append(d.toordinal())
                buf["raw"].append(float(close) if close is not None else np.nan)
                buf["adj"].append(float(adj) if adj is not None else 0.0)
                buf["vol"].append(float(vol) if vol is not None else np.nan)
                buf["high"].append(float(high) if high is not None else np.nan)
                buf["low"].append(float(low) if low is not None else np.nan)
            flush()

            print(f"episodes {start} -> {end}: "
                  + " · ".join(f"{k} {v}" for k, v in counts.items())
                  + f" · {len(rows_out)} rows")
            hb.detail.update(counts=counts, window=[str(start), str(end)])
            hb.rows = len(rows_out)

            if not rows_out:
                raise RuntimeError(
                    f"zero episodes on {start} -> {end} — nine years of tape cannot contain no "
                    f"breakouts, so the window or the tape is wrong; refusing to write an empty "
                    f"study that would read as 'measured, nothing there'")
            if dry():
                print("DRY_RUN — nothing written")
                return 0
            with conn.cursor() as cur:
                cur.execute("delete from push_study where window_start=%s and window_end=%s",
                            (start, end))
                cols = list(rows_out[0].keys())
                cur.executemany(
                    f"insert into push_study ({', '.join(cols)}) "
                    f"values ({', '.join('%(' + c + ')s' for c in cols)})", rows_out)
            conn.commit()
            print(f"push_study replaced for window {start} -> {end}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
