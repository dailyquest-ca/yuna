# Yuna — build plan to full plan-conformance

*Draft 1 · 2026-07-31 · against `docs/yuna_plan.md` (16:37 UTC stamp) and `docs/audit-2026-07-31-v4.md`.*

**Purpose.** Get the running system to do exactly what the plan says — no more, no less — at a
quality and security standard fit for a system that touches CAD 200K of real money.

**This plan is not the law.** `docs/yuna_plan.md` is. Where this document and the plan disagree,
the plan wins and this document is wrong.

---

## 0. Standing rules for every step

These apply to all work below and are not repeated per step.

**Definition of done.** A step is done when *all* of:
1. The clauses it claims are `wired` in `src/yuna/rules.py`, verified by the call-graph test —
   not asserted.
2. Tests exist that would fail if the rule were wrong, written against the **plan text**, not
   against the code's current behaviour.
3. `ruff`, `mypy` (for modules in the strict list), and `pytest` pass.
4. The change ran once in production with `DRY_RUN=true` and its heartbeat was inspected.
5. Anything the plan does not state, that the code now does, is recorded as a deviation in the
   ledger **and** raised in `docs/open-questions.md`.

**Never.** No step may: introduce a rule the plan does not state; widen a risk parameter; make a
job write a ticket that §4.3 reserves to sessions; or ship a behaviour change without a test that
distinguishes old from new.

**Safety posture.** The system is live. The book is seeded, Phase 0 tickets sit in `proposed`,
and the nightly runs against real data every weekday. Therefore:
- Every job change ships behind `DRY_RUN` first and is compared against the previous night's
  output before it writes.
- Migrations are applied only via the dispatch-only `migrate` workflow, never automatically.
- A migration that could lose data is preceded by a `monthly-backup` run, on demand.

**Commit discipline.** One work package per commit series; each commit builds green. The commit
message states what changed *and why the plan required it*.

---

## 1. Preconditions

### 1.1 Rulings needed before certain steps (see `docs/open-questions.md`)

| Ruling | Blocks |
|---|---|
| **D1** — theme is judgment, not sector; what does a job do meanwhile? | S7 theme cap |
| **Q7** — what growth the hurdle uses when the engine diverges | S4 hurdle |
| **Q8** — sequencing FX conversion with effective shares | S4 foreign issuers |
| **Q1** — TWR window and observation cadence | S10 performance line |
| **Q4** — legal ticket state transitions | S9 fill loop |
| **Q5** — quarantine thresholds | S3 write path apply |
| **Q6** — CNQ / levered single-name eligibility | S8 leverage |
| **§4.3 vs §2.0/§5.4** — may a session write `balances`? | S3 write path apply |

Everything not listed proceeds without waiting.

### 1.2 Environment work

- A throwaway Postgres in CI (service container) so migrations and SQL can be tested at all.
- A restore procedure, written down and rehearsed once against a scratch Supabase project.

---

## 2. The steps

Ordered by dependency. Each step lists what it closes.

### S0 — Test the database, or nothing else is verifiable

*Nothing in this repo has ever executed a line of SQL under test — including the 1,462-line
session write path.*

1. CI gains a `postgres:17` service container.
2. A `tests/db/` suite that: applies every migration in order to an empty database; asserts the
   resulting schema (tables, columns, types, constraints, indexes); asserts the guard triggers
   refuse a write from a non-migrator role; asserts every view's column list matches expectation.
3. A migration-idempotency test: applying all migrations twice must succeed and produce an
   identical schema.
4. Mark these `@pytest.mark.db` and skip when no `TEST_DATABASE_URL` is present, so local runs
   stay fast and CI runs them.

**Why first:** every later step touches schema or SQL, and none of it is currently testable.

**Closes:** no plan clause. Enables everything.

### S1 — Schema defences (migration 019)

1. `CHECK` constraints on every state machine the schema currently records as a comment:
   `tickets.state`, `tickets.action`, `book.sleeve`, `book.status`, `runs.status`,
   `candidates.state`, `queue.state`, `accounts.kind`.
