# WO-A25 — The holdable cell through 2008

*Pre-registered 2026-09-02, before any arm was dispatched. Zak, 2026-09-02: "I want the highest
realized return possible... but I want a plan whose worst case I can hold through the bad years."*

## The question

§3.8, quoted with the engine always: *"A −61% drawdown has never been tested against a human."*
WO-A24 measured the park's half of that number and settled it: a bill park takes the cell of
record's 2007–09 episode from −60.3% to −21.8% and leaves the sleeve's own drawdown — −45.8% on
2025-11-21, gate ON throughout — exactly where it was. *"A bill park protects gated-off capital
and nothing else."* The sleeve's own drawdown needs a sleeve-side mechanism, and the plan already
names two: §3.2's trail, checked every session, and the volatility governor (Barroso &
Santa-Clara — scale the book by its own realized volatility, the series that forecasts a momentum
crash). The 2016–26 grid ran both. `lg12_semi_trail_vt` was that grid's lowest-drawdown cell,
−29.6% at 23.00% CAGR (`session-2026-08-13`, unproven), and no cell of that grid has ever been
shown 2008. This WO shows it.

## The claim, fixed in advance

**A cell is "holdable" for this WO if, on the 2006-01-10..open window (first decision
2007-01-12), BOTH hold: full-window maxDD no worse than −35%, and CAGR at least twice the index's
over the same window.** The index is SPY.US total return on the store's own adjusted closes,
100.17 on 2007-01-12 to 761.78 on 2026-09-01: **10.88%/yr, so the bar is 21.8%.** One without the
other is not the answer — a −20% cell at 12% is an index fund with extra steps, and a 30% cell at
−55% is the number §3.8 already refuses to call tested.

The −35% is not a plan number. It is the figure Zak's question implies — a worst year a person
holds through rather than sells at the bottom of — declared here so the result cannot move it.
If it is the wrong bar it is wrong in the open, and the ruling that fixes it is his.

Predictions, written before the runs so they can be wrong:

1. The trail-plus-governor arms cut 2007–09 far below the b5 cell's −60%, because the governor
   shrinks the book as its own volatility rises and 2008 is the loudest volatility signal on the
   tape.
2. The gate adds little on top of the governor. They watch different series (index trend, book
   volatility) but fire in the same seasons.
3. The bill park lowers drawdown and CAGR together, as in A24, and by less than in A24, because
   the governor's parked fraction is smaller and shorter-lived than a gate's.
4. The 2016–26 champion `lg8_semi_trail` (proven, 31.75% / −31.2%) draws 40–60% in 2007–09: it
   has a trail and no governor, and a trail alone did not hold the 2025–26 episode below −45%
   in the cell of record.

## The arms

Five dispatches of `backtest.yml`, `research=concentrated`, on one commit, identical in every
input but the two named: `calendar=SPY.US`, `start_date=2006-01-10` (A24's window — first
decision 2007-01-12, one session inside SHV's history), `end_date` blank, `start_nav=100000`.

| arm | `cells` | `park` | what the pair isolates |
|---|---|---|---|
| A | `lg12_semi_trail_vt` | `SHV.US` | the sleeve-side mechanisms, bill park |
| B | `lg12_semi_trail_vt` | `SPY.US` | A–B: the park under the governor, which parks the fraction it shrinks |
| C | `lg12_semi_trail_vt_L1_3` | `SHV.US` | A–C: the gate on top of the governor |
| D | `lg12_semi_trail_vt_L1_3` | `SPY.US` | C–D: the park under gate and governor; B–D: the gate on a SPY park |
| E | `lg8_semi_trail` | `SHV.US` | the champion through 2008, once; its park sensitivity is not measured |

`lg12_semi_trail_vt_L1_3` is the code change: the existing cell plus `gated=True,
latch=(1, 3)`, the cell of record's own latch — out after one close below the 200-day, back after
three above. The grid's one-axis rule (`test_every_announced_cell_moves_one_axis_off_its_own_parent`)
requires the rung between — `lg12_semi_trail_vt_gated`, gate on at the default latch — so it is
declared for the lineage and is not an arm. Every other stored cell reproduces to the digit.

## Trials

Five more trials into §2.5's deflation count (470 before this WO). None is a champion selection:
WO-A5's ladder rule applies, and a probe that beats the champion is evidence about the surface,
not a new champion, because promoting it re-runs the selection the deflation already prices.

## What this is not

Not a promotion. §3.1's three numbers stand; §3.7's park stands. A cell that meets the bar is a
candidate for a ruling, taken after the freeze question (research freeze — how many more of these
before the count itself is the finding) has been ruled, not before. A24's vehicle note holds
unchanged: SHV measures the mechanism, and production, if anything is promoted, picks a vehicle
under `.claude/rules/investment-tax.md`.

The window's own limit is §3.8's: two crash shapes, both V-shaped. 2000–02 is not on the tape
(WO-A26), and a cell that holds 2008 has still not been shown a grinding multi-year decline.

## Gates

As A24: `finding.py` (fails closed when the window cannot support the claim) and
`capture_audit.py` on every run; `verify_run.py`'s sixteen checks after. Learning 40 applies —
the episode cut (2007–09, worst of the 2010s, 2020, 2022, 2025–26) is owed before any full-window
number is called a finding. A24's standing caveat applies too: repo-standard until the upstream
`backtest-protocol` has been applied.
