# Backtest v1 — momentum sleeve, 2024-08-28 → 2026-07-30

Run 5, `backtest_runs.id = 5`. 500 trading days, 296 trades, 2,783 US names.

## Headline

| | Yuna momentum | S&P 500 |
|---|---|---|
| Total return (on NAV) | **+7.49%** | +33.00% |
| CAGR | **+3.83%** | +16.02% |
| Max drawdown | **−7.21%** | — |
| Average exposure | **12.66%** of NAV | 100% |
| **Return on capital actually deployed** | **≈ 27.6%/yr** | — |

The last line is the finding. Per dollar at risk the sleeve earns close to the 30% bar; it
just cannot keep dollars at risk. A sleeve permitted 40% of NAV averaged 12.66%.

## Where the money went

| Exit | Trades | Avg | Total CAD | Avg days | Avg MFE | Avg MCN |
|---|---|---|---|---|---|---|
| MCN < 55 | 66 | +2.38% | **+32,120** | 7.0 | +4.8% | 61.1 |
| stop | 51 | −1.46% | −1,674 | 4.6 | **+7.2%** | 65.9 |
| trend template fail | 8 | −7.00% | −5,930 | 6.5 | +1.8% | 65.4 |
| volume unconfirmed | 171 | −0.59% | **−9,486** | 1.1 | 0.0% | 62.3 |

Every dollar of profit comes from the relative-strength exit. Everything else leaks.

Strip the volume churn and the remaining 125 trades look like a working momentum system:
**35.2% win rate, +7.53% average winner against −3.76% average loser, 2.0:1, expectancy
+0.22% per trade, best +47.8%, worst −28.4%.** The selection is not the problem.

## Three findings

1. **The §5.1 volume mechanic costs 4.7% of NAV over two years.** The GTC stop-limit fills
   on the break; only 34% of fills carry 1.4x volume (the tape's own rate over 78,328
   breakout days is 29.2%, so the model is honest); the other 171 exit next morning at
   −0.59% each. That is the price of not being able to see volume before the order fills.

2. **Stops give back an average +7.2% of unrealised gain to exit at −1.46%.** The cause is
   an interaction, not a bad stop: §3.2 moves the stop to breakeven only at *full* pyramid
   size, and average pyramid depth is 1.98 of 3. Most positions never complete, so the stop
   never leaves its initial level, and a position that ran +7% round-trips to a small loss.

3. **The trend-template exit fires late.** Only 8 trades, but −7.00% each — the worst
   average of any exit. By the time the weekly template check fails, the damage is done.

## What this does not prove

Survivorship: the L0 census is today's listings, so names that delisted inside the window
are absent and every number above is flattered. No M4 gate (point-in-time EPS is not
stored), which makes L1-M wider here than live and probably *lowers* selectivity. No
earnings blackout. One regime — a 16%/yr bull market — over 1.9 years. Fills modelled at
the pivot with no slippage or FX cost charged.

## Four bugs found getting here, all diagnosed from the heartbeat

1. Exit rule invented a condition — closing anything that fell out of the top-150 L1-M,
   which §3.2 never lists. Ejected six of nine positions within days.
2. A missing bar zeroed a position in the daily mark, inventing a 19% drawdown on a book
   that was 0.3% invested.
3. The volume rule refused the *entry*; §5.1 says the order fills and the brief exits it
   the next morning. Different system entirely.
4. **The one that mattered:** one Canadian listing in the frame put TSX-only dates into the
   union index, so pandas' `rolling()` — whose `min_periods` defaults to the window — returned
   a NaN volume baseline for US names, and an unknown baseline silently read as "not
   confirmed." The sim found 2% confirmation where the tape has 29%. Cross-checking the
   model's own rate against a SQL query on the raw bars is what caught it.

---

# Round 2 — the variant matrix, and the compounder sleeve

## Momentum: six variants

