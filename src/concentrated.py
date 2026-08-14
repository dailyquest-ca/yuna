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

The one exception is the **stop**, and it earns its place: `trail=True` runs §3.2's own ratchet
per name, every session — the exit the plan already legislates and this arm was first built
without. Measured on the corrected grid (session-2026-08-13 §14), it is the difference between
unproven and proven:

  * `lg12_semi` (no exit between rebalances) — 36.02% CAGR, bootstrap median drawdown -51.9%,
    deflated Sharpe 0.897, **unproven**
  * `lg12_semi_trail` — 29.19%, bootstrap median drawdown **-31.0%**, DSR 0.969, **proven**
  * `lg8_semi_trail` — **31.75%**, -31.0%, DSR **0.979**, **proven**, at 16.7 names a year

**An earlier version of this docstring said the opposite about two of these knobs**, on numbers
measured before the calendar defect in `build_grid` was found. The large-cap pool does not hurt —
it is the biggest single lever in the grid, worth ten points of CAGR (27.31% full universe →
36.02% top-500 → 37.54% top-250). The market gate is a bad trade rather than a no-op: -6.2 points
of CAGR for +2.3 of drawdown. `vol_target` (Barroso-Santa-Clara) was the hypothesis that the
strategy's own volatility forecasts a momentum crash; it does, but the trail collects the same
information per name and acts faster, so the governor only adds turnover. Tested, rejected.

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
# WO-A6's entry door: a close above every close in the prior 252 sessions. §3.2 enters on a break
# above a pivot; this is that with the base detection removed, and the same window A2 used.
ENTRY_HIGH = 252

# ---- WO-A6, the banded continuous book. Every constant here is the work order's own.
A6_ENTRY_RANK = 15          # §1: a slot takes the highest-ranked name at rank <= 15
A6_EXIT_RANK = 40           # §1: held until rank > 40 — between 15 and 40 flicker costs nothing
A6_HIGH_WINDOW = 252        # §1 valid-base state: within 10% of the 252-session high close
A6_HIGH_PROX = 0.10
A6_SMA = 50                 # ... close > 50-day SMA, and that SMA rising over ten sessions
A6_SMA_SLOPE = 10
A6_RIDER_WINDOW = 126       # §2: §2.2's own correlation window
A6_RIDER_BETS = 5.0         # §2: effective-bets floor at formation
A6_RIDER_RHO = 0.70         # §2: pairwise correlation defining a cluster
A6_RIDER_PER_CLUSTER = 2    # §2: at most two names from one cluster
A6_PATH_WINDOW = 231        # §3's A6-F rung: %-positive-days over the 231-session formation
A6_PATH_POOL = 50           # ... measured against the median of the top-50 by rank

TRAIL_DEFAULTS = dict(initial=TRAIL_INITIAL, arm=TRAIL_ARM, wide=TRAIL_WIDE,
                      euphoria=TRAIL_EUPHORIA)