2. `security_invoker = true` on all six views, plus explicit `revoke` from `anon`/`authenticated`.
3. `v_fundamentals_latest` rebuilt with an explicit column list — the `select *` that already
   broke this system once.
4. A `prices` sanity constraint: `high >= low`, `high >= open`, `high >= close`, all positive.
5. `transactions` gains its writer path (schema is already correct; nothing writes it).

**Closes:** hardening; enables `4.3/guard-triggers` to mean what it says.

### S2 — Heartbeat honesty

1. `policy.domain_is_stale` replaces the inline status test in `daily.freshness`: `running` is
   stale, and a job with **no row at all** in its expected window is stale.
2. The freshness line learns the expected schedule, so silence is detectable.
3. `nightly-retry` re-runs the `daily` duties too — today the night the pipeline fails is the
   night with no stop sheet.
4. The autopsy step moves before `pip install`, or is made installation-independent, so a failure
   during dependency install still leaves a trace.

**Closes:** `4.7/stale-detects-silence`. Strengthens `4.7/heartbeat`, `4.7/stale-data-no-tickets`.

### S3 — Apply the session write path

Migration 018 is written and reviewed but **not applied**. Blocked on Q4, Q5 and the §4.3
`balances` question. Once ruled: apply, mint the scoped token, verify each verb end-to-end
against the S0 test harness.

**Closes:** `2.0/provisional-balances`. Enables `2.2/jobs-arm-sessions-write`.

### S4 — Wire the compounder rules and fix Gate C1

1. `fundamentals.py` calls `policy.is_excluded_financial` — the live code excludes the entire
   Financial Services sector, dropping exactly the toll-booth compounders §3.1 names as eligible.
2. Gate C1 **fails closed** on missing inputs; today leverage, issuance and the debt-vs-EBITDA
   test all default to pass.
3. The engine tolerance is flat 5pp in the sweep, matching §3.1 and `score.py`.
4. `filing_date` never falls back to fiscal period end — §3.3 calls this non-negotiable.
5. On engine divergence the **engine component drops out of the CCN** (§3.1 routes it down the
   data-confidence path); today it is flagged and still contributes 33%.
6. *(Blocked on Q7/Q8)* effective shares and the FX conversion.

**Closes:** `3.1/c1-excludes-financials` · `3.1/compounder-sizing` · strengthens
`3.1/engine-reliability`, `3.3/filing-date`.

### S5 — Wire the momentum rules

1. `rank.py` calls `policy.scan_base` — the live scan is the superseded rule and diverges three
   ways (pivot window, break test, where the 0.5% grace applies).
2. MCN setup proximity at **three** sub-scores; the 2026-07-31 pass dropped pullback contraction.
3. `policy.l1m_member` — M4 must **pass**, not merely "not fail".
4. `policy.trend_template` replaces the inline M2.
5. Remove the invented 210-bar scoreability threshold, which silently shortens the plan's
   52-week and 252-session windows.
6. `queue` insert deduplicated — `rank.py` can die on a duplicate primary key when a holding is
   also a top-10 BUY.

**Closes:** `3.2/base-detection` · `3.2/pivot-grace` · `3.2/m2-trend-template` ·
`3.2/l1m-top150` · `3.2/mcn-score`.

### S6 — One universe

`funnel.py` and `score.py` both call `policy.in_l0`. Today the census sets `in_l0` at $4 and one
day's $5M volume, `rank.py` re-applies the real filters, and `score.py` re-applies nothing — so
the two sleeves screen different universes off the same column.

**Closes:** `3.0/l0-filters`.

### S7 — The four money bugs

1. **`book.sleeve` is written** by phase0's §6 Step 2a assignment. Until this lands,
   `daily.ratchet` selects an empty set and **no position in the book carries a trailing stop**.
2. **The entry ticket is 50%** of intended size (§3.2 step 1); steps 2–3 ship as add stop-limits
   at pivot +2% / +4%, both limited at pivot × 1.05.
