# WO-A29 — The park ladder

*Pre-registered 2026-09-03, before any arm was dispatched. Zak: "Run this comparison against the
likeliest 5-10 other park options."*

## The question

A24 showed that the park decides the gated-off episodes: bills against SPY took the cell of
record's 2007–09 from −60.3% to −21.8% for 1.86 CAGR points. A25 showed the same for the governor
on a different cell. Bills are the floor of the ladder, the park with no market exposure at all.
The question is whether any instrument with SOME exposure does better than bills in the seasons
the sleeve is off, without giving the protection back in another season.

## The claim, fixed in advance

**A park is preferable to bills only if, on the cell of record and A24's window, all three hold:**

1. its 2007–09 peak-to-trough is no worse than the bill park's −21.8%;
2. it is not worse than the bill park by more than 5 points in any of the other four episodes;
3. its CAGR is at least the bill park's 24.22%.

A park that fails clause 2 helps in one crash and hurts in another, and the plan cannot know
which crash comes next. That is the whole reason bills are the floor.

## The rungs

Eight instruments, every one with vendor bars before the first decision on 2007-01-12, each one
dispatch of `b5_12_2_L1_3` with `park=<ticker>` and everything else A24's (`calendar=SPY.US`,
`start_date=2006-01-10`, `start_nav=100000`):

| rung | what it is | why it is on the ladder |
|---|---|---|
| `TLT.US` | 20+ year Treasuries | the classic crash hedge (2008, 2020) and the classic 2022 casualty |
| `IEF.US` | 7–10 year Treasuries | the same bet with half the duration |
| `AGG.US` | US aggregate bonds | bonds without the duration bet |
| `LQD.US` | investment-grade corporates | credit: paid a spread, sold off in the 2008 credit crash |
| `TIP.US` | inflation-protected Treasuries | the 2022 case |
| `GLD.US` | gold | the crisis asset that is not a bond |
| `XLU.US` | utilities | the defensive equity sector |
| `XLP.US` | consumer staples | the other defensive equity sector |

Not on the ladder: commodities (DBC lost a third in 2008; no case), foreign equity (EFA, EEM fall
with the crash), BIL (bills, first bar 2007-05-30; SHV already covers it), real estate (VNQ, 2008).

## Predictions, written before the runs

1. TLT posts the best 2007–09 of the ladder and fails clause 2 on the 2022 episode by more than
   5 points.
2. No rung passes all three clauses. Bills stay the research park.
3. GLD is the rung most likely to pass all three. If it does, that is one instrument's best two
   decades since the 1970s and not a mechanism, and the write-up must say so.
4. XLU and XLP behave like a diluted SPY park: better than SPY in every episode, worse than bills
   in 2007–09 by more than 10 points.

## The dynamic park, deliberately not run here

A park that is itself a rule, holding whichever rung has the best trailing six-month return, is
a code change and a separate work order. This ladder is its prerequisite: if no static rung
dominates the episodes, the dynamic park has a case; if bills dominate, it does not.

## Data

Migration 065 registers the eight as `kind='index'`, `in_l0=false`: reference data, never
candidates, unseen by §3.2's universe and by `desk.PARKED`, exactly as 043 and 063 registered
SPY, SPMO and SHV. Bars are backfilled from the vendor and each rung's first bar is verified to
precede 2007-01-12 before dispatch, so A24's park-start confound cannot recur.

## Gates and trials

As A24 and A25: `finding.py`, `capture_audit.py`, `verify_run.py`; learning 40's episode cut
before any full-window number is called a finding. Eight more trials. The comparisons between
arms are valid on one stamp and one window; no arm carries an absolute claim.

## Result — 2026-09-03, runs 643 to 650

Eight rungs on code stamp `55353058db496b93`, A24's window, start NAV $100,000, two at a time.
The sleeve is untouched: **748 trades in every arm with an identical exit mix**, so every
difference below is the park's and nothing else's. Controls are A24's runs 623 (bills) and 624
(SPY) on stamp `473a07e6a060dcf1`; the stamp change cannot be worth more than the 0.03 CAGR
points it was worth on the same cell in WO-A31. Episodes are the 2007-01-01 to 2009-12-31 cut
and its siblings.