# WO-A6 §3's ATR rung, verbatim from the work order: "3xATR(20) initial, +1R arm, 8xATR(22)
# Chandelier". `mode` selects the shape; the percentage bands above are ignored in this mode. It is
# a PROBE — §3.2's own numbers are the ones in TRAIL_DEFAULTS and a cell running this is asking
# whether the trail's shape matters, not proposing a replacement for the plan's stop.
TRAIL_ATR = dict(mode="atr", atr_init_mult=3.0, atr_init_window=20,
                 atr_arm_r=1.0, atr_chand_mult=8.0, atr_chand_window=22)

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
    # ---- WO-A5's robustness ladder. `lg8_semi_trail` came out of a 22-cell search and reached
    # §2.5 `proven`; these move ONE axis one step either side of it to find out whether it sits on
    # a plateau or a spike. Declared in the work order BEFORE any of them ran, with the reading
    # fixed there too — and a probe that beats the champion is evidence about the surface, not a
    # new champion, because promoting it re-runs the same selection the deflation already prices.
    "lad_n6":      dict(n=6,  months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500, trail=True),
    "lad_n10":     dict(n=10, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500, trail=True),
    "lad_p250":    dict(n=8,  months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=250, trail=True),
    "lad_p750":    dict(n=8,  months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=750, trail=True),
    "lad_quarter": dict(n=8,  months=3, risk_adjusted=True, sleeve=1.00, top_by_addv=500, trail=True),
    "lad_annual":  dict(n=8,  months=12, risk_adjusted=True, sleeve=1.00, top_by_addv=500, trail=True),
    "lad_wide8":   dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500, trail=True,
                        trail_cfg=dict(initial=0.08, arm=0.15, wide=0.08, euphoria=0.05)),
    "lad_wide12":  dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500, trail=True,
                        trail_cfg=dict(initial=0.08, arm=0.15, wide=0.12, euphoria=0.05)),
    "lad_arm12":   dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500, trail=True,
                        trail_cfg=dict(initial=0.08, arm=0.12, wide=0.10, euphoria=0.05)),
    "lad_arm18":   dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500, trail=True,
                        trail_cfg=dict(initial=0.08, arm=0.18, wide=0.10, euphoria=0.05)),
    "lad_init6":   dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500, trail=True,
                        trail_cfg=dict(initial=0.06, arm=0.15, wide=0.10, euphoria=0.05)),
    "lad_init10":  dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500, trail=True,
                        trail_cfg=dict(initial=0.10, arm=0.15, wide=0.10, euphoria=0.05)),
    "lad_euph4":   dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500, trail=True,
                        trail_cfg=dict(initial=0.08, arm=0.15, wide=0.10, euphoria=0.04)),
    "lad_euph6":   dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500, trail=True,
                        trail_cfg=dict(initial=0.08, arm=0.15, wide=0.10, euphoria=0.06)),
    # ---- WO-A5 §3.1: costs at 2x and 4x §2.2's curve. 16.7 entries a year should not be
    # cost-fragile; "should not be" is not a measurement.
    "lad_cost2x":  dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                        trail=True, cost_mult=2.0),
    "lad_cost4x":  dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                        trail=True, cost_mult=4.0),
    # ---- WO-A5 §2.1: the same champion, filled the way a broker fills a resting stop — at the
    # open when the session gaps through it, at the stop otherwise. Reported ALONGSIDE the
    # close-based cell, not instead of it.
    "lg8_trail_intraday":  dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                               trail=True, intraday=True),
    "lg12_trail_intraday": dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                               trail=True, intraday=True),
    # ---- WO-A5 amendment: the THIRD fill model, and the honest disclosure is that it was
    # proposed after seeing the second one cost 5.9 points. The argument for it does not depend
    # on that number: a resting GTC stop is one execution path and a decision taken at the close
    # for the next open is the other, §3.2 already legislates BOTH (stops rest at the broker; the
    # hair-trigger "exits next morning"), and §5.1 has Zak placing every order from a morning
    # brief. Which one this arm would actually run under is an operational question, not a
    # modelling preference — so it is measured and reported alongside, never instead of.
    "lg8_trail_nextopen":  dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                                trail=True, next_open=True),
    "lg12_trail_nextopen": dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                                trail=True, next_open=True),
    # ---- the clock, measured on the RULED execution path. Zak, 2026-08-13: *"you said we
    # rebalance only twice a year... what about 12 times a year? Monthly even? Twice a year seems
    # like a long time."* It is a fair question and the trail makes it sharper than it looks: the
    # trail exits names continuously, so the rebalance is really the RE-ENTRY clock. A stop-out
    # wave currently parks the whole book until the next one — the July 2026 book stopped out by
    # the 8th and the arm has been 100% SPMO since, with nothing scheduled until 2027-01.
    "clk_monthly":   dict(n=8, months=1,  risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True),
    "clk_bimonthly": dict(n=8, months=2,  risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True),
    "clk_quarter":   dict(n=8, months=3,  risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True),
    "clk_annual":    dict(n=8, months=12, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True),
    # ---- the loose sector cap Zak allowed. At eight names, 0.7 permits five of one sector — it
    # would have trimmed the July 2026 book (7 of 8 Technology) to five and left three slots for
    # the next-ranked names outside it. Priced, not assumed: if it costs return, he is right that
    # there should not be one.
    "sec70_semi":    dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True, sector_cap=0.70),
    "sec70_monthly": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True, sector_cap=0.70),
    # ---- the phase test. Nine years of a semi-annual clock is EIGHTEEN decisions; the same rule
    # started one month later is the same rule. If Jan/Jul beats monthly because slower re-entry
    # avoids buying declines, every phase must beat monthly. If the phases disagree with each
    # other by more than they disagree with monthly, the clock finding was date luck.
    "ph_semi_0": dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, offset=0),
    "ph_semi_1": dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, offset=1),
    "ph_semi_2": dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, offset=2),
    "ph_semi_3": dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, offset=3),
    "ph_semi_4": dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, offset=4),
    "ph_semi_5": dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, offset=5),
    "ph_qtr_1":  dict(n=8, months=3, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, offset=1),
    "ph_qtr_2":  dict(n=8, months=3, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, offset=2),
    # ---- WO-A6: no calendar. A slot is filled the session a qualifying name prints a new
    # 252-day high; names leave only via the trail. `months` is inert in this mode and is left at
    # the champion's value so the cell spec still reads as one axis off it.
    "evt_hi8":       dict(n=8,  months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True, entry_rule="new_high"),
    "evt_hi6":       dict(n=6,  months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True, entry_rule="new_high"),
    "evt_hi12":      dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True, entry_rule="new_high"),
    "evt_hi8_sec70": dict(n=8,  months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True, entry_rule="new_high", sector_cap=0.70),
    # the phase analogue: an event rule has no calendar to shift, so shift when watching begins
    "evt_hi8_s1":    dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True, entry_rule="new_high", start_offset=1),
    "evt_hi8_s2":    dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True, entry_rule="new_high", start_offset=2),
    "evt_hi8_s3":    dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True, entry_rule="new_high", start_offset=3),
    "evt_hi8_s4":    dict(n=8, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                          trail=True, next_open=True, entry_rule="new_high", start_offset=4),
    # ---- WO-A7: monthly's OWN stability. The clock ranking was read off phase 0, which is the
    # comparison the phase test invalidated — so monthly was dismissed on corrupted evidence. It
    # should be structurally far more stable than semi-annual for the reason semi-annual failed:
    # 108 decision points against 18. A monthly calendar has no month-phase to shift, so the
    # arbitrary choice under test is again when trading begins.
    "mo_s1": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                  trail=True, next_open=True, start_offset=1),
    "mo_s2": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                  trail=True, next_open=True, start_offset=2),
    "mo_s3": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                  trail=True, next_open=True, start_offset=3),
    "mo_s4": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                  trail=True, next_open=True, start_offset=4),
    # and the same for bi-monthly and quarterly, so the stability/frequency curve has three points
    "bi_s1": dict(n=8, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                  trail=True, next_open=True, start_offset=1),
    "bi_s2": dict(n=8, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                  trail=True, next_open=True, start_offset=2),
    "bi_s3": dict(n=8, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                  trail=True, next_open=True, start_offset=3),
    # ---- WO-A7 extension: past monthly. Calendar months bottom out at 21 sessions, so the
    # frequency axis continues in SESSIONS. Zak: *"can you test... even more often? Like...
    # daily?"* The curve has already turned once — bi-monthly (33.37% mean) edges monthly
    # (32.79%) — so this is measuring where cost and whipsaw overtake the sampling benefit, not
    # extrapolating a trend. At every=1 there is no date left to be lucky about.
    "fq_d1":    dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=1),
    "fq_d1_s1": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=1, start_offset=1),
    "fq_w1":    dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=5),
    "fq_w1_s1": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=5, start_offset=1),
    "fq_w1_s2": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=5, start_offset=2),
    "fq_f2":    dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=10),
    "fq_f2_s1": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=10, start_offset=1),
    "fq_f2_s2": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=10, start_offset=2),
    # ---- the phase test on the recommended clock. Two shapes, because the calendar version
    # cannot carry a real one: a TWO-month bucket has only TWO month-phases (offset 2 lands back
    # on offset 0), so `bi_ph1` exhausts the calendar test in a single extra cell. The honest
    # version uses a 42-SESSION clock — the same ~2-month cadence with 42 distinct phases — and
    # samples six of them a week apart. That is the direct analogue of the six semi-annual phases
    # that spread 17.6 points and destroyed the previous champion.
    "bi_ph1":  dict(n=8, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, offset=1),
    "s42_p0":  dict(n=8, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, every_sessions=42),
    "s42_p7":  dict(n=8, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, every_sessions=42, offset=7),
    "s42_p14": dict(n=8, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, every_sessions=42, offset=14),
    "s42_p21": dict(n=8, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, every_sessions=42, offset=21),
    "s42_p28": dict(n=8, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, every_sessions=42, offset=28),
    "s42_p35": dict(n=8, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, every_sessions=42, offset=35),
    # ---- the same test on the monthly clock, because the bi-monthly one failed and the earlier
    # "monthly is stable" reading rests on the SAME mistake: `start_offset` drops early
    # rebalances while leaving the calendar phase untouched, so it measured start-date
    # sensitivity and was reported as phase stability. A 21-session clock carries 21 real phases.
    "s21_p0":  dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, every_sessions=21),
    "s21_p3":  dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, every_sessions=21, offset=3),
    "s21_p7":  dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, every_sessions=21, offset=7),
    "s21_p10": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, every_sessions=21, offset=10),
    "s21_p14": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, every_sessions=21, offset=14),
    "s21_p17": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                    trail=True, next_open=True, every_sessions=21, offset=17),
    # and weekly, where FIVE offsets exhaust the phase space entirely
    "s5_p1": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                  trail=True, next_open=True, every_sessions=5, offset=1),
    "s5_p2": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                  trail=True, next_open=True, every_sessions=5, offset=2),
    "s5_p3": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                  trail=True, next_open=True, every_sessions=5, offset=3),
    "s5_p4": dict(n=8, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                  trail=True, next_open=True, every_sessions=5, offset=4),
    # ================= WO-A6 (Zak, 2026-08-14) — the banded continuous book =================
    # Observe every session; transact only on gates. No calendar anywhere in the rule.
    "a6":       dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, entry_rule="banded"),
    # §4 falsifier 1: five simulation-start offsets. Kill at a spread above 6 CAGR points.
    "a6_s10":   dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, entry_rule="banded", start_offset=10 / 21),
    "a6_s21":   dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, entry_rule="banded", start_offset=1),
    "a6_s42":   dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, entry_rule="banded", start_offset=2),
    "a6_s63":   dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, entry_rule="banded", start_offset=3),
    # §4 falsifier 2 (added at Zak's approval, 2026-08-14): read the rank and the base state one
    # session late while executing on the same day. A start offset only changes where the walk
    # begins; this changes WHICH observation the rule acts on, every single session. A state-door
    # that responds to a slow condition should barely notice. One that moves materially was
    # riding a specific-day effect, which is the failure the start-offset test cannot see — and
    # is exactly the axis mistaken for a phase test on the bi-monthly book.
    "a6_lag1":  dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, entry_rule="banded", rank_lag=1),
    "a6_lag2":  dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, entry_rule="banded", rank_lag=2),
    "a6_lag5":  dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, entry_rule="banded", rank_lag=5),
    # ---- DIAGNOSTICS, not candidates. The §2 floor of 5 effective bets is unreachable for a
    # 12-name equity book: with the measured mean pairwise correlation of 0.191 among the 40
    # most-traded names, k/(1+(k-1)rho) tops out at 3.87 at k=12, and a momentum book runs hotter
    # still (July 2026 was 0.477 -> 1.92). The centre above therefore capped at 3.81 names and
    # 32.6% deployed and reported two-thirds of SPMO's return as its own. These two cells measure
    # what the arm does when the floor is set to something an equity book can actually reach, so
    # the ruling has numbers under it. Neither is a candidate until Zak rules on the floor.
    "a6_floor4": dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=4.0),
    "a6_floor0": dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=0.0),
    # §4's falsifiers, re-run on the book that actually fills. The first pass measured them on a
    # 32.6%-deployed book, so its 0.94-point spread was largely the park holding still.
    "a6f0_s21":  dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=0.0,
                      start_offset=1),
    "a6f0_s42":  dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=0.0,
                      start_offset=2),
    "a6f0_s63":  dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=0.0,
                      start_offset=3),
    "a6f0_lag1": dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=0.0,
                      rank_lag=1),
    "a6f0_lag5": dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=0.0,
                      rank_lag=5),
    # §2's rider, priced. Its block count says how often it fired; only this cell says what firing
    # BOUGHT. `held_book` in the stats carries the continuous effective-bets read for both, which
    # is the measurement the 1.84-effective-bet finding was made with.
    "a6f0_norider": dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                         trail=True, next_open=True, entry_rule="banded", rider_bets=0.0,
                         rider=False),
    # §3's sensitivity grid. ONE axis each, off a6_floor0. A centre that survives its falsifiers
    # but has never been perturbed on N or on the exit band is a partial result.
    "a6f0_x25":  dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=0.0,
                      exit_rank=25),
    "a6f0_x60":  dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=0.0,
                      exit_rank=60),
    "a6f0_n10":  dict(n=10, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=0.0),
    "a6f0_n15":  dict(n=15, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=0.0),
    # the trail's SHAPE, not its levels — WO-A5's ladder already moved the levels one step either
    # side. `atr` is the work order's own 3xATR(20)/+1R/8xATR(22); `noeuph` disables the euphoria
    # tighten by holding the band at its wide value, which is the cleanest way to ask what the
    # 5% leash is worth without inventing a replacement number for it.
    "a6f0_atr":  dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=0.0,
                      trail_cfg=TRAIL_ATR),
    "a6f0_noeuph": dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                        trail=True, next_open=True, entry_rule="banded", rider_bets=0.0,
                        trail_cfg=dict(TRAIL_DEFAULTS, euphoria=TRAIL_DEFAULTS["wide"])),
    # A6-F: does the ROAD to the 12-month return matter, or only the return?
    "a6f0_path": dict(n=12, months=6, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, entry_rule="banded", rider_bets=0.0,
                      path_quality_gate=True),
    # ---- WO-A6 §5, the B-arm. Two tranches on alternating bi-monthly dates, so half the book is
    # always two months old and half four. It is the phase test moved INSIDE one run: you cannot
    # own six phases of the same account, but you can own two, and if phase luck is what the
    # 15.1-point bi-monthly spread was made of then holding both halves should collect its mean
    # rather than a draw from it. `b0` is the centre; `b_ph1..b_ph5` are the same rule started one
    # to five months later, and the SPREAD across those six is the arm's real number.
    # The clock is the 42-SESSION one the §1 table measured, not a two-calendar-month one: a
    # `months=2` calendar has only two distinct phases (offset 2 repeats offset 0), so the
    # six-phase spread Zak is comparing against can only be built on the session clock.
    #
    # Three steps get from the existing `s42_p0` to the B centre, and each is a real cell rather
    # than a bookkeeping stop on the way: n 8 -> 12, then §2's rider as SPECIFIED (floor 5, which
    # a6_floor4 showed cripples a banded book — worth knowing whether it does the same here), then
    # the floor off so only the cluster cap binds, which is how A6 actually runs.
    "s42n12_p0": dict(n=12, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, every_sessions=42),
    "s1cap_p0":  dict(n=12, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, every_sessions=42, rider_calendar=True),
    "s1_p0":     dict(n=12, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, every_sessions=42, rider_calendar=True,
                      rider_bets=0.0),
    "b_p0":      dict(n=12, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, every_sessions=42, rider_calendar=True,
                      rider_bets=0.0, tranches=2),
    # the remaining five phases of each, which is §5's second clause. Each `b_p*` shares every
    # parameter with its `s1_p*` twin except the tranche count, so the pair prices TRANCHING
    # rather than tranching plus a rider plus a phase.
    **{f"s1_p{p}": dict(n=12, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                        trail=True, next_open=True, every_sessions=42, rider_calendar=True,
                        rider_bets=0.0, offset=p)
       for p in (7, 14, 21, 28, 35)},
    **{f"b_p{p}": dict(n=12, months=2, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                       trail=True, next_open=True, every_sessions=42, rider_calendar=True,
                       rider_bets=0.0, tranches=2, offset=p)
       for p in (7, 14, 21, 28, 35)},
    # ---- WO-A7, Zak's ruling of 2026-08-14: "the only thing I want to run is something that
    # confirms a 30+% return or finds one." The bi-monthly B-arm cannot — its own phase mean is
    # 20.58%, below the ETF, and tranching collects a mean rather than a maximum. The WEEKLY clock
    # can: its five phases mean 36.25% and three of the five carry a Sharpe ABOVE SPMO's 0.987.
    # Its defect is that you get ONE of those phases, drawn from a 14.1-point spread, and which
    # one is decided by the day you happen to start. Tranching is exactly the instrument for that:
    # five sub-books, each on its own weekly phase, held simultaneously.
    #
    # `every_sessions=1, tranches=5` is what builds them — every session is a rebalance date and
    # `turn` cycles 0..4, so tranche k rebalances on sessions congruent to k mod 5. That IS the
    # five weekly phases, running at once.
    #
    # N moves 8 -> 10 so the five tranches divide evenly (two names each). The `w10_p*` controls
    # exist to price the tranching against its OWN phase mean at the same N — comparing a
    # ten-name tranched book against the stored eight-name phases would move two axes and prove
    # nothing.
    "w10_p0": dict(n=10, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                   trail=True, next_open=True, every_sessions=5),
    **{f"w10_p{p}": dict(n=10, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                         trail=True, next_open=True, every_sessions=5, offset=p)
       for p in (1, 2, 3, 4)},
    # `d10_p0` is the daily n=10 book — the un-tranched version of the clock `w10_t5` runs on, and
    # the cell that isolates what the tranching is worth. It is also the churn case A6 was designed
    # against, at this N, so it is worth having on the record rather than being a bookkeeping stop.
    "d10_p0": dict(n=10, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                   trail=True, next_open=True, every_sessions=1),
    "w10_t5": dict(n=10, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                   trail=True, next_open=True, every_sessions=1, tranches=5),
    # ---- WO-A7 §10: the weekly arm's sensitivity grid, deliberately mirroring WO-A6 §3 cell for
    # cell so the two arms are compared on equal footing. A6's headline fell 2.59 points the moment
    # its grid ran; comparing a GRIDDED A6 against an UNGRIDDED weekly arm would hand the weekly
    # arm the same unearned advantage A6 briefly had, which is the error this grid exists to avoid.
    #
    # Four axes, one move each, all off `w10_t5`. The exit band has no analogue here — a staggered
    # calendar book has no rank hysteresis; names leave at their tranche's refresh or on the trail
    # — so the pool takes its slot, and §4.1 makes that the single biggest lever in the programme
    # and one never perturbed on this clock.
    "w10_n5":   dict(n=5, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=1, tranches=5),
    "w10_n15":  dict(n=15, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=1, tranches=5),
    # the tranche count itself. `d10_p0` above is the tranches=1 end of this axis and is already
    # declared; ten tranches refreshes each single-name sub-book fortnightly instead of weekly.
    "w10_t10":  dict(n=10, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=1, tranches=10),
    "w10_atr":  dict(n=10, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=1, tranches=5,
                     trail_cfg=TRAIL_ATR),
    "w10_noeuph": dict(n=10, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                       trail=True, next_open=True, every_sessions=1, tranches=5,
                       trail_cfg=dict(TRAIL_DEFAULTS, euphoria=TRAIL_DEFAULTS["wide"])),
    "w10_pool250": dict(n=10, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=250,
                        trail=True, next_open=True, every_sessions=1, tranches=5),
    # ---- WO-A8. `w10_n5` topped the §10 grid at 37.76% and is the arm Zak asked to chase. The
    # forensics on run 340 found four things, and each cell below answers exactly one of them.
    # Nothing here is a guess: every axis traces to a measured number in
    # `docs/wo-a8-2026-08-14.md` §1. The centre is `w10_n5` itself — five names, one per weekly
    # tranche — already stored as run 340, so it is not re-run.
    #
    # 1. The euphoria tighten fires constantly on a book whose names run 60% realized vol, and
    #    removing it already bought +1.68 points on the ten-name version.
    "w5_noeuph": dict(n=5, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                      trail=True, next_open=True, every_sessions=1, tranches=5,
                      trail_cfg=dict(TRAIL_DEFAULTS, euphoria=TRAIL_DEFAULTS["wide"])),
    # 2. §3.2's valid-base clause, never implemented on a calendar book. 78.6% of stop exits are
    #    re-bought inside 21 days, average 6.4 days out; one name round-tripped 29 times.
    "w5_door":  dict(n=5, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=1, tranches=5, base_gate=True),
    # 3. Realized volatility runs 19% in 2017 and 69% in 2026 and the annual Sharpe tracks it
    #    inversely. Barroso–Santa-Clara was rejected on A6 — a slow twelve-name book where the
    #    trail already did the job. This is the opposite book, and the governor is worth re-asking.
    "w5_vt40":  dict(n=5, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=1, tranches=5, vol_target=0.40),
    "w5_vt55":  dict(n=5, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                     trail=True, next_open=True, every_sessions=1, tranches=5, vol_target=0.55),
    # 4. The "8%" initial stop delivers −14.55% on the 261 trades it closes below −10%, because
    #    these names gap straight through it. It is not protecting at its stated level, and every
    #    stop manufactures a re-entry. Two ends of that axis: no trail at all, so the weekly
    #    rebalance is the only exit; and an initial wide enough to sit outside the noise.
    "w5_notrail": dict(n=5, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                       trail=False, next_open=True, every_sessions=1, tranches=5),
    "w5_init15":  dict(n=5, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                       trail=True, next_open=True, every_sessions=1, tranches=5,
                       trail_cfg=dict(TRAIL_DEFAULTS, initial=0.15)),
    # ---- WO-A8 §4. `w5_notrail` returned 43.91% and Zak asked, correctly, what might be
    # inflating it. Two asymmetries were found and both are tested here.
    #
    # The rank is computed from bars <= i and the book trades at `adj[i]` — the SAME close. That is
    # a one-bar advantage no one can take, and it scales with clock speed. Worse, it is not applied
    # evenly: 47% of the CENTRE's exits are trail stops filled at the next OPEN, genuinely lagged,
    # while 100% of `w5_notrail`'s exits are rebalances at the deciding close. **Removing the stop
    # removed the only conservatively-filled exits in the model**, so part of its margin may be
    # execution rather than strategy. The lag pairs below price exactly that.
    "w5_nt_lag1": dict(n=5, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                       trail=False, next_open=True, every_sessions=1, tranches=5, rank_lag=1),
    "w5_nt_lag2": dict(n=5, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                       trail=False, next_open=True, every_sessions=1, tranches=5, rank_lag=2),
    # the centre carried through the same lag, so the COMPARISON stays honest even if both fall.
    "w5_c_lag1":  dict(n=5, months=1, risk_adjusted=True, sleeve=1.00, top_by_addv=500,
                       trail=True, next_open=True, every_sessions=1, tranches=5, rank_lag=1),
}


