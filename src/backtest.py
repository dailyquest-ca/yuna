"""backtest — the momentum sleeve replayed under the law, using the law's own code.

This job is a **driver**, not a second implementation. Every rule it applies is a call into
`signals.py`, the same module `arming.py` calls tonight: one market gate, one trend template, one
base detector, one confirmation state machine, one stop ladder, one sizing formula. Before this
rewrite the backtest re-derived all of them by hand, and the private copy had drifted in nine
places — four MCN setup sub-scores against the law's three, pyramid adds at +2.5%/+4.5% against
+2%/+4%, no add ceiling, no MCN floor, a `volume unconfirmed` exit the plan deleted, and no
blackout at all. 211 of run 5's 296 trades were entries §3.2 forbids outright. A backtest that
measures a sincere restatement of the rules measures nothing.

What it models, per the 2026-08-10 rulings:

  * **USD-native.** US listings only; no FX translation and no conversion fee. NAV starts in USD.
  * **VOO is the benchmark**, on adjusted closes — total return, dividends included. The sleeve's
    own P&L is price-only, so the comparison is biased *against* us, which is the safe direction;
    the magnitude is reported as `stats.dividend_bps` rather than left to the imagination.
  * **Delisted names are retained.** L0 membership is derived from bars at each date, never from
    today's `universe.status`, so a name that died in 2019 is in the census until the day its bars
    stop — and a position holding it exits on the `delisted` rule instead of being marked forever.
  * **Costs.** Half-spread by ADDV bucket, per side; commission zero (Wealthsimple). Gross and net
    both recorded on every trade.
  * **Fixed 280-bar tails.** No rule reads deeper than 266 bars, so the driver hands each call a
    280-bar window and the cost per rank date is constant in the length of the test.
    `tests/test_tail_equivalence.py` pins that the tail and the full series agree.

Biases that remain, stated on every run rather than buried: the vendor serves the current version
of a past statement, so a restatement is seen earlier than the market saw it; industry mappings are
today's; and the L0 census is reconstructed from bars rather than from a stored point-in-time
listing, so a name whose bars we never pulled is still absent.
"""
import os, sys, json, bisect, datetime as dt
import numpy as np
import pandas as pd
from db import connect, config, config_digest, dry, Heartbeat
import signals as sg

START_NAV = float(os.environ.get("START_NAV", "200000"))       # USD (ruled 2026-08-10)
LABEL = os.environ.get("LABEL", "law-v0")
VARIANT = os.environ.get("VARIANT", "law-v0")
LAW_STAMP = os.environ.get("LAW_STAMP", "2026-08-09")
START_DATE = os.environ.get("START_DATE") or None
END_DATE = os.environ.get("END_DATE") or None
HAIR_TRIGGER_PENDING = os.environ.get("HAIR_TRIGGER_PENDING", "false").lower() in ("1", "true", "yes")
HYPOTHESIS = os.environ.get("HYPOTHESIS", "").strip()

# The 2026-08-10 hypothesis set. Every default below is the law; a variant is opt-in, recorded in
# `params.hypothesis`, and changes nothing about law-v0 — which stays the baseline until a run
# earns the change. The presets stage the way the changes depend on each other: risk widening is
# pointless while unconfirmed breakouts are still being bought, and pressing is dangerous until
# expectancy turns.
LAW = dict(mq_vol_divisor=True,        # S1  — momentum quality divided by volatility
           mcn_drop_atr=False,         # S2  — ATR-tightness inside the ranking
           m4_swing=False,             # S3  — loss-to-profit swing scores no growth rate
           confirm_before_entry=False, # E1  — mechanical fill at the pivot, volume judged after
           atr_stop_mult=None,         # R1  — fixed 8% cap, floored at the contraction low
           max_stop=0.08,
           breakeven_r=None,           # R2  — breakeven at full pyramid size
           breakeven=True,             # B1  — a breakeven rung exists at all
           breakeven_on_full_size=True,# B4  — full pyramid size trips it, per §3.2
           breakeven_giveback=0.0,     # B5  — how much of the initial risk the rung leaves under
           euphoria=True,              # B2  — >2sd above the 50-day tightens the trail to 5%
           trail_from=0.15, trail=0.10,# R3  — 10% trail from +15%
           press_on_next_base=False,   # P1  — a stalled pyramid only ever exits
           press_grace=20,             #       sessions the next base has to show up in
           stagnation_days=None,       # H4  — resolve a position that stops making new highs
           template_exit=True,         # T1  — sell when M2 stops passing
           entry_fraction=0.5,         # Z1  — §3.2's first tranche: half now, the rest on the way
           band_hi=None,               # Z2  — the position ceiling, as a fraction of NAV
           budget_lo=None, budget_hi=None,  #  — risk budget, ordinary / full conviction
           sleeve_cap_pct=None,        # Z3  — the sleeve's ceiling, as a fraction of NAV
           trim_at=None,               # M1  — unrealised gains at which to sell a slice
           trim_frac=0.25,             #     — how much of the full position each slice is
           runner_immunity=False,      #     — what is left after a trim rides on the stop alone
           heat_cap=None,              # H1  — total open risk, as a fraction of NAV
           pyramid_spacing=None,       # A1  — average in: tranche spacing, equal thirds
           pyramid_tranches=3,
           strength_at=None,           # A2  — gain at which a position has "proven strength"
           strength_trail=None,        #     — the trail it earns by proving it
           forever=False,              # A3  — past the last rung, only the financials can sell it
           screen=None,                # C1  — 'deep_recovery' replaces M2+M3 with the census screen
           require_m4=True,            #     — M4 has a lift of 0.76; a variant may decline it
           screen_exit=False,          # C2  — sell when the screen stops passing (no longer cheap)
           screen_exit_min_gain=None,  #     — but only from profit, not when the 52w high ages out
           dead_needs_worsening=False, # C3  — a forever hold needs the loss DEEPENING, not merely
                                       #       negative: 41% of winners are unprofitable at entry
           momentum_exit_r3=None,      # C4  — sell when the trailing quarter stops being up
           runner_trail=None,          # M2  — the trail the runner rides on, if not the position's
           runner_no_euphoria=False,   #     — whether the runner is exempt from the 5% tightening
           depth_atr_mult=None,        # D1  — base depth allowance scaled to the name's own ATR
           off_high_atr_mult=None,     # D2  — 52-week-high tolerance scaled the same way
           min_base_age=25,            # D3  — sessions a base runs before its pivot is tradeable
           reentry_window=None,        # X1  — buy back on a new N-session closing high
           reentry_cooloff=5,          #       sessions after an exit before a name is buyable
           max_names=None)             # P2  — from config (4)