3. **M1 is checked at entry** — §3.2 says the gate is enforced at entry time; `gate_state`
   appears in `phase0.py` zero times today.
4. **`bench.approved` is checked** — §6 Step 3 says *approved* bench names.
5. phase0 calls `policy.momentum_size`, `group_has_room`, `sleeve_has_room`,
   `size_is_admissible`, `compounder_size`, `initial_stop`, `in_blackout`.
6. *(Blocked on D1)* the theme cap.

**Closes:** `3.2/pyramid` · `3.2/pyramid-ceiling` · `3.2/stop-8pct` · `3.2/momentum-sizing` ·
`2.1/sleeve-counts` · `2.2/max-2-per-group` · `2.3/position-floor` · `2.3/single-name-cap` ·
`2.3/risk-not-dollars` · `3.3/blackout` · `3.3/blackout-trading-days`.

### S8 — Data integrity at the feed

1. **Bulk ingest.** §4.1 forbids per-ticker pulls *as the routine* by name; per-ticker survives
   for the four enumerated exceptions.
2. **Corporate-action refresh.** A split rewrites adjusted history; without a re-pull a 4:1 split
   reads as −75% and fires stops — the plan states this failure verbatim.
3. **Price quarantine.** `policy.price_is_suspect` plus a quarantine store; quarantined rows are
   named in the next brief, never silently used.
4. **Quota meter and the 70% alarm.**
5. **3-year rolling window**: archive compressed to the repo, then prune.
6. **Delisted names retained.**

**Closes:** `4.1/bulk-prices` · `4.1/corporate-actions` · `4.1/price-quarantine` ·
`4.1/quota-meter` · `4.1/bar-retention` · `3.3/delisted-retained`.

### S9 — Steady-state ticket generation

The largest missing piece: today `phase0` writes tickets and nothing else does, so there is no
steady state at all.

1. The pyramid state machine — `book.pyramid_step` is never advanced, so the breakeven ratchet
   can never fire.
2. Breakout confirmation on the live path, with late confirmation and the failed-breakout exit.
3. The fill loop: chat or ticket flip → provisional → book that night → Sunday confirm.
4. `2.0/ticket-names-account` with its cash test and T+1 same-account reuse.
5. The +10 displacement rule, within-sleeve only.
6. `3.0/l2-composition` in full.
7. Momentum exits: template failure and MCN < 55, not just a fired stop.
8. The stalled-pyramid rule.

### S10 — The five sessions

R1–R5 as runbooks, plus the database support they need: shadow book, entry snapshots,
invalidators, purchase anniversaries, the C2 memo store, the rejection cooldown store, and the
TWR performance line.

### S11 — Re-run the evidence

The backtest currently simulates rules the plan deleted and has lookahead on re-rank days. After
S4–S7 land: fix the simulator to share `policy` rather than reimplement it, re-run both sleeves,
and re-grade. Only then is Phase 0 re-run against conforming rules.

---

## 3. Cross-cutting

**Testing.** Golden fixtures for CCN, MCN and the hurdle so a refactor that moves every score 3%
is visible. Property tests where a property exists (hurdle monotonic in the fair multiple, stops
never ratchet down, percentiles bounded). `nav_cad` gets a test — it has none, and every position
size depends on it.

**Security.** SHA-pin every action in the eleven secret-holding workflows. `sslmode=verify-full`.
Migration checksums in `_migrations` so deployed controls can be verified against the repo. The
backup contains `runs.detail` — tracebacks and raw stdout — and is committed to the repo;
scrub it. Secret rotation cadence written down.

**Types.** `mypy` strict module by module, starting with `policy`.

---

## 4. Deliberately not doing

- Money as `numeric` instead of `double precision` — correct, but a large migration touching
  every table; raised separately.
- Options, shorting (D8, deferred by the plan).
- Learnings promotion thresholds (the plan says write them once real observations accumulate).