| park | CAGR | maxDD (date) | 2007–09 | 2010s | 2020 | 2022 | 2025–26 | ≥20% below | end NAV | Sharpe | DSR | clauses |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY (624) | 26.08% | −60.3% (2009-03) | −60.3% | −50.0% | −37.2% | −46.4% | −45.9% | 47.6% | $9.46M | 0.78 | 0.210 | — |
| **bills, SHV (623)** | 24.22% | −45.8% (2025-11) | −27.3% | −37.5% | −28.4% | −40.3% | −45.8% | 34.3% | $7.07M | 0.78 | 0.205 | the floor |
| IEF (643) | 25.77% | −45.8% (2025-11) | −23.9% | −35.5% | −28.4% | −45.7% | −45.8% | 27.6% | $9.03M | 0.81 | 0.263 | 2 fails by 0.4 (2022) |
| TLT (644) | 25.42% | −55.7% (2022-10) | −31.5% | −36.0% | −28.5% | −55.7% | −45.9% | 28.7% | $8.54M | 0.79 | 0.237 | 1 and 2 fail |
| AGG (646) | 25.08% | −45.8% (2025-11) | −27.3% | −35.8% | −28.4% | −45.4% | −45.8% | 30.3% | $8.10M | 0.79 | 0.245 | 2 fails by 0.1 (2022) |
| LQD (645) | 25.11% | −48.5% (2022-10) | −34.9% | −34.6% | −32.8% | −48.5% | −45.9% | 32.1% | $8.14M | 0.79 | 0.238 | 1 and 2 fail |
| **TIP (647)** | 24.73% | −45.8% (2025-11) | −26.9% | −36.3% | −28.4% | −42.8% | −45.8% | 33.7% | $7.67M | 0.79 | 0.235 | **all three pass** |
| GLD (648) | **28.56%** | −46.9% (2022-09) | −33.4% | −35.1% | −28.5% | −46.9% | −45.9% | **25.8%** | **$13.88M** | **0.85** | **0.330** | 1 and 2 fail |
| XLU (650) | 26.54% | −54.5% (2009-03) | −54.5% | −48.0% | −41.2% | −44.8% | −46.0% | 42.0% | $10.17M | 0.80 | 0.253 | 1 and 2 fail |
| XLP (649) | 26.89% | −46.3% (2022-10) | −42.6% | −36.0% | −31.1% | −46.3% | −45.9% | 31.2% | $10.74M | 0.82 | 0.282 | 1 and 2 fail |

**Against the claim: one rung passes, and it passes by less than a point on every clause.** TIP
beats bills by 0.4 points in 2007–09, by 0.5 points of CAGR, and is 2.5 points worse in 2022.
That is a tie with bills, not a preference, and it is read as one. Prediction 2 said no rung
would pass; it was wrong by four tenths of a point.

### What we learn

1. **2022 is the ladder's referee.** Every bond rung that wins 2008 loses 2022: IEF and AGG beat
   bills in 2007–09 and on CAGR and fail clause 2 by 0.4 and 0.1 points, on 2022 alone. TLT wins
   nothing and loses 2022 by fifteen. Clause 2 exists because the plan cannot know which crash
   comes next, and 2008 against 2022 is exactly the pair of crashes it was written for.
2. **Gold is the best park on every number but the two that matter.** 28.56% a year, the highest
   CAGR of anything this repository has run, twice bills' terminal wealth, the lowest share of
   sessions 20% below the high, the ladder's best Sharpe and deflated Sharpe. And −33.4% in
   2007–09 against bills' −27.3%, −46.9% in 2022 against −40.3%. The pre-registered caveat holds
   in full: 2007–2026 was gold's best two decades since the 1970s, and a park that rides that is
   one instrument's run, not a mechanism.
3. **The park is the largest lever in the system, again.** With the sleeve pinned at 748
   identical trades, the parks span 24.2% to 28.6% of CAGR and −45.8% to −60.3% of drawdown. The
   four sleeve-side mechanisms of A30–A33 spanned 17.5% to 26.1% with different trades and never
   moved the worst episode down. Where the money sits when it is not in stocks decides more than
   how the stocks are chosen.
4. **No park touches 2025–26.** Every rung reads −45.8% to −46.0% on the current episode, because
   the gate was ON throughout and the park was empty. That number belongs to the sleeve, and
   only residual momentum has moved it (A30, −34.6%, at 6.4 points of CAGR).
5. **The defensive sectors are diluted SPY.** XLP and XLU beat SPY in 2007–09 and the 2010s and
   are worse than bills there by 15 and 27 points; XLU is worse than SPY in 2020. Prediction 4
   was right for XLP and half right for XLU.

### The predictions, scored

| prediction | outcome |
|---|---|
| 1. TLT posts the ladder's best 2007–09 and fails clause 2 on 2022 by more than 5 | half: it fails 2022 by 15.4; its 2007–09 (−31.5%) is the fourth best, behind IEF, TIP and AGG |
| 2. No rung passes all three | wrong by four tenths: TIP passes every clause by less than a point |
| 3. GLD is the rung most likely to pass all three | wrong: it fails clauses 1 and 2 by 6 points each; its CAGR is the ladder's best, as the caveat foresaw |
| 4. XLU and XLP: better than SPY in every episode, worse than bills in 2007–09 by more than 10 | XLP right; XLU right on 2007–09, wrong on 2020 |

### The dynamic park, now with a case

No static rung dominates: bonds win 2008 and lose 2022, gold wins the 2010s and 2020 and loses
2008 and 2022, bills lose nothing and win nothing. That is the precondition the pre-registration
set for a park that is itself a rule, holding whichever rung has the best trailing six months.
It is a code change, a second momentum rule inside the first, and one more trial; it is filed as
a candidate work order behind the freeze ruling, with its threshold declared before it runs.

### Gates, as run

Conformance OK on all eight. `finding.py` UNPROVEN on all eight (DSR 0.235 to 0.330). `verify_run`
14 of 16 on seven rungs, failing B4 and B7 only, the two tape properties every A24-window run
carries; 13 of 16 on TLT, whose series lacks one vendor bar (2023-04-06) that the sim carries
forward — cosmetic, and named. Eight more trials: 491. Nothing here is a promotion; §3.7's park
is SPY until Zak rules, and A24's vehicle note stands for whatever is promoted.
