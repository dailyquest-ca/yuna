# The backtest as a standing instrument — build plan, 2026-08-10

*Supersedes the benchmark and cost sections of the 2026-08-09 WO-11–14 batch. Written after the
review in `backtest-spec-review-2026-08-10.md` and Zak's rulings the same day.*

---

## Zak's rulings, 2026-08-10

| # | Ruling | Consequence |
|---|---|---|
| 1 | **The named-investor comparison is dropped.** Not parked — dropped | No 13F ingest, no clone, no WO-15. `config.named_investors` keeps its existing job (§3.1 corroboration) and gains no new one |
| 2 | **The benchmark is the S&P 500, held as VOO.** That is the thing we are versing over time | One yardstick. Everything reports against it |
| 3 | **No currency conversion is modelled.** US markets and US-listed equivalents only; the backtest is USD-native and does not translate to CAD | `fx_fee_per_side = 0` becomes a *recorded ruling*, not a pending default. The FX question that gated the batch is closed |
| 4 | **The backtest calls the real logic.** One source of truth | `backtest.py` becomes a driver over `signals.py`. This is the load-bearing decision |
| 5 | **It runs on every logic or behaviour change, and on demand** | Phase 5 |

**One caveat that follows from ruling 3, to be printed on every run:** the live book is a CAD NAV
holding CNQ.TO among other things. A USD-native backtest is therefore *"what the US sleeve would
have done, in USD"* — it is not comparable line-for-line to the live NAV number, and no letter
should imply it is. That is the right trade: we are testing the rules, not reconstructing the
account.

---

## The design, in one paragraph

`signals.py` is the law expressed as code. `arming.py` applies it to today. `backtest.py` applies
it to every day since 2016. Same functions, same constants, one implementation, and anything the
backtest needs that `signals.py` does not yet have gets built **in `signals.py`**, so production
gets it in the same commit. There is no second copy of a rule anywhere in this plan, and the CI
guard in Phase 2 exists to keep it that way after we've all forgotten why.

---

## Phase 0 — the spike (measure before designing) · half a day

One real unknown: **speed**. Today's `rank_week` is vectorised across all names at once and runs
the whole 500-day test in **0.6–1.4 minutes** (`runs` table, 2026-07-31). `signals.py` is per-name.
A ten-year weekly rank is roughly 520 rank-dates × ~2,800 names ≈ **1.5M evaluations**, and
`setup_proximity` → `atr` currently convolves the whole price history on each call.

Port one year of the rank loop onto `signals.py`, time it, extrapolate. Decision rule:

- **Under ~15 minutes** → done, build Phase 2 as written, no optimisation.
- **Over** → optimise **inside `signals.py`** (incremental ATR, cached rolling means, accept a
  window slice instead of the full series). Production gets the same speedup. **Forking a fast copy
  into the backtest is not on the table** — that is the failure this whole plan exists to end.

Deliverable: a number in the PR body, and a go/no-go on optimisation.

---

## Phase 1 — data · one afternoon

| Item | Why | Note |
|---|---|---|
| **`VOO.US` into `universe`, bars back to 2016** | The yardstick (ruling 2). `adj_close` is distribution-adjusted, so VOO gives **total return** for free | Fixes the price-index problem in one move. VOO's inception is 2010, so 2016 is clean |
| **`GSPC.INDX` backfill to 2016** | Currently starts **2023-08-01** — it, not the stock bars, is what caps the window at two years | Optional secondary reference; VOO is the yardstick |
| **Position returns from `adj_close` ratios; triggers, pivots and stops from raw OHLC** | `corporate_actions` holds dividends only from **2025-06-30** (2,084 rows), so dividends cannot come from there | Negligible for 6-day momentum holds; **material** for 290-day compounder holds. Doing it once, correctly, costs nothing extra |
| **`earnings` report dates back to 2016 from `raw_doc->'Earnings'->'History'`** | The `earnings` table starts **2025-06-27** (`CAL_BACK = 400`). Without this the blackout and M4 are unenforceable across most of the window | 2,949 tickers, avg 98.8 quarters, `reportDate` per quarter. **No new vendor call** |
| **Survivorship — decision required** | `universe` has 3,244 active and **2** delisted, and `backtest.py` filters `status='active'` | See "Open decisions" below |

Bars themselves need nothing: **6,410,951 rows, 3,268 tickers, back to 2016-08-05**, with 2,050
tickers carrying the full depth.

---

## Phase 2 — the engine becomes a driver · the main build

