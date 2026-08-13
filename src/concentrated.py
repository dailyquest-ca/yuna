"""concentrated — the winner-catcher, tested on its own terms (WO-A4).

Zak, 2026-08-13: *"There IS a combination of buying stocks over the year that went very high value
very quickly... I'm talking about picking out the winners... and only what is going to our momentum
sleeve is cycled into potential big winners like MRVL, GOOGL, SQ, MU... catching all of the +100%
within a year... and we don't want A LOT of trades, like 10-15 names a year, because we want to
work our day job."*

That is a different shape from everything the E-series ran, and the difference is the point:

  * A2 and A3 were BREADTH arms — thirty slots, thousands of trades, catching a large share of a
    large population. They measured well and returned badly.
  * This is a PRECISION arm. The census says 50-282 liquid names double in a given year (median
    ~140 of roughly 3,000 eligible, so a ~5% base rate). Holding 10-15 of them at a time, changed
    a few times a year, is a dozen-odd decisions a year — a book a person with a job can actually
    run.

**Almost no §3.2 machinery.** No base detection, no pivot, no MCN, no confirmation state machine,
no trim ladder. Today's session spent five runs discovering that every new strategy shape inherits
the law's defaults until each one is explicitly switched off. This module holds one idea and
implements only that idea: rank the liquid universe by trend, hold the top N, change the book on
a slow clock, park the rest in the momentum ETF.

The one exception is the **stop**, and it was added because the first grid measured what its
absence costs. A book with no exit between rebalances bought in December 2025 and could not change
its mind until the end of June 2026; it peaked at $1.73M on 2025-10-15 and troughed at $670k on
2026-07-29. Two cheap fixes were tried against that and BOTH failed, measured:

  * **A large-cap pool** (`top_by_addv`) moved the drawdown the wrong way — -56.5% over the full
    universe became -61.3% at the top 500 and -60.6% at the top 250. At a momentum peak the
    most-traded names *are* the crowded trade; restricting to them concentrates the crash.
  * **A market regime gate** (`gated`) did nothing at all: -61.28% gated against -61.28% ungated,
    identical to four decimals, because VOO never closed below its own 200-day between 2025-11 and
    2026-07 while the book lost 61%. The gate was watching the wrong series.

So the cells carrying `trail=True` run §3.2's own ratchet per name, every session — the exit the
plan already legislates and this arm was built without. `vol_target` carries the other half of the
answer: Barroso & Santa-Clara's finding is that a momentum crash is forecastable from the
**strategy's** realized volatility, which is the series the failed gate should have been watching.

Deliberate design choices, each with its source:

  * **12-1 momentum** — the twelve-month return skipping the most recent month, the academic
    standard and SPMO's own published methodology (which measures 12 months excluding the last,
    then adjusts for volatility). `risk_adjusted` divides by the realized volatility of daily
    returns, which is SPMO's adjustment and the Clenow R-squared idea in a cheaper form.
  * **A slow clock.** Rebalancing quarterly or semi-annually is what keeps the trade count near a
    dozen a year; it is also what the momentum literature finds survives costs at small AUM.
  * **The park.** Idle capital sits in SPMO, per the measured ladder: on this window the vehicle
    returned 21.12% CAGR alone, and every point of the account not in a single name earns it.
  * **Costs** are §2.2's curve, charged per side on every traded dollar.

    python src/concentrated.py          # the announced grid
    CELLS='n10_semi,n15_quarterly'      # or a named subset

Writes one `backtest_runs` row per cell and scores each with `finding`, exactly like every other
arm, so these numbers sit in the same ledger under the same bars.
"""
import os
import sys
import json
import hashlib
import pathlib
import datetime as dt

import numpy as np

from db import connect, dry, Heartbeat
from backtest import SPREAD_CURVE, BENCH, PARK_BAND, param_digest
from capture_audit import load_tape
import finding

PARK_TICKER = "SPMO.US"
FORMATION = 252          # the twelve months the rank is measured over
SKIP = 21                # ... minus the most recent month (12-1, the standard)
VOL_WINDOW = 252
L0_MIN_BARS = 210
L0_MIN_RAW = 5.0
L0_MIN_ADDV = 10_000_000.0
ADDV_WINDOW = 50

