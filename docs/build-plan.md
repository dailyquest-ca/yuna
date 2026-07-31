# Yuna — prototype build plan

*2026-07-31 · replaces the 23-step draft (in git history). The law is `docs/yuna_plan.md`;
the audit behind this is `docs/audit-2026-07-31-v4.md`.*

**Goal.** The plan's strategy running end-to-end: correct analysis, correct tickets, real
briefs, a backtest that measures the actual rules, and the daily operating loop live. This is
a prototype — **correct beats polished, and speed matters.** Everything that is not "the
analysis is right" or "a bug costs real money" goes to the TODO list at the bottom.

**Quality bar per step:** the changed rule has a test (most already do — 124 exist), `ruff`
and `pytest` green, one manual compare against the previous run's output. That's it. The
heavyweight verification machinery from the old draft is TODO.

---

## P0 — Today (hours, before 2026-08-01 14:00 UTC)

1. **Backup**: add `runs` to `backup.py`'s SKIP set. `runs.detail` carries raw tracebacks and
   job stdout (which can contain the API key in a URL); the first-ever dump commits tomorrow
   at 14:00 UTC and gitleaks can't read gzip. One line now; proper redaction is TODO.
2. **Message Zak**: the tickets sitting in `proposed` are void — written at full size with no
   gate or approval check. Place nothing from them; void anything already at the broker.
   (No state change — ticket states are Q4, unruled.)
3. **Strip the `fundamentals.yml` cron** — §4.2 authorizes exactly five scheduled jobs, and
   `monthly-funnel` already runs the sweep. Manual dispatch remains.

**Done when:** committed, and Zak has the message.

## P1 — Correct the analysis (~1 day)

Wire the tested `policy` functions into the jobs and delete the drifted inline copies:

1. **Gate C1** — `fundamentals.py` calls `is_excluded_financial` (today it drops the whole
   Financial Services sector, including the toll-booths §3.1 names as eligible). Engine
   tolerance flat 5pp. `filing_date` never falls back to period end. Drop the invented
   `< 3 fiscal years fails C1` — §3.1 routes that to data-confidence, not the gate.
2. **Base detection** — `rank.py` calls `scan_base` (live scan is the superseded rule:
   wrong window, wrong break test, grace on the wrong price).
3. **MCN setup** at three sub-scores (pullback contraction was deleted from the law).
4. **M4 must pass** — unknown is not a pass (`l1m_member`).
5. **M2** via `trend_template`; drop the invented 210-bar threshold.
6. **One universe** — `score.py` applies `policy.in_l0` the way `rank.py` already does, so
   both sleeves screen the same L0.
7. **On engine divergence the engine component drops out of the CCN** (§3.3 path), not
   flagged-but-still-counted.

Then **recompute**: re-extract C1/CCN from the stored `fundamentals.raw` (no API calls
needed), re-run score and rank. Every bench and candidate row currently in the database was
computed by the old rules.

**Done when:** the recomputed bench and queue are in the database and spot-checked — the
financials are back, the pivots moved, and the diffs make sense.

## P2 — Correct the tickets (~½ day)

1. **`book.sleeve` gets written** from the §6 Step 2a assignment — until then the stop
   ratchet selects an empty set and no position has a trailing stop. Initialize
   `highest_close` from history in the same change so the first ratchet run is sane.
2. **Entry at 50%** of intended size (§3.2 step 1); steps 2–3 ship as add stop-limits at
   pivot +2% / +4%, both limits at pivot × 1.05.