COST_MULT = 1.0          # WO-A5 §3.1 sets this per cell; §2.2's curve is the 1.0 case


def spread_frac(addv):
    for floor, bps in SPREAD_CURVE:
        if addv >= floor:
            return bps / 10_000.0 * COST_MULT
    return SPREAD_CURVE[-1][1] / 10_000.0 * COST_MULT


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
    op = np.full(shape, np.nan)
    lo = np.full(shape, np.nan)
    hi = np.full(shape, np.nan)
    for row in tape:
        tk, d, close, a, vol = row[:5]
        if d not in di:
            continue          # a bar printed on a day the market was shut — not a session
        i, j = di[d], ti[tk]
        if a is None or a <= 0:
            continue
        adj[i, j] = float(a)
        raw[i, j] = float(close) if close is not None else np.nan
        dv[i, j] = float(a) * float(vol) if vol is not None else np.nan
        if len(row) >= 8 and close:
            # the whole bar is rescaled by the session's own adj/close factor, so open, high and
            # low sit on the SAME axis as the adjusted closes the stop is set from. Comparing a raw
            # low to an adjusted stop is the split defect that invalidated runs 18-44, in a new
            # place. The high is carried for WO-A6 §3's ATR rung: true range needs it, and a range
            # built from closes alone would be an invented substitute for a measurable quantity.
            f = float(a) / float(close)
            op[i, j] = float(row[7]) * f if row[7] is not None else np.nan
            lo[i, j] = float(row[6]) * f if row[6] is not None else np.nan
            hi[i, j] = float(row[5]) * f if row[5] is not None else np.nan
    return dates, tickers, adj, raw, dv, op, lo, hi


