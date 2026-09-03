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
