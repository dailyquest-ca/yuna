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

**Settled the same day (second pass):** non-US holdings are out of scope for the instrument —
the backtest is USD-native, benchmarked on VOO, and does not attempt to reconstruct the live
account. Survivorship is **in scope** (see Phase 1). Starting capital is **$200,000 USD**, the
window starts **2016-08**, and **both sleeves ride the same rails** — same triggers, same delta
report, same benchmark, the compounder side still graded indicative-only per §4.8.

---

## The design, in one paragraph

`signals.py` is the law expressed as code. `arming.py` applies it to today. `backtest.py` applies
it to every day since 2016. Same functions, same constants, one implementation, and anything the
backtest needs that `signals.py` does not yet have gets built **in `signals.py`**, so production
gets it in the same commit. There is no second copy of a rule anywhere in this plan, and the CI
guard in Phase 2 exists to keep it that way after we've all forgotten why.

---

## Phase 0 — the speed spike · **DONE, 2026-08-10**

The one real unknown was whether per-name `signals.py` calls could drive a ten-year run at all.
Today's `rank_week` is vectorised across every name at once and does the two-year test in
**0.6–1.4 minutes**; a ten-year weekly rank is ~520 rank-dates × ~2,840 names ≈ **1.5M
evaluations**, each calling `trend_template` + `base_scan` + `momentum_quality` +
`setup_proximity`. Measured single-threaded on a decade of synthetic bars:

| | per name | ten-year run |
|---|---|---|
| Naive port — pass the whole series to date | 264 µs | **8.1 min** |
| **Fixed 280-bar tail** | 225 µs | **5.8 min** |

**Verdict: build Phase 2 as written. No optimisation needed, and `signals.py` is not touched for
speed.** Call it ~10 minutes on an Actions runner plus bar loading — affordable on every push, with
no fast/slow CI split.

