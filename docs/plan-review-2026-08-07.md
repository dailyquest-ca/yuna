# Plan review notes — 2026-08-07

*What the 08-07 work-order build changed, framed as questions for the plan. Not law, not a
proposal — a reading list for the next time the Project copy is opened.*

The build itself is in PR #7. This file is only the part that touches **the document**: lines that
are now true for the first time, lines that are now wrong, and behaviour that exists in code and
nowhere in the law.

---

## 1. Lines that were true on paper and false in the machine

Each of these was already law. None of them was running.

| § | The line | What was actually happening |
|---|---|---|
| §3.1 | "Jobs read it: only ruled names arm entry tickets" | Every reader asked `verdict in ('pass','fail')`. The desk writes `PASS`, `ESCALATE`, `QUARANTINE — …`. **68 rulings were invisible.** |
| §3.1 | Owner-cash quarantine — "marked on its bench row … never ticketed" | Nothing ever wrote the mark. Ruling 66 quarantined DLO and the nightly armed it the same night. |
| §3.1 | "PASS joins the bench" | `bench.approved` was set by hand, 30 rows of it, and wiped whenever `score` rebuilt a row. |
| §3.0 | Foreign issuers eligible "when FCF and market cap are expressed in one currency" | No FX pairs were pulled but USDCAD, so ~185 names were excluded rather than converted. TSM scored a P/FCF of 1.76×. |
| §4.1 | "FX — USDCAD **+ statement currencies for foreign filers**" | Only USDCAD. |
| §3.0 | "membership lists never drop a name the book owns" | `universe.is_holding` still said VRT (closed 8/5) and had never heard of NUE or RS (filled 8/4). |
| §4.9 | "the monthly backup commit provides activity" | The backup job had not run since its rename. Last dump: 2026-08-01. |

**The pattern is one thing, and it is worth naming in the plan somewhere:** every one of these is a
rule the document states and no line of code read. `docs/learnings.md` #21 says *a rule stored is
not a rule enforced* about config keys — it generalises. The plan is a specification, and nothing
in the build currently proves the specification is implemented. That is what the four new `check`
assertions are: acceptance queries that run every night instead of once.

## 2. Lines that are now wrong and want an edit

**§4.2's job table — `backup` | "1st Sat 14:00 UTC".** The guard is work-keyed now: it fires every
Saturday and backs up if the month has none. Same ruling §4.2 already applies to `ingest-universe`
and the R5 letter — `backup` was simply left behind. The table line should read like theirs.

**§2.5 — the owner-cash quarantine reads as temporary.** "…until the balance-sheet treatment
(TODO) prices it on cash the owners actually keep" implies every quarantine eventually clears. For
MELI and DLO that is true — the float is separable and a balance-sheet treatment would price it.
For **AXP, SCHW, AMP, APO, SYF** it is not: the credit book *is* the business, and no measurement
changes that. Zak's read on 2026-08-07: *"Quarantine makes it sound like they can be cleared at
some point, but I don't see how if that's just how they do their financials."*

Two questions for the document, and they are separable:

1. Should structurally-float businesses be **evicted** rather than quarantined? §3.1 currently
   keeps "Credit Services, Capital Markets and the rest of Financial Services" eligible on purpose
   (EBITDA is meaningful for fee businesses), and says quarantined names stay "scored, ranked,
   watched". Evicting them contradicts both. **Worth the edit:** a permanently-unbuyable name
   holds a seat on a 60-name bench.
2. If they stay, should §3.1 distinguish *structural* from *pending measurement*? One word on the
   bench row would let the brief stop implying a review that will never come.

## 3. Behaviour that exists in code and nowhere in the law

Mechanics-lane items (§5.8): none moves a plan-stated number, so none needed an announced edit.
Listed here because the plan is meant to be the thing a future reader learns the system from.

- **A hand dispatch is never guarded.** Every work-guard now reads the clock only when the clock
  started the run. Ruled by Zak 2026-08-07: *"I don't want a manual run to be thwarted by the
  day."* Candidate line for §4.2, beside the monthly-work guard rule it qualifies.
