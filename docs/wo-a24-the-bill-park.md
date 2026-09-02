# WO-A24 — The bill park

*Pre-registered 2026-09-02, before either arm was dispatched. §7's own work order: "Park is SPY
per the cell of record; a T-bill park variant is a research work order, promoted only on
evidence."*

## The question

§3.8, quoted with the engine always: *"The park is SPY: gated-off capital rides the index down
(2008 modeled: −37.3% while gated)."* The repo has measured how much of the account the park
holds and said so in four places — `backtest.py`: *"A1V ran 74% of the account parked, so the
vehicle it sits in decides more of the return than the sleeve does"*; `desk.py`: *"~60% of the
account never leaves the park"*; WO-A22: *"under a gate the park IS the return for every session
the book is off."* So the park is the highest-leverage axis in the system, and the plan's own
question about it has never been run: what does the cell of record do if gated-off capital sits
in bills instead of the index?

## The claim, fixed in advance

**The bill park is promotable only if it materially reduces the gated drawdown** — the 2008
figure §3.8 names and the full-window maxDD (−61.2% in WO-A18's table for this cell) — **at a
CAGR cost Zak rules acceptable.**

A CAGR *improvement* is not the claim, and would be a red flag: bills underperform the index over
nineteen years, so a bill park that raises CAGR is the window doing the work, not the park. The
number this WO is allowed to be excited about is the drawdown. Nothing else.

## The arms

Two dispatches of `backtest.yml`, `research=concentrated`, identical in every input but one:

| | control | bill park |
|---|---|---|
| `cells` | `b5_12_2_L1_3` | `b5_12_2_L1_3` |
| `park` | `SPY.US` | **`SHV.US`** |
| `calendar` | `SPY.US` | `SPY.US` |
| `start_date` | computed, see window | same value |
| `end_date` | blank (open) | blank (open) |
| code | same commit | same commit |

The control is re-run rather than read from run 589, because WO-A23 records that a fresh run no
longer reproduces stamp `235bef5fd174dcab`, and because the window below is not 589's. Two runs
on one commit share a `code_stamp`; a comparison across differing stamps was never valid.

## The window

`concentrated.py` does not halt on a park that starts after the window opens. It loads the park
over its whole history and guards every use with `np.isfinite(park_px[i])` — so on a session with
no park bar the sim cannot enter, park, gate or rebalance, and the arm that lacks the bar simply
sits. That would be a confound dressed as a result. Both arms therefore open on the same computed
`START_DATE`: the SPY session 253 sessions before 2007-01-12, so that the first decision session
(`i = warmup = FORMATION + 1 = 253`) is 2007-01-12 — one session inside SHV's history, whose first
vendor bar is 2007-01-11. The value is recorded in each run's `params.window`.

Cost against run 589's window: the first week of January 2007. Nothing of 2008 is lost.

## What this is not

**It is not a production recommendation, and SHV is not the production vehicle.** Two facts, both
Zak's to rule:

- SHV is US-domiciled and the engine lives in the TFSA (§2.1). `.claude/rules/investment-tax.md`:
  *"US dividend withholding is treaty-exempt in an RRSP and is not in a TFSA."* A Canadian-listed
  USD cash fund — `PSU-U.TO` (live 2018-02-28, pinned $100.00–100.09, adjusted close 79→100 in
  eight years, i.e. pure accrual), `HISU-U.TO` (2022-08-30), `UCSH-U.TO`, `MUSD-U.TO` — is the
  same accrual with no withholding and no FX round-trip. None reaches 2008. **The sim parks in
  SHV to measure the mechanism; production, if the mechanism is promoted, picks the vehicle.**
  That is a §3.7 / §8 change and a ruling.
- `CASH.TO` and its CAD siblings are the wrong instruments for a USD engine regardless of the
  result: two currency conversions per gate cycle and USDCAD risk while parked.

Why an ETF and not 043's `bill_rates`: the rates reach only 2016-01-04 and cannot see 2008, and
043 deliberately refused to pick the tenor, accrual and holiday-fill in code — *"a plan gap for
Zak, not a default to be picked in code."* An ETF's adjusted close carries all three inside the
price, so the sim assumes nothing. BIL.US (1–3 month) is the purer bill instrument and starts
2007-05-30; SHV.US (under one year) starts 2007-01-11 and is used for the four months of reach.

## Gates

The dispatch runs `finding.py` (fails closed when the window cannot support the claim) and
`capture_audit.py` on every run; `verify_run.py`'s sixteen checks are available after. Learning 40
applies: a full-window comparison is one number, and a sub-window cut is owed before any of it is
called a finding.

**Caveat on standing.** `momentum-strategy@dq-investing` is enabled in `.claude/settings.json`
but its `backtest-protocol` skill was not loadable in the session that wrote this, so the upstream
rules could not be certified against. What runs here is the repo's own standard. A result from
this WO is a repo-standard finding until the upstream protocol has been applied to it.

## Standing

`SHV.US` is registered by migration 063 as `kind='index'`, exactly as 043 registered SPY and SPMO:
a measuring instrument, never a candidate, unseen by §3.2's universe and by `desk.PARKED`. It is
reference data until a ruling changes §3.7. Nothing here joins the pipeline schedule.
