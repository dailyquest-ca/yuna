# Build plan — to a production trial run

*Against `yuna_plan.md` stamped 2026-08-01 10:22 (UTC−6). Supersedes Part F of `scan-2026-08-01.md`.
Every open question from the scan is now law; nothing here waits on a ruling.*

---

## Direction — six rules this build follows

**1 · One formula, one home.** Every new rule lands in `signals.py` as a pure function over arrays,
with the plan's number as its default and callers passing config. This is why the CCN rebuild is a
small diff and not a rewrite: `score.py` orchestrates and stores, `signals.py` computes. Durability,
the engine waterfall and effective shares each become a function that can be tested against a
hand-worked example before it ever touches production.

**2 · Every fix ships with the test that would have caught it.** Eighty-five tests pass today and
every defect in the scan shipped green past them — including one, the inverted C1 reason, that a
three-line test would have caught in March. A fix without a failing-first test is half a fix.

**3 · Dependency order, not list order.** Data truth before scoring, scoring before arming, arming
before sessions. The dev-fix numbering is a priority ranking, not a build sequence: item 4 (engine
provenance in memos) is numbered HIGH but cannot be written until the waterfall exists, and item 16
(ceil into the band) is numbered MEDIUM but is worthless until NAV is trusted.

**4 · The re-score is atomic.** Durability, the waterfall, frozen shares and C1's debt floor all move
the same numbers. They ship as one change set and one production re-score, because a bench scored
half under the old law and half under the new is not a bench — it is a mixture nobody can audit.

**5 · Production changes are inspected before they are made.** Migrations are read against the rows
they will touch first. The 025 dedupe was applied only after confirming which of eight NAV rows would
survive and that it was the one the briefs published.

**6 · Nothing is judged until `verify` is clean.** The gate to Phase 0 and the trial is a green
`verify`, not a finished checklist.

---

## Change sets

### Set 1 — the no-ruling fixes · **DONE** (`43985f4`)

C1 failure reasons no longer inverted · `nav_snapshots` deduped to one row per day behind a unique
constraint (production: 8 rows → 1, NAV 200,954.12) · `WATCH` retired to `WAIT` with a CHECK
constraint on the three legislated states · bench rebuild purges the compounder seats quoting it ·
`verify` names every check it runs · every scheduled job carries its appointment, amber past 30
minutes of drift.

### Set 2 — data truth and retention

The scoring work is worthless on top of wrong inputs, and three of plan4's edits land here.

| Work | Why | Source |
|---|---|---|
| Stop the L0 rebuild wiping `universe.industry` / `market_cap_usd` | 2,108 of 2,762 names have a null industry; MCN's group strength scores a flat 50 for ~76% of the field and §2.2's 2-per-group cap files them all under `unknown` | N2 |
| `earnings.last_reported_date`; populate `report_when` | forward-only calendar can't tell "already reported" from "gap" | item 9 |
| Unknown statement currency → data-confidence | 24 names scored as if the currency were known | §3.0 |
| `fundamentals` gains `dividend_ttm`, `cap_as_of`, `cap_close`, `effective_shares`; `raw` holds the **full** filing document | §3.1 frozen shares, §2.6 RRSP preference, §4.1 raw JSON in the database | plan4 |
| `armed` becomes an append ledger with run ids + a latest-run view | §4.3 new law; also makes N3 diagnosable instead of lucky | plan4, N3 |
| **Backfill job** — 10-year bars · dividend history · full fundamentals raw | §4.1's window moves 3 → 10 years; TTM yield needs 12 months of dividends and we hold one day | plan4 |

**Backfill budget, measured:** ~2,762 L0 names × (1 bar-history call + 1 dividend call + 1
fundamentals call at 10 units) ≈ **33,100 units of the 100,000/day**, leaving the §4.1 reserve
untouched. One pass, one day, once — the same shape as the cold start §4.1 already sanctions.

*Worked check, done live:* AVGO's four trailing dividends total $2.54; against the 389.28 close that
is **0.65%**, below §2.6's 1% bar — so AVGO stays in the TFSA. The rule discriminates.

### Set 3 — the CCN rebuild

