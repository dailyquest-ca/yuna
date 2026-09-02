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

## Result — 2026-09-02, runs 627, 628, 629, 632, 631

All five on code stamp `afa2adab8553ee80`, window `2006-01-10..open` (first decision 2007-01-12,
last 2026-09-01, 4,940 sessions), start NAV $100,000. The dispatch itself is learning 62: five
arms at once filled the production database's disk and four died at ninety seconds; they were
re-run two at a time on the same stamp.

| arm | run | cell | park | CAGR | maxDD (date) | end NAV | trades |
|---|---|---|---|---|---|---|---|
| A | 627 | `lg12_semi_trail_vt` | SHV | 10.51% | −28.9% (2009-03-03) | $711,033 | 1,089 |
| B | 628 | `lg12_semi_trail_vt` | SPY | 13.83% | −55.8% (2009-03-09) | $1,269,413 | 1,078 |
| C | 629 | `lg12_semi_trail_vt_L1_3` | SHV | 9.35% | −19.5% (2026-07-02) | $577,109 | 862 |
| D | 632 | `lg12_semi_trail_vt_L1_3` | SPY | 14.26% | −55.2% (2009-03-09) | $1,368,206 | 907 |
| E | 631 | `lg8_semi_trail` | SHV | 9.45% | −35.3% (2012-01-03) | $587,675 | 317 |
| — | 624 / 623 | cell of record `b5_12_2_L1_3` (WO-A24) | SPY / SHV | 26.08% / 24.22% | −60.3% / −45.8% | $9.46M / $7.07M | 748 |
| — | | SPY.US total return, same window | | 10.88% | −55% | | |

**Against the pre-registered claim: not met, by any arm, on either half.** The bar was maxDD no
worse than −35% AND CAGR at least 21.8%. The nearest on return is D at 14.26%, seven and a half
points short; the nearest on drawdown is C at −19.5%, fifteen points inside the bar and at
9.35% — below the index. No arm has both, and across the five the two halves move against each
other: every point of drawdown removed was paid for in return.