def session_rebalances(dates, every, warmup, offset=0):
    """Rebalance every `every` SESSIONS rather than on a month boundary.

    Calendar months bottom out at monthly; this is how the frequency axis is pushed past it to
    fortnightly, weekly and daily. `offset` shifts the starting session so the same
    spread-across-arbitrary-choices test applies — at `every=1` there is nothing left to shift,
    which is itself the point: a daily book has no date luck available to it at all.
    """
    if every < 1:
        raise ValueError(f"a rebalance interval of {every} sessions is not a schedule")
    return [i for i in range(warmup + offset, len(dates)) if (i - warmup - offset) % every == 0]


def rebalance_dates(dates, months, warmup, offset=0):
    """The first session of each period, after the formation window is available.

    `offset` shifts the calendar by whole months, and it exists to answer Zak's objection to the
    clock result: *"we are relying on TIME to tell us when to go back in? And not an observation
    of the market?"* Semi-annual over nine years is EIGHTEEN decision points. If a Jan/Jul book
    beats a monthly one because slower re-entry avoids buying into declines, then Feb/Aug and
    Mar/Sep must beat it too. If they do not, the finding was never about frequency — it was about
    where 2018, 2020 and 2022 happened to fall relative to two arbitrary dates, and the honest
    reading is date luck.

    The bucket is computed on an absolute month index rather than (year, month // n), so the
    periods stay contiguous across a year boundary at any offset — `offset=1` on a six-month clock
    must give Feb-Jul and Aug-Jan, not a short bucket every December.
    """
    out, seen = [], set()
    for i, d in enumerate(dates):
        if i < warmup:
            continue
        key = (d.year * 12 + d.month - 1 - offset) // months
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


def base_state(i, j, adj):
    """WO-A6 §1's valid-base STATE — evaluable on any session, unlike a breakout event.

    Three conditions, all the work order's: the close sits within 10% of the name's own
    252-session high close, the close is above its 50-day SMA, and that SMA is higher than it was
    ten sessions ago. Together they say "this name is near its highs and its trend is still
    rising", which is a condition a nightly review can check — not a one-day aperture that admits
    whoever happened to break out today. That aperture is what produced WO-A6(event-door)'s 1.54%.

    All windows read bars <= i. Unknown is False: a door that cannot be evaluated stays shut.
    """
    if i < A6_HIGH_WINDOW or not np.isfinite(adj[i, j]):
        return False
    px = float(adj[i, j])
    hi_w = adj[i - A6_HIGH_WINDOW + 1:i + 1, j]
    hi_w = hi_w[np.isfinite(hi_w)]
    if not len(hi_w) or px < hi_w.max() * (1.0 - A6_HIGH_PROX):
        return False
    sma_w = adj[i - A6_SMA + 1:i + 1, j]
    sma_w = sma_w[np.isfinite(sma_w)]
    if len(sma_w) < A6_SMA or px <= sma_w.mean():
        return False
    prev = adj[i - A6_SMA + 1 - A6_SMA_SLOPE:i + 1 - A6_SMA_SLOPE, j]
    prev = prev[np.isfinite(prev)]
    return bool(len(prev) >= A6_SMA and sma_w.mean() > prev.mean())


def return_corr(i, idx, adj, window=A6_RIDER_WINDOW):
    """Pairwise correlation of daily returns over the trailing window, for the names in `idx`.

    Sessions where any name in the set did not print are dropped, so every pair is measured on
    the same rows — a pairwise-complete matrix can fail to be positive semi-definite and would
    make the effective-bets denominator meaningless.
    """
    w = adj[max(0, i - window):i + 1, idx]
    if w.shape[0] < 3 or w.shape[1] == 0:
        return None
    rets = np.diff(w, axis=0) / w[:-1]
    keep = np.isfinite(rets).all(axis=1)
    rets = rets[keep]
    if rets.shape[0] < 20 or (rets.std(axis=0) == 0).any():
        return None
    return np.corrcoef(rets, rowvar=False).reshape(len(idx), len(idx))