`backtest.py` keeps: data loading, the day loop, portfolio accounting, cost modelling, persistence.
It loses every rule it currently re-derives.

| Clause | Today in `backtest.py` | After |
|---|---|---|
| M1 market gate | `m1_series()` | `sg.market_gate()` |
| M2 trend template | inline in `rank_week` | `sg.trend_template()` |
| M3 base detection | inline in `rank_week` | `sg.base_scan()` |
| MCN | inline, **four** setup sub-scores | `sg.momentum_quality` / `setup_proximity` / `mcn` — three |
| Entry / stop / pyramid | inline, **+2.5%/+4.5%**, no ceiling | `sg.entry_order`, `sg.initial_stop`, `sg.pyramid_orders` — +2%/+4%, ceiling pivot × 1.05 |
| Ratchet, breakeven, euphoria | inline | `sg.ratchet_stop()` |
| Sizing | inline, **no MCN floor** | `sg.momentum_size()` + an explicit MCN ≥ 70 gate |
| Blackout / hold-through | absent | `sg.in_blackout()`, `sg.holds_through_earnings()` |

**New in `signals.py`** (production needs these too, and currently open-codes two of them):

- `confirmation_state(...)` — the §3.2 state machine as one pure function: confirmed → arm ·
  unconfirmed → freeze at 50% · three sessions each against its own 50-day to confirm late ·
  hair-trigger close below pivot → exit next open. This is the mechanic that has never been tested.
- `stalled_pyramid(...)` — the 4-week rule.
- M3 evaluated **daily**, not weekly. §3.2's table says daily trigger check; the current sim reuses
  Friday's pivot all week.