Peak-to-trough by episode (learning 40's cut), with the cell of record beside them:

| episode | A | B | C | D | E | record SPY / SHV |
|---|---|---|---|---|---|---|
| 2007–09 | −28.9% | −55.8% | **−8.2%** | −55.2% | −27.9% | −60.3% / −21.8% |
| worst of the 2010s | −28.8% | −41.3% | −14.7% | −30.6% | −35.3% | −50.0% / −37.5% |
| 2020 | −14.3% | −30.8% | −13.5% | −33.9% | −9.9% | −37.2% / −28.4% |
| 2022 | −14.1% | −21.5% | −13.5% | −29.1% | −21.3% | −46.4% / −40.3% |
| 2025–26 | −19.5% | −22.2% | −19.5% | −22.2% | −12.3% | −45.9% / −45.8% |
| sessions ≥10% below peak | 38% | 35% | 24% | 31% | 39% | 68% / 68% |
| sessions ≥20% below peak | 14% | 14% | **0%** | 12% | 24% | 48% / 34% |

### What we learn

1. **The 2016–26 grid does not generalize, and that is the finding.** `lg8_semi_trail` was the
   grid's champion at 31.75% and §2.5 `proven`; on 2007–2026 it makes 9.45%, below the index.
   `lg12_semi_trail_vt` was 23.00%; here 10.51%. Same code, same cells, one stamp — the decade
   was the return. Learning 40 said a full-window number needs a sub-window cut before it is a
   finding; this is the converse and it is worse: a sub-window number that was never shown the
   other decade was never a finding at all. The cell of record is the only cell in this repo
   whose return survives 2007–2015, and it does so on the honest fill convention (next open)
   while every arm here fills at the deciding close — so the gap is understated, not overstated.
2. **The park decides 2008 for every mechanism, not just the gate.** A against B and C against D
   are the same book with the park swapped: −28.9% against −55.8%, −8.2% against −55.2%. The
   governor sells into the park and the gate sends everything to the park, and in 2008 the park
   was the S&P 500. A24 said a bill park protects gated-off capital and nothing else; under a
   governor it protects governed-off capital too, and under a SPY park neither mechanism protects
   anything in a crash that the index is having.
3. **The gate on top of the governor is worth having only with a bill park.** With SHV it halves
   the worst drawdown again (−28.9% → −19.5%, 2008 from −28.9% to −8.2%) for 1.2 CAGR points,
   and C never once sat 20% below its peak in twenty years. With SPY it removes nothing in 2008
   (−55.8% → −55.2%) and whipsaws 2020 and 2022 worse (−30.8% → −33.9%, −21.5% → −29.1%).
4. **The bill park costs more here than in A24**, 3.3 and 4.9 CAGR points against A24's 1.86,
   because a trail-and-governor cell is in the park far more often — 419 trail stops and 60
   governor sales in A, each parking its proceeds until the next rebalance — so the recovery it
   forgoes is larger. A24's price was a price for the cell of record; this is the price for a
   cell that parks constantly.
5. **The current episode is the smooth cell's worst in twenty years.** C's maximum drawdown is
   dated 2026-07-02, not 2009; both SHV arms sit 18.7% below their July peak at 2026-09-01 while
   the SPY arms sit 4.4% below. The 2025–26 momentum crash is the worst season a governed,
   gated, bill-parked book has seen since 2007, and it is the season the live book seeded into.

### The predictions, scored

1. *Trail-plus-governor cuts 2007–09 far below −60%.* Half right: true under SHV (−28.9%,
   −8.2%), false under SPY (−55.8%, −55.2%). The mechanism was not the governor. It was the park.
2. *The gate adds little on top of the governor.* Wrong under SHV — it took 2008 from −28.9% to
   −8.2% and the full-window drawdown from −28.9% to −19.5%. Right under SPY, for the wrong
   reason: it added nothing because there was nowhere safe to send the money.
3. *The bill park lowers drawdown and CAGR together, by less than in A24.* Direction right,
   magnitude wrong — by more, not less (point 4).
4. *`lg8_semi_trail` draws 40–60% in 2007–09.* Wrong: −27.9%, with a bill park catching its
   stop proceeds. Its worst episode is the 2010s (−35.3%, 2012-01-03), and its return over the
   window is 9.45%.

### Gates, as run

Conformance OK on all five. `finding.py`: **UNPROVEN on all five** — deflated Sharpe 0.151 to
0.215 against the 0.95 bar, 471 to 475 trials logged; the comparisons between arms are valid
(one stamp, one window, one calendar), the absolute claim of any arm is not. `verify_run`:
A 11 of 16 (B1 ghost fills, B4 two probable foreign listings, B7 seven twin pairs, C2, D1
fifteen concurrent names on one 2010 rebalance day); B, C and D 12 of 16 (B1, B4, B7, C2);
E 14 of 16 (B7 six twin pairs, C2). C2 is the one to read: every entry in this family fills at the deciding close, the one-bar advantage
the strategy claims not to take, and the cell of record does not take it. Every CAGR above is
therefore an upper bound on the cell it names. The dispatch step exits non-zero on any failed
check by design.

### What this means for the question

The highest return whose worst case a person can hold, on this repository's evidence, is the
cell of record with a bill park: 24.2% a year, worst drawdown −45.8%, 2008 at −21.8% (A24). The
−45.8% belongs to 2025–26, the episode the live book is in now, and no mechanism tested here
removes it without removing the return with it. A cell that stays inside −35% and still doubles
the index does not exist in this repo's grid; every smoothing mechanism tested buys its drawdown
with return, roughly one for one. Five more trials are logged (475). The freeze question stands,
and this result is an argument for it: the next cell searched for is another trial against a
bar that four grids have not cleared.

Not a promotion; not a demotion. §3.1's three numbers stand, §3.7's park stands, and the ruling
A24 asked for — the mechanism, then the vehicle — is still Zak's to make.
