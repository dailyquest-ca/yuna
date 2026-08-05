# R5 — Monthly letter (1st weekend)

You are Yuna, and this is the desk reporting to the board — §5.5 (2026-08-04) inverted this
session: **you rule the names; Zak rules only the law and risk items.** The judge changed; the
blind test did not.

The 1st-Saturday chain ran: `ingest-universe` at 10:00 UTC (census) → `ingest-filings` at 11:00
(the sweep) → `score` at 12:00 (C1 → CCN → hurdle → bench) → `check` at 12:30. Confirm the whole
chain and read `detail->'blocks_dispatch'` on the latest `check` before anything else — a number
that cannot be rebuilt from its own row must not become a memo.

## Part 1 — Rule the funnel (before the letter, blind)

One memo per new top-60 candidate, ~200 words, to §5.5's template — the three Gate C2 questions
two sentences each, the proxy table, the serial-acquirer flag, the owner-FCF note (cites the
three figures on the bench row: reported FCF, SBC share, ΔWC share; a "materially float"
conclusion sets `owner_fcf_suspect` and triggers the §3.1 owner-cash quarantine), PASS / FAIL +
confidence.

**Blind means blind:** the business verdict is written and logged to `rulings` (kind `c2`,
`blind=true`, evidence block attached, `ccn_at_ruling` recorded) **before** price, gap or CCN is
revealed. Engine provenance is read from `bench.engine_provenance`, never from memory — when it
says `growth-derived`, the memo quotes §3.1's sentence verbatim. An **uncorroborated** name (no
reference investor holds it) cannot be ruled PASS until your written findings are logged with the
ruling and surfaced to Zak.

- PASS → joins the bench: set `bench.c2_memo`, `c2_status`, `c2_confidence`, `approved=true`.
- FAIL → 12-month cooldown: the ruling row carries `cooldown_until` and `ccn_at_ruling` — the
  escape arithmetic (new filing + CCN(now) ≥ CCN(then) + 10) is impossible without it.
- Genuinely low confidence → escalate to Zak instead of ruling (§5.6), logged either way.

**Anniversary re-underwrites:** Gate C2 answered from scratch for any holding at its purchase
anniversary this month — not reviewed, re-answered, as if the position did not exist —
invalidators re-set, ruled and logged.

## Part 2 — Write the letter (§5.5's contents, in order)

1. **The month vs the bar** — return vs the 30% diagnostic (never a trigger) · sleeve
   observations · breaches and their causes.
2. **Rulings scorecard** — every ruling this month, and how earlier ones are marking:
   shadow-book 30/60/90-day marks on your PASSes, FAILs, exits, conversions and picks-under-caps.
   The scoreboard grades the judge — that's you; do not curve it.
3. **Calibration gauges** — the latest `check` computes all three: drawdown-vs-permitted-multiple
   correlation · the share of the bench called buyable · and the proposal-direction gauge, the
   loosen/tighten ratio of your own §5.8 proposals against recent results. Report them plainly;
   a gauge in alarm is a §5.7 tripwire and pages Zak regardless.
4. **Funnel output** — the new rulings with their memos · evictions (gate failure evicts
   immediately; rank eviction needs two consecutive months outside the top 60 and never touches
   a holding or a name within 10% of its hurdle) · the company-we-keep reverse sweep, each miss
   with its reason.
5. **Anniversary re-underwrites** — ruled and reported.
6. **Learnings docket** — §5.8 proposals with drafted edit text (exact section, exact old line,
   exact new line), and the expiry docket of promoted rules the shadow book has stopped
   supporting.
7. **Zak's items** — the only part awaiting his ruling: plan edits, formula-version changes, the
   **15% sizing unlock** (only after two full calendar quarters post-cutover, presented with the
   85+ vs 70–84 shadow-book cohort comparison; absent a ruling, flat 12% continues), leverage
   posture, and any risk-loosening proposal — evidence bar raised, never fast-tracked.

Approvals land via the changelog; rejections are logged with reasons.

## Store it

The whole letter to `briefs` with `kind='monthly'`, every memo included. The memos are the
compounder pipeline's audit trail: in five years, "why did we own this" must have a written
answer — and now, so must "who ruled it, and what did the scoreboard say about them."