**The structural guard** (`learnings.md` #20 — write the check before the feature): a test that
fails if `backtest.py` defines any function whose name or behaviour duplicates a `signals.py`
export. Cheap, and it is the only thing that will stop this from happening again in six months.

---

## Phase 3 — law-v0, with a conformance table that can be believed

The batch's 13 clauses, plus two the review added:

14. **MCN ≥ 70 at entry.** Acceptance: `select count(*) from backtest_trades where run_id = <law-v0>
    and mcn < 70` → **0**. Today that query returns 211 of 296 on run 5.
15. **M3 checked daily.**

And the part that makes the table honest: each clause reports **`implemented`** *and* **`coverage`**
— the fraction of the tested window over which the data required to enforce it actually existed. A
green tick on a clause with no data for 80% of the run is precisely the failure this batch exists to
end (`learnings.md` #19, *green is not a result*).

Acceptance runs as SQL in `check`, not only as unit tests: zero `volume unconfirmed` exits, exit
vocabulary closed against the §3.2 list, `backtest_equity.benchmark` non-null on every row,
`params` carrying `{variant, law_stamp, config_stamp, window, costs}`.

---

## Phase 4 — the differential test · the real conformance instrument

A single hand-picked week cannot prove the engine implements the law, and the 8/4 NUE/RS test can
fail for reasons that are purely about portfolio state (review §4).

Instead: **every night, for every name in that night's `armed` ledger, the backtest engine
re-evaluates that same date and must agree** — state, pivot, confirmation verdict, freeze, stop,
flags. Portfolio state excluded from the comparison. Disagreement is a red `check`.

The corpus is already ~100+ name-days (47 `pass` observations plus the `armed` ledger since
2026-08-01) and grows every night for free. After Phase 2 this is also a live assertion that both
sides are still calling the same functions. The 8/4 week stays as one named case in it.

---

## Phase 5 — the triggers · what Zak asked for

Four doors, three of them automatic.

**1 · On every logic change (git).** `backtest.yml` gains `pull_request` and `push` with a paths
filter: `src/signals.py`, `src/backtest.py`, `src/arming.py`, `src/score.py`, `src/rank.py`,
`migrations/**`, `docs/yuna_plan.md`. It runs law-v0 and posts the delta comment from Phase 6.
Runtime today is ~1 minute; if Phase 0 lands it under ~15 for the full window, this is affordable on
every push with no fast/slow split.

**2 · On demand.** `workflow_dispatch` already exists — re-cut its inputs for the new shape: window
start/end, label, `baseline_run_id` to compare against, `dry_run`. Typing **backtest** in a project
chat dispatches the same job. This is the "reassure myself" door, and it is the one that should be
easiest to open.

**3 · On behaviour change that git cannot see.** There are **52 config keys** in the database —
thresholds, budgets, caps — and changing one changes the machine's behaviour without a commit. So:
`score` writes a hash of the decision-relevant subset, and `check` goes **amber** when the newest
law-v0 run's `config_stamp` no longer matches today's. That converts "behaviour changed and nothing
was re-tested" from a silent state into a line in the brief. Without this, a git trigger gives false
comfort — `learnings.md` #21, *a rule stored is not a rule enforced*.

**4 · Weekly.** The Saturday chain re-runs law-v0 after the weekly rank, as WO-14 proposed. Cheap,
idempotent, and it means the answer is never more than seven days stale even if nothing changed.

---

## Phase 6 — the report, and the one rule that keeps it honest

A number alone reassures nobody. Every run is compared against a pinned baseline
(`config.backtest_baseline_run_id`), and the PR comment / letter line is a **delta**:

```
law-v0 · stamp 2026-08-09 · config a3f1e9 · 2016-08 → 2026-08
                     this run     baseline      Δ
CAGR                   X.X%         X.X%      +0.0
vs VOO (total return)  −X.X%       −X.X%      +0.0
expectancy / trade      XX bps       XX bps     +0
trades                  XXX          XXX        +0
max drawdown          −XX.X%       −XX.X%     +0.0
avg exposure           XX.X%        XX.X%      +0.0
conformance             15/15        15/15      ok
```

**The rule: the backtest reports, it does not gate.** The build fails on **conformance** assertions
only — MCN floor, exit vocabulary, coverage present, benchmark non-null, differential test agrees.
It must **never** fail because the performance number went down.

That distinction is the whole difference between a regression test and an optimiser. A merge gate on
CAGR is a standing instruction to fit parameters to history, and it would corrupt exactly the
instrument phase 2's ablation grid will later depend on. A performance move gets printed, and the PR
body owes it a sentence. Zak rules; the machine reports.

---

## What this will and will not tell you

Worth writing down now, so the first green run isn't over-read:

- **It will tell you** whether the rules as ratified would have made money over ten years spanning
  Q4-2018, the 2020 crash and the 2022 bear — three regimes the current two-year evidence base does
  not contain — and whether a change you just made moved that number.
- **It will not tell you** how a survivor-free universe behaves (unless the decision below scopes it
  in), how non-US markets behave, or anything trustworthy about the compounder sleeve from six
  trades.
- **Read the per-trade numbers, not the headline.** Momentum sat at ~12.7% average exposure, so its
  NAV CAGR is mostly a measurement of cash. Expectancy per trade and return on deployed capital are
  the signal; the headline is the cash drag.

---

## Open decisions

| # | Decision | Recommendation |
|---|---|---|
| 1 | **Survivorship** — scope it in, or quantify and disclose? | **Quantify now, scope in later as its own phase.** Rebuilding a point-in-time L0 census for 2016–2026 and pulling bars for dead names is plausibly the largest single item in the programme, and it would block everything behind it. Start recording census membership from this month so the bias shrinks going forward, and print the count of names that left L0 during the window in `stats.biases` |
| 2 | **Starting capital, in USD** | A round **$200,000 USD**. It is a scale factor on nothing that matters — per-trade stats and exposure percentages are the outputs — and a round number stops anyone reading the end NAV as a forecast |
| 3 | **Window start** | **2016-08**, the full depth of the bars. Report the first tradeable date after warm-up (~280 bars) on every run |
| 4 | **Does the compounder sleeve ride the same rails?** | **Yes** — same triggers, same delta report, same VOO benchmark, still graded indicative-only per §4.8. It is already a driver over `signals.py`, so it costs almost nothing |

---

## Sequence and rough size

| Phase | What | Size |
|---|---|---|
| 0 | Speed spike | half a day |
| 1 | VOO + backfills + adj_close returns + earnings history | one afternoon |
| 2 | `backtest.py` → driver over `signals.py`; three new `signals.py` functions; structural guard | the main build |
| 3 | law-v0 + conformance table with coverage + acceptance SQL | with Phase 2 |
| 4 | Differential test against the `armed` ledger, nightly | small, high value |
| 5 | Triggers: paths-filtered CI · dispatch · config stamp · Saturday | small |
| 6 | Baseline + delta report; letter line | small |

Phase 2 is the only large one, and most of its diff is deletion.

**Still parked, and now for a sharper reason:** the exit-rule ablation grid. A grid searched against
a baseline that enters names at MCN 15, over one bull regime, with no costs, on a survivor-only
tape, will faithfully find the parameters that fit those four defects. It gets unparked when
law-v0 is trusted, and not before.