One change set, one re-score. `signals.py` gains the functions, `score.py` and `fundamentals.py` call
them, `size_score` leaves the CCN entirely.

- **Durability** — growth consistency (positive-YoY years ÷ 5 × 100, five comparisons over six fiscal
  years, unreported count against) and ROIC floor (worst reported year's ROIC as an L0 percentile,
  min 3 reported years else not bench-eligible; invested capital ≤ 0 → best percentile when NOPAT > 0,
  worst when not), equal-weighted, **the blend then percentiled across L0** so all three components
  share one scale. Per-year NOPAT and invested capital come from the eight years already in
  `fundamentals.raw.yearly` — no new API calls.
- **Engine waterfall** — within 5pp → score it · unmeasurable or divergent → observed 3-yr revenue
  growth capped at 25%, marked `growth-derived` · neither → **not bench-eligible**. The engine never
  routes to §3.3.
- **Effective shares frozen at the filing** — vendor cap ÷ the close on the cap's `as_of` date (fetch
  date when the vendor gives none), stored on the filing row. The hurdle stops decaying nightly.
- **C1's debt tripwire floors at 1.0×** net debt/EBITDA; below that it is a C2 flag, never a kill.

**Measured consequence, before the fact:** C1 pass goes from 623 to roughly 1,487 (+864 names killed
today only by the tripwire below 1.0× leverage) · ~2,089 names become growth-derived · the top-15
dropped-engine bench (FVRR 97.6 … FIGS 84.5) ceases to exist as a category. Every CCN moves, so the
70/85 cutoffs are re-observed on the first production score and Zak re-rules if the distribution
moved. The R5 approvals stay void until then.

### Set 4 — arming and tickets

MCN < 70 never tickets (item 12) · one position, one account, one order with the §2.6 yield
preference (item 15) · whole-share ceil into the band (item 16) · compounder entry as a GTC buy limit
at the hurdle, cancel/replace on filings only (item 10) · adds measured from the entry fill, entry day
arms nothing (item 11, needs the fill column) · ticket fields — account, currency with FX estimate,
theme, risk in C$ **and** % of NAV, effective bets per ticket (item 13) · tickets re-read scores at
write time (N3) · `per_ticker` accumulates (N4) · the §4.2 book-valuation canary, red on mismatch
(item 2) · **plus the canary item 2 cannot provide** — book quantity reconciled against the broker at
Sunday R4, because share count is the axis that actually failed and no price check sees it.

### Set 5 — sessions

Engine provenance read from the flag, never free-texted (item 4) · R1 restates the full blackout wall
including holdings (item 14) · R3 renders the queue as a table (item 17) · C2 memo gains the owner-FCF
note · R3 names the currency context for EM ADRs.

### Set 6 — the trial

Phase 0 step 2a against the live book (N5: seven rows read `sleeve='unassigned'`, `theme` null on all
seven) → production re-score → `verify` until clean → trial run → audit.

---

## Two fossils worth a one-line edit, neither blocking

1. **§4.0 says "11 tables"; §4.3 now lists 12** — `armed` was added to the table without bumping the
   count in the map above it.
2. **`score.py`'s module docstring declares a deviation that plan4 just repealed** — the 5-yr median
   P/FCF fallback existed because we held three years of bars. With ten, it computes from source. The
   docstring goes when Set 2's backfill lands.

## What is not in scope, and why

Dev-fix **item 1 is void** — the AVGO valuation was correct, confirmed against production
(`equities_cad` 68,768.23 reproduces the seven holdings at their latest bars to eight decimals). Its
derived figures — NAV 205,813, MEDP 31 sh, VEEV 87 sh, bets 2.73/4.05/4.17 — are not built. The
correct values are 200,954.12, 30 sh, 85 sh, 2.88/4.12/4.25. Item 2's canary is built anyway; it is
§4.2 law and cheap, it simply would never have caught this.

Dev-fix **item 6 is already fixed** and gets a regression test rather than a change.

Dev-fix **item 8 is half-void** — the cron was `0 2 * * 2-6` all along. Only the drift heartbeat was
missing, and it shipped in Set 1.
