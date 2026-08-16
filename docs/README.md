# docs — what to read, and what is no longer true

`README.md` at the repo root says **three documents, and only three**. That is still the rule. This
file exists because everything else in this directory is *dated evidence*, and dated evidence goes
stale in a particular way: it keeps stating its conclusion long after a later run overturned it.

**A document here is not wrong because it is old. It is wrong because something later measured
better.** Where that has happened it is marked below, and the file itself carries the same note at
the top. Read the marker before you act on the number.

---

## The three

| | |
| --- | --- |
| [`yuna_plan.md`](yuna_plan.md) | **The law.** Where anything else disagrees, the plan wins. |
| [`roadmap-2026-07-31.md`](roadmap-2026-07-31.md) | **The build order** — what is done, what drifted, what comes next. |
| [`learnings.md`](learnings.md) | **The scar tissue.** Facts this build paid for. Read before touching anything. |

Nothing else in this directory is instruction. All of it is record.

---

## The momentum research programme (2026-08-12 → 2026-08-15)

Read these three and stop:

| document | what it is |
| --- | --- |
| [`wo-a20-v2-decision.md`](wo-a20-v2-decision.md) | **The current strategy of record.** V2 — entry band 2, exit band 12, regime gate with a 1/3 latch. Research complete; **not adopted**. Adoption is a plan amendment. |
| [`wo-a18-programme-record.md`](wo-a18-programme-record.md) | **The history.** Everything tried, every ruling, every number, in the order it happened. Where an earlier document conflicts with this one, this one is later. |
| [`wo-a22-cell-of-record-audit.md`](wo-a22-cell-of-record-audit.md) | **The cell of record, audited.** Run 589 passes 13 of 16 checks — every headline verifies to the digit, the tape is clean — and fails three, all about which names were in the book. Read before quoting §3.1. |
| [`wo-a21-merge-plan.md`](wo-a21-merge-plan.md) | **The merge plan.** What of this branch is safe on `main`, in what order, and what must not go until the plan is amended. |

### Superseded — do not act on the recommendation

| document | still good for | its conclusion is wrong because |
| --- | --- | --- |
| [`wo-a15-v1-synthesis.md`](wo-a15-v1-synthesis.md) | the reproduction spec, and §5's merge conditions | it names the wrong cell, chosen on a tape whose discontinuity guard was blind below $1 and across trading gaps |
| [`wo-a17-regime-synthesis.md`](wo-a17-regime-synthesis.md) | the clean-tape grid, and the finding that 0 of 25 cells made money 2007–2017 | that finding is true of 25 **ungated** cells; §3's framing was too broad, and its §3.1 decomposition lays separate runs end to end |
| [`wo-a13-decision-sheet.md`](wo-a13-decision-sheet.md) · [`wo-a12-gaps-and-rulings.md`](wo-a12-gaps-and-rulings.md) | the gap inventory and the rulings Zak made on it | their recommendations were superseded by WO-A15, then twice again |
| [`synthesis-2026-08-14.md`](synthesis-2026-08-14.md) · [`arms-2026-08-12.md`](arms-2026-08-12.md) | the arms as measured on the day | pre-dates the tape screen, the stable sort, and next-open fills |

### The work orders, in order

Pre-registration matters here: several of these were written *before* the cells in them ran, which
is what makes their results admissible under `backtest-protocol`.

| | |
| --- | --- |
| [`wo-e-series-2026-08-12.md`](wo-e-series-2026-08-12.md) | the E-series — Micron, slot ordering, the conformance clause |
| [`wo-a3-2026-08-13.md`](wo-a3-2026-08-13.md) | blends, the push study, the A3 family |
| [`wo-a5-2026-08-13.md`](wo-a5-2026-08-13.md) | the concentrated arm, **pre-registered** |
| [`wo-a6-2026-08-14.md`](wo-a6-2026-08-14.md) | replacing the calendar with a condition, **pre-registered** |
| [`wo-a6-banded-2026-08-14.md`](wo-a6-banded-2026-08-14.md) | Zak's banded continuous book, filed verbatim as issued |
| [`wo-a7-2026-08-14.md`](wo-a7-2026-08-14.md) · [`wo-a8-2026-08-14.md`](wo-a8-2026-08-14.md) · [`wo-a9-2026-08-14.md`](wo-a9-2026-08-14.md) | sensitivity, the `w10_n5` forensics, the stabilisers |
| [`wo-a10-2026-08-14.md`](wo-a10-2026-08-14.md) | the regime clause, from Zak's ruling |
| [`wo-a11-daily-desk-spec.md`](wo-a11-daily-desk-spec.md) | the daily desk — **specification only, no code exists** |
| [`wo-a16-foreign-listings.md`](wo-a16-foreign-listings.md) | foreign securities carried on `.US` tickers, and the participation gate built for them |

