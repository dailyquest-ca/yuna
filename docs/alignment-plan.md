# Alignment plan — closing the gap to plan v4

*Written 2026-07-31 against `docs/audit-2026-07-31-v4.md`. The ledger in `src/yuna/rules.py`
is the progress bar: 89 clauses, 31 wired at the start of this work.*

Goal: the running system does exactly what `docs/yuna_plan.md` says — no more, no less. Every
step below closes named clauses, and the conformance test refuses to let the ledger lie about it.

---

## W1 — Wire the rules, delete the inline copies

The root cause of a third of the audit. Seventeen `policy` functions have no caller while the
jobs run their own drifted copies. Nothing new gets written here — the correct rule already
exists and is tested; the job stops reimplementing it.

| Module | Replace with |
|---|---|
| `rank.py` | `scan_base` (the live scan is the superseded rule), MCN setup at **three** sub-scores, M4 null must not read as a pass |
| `daily.py` | `in_blackout` counted in trading days, `holds_through_earnings` |
| `phase0.py` | `momentum_size`, `group_has_room`, `sleeve_has_room`, `size_is_admissible`, `compounder_size`, `initial_stop`, `in_blackout` |
| `fundamentals.py` | `is_excluded_financial`, flat 5pp tolerance, C1 must fail closed on missing inputs, `filing_date` must never fall back to period end |
| `score.py` | the engine component drops out of CCN on divergence |

**Closes:** `2.1/sleeve-counts` · `2.2/max-2-per-group` · `2.3/position-floor` ·
`2.3/single-name-cap` · `2.3/risk-not-dollars` · `3.1/c1-excludes-financials` ·
`3.1/compounder-sizing` · `3.2/base-detection` · `3.2/pivot-grace` · `3.2/stop-8pct` ·
`3.2/momentum-sizing` · `3.3/blackout` · `3.3/blackout-trading-days` · `3.3/earnings-cushion`

## W2 — The four money bugs

1. **`book.sleeve` is never written.** `phase0` computes the §6 Step 2a assignment and discards
   it; `daily.ratchet` selects `where sleeve='momentum'` and gets an empty set. **No position in
   the book carries a trailing stop today.**
2. **The entry ticket is full size.** §3.2 step 1 is 50%; steps 2–3 ship as add stop-limits at
   pivot +2% / +4%, both limited at pivot × 1.05.
3. **M1 is not checked at entry.** §3.2 says the gate is *enforced at entry time*; `gate_state`
   appears in `phase0.py` zero times.
4. **Un-approved names are bought.** §6 Step 3 says *approved* bench names; `phase0` never reads
   `bench.approved`.

**Closes:** `3.2/pyramid` · `3.2/pyramid-ceiling` · `2.6/account-placement` (partial) ·
`2.4/no-averaging-down-momentum`

## W3 — One universe, one L0

`funnel.py` sets `in_l0` at $4 and one day's $5M volume; `rank.py` re-applies §3.0's real filters
but `score.py` does not, so the two sleeves screen different universes. The L0 test moves into
`policy` and both pipelines call it.

## W4 — Data integrity at the feed

1. **Bulk ingest.** §4.1 forbids per-ticker pulls *as the routine* by name; per-ticker survives
   for the four enumerated exceptions only.
2. **Corporate-action refresh.** A split rewrites adjusted history; without a re-pull a 4:1 split
   reads as −75% and fires stops. The plan states this failure verbatim.
3. **Price quarantine.** >40% move with no corporate action, or any print that would fire a
   sell-side action, needs two sources.
4. **Quota meter and the 70% alarm.**
5. **The 3-year rolling window** — archive, then prune.

**Closes:** `3.3/delisted-retained` (enables) · quarantine and refresh clauses added to the ledger

## W5 — Heartbeat honesty

- `'running'` is not a terminal status; a killed runner currently reads green.
- A job that never fired writes no row, so no staleness check can see it. The freshness line must
  know the expected schedule.
- `nightly-retry` re-runs only the bar pull, so the night the pipeline fails is the night with no
  stop sheet.

## W6 — Schema defences (migration 019)

CHECK constraints on every state machine · `security_invoker` on all six views ·
`v_fundamentals_latest` gets an explicit column list · `transactions` gets its writer ·
guard-trigger coverage reviewed against §4.3's list.

Money as `numeric` is a separate, larger migration — raised, not bundled.

## W7 — Steady-state ticket generation

The largest missing piece. §4.3: *jobs arm; only sessions write tickets.* Today `phase0` writes
tickets and nothing else does, so there is no steady state at all. Needs: the pyramid state
machine, the fill loop, `2.0/ticket-names-account` with its cash test and T+1 reuse, the
displacement +10 rule, `3.0/l2-composition` in full.

## W8 — The five sessions

R1–R5 as runbooks, plus the database support they need (shadow book, entry snapshots,
invalidators, anniversaries, the C2 memo store, the TWR performance line).

---

## Blocked on a ruling

These cannot be built correctly until Zak answers `docs/open-questions.md`:

| Clause | Blocked on |
|---|---|
| `2.2/theme-cap-35` | **D1** — theme is judgment, not sector; what does a *job* do meanwhile? |
| `3.1/foreign-fx`, `3.1/effective-shares` | **Q8** — sequencing the FX conversion with effective shares |
| the hurdle's growth on divergence | **Q7** — what growth replaces an untrustworthy engine |
| `5.6/performance-twr` | **Q1** — what window and what observation cadence |
| ticket state machine | **Q4** — the legal transitions |
| quarantine thresholds | **Q5** — the numbers |
| `2.5/leverage` | **Q6** — is CNQ an exception, or does the levered layer need its own test |

Everything else proceeds.

---

## Order

W1 → W2 → W3 (one pass, they touch the same files) · W5 and W6 in parallel · W4 · then W7, W8.
Re-run the backtest only after W1–W3 land, because until then it measures a different system.
