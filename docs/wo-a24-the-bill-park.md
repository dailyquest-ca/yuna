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

**One asymmetry survives that choice, and it is proved inert rather than patched.** The gate's
carried state is advanced by `regime_latch()`, and that call sits behind the same
`np.isfinite(park_px[i])` guard as the action. So through warmup the SPY arm evaluates the latch
every session while the SHV arm's `regime_state` never moves; the two enter the first decision
with different streak histories. On this window it cannot matter: `regime_latch` sets
`on = ok_now` on its first evaluated session, and on 2007-01-12 `ok_now` is True for both arms
(SPY above its 200-day since well before, `confirm_in = 3` met by i = 202 in the SPY arm), so
both hold `on = True`. Under `confirm_out = 1` the differing `up` streaks (≈54 against 1) cannot
change any later verdict, because one down session zeroes `up` and flips the latch in both arms
alike. A future park experiment whose first decision falls inside a bear market does NOT get this
proof for free: move the state update outside the park guard first, and leave the action inside
it. That patch is behaviour-identical for every stored cell, whose parks are finite throughout.

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

## Result — 2026-09-02, runs 624 (SPY park) and 623 (SHV park)

Both on code stamp `473a07e6a060dcf1`, window `2006-01-10..open` (first decision 2007-01-12,
last 2026-09-01, 4,940 sessions), start NAV $100,000 to match run 589. **The sleeve was untouched:
748 trades in each arm with an identical exit mix — gate_off 175, displaced 211, rank_band 357,
open at end 5.** Only the park moved, which is the whole design.

| | SPY park (control) | SHV park | delta |
|---|---|---|---|
| CAGR | 26.08% | 24.22% | −1.86 pts |
| Full-window maxDD | −60.3% (2009-03-09) | −45.8% (2025-11-21) | +14.5 pts |
| End NAV | $9,463,000 | $7,068,350 | −25.3% |
| Conformance | OK | OK | |
| `finding.py` §2.5 (DSR · z · trials) | 0.210 · −0.81 · 470 | 0.205 · −0.82 · 470 | |
| OOS Sharpe, 2025-08 → open | 1.58 | 1.52 | |

Peak-to-trough by episode, the cut learning 40 asks for before a full-window number is called a
finding — five episodes, one sign:

| episode | SPY park | SHV park | delta |
|---|---|---|---|
| **2007–09** | **−60.3%** | **−21.8%** | **+38.5 pts** |
| *same row, 2007-01-01 to 2009-12-31 cut* | *−60.3%* | *−27.3% (2009-10-28)* | *+33.0* |
| worst of the 2010s | −50.0% | −37.5% | +12.5 |
| 2020 | −37.2% | −28.4% | +8.8 |
| 2022 | −46.4% | −40.3% | +6.1 |
| 2025–26 (2025-11-21) | −45.9% | −45.8% | 0.1 |

**Against the pre-registered claim: met, decisively.** The gated drawdown falls in every gated
episode; 2008 falls by 38.5 points. CAGR fell, as it was expected to — no red flag. The one
episode the park does not touch is 2025–26, and that is the proof of mechanism rather than a
failure of it: the gate was ON through that drawdown, so the book held stocks and the park was
empty. **A bill park protects gated-off capital and nothing else.** §3.8's other limitation —
"a −61% drawdown has never been tested against a human" — is now a −46% drawdown that the park
cannot shorten, because it belongs to the sleeve.

Where the CAGR went: the SPY park rides back up as well as down. From the 2009 trough to the 2009
year-end high the control multiplied 2.52×; the bill arm 1.37×. The bill park forgoes the
gated-off stretch's recovery along with its loss, and over nineteen years that is 1.86 points a
year and a quarter of terminal wealth. That is the price, stated as a price.

Two reading notes. §3.8's "−37.3% while gated" (run 589, window opening 2007-01-05) is a
gated-only slice; the −60.3% above is the whole 2007–09 episode including the sleeve's own losses
before the gate went off, and is the number a human lives through. They do not contradict.
And `backtest_equity.gate` is NULL for `concentrated` runs, so the gated-only slice cannot be
recut from the stored curve; the exit counts carry the gate's footprint instead.

**Standing of this result:** repo-standard. Conformance and `finding.py` are green on both arms;
the sixteen-check `verify_run` audit ran on both as part of the dispatch (its verdict is recorded
below). The upstream `backtest-protocol` skill was not loadable in the session that ran this, so
the result is not certified against it. Promotion is Zak's ruling (§7), and would be two rulings,
not one: the mechanism (§3.7's park leaves SPY) and the production vehicle (a Canadian-listed USD
cash fund, not SHV — see "What this is not").

**Gates, as run.** `finding.py` returns **UNPROVEN on both arms** — deflated Sharpe 0.210 (SPY)
and 0.205 (SHV) against a 0.95 bar, 470 trials logged. That is the verdict the cell of record has
always carried (WO-A18 calls `b5_12_2_L1_3` unproven on exactly this bar), and it is unchanged by
the park: the comparison between the arms is valid, the absolute claim for either arm is not. Note
that `finding.py`'s "vs benchmark" line follows each run's park, so "+9368% vs +660%" (SPY) and
"+6972% vs +36%" (SHV) are not comparable across arms; the ex-top-3 lines (+5824% / +4273%, both
beating their benchmark) and the bootstrap CAGR bands (p5 +9.65% / +9.31%) are.

`verify_run` sixteen checks: **14 passed, 2 failed, identically on both arms.** B4 (three traded
names — RXDX, NBIS, AOI — miss more than 3% of sessions while listed, probable foreign listings)
and B7 (four pairs held concurrently as one security under two symbols — BBWI/LB_old1, BBBY/OSTK,
B/GOLD_old, CLVS/CLVSQ — so the book doubled a position while every cap counted it twice). Both
are properties of the cell of record's trades on this tape, not of the park: run 589 carried the
same B7 finding seven times (`engine.py` cites it), and §3.7(3)'s twin rule exists in the live
engine for that reason while this sim cell still admits the pairs. The 748 trades are the same in
both arms, so the bias is identical on each side and cancels in the delta; it stands as a caveat
on the absolute figures of both. The dispatch step exits non-zero on any failed check by design.

## Standing

`SHV.US` is registered by migration 063 as `kind='index'`, exactly as 043 registered SPY and SPMO:
a measuring instrument, never a candidate, unseen by §3.2's universe and by `desk.PARKED`. It is
reference data until a ruling changes §3.7. Nothing here joins the pipeline schedule.