PRESETS = {
    # H1 · selection + entry. Does expectancy cross zero once we stop screening for quiet names
    # and stop paying to discover that a breakout had no volume?
    "h1": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True),
    # H2 · H1 plus room to breathe. Does the tail show up once the stop stops firing first?
    # The multiplier is 5, not the conventional 2.5: ATR(14) on our own names runs 2.86% of price
    # at the median, so 2.5x reproduces the law's 7.57% stop almost exactly and would have tested
    # nothing. 5x gives ~14% on a median name and hits the 20% cap on the volatile ones — which is
    # the range that survives a 125-session hold.
    "h2": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25),
    # H3 · H2 plus pressing. Does adding to what already works, across more names, pay?
    "h3": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               press_on_next_base=True, max_names=10),
    # H4 · H2 plus the profit-taking the stall clock was doing by accident. The grid showed E1
    # deletes law-v0's only profitable bucket as a side effect of completing the pyramid; this
    # puts it back on a rule that does not depend on position size, and keeps runners because a
    # name still making new highs never triggers.
    "h4": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20),
    # H5 · H4 plus eligibility scaled to how much the name actually moves. Everything above this
    # line changes what we do with a position; this changes which names can produce one at all.
    # The funnel decomposition found the winners were excluded before ranking ever saw them: a name
    # that produces a +100% year corrects 42% on the way, so §3.2's flat 25% depth clause gives it
    # a valid base on 5.9% of days against 29.3% at 40%. The multiplier is 8, chosen against the
    # measured median ATR of 2.86%: a median name gets 8 x 2.86% = 22.9%, below the 25% floor, so
    # it keeps the law exactly, and only a genuinely volatile name is given more.
    #
    # `min_base_age` is in here to close Zak's question about the 25-session minimum rather than
    # because it is expected to matter — measured, shortening it to 12 moves the winners' base
    # frequency from 5.9% to 6.8% while depth moves it to 29.3%. Depth is worth twenty-three
    # points and base length is worth one. If H5 wins, ablate the base age first.
    "h5": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20,
               depth_atr_mult=8.0, off_high_atr_mult=8.0, min_base_age=12),
    # H6 · H5 plus a way back in. §3.2 has none: once we exit, the name needs a fresh valid base,
    # which for something correcting 42% takes months it does not have — and of 200 stopped-out
    # positions, 96% traded back above the exit inside 60 days and the average best subsequent move
    # was +26.8%. The trigger is deliberately NOT our exit price, which is our history rather than
    # the stock's: it is a new 20-session closing high, the market's own statement that the move
    # resumed, on a name that still passes M2, M4 and the MCN floor.
    "h6": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20,
               depth_atr_mult=8.0, off_high_atr_mult=8.0, min_base_age=12,
               reentry_window=20, reentry_cooloff=5),
    # H5 came back at -1.79% against H4's +0.04% — 150 extra trades, a worse average loss, and
    # **the identical best trade**, so the widening produced no new right tail at all. It bundles
    # three changes, and the pre-run measurement only ever tested them on the numerator (do the
    # winners get a valid base?) and never on the denominator (how much junk does each admit?).
    # These four ablate H5 one clause at a time, each against H4 rather than against H5.
    "d1": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, depth_atr_mult=8.0),
    "d2": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, off_high_atr_mult=8.0),
    "d3": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, min_base_age=12),
    # X1 on the best base rather than on the worst. H6 measures re-entry on top of a widening that
    # lost money; this measures it on H4, which is the run we would actually adopt.
    "x1": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, reentry_window=20, reentry_cooloff=5),
    # T1 · H4 without the trend-template exit. It is H4's worst per-trade bucket — 29 exits at
    # -5.48% for -$8,272 — and §2's forward returns showed twice that the names it sells go on to
    # beat the market. Unlike every other variant this DELETES a §3.2 rule rather than widening
    # one, so `template_exit` is declared in the conformance table: a run that silently stopped
    # enforcing a clause is the exact failure that table exists to catch.
    #
    # Nothing replaces it yet. The question this answers is what the clause costs, not what should
    # stand in its place — a position still has the volatility stop, the 25% trail from +30%, the
    # MCN floor and the 20-session stagnation clock between it and forever.
    "t1": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, template_exit=False),
    # ---- the duration set. Five variants have now tried to put MORE names in the book and every
    # one lost money, while the only profitable bucket in the entire grid is `stagnant` — the one
    # that holds 36 sessions. Average hold across every run is 10-13 sessions. A +100% year takes
    # 250. So these three stop asking what we buy and ask what cuts the hold short.
    #
    # B1 · no breakeven rung. 109 of H4's 252 exits are `stop`, at 9.4 sessions and -0.49% — the
    # signature of a position that earned +1R, ratcheted to breakeven, and got scratched by an
    # ordinary pullback. Zak: "allow a little volatility as the buy gets moving."
    "b1": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, breakeven=False),
    # B2 · no euphoria tightening. §3.2 cuts the trail to 5% when a close sits >2sd above its own
    # 50-day — which is the *definition* of the names we are trying to catch. A stock in the leg
    # that makes a +100% year is euphoric by this test for weeks at a time, and a 5% trail on a
    # name whose ATR is 5% exits on an ordinary two-day pullback.
    "b2": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, euphoria=False),
    # B3 · give the stall clock twice as long. `stagnant` is the grid's only profit centre (+17.20%
    # over 36.3 sessions) and it is a profit-*taking* rule, so the obvious question is whether it
    # is taking profit too early on the names that were still going.
    "b3": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=40),
    # ---- B1 was the most informative run in the grid and it cut both ways. Deleting the
    # breakeven rung DOUBLED the average hold (11.9 -> 23.9 sessions) and more than doubled the
    # win rate (16.7% -> 37.2%), so the diagnosis was right: that rung is what caps the hold. But
    # the average loss went -2.83% -> -7.60%, because every loser then runs the full volatility
    # stop, and that swamped the gain (payoff 4.36:1 -> 1.42:1).
    #
    # The rung is not the problem. A rung sitting *exactly at cost* is: price oscillates around
    # entry, so a stop parked there is a magnet — 38 of H4's 43 `gap` exits are shallow scratches
    # 6.4 sessions in, and 109 `stop` exits average -0.49% at 9.4 sessions. Both are this.
    # B4 and B5 interpolate between H4 and B1 from the two directions that exist.
    #
    # B4 · earn it first. Keep the rung, drop the sizing trigger, and require 3x the initial risk
    # before the stop moves to cost. §3.2 trips it on full pyramid size, which under E1 nearly
    # every position reaches — so the rung currently fires on positions that have earned nothing.
    "b4": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=3.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, breakeven_on_full_size=False),
    # B5 · halve the risk instead of erasing it. Same triggers as H4, but the rung sits half the
    # initial risk under cost rather than on it, so an ordinary pullback through entry costs
    # nothing and the downside is still cut by half.
    "b5": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, breakeven_giveback=0.5),
    # ---- the capital regime, ruled by Zak 2026-08-11. Thirteen runs established that no rule
    # change closes the gap to VOO, because the sleeve is ~90% in cash: §3.2's risk budget is
    # 0.7-0.9% of NAV and the position band tops out at 12%, so against a 20% volatility stop a
    # position is 3.5-6.4% of NAV and the book averages 1.3-1.8 names. VOO is 100% invested.
    #
    # "to be fair we should say 100k USD is the amount and we can use all of it... with up to 25%
    # on high conviction... and that's vs. 100% in VOO." So the sleeve gets the whole account: the
    # budgets are raised until a full-conviction name reaches the 25% ceiling against its own
    # stop, the sleeve cap goes to 100%, and E1's confirmation makes §3.2's half-now first tranche
    # a hedge against a risk that no longer exists.
    #
    # `breakeven_on_full_size=False` is forced by `entry_fraction=1.0`, not chosen. A position that
    # opens full is marked step 3, which trips §3.2's "breakeven at full pyramid size" on its FIRST
    # session — so B5's rung, whose whole value is that it sits below cost and only after the
    # position has earned +1R, would instead become an initial stop of half the intended width
    # applied before the position has earned anything. Run 33 is what that costs: the `stop` bucket
    # alone was -$81,536 of a -$30,036 total, on 95 exits at -3.48% against an intended ~10%.
    "z1": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, breakeven_giveback=0.5,
               budget_lo=0.025, budget_hi=0.05, band_hi=0.25, sleeve_cap_pct=1.0,
               entry_fraction=1.0, max_names=5, breakeven_on_full_size=False),
    # M1 · Zak's own ladder, on top of the capital regime: sell a quarter at +50%, a quarter at
    # +100%, and let the remaining half ride "until the stock completely dies". The rungs are
    # resting limit sells at avg cost x (1 + level). The ride is implemented as immunity from the
    # housekeeping exits — template, MCN floor, stall clock, stagnation clock — since those are
    # how a position that is merely *resting* gets closed, and a trimmed position is not resting.
    # It keeps its stop, the gate, and delisting. That reading of "completely dies" is an
    # assumption, and it is the first thing to revisit if the runner bucket bleeds.
    "m1": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, breakeven_giveback=0.5,
               budget_lo=0.025, budget_hi=0.05, band_hi=0.25, sleeve_cap_pct=1.0,
               entry_fraction=1.0, max_names=5, breakeven_on_full_size=False,
               trim_at=(0.50, 1.00), trim_frac=0.25, runner_immunity=True),
    # M2 · let the runner actually run. Run 33's ladder worked exactly as Zak described it — MU
    # trimmed at +49.9% and +99.9%, AVAV at +49.8% and +99.7% — and then **all three runners
    # stopped out two to four sessions after their second trim**: MU at +91.7%, AVAV at +102.7%,
    # CAMT at +9.9%. Not the housekeeping exits, which runner immunity had already switched off.
    # The euphoria rung. A name up 100% is by construction far above its own 50-day, so the trail
    # cuts to 5%, and 5% is one ordinary session for it.
    #
    # B2 showed that tightening pays on an ordinary position and it stays on for those. A runner is
    # different in kind: two rungs of profit are already banked, so the question is no longer how
    # much of this gain survives but how far the name can go. It rides a 35% trail and is exempt
    # from the tightening.
    "m2": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, breakeven_giveback=0.5,
               budget_lo=0.025, budget_hi=0.05, band_hi=0.25, sleeve_cap_pct=1.0,
               entry_fraction=1.0, max_names=5, breakeven_on_full_size=False,
               trim_at=(0.50, 1.00), trim_frac=0.25, runner_immunity=True,
               runner_trail=0.35, runner_no_euphoria=True),
    # M3 · M2 with a cap on total open risk. Run 34 is the argument: average trade **+1.27%**,
    # win rate 39.6%, average hold 24.5 sessions — a real edge by every per-trade measure — and a
    # **-53.5% drawdown**. That gap is not a bad strategy, it is over-betting a good one. The
    # sleeve cap limits how much is invested and nothing limited how much could be lost: a 25%
    # position behind a 20% stop risks 5% of NAV, and the book holds four or five of them.
    #
    # 6% is one full-conviction name's worth of risk plus change — so the book can carry one 25%
    # position at full stop width, or several whose stops have already ratcheted up. It makes the
    # heat, not the cash, the binding constraint, which is the right way round.
    "m3": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, breakeven_giveback=0.5,
               budget_lo=0.025, budget_hi=0.05, band_hi=0.25, sleeve_cap_pct=1.0,
               entry_fraction=1.0, max_names=5, breakeven_on_full_size=False,
               trim_at=(0.50, 1.00), trim_frac=0.25, runner_immunity=True,
               runner_trail=0.35, runner_no_euphoria=True, heat_cap=0.06),
    # ---- C · the census screen. §9 of the findings: M3's depth clause has a lift of 0.04 against
    # the population that actually produces 70% moves, M2's off-high clause 0.64, the moving-average
    # stack 0.97, and M4 0.76 — every gate anti-predictive, in all ten years, on hit rate and on
    # forward return. The set they admit returned +1.12% per six months, which is what nineteen
    # runs produced from it. C1 replaces M2 and M3 with the four census conditions, drops M4, and
    # enters on a new 20-session closing high because a name 50% off its low has no §3.2 base.
    #
    # Everything else is A1's machinery, which the drawdown table says should finally fit: on this
    # population a 20% stop removes 47% of the losers and 20% of the winners, where on §3.2's it
    # fired on the winners first.
    "c1": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.30, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, breakeven_giveback=0.5,
               budget_lo=0.025, budget_hi=0.05, band_hi=0.25, sleeve_cap_pct=1.0,
               entry_fraction=1.0 / 3.0, pyramid_spacing=0.05, pyramid_tranches=3,
               max_names=5, breakeven_on_full_size=False, heat_cap=0.06,
               trim_at=(0.35, 0.75), trim_frac=0.25, runner_immunity=True,
               runner_trail=0.35, runner_no_euphoria=True,
               strength_at=0.25, strength_trail=0.40,
               screen="deep_recovery", require_m4=False),
    # C2 · the exit test. C1 sold on the screen (accidentally) and made +$4,624; C1b never did and
    # lost $8,459. The screen failing is real information — but it fires for two different reasons,
    # and only one of them is a reason to sell. Take the money when the position has actually made
    # some; ignore it when the 52-week high merely rolled out of the window.
    "c2": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.30, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, breakeven_giveback=0.5,
               budget_lo=0.025, budget_hi=0.05, band_hi=0.25, sleeve_cap_pct=1.0,
               entry_fraction=1.0 / 3.0, pyramid_spacing=0.05, pyramid_tranches=3,
               max_names=5, breakeven_on_full_size=False, heat_cap=0.06,
               trim_at=(0.35, 0.75), trim_frac=0.25, runner_immunity=True,
               runner_trail=0.35, runner_no_euphoria=True,
               strength_at=0.25, strength_trail=0.40,
               screen="deep_recovery", require_m4=False,
               screen_exit=True, screen_exit_min_gain=0.10, dead_needs_worsening=True),
    # C3 · the control. Same, with no gain requirement — this is what run 39 did by accident, now
    # done on purpose, so the min-gain gate can be priced against it rather than against a bug.
    "c3": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.30, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, breakeven_giveback=0.5,
               budget_lo=0.025, budget_hi=0.05, band_hi=0.25, sleeve_cap_pct=1.0,
               entry_fraction=1.0 / 3.0, pyramid_spacing=0.05, pyramid_tranches=3,
               max_names=5, breakeven_on_full_size=False, heat_cap=0.06,
               trim_at=(0.35, 0.75), trim_frac=0.25, runner_immunity=True,
               runner_trail=0.35, runner_no_euphoria=True,
               strength_at=0.25, strength_trail=0.40,
               screen="deep_recovery", require_m4=False,
               screen_exit=True, screen_exit_min_gain=None, dead_needs_worsening=True),
    # C4 · the screen exit, reduced to the only clause that carries information. No gain gate, no
    # dependence on a 252-day window rolling over: sell when the trailing quarter stops being up.
    "c4": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.30, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, breakeven_giveback=0.5,
               budget_lo=0.025, budget_hi=0.05, band_hi=0.25, sleeve_cap_pct=1.0,
               entry_fraction=1.0 / 3.0, pyramid_spacing=0.05, pyramid_tranches=3,
               max_names=5, breakeven_on_full_size=False, heat_cap=0.06,
               trim_at=(0.35, 0.75), trim_frac=0.25, runner_immunity=True,
               runner_trail=0.35, runner_no_euphoria=True,
               strength_at=0.25, strength_trail=0.40,
               screen="deep_recovery", require_m4=False,
               dead_needs_worsening=True, momentum_exit_r3=0.10),
    # ---- A · Zak's compounder reading of the momentum sleeve (2026-08-11): "what if our biggest
    # winners that made it to +100%... we never sold. We just kept them long-term?"
    #
    # Four changes, and the last one is a change of kind rather than of degree.
    #   A1  average in over three equal tranches 5% apart, against §3.2's 50/25/25 at +0/+2/+4%
    #   A2  proven strength (+25%) earns a 40% trail and exemption from the euphoria cut
    #   A3  trim rungs move in, to +35% and +75%, so more names reach them
    #   A4  past the last rung the position stops being a trade: every §3.2 exit is a PRICE exit,
    #       and the premise is that price no longer speaks, so the stop, the trail, the template,
    #       the score, the clocks and the market gate all go. Only `profitability_dead` — two
    #       consecutive reported quarters at or below zero — and delisting can sell it.
    #
    # A4 is the one to watch. It removes the crash protocol from a live position, so a forever hold
    # carries a 2008-shaped drawdown by construction. That is the trade Zak is proposing and the
    # measurement is whether the compounding beats it.
    "a1": dict(mq_vol_divisor=False, mcn_drop_atr=True, m4_swing=True, confirm_before_entry=True,
               atr_stop_mult=5.0, max_stop=0.20, breakeven_r=1.0, trail_from=0.30, trail=0.25,
               stagnation_days=20, breakeven_giveback=0.5,
               budget_lo=0.025, budget_hi=0.05, band_hi=0.25, sleeve_cap_pct=1.0,
               # a third at the breakout and a third at each of +5% and +10% — averaging in is the
               # point, so this cannot open full the way z1/m1..m3 do
               entry_fraction=1.0 / 3.0, pyramid_spacing=0.05, pyramid_tranches=3,
               max_names=5, breakeven_on_full_size=False, heat_cap=0.06,
               trim_at=(0.35, 0.75), trim_frac=0.25, runner_immunity=True,
               runner_trail=0.35, runner_no_euphoria=True,
               strength_at=0.25, strength_trail=0.40, forever=True),
}