def effective_bets(corr):
    """§2.2's own formula, 1 / sum(wi wj rho_ij), equal weights."""
    k = corr.shape[0]
    w = np.full(k, 1.0 / k)
    denom = float(w @ corr @ w)
    return float("inf") if denom <= 0 else 1.0 / denom


def clusters_at(corr, rho=A6_RIDER_RHO):
    """Single-linkage clusters: a name joins if it correlates above `rho` with ANY member.

    **The clustering method, pre-registered here because WO-A6 §2 requires one to be named.**
    Single-linkage is the conservative choice for this purpose — it merges readily, so it CAPS
    more aggressively than complete-linkage would, and a rider meant to prevent a 1.84-effective-
    bet book should err toward calling things related rather than unrelated.
    """
    k = corr.shape[0]
    parent = list(range(k))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a in range(k):
        for b in range(a + 1, k):
            if corr[a, b] > rho:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra
    sizes = {}
    for a in range(k):
        r = find(a)
        sizes[r] = sizes.get(r, 0) + 1
    return sizes


def rider_ok(i, book, adj, floor=None):
    """WO-A6 §2, checked at FORMATION only — it never forces an exit.

    Two interpretation calls, both stated rather than buried:

    * **The effective-bets floor binds only once the book could satisfy it.** A book of three
      names cannot have five effective bets under any correlation structure, so a literal reading
      would refuse every entry and the book would never fill at all. The floor applies from the
      fifth name onward; below that only the cluster cap binds.
    * **Unmeasurable correlation admits the name.** Too few shared sessions to compute a matrix
      means the rider abstains rather than blocking, because the alternative is a liquidity-and-
      history filter masquerading as a diversification rule. It is logged, not silent.
    """
    if len(book) <= 1:
        return True, "single name"
    corr = return_corr(i, list(book), adj)
    if corr is None:
        return True, "correlation unmeasurable — rider abstained"
    if max(clusters_at(corr).values()) > A6_RIDER_PER_CLUSTER:
        return False, "cluster cap"
    bar = A6_RIDER_BETS if floor is None else float(floor)
    if bar > 0 and len(book) >= int(bar) and effective_bets(corr) < bar:
        return False, "effective bets below floor"
    return True, "ok"


def path_quality(i, j, adj, window=A6_PATH_WINDOW):
    """Share of up-days over the formation window. None where the window is incomplete.

    WO-A6 §3's A6-F rung. Two names can post the same 12-month return by very different roads —
    one grinding, one on three gaps — and the claim under test is that the grinding one is the
    better hold. This measures the road; `path_gate` below decides what to do with it.
    """
    w = adj[max(0, i - window):i + 1, j]
    w = w[np.isfinite(w)]
    if len(w) < window // 2:
        return None
    r = np.diff(w) / w[:-1]
    return float((r > 0).mean()) if len(r) else None


def path_gate(i, cand, adj, pool):
    """Does `cand` clear the POOL MEDIAN share of up-days? WO-A6 §3 sets the bar at the median of
    the top-50 by rank, so the gate is relative and carries no invented threshold — it moves with
    whatever the market is currently offering rather than asserting a level.

    Names whose path cannot be measured are admitted, on the same reasoning as the rider: a filter
    that silently doubles as a history requirement is not the filter it claims to be.
    """
    q = path_quality(i, cand, adj)
    if q is None:
        return True
    peers = [p for p in (path_quality(i, k, adj) for k in pool) if p is not None]
    if len(peers) < 5:
        return True
    return q >= float(np.median(peers))


def at_new_high(i, j, adj, window=ENTRY_HIGH):
    """Does today's close exceed every close in the PRIOR `window` sessions?

    Strictly prior — `adj[i - window:i]` excludes today, so the comparison is against history the
    market had already printed. Unknown (not enough history, or today did not print) is False: a
    door that cannot be evaluated must not open.
    """
    if i < window or not np.isfinite(adj[i, j]):
        return False
    past = adj[i - window:i, j]
    past = past[np.isfinite(past)]
    return bool(len(past) and adj[i, j] > past.max())


def pick_book(ranked, n, sectors=None, cap=None, held_sectors=None):
    """The top `n` off the ranked list, optionally with no sector taking more than `cap` of the
    book. Skipped names are passed over, not dropped — the slot goes to the next eligible name, so
    the book is still `n` deep.

    Zak, 2026-08-13: *"I don't think there should be a theme cap honestly... Maybe 70%. It's OK to
    go in and go hard on a theme... and accept a bad drawdown when it happens. Ride the wins."* So
    the cap is deliberately loose: at eight names, 0.7 permits five of one sector.

    **Stated limit:** `universe.sector` is the vendor's CURRENT label, not a point-in-time one.
    Sector membership is far more stable than price, so this is a mild look-ahead rather than a
    material one — but it is a look-ahead, and a cell that uses it cannot be compared to one that
    does not without saying so.
    """
    if not cap or sectors is None:
        return ranked[:n]
    room = max(1, int(n * cap))
    picked, used = [], dict(held_sectors or {})
    for j in ranked:
        sec = sectors[j] or "?"
        if used.get(sec, 0) >= room:
            continue
        picked.append(j)
        used[sec] = used.get(sec, 0) + 1
        if len(picked) >= n:
            break
    return picked


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


def stop_fill(stop, op, lo):
    """Where a resting stop-market order actually fills on a session, given its bar.

    Broker semantics, not close semantics:
      * the session **opens through** the stop → it fills at the OPEN, worse than the stop. This
        is the gap, and a close-based test cannot see it at all.
      * the stop sits inside the day's range → it fills AT the stop.
      * the low never reaches it → no fill.

    Returns None when the bar cannot decide, so the caller falls back to the close-based path
    rather than inventing a fill. Whether this flatters the arm or not is genuinely unknown in
    advance and is the reason WO-A5 pre-registers both: it fills earlier on a name that keeps
    falling, and it also fires on an intraday spike the close recovered from — the classic reason
    mechanical stops underperform the backtest that priced them on closes.
    """
    if not (np.isfinite(lo) and np.isfinite(op)):
        return None
    if op <= stop:
        return float(op)
    if lo <= stop:
        return float(stop)
    return None


def atr(i, j, highs, lows, adj, window):
    """Wilder's true range, averaged over `window` sessions ending at `i`. None if unmeasurable.

    TR is max(high-low, |high - prev close|, |prev close - low|) — the two gap terms are the whole
    point of using ATR rather than the bar's own range, and dropping them would quietly under-state
    volatility on exactly the names this book holds. Sessions missing any of the three inputs are
    dropped rather than filled; a window with fewer than `window` complete rows returns None and
    the caller falls back rather than trading on a number built from nothing.
    """
    if highs is None or lows is None or window < 1 or i < window:
        return None
    h = highs[i - window + 1:i + 1, j]
    lw = lows[i - window + 1:i + 1, j]
    pc = adj[i - window:i, j]
    ok = np.isfinite(h) & np.isfinite(lw) & np.isfinite(pc)
    if ok.sum() < window:
        return None
    h, lw, pc = h[ok], lw[ok], pc[ok]
    tr = np.maximum(h - lw, np.maximum(np.abs(h - pc), np.abs(pc - lw)))
    v = float(tr.mean())
    return v if v > 0 else None


def trail_stop_atr(px, st, cfg):
    """WO-A6 §3's ATR rung, as the work order specifies it: 3xATR(20) initial, +1R arm,
    8xATR(22) Chandelier. Every constant here is the WO's own; none is inferred.

    `st["atr_init"]` and `st["atr_chand"]` are stamped at ENTRY and at each session respectively by
    the caller, because ATR(20) at entry defines R for the life of the trade while the Chandelier
    reads today's ATR(22). Where ATR is unmeasurable the caller leaves the previous value in place,
    so the stop holds rather than jumping.
    """
    r = st.get("atr_init")
    if not r:
        return st["stop"]
    want = st["entry"] - cfg["atr_init_mult"] * r
    if st["armed"] or px >= st["entry"] + r * cfg["atr_arm_r"]:
        st["armed"] = True
        a = st.get("atr_chand") or r
        want = max(want, st["hi"] - cfg["atr_chand_mult"] * a)
    return max(st["stop"], want)