3. **M1 gate checked at entry.** No ticket when the gate is OFF.
4. **`bench.approved` checked** — §6 Step 3 buys *approved* names only.
5. **Approvals get a home**: a small session-writable `approvals` table; Zak approves in
   chat, the session records it, `score.py` folds it into `bench.approved`. (Jobs compute
   bench; Zak's decision is an input to it — §4.3 shape.)
6. Blackout in the ticket path via `policy.in_blackout`, counted in trading days, once.

**Done when:** a dry phase0 run produces tickets that are half-size, gated, approved-only,
and blackout-clean.

## P3 — Backtest gate (~1–1.5 days)

The current backtest simulates rules the plan deleted, and reimplements the rest — which is
how "wrong but green" happened four times last round.

1. The simulator **calls `policy`** — `scan_base`, `classify_breakout`, `pyramid_orders`,
   `ratchet_stop`, `momentum_size`, `in_blackout` — instead of its own copies.
2. Kill the re-rank lookahead (rank on the prior close, trade the next bar).
3. Re-run both sleeves. Cross-check the sim against raw SQL on the bars (the discipline that
   caught the 2%-vs-29.2% bug).
4. Output carries its grade per §4.8: momentum honest-but-survivorship-flattered, compounders
   indicative-only. Q7's interim (hurdle growth capped at observed on divergence) is labeled
   in the output.

**Done when:** results reviewed with Zak. This is the go/no-go for arming real tickets —
if v4's base detection still won't deploy capital, that's a plan conversation before code
goes further.

## P4 — The operating loop (~2 days)

What "running" means day-to-day. Jobs arm; sessions judge and write tickets (§4.3).

1. **Apply migration 018** (the session write path — written, reviewed, unapplied). Needs
   Zak's one bundled blessing: Q4 ticket states and Q5 quarantine numbers as *prototype
   defaults, amendable*, and the §4.3 note that sessions write `balances` (which §5.4's
   Sunday reconciliation requires anyway). Zak mints the scoped token.
2. **Fill loop**: Zak confirms a fill in chat → session records it provisional via the write
   path → the nightly folds provisional fills into `book`. (Jobs own `book`; this is the
   §4.5 loop.)
3. **phase0 stops writing tickets** — it computes the conforming target book into a brief;
   the session proposes tickets from it through the write path. Closes the §4.3 breach.
4. **Breakout confirmation at EOD** in the nightly: mechanical volume-vs-50-day
   classification, late confirmation over three sessions, pyramid arming state on the book —
   blackout beats arming. R1 ships the add tickets only when armed.
5. **R1 and R2 as scheduled Claude sessions.** R1 (weekdays ~6:00 PT): freshness gate first
   — stale ⇒ no new tickets — then gaps, fired stops, and broker-ready tickets from what the
   nightly armed, max 2 new entries, effective-bets line printed. R2 (~20:30 PT): the stop
   sheet, always at least one line. R4 Sunday interactive: balances anchored via the write
   path, fills confirmed. R5 on the first monthly funnel: C2 memos and approvals.
6. **Heartbeat honesty, the careful version**: freshness treats a run stuck in `running`
   past its plausible duration, and a scheduled job with *no* row in its window, as stale —
   without flagging the current job's own in-flight row.

**Done when:** one full week runs — nightly → R1 brief → R2 stop sheet → Sunday
reconciliation — with Zak receiving every message and no manual intervention in the pipeline.

## Then: live

Re-run Phase 0 (§6) against the corrected rules with approvals in place → R1 proposes the
entry/exit tickets → Zak rules and places. Steady state from there.

**Total: roughly five working days of build, with the P3 review gate in the middle.**

---

## Rulings needed (one bundled yes/no message)

| # | Question | Prototype default if blessed |
|---|---|---|
| 1 | Q4 — ticket states | `proposed → approved → placed → filled_provisional → confirmed`, plus `cancelled`/`expired`, as coded in 018 |
| 2 | Q5 — quarantine thresholds | 10K materiality · 10x/0.1x anchor ratio · 50K movement, as coded in 018 |
| 3 | §4.3 wording | sessions may write `balances` (R4 requires it) |
| 4 | D1 — theme cap in a job | jobs print raw theme exposure in the brief; the 35% cap is enforced only where judgment exists — in the session writing the ticket |

Q7 (hurdle growth on divergence) and Q1 (TWR window) run as **labeled interims** and don't
block. Amend any of these later; the plan is law and these are placeholders it can overwrite.

---

## TODO — after it works

Hardening, in rough priority: proper backup redaction (then re-include `runs`) · price
quarantine (§4.1) · corporate-action refresh (§4.1) · bulk ingest · CHECK constraints ·
`security_invoker` on views · DB test harness in CI · quota meter + 70% alarm · 3-year bar
prune/archive · SHA-pin actions · `sslmode=verify-full` · migration checksums · migrate-path
lockdown (ref pinning, file selection) · money as `numeric` · delisted names for the backtest
· shadow book · displacement +10 · rejection cooldown · stalled-pyramid rule · earnings-cushion
exit ticket · crash protocol · dual-qualification flow · annual re-underwrites · TWR
performance line (pending Q1) · L2 spare seats · averaging-down add counter · R3 deep-dive
session · learnings promotion (plan defers it).

**Accepted risks while those wait** — named, not hidden:

- **A stock split reads as a crash** (no corporate-action feed). Odds are low across 7–9
  names; the ±7% gap interrupt flags it next morning and R1 says *verify before acting*.
- **No price quarantine** — one bad vendor print can reach a stop suggestion. Same partial
  mitigation: the gap flag plus Zak's eyes before any order.
- **Per-ticker nightly ingest** — ~2,800 calls against a 100K/day quota. Inefficient, not
  dangerous.
- **Backtest survivorship** — today's listings only; the grade says so on every output.