**Design decision that falls out of it:** the driver passes each rule a **fixed 280-bar tail**, not
the growing slice. No rule reads deeper than 266 bars (`setup_proximity`'s 252-session ATR
percentile plus ATR's own 14), and every output — M2's verdict, M3's `valid` / `state` / `broken` /
`pivot` / `depth` / `contraction_low`, and all three MCN sub-scores — is **identical** on the tail
and on the full 2,520-bar series. So the cost is constant in window length: a twenty-year run costs
the same per rank date as a two-year one. `WARMUP = 280` already carries exactly this number, for
exactly this reason.

That equivalence is now pinned in CI rather than remembered — **`tests/test_tail_equivalence.py`**,
26 assertions over five unrelated price paths, plus one test that truncates *below* 266 and asserts
the answers genuinely diverge, so the guard cannot pass vacuously. A future rule that starts reading
deeper than 280 bars would otherwise break the driver silently: the run still completes, with
quietly different answers.

---

## Phase 1 — data · one afternoon

| Item | Why | Note |
|---|---|---|
| **`VOO.US` into `universe`, bars back to 2016** | The yardstick (ruling 2). `adj_close` is distribution-adjusted, so VOO gives **total return** for free | Fixes the price-index problem in one move. VOO's inception is 2010, so 2016 is clean |
| **`GSPC.INDX` backfill to 2016** | Currently starts **2023-08-01** — it, not the stock bars, is what caps the window at two years | Optional secondary reference; VOO is the yardstick |
| **Position returns from `adj_close` ratios; triggers, pivots and stops from raw OHLC** | `corporate_actions` holds dividends only from **2025-06-30** (2,084 rows), so dividends cannot come from there | Negligible for 6-day momentum holds; **material** for 290-day compounder holds. Doing it once, correctly, costs nothing extra |
| **`earnings` report dates back to 2016 from `raw_doc->'Earnings'->'History'`** | The `earnings` table starts **2025-06-27** (`CAL_BACK = 400`). Without this the blackout and M4 are unenforceable across most of the window | 2,949 tickers, avg 98.8 quarters, `reportDate` per quarter. **No new vendor call** |
| **Survivorship — in scope (ruled 2026-08-10)** | `universe` has 3,244 active and **2** delisted, and `backtest.py` filters `status='active'`, so the sim can never buy a name that later died | See below — cheaper than the review implied |

Bars themselves need nothing: **6,410,951 rows, 3,268 tickers, back to 2016-08-05**, with 2,050
tickers carrying the full depth.

### Survivorship, and why it costs less than it looks

The bias: we test on today's list of living companies. Every name that went bankrupt, got acquired
or was delisted between 2016 and now is simply absent, so the simulation cannot buy one. Momentum
buys names printing new highs, and some of those crash and delist — testing only on survivors
deletes the worst tail from the sample and flatters every number in every run to date.

The review implied a large rebuild. Reading the code more carefully, it is mostly one line plus one
ingest, because **L0 membership in the backtest is already derived from bars, not from a stored
flag**. `rank_week` computes it live:

```python
eff = live & (nbars >= 126) & (close[-1] >= 5) & (addv >= 10_000_000) & (nbars >= 210)
```

That is a point-in-time census by construction. A name with no bar on date *t* has `live = False`
and drops out of the ranking automatically on the day it stops trading. The only look-ahead is the
SQL above it — `where u.status='active' and (u.in_l0 or u.is_holding)` — which deletes the dead
before the census ever sees them.

So the work is three items, in order of size:

1. **Ingest the delisted census.** `get_exchange_tickers(exchange_code='US', delisted=True)` →
   `universe` rows with `status='delisted'`, then one EOD history call each. The budget is not a
   constraint: **100,000 requests/day, 11 used today**, so even a five-figure delisted list lands
   inside a single day.
2. **Drop the `status='active'` filter** in the backtest loader, and let `eff` do the census.
3. **Handle a position whose bars stop** — the one genuine new edge case. Today the daily mark
   carries `last_mark` forward when a bar is missing, so a delisted holding would be held at its
   final price forever and never exit. It needs an explicit rule: no bar for N sessions → exit at
   the last close, `exit_reason = 'delisted'`. Without item 3, item 1 makes the numbers *better*
   rather than worse, which is the trap.

Acceptance: `select count(*) from universe where status='delisted'` is four figures, not 2; and a
law-v0 run reports a non-zero `delisted` exit bucket.

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

## Decisions — all settled 2026-08-10

| # | Decision | Ruling |
|---|---|---|
| 1 | Survivorship | **In scope.** Delisted census ingested, `status` filter dropped, delisted-exit rule added |
| 2 | Starting capital | **$200,000 USD.** A scale factor on nothing that matters — the outputs are per-trade statistics and exposure percentages |
| 3 | Window start | **2016-08**, the full depth of the bars. Every run reports its first tradeable date after the 280-bar warm-up |
| 4 | Both sleeves on the same rails | **Yes.** Same triggers, same delta report, same VOO benchmark; the compounder side stays graded indicative-only per §4.8 |

---

## Sequence and rough size

| Phase | What | Size |
|---|---|---|
| 0 | Speed spike | **done — 5.8 min/run, no optimisation needed** |
| 1 | VOO + backfills + adj_close returns + earnings history + delisted census | one afternoon, plus the delisted ingest |
| 2 | `backtest.py` → driver over `signals.py`; three new `signals.py` functions; structural guard | the main build |
| 3 | law-v0 + conformance table with coverage + acceptance SQL | with Phase 2 |
| 4 | Differential test against the `armed` ledger, nightly | small, high value |
| 5 | Triggers: paths-filtered CI · dispatch · config stamp · Saturday | small |
| 6 | Baseline + delta report; letter line | small |

Phase 2 is the only large one, and most of its diff is deletion.

One line in `signals.py`'s own docstring already claims *"the nightly job, the weekly rank and both
backtests import from here."* Phase 2 is the commit that makes that sentence true.

---

## Build log — 2026-08-10

| Phase | State | What landed |
|---|---|---|
| 0 | **done** | 5.8 min/run on fixed tails; `tests/test_tail_equivalence.py` pins the tail against the full series, including one test that truncates below 266 bars and asserts divergence |
| 1 | **partly done** | VOO in the universe as `kind='index'` (untradeable by construction) · VOO + GSPC backfilled to **2016-08-12** with adjusted closes · **still to do:** the delisted census, and `earnings` report dates backfilled from `Earnings.History` |
| 2 | **done** | `backtest.py` is a driver; `confirmation_state`, `stalled_pyramid`, `enterable` and `m4_acceleration` moved into `signals.py`; `arming.py` and `fundamentals.py` call them too |
| 3 | **done** | 15-clause conformance table with per-clause coverage, written to `stats.conformance` |
| 4 | **to do** | the differential test against the `armed` ledger |
| 5 | **done** | paths-filtered CI · dispatch with window and label · config stamp on every run · **still to do:** the `check` amber when the stamp goes stale, and the Saturday chain entry |
| 6 | **done** | `backtest_report.py` — delta against `config.backtest_baseline_run_id`, job summary + PR comment, conformance-only exit code |

**Two bugs the engine tests found**, both of which would have produced a plausible wrong number
rather than a crash:

1. The entry loop scanned the base **through today**, so the very breakout it was meant to trigger
   on marked that base spent (`base_scan` returns `broken='breakout'` the moment a close clears the
   pivot). Nothing but marginal touches could ever have filled. It now reads last night's bars,
   which is what a resting GTC order actually does.
2. The config read invented key names — `momentum_min_mcn`, `mcn_exit` — that do not exist in
   `config`. Every run would have silently used the defaults while production read
   `score_thresholds`. This repo has already paid for that exact failure once: `score_thresholds.
   enter` was decorative for weeks because the code asked for `enterable` (learnings #21).

**One question for Zak, not settled here.** §3.2 says the unconfirmed hair-trigger applies "while
unconfirmed", and a name is unconfirmed from the EOD of its breakout day — the pending window
included. `arming.py` fires it only once the three-session window has *closed*. The backtest follows
the law; the nightly keeps its current behaviour; `signals.confirmation_state` carries both under a
flag and tests pin each, so neither can drift while the question is open. It is a live-rule change,
so it rides the slow lane (§5.8) and wants a ruling.

**Still parked, and now for a sharper reason:** the exit-rule ablation grid. A grid searched against
a baseline that enters names at MCN 15, over one bull regime, with no costs, on a survivor-only
tape, will faithfully find the parameters that fit those four defects. It gets unparked when
law-v0 is trusted, and not before.