def open_state(px, i, j, cfg, bars, adj):
    """The per-name trail state at entry. One constructor, because there are three entry paths
    (calendar rebalance, WO-A6's banded door, WO-A6e's new-high door) and a stop that differs by
    which door a name came through is a bug waiting for a cell to expose it.

    In ATR mode R is stamped here and never recomputed: the initial risk defines the arm threshold
    for the life of the trade. Where ATR(20) cannot be measured at entry the name falls back to
    §3.2's percentage initial rather than entering with no stop at all.
    """
    c = cfg or TRAIL_DEFAULTS
    # ATR mode carries no percentage bands, so §3.2's own initial is the fallback there.
    init = c.get("initial", TRAIL_DEFAULTS["initial"])
    st = dict(entry=px, hi=px, armed=False, entered=i, stop=px * (1 - init))
    if c.get("mode") == "atr":
        hi_a, lo_a = bars if bars is not None else (None, None)
        r = atr(i, j, hi_a, lo_a, adj, c["atr_init_window"])
        if r:
            st["atr_init"] = r
            st["stop"] = px - c["atr_init_mult"] * r
    return st


def trail_stop(px, st, closes, cfg=None):
    """§3.2's ratchet for one name on one session. Returns the stop, never below its last value.

    `closes` is the name's own trailing window of adjusted closes ending today, for the euphoria
    test. The initial stop is live from entry; the 10% trail replaces it only once the name has
    printed +15% from average cost, and stays armed thereafter (the plan ratchets up, never down).

    `cfg` overrides the four bands. WO-A5's ladder moves each one step either side to find out
    whether the champion is a plateau or a spike; the DEFAULTS, and only the defaults, are §3.2's
    own numbers, and a cell that varies them is a probe rather than a candidate.
    """
    c = cfg or TRAIL_DEFAULTS
    want = st["entry"] * (1 - c["initial"])
    if st["armed"] or px >= st["entry"] * (1 + c["arm"]):
        st["armed"] = True
        band = c["wide"]
        w = closes[np.isfinite(closes)]
        if len(w) >= EUPHORIA_WINDOW:
            sd = w.std(ddof=1)
            # a flat window has no standard deviation to be two of. Without this, "> mean + 0"
            # calls any uptick euphoric, and a halted name printing one price for fifty sessions
            # arrives back from the halt on a 5% leash.
            if sd > 0 and px > w.mean() + EUPHORIA_SD * sd:
                band = c["euphoria"]
        want = max(want, st["hi"] * (1 - band))
    return max(st["stop"], want)


