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