### The defect record

[`wo-a16`](wo-a16-foreign-listings.md) and WO-A18 §2 between them carry the seven tape-integrity
defect classes found while verifying this programme. Four were fixed outright; `src/verify_run.py`
now audits every run against all of them, and `src/backtest.py` asserts against `market-mechanics`
on every run. **The audit gates the build — a failed audit fails the workflow.**

---

## Earlier record — the build, the trials, the incident

Kept because they are the evidence behind rulings that are still in force. None of it is current
instruction.

| | |
| --- | --- |
| [`backtest-findings-2026-08-10.md`](backtest-findings-2026-08-10.md) | momentum measured against its own law — **read this, not the 07-31 file** |
| [`backtest-findings-2026-07-31.md`](backtest-findings-2026-07-31.md) | ⚠️ measures a rule §3.2 has since repealed; 211 of 296 trades entered below MCN 70, which the law forbids |
| [`backtest-plan-2026-08-10.md`](backtest-plan-2026-08-10.md) · [`backtest-spec-review-2026-08-10.md`](backtest-spec-review-2026-08-10.md) | the backtest as a standing instrument, and the review that shaped it |
| [`results-2026-08-02.md`](results-2026-08-02.md) · [`acceptance-2026-08-01.md`](acceptance-2026-08-01.md) | state of the system, and the full-cadence acceptance pass |
| [`scan-2026-08-01.md`](scan-2026-08-01.md) · [`build-plan-2026-08-01.md`](build-plan-2026-08-01.md) · [`dev-fixes-2026-08-01.md`](dev-fixes-2026-08-01.md) | the 08-01 law change: the scan, the plan that closed it, the fix list |
| [`coverage-2026-07-31.md`](coverage-2026-07-31.md) | every §2 and §3 rule against the code and the test that pins it |
| [`vetting-2026-08-01.md`](vetting-2026-08-01.md) · [`vetting-hurdle-2026-08-02.md`](vetting-hurdle-2026-08-02.md) · [`trial-audit-2026-08-01.md`](trial-audit-2026-08-01.md) | the compounder side — scores, the entry hurdle, and the adversarial brief teardown |
| [`r5-2026-07-31.md`](r5-2026-07-31.md) | the monthly approval that needed ten C2 rulings |
| [`plan-review-2026-08-07.md`](plan-review-2026-08-07.md) | what the 08-07 build changed, framed as questions for the plan |
| [`incident-2026-08-03.md`](incident-2026-08-03.md) | production database down, disk full — resolved, and why |
| [`research-2026-08-13.md`](research-2026-08-13.md) · [`session-2026-08-12.md`](session-2026-08-12.md) · [`session-2026-08-13.md`](session-2026-08-13.md) · [`handoff-2026-08-13.md`](handoff-2026-08-13.md) | working notes and handoffs — the least durable things here |

---

## If you add a document

Date it, say at the top what it supersedes, and add a row here. The failure mode is not a document
going out of date — that is inevitable. It is a document going out of date *silently*, so a reader
acts on a number a later run has already overturned. Both cases in this directory that would have
cost something were caught by a note the author put at the top of the file
([`backtest-findings-2026-07-31.md`](backtest-findings-2026-07-31.md) measuring a repealed §3.2 rule,
and [`wo-a15-v1-synthesis.md`](wo-a15-v1-synthesis.md) naming a cell chosen on a defective tape).
Write the note when you write the successor, not later.