def simulate(dates, tickers, adj, raw, dv, park_px, *, n, months, risk_adjusted, sleeve,
             start_nav, top_by_addv=None, index_px=None, gate_every=21, trail=False,
             vol_target=None, trail_cfg=None, intraday=None, next_open=None, bars=None,
             sectors=None, sector_cap=None, offset=0, entry_rule=None,
             start_offset=0, every_sessions=None, rank_lag=0, rider_bets=None,
             rider=True, exit_rank=None, path_quality_gate=False, tranches=1,
             rider_calendar=False, base_gate=False):
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
    warmup = warmup + int(start_offset * 21)      # WO-A6: shift when trading begins, in months
    if entry_rule:
        rebal_list = []         # no calendar exists in either event mode
    elif every_sessions:
        rebal_list = session_rebalances(dates, int(every_sessions), warmup, offset)
    else:
        rebal_list = rebalance_dates(dates, months, warmup, offset)
    rebals = set(rebal_list)
    # WO-A6 §5's B-arm needs to know WHICH rebalance this is, not merely that one is due: with
    # two tranches only one of them is refreshed per date, and which one alternates.
    rebal_ord = {i: k for k, i in enumerate(sorted(rebal_list))}
    tranches = max(1, int(tranches))
    tranche_of = {}                 # ticker index -> which tranche is carrying it
    held = {}                       # ticker index -> shares
    state = {}                      # ticker index -> {entry, hi, stop, armed} for the §3.2 trail
    last_px = {}                    # ticker index -> the most recent price it actually printed
    park_qty, cash = 0.0, start_nav
    equity, trades, costs = [], [], 0.0
    navs = []                       # the NAV path alone, for the volatility governor
    stale_skips, empty_rebals, rider_blocks = 0, [], {}
    bets_series, cluster_series = [], []   # WO-A6 §2's reported (not enforced) continuous read

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

    def sell(i, j, qty, reason, price_override=None):
        """Sell `qty` shares of name j at its price today. A name that did not print cannot be
        sold — the position stays and is retried next session, which is what a halt or a holiday
        actually does to an order.

        `price_override` is the intraday stop fill: a resting order does not execute at the close.
        `price()` is still called so the name's last mark stays current for the rest of the walk.
        """
        nonlocal cash, costs
        px_j = price(i, j)
        if price_override is not None and np.isfinite(price_override):
            px_j = float(price_override)
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
            if j not in held:
                queued.remove(j)
                continue
            # `next_open` fills the morning after the close that broke the stop — the path a
            # person who reviews at night and places a market-on-open order actually takes, and
            # the one §3.2's hair-trigger already names ("exit next morning").
            at = float(next_open[i, j]) if (next_open is not None
                                            and np.isfinite(next_open[i, j])) else None
            if sell(i, j, held[j], "trail_stop", price_override=at):
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
            # WO-A8 §4: the rank-lag falsifier, which the CALENDAR path has never had — `rank_lag`
            # was wired to the banded door only, so no calendar cell in the ledger has ever been
            # asked this question.
            #
            # It matters most exactly here. `rank_at(i)` reads bar i (the volatility denominator,
            # the ADDV filter and the price floor all include today) and the book then trades at
            # `adj[i]`, the same session's close. You cannot do that: you need the close to compute
            # the rank, so the earliest you can act is the next session. Every calendar arm carries
            # that one-bar advantage, and it compounds with clock speed — twice a year for the
            # semi-annual book, 252 times a year for this one.
            #
            # `rank_lag=1` is the honest version: decide on data through i-1, execute at i's close.
            # Only the OBSERVATION moves; sizing and fills stay at i.
            obs_i = max(warmup, i - int(rank_lag))
            ranked = rank_at(obs_i, adj, raw, dv, risk_adjusted=risk_adjusted,
                             top_by_addv=top_by_addv)
            # ---- WO-A6 §5's B-arm. With `tranches` > 1 the book is split into equal sub-books
            # that rebalance on ALTERNATING dates, so at any moment half the book was chosen two
            # months ago and half four. That is the same phase-averaging the six-cell phase test
            # does ACROSS runs, moved INSIDE one run — which is the only version of it a person
            # can actually hold, since you cannot own six phases of the same account. The rest of
            # the block below is unchanged; only the slot count, the capital share and the sell
            # list are scoped to the tranche whose turn it is.
            turn = rebal_ord.get(i, 0) % tranches
            for j in [j for j in tranche_of if j not in held]:
                tranche_of.pop(j)       # the trail took it; its slot returns to its tranche
            mine = {j for j, t in tranche_of.items() if t == turn}
            theirs = {j for j, t in tranche_of.items() if t != turn}
            slots = max(1, n // tranches)
            pool = [j for j in ranked if j not in theirs]
            # ---- WO-A8: §3.2's re-entry clause, which the calendar path has never implemented.
            #
            #   "A stop-out carries no cooldown — re-entry requires a valid base and all gates,
            #    nothing more."
            #
            # A calendar book has no concept of a base: it re-buys whatever ranks, including the
            # name it stopped out of four sessions ago. Measured on run 340, **78.6% of trail-stop
            # exits are re-bought within 21 days**, average 6.4 days out — one name round-tripped
            # 29 times in ten months. This is not a cooldown (the plan forbids one) and it is not
            # a new rule; it is the valid-base half of the clause the plan already carries, using
            # WO-A6's `base_state` as the base test. A name that stopped out and has not climbed
            # back to a valid base is refused; a name that has is bought with no delay at all.
            if base_gate:
                gated = [j for j in pool if base_state(obs_i, j, adj)]
                rider_blocks["no valid base"] = (rider_blocks.get("no valid base", 0)
                                                 + len(pool) - len(gated))
                pool = gated
            if rider_calendar:
                # §5 attaches §2's rider to the B-arm. Kept behind its OWN flag rather than the
                # banded `rider`: every A4 and A5 calendar cell in the ledger ran without it, and
                # a default that reached back into this path would silently re-price all of them.
                want, carried = [], list(theirs)
                for j in pool:
                    if len(want) >= slots:
                        break
                    ok, why = rider_ok(i, carried + want + [j], adj, floor=rider_bets)
                    if not ok:
                        rider_blocks[why] = rider_blocks.get(why, 0) + 1
                        continue
                    want.append(j)
                want = pick_book(want, slots, sectors, sector_cap)
            else:
                want = pick_book(pool, slots, sectors, sector_cap)
            wanted = set(want)
            for j in want:
                tranche_of[j] = turn
            # sell what fell out of THIS tranche, and the park, then buy its new book. A name the
            # other tranche is carrying is never sold here and never re-bought here — it belongs
            # to a book that is not being rebalanced today.
            for j in list(held):
                if j not in wanted and (tranches == 1 or j in mine):
                    sell(i, j, held[j], "rebalance")
                    tranche_of.pop(j, None)
            # A single-tranche book rebalances its WHOLE self, so emptying the park and re-parking
            # the remainder costs one round trip per rebalance and is right. A tranche does not:
            # it touches a fifth of the account, and liquidating the other four fifths' park on its
            # date would charge the whole book a spread every session the clock ticks. At
            # every_sessions=1 with five tranches that is 2,260 park round trips instead of 452, a
            # cost the arm never actually incurs. Tranched books unpark on demand instead, exactly
            # as the banded door does.
            if park_qty > 0 and tranches == 1:
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
            #
            # The park is in this sum too, and must be. For a single-tranche book it is zero here
            # — the block above just liquidated it — so this changes nothing for any stored cell.
            # For a tranched book nothing was liquidated, and reading NAV as cash-plus-holdings
            # gave nav = 0 on the first rebalance: everything sat in the park, per_name came out
            # zero, and the book bought nothing for the whole run while reporting no error at all.
            nav = (cash + park_qty * float(park_px[i])
                   + sum(q * (price(i, j) or 0.0) for j, q in held.items()))
            eff_sleeve = sleeve * (vol_scalar(navs, float(vol_target)) if vol_target else 1.0)
            # ... and the active tranche funds its OWN share of the account, not the whole of it.
            # At tranches=2, n=12 this is nav/2 across 6 slots — the same per-name weight the
            # single-tranche twelve-name book carries, which is what makes the two comparable.
            per_name = nav * eff_sleeve / (tranches * max(len(want), 1)) if want else 0.0
            funded = 0
            for j in want:
                if not np.isfinite(adj[i, j]):
                    stale_skips += 1  # never BUY on a stale mark — only hold and sell on one
                    continue
                px = float(adj[i, j])
                fee_frac = spread_frac(np.nanmedian(dv[max(0, i - ADDV_WINDOW):i + 1, j]))
                have = held.get(j, 0.0) * px
                if tranches > 1:
                    want_cash = max(per_name - have, 0.0) * (1 + fee_frac)
                    if cash < want_cash:
                        unpark(i, want_cash - cash)
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
                    state[j] = open_state(px, i, j, trail_cfg, bars, adj)
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
        # ---- WO-A6 (banded): observe every session, transact only on gates. `rank_lag` is the
        # second falsifier — it evaluates the rank and the base state on session i-lag while
        # execution stays at i. The work order's §0 claims timing luck "dies by construction"
        # here; a rule that genuinely responds to a slow state should barely notice being read a
        # day late, and one that moves materially was riding a specific-day effect after all.
        if entry_rule == "banded" and i >= warmup and np.isfinite(park_px[i]):
            obs = max(warmup, i - int(rank_lag))
            order = rank_at(obs, adj, raw, dv, risk_adjusted=risk_adjusted,
                            top_by_addv=top_by_addv)
            rank_of = {j: r for r, j in enumerate(order, start=1)}
            # exit gate 2: the rank band. The trail below is gate 1 and runs unchanged.
            band = A6_EXIT_RANK if exit_rank is None else int(exit_rank)
            for j in list(held):
                if rank_of.get(j, 10 ** 9) > band and j not in queued:
                    queued.append(j)
            # entry gate: the state-door, highest qualifying rank first, rider on the RESULT
            if len(held) < n:
                nav_now = mark(i)
                eff = sleeve * (vol_scalar(navs, float(vol_target)) if vol_target else 1.0)
                per_name = nav_now * eff / n
                for j in order[:A6_ENTRY_RANK]:
                    if len(held) >= n:
                        break
                    if j in held or j in queued or not np.isfinite(adj[i, j]):
                        continue
                    if not base_state(obs, j, adj):
                        continue
                    if path_quality_gate and not path_gate(obs, j, adj, order[:A6_PATH_POOL]):
                        rider_blocks["path quality"] = rider_blocks.get("path quality", 0) + 1
                        continue
                    # `rider=False` is the one-axis cell that PRICES the rider. Without it the
                    # only evidence the rider works is its own block count, which measures how
                    # often it fired and not what firing bought.
                    if rider:
                        ok, why = rider_ok(obs, list(held) + [j], adj, floor=rider_bets)
                        if not ok:
                            rider_blocks[why] = rider_blocks.get(why, 0) + 1
                            continue        # step DOWN the rank to the next qualifier
                    px = float(adj[i, j])
                    fee_frac = spread_frac(np.nanmedian(dv[max(0, i - ADDV_WINDOW):i + 1, j]))
                    if cash < per_name * (1 + fee_frac):
                        unpark(i, per_name * (1 + fee_frac) - cash)
                    spend = min(per_name, cash / (1 + fee_frac))
                    if spend <= 0:
                        continue
                    qty = spend / (px * (1 + fee_frac))
                    held[j] = held.get(j, 0.0) + qty
                    cash -= spend
                    costs += spend * fee_frac / (1 + fee_frac)
                    state[j] = open_state(px, i, j, trail_cfg, bars, adj)
                    trades.append(dict(ticker=tickers[j], entry_date=dates[i], spend=spend,
                                       price=px, qty=qty))
                park_all(i)

        # ---- WO-A6: the door, checked every session. No calendar exists in this mode; a free
        # slot is filled by the highest-ranked name printing a new 252-session high, and a name
        # that stopped out cannot return until it has climbed back to one. That is the churn fix
        # and it costs no invented constant.
        if entry_rule == "new_high" and len(held) < n and np.isfinite(park_px[i]) and i >= warmup:
            ranked = [j for j in rank_at(i, adj, raw, dv, risk_adjusted=risk_adjusted,
                                         top_by_addv=top_by_addv) if j not in held]
            door = [j for j in ranked if at_new_high(i, j, adj)]
            if door:
                held_sec = {}
                if sectors is not None:
                    for j in held:
                        sec = sectors[j] or "?"
                        held_sec[sec] = held_sec.get(sec, 0) + 1
                take = pick_book(door, n - len(held), sectors, sector_cap, held_sec)
                nav = mark(i)
                eff = sleeve * (vol_scalar(navs, float(vol_target)) if vol_target else 1.0)
                per_name = nav * eff / n
                for j in take:
                    px = float(adj[i, j])
                    fee_frac = spread_frac(np.nanmedian(dv[max(0, i - ADDV_WINDOW):i + 1, j]))
                    want_cash = per_name * (1 + fee_frac)
                    if cash < want_cash:
                        unpark(i, want_cash - cash)
                    spend = min(per_name, cash / (1 + fee_frac))
                    if spend <= 0:
                        continue
                    qty = spend / (px * (1 + fee_frac))
                    held[j] = held.get(j, 0.0) + qty
                    cash -= spend
                    costs += spend * fee_frac / (1 + fee_frac)
                    state[j] = open_state(px, i, j, trail_cfg, bars, adj)
                    trades.append(dict(ticker=tickers[j], entry_date=dates[i], spend=spend,
                                       price=px, qty=qty))
                park_all(i)

        # ---- §3.2's ratchet, every session, on every name held. A name already queued is not
        # re-tested. Two fill models, chosen by `intraday` and pre-registered in WO-A5 §2.1:
        #   * close-based — the stop is judged on the close and filled at the NEXT close, because
        #     a tape of closes cannot price an intraday fill
        #   * intraday — the stop rests at the broker and fills from the bar, at the open when the
        #     session gaps through it and at the stop otherwise
        if trail and held:
            op_a, lo_a = intraday if intraday is not None else (None, None)
            bar_hi, bar_lo = bars if bars is not None else (None, None)
            for j in list(held):
                st = state.get(j)
                px_j = price(i, j)
                if st is None or px_j is None or j in queued:
                    continue
                if op_a is not None and st["stop"] > 0 and i > st["entered"]:
                    # The resting order is tested BEFORE today's close moves the trail up: a stop
                    # set yesterday is the stop the broker holds this morning.
                    #
                    # `i > st["entered"]` is not a nicety. Entry fills at the session's CLOSE, so
                    # that session's own open and low printed BEFORE the position existed —
                    # testing against them stops a name out at a price it traded at while the
                    # account was still in cash. It read as a devastating result and was a
                    # backwards look-ahead: ENPH bought 2020-01-02 was "stopped" on 2020-01-02 at
                    # -10.1%, and MRNA bought 2020-07-01 on 2020-07-02, each giving up a move the
                    # close-based model kept. The stop rests from the next session.
                    fill = stop_fill(st["stop"], op_a[i, j], lo_a[i, j])
                    if fill is not None:
                        sell(i, j, held[j], "trail_stop", price_override=fill)
                        continue
                st["hi"] = max(st["hi"], px_j)
                if (trail_cfg or {}).get("mode") == "atr":
                    a = atr(i, j, bar_hi, bar_lo, adj, trail_cfg["atr_chand_window"])
                    if a:
                        st["atr_chand"] = a       # unmeasurable → hold the last, never jump
                    st["stop"] = trail_stop_atr(px_j, st, trail_cfg)
                else:
                    st["stop"] = trail_stop(px_j, st,
                                            adj[max(0, i - EUPHORIA_WINDOW + 1):i + 1, j],
                                            trail_cfg)
                if op_a is None and px_j < st["stop"]:
                    queued.append(j)
        v = mark(i)
        navs.append(v)
        # WO-A6 Q1: the DEPLOYED fraction and the live position count, not the cell's declared
        # sleeve and N. Writing the spec's constants into these columns made "how much of this
        # return is the park's" unanswerable, and it is the first question any headline has to
        # survive — a book that is mostly in SPMO is mostly reporting SPMO.
        held_v = sum(q * (price(i, j) or 0.0) for j, q in held.items())
        equity.append((dates[i], v, float(park_px[i]) if np.isfinite(park_px[i]) else None,
                       (held_v / v) if v > 0 else 0.0, len(held)))
        # WO-A6 §2: "continuous effective bets is REPORTED, not enforced." The rider gates at
        # formation and never forces an exit, so the book it actually holds can drift below any
        # level the rider allowed on the way in — and the 1.84-effective-bet finding that motivated
        # the rider was a measurement of exactly this, on the held book rather than at entry. A
        # rider verified only by its own block count would be verified against its intent instead
        # of its effect.
        if i >= warmup and len(held) >= 2:
            c = return_corr(i, list(held), adj)
            if c is not None:
                bets_series.append(effective_bets(c))
                cluster_series.append(max(clusters_at(c).values()))

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
                                       empty_rebalances=[d.isoformat() for d in empty_rebals],
                                       rider_blocks=rider_blocks,
                                       held_book=book_diversification(bets_series, cluster_series))