# §3.2 Stops, verbatim — the exit this book was built without. Every number is the plan's:
#   "Initial: higher of the base's final-contraction low, or entry - 8%. Never wider than 8%."
#     A rank book has no base, so the final-contraction low does not exist and the 8% half binds.
#   "Ratchet: ... +15% from average cost -> trail 10% below highest close since entry ·
#    stops ratchet up, never down."
#   "Euphoria rule - tighten, never sell: when price closes > 2 standard deviations above its
#    own 50-day (std dev of closes, 50-day window) -> trail tightens to 5% below highest close."
TRAIL_INITIAL = 0.08
TRAIL_ARM = 0.15
TRAIL_WIDE = 0.10
TRAIL_EUPHORIA = 0.05
EUPHORIA_WINDOW = 50
EUPHORIA_SD = 2.0
# Barroso-Santa-Clara's governor, the paper's own constants as `backtest.py` already declares
# them for A3 (vol_target=0.12, vol_window=126). PARK_BAND is §2.1's park deadband, reused for
# its own purpose: how far the parked weight may drift before it is worth a trade.
VOL_TARGET_WINDOW = 126

# The announced grid (WO-A4). One axis moves per cell against the centre `n12_semi`.
CELLS = {
    # centre: twelve names, changed twice a year, risk-adjusted rank, whole account in the sleeve
    "n12_semi":       dict(n=12, months=6, risk_adjusted=True,  sleeve=1.00),
    # how many names — the concentration axis Zak's ask is really about
    "n8_semi":        dict(n=8,  months=6, risk_adjusted=True,  sleeve=1.00),
    "n20_semi":       dict(n=20, months=6, risk_adjusted=True,  sleeve=1.00),
    # how often the book changes — the trade-count axis, and the day-job constraint
    "n12_quarterly":  dict(n=12, months=3, risk_adjusted=True,  sleeve=1.00),
    "n12_annual":     dict(n=12, months=12, risk_adjusted=True, sleeve=1.00),
    # raw 12-1 against the volatility-adjusted rank — SPMO's own adjustment, priced
    "n12_semi_raw":   dict(n=12, months=6, risk_adjusted=False, sleeve=1.00),
    # the sleeve fraction: the rest parked in SPMO, which is the shape Zak described
    "n12_semi_half":  dict(n=12, months=6, risk_adjusted=True,  sleeve=0.50),
    "n12_semi_third": dict(n=12, months=6, risk_adjusted=True,  sleeve=0.30),
    # ---- the large-cap pool. SPMO ranks inside the S&P 500; these rank inside the 500
    # most-traded names, which is the closest point-in-time proxy the store supports. Zak's own
    # examples — MRVL, GOOGL, SQ, MU — are all large caps, and the full-universe cells above
    # measured what happens without the restriction: -56.5% drawdowns on a 16.66% return.
    "lg12_semi":       dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500),
    "lg12_semi_third": dict(n=12, months=6, risk_adjusted=True, sleeve=0.30, top_by_addv=500),
    "lg20_semi":       dict(n=20, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500),
    "lg12_annual":     dict(n=12, months=12, risk_adjusted=True, sleeve=1.00, top_by_addv=500),
    # ---- the gated family. The ungated cells hold through everything between rebalances and
    # drew 54-63%; peak-to-trough on lg12_semi was $1.66M down to $644k, which is the same
    # concentration that produced the 8x. This adds the cheapest exit there is — out to the park
    # while the market is below its own 200-day, checked monthly — and a tighter top-250 pool.
    "lg12_semi_gated":  dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                             gated=True),
    "t250_12_semi":     dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=250),
    "t250_12_gated":    dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=250,
                             gated=True),
    "t250_8_gated":     dict(n=8,  months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=250,
                             gated=True),
    # ---- the trail family. Measured, and the reason this family exists: the market gate did
    # NOTHING. lg12_semi_gated drew -61.28% against lg12_semi's -61.28% — identical to four
    # decimals — because VOO never closed below its own 200-day between 2025-11 and 2026-07 while
    # the book fell from $1.73M to $670k. The gate watched the wrong series. So did the pool: the
    # top-500 and top-250 filters moved the drawdown the WRONG way (-56.5% full universe ->
    # -61.3% top-500 -> -60.6% top-250), because at a momentum peak the most-traded names ARE the
    # crowded trade.
    #
    # What every cell above actually shares is the real defect: NO EXIT BETWEEN REBALANCES. The
    # book bought in December 2025 and could not change its mind until the end of June 2026.
    # §3.2 already legislates the exit — initial entry -8%, armed at +15%, trailing 10% below the
    # highest close (5% under the euphoria rule), checked every session. These cells run it.
    "lg12_semi_trail":       dict(n=12, months=6, risk_adjusted=True, sleeve=1.00,
                                  top_by_addv=500, trail=True),
    "lg8_semi_trail":        dict(n=8,  months=6, risk_adjusted=True, sleeve=1.00,
                                  top_by_addv=500, trail=True),
    "t250_12_trail":         dict(n=12, months=6, risk_adjusted=True, sleeve=1.00,
                                  top_by_addv=250, trail=True),
    "lg12_semi_trail_third": dict(n=12, months=6, risk_adjusted=True, sleeve=0.30,
                                  top_by_addv=500, trail=True),
    # ---- the volatility governor. The gate's failure names its own replacement: Barroso &
    # Santa-Clara's result is that a momentum crash is forecastable from the STRATEGY's realized
    # volatility, not the market's trend. Same monthly clock the gate rode, watching the book.
    "lg12_semi_vt":          dict(n=12, months=6, risk_adjusted=True, sleeve=1.00,
                                  top_by_addv=500, vol_target=0.12),
    "lg12_semi_trail_vt":    dict(n=12, months=6, risk_adjusted=True, sleeve=1.00,
                                  top_by_addv=500, trail=True, vol_target=0.12),
}