- **A non-urgent exit ships as a marketable limit** — 0.3% inside the last print, recomputed at
  placement (his 2026-08-06 mechanics ruling, extended from the exits he rules to the ones the
  machine concludes). Market survives for the three urgent cases: gap-through (§4.6 names it),
  gate-off (§3.3's crash protocol), and the unconfirmed hair-trigger. Candidate line for §4.5.
- **`briefs.session_date` means the market session an output serves**, derived from the newest bar.
  It used to be `now()::date` in UTC, which stamped the brief a session ahead of the market it was
  written for. Candidate line for §4.2's clock convention.
- **Escalation has a place to live.** §5.6 calls it "a question in the brief"; it is now a distinct
  payload field and brief section rather than a name buried on the unruled docket.
- **Verdicts are prose; jobs read them through one function.** `yuna_verdict()` /
  `v_rulings_latest`. Worth a line in §4.3 beside the `rulings` row, because it is now the contract
  between what a session writes and what a job can act on.

## 4. Consequences of §3.0's conversion the plan does not mention

Converting each statement at its own fiscal-period-end rate means **multi-year revenue growth for
a foreign filer is now measured in the currency we underwrite in.** That is correct — a local
grower whose currency halved has not compounded a USD shareholder's money — and §3.2 already names
the pathology from the momentum side ("EM ADRs whose EPS is inflation- or FX-flattered pass this
test mechanically").

But §3.1's engine cross-check reads that number, so **a name can change engine provenance on
conversion**, measured ↔ growth-derived, which moves its CCN and its guardrails. Nothing is wrong;
the plan simply does not say it anywhere, and the first weekly rank after the backfill will move
the bench more than usual.

*(EPS is deliberately left unconverted — M4 reads it as a YoY ratio where the currency cancels, and
§3.2 already routes FX-flattered EPS to the R3 workup as judgment.)*

## 5. The TODO that turned out to be load-bearing

§3.1 names a balance-sheet treatment that would "price it on cash the owners actually keep", and
the work orders parked it under *explicitly not in this package*.

**It is the only way the float test becomes computable.** Measured on the live bench — the
working-capital share of reported FCF, which is the signal we store:

| marked as float businesses | | ordinary names | |
|---|---|---|---|
| APO | 136% | MEDP | 16% |
| MELI | 59% | HLNE | 12% |
| AXP | 6% | MA | 4% |
| SYF | −3% | BKNG | 4% |
| HQY | −5% | INTU | −8% |
| PCTY | −14% | SPGI | −10% |
| AMP | −97% | DOCS | −14% |
| SCHW | −108% | | |

The two columns are the same distribution. Schwab reads as *less* float-driven than a contract
research organisation. The reason is structural: for a lender or a broker the customer money is
deposits and the loan book, which live on the balance sheet, and every figure we extract comes off
the cash-flow statement. The signal catches the marketplace-with-a-wallet class and is blind to the
class that matters most.

So the honest position, and the one worth recording in the plan: **until the balance-sheet
treatment exists, the quarantine is a judgment the ledger remembers, not a fact the machine
recomputes.** Zak's objection on 2026-08-07 — *"the refresh should be able to find that information
as well and reassess them the same way"* — is right in principle and blocked in practice, and the
block has a name and a place in the document already.

## 6. Small things worth a sweep

- **`config.score_thresholds.enter` was never read.** The code asked for `enterable` and fell
  through to the same 70 by luck, so the stored row was decorative. Fixed — but it was found by
  accident, and nothing systematically checks that every config key has a reader. That is
  learnings #21 from the other side, and it wants a test rather than a habit.
- **`book.sleeve = 'unassigned'` on three open positions** (AVGO, ISRG, TSM). Sleeve exposure in
  the arming stage sums by sleeve, so an unassigned holding counts toward neither ceiling. Phase 0
  Step 2a owns this; noted because it silently understates both sleeves.
- **The `armed` ledger is append-only**, so any acceptance query written as `select … from armed`
  keeps counting last week's rows forever. Use `v_armed_latest`.