def book_diversification(bets, clusters):
    """Summarise WO-A6 §2's continuous read of the book the strategy actually held.

    Reported, never enforced. `p5` is the number that matters: the rider's whole purpose is to
    stop the book becoming one bet in the sessions that hurt, and a healthy mean over a decade
    tells you nothing about the left tail of a diversification measure.
    """
    if not bets:
        return None
    b = np.asarray(bets, dtype=float)
    b = b[np.isfinite(b)]
    if not len(b):
        return None
    c = np.asarray(clusters, dtype=float)
    return dict(sessions=int(len(b)),
                mean=round(float(b.mean()), 3),
                median=round(float(np.median(b)), 3),
                p5=round(float(np.percentile(b, 5)), 3),
                min=round(float(b.min()), 3),
                frac_below_5=round(float((b < 5.0).mean()), 4),
                frac_below_3=round(float((b < 3.0).mean()), 4),
                max_cluster_mean=round(float(c.mean()), 3) if len(c) else None,
                max_cluster_max=int(c.max()) if len(c) else None)


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
                tape = load_tape(cur, with_range=True)
                cur.execute("""select d, coalesce(adj_close, close) from prices
                                where ticker = %s order by d""", (PARK_TICKER,))
                park_rows = dict(cur.fetchall())
                cur.execute("""select d, coalesce(adj_close, close) from prices
                                where ticker = %s order by d""", (BENCH,))
                bench_rows = dict(cur.fetchall())
                cur.execute("select ticker, sector from universe where sector <> ''")
                sector_by_ticker = dict(cur.fetchall())
            # the benchmark's own bars ARE the market calendar: an index ETF prints on every real
            # US session and on no holiday, which is exactly the predicate this grid needs
            dates, tickers, adj, raw, dv, op, lo, hi = build_grid(tape, set(bench_rows))
            park_px = np.array([float(park_rows.get(d, np.nan)) for d in dates])
            # forward-fill the park so a dark session carries its last mark rather than vanishing
            for i in range(1, len(park_px)):
                if not np.isfinite(park_px[i]):
                    park_px[i] = park_px[i - 1]
            first = int(np.argmax(np.isfinite(park_px)))
            print(f"grid {len(dates)} sessions x {len(tickers)} names · park from {dates[first]}")

            written = []
            sectors = [sector_by_ticker.get(t) for t in tickers]
            bench_px = np.array([float(bench_rows.get(d, np.nan)) for d in dates])
            for i in range(1, len(bench_px)):
                if not np.isfinite(bench_px[i]):
                    bench_px[i] = bench_px[i - 1]
            for name in want:
                global COST_MULT
                spec = dict(CELLS[name])
                gated = spec.pop("gated", False)
                COST_MULT = float(spec.pop("cost_mult", 1.0))
                bars_in = (op, lo) if spec.pop("intraday", False) else None
                opens = op if spec.pop("next_open", False) else None
                try:
                    eq, trades, costs, health = simulate(
                        dates, tickers, adj, raw, dv, park_px, start_nav=start_nav,
                        index_px=bench_px if gated else None, intraday=bars_in,
                        next_open=opens, sectors=sectors, bars=(hi, lo), **spec)
                finally:
                    COST_MULT = 1.0        # never leak a probe's costing into the next cell
                exits = {}
                for t in trades:
                    if "exit_date" in t:
                        exits[t["reason"]] = exits.get(t["reason"], 0) + 1
                # WO-A6 §0/Q3: SPMO is the benchmark on every cell. `finding.py` cuts against
                # whatever sits in this column, and it was VOO — so every §2.5 verdict this arm
                # ever produced was measured against +262.7% when the arm's own park returned
                # +453.9%. The sleeve's whole justification (§2.4.1) is beating the park; scoring
                # it against a different, lower index was answering a question nobody asked.
                eq = [(d, v, park_rows.get(d), dep, npos) for d, v, _, dep, npos in eq
                      if d >= dates[first]]
                nav = np.array([e[1] for e in eq])
                years = max((eq[-1][0] - eq[0][0]).days / 365.25, 1e-9)
                total = float(nav[-1] / nav[0] - 1)
                cagr = float((1 + total) ** (1 / years) - 1)
                dd = float((nav / np.maximum.accumulate(nav) - 1).min())
                entries = [t for t in trades if "entry_date" in t]
                per_year = len(entries) / years
                rows = [(d, float(v), float(b)) for d, v, b, _, _ in eq if b is not None]
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
                              benchmark=PARK_TICKER, start_nav=start_nav, park=PARK_TICKER,
                              regime_source=BENCH,
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
                        [(rid, d, v, dep, npos, None, b) for d, v, b, dep, npos in eq])
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