def spread_frac(addv):
    for floor, bps in SPREAD_CURVE:
        if addv >= floor:
            return bps / 10_000.0
    return SPREAD_CURVE[-1][1] / 10_000.0


def build_grid(tape, calendar):
    """The tape as (dates, tickers, adjusted closes, raw closes, dollar volume) arrays.

    `calendar` is the set of dates the US market was actually open, and it is REQUIRED. Taking
    the session list from the tape's own union of dates instead — which is what this did — put
    New Year's Day in the grid, because 26 junk listings in the store print on it while VOO does
    not. `rebalance_dates` then picked 2018-01-01, 2019-01-01, 2020-01-01 and 2026-01-01 as the
    first session of the half-year, and on a day when nothing real prints the book SOLD its whole
    book (selling carries the last mark) and BOUGHT nothing (buying refuses a stale mark, and
    rightly). The proceeds went to the park and stayed there until July. Every A4 cell was
    therefore about half its life in SPMO — which is why they all pinned to SPMO's own -30.95%
    drawdown on 2020-03-23, a session on which the concentrated book held no stocks at all.
    """
    if not calendar:
        raise RuntimeError("no market calendar — the benchmark printed no bars, and a session "
                           "list taken from the tape alone silently includes market holidays")
    tickers = sorted({r[0] for r in tape})
    dates = sorted({r[1] for r in tape} & set(calendar))
    ti = {t: i for i, t in enumerate(tickers)}
    di = {d: i for i, d in enumerate(dates)}
    shape = (len(dates), len(tickers))
    adj = np.full(shape, np.nan)
    raw = np.full(shape, np.nan)
    dv = np.full(shape, np.nan)
    for tk, d, close, a, vol in tape:
        if d not in di:
            continue          # a bar printed on a day the market was shut — not a session
        i, j = di[d], ti[tk]
        if a is None or a <= 0:
            continue
        adj[i, j] = float(a)
        raw[i, j] = float(close) if close is not None else np.nan
        dv[i, j] = float(a) * float(vol) if vol is not None else np.nan
    return dates, tickers, adj, raw, dv