def hypothesis():
    """The law, with a preset laid over it, with individual env overrides laid over that."""
    h = dict(LAW)
    h.update(PRESETS.get(HYPOTHESIS, {}))
    for k in list(h):
        raw = os.environ.get(k.upper())
        if raw is None or raw == "":
            continue
        low = raw.strip().lower()
        h[k] = (True if low in ("1", "true", "yes") else
                False if low in ("0", "false", "no") else
                None if low == "none" else float(raw) if "." in raw else int(raw))
    return h

WARMUP = 280            # >= 266, the deepest window any rule reads (see tests/test_tail_equivalence)
TAIL = 280
T10 = 10                # §3.2: every MCN ranking window ends 10 trading days ago
BENCH = os.environ.get("BENCHMARK", "VOO.US")
DELISTED_AFTER = 5      # sessions without a bar before a holding is treated as gone
CALENDAR_HORIZON = 100  # a scheduled report we can believe in — one quarter (check.py allows 110)


# =============================================================================== data
def load(cur):
    """Every US bar we hold, living and dead. The census is rebuilt from bars, not from `status`."""
    cur.execute("""select p.ticker, p.d, p.open, p.high, p.low, p.close, p.adj_close, p.volume
                     from prices p join universe u on u.ticker = p.ticker
                    where u.kind = 'stock' and u.ticker like '%%.US'
                    order by p.d""")
    df = pd.DataFrame(cur.fetchall(),
                      columns=["ticker", "d", "open", "high", "low", "close", "adj", "vol"])
    for c in ("open", "high", "low", "close", "adj", "vol"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["adj"] = df["adj"].fillna(df["close"])

    # Scatter into the date x ticker grid directly rather than pivoting six times. Retaining the
    # delisted census roughly doubles the ticker count, and six pivots of a ten-million-row frame
    # is where a runner with 7 GB stops being able to load the tape at all.
    tcode, cols = pd.factorize(df["ticker"], sort=True)
    dcode, dates = pd.factorize(df["d"], sort=True)
    shape = (len(dates), len(cols))
    arrays = {}
    for c in ("open", "high", "low", "close", "adj", "vol"):
        a = np.full(shape, np.nan)
        a[dcode, tcode] = df[c].to_numpy(dtype=float)
        arrays[c] = a
    del df

    cur.execute("select ticker, industry from universe where kind='stock'")
    industry = {t: i for t, i in cur.fetchall()}

    cur.execute("""select d, close, coalesce(adj_close, close) from prices
                    where ticker = %s order by d""", (BENCH,))
    rows = cur.fetchall()
    bench = pd.Series({d: float(a) for d, _, a in rows}).sort_index() if rows else pd.Series(dtype=float)

    # M1 is the S&P 500 (§3.2). GSPC if we hold it deep enough, else the tracker standing in for it.
    cur.execute("select d, close from prices where ticker='GSPC.INDX' order by d")
    spx = pd.Series({d: float(c) for d, c in cur.fetchall()}).sort_index()
    gate_source = "GSPC.INDX"
    if len(spx) < len(bench):
        spx, gate_source = pd.Series({d: float(c) for d, c, _ in rows}).sort_index(), BENCH

    cur.execute("select ticker, report_date from earnings order by ticker, report_date")
    reports = {}
    for tk, rd in cur.fetchall():
        reports.setdefault(tk, []).append(rd)

    # Point-in-time EPS for M4: each quarter carries its own reportDate, so what was knowable on a
    # past date is a prefix cut, not a guess. Period order and report order agree, so one bisect.
    cur.execute("""select f.ticker,
                          array_agg((h.value->>'reportDate')::date order by h.key desc)  as rds,
                          array_agg((h.value->>'epsActual')::double precision
                                    order by h.key desc)                                 as eps
                     from v_fundamentals_latest f,
                          lateral jsonb_each(coalesce(f.raw_doc->'Earnings'->'History','{}'::jsonb)) h
                    where h.value->>'epsActual' is not null
                      and h.value->>'reportDate' is not null
                    group by f.ticker""")
    eps = {}
    for tk, rds, vals in cur.fetchall():
        pairs = [(r, v) for r, v in zip(rds, vals) if r is not None and v is not None]
        if pairs:
            eps[tk] = (np.array([r.toordinal() for r, _ in pairs]), [v for _, v in pairs])

    return dict(dates=list(dates), cols=list(cols), arrays=arrays, industry=industry,
                bench=bench, spx=spx, gate_source=gate_source, reports=reports, eps=eps)


def eps_as_of(eps_entry, day):
    """The quarters already reported by `day`, newest first — a prefix cut on report date."""
    rds, vals = eps_entry
    # rds descends, so the first index whose report date is on or before `day` starts the slice.
    i = int(np.searchsorted(-rds, -day.toordinal(), side="left"))
    return vals[i:]


# =============================================================================== the weekly rank
def own_bars(valid, j, t, back=0, n=TAIL):
    """The last `n` bars **this name actually printed**, ending `back` sessions before `t`.

    Not a slice of the date grid. The grid is the union of every ticker's dates, so a name is NaN
    on any session it did not trade, and a fixed grid slice therefore mixes "no bar" into a window
    the rules read as prices. Taking a name's own bars is what `rank.py` does — it loads one
    series per ticker — and it is the difference between 2,310 rank dates and zero: the first run
    of this engine required a hole-free grid window and no name in ten years ever had one.

    The 2026-07-31 findings recorded the same shape from the other direction: one TSX listing put
    TSX-only dates into the union index and every US name silently lost its volume baseline.
    """
    v = valid[j]
    k = int(np.searchsorted(v, t, side="right")) - back
    return v[k - n:k] if k >= n else None


def _reentry_ready(tk, j, t, valid, C, exited, hyp):
    """X1 — may we buy this name back today, having sold it before?

    Three conditions, all of them the stock's rather than ours: we held it and let it go, the
    cool-off has passed, and last night it closed above every close of the prior `reentry_window`
    sessions. A name we never held cannot re-enter, and one that delisted cannot come back.
    """
    if not hyp["reentry_window"]:
        return False
    last = exited.get(tk)
    if last is None or t - last < int(hyp["reentry_cooloff"]):
        return False
    rows = own_bars(valid, j, t, back=1)
    if rows is None:
        return False
    return sg.resumed(C[rows, j], window=int(hyp["reentry_window"]))


def _tolerance(atr_frac, mult, floor=0.25):
    """The law's flat allowance, or that allowance widened in proportion to the name's own ATR."""
    return floor if not mult else sg.volatility_tolerance(atr_frac, floor=floor, mult=float(mult))


def rank(frame, t, cols, arrays, valid, hyp):
    """L1-M as `rank.py` builds it: M2 + M4, ranked by MCN, top 150 — same calls, same order.

    Gates and stops read current price; MCN reads windows ending 10 sessions ago (§3.2, "rank is
    calm; protection is real-time"). Both slices are 280 of the name's own bars, so both are
    constant-cost.
    """
    O, H, L, C, A, V = (arrays[k] for k in ("open", "high", "low", "close", "adj", "vol"))

    # ---- L0 liquidity, evaluated on the bars of the day. Not a §3.2 rule: it is the census, and
    # it is what makes a delisted name leave the universe on the day its bars stop.
    close_t = C[t]
    live = ~np.isnan(close_t)
    nbars = (~np.isnan(C[max(0, t - 251):t + 1])).sum(axis=0)
    addv = np.nanmedian((C[max(0, t - 49):t + 1] * V[max(0, t - 49):t + 1]), axis=0)
    eff = live & (nbars >= 210) & (close_t >= 5) & (addv >= 10_000_000)
    idx = np.where(eff)[0]
    if len(idx) < 30:
        return None

    quality, atr_pct, dryup, near_high = {}, {}, {}, {}
    m2, bases, group_returns = {}, {}, {}
    for j in idx:
        tk = cols[j]
        f_rows = own_bars(valid, j, t)
        m_rows = own_bars(valid, j, t, back=T10)
        if f_rows is None or m_rows is None:
            continue                                     # not yet 280 of its own bars
        cl_f, hi_f, lo_f = C[f_rows, j], H[f_rows, j], L[f_rows, j]
        ac, hh, ll, cc, vv = (X[m_rows, j] for X in (A, H, L, C, V))

        # D1/D2: eligibility scaled to the name's own daily range. Both default to the law's flat
        # 25% — `volatility_tolerance` floors at it, so a quiet name is judged exactly as §3.2
        # judges it and only a name that actually moves is given room.
        apct = sg.atr_fraction(hi_f, lo_f, cl_f)
        if hyp["screen"] == "deep_recovery":
            # C1: M2 and M3 both go. The census screen is the whole eligibility test, and it has
            # no pivot — the entry trigger is a new 20-session closing high (`signals.resumed`),
            # the same door X1 opened, because a name 50% off its low has no §3.2 base and will
            # not have one for months.
            m2[tk] = sg.deep_recovery(hi_f, lo_f, cl_f)["passes"]
            bases[tk] = dict(valid=False, pivot=None, contraction_low=None, depth=None)
        else:
            m2[tk] = sg.trend_template(cl_f, off_high=_tolerance(apct, hyp["off_high_atr_mult"]))
            bases[tk] = sg.base_scan(hi_f, lo_f, cl_f, min_age=int(hyp["min_base_age"]),
                                     max_depth=_tolerance(apct, hyp["depth_atr_mult"]))
        quality[tk] = sg.momentum_quality(ac, vol_divisor=hyp["mq_vol_divisor"])
        subs = sg.setup_proximity(hh, ll, cc, vv)
        atr_pct[tk], dryup[tk], near_high[tk] = subs["atr_pct"], subs["dryup"], subs["near_high"]
        ind = frame["industry"].get(tk)
        if ind and len(ac) >= 126 and ac[-126] > 0:
            group_returns.setdefault(ind, []).append(float(ac[-1]) / float(ac[-126]) - 1)

    ranked = sorted(quality)
    if not ranked:
        return None
    groups = sorted(group_returns)
    group_mean = {g: float(np.nanmean(group_returns[g])) for g in groups}
    group_pct = dict(zip(groups, sg.pct_rank([group_mean[g] for g in groups])))
    q_p = dict(zip(ranked, sg.pct_rank([quality[tk] for tk in ranked])))
    d_p = dict(zip(ranked, sg.pct_rank([dryup[tk] for tk in ranked])))
    x_p = dict(zip(ranked, sg.pct_rank([near_high[tk] for tk in ranked])))

    day = frame["dates"][t]
    out, m4_known = {}, 0
    for tk in ranked:
        # S2: the ATR-tightness sub-score rewards quiet. Tightness belongs at the pivot, where
        # M3 already measures the base contraction — as a ranking term it tilts the whole book
        # toward names that cannot produce a tail.
        parts = [d_p[tk], x_p[tk]] if hyp["mcn_drop_atr"] else [atr_pct[tk], d_p[tk], x_p[tk]]
        setup = float(np.nanmean(parts))
        ind = frame["industry"].get(tk)
        grp = group_pct.get(ind, 50.0) if ind else 50.0
        score = sg.mcn(q_p[tk], setup, grp)
        entry = frame["eps"].get(tk)
        if entry is not None:
            m4 = sg.m4_acceleration(eps_as_of(entry, day), swing=hyp["m4_swing"])["passes"]
            m4_known += 1
        else:
            m4 = None                       # unknown is not a pass; §3.3 never guesses a component
        out[tk] = dict(mcn=score, m2=bool(m2[tk]), m4=m4, base=bases[tk])

    # L1-M = M2 and M4 pass, ranked by MCN, top 150 (§3.2). An unknown M4 is not a pass.
    eligible = [tk for tk in out if out[tk]["m2"]
                and (out[tk]["m4"] is True or not hyp["require_m4"])
                and out[tk]["mcn"] == out[tk]["mcn"]]
    l1m = sorted(eligible, key=lambda tk: -out[tk]["mcn"])[:150]
    return dict(scored=out, l1m=l1m, evaluated=len(ranked), m4_known=m4_known)


# =============================================================================== the simulation
def simulate(frame, cfg):
    """The day loop. Pure: no database, no clock — `tests/test_backtest_engine.py` runs it on
    hand-built bars, which is the only way to assert what the engine refuses to do."""
    hyp = cfg["hyp"]
    dates, cols = frame["dates"], frame["cols"]
    arrays = frame["arrays"]
    O, H, L, C, A, V = (arrays[k] for k in ("open", "high", "low", "close", "adj", "vol"))
    col = {tk: j for j, tk in enumerate(cols)}
    n = len(dates)

    # the 50 sessions *before* each day — the breakout day is the test, never its own baseline
    v50 = pd.DataFrame(V).shift(1).rolling(50, min_periods=25).mean().values
    # every name's own printed sessions, once. Rules read these rows, never grid slices.
    valid = [np.flatnonzero(~np.isnan(C[:, j])) for j in range(len(cols))]

    gate_weeks, gate_states = _gate_series(frame["spx"])

    nav = cash = cfg["start_nav"]
    book, trades, equity, pending = {}, [], [], {}
    exited = {}                 # ticker -> the session we last let it go (X1's cool-off clock)
    fired, queue, conf = {}, None, dict(m4_evaluated=0, m4_known=0, blackout_decisions=0,
                                        blackout_known=0, rank_dates=0, entries=0,
                                        entries_refused_below_70=0, gap_no_fill=0,
                                        pressed=0, press_windows=0, press_expired=0,
                                        reentries=0, trims=0, heat_refused=0, recoveries=0)

    def spread(j, t):
        """§ WO-12: half-spread by ADDV bucket, per side. Wide names cost more to touch."""
        advv = np.nanmedian(C[max(0, t - 49):t + 1, j] * V[max(0, t - 49):t + 1, j])
        bps = cfg["spread_bps"][0] if advv >= cfg["addv_break"] else cfg["spread_bps"][1]
        return bps / 10_000.0

    def _blacked_out(frame, conf, tk, day):
        """§3.3: the earnings wall cancels a resting order. Counted per door tried, because the
        coverage ratio only means anything if the denominator is the decisions we actually made."""
        nxt = _next_report(frame["reports"].get(tk), day)
        conf["blackout_decisions"] += 1
        conf["blackout_known"] += 1 if _knowable(nxt, day) else 0
        return nxt is not None and sg.in_blackout(day, nxt)

    def base_trigger(j, t, base, rows):
        """Door one — the breakout §3.2 names. Returns the fill, or None if nothing triggered."""
        pivot = base["pivot"]
        hi, op = H[t, j], O[t, j]
        if hyp["confirm_before_entry"]:
            # E1. Nothing rests at the broker. The trigger is a session that *closes* above the
            # pivot carrying >= 1.4x its own 50-day, and the fill is the next open — so a breakout
            # that did not carry is never bought, rather than bought and then discovered. Costs a
            # session of drift; removes the entire unconfirmed bucket, which lost money under both
            # readings of the hair-trigger.
            vj = valid[j]
            kk = int(np.searchsorted(vj, t, side="left"))
            if kk == 0:
                return None
            trig = vj[kk - 1]
            if not (C[trig, j] > pivot) or not sg.breakout_confirmed([V[trig, j]], [v50[trig, j]]):
                return None
            fill = op if not np.isnan(op) else C[trig, j]
            if fill > pivot * cfg["confirm_limit"]:
                conf["gap_no_fill"] += 1
                return None                               # gapped past the ceiling — let it go
            return dict(kind="base", fill=fill, pivot=pivot, confirmed=True)
        if np.isnan(hi) or hi < pivot:
            return None
        order = sg.entry_order(pivot, base["contraction_low"],
                               limit_over=cfg["limit_over"], max_stop=cfg["max_stop"])
        fill = pivot if (np.isnan(op) or op <= pivot) else op
        if fill > order["limit"]:
            conf["gap_no_fill"] += 1
            return None                                   # gapped through the limit — no fill
        return dict(kind="base", fill=fill, pivot=pivot, confirmed=None)

    def realise(tk, day, price, reason, t, qty, gross_price=None):
        """Book `qty` shares out of a position and write the trade row for that slice.

        The engine held whole positions only until the trim ladder needed partials. A slice is a
        trade in its own right — its own row, its own reason, its own P&L — so `trim50` and the
        eventual exit of the runner are separately measurable, which is the whole point of asking
        whether trimming pays. Average cost is unchanged by a trim: the lots shrink pro rata, so
        what is left has the same basis, the same stop and the same milestones ahead of it.
        """
        p = book[tk]
        j = col[tk]
        share = qty / p["qty"]
        # Decisions ride raw prices, so the sleeve's P&L is price-only. The dividend the adjusted
        # series implies is measured and reported (`stats.dividend_bps`) rather than either banked
        # silently or forgotten — VOO's benchmark is total return, so this is the size of the
        # handicap we are giving it.
        adj_t, px_t = A[t, j], C[t, j]
        if np.isfinite(adj_t) and np.isfinite(px_t):
            total = sum(d * (adj_t / a) for d, _, a in p["lots"])
            dividend = share * (total - sum(d * (px_t / e) for d, e, _ in p["lots"]))
        else:
            dividend = 0.0
        invested, gross_invested = p["invested"] * share, p["gross_invested"] * share
        proceeds = qty * price
        gross = qty * (gross_price if gross_price is not None else price)
        trades.append(dict(
            ticker=tk, entry_date=p["entry_date"], entry_price=invested / qty,
            qty=qty, exit_date=day, exit_price=price, mcn=p["mcn"], pivot=p["pivot"],
            initial_stop=p["init_stop"], size_pct=p["size"], pyramid_steps=p["step"],
            pnl_usd=proceeds - invested, pnl_pct=proceeds / invested - 1,
            pnl_gross_usd=gross - gross_invested,
            cost_usd=(gross - proceeds) + (invested - gross_invested),
            dividend_usd=dividend,
            bars_held=t - p["entry_idx"], max_favorable=p["mfe"], max_adverse=p["mae"],
            exit_reason=reason, confirmed=p["confirmed"], entry_kind=p.get("kind", "base")))
        p["qty"] -= qty
        p["invested"] -= invested
        p["gross_invested"] -= gross_invested
        p["lots"] = [(d * (1 - share), e, a) for d, e, a in p["lots"]]
        return proceeds

    def trim(tk, day, price, reason, t, qty, gross_price=None):
        got = realise(tk, day, price, reason, t, qty, gross_price=gross_price)
        conf["trims"] += 1
        return got

    def close_position(tk, day, price, reason, t, gross_price=None):
        proceeds = realise(tk, day, price, reason, t, book[tk]["qty"], gross_price=gross_price)
        book.pop(tk)
        # A delisted name has no way back; everything else is only a moment we were wrong about.
        if reason != "delisted":
            exited[tk] = t
        return proceeds

    for t in range(WARMUP, n):
        day = dates[t]
        on = _gate_on(gate_weeks, gate_states, day)

        # ---- exits flagged at yesterday's close fill at this open (§5.1: the desk arms, the
        # morning executes). Only the stop is intraday, because the broker holds it.
        for tk, reason in list(pending.items()):
            pending.pop(tk)
            if tk not in book:
                continue
            j = col[tk]
            px = O[t, j]
            if np.isnan(px):
                px = C[t, j]
            if np.isnan(px):
                px = book[tk]["last_mark"]
            cash += close_position(tk, day, px * (1 - spread(j, t)), reason, t, gross_price=px)

        # ---- weekly re-rank (§3.0 cadence: M2 and M4 weekly, MCN weekly)
        if pd.Timestamp(day).weekday() == 4 or queue is None:
            got = rank(frame, t, cols, arrays, valid, hyp)
            if got is not None:
                queue = got
                conf["rank_dates"] += 1
                conf["m4_evaluated"] += got["evaluated"]
                conf["m4_known"] += got["m4_known"]

        scored = (queue or {}).get("scored", {})

        # ---- what we hold: stops first, then the conclusions the law draws
        for tk in list(book):
            p, j = book[tk], col[tk]
            lo, hi, cl, op = L[t, j], H[t, j], C[t, j], O[t, j]

            if np.isnan(cl):
                p["stale"] += 1
                if p["stale"] >= DELISTED_AFTER:
                    cash += close_position(tk, day, p["last_mark"], "delisted", t,
                                           gross_price=p["last_mark"])
                continue
            p["stale"] = 0

            # the stop is a resting broker order: it fires intraday, and a gap fills at the open
            if p["stop"] is not None and lo <= p["stop"]:
                gapped = not np.isnan(op) and op < p["stop"]
                fill = op if gapped else p["stop"]
                cash += close_position(tk, day, fill * (1 - spread(j, t)),
                                       "gap" if gapped else "stop", t, gross_price=fill)
                continue

            if cl > p["hi_close"]:
                p["hi_close"], p["hi_at"] = cl, t
            p["mfe"] = max(p["mfe"], hi / p["avg_cost"] - 1)
            p["mae"] = min(p["mae"], lo / p["avg_cost"] - 1)

            # ---- M1: the trim ladder. Zak's own method — sell a quarter at +50%, a quarter at
            # +100%, let the rest ride until the name is genuinely finished. Each rung is a
            # resting GTC limit sell at avg cost x (1 + level), so it fills intraday when the
            # high reaches it and takes the better price on a gap through. That is how the order
            # would actually sit at the broker, and unlike an at-the-close trim it cannot use a
            # price the day had not yet printed when the decision was made.
            for rung, level in enumerate(hyp["trim_at"] or ()):
                if rung in p["trimmed"] or p["qty"] <= 0:
                    continue
                target = p["avg_cost"] * (1 + float(level))
                if np.isnan(hi) or hi < target:
                    continue
                fill = max(target, op if not np.isnan(op) else target)
                sold = min(p["qty_peak"] * float(hyp["trim_frac"]), p["qty"])
                p["trimmed"].add(rung)
                if sold <= 0:
                    continue
                cash += trim(tk, day, fill * (1 - spread(j, t)),
                             f"trim{int(round(level * 100))}", t, sold, gross_price=fill)
            if p["qty"] <= 0:
                book.pop(tk)                      # the ladder sold the last of it
                exited[tk] = t
                continue
            # What is left after a trim is the runner. §3.2's housekeeping exits — the template,
            # the MCN floor, the stall clock, the stagnation clock — are how a position that is
            # merely resting gets closed, and Zak's rule is that the runner rides "until the stock
            # completely dies". So on a trimmed position only the stop, the gate and delisting
            # speak. This is an interpretation of "completely dies", and it is the assumption to
            # revisit first if the runner bucket bleeds.
            riding = hyp["runner_immunity"] and p["trimmed"]
            # A2: proven strength earns room. Zak's "on proven strength we widen the stops" — a
            # position that has already made `strength_at` has told us something the entry could
            # not, and the trail that was right for an unproven breakout is not right for it.
            gain = cl / p["avg_cost"] - 1
            proven = hyp["strength_at"] is not None and gain >= float(hyp["strength_at"])
            # A3: past the final rung the position stops being a trade. Zak's rule — "if it makes
            # it that high... never sell... just ride it through the highs and lows unless the
            # financials on the profitability of the company dies". Every §3.2 exit is a PRICE
            # exit, and the whole premise here is that price no longer speaks, so all of them go:
            # the stop, the trail, the template, the score, the clocks and the market gate. What
            # is left is the business failing, and the name ceasing to trade.
            forever = bool(hyp["forever"] and hyp["trim_at"]
                           and len(p["trimmed"]) >= len(hyp["trim_at"]))
            if forever:
                p["stop"] = None
                eps = frame["eps"].get(tk)
                if eps is not None and sg.profitability_dead(
                        eps_as_of(eps, day), worsening=bool(hyp["dead_needs_worsening"])):
                    pending[tk] = "profitability"
                    continue
                p["last_mark"] = cl
                continue

            # ---- §3.2 breakout confirmation, judged at EOD on the sessions since entry
            k = t - p["entry_idx"] + 1
            window = range(p["entry_idx"], min(p["entry_idx"] + sg.CONFIRM_SESSIONS, t + 1))
            if hyp["confirm_before_entry"]:
                # E1: the breakout was confirmed before a share was bought, so there is nothing to
                # classify, nothing to freeze, no late window and no hair-trigger. The entire
                # apparatus §3.2 needed to manage an unconfirmed fill simply does not arise.
                state = dict(confirmed=True, pyramid_armed=True, fraction=1.0,
                             exit_next_open=False, closed_below_pivot=False)
            else:
                state = sg.confirmation_state(
                    [V[i, j] for i in window], [v50[i, j] for i in window],
                    closes=[C[i, j] for i in window], pivot=p["pivot"],
                    hair_trigger_while_pending=cfg["hair_trigger_while_pending"])
            p["confirmed"] = state["confirmed"]

            if not on:
                pending[tk] = "gate_off"                 # §3.3 crash protocol, acted next open
                continue
            if state["exit_next_open"]:
                pending[tk] = "unconfirmed"              # the hair-trigger — the only volume exit
                continue

            row = scored.get(tk)
            # An ENTRY screen is not a HOLD condition, and conflating the two cost run 39 its
            # winners. `deep_recovery` requires the name to be at least 25% under its 52-week
            # high — so the moment a position works, the screen stops passing and the template
            # exit sells it. 142 of that run's 253 exits were `template` at 9.1 sessions: the
            # rule was selling every name for the crime of no longer being cheap. With a screen
            # in use, holding is governed by the stop, the trail, the rungs and the clocks.
            if hyp["template_exit"] and not hyp["screen"] and not riding \
                    and row is not None and row["m2"] is False:
                pending[tk] = "template"
                continue
            # C2. Run 39 did this by accident and it was the best bucket in the run: +$18,831 over
            # 142 exits. Run 40 removed it and lost $13,083 — the hold doubled, the best trade went
            # to +271%, and the account got worse. So the screen failing IS information; it is just
            # not a stop. `deep_recovery` stops passing for two different reasons — the price rose
            # out of the cheap band, or the old 52-week high simply aged out of the window — and
            # only the first is a reason to take money off the table. `screen_exit_min_gain` keeps
            # the first and discards the second.
            # C4. C2 is why this exists. Requiring +10% of profit before the screen could sell made
            # the run WORSE than either taking the signal raw (C1, +$4,624) or ignoring it
            # entirely (C1b, -$8,459): -$12,773, average loss -10.21% -> -13.24%, drawdown -18% ->
            # -35%. The gate did not protect winners, it stopped the rule cutting losers — which
            # means the rule was never a profit-take at all.
            #
            # `deep_recovery` has four clauses and only one of them moves on its own: `r3 > 0.10`,
            # the trailing quarter. Depth and off-high fail when the old high or low simply ages
            # out of the 252-day window, which says nothing; the quarter failing says the move
            # stopped. So the exit is that clause by itself, judged on the stock and not on our
            # P&L, which is how every other exit in §3.2 works.
            if hyp["momentum_exit_r3"] is not None and not riding:
                r3 = sg.deep_recovery(H[own_bars(valid, j, t), j], L[own_bars(valid, j, t), j],
                                      C[own_bars(valid, j, t), j])["r3"] \
                     if own_bars(valid, j, t) is not None else None
                if r3 is not None and r3 < float(hyp["momentum_exit_r3"]):
                    pending[tk] = "momentum_died"
                    continue
            if hyp["screen"] and hyp["screen_exit"] and not riding \
                    and row is not None and row["m2"] is False \
                    and (hyp["screen_exit_min_gain"] is None
                         or cl / p["avg_cost"] - 1 >= float(hyp["screen_exit_min_gain"])):
                pending[tk] = "no_longer_cheap"
                continue
            if not riding and row is not None and row["mcn"] == row["mcn"] \
                    and row["mcn"] < cfg["mcn_exit"]:
                pending[tk] = "score"
                continue
            if not riding and sg.stagnant(sessions_since_high=t - p["hi_at"],
                                          limit=hyp["stagnation_days"]):
                pending[tk] = "stagnant"
                continue

            # §3.2: a stalled pyramid "either completes on the next base or exits". Only the exit
            # branch was ever built. P1 builds the other one — the press.
            #
            # The first cut of this required a valid new base AND a breakout on the exact session
            # the four-week clock expired. That is a coincidence, not a rule: it never fired once
            # in 285 trades, so P1 went untested while looking disproven. "The next base" needs a
            # window to arrive in — the position keeps its stop and is given `press_grace` sessions
            # to complete, and exits only if none shows up.
            stalled_now = not riding and sg.stalled_pyramid(
                pyramid_step=p["step"], sessions_held=t - p["stall_from"])
            seeking = p.get("seeking")
            if hyp["press_on_next_base"] and p["step"] < 3 and (stalled_now or seeking):
                if not seeking:
                    p["seeking"] = seeking = t + int(hyp["press_grace"])
                    conf["press_windows"] += 1
                pressed = False
                nb_rows = own_bars(valid, j, t, back=1)
                nb = (sg.base_scan(H[nb_rows, j], L[nb_rows, j], C[nb_rows, j],
                                   min_age=int(hyp["min_base_age"]),
                                   max_depth=_tolerance(sg.atr_fraction(H[nb_rows, j], L[nb_rows, j],
                                                                        C[nb_rows, j]),
                                                        hyp["depth_atr_mult"]))
                      if nb_rows is not None else None)
                if nb and nb["valid"] and not np.isnan(hi) and hi >= nb["pivot"]:
                    dollars = p["target"] * (3 - p["step"]) * 0.25
                    if cash >= dollars:
                        fillp = max(nb["pivot"], op if not np.isnan(op) else nb["pivot"])
                        paid = dollars * (1 + spread(j, t))
                        cash -= paid
                        p["lots"].append((dollars, fillp,
                                          A[t, j] if np.isfinite(A[t, j]) else fillp))
                        p["qty"] += dollars / fillp
                        p["invested"] += paid
                        p["gross_invested"] += dollars
                        p["avg_cost"] = p["invested"] / p["qty"]
                        p["qty_peak"] = max(p["qty_peak"], p["qty"])
                        p["step"] = 3
                        p["stall_from"] = t
                        p["seeking"] = None
                        conf["pressed"] += 1
                        pressed = True
                if not pressed and t >= seeking:
                    conf["press_expired"] += 1
                    pending[tk] = "stalled"
                    continue                      # no base arrived in the window — resolve it
            elif stalled_now:
                pending[tk] = "stalled"
                continue

            nxt = _next_report(frame["reports"].get(tk), day)
            conf["blackout_decisions"] += 1
            if _knowable(nxt, day):
                conf["blackout_known"] += 1
                if not riding and sg.trading_days_between(day, nxt) <= 1 and \
                        sg.holds_through_earnings(cl, p["avg_cost"], cushion=cfg["cushion"]) is False:
                    pending[tk] = "earnings"
                    continue

            # ---- pyramid: adds arm only once confirmed, both limits at the ceiling (§3.2)
            add_nxt = _next_report(frame["reports"].get(tk), day)
            if state["pyramid_armed"] and p["step"] < 3 and not (
                    add_nxt is not None and sg.in_blackout(day, add_nxt)):
                for order in sg.pyramid_orders(p["pivot"], ceiling=cfg["pyramid_ceiling"],
                                               spacing=hyp["pyramid_spacing"],
                                               tranches=int(hyp["pyramid_tranches"])):
                    if order["step"] <= p["step"] or hi < order["trigger"]:
                        continue
                    fill = max(order["trigger"], op if not np.isnan(op) else order["trigger"])
                    if fill > order["limit"]:
                        continue                          # a gap beyond +5% fills nothing
                    dollars = p["target"] * order["fraction"]
                    if cash < dollars:
                        continue
                    paid = dollars * (1 + spread(j, t))
                    cash -= paid
                    p["lots"].append((dollars, fill, A[t, j] if np.isfinite(A[t, j]) else fill))
                    p["qty"] += dollars / fill
                    p["invested"] += paid
                    p["gross_invested"] += dollars
                    p["avg_cost"] = p["invested"] / p["qty"]
                    p["qty_peak"] = max(p["qty_peak"], p["qty"])
                    p["step"] = order["step"]

            # ---- the stop ladder
            out = sg.ratchet_stop(closes=C[max(0, p["entry_idx"]):t + 1, j][
                                      ~np.isnan(C[max(0, p["entry_idx"]):t + 1, j])],
                                  avg_cost=p["avg_cost"], current_stop=p["stop"],
                                  highest_close=p["hi_close"], pyramid_step=p["step"],
                                  trail10_from=hyp["trail_from"],
                                  trail10=(hyp["runner_trail"] if riding and hyp["runner_trail"]
                                           else hyp["strength_trail"] if proven
                                           and hyp["strength_trail"] else hyp["trail"]),
                                  breakeven_r=hyp["breakeven_r"], init_stop=p["init_stop"],
                                  breakeven=hyp["breakeven"],
                                  # A runner has already banked two rungs of profit. The euphoria
                                  # tightening pays on an ordinary position (B2 proved that) but on
                                  # a trimmed one it is what ends the ride: in run 33 all three
                                  # runners stopped out 2-4 sessions after their second trim, on a
                                  # 5% trail, at +91.7% (MU), +102.7% (AVAV) and +9.9% (CAMT).
                                  euphoria=hyp["euphoria"] and not proven and not (
                                      riding and hyp["runner_no_euphoria"]),
                                  breakeven_on_full_size=hyp["breakeven_on_full_size"],
                                  breakeven_giveback=hyp["breakeven_giveback"])
            if out["stop"] is not None:
                p["stop"] = out["stop"]
            p["last_mark"] = cl

        # ---- entries. A resting GTC buy stop-limit at the pivot, judged daily (§3.2 M3 is a
        # daily trigger check — the pre-rewrite sim reused Friday's pivot all week).
        if on and queue and len(book) < cfg["max_names"]:
            exposure = sum(p["qty"] * (C[t, col[p["ticker"]]] if not np.isnan(C[t, col[p["ticker"]]])
                                       else p["last_mark"]) for p in book.values())
            for tk in queue["l1m"]:
                if tk in book or len(book) >= cfg["max_names"]:
                    continue
                row = scored[tk]
                if not sg.enterable(row["mcn"], floor=cfg["min_mcn"]):
                    conf["entries_refused_below_70"] += 1
                    continue
                j = col[tk]
                # The base is read on LAST NIGHT's bars, and today's session is what fills the
                # order resting at its pivot (§5.1). Scanning through today instead would mark the
                # base broken by the very breakout it is supposed to trigger — the scan says
                # "spent" the moment a high clears pivot x 1.005 — so nothing but marginal touches
                # could ever fill.
                back = 2 if hyp["confirm_before_entry"] else 1
                rows = own_bars(valid, j, t, back=back)
                if rows is None:
                    continue
                apct = sg.atr_fraction(H[rows, j], L[rows, j], C[rows, j])
                base = sg.base_scan(H[rows, j], L[rows, j], C[rows, j],
                                    min_age=int(hyp["min_base_age"]),
                                    max_depth=_tolerance(apct, hyp["depth_atr_mult"]))
                # Two doors, tried in that order. §3.2 has only the first; a valid base that did
                # not trigger today must not shut the second, which is what an if/elif on the base
                # would do — the recovering name has an intact old pivot overhead for months.
                got = None
                if base["valid"] and fired.get(tk) != round(float(base["pivot"]), 4):
                    if not _blacked_out(frame, conf, tk, day):
                        got = base_trigger(j, t, base, rows)
                if got is None and hyp["screen"] == "deep_recovery":
                    rows1 = own_bars(valid, j, t, back=1)
                    if rows1 is not None and sg.resumed(C[rows1, j], window=20) \
                            and not _blacked_out(frame, conf, tk, day):
                        px = O[t, j]
                        if np.isnan(px):
                            px = C[rows1[-1], j]
                        got = dict(kind="recovery", fill=px, pivot=px, confirmed=True)
                if got is None and _reentry_ready(tk, j, t, valid, C, exited, hyp):
                    # X1. No base, or one that will not trigger for months: a name that corrected
                    # 42% needs that long to build another, and by then the move it was going to
                    # make has happened. The way back in is the market's own statement that the
                    # move resumed — a close above every close of the prior `reentry_window`
                    # sessions, on a name that still passes M2, M4 and the MCN floor. Not our exit
                    # price: where we happened to sell is our history, not the stock's, and 96% of
                    # stopped-out names traded back through it inside 60 days anyway.
                    #
                    # Same timing discipline as E1 — judged at last night's close, filled at this
                    # open. The new high IS the confirmation, so no volume multiple is demanded on
                    # top of it; that is the clause to falsify if the bucket churns.
                    if not _blacked_out(frame, conf, tk, day):
                        px = O[t, j]
                        if np.isnan(px):
                            px = C[own_bars(valid, j, t, back=1)[-1], j]
                        # the pivot is the fill: the adds ladder off the entry, there being no base
                        got = dict(kind="reentry", fill=px, pivot=px, confirmed=True)
                if got is None:
                    continue
                kind, fill, pivot = got["kind"], got["fill"], got["pivot"]
                born_confirmed = got["confirmed"]
                if not np.isfinite(fill) or fill <= 0:
                    continue
                # R1: the stop is the name's own noise, not a fixed percentage floored at the
                # contraction low — that floor is what makes the law's stop tight enough to fire
                # before any multi-month move can happen. A re-entry has no base and therefore no
                # contraction low, so it takes the volatility stop or a flat cap.
                if hyp["atr_stop_mult"]:
                    a14 = sg.atr(H[rows, j], L[rows, j], C[rows, j])
                    stop = sg.volatility_stop(fill, float(a14[-1]) if len(a14) else None,
                                              mult=hyp["atr_stop_mult"], max_stop=hyp["max_stop"])
                else:
                    stop = sg.initial_stop(fill, None if kind == "reentry"
                                           else base["contraction_low"], max_stop=hyp["max_stop"])
                dist = max((fill - stop) / fill, 1e-4)
                budgets = ((hyp["budget_lo"], hyp["budget_hi"])
                           if hyp["budget_lo"] and hyp["budget_hi"] else (0.007, 0.009))
                size = sg.momentum_size(nav=nav, mcn_score=row["mcn"], stop_distance=dist,
                                        budgets=budgets,
                                        band=(0.08, hyp["band_hi"] or 0.12))
                if not size:
                    continue
                target = size["size_pct"] * nav
                if exposure + target > (hyp["sleeve_cap_pct"] or cfg["sleeve_cap"]) * nav:
                    continue
                # ---- H1: total open risk. The sleeve cap limits how much is INVESTED; nothing
                # limited how much could be LOST. Under the capital regime a 25% position behind a
                # 20% stop puts 5% of NAV at risk, and four of them put 20% at risk at once — run
                # 34 drew down 53.5% while its average trade was +1.27%, which is what over-betting
                # a real edge looks like. Heat is the missing primitive: the sum of (what we would
                # lose if every open stop fired today), capped as a fraction of NAV.
                if hyp["heat_cap"]:
                    open_heat = sum(q["qty"] * max(q["avg_cost"] - (q["stop"] or 0.0), 0.0)
                                    for q in book.values())
                    if open_heat + target * dist > float(hyp["heat_cap"]) * nav:
                        conf["heat_refused"] += 1
                        continue
                # §3.2 buys half now and the rest at +2%/+4%, because at the pivot the breakout is
                # still unconfirmed. Under E1 it is confirmed before a share is bought, so the
                # hedge is paying for a risk that no longer exists — Z1 lets the caller take the
                # whole position at entry, and marks it full so the pyramid does not add again.
                frac = float(hyp["entry_fraction"])
                dollars = target * frac
                if cash < dollars * (1 + 0.01):
                    continue
                paid = dollars * (1 + spread(j, t))
                cash -= paid
                exposure += dollars
                if kind == "base":
                    fired[tk] = round(float(pivot), 4)
                elif kind == "recovery":
                    conf["recoveries"] += 1
                else:
                    conf["reentries"] += 1
                conf["entries"] += 1
                book[tk] = dict(ticker=tk, kind=kind,
                                lots=[(dollars, fill, A[t, j] if np.isfinite(A[t, j]) else fill)],
                                qty=dollars / fill, invested=paid, gross_invested=dollars,
                                avg_cost=paid / (dollars / fill), stop=stop, pivot=pivot,
                                hi_close=fill, hi_at=t, step=3 if frac >= 1.0 else 1,
                                target=target, mcn=row["mcn"], trimmed=set(),
                                qty_peak=dollars / fill,
                                entry_date=day, entry_idx=t, stall_from=t, init_stop=stop,
                                size=size["size_pct"], mfe=0.0, mae=0.0, last_mark=fill,
                                confirmed=born_confirmed, stale=0)

        # ---- mark
        held = 0.0
        for p in book.values():
            px = C[t, col[p["ticker"]]]
            if np.isnan(px):
                px = p["last_mark"]
            else:
                p["last_mark"] = px
            held += p["qty"] * px
        nav = cash + held
        equity.append((day, nav, held / nav if nav else 0.0, len(book),
                       "ON" if on else "OFF", frame["bench_by_day"].get(day)))

    for tk in list(book):
        j = col[tk]
        px = C[n - 1, j]
        cash += close_position(tk, dates[n - 1], px if not np.isnan(px) else book[tk]["last_mark"],
                               "end_of_test", n - 1)
    return trades, equity, conf


def _gate_series(spx):
    """M1 for every week of the test, latched — `market_gate` carrying its own previous state.

    The rule returns one verdict for one moment and needs the prior state to latch, so the driver
    walks it forward week by week. The walking is the driver's job; the verdict is never the
    driver's job, which is why this calls §3.2's own function 520 times rather than reimplementing
    the comparison once.
    """
    dates, closes = list(spx.index), list(spx.values)
    weeks = sg.weekly_closes(dates, closes)
    ends, states, prev = [], [], None
    for i, (week_end, _) in enumerate(weeks):
        k = bisect.bisect_right(dates, week_end)
        try:
            out = sg.market_gate(dates[:k], closes[:k], previous=prev)
        except ValueError:
            continue                              # not yet 35 weekly closes — no verdict exists
        prev = out["state"]
        ends.append(week_end)
        states.append(prev)
    return ends, states


def _gate_on(ends, states, day):
    """The M1 decision in force — the most recent weekly verdict at or before `day` (§3.2 latch)."""
    i = bisect.bisect_right(ends, day) - 1
    return bool(i >= 0 and states[i] == "ON")


def _next_report(reports, day):
    if not reports:
        return None
    i = bisect.bisect_left(reports, day)
    return reports[i] if i < len(reports) else None


def _knowable(nxt, day, horizon=CALENDAR_HORIZON):
    """Did we actually know when this name next reports — or just find *a* date?

    Coverage has to mean the second thing. The `earnings` ledger reaches back only as far as the
    calendar sweep has run, so on any earlier date the "next report" it returns is whatever the
    modern calendar holds — often years ahead. `in_blackout` correctly declines to fire on a date
    that far out, so nothing is wrongly blocked; but counting it as coverage told the conformance
    table the blackout was enforceable over 99.9% of a window where it was mostly unenforceable.
    A clause that reports itself covered when it is blind is the exact failure this table exists
    to catch, so the horizon is one quarter.
    """
    return nxt is not None and (nxt - day).days <= horizon


# =============================================================================== conformance
def _declare(hyp, key, law_text, variant_text):
    """What a clause was actually enforced at. A widened threshold is not a violation, but a
    conformance table that still prints the law's number while the run used another one is a lie."""
    mult = (hyp or {}).get(key)
    return law_text if not mult else variant_text.format(mult)


def conformance(conf, trades, equity, hyp=None):
    """Every §3.2/§3.3 clause the run claims to implement, and how much of the window had the data
    to enforce it. A green tick on a clause that was unenforceable for most of the test is the
    failure this table exists to end (learnings #19 — green is not a result)."""
    reasons = {t["exit_reason"] for t in trades}
    legal = {"stop", "gap", "gate_off", "unconfirmed", "template", "score", "earnings",
             "stalled", "delisted", "end_of_test"}
    # A hypothesis may introduce an exit the law does not name. That is not a violation, but it is
    # not conformance either — it has to be declared, so a variant can never quietly pass as
    # law-v0. law-v0 declares nothing and so still fails on any unknown reason.
    declared = {"stagnant"} if (hyp or {}).get("stagnation_days") else set()
    declared |= {f"trim{int(round(x * 100))}" for x in ((hyp or {}).get("trim_at") or ())}
    if (hyp or {}).get("forever"):
        declared.add("profitability")
    if (hyp or {}).get("screen_exit"):
        declared.add("no_longer_cheap")
    if (hyp or {}).get("momentum_exit_r3") is not None:
        declared.add("momentum_died")
    cov = lambda a, b: (a / b) if b else None
    return [
        dict(clause="M1 latch — weekly, 30-week SMA", fn="signals.market_gate", coverage=1.0),
        dict(clause="M2 trend template — six conditions", fn="signals.trend_template",
             coverage=1.0, off_high=_declare(hyp, "off_high_atr_mult", "25% flat",
                                             "max(25%, {} x ATR), capped 60%")),
        dict(clause="M3 base detection, checked daily", fn="signals.base_scan", coverage=1.0,
             depth=_declare(hyp, "depth_atr_mult", "25% flat",
                            "max(25%, {} x ATR), capped 60%"),
             min_age=int((hyp or {}).get("min_base_age", 25))),
        dict(clause="M4 earnings acceleration", fn="signals.m4_acceleration",
             coverage=cov(conf["m4_known"], conf["m4_evaluated"])),
        dict(clause="MCN — three components, windows end t-10", fn="signals.mcn", coverage=1.0),
        dict(clause="Entry — GTC stop-limit, pivot / pivot+2%", fn="signals.entry_order",
             coverage=1.0,
             # §3.2 knows one way into a name: a fresh valid base. A run that bought any other way
             # has to say so here, with the count, or a variant could pass as law-v0.
             reentries=conf.get("reentries", 0), recoveries=conf.get("recoveries", 0),
             screen=(hyp or {}).get("screen") or "M2 trend template + M3 base (§3.2)",
             m4_required=bool((hyp or {}).get("require_m4", True)),
             violations=((0 if (hyp or {}).get("reentry_window") else conf.get("reentries", 0))
                         + (0 if (hyp or {}).get("screen") else conf.get("recoveries", 0)))),
        dict(clause="EOD confirmation, freeze at 50%, late window",
             fn="signals.confirmation_state", coverage=1.0),
        dict(clause="Pyramid +2%/+4%, both limits pivot x 1.05", fn="signals.pyramid_orders",
             coverage=1.0),
        dict(clause="Stops — initial, breakeven, 10% trail, euphoria", fn="signals.ratchet_stop",
             coverage=1.0),
        # `unknown_reasons` catches an exit the law does not name. `suppressed` catches the other
        # direction — a §3.2 exit the run stopped enforcing, which no count of reasons can show,
        # because a rule that never fires looks exactly like a rule with nothing to fire on.
        dict(clause="Exits — stop, template, MCN < 55", fn="driver",
             coverage=1.0, unknown_reasons=sorted(reasons - legal - declared),
             variant_reasons=sorted(reasons & declared),
             suppressed=([] if ((hyp or {}).get("template_exit", True)
                                and not (hyp or {}).get("screen")) else ["template"])),
        dict(clause="Earnings blackout — 5 trading days", fn="signals.in_blackout",
             coverage=cov(conf["blackout_known"], conf["blackout_decisions"])),
        dict(clause="Sizing — budget / stop distance", fn="signals.momentum_size", coverage=1.0,
             heat_cap=(hyp or {}).get("heat_cap"), heat_refused=conf.get("heat_refused", 0),
             band_ceiling=(hyp or {}).get("band_hi") or 0.12,
             entry_fraction=(hyp or {}).get("entry_fraction", 0.5),
             sleeve_cap=(hyp or {}).get("sleeve_cap_pct")),
        # §3.2 has no partial exit: a position is opened once and closed once. The trim ladder
        # sells slices, so the rungs are named here and the count is reported — a run that sold
        # part of a position without declaring it is not law-v0 however its exits are labelled.
        dict(clause="Position is opened once and closed once", fn="driver", coverage=1.0,
             trims=conf.get("trims", 0),
             violations=(0 if (hyp or {}).get("trim_at") else conf.get("trims", 0)),
             rungs=list((hyp or {}).get("trim_at") or ()),
             runner_immunity=bool((hyp or {}).get("runner_immunity"))),
        dict(clause="MCN < 70 never tickets", fn="signals.enterable", coverage=1.0,
             refused=conf["entries_refused_below_70"],
             violations=sum(1 for t in trades if t["mcn"] is not None and t["mcn"] < 70)),
        dict(clause="Stalled pyramid — 4 weeks", fn="signals.stalled_pyramid", coverage=1.0),
        dict(clause="Survivorship — delisted retained", fn="driver", coverage=1.0,
             delisted_exits=sum(1 for t in trades if t["exit_reason"] == "delisted")),
    ]


def summarise(trades, equity, frame, conf, hyp=None):
    eq = pd.DataFrame(equity, columns=["d", "nav", "exposure", "positions", "gate", "bench"])
    eq["d"] = pd.to_datetime(eq["d"])
    nav = eq.nav
    years = max((eq.d.iloc[-1] - eq.d.iloc[0]).days / 365.25, 1e-9)
    dd = nav / nav.cummax() - 1
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    b = eq.bench.dropna()
    bench_total = (b.iloc[-1] / b.iloc[0] - 1) if len(b) > 1 else None
    invested = sum(t["qty"] * t["entry_price"] for t in trades) or 1.0
    full = [t for t in trades if not str(t["exit_reason"]).startswith("trim")]
    deployed = sum(t["qty"] * t["entry_price"] for t in trades)
    table = conformance(conf, trades, equity, hyp=hyp)
    return dict(
        start_date=eq.d.iloc[0].date(), end_date=eq.d.iloc[-1].date(), trading_days=len(eq),
        start_nav=float(nav.iloc[0]), end_nav=float(nav.iloc[-1]),
        total_return=float(nav.iloc[-1] / nav.iloc[0] - 1),
        cagr=float((nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1),
        max_drawdown=float(dd.min()), max_dd_date=eq.d.iloc[int(dd.idxmin())].date(),
        trades=len(trades), wins=len(wins),
        win_rate=(len(wins) / len(trades)) if trades else None,
        avg_win=float(np.mean([t["pnl_pct"] for t in wins])) if wins else None,
        avg_loss=float(np.mean([t["pnl_pct"] for t in losses])) if losses else None,
        # Equal-weighted over trade ROWS. Kept for continuity with runs 1-32, but once a variant
        # trims, a row is a *slice* rather than a position and this number stops meaning what it
        # meant — see `expectancy_full_exits` and `return_on_deployed` below, which are the ones to
        # compare across the M-series.
        expectancy=float(np.mean([t["pnl_pct"] for t in trades])) if trades else None,
        avg_exposure=float(eq.exposure.mean()),
        avg_hold_days=float(np.mean([t["bars_held"] for t in trades])) if trades else None,
        benchmark_return=float(bench_total) if bench_total is not None else None,
        benchmark_cagr=float((1 + bench_total) ** (1 / years) - 1) if bench_total is not None else None,
        stats=dict(
            benchmark=BENCH, gate_source=frame["gate_source"], currency="USD",
            conformance=table,
            conformance_ok=all(c.get("coverage") not in (None, 0) for c in table)
                           and not any(c.get("unknown_reasons") for c in table)
                           and not any(c.get("violations") for c in table),
            exits={r: sum(1 for t in trades if t["exit_reason"] == r)
                   for r in sorted({t["exit_reason"] for t in trades})},
            cost_usd=float(sum(t["cost_usd"] for t in trades)),
            expectancy_gross=float(np.mean([t["pnl_gross_usd"] / (t["qty"] * t["entry_price"])
                                            for t in trades])) if trades else None,
            dividend_bps=float(10_000 * sum(t["dividend_usd"] for t in trades) / invested)
                         if trades else None,
            days_gate_on=int((eq.gate == "ON").sum()), days_gate_off=int((eq.gate == "OFF").sum()),
            pct_time_invested=float((eq.positions > 0).mean()),
            best=max((t["pnl_pct"] for t in trades), default=None),
            worst=min((t["pnl_pct"] for t in trades), default=None),
            # A trim rung can only be hit by a position that is already up 50% or 100%, so the
            # slices are winners *by construction* and averaging them beside full exits flatters
            # the run. Run 36 reads +2.208% on `expectancy` and -1.45% on the dollar it actually
            # deployed: five slices averaging +69.85% on $3.4k positions against 122 full exits
            # averaging -0.56% on $18.2k positions. These two are the honest measures.
            expectancy_full_exits=float(np.mean([t["pnl_pct"] for t in full])) if full else None,
            return_on_deployed=(float(sum(t["pnl_usd"] for t in trades) / deployed)
                                if deployed else None),
            trim_slices=len(trades) - len(full),
            trim_usd=float(sum(t["pnl_usd"] for t in trades if t not in full)) if trades else 0.0,
            diagnostics=conf,
            biases=["vendor serves the current version of a past statement (restatements)",
                    "industry mappings are today's",
                    "L0 census rebuilt from stored bars — names never ingested are still absent"]),
    )


# =============================================================================== entry point
def main():
    with connect() as conn:
        with Heartbeat(conn, "backtest") as hb:
            with conn.cursor() as cur:
                hyp = hypothesis()
                frame = load(cur)
                # The SAME config rows the nightly reads, spelled the same way. Inventing
                # `momentum_min_mcn` here would have read a row that does not exist, fallen
                # through to a default, and measured a threshold nobody set — learnings #21,
                # which this repo has already paid for once (`score_thresholds.enter` was
                # decorative for weeks because the code asked for `enterable`).
                thresholds = config(cur, "score_thresholds", {}) or {}
                ceilings = config(cur, "sleeve_ceiling", {"momentum": 0.40}) or {}
                cfg = dict(start_nav=START_NAV,
                           max_names=int(hyp["max_names"]
                                         or config(cur, "momentum_max_names", 4)),
                           sleeve_cap=float(ceilings.get("momentum", 0.40)),
                           min_mcn=float(thresholds.get("enter", 70)),
                           mcn_exit=float(thresholds.get("hold", 55)),
                           cushion=float(config(cur, "holdthrough_cushion", 1.08)),
                           max_stop=hyp["max_stop"], limit_over=0.02,
                           pyramid_ceiling=1.05, confirm_limit=1.05, hyp=hyp,
                           spread_bps=(5.0, 15.0), addv_break=50_000_000.0,
                           # Ruled 2026-08-10: wait out the window. The rejected reading stays
                           # runnable so the ruling can be priced against its alternative.
                           hair_trigger_while_pending=HAIR_TRIGGER_PENDING)
                # Behaviour lives in the database as well as in git, so the run stamps what it
                # ran under. A config change with no re-test is then a visible condition rather
                # than a silent one (Phase 5 of the backtest plan).
                config_stamp = config_digest(cur)

            if START_DATE or END_DATE:
                keep = [i for i, d in enumerate(frame["dates"])
                        if (not START_DATE or str(d) >= START_DATE)
                        and (not END_DATE or str(d) <= END_DATE)]
                frame["dates"] = [frame["dates"][i] for i in keep]
                frame["arrays"] = {k: v[keep] for k, v in frame["arrays"].items()}
            frame["bench_by_day"] = {d: float(v) for d, v in frame["bench"].items()}

            hb.detail.update(tickers=len(frame["cols"]), bars=len(frame["dates"]),
                             benchmark=BENCH, gate_source=frame["gate_source"],
                             hair_trigger_while_pending=HAIR_TRIGGER_PENDING)
            print(f"backtest {VARIANT}: {len(frame['cols'])} tickers x {len(frame['dates'])} bars "
                  f"| bench {BENCH} | gate {frame['gate_source']}")

            trades, equity, conf = simulate(frame, cfg)
            summary = summarise(trades, equity, frame, conf, hyp=hyp)
            print(f"  {summary['trades']} trades | CAGR {summary['cagr']:.1%} "
                  f"vs {BENCH} {summary['benchmark_cagr'] or 0:.1%} | "
                  f"maxDD {summary['max_drawdown']:.1%} | "
                  f"conformance {'OK' if summary['stats']['conformance_ok'] else 'FAILED'}")
            for c in summary["stats"]["conformance"]:
                if c.get("coverage") is not None and c["coverage"] < 1.0:
                    print(f"    coverage {c['coverage']:.0%} — {c['clause']}")

            if not dry():
                params = dict(variant=VARIANT, law_stamp=LAW_STAMP, currency="USD",
                              config_stamp=config_stamp,
                              benchmark=BENCH, start_nav=START_NAV, warmup=WARMUP,
                              costs=dict(commission_per_trade=0.0, fx_fee_per_side=0.0,
                                         half_spread_bps=dict(deep=cfg["spread_bps"][0],
                                                              thin=cfg["spread_bps"][1]),
                                         addv_break=cfg["addv_break"]),
                              max_names=cfg["max_names"], sleeve_cap=cfg["sleeve_cap"],
                              min_mcn=cfg["min_mcn"],
                              hair_trigger_while_pending=HAIR_TRIGGER_PENDING,
                              hypothesis=HYPOTHESIS or "law", hyp=cfg["hyp"])
                with conn.cursor() as cur:
                    cur.execute("""insert into backtest_runs(label,params,start_date,end_date,
                          trading_days,start_nav,end_nav,total_return,cagr,max_drawdown,max_dd_date,
                          trades,wins,win_rate,avg_win,avg_loss,expectancy,avg_exposure,
                          avg_hold_days,benchmark_return,benchmark_cagr,stats)
                        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        returning id""",
                        (LABEL, json.dumps(params),
                         summary["start_date"], summary["end_date"], summary["trading_days"],
                         summary["start_nav"], summary["end_nav"], summary["total_return"],
                         summary["cagr"], summary["max_drawdown"], summary["max_dd_date"],
                         summary["trades"], summary["wins"], summary["win_rate"],
                         summary["avg_win"], summary["avg_loss"], summary["expectancy"],
                         summary["avg_exposure"], summary["avg_hold_days"],
                         summary["benchmark_return"], summary["benchmark_cagr"],
                         json.dumps(summary["stats"], default=str)))
                    rid = cur.fetchone()[0]
                    cur.executemany("""insert into backtest_trades(run_id,ticker,entry_date,
                          entry_price,qty,exit_date,exit_price,mcn,pivot,initial_stop,size_pct,
                          pyramid_steps,pnl_cad,pnl_pct,bars_held,max_favorable,max_adverse,
                          exit_reason,entry_kind)
                        values (%(run_id)s,%(ticker)s,%(entry_date)s,%(entry_price)s,%(qty)s,
                          %(exit_date)s,%(exit_price)s,%(mcn)s,%(pivot)s,%(initial_stop)s,
                          %(size_pct)s,%(pyramid_steps)s,%(pnl_usd)s,%(pnl_pct)s,%(bars_held)s,
                          %(max_favorable)s,%(max_adverse)s,%(exit_reason)s,%(entry_kind)s)""",
                        [{**t, "run_id": rid} for t in trades])
                    cur.executemany("""insert into backtest_equity(run_id,d,nav,exposure,positions,
                                         gate,benchmark) values (%s,%s,%s,%s,%s,%s,%s)""",
                        [(rid, d, nv, e, p, g, None if bch is None or
                          (isinstance(bch, float) and np.isnan(bch)) else bch)
                         for d, nv, e, p, g, bch in equity])
                conn.commit()
                hb.detail["run_id"] = rid

            hb.rows = len(trades) + len(equity)
            hb.detail.update({k: v for k, v in summary.items() if k != "stats"})
            hb.detail["exits"] = summary["stats"]["exits"]
            hb.detail["conformance_ok"] = summary["stats"]["conformance_ok"]
            if not summary["stats"]["conformance_ok"]:
                hb.amber("conformance table has a failing clause — see stats.conformance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