| | Variant | Trades | Return | CAGR | MaxDD | Win | Avg win | Avg loss | Expectancy | Exposure | Hold |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | baseline (plan as written) | 296 | +7.49% | +3.83% | −7.21% | 38.9% | +3.65% | −2.73% | **−0.25%** | 12.7% | 3.1d |
| **B** | **confirm volume before entry** | **84** | **+7.30%** | **+3.74%** | **−2.95%** | 34.5% | +6.08% | −2.53% | **+0.44%** | 7.2% | 6.1d |
| C | breakeven stop at step 2 | 328 | −0.94% | −0.49% | −5.60% | 36.0% | +2.91% | −2.39% | −0.48% | 10.9% | 2.6d |
| D | B + C | 86 | +3.65% | +1.89% | −2.56% | 24.4% | +5.97% | −1.89% | +0.03% | 4.6% | 4.1d |
| E | B + MCN exit at 60 | 85 | +3.75% | +1.94% | −2.93% | 38.8% | +4.49% | −2.84% | +0.01% | 5.9% | 5.0d |
| F | B + one-week minimum hold | 81 | +6.66% | +3.42% | −3.40% | 24.7% | +8.69% | −2.56% | +0.22% | 8.3% | 7.2d |

**B wins and every further tweak makes it worse.** Three of the four hypotheses were wrong:
moving the stop to breakeven earlier (C) turns a positive year negative, tightening the MCN
exit (E) halves the return, and a forced one-week hold (F) costs a little. The plan's own
parameters — breakeven at full size, exit at 55, no minimum hold — beat all of them.

The one change that helps is not a formula change at all. It is §5.1's execution mechanic:
waiting for a confirmed breakout *close* before buying, instead of filling on the touch and
exiting the next morning. Same return, 72% fewer trades, 41% of the drawdown, and expectancy
crosses from −0.25% to +0.44% a trade.

## Compounders: it can be backtested after all

`backtest_runs.id = 12` — 731 non-financial names with point-in-time filings, 494 days.

| | Compounders | S&P 500 |
|---|---|---|
| Total return | +25.96% | +36.86% |
| CAGR | **+12.50%** | +17.36% |
| Max drawdown | **−7.06%** | — |
| Trades | **6** (≈3/yr) | — |
| Average hold | **290 days** | — |
| Win rate | 83.3% | — |
| Average winner / loser | +47.9% / −23.3% | — |
| Average exposure | 45.7% of NAV | 100% |
| Return on deployed capital | **≈ 26.3%/yr** | — |

| Ticker | Entry | CCN | P/L | Days | Exit |
|---|---|---|---|---|---|
| COKE Coca-Cola Consolidated | 2025-06-30 @ 111.65 | 70.6 | **+70.0%** | 274 | held |
| EXEL Exelixis | 2025-07-31 @ 36.22 | 77.4 | +54.5% | 252 | held |
| SIRI Sirius XM | 2025-04-30 @ 21.42 | 80.8 | +44.6% | 315 | held |
| GMAB Genmab | 2024-11-29 @ 21.50 | 71.4 | +36.9% | 310 | CCN < 55 |
| ZM Zoom | 2024-08-30 @ 69.08 | 80.9 | +33.6% | 480 | held |
| TTD Trade Desk | 2026-02-27 @ 23.82 | 90.5 | **−23.3%** | 107 | held |

**Six trades is an anecdote, not evidence.** Read the shape, not the number: year-long holds,
capital actually deployed, one loser, and the loser is the highest-CCN name in the set.

## The strategic finding

Both sleeves earn close to the 30% bar *per dollar deployed* — momentum ≈ 41%/yr on its
average 7.2% exposure, compounders ≈ 26%/yr on 45.7%. Run together they would have made
roughly 16%/yr on NAV against the index's 17.4%, with about half the capital in cash.

The edge is real. The machine will not deploy it. That is the thing to fix, and it is a
different problem from the one the plan is currently written to solve.

## One more bug, found in the compounder run

§3.1 excludes banks and insurers from Gate C1 because EBITDA means nothing for them. The
point-in-time gate rebuilds C1 from filings, and filings carry no sector — so the exclusion
silently vanished, and a reinsurer plus an asset manager took two of six slots including a
+110% winner. Caught by reading the names in the trade list, not by any check.