def rebalance_dates(dates, months, warmup):
    """The last session of each period, after the formation window is available."""
    out, seen = [], set()
    for i, d in enumerate(dates):
        if i < warmup:
            continue
        key = (d.year, (d.month - 1) // months)
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def rank_at(i, adj, raw, dv, *, risk_adjusted, top_by_addv=None):
    """12-1 momentum over the liquid universe at session i. Uses bars <= i only.

    `top_by_addv` narrows the pool to the K most-traded names BEFORE ranking. This is the
    difference between our universe and SPMO's: SPMO ranks inside the S&P 500 — large caps only —
    while a rank over all ~3,000 liquid US names reaches deep into small and mid caps, where
    12-1 momentum is mostly volatility that mean-reverts. The first concentrated grid measured
    the consequence: the full-universe book returned 16.66% with a -56.5% drawdown against the
    ETF's 21.12% / -31.0%. Dollar volume is the point-in-time proxy — a real S&P membership
    series is not in the store, and reconstructing one from today's index would be look-ahead.
    """
    if i < FORMATION + 1:
        return []
    past, recent = adj[i - FORMATION], adj[i - SKIP]
    live = np.isfinite(past) & np.isfinite(recent) & (past > 0)
    bars = np.isfinite(adj[max(0, i - FORMATION + 1):i + 1]).sum(axis=0)
    addv = np.nanmedian(dv[max(0, i - ADDV_WINDOW + 1):i + 1], axis=0)
    with np.errstate(invalid="ignore"):
        eligible = (live & (bars >= L0_MIN_BARS) & (raw[i] >= L0_MIN_RAW)
                    & (addv >= L0_MIN_ADDV))
    idx = np.where(eligible)[0]
    if not len(idx):
        return []
    if top_by_addv and len(idx) > top_by_addv:
        idx = idx[np.argsort(-addv[idx])[:top_by_addv]]
    score = recent[idx] / past[idx] - 1.0
    if risk_adjusted:
        window = adj[max(0, i - VOL_WINDOW):i + 1, idx]
        rets = np.diff(window, axis=0) / window[:-1]
        vol = np.nanstd(rets, axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            score = np.where(vol > 0, score / vol, np.nan)
    ok = np.isfinite(score)
    idx, score = idx[ok], score[ok]
    return [int(j) for j in idx[np.argsort(-score)]]


def regime_ok(i, index_px, window=200):
    """Is the index above its own long moving average? Clenow's gate, and §3.3's M1 latch.

    The concentrated book has NO exit between rebalances — it holds whatever it bought through
    whatever happens, which is why the ungated cells drew 54-63%. This is the cheapest exit that
    exists: when the market itself is below its 200-day, the sleeve goes to the park and waits.
    Unknown (not enough history) is treated as OFF rather than ON — a gate that cannot be
    evaluated must not wave the book through.
    """
    if i < window:
        return False
    hist = index_px[i - window + 1:i + 1]
    if not np.isfinite(index_px[i]) or not np.isfinite(hist).any():
        return False
    return bool(index_px[i] > np.nanmean(hist))


def vol_scalar(equity, target, window=VOL_TARGET_WINDOW):
    """Barroso-Santa-Clara's dial: min(1, target / realized), on the BOOK's own daily returns,
    annualized at 252. It only ever shrinks — the paper's symmetric version borrows and this
    account does not. Too little history reads as 1.0, declared as warmup rather than guessed.

    Identical in form to `backtest.py:_vol_scalar`; kept separate because that one reads the
    engine's equity rows and this one reads a plain list of NAVs.
    """
    if len(equity) < window + 1:
        return 1.0
    navs = np.array(equity[-(window + 1):], dtype=float)
    rets = navs[1:] / navs[:-1] - 1.0
    sd = float(rets.std(ddof=1))
    if sd <= 0:
        return 1.0
    return float(min(1.0, target / (sd * np.sqrt(252.0))))


def trail_stop(px, st, closes):
    """§3.2's ratchet for one name on one session. Returns the stop, never below its last value.

    `closes` is the name's own trailing window of adjusted closes ending today, for the euphoria
    test. The initial stop is live from entry; the 10% trail replaces it only once the name has
    printed +15% from average cost, and stays armed thereafter (the plan ratchets up, never down).
    """
    want = st["entry"] * (1 - TRAIL_INITIAL)
    if st["armed"] or px >= st["entry"] * (1 + TRAIL_ARM):
        st["armed"] = True
        band = TRAIL_WIDE
        w = closes[np.isfinite(closes)]
        if len(w) >= EUPHORIA_WINDOW:
            sd = w.std(ddof=1)
            # a flat window has no standard deviation to be two of. Without this, "> mean + 0"
            # calls any uptick euphoric, and a halted name printing one price for fifty sessions
            # arrives back from the halt on a 5% leash.
            if sd > 0 and px > w.mean() + EUPHORIA_SD * sd:
                band = TRAIL_EUPHORIA
        want = max(want, st["hi"] * (1 - band))
    return max(st["stop"], want)


def simulate(dates, tickers, adj, raw, dv, park_px, *, n, months, risk_adjusted, sleeve,
             start_nav, top_by_addv=None, index_px=None, gate_every=21, trail=False,
             vol_target=None):
    """Hold the top `n` names, changed every `months`, with the rest of the account in the park.

    With `index_px` supplied the book is ALSO checked every `gate_every` sessions against the
    market's own trend: below its 200-day the whole sleeve moves to the park, and it only comes
    back at a check that finds the market above it again. That is one extra decision a month at
    most, which the day-job constraint can carry.

    With `trail` the book gets §3.2's per-name stop, tested on every session's close. **The fill
    is the NEXT session's close, not the stop price.** This tape carries adjusted closes and no
    intraday range, so an intraday stop cannot be priced; taking the next close is strictly worse
    than a real broker stop in a fast market and never better, which is the direction an honest
    simulation errs in. Proceeds sit in the park until the next rebalance.

    With `vol_target` the sleeve fraction is scaled by the BOOK's own realized volatility on the
    `gate_every` clock, trading only when the drift exceeds §2.1's PARK_BAND.
    """
    warmup = FORMATION + 1
    rebals = set(rebalance_dates(dates, months, warmup))
    held = {}                       # ticker index -> shares
    state = {}                      # ticker index -> {entry, hi, stop, armed} for the §3.2 trail
    last_px = {}                    # ticker index -> the most recent price it actually printed
    park_qty, cash = 0.0, start_nav
    equity, trades, costs = [], [], 0.0
    navs = []                       # the NAV path alone, for the volatility governor
    stale_skips, empty_rebals = 0, []

    def price(i, j):
        """What the position is worth today: today's print, or the last one it made.

        A name is NOT worth zero on a session it did not trade. Dropping an unprinted holding
        out of the mark is precisely the defect that gave run 52 a fake -91.5% drawdown — the
        account appeared to fall to its cash balance and recover the next day — and it reappeared
        here as a -100.0% max drawdown on five of eight cells, which is the statistic doing its
        job. Holidays, halts and the delisting tail all take this path.
        """
        if np.isfinite(adj[i, j]):
            last_px[j] = float(adj[i, j])
        return last_px.get(j)

    def mark(i):
        v = 0.0
        for j, q in held.items():
            px = price(i, j)
            if px is not None:
                v += q * px
        p = park_qty * park_px[i] if np.isfinite(park_px[i]) else 0.0
        return cash + v + p

    def sell(i, j, qty, reason):
        """Sell `qty` shares of name j at its price today. A name that did not print cannot be
        sold — the position stays and is retried next session, which is what a halt or a holiday
        actually does to an order."""
        nonlocal cash, costs
        px_j = price(i, j)
        if px_j is None or qty <= 0:
            return False
        gross = qty * px_j
        fee = gross * spread_frac(np.nanmedian(dv[max(0, i - ADDV_WINDOW):i + 1, j]))
        cash += gross - fee
        costs += fee
        trades.append(dict(ticker=tickers[j], exit_date=dates[i], price=px_j, qty=qty,
                           reason=reason))
        held[j] -= qty
        if held[j] <= 1e-9:
            del held[j]
            state.pop(j, None)
        return True

    def park_all(i):
        """Every idle dollar into the park."""
        nonlocal cash, park_qty, costs
        if cash <= 0 or not np.isfinite(park_px[i]):
            return
        park_qty += cash / (park_px[i] * (1 + spread_frac(1e9)))
        costs += cash * spread_frac(1e9)
        cash = 0.0

    def unpark(i, want):
        """Raise `want` dollars out of the park, or as much of it as the park holds."""
        nonlocal cash, park_qty, costs
        if want <= 0 or park_qty <= 0 or not np.isfinite(park_px[i]):
            return
        qty = min(park_qty, want / (park_px[i] * (1 - spread_frac(1e9))))
        gross = qty * park_px[i]
        cash += gross * (1 - spread_frac(1e9))
        costs += gross * spread_frac(1e9)
        park_qty -= qty

    gated_off = False
    queued = []                     # trail stops hit at yesterday's close, filled at today's
    for i in range(warmup, len(dates)):
        # ---- yesterday's stops, filled today. §3.2 acts on the session after the close that
        # broke the stop; this tape has no intraday range to fill against, so the next close it is.
        for j in list(queued):
            if j in held and sell(i, j, held[j], "trail_stop"):
                queued.remove(j)
            elif j not in held:
                queued.remove(j)
        park_all(i)
        nav = mark(i)
        # ---- the regime check, on its own clock
        if index_px is not None and i % gate_every == 0 and np.isfinite(park_px[i]):
            on = regime_ok(i, index_px)
            if not on and held:
                for j in list(held):
                    sell(i, j, held[j], "gate_off")
                queued.clear()
                park_all(i)
            gated_off = not on
        # ---- the volatility governor, on the same clock. Barroso-Santa-Clara scale by the
        # book's OWN realized volatility: the series that forecasts a momentum crash, unlike the
        # index trend the gate above watches. Trades only outside §2.1's band.
        if vol_target and held and i % gate_every == 0 and np.isfinite(park_px[i]) and not gated_off:
            nav = mark(i)
            want_w = sleeve * vol_scalar(navs, float(vol_target))
            have = sum(q * (price(i, j) or 0.0) for j, q in held.items())
            if nav > 0 and abs(have / nav - want_w) > PARK_BAND:
                target_v = nav * want_w
                if have > target_v:                       # shrink pro rata, park the difference
                    share = 1.0 - target_v / have
                    for j in list(held):
                        sell(i, j, held[j] * share, "vol_governor")
                    park_all(i)
                else:                                     # grow pro rata out of the park
                    unpark(i, target_v - have)
                    for j in list(held):
                        px_j = price(i, j)
                        if px_j is None:
                            continue
                        add = min((target_v - have) * (held[j] * px_j) / have,
                                  cash / (1 + spread_frac(1e9)))
                        fee_frac = spread_frac(np.nanmedian(dv[max(0, i - ADDV_WINDOW):i + 1, j]))
                        add = min(add, cash / (1 + fee_frac))
                        if add <= 0:
                            continue
                        qty = add / (px_j * (1 + fee_frac))
                        held[j] += qty
                        cash -= add
                        costs += add * fee_frac / (1 + fee_frac)
                        st = state.get(j)
                        if st:                             # average cost moves; the stop does not
                            st["entry"] = ((st["entry"] * (held[j] - qty) + px_j * qty)
                                           / max(held[j], 1e-12))
                        trades.append(dict(ticker=tickers[j], entry_date=dates[i], spend=add,
                                           price=px_j, qty=qty))
                    park_all(i)
        if i in rebals and np.isfinite(park_px[i]) and not gated_off:
            queued.clear()
            want = rank_at(i, adj, raw, dv, risk_adjusted=risk_adjusted,
                           top_by_addv=top_by_addv)[:n]
            wanted = set(want)
            # sell what fell out of the book, and the park, then buy the new book
            for j in list(held):
                if j not in wanted:
                    sell(i, j, held[j], "rebalance")
            if park_qty > 0:
                gross = park_qty * park_px[i]
                cash += gross * (1 - spread_frac(1e9))
                costs += gross * spread_frac(1e9)
                park_qty = 0.0
            # NAV is cash PLUS the names being carried through this rebalance. Reading it as cash
            # alone — which is what this did, because the line sat under a block that had just
            # liquidated everything unwanted — sized the new slices out of a NAV missing every
            # survivor. Worked example at the observed turnover (≈8 of 12 names replaced): the
            # four carried names hold ~35% of the account, so per-name came out at k/12 instead
            # of nav/12, the eight new names absorbed only 8/12 of the cash, and the remaining
            # ~23% of the account went silently to the park. Every A4 cell labelled sleeve=1.00
            # was therefore running about 0.77, and its drawdown is an understatement.
            nav = cash + sum(q * (price(i, j) or 0.0) for j, q in held.items())
            eff_sleeve = sleeve * (vol_scalar(navs, float(vol_target)) if vol_target else 1.0)
            per_name = nav * eff_sleeve / max(len(want), 1) if want else 0.0
            funded = 0
            for j in want:
                if not np.isfinite(adj[i, j]):
                    stale_skips += 1  # never BUY on a stale mark — only hold and sell on one
                    continue
                px = float(adj[i, j])
                fee_frac = spread_frac(np.nanmedian(dv[max(0, i - ADDV_WINDOW):i + 1, j]))
                have = held.get(j, 0.0) * px
                # Cap the slice at what the account can actually pay, fee included. Sizing N
                # equal slices out of NAV and then charging a spread on each leaves the LAST
                # name unfunded by exactly the fees — a book of eleven names wearing a
                # twelve-name label, with the shortfall landing silently on whichever name
                # ranked last.
                spend = min(max(per_name - have, 0.0), cash / (1 + fee_frac))
                if spend <= 0:
                    continue
                qty = spend / (px * (1 + fee_frac))
                held[j] = held.get(j, 0.0) + qty
                cash -= spend
                costs += spend * fee_frac / (1 + fee_frac)
                st = state.get(j)
                if st:      # a carried name: average cost moves, the stop never ratchets down
                    st["entry"] = (st["entry"] * (held[j] - qty) + px * qty) / held[j]
                else:
                    state[j] = dict(entry=px, hi=px, stop=px * (1 - TRAIL_INITIAL), armed=False)
                funded += 1
                trades.append(dict(ticker=tickers[j], entry_date=dates[i], spend=spend,
                                   price=px, qty=qty))
            # A rebalance that ends holding NOTHING dumps the whole account in the park until the
            # next one. Both routes matter and the guard must not care which fired: a holiday in
            # the session list emptied the RANK (no name clears the $5 floor when no name prints),
            # while a halt on a real session empties the FUNDING. The first ran for six months at
            # a time across four Januaries, invisibly, because nothing counted it.
            if not held:
                empty_rebals.append(dates[i])
            park_all(i)
        # ---- §3.2's ratchet, every session, on every name held. What breaks today is sold at
        # tomorrow's close (see the docstring); a name already queued is not re-tested.
        if trail and held:
            for j in list(held):
                st = state.get(j)
                px_j = price(i, j)
                if st is None or px_j is None or j in queued:
                    continue
                st["hi"] = max(st["hi"], px_j)
                st["stop"] = trail_stop(px_j, st, adj[max(0, i - EUPHORIA_WINDOW + 1):i + 1, j])
                if px_j < st["stop"]:
                    queued.append(j)
        v = mark(i)
        navs.append(v)
        equity.append((dates[i], v, float(park_px[i]) if np.isfinite(park_px[i]) else None))

    # Close the surviving book on paper at the last session's mark. No fee, no cash movement, no
    # effect on the equity path above — this is bookkeeping, and `reason` says so. It exists
    # because the alternative is a ledger row with a NULL P&L, and a NULL there is worse than it
    # looks: the jackknife asks whether the result survives removing its biggest winners, and a
    # winner the book is still holding is IN the equity curve's return while being invisible to
    # the trade list. It could never be jackknifed out, which flatters exactly the arm that most
    # needs the test. (It also crashed both consumers on `float(None)` — twice.)
    last = len(dates) - 1
    for j in list(held):
        px_j = price(last, j)
        if px_j is not None:
            trades.append(dict(ticker=tickers[j], exit_date=dates[last], price=px_j,
                               qty=held[j], reason="open_at_end"))
    return equity, trades, costs, dict(stale_skips=stale_skips,
                                       empty_rebalances=[d.isoformat() for d in empty_rebals])


def pair_trades(trades, dates):
    """Match each exit to the lots that opened it, FIFO, so the ledger holds positions rather
    than legs. A name still held when the window ends is closed at the last session it priced.

    Partial fills are matched partially: the volatility governor scales the whole book up and
    down between rebalances, so an exit leg routinely closes a fraction of a lot and a lot is
    routinely closed by several exits. Popping the lot whole on the first touch — which is what
    this did while every exit was all-or-nothing — would have leaked the remainder into the
    open-at-end tail and mispriced its P&L."""
    idx = {d: i for i, d in enumerate(dates)}
    open_by, out = {}, []
    for t in sorted(trades, key=lambda t: t.get("entry_date") or t.get("exit_date")):
        tk = t["ticker"]
        if "entry_date" in t:
            open_by.setdefault(tk, []).append(dict(t))
            continue
        lots, remaining = open_by.get(tk) or [], t["qty"]
        while remaining > 1e-9 and lots:
            e = lots[0]
            qty = min(e["qty"], remaining)
            out.append(dict(ticker=tk, entry_date=e["entry_date"], entry_price=e["price"],
                            qty=qty, exit_date=t["exit_date"], exit_price=t["price"],
                            pnl=qty * (t["price"] - e["price"]),
                            pnl_pct=(t["price"] / e["price"] - 1.0) if e["price"] else None,
                            bars=idx[t["exit_date"]] - idx[e["entry_date"]], reason=t["reason"]))
            e["qty"] -= qty
            remaining -= qty
            if e["qty"] <= 1e-9:
                lots.pop(0)
    # A lot of zero shares is not an open position. Top-ups can round to a sliver, and a sliver
    # left at the tail of a ticker's FIFO queue after the exits have consumed everything real
    # would otherwise be reported as a live holding with no P&L.
    open_by = {tk: [e for e in lots if e["qty"] > 1e-9] for tk, lots in open_by.items()}
    for tk, lots in open_by.items():
        for e in lots:
            out.append(dict(ticker=tk, entry_date=e["entry_date"], entry_price=e["price"],
                            qty=e["qty"], exit_date=None, exit_price=None, pnl=None,
                            pnl_pct=None, bars=None, reason="open_at_end"))
    return out


def main():
    here = pathlib.Path(__file__).resolve().parent
    code = hashlib.sha256((here / "concentrated.py").read_bytes()).hexdigest()[:16]
    start_nav = float(os.environ.get("START_NAV", "200000"))
    want = [c.strip() for c in os.environ.get("CELLS", "").split(",") if c.strip()] or list(CELLS)

    with connect() as conn:
        with Heartbeat(conn, "concentrated") as hb:
            with conn.cursor() as cur:
                tape = load_tape(cur)
                cur.execute("""select d, coalesce(adj_close, close) from prices
                                where ticker = %s order by d""", (PARK_TICKER,))
                park_rows = dict(cur.fetchall())
                cur.execute("""select d, coalesce(adj_close, close) from prices
                                where ticker = %s order by d""", (BENCH,))
                bench_rows = dict(cur.fetchall())
            # the benchmark's own bars ARE the market calendar: an index ETF prints on every real
            # US session and on no holiday, which is exactly the predicate this grid needs
            dates, tickers, adj, raw, dv = build_grid(tape, set(bench_rows))
            park_px = np.array([float(park_rows.get(d, np.nan)) for d in dates])
            # forward-fill the park so a dark session carries its last mark rather than vanishing
            for i in range(1, len(park_px)):
                if not np.isfinite(park_px[i]):
                    park_px[i] = park_px[i - 1]
            first = int(np.argmax(np.isfinite(park_px)))
            print(f"grid {len(dates)} sessions x {len(tickers)} names · park from {dates[first]}")

            written = []
            bench_px = np.array([float(bench_rows.get(d, np.nan)) for d in dates])
            for i in range(1, len(bench_px)):
                if not np.isfinite(bench_px[i]):
                    bench_px[i] = bench_px[i - 1]
            for name in want:
                spec = dict(CELLS[name])
                gated = spec.pop("gated", False)
                eq, trades, costs, health = simulate(dates, tickers, adj, raw, dv, park_px,
                                                     start_nav=start_nav,
                                                     index_px=bench_px if gated else None, **spec)
                exits = {}
                for t in trades:
                    if "exit_date" in t:
                        exits[t["reason"]] = exits.get(t["reason"], 0) + 1
                eq = [(d, v, bench_rows.get(d)) for d, v, _ in eq
                      if d >= dates[first]]
                nav = np.array([e[1] for e in eq])
                years = max((eq[-1][0] - eq[0][0]).days / 365.25, 1e-9)
                total = float(nav[-1] / nav[0] - 1)
                cagr = float((1 + total) ** (1 / years) - 1)
                dd = float((nav / np.maximum.accumulate(nav) - 1).min())
                entries = [t for t in trades if "entry_date" in t]
                per_year = len(entries) / years
                rows = [(d, float(v), float(b)) for d, v, b in eq if b is not None]
                full = finding.score_cut(finding.cut(rows, []))
                try:
                    oos = finding.score_cut(finding.cut(rows, [], since=finding.OOS_START))
                except RuntimeError:
                    oos = None
                print(f"{name}: {total:+.1%} · CAGR {cagr:.2%} · maxDD {dd:.1%} · "
                      f"{len(entries)} entries ({per_year:.1f}/yr) · cost ${costs:,.0f}")
                if dry():
                    continue
                params = dict(variant=name, hypothesis="a4", code_stamp=code, currency="USD",
                              benchmark=BENCH, start_nav=start_nav, park=PARK_TICKER,
                              spec=dict(CELLS[name]), formation=FORMATION, skip=SKIP)
                # P1's digest, on this arm's own surface. Without it these cells carry no
                # param_hash, `finding.trial_sharpes` cannot see them, and a grid of twenty-odd
                # configurations contributes NOTHING to the deflation that exists to price
                # exactly that kind of search. A grid this wide is the case the deflated Sharpe
                # was invented for; leaving it out of the trial count inflates every cell in it.
                params["param_hash"] = param_digest(
                    dict(CELLS[name]),
                    {k: v for k, v in params.items() if k not in ("spec", "code_stamp")})
                stats = dict(a4=dict(spec=spec, entries=len(entries),
                                     entries_per_year=round(per_year, 2),
                                     cost_usd=round(costs, 2), **health),
                             bars_25=dict(source="wo-a4-2026-08-13", full=full, oos=oos,
                                          dsr="not scored — see the ledger's swept runs"),
                             conformance_ok=True, exits=exits)
                with conn.cursor() as cur:
                    cur.execute("""insert into backtest_runs(label,params,start_date,end_date,
                          trading_days,start_nav,end_nav,total_return,cagr,max_drawdown,
                          max_dd_date,trades,stats)
                        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                        (f"A4 · concentrated · {name}", json.dumps(params, default=str),
                         eq[0][0], eq[-1][0], len(eq), start_nav, float(nav[-1]), total, cagr,
                         dd, eq[int(np.argmin(nav / np.maximum.accumulate(nav)))][0],
                         len(entries), json.dumps(stats, default=str)))
                    rid = cur.fetchone()[0]
                    cur.executemany("""insert into backtest_equity(run_id,d,nav,exposure,
                                         positions,gate,benchmark) values (%s,%s,%s,%s,%s,%s,%s)""",
                        [(rid, d, v, spec["sleeve"], spec["n"], None, b) for d, v, b in eq])
                    # the book itself, so "did it hold MRVL" is a query rather than a belief
                    cur.executemany("""insert into backtest_trades(run_id,ticker,entry_date,
                          entry_price,qty,exit_date,exit_price,pnl_cad,pnl_pct,bars_held,
                          exit_reason,entry_kind)
                        values (%(run_id)s,%(ticker)s,%(entry_date)s,%(entry_price)s,%(qty)s,
                          %(exit_date)s,%(exit_price)s,%(pnl)s,%(pnl_pct)s,%(bars)s,
                          %(reason)s,'momentum_rank')""",
                        [{**t, "run_id": rid} for t in pair_trades(trades, dates)])
                conn.commit()
                written.append(rid)
                print(f"  run {rid} written")
            hb.rows = len(written)
            hb.detail["run_ids"] = written
            if written:
                pathlib.Path("/tmp/run_ids.txt").write_text("\n".join(str(r) for r in written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
