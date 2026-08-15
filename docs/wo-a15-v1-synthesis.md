# WO-A15 · The V1 momentum strategy — decision record and reproduction spec

> ### ⚠️ Superseded. Do not act on the recommendation.
>
> **The cell this document names, `b5_12_3`, was selected on a defective tape.** The discontinuity
> guard was blind below $1 and blind across trading gaps, so mis-stated split factors reached the
> book — 136 names, 1,865 bars, plus `CLSK.US` at 9,372×. Every cell was re-run on a screened tape
> and the ranking changed.
>
> The current strategy of record is [`wo-a20-v2-decision.md`](wo-a20-v2-decision.md).
> [`wo-a17-regime-synthesis.md`](wo-a17-regime-synthesis.md) superseded this one first, and was
> itself superseded in turn.
>
> **Still good here:** §1–2's reproduction spec (the *shape* of the rule is unchanged), §4's
> honesty section, and §5's merge conditions — one of which, the M4 differential test, is now
> `tests/test_refactor_parity.py`.

**Written:** 2026-08-15. Supersedes the recommendation sections of WO-A13 and WO-A14.
**Status:** research complete; **not adopted**. Adoption is a `docs/yuna_plan.md` amendment.
**Code:** `src/concentrated.py` at `9538139`, cell `b5_12_3`.

This document has three jobs. §1–2 state the strategy precisely enough to reimplement from
scratch. §3 records every decision with the evidence that produced it. §4 states honestly how far
the simulation can be trusted to reproduce — including where it currently cannot.

**Amended 2026-08-14.** Two changes, both in §4. The engine **is** bit-reproducible; the earlier
claim that it was not came from comparing runs built by three different versions of the code, and
§4.2 now says so. Separately, the universe was found to contain foreign securities carried under
`.US` tickers, which the vendor's own metadata does not admit — §4.3 records the measured cost and
[`wo-a16-foreign-listings.md`](wo-a16-foreign-listings.md) carries the finding. **Every number in
this document is pre-gate.**

---

## 1. The strategy

### 1.1 Eligible universe, evaluated on each session *i*

| filter | value | constant |
| --- | --- | --- |
| security type | US common stock, ticker matching `%.US`, `universe.kind = 'stock'` | — |
| exclusions | not present in `universe_excluded` | — |
| history | at least **210** finite adjusted closes within the trailing **252** sessions | `L0_MIN_BARS` |
| price | **unadjusted** close ≥ **$5.00** | `L0_MIN_RAW` |
| liquidity | **median** of (adjusted close × volume) over the trailing **50** sessions ≥ **$10,000,000** | `L0_MIN_ADDV`, `ADDV_WINDOW` |
| pool cap | of the survivors, the **500** highest by that same median, **stable sort** | `top_by_addv` |

The pool cap is applied **after** the other four filters. Dollar volume is the point-in-time proxy
for index membership; a real S&P membership series is not in the store and reconstructing one from
today's index would be look-ahead.

### 1.2 The score

```
past     = adj_close[i - 252]
recent   = adj_close[i - 21]
momentum = recent / past - 1.0

window   = adj_close[i - 252 .. i]        # 253 closes
rets     = diff(window) / window[:-1]     # 252 SIMPLE returns, not log
vol      = stdev(rets)                    # population sd, ddof = 0, NOT annualised

score    = momentum / vol                 # names with vol <= 0 are dropped
```

Rank descending by `score`, **stable sort**, so equal scores resolve in tape order (ticker
ascending). Rank 1 is best.

Three details are load-bearing:

1. **The momentum window ends 21 sessions ago**, not today — it measures 252-sessions-ago to
   21-sessions-ago. That skip is the whole point of 12-1.
2. **The volatility window ends today.** Momentum is a lagged signal, volatility is current risk.
   The asymmetry is intentional and is SPMO's own construction.
3. **`vol` is not annualised and the returns are simple, not log.** The score is a ratio so the
   annualisation factor cancels — but only if applied consistently. Do not "fix" it.
   `numpy.nanstd` defaults to `ddof=0`.

### 1.3 The book

- **5 positions**, each targeting **20%** of sleeve NAV.
- Sleeve fraction **1.00** — fully invested. Idle cash parks in SPMO.
- **No stop-loss of any kind.** Positions leave only by the rank rules below.
- **No concentration cap.** Sector weight is reported, never constrained.

### 1.4 The rank rules — evaluated every session, on every holding

Let **X = 12** (exit band) and **E = 3** (entry band).

1. **Forced exit.** Any holding whose rank is **worse than 12** (i.e. rank ≥ 13) is queued to sell.
2. **Displacement.** If the book is full, and some unheld name ranks **3 or better**, and it ranks
   better than the worst current holding, that worst holding is queued to sell.
   **At most one displacement per session**, and only on a strict improvement — so a book already
   holding the top five never trades.
3. **Fill.** Any empty slot takes the highest-ranked eligible unheld name from the **top 12** (the
   exit band doubles as the fill pool: a name good enough to hold is good enough to buy).

No state door, no path-quality gate, no diversification floor (`rider`), no volatility target.

### 1.5 Execution

- Decisions are computed from session *i*'s **close**.
- Every order fills at session *i+1*'s **open**, adjusted by that session's own adj/close factor.
- **Sells drain before buys within the session**, so proceeds fund the same-morning swap.
- An order that finds no print is **cancelled**, not carried — the rules re-propose against a
  fresh rank.
- Costs: §2.2's spread curve, charged per side on every traded dollar, as a function of the name's
  own median dollar volume.

### 1.6 Measured trading load

**47–50 round trips per year.** Roughly one position change a week.

---

## 2. Canonical results

Both runs at $100,000 start, survivorship-corrected universe, `code_stamp 08ff10e30092e78b`.

| | 9-year | 20-year |
| --- | ---: | ---: |
| window | 2017-08-15 → 2026-08-13 | 2007-01-05 → 2026-08-13 |
| sessions | 2,261 | 4,932 |
| park | SPMO | SPY |
| **CAGR** | **45.17%** | **15.49%** |
| benchmark CAGR | 21.50% | 11.15% |
| end NAV | $2,855,134 | $1,683,440 |
| **max drawdown** | **−48.53%** (2025-04-04) | **−80.59%** (2010-07-06) |
| Sharpe (annualised) | 0.989 | 0.548 |
| **bootstrap 5th %ile** | **+12.8%** | **−2.6%** |
| trades | 426 | 974 |
| exits: displaced / rank-band | 235 / 186 | 541 / 428 |
| effective bets | 2.48 | 2.48 |
| conformance | pass | pass |

**Plan capital around the 20-year row.** −80.6% is the drawdown this strategy has actually
produced, and the bootstrap floor is negative: in the worst 5% of reorderings of the same returns,
twenty years ends below where it started.

---

## 3. Decision record

Every row is a decision, what was tested, what the data said, and the ruling. Numbers are CAGR on
20yr / 9yr unless stated.

### 3.1 Decided by measurement

| # | decision | tested | result | ruling |
| --- | --- | --- | --- | --- |
| 1 | **Stop-loss** | trail vs none | trail cost 12.5 points and 27 points of drawdown on the deep test | **None** |
| 2 | **Exit band** | 6, 8, 10, 12, 14, 15, 16, 20, 25, 30 | **Noise.** 20yr spans 11.75–16.57 with no monotone structure | **12**, on a region not a peak |
| 3 | **Entry band** | 1, 2, 3, 4, 5 | **4 and 5 degenerate the rule** — see §3.3. 1–3 are live | **3** |
| 4 | **Displacement** | on vs off | +1.6 (9yr) / −0.8 (20yr) — ambiguous | **On**, structurally required |
| 5 | **State door** (WO-A6) | on vs off | −2.6 (9yr) / −0.7 (20yr), and exposure 92.9% vs 98% | **Off** |
| 6 | **Concentration cap** | none / 0.70 / 0.50 | not run — Zak ruled before measurement | **None** |
| 7 | **Regime filter** | plain 200-day, 12 latch variants | +6.4 points and bootstrap floor −3.4% → +5.6% over 20yr; **−9.45 points over the last 9** | **Advisory only** — displayed, never automatic |
| 8 | **Min history** | 189 / 210 / 252 | **not run** | 210 carried, unverified |

### 3.2 The band grid — the evidence behind decisions 2 and 3

**CAGR, 20-year.** Exit band (rows) × entry band (columns):

| exit ↓ / entry → | 1 | 2 | **3** | 4 | 5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 | 11.77 | 11.75 | 11.95 | 13.95 | 13.39 |
| 10 | 12.66 | 15.14 | 12.18 | 13.73 | 13.35 |
| **12** | 16.57 | 15.85 | **15.49** | 13.71 | 13.39 |
| 14 | 14.12 | 13.62 | 14.43 | 12.99 | 13.53 |
| 16 | 12.61 | 14.09 | 14.29 | 13.32 | 13.53 |

**CAGR, 9-year:**

| exit ↓ / entry → | 1 | 2 | **3** | 4 | 5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 | 38.35 | 38.89 | 42.10 | 44.58 | 44.03 |
| 10 | 45.01 | 48.64 | 41.71 | 43.34 | 43.60 |
| **12** | 47.05 | 46.04 | **45.17** | 41.94 | 43.57 |
| 14 | 44.18 | 43.63 | 44.69 | 42.86 | 43.95 |
| 16 | 43.66 | 45.02 | 44.28 | 42.88 | 43.98 |

**Max drawdown, 20-year:**

| exit ↓ / entry → | 1 | 2 | **3** | 4 | 5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 | −81.9 | −83.3 | −83.2 | −81.3 | −80.9 |
| 10 | −84.1 | −84.2 | −82.5 | −81.6 | −80.9 |
| **12** | −84.7 | −85.7 | **−80.6** | −82.2 | −80.9 |
| 14 | −83.7 | −85.7 | −81.2 | −83.3 | −80.9 |
| 16 | −84.2 | −84.5 | −80.9 | −82.8 | −80.9 |

**Trades per year, 20-year** — the only clean, monotone surface in the entire programme:

| exit ↓ / entry → | 1 | 2 | **3** | 4 | 5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 | 52 | 55 | 63 | 80 | 129 |
| 10 | 41 | 45 | 54 | 74 | 128 |
| **12** | 34 | 39 | **50** | 72 | 127 |
| 14 | 31 | 37 | 48 | 70 | 127 |
| 16 | 30 | 36 | 47 | 70 | 127 |

*Staggered weekly control: 15.02% / 44.79%, −82.5% / −48.7%, **166 trades per year**.*

### 3.3 Two findings that decided the shape

**Entry 4 and 5 degenerate the rule.** Zak, 2026-08-15: *"an entry band of 5 seems so noisy."* It
is worse than noisy. If any unheld name in the top 5 displaces the worst holding, the book is
pulled continuously toward owning exactly the top 5 and **the exit band never binds** — a holding
can only slide out while something better takes its place, which is a displacement anyway. The
entry-5 column is flat at 13.39 / 13.35 / 13.39 / 13.53 / 13.53 across every exit band, with
turnover pinned at 127–129 and drawdown pinned at −80.9. `b5_8_5` and `b5_5_5` (no band at all)
both return 13.39%. The mechanism is alive only at entry 1–3.

**Exit 12 topping all three live columns on the 20-year was 2008, not structure.** On 20 years
exit 12 was best at entry 1, 2 and 3. On 9 years the peak moves — entry 2 peaks at exit 10, entry 3
at exit 14. The columns are not independent: they share a tape, and one holding's survival at a
band of 12 through the crash propagates to all three. **This is why 12 is defended as "in a flat
region", not as "the winner".** Within entry 3, exits 12/14/16 give 15.49 / 14.43 / 14.29 on 20yr
and 45.17 / 44.69 / 44.28 on 9yr — a 1.2-point band, which is inside the noise.

### 3.4 What the band rule is actually worth

**Not return.** Every cell in the grid sits inside the control's range on both windows. Twenty-five
configurations, two windows, and none beats the staggered weekly book by a margin that survives a
change of window.

**Turnover.** 50 trades a year against 166 — a **70% reduction** for a return statistically
indistinguishable from the control, and a drawdown that is equal or slightly better on both
windows. That is the honest case for adopting it, and it is the only claim here supported by a
clean monotone surface.

### 3.5 Decided by ruling, not measurement

| decision | ruling | date |
| --- | --- | --- |
| Sleeve fraction 100%, idle cash to SPMO | Zak | 2026-08-14 |
| Account: TFSA only | plan §2.6 | pre-existing |
| Starting capital $100,000, no contributions | Zak | 2026-08-14 |
| No concentration cap — "80% in one sector is what momentum IS" | Zak | 2026-08-14 |
| Regime filter advisory, not automatic | Zak | 2026-08-14 |
| Same-morning swap: sell and buy both at the next open | Zak | 2026-08-14 |
| Report 20-year, 9-year and crash windows, decided in advance | Zak | 2026-08-14 |
| Exit band 12, entry band 3 | Zak | 2026-08-15 |

---

## 4. Reproduction and soundness

### 4.1 What is pinned

- `param_hash` covers the full cell spec including the window; `code_stamp` covers the source.
  Both are stored on every run.
- Both sorts that decide membership are now **stable**: the score sort (`rank_at`) and the
  universe pool selection (`top_by_addv`). Before 2026-08-15 the second was not, and fixing only
  the first was half a fix.
- 528 unit tests. The band rule's specific behaviours are pinned: displacement admits a top-3 name
  to a full book; a book holding the top five never trades; the book never exceeds its slot count
  on either fill path; a displaced slot refills the same morning unless `swap_gap` is set.

### 4.2 Reproducibility — settled, and the earlier reading of it was wrong

**The engine is bit-reproducible.** Runs 457 and 484, same spec, same code, dispatched an hour
apart, on the 20-year window:

| | run 457 | run 484 |
| --- | ---: | ---: |
| CAGR | 0.154948350433643 | 0.154948350433643 |
| end NAV | $1,683,439.66482761 | $1,683,439.66482761 |
| max drawdown | −0.805949264478038 | −0.805949264478038 |
| total return | 15.8428138466003 | 15.8428138466003 |
| trades | 974 | 974 |
| displaced / band | 541 / 428 | 541 / 428 |

Identical to the last digit stored. Diffed below the headline as well: the 974 trade rows match in
both directions with zero rows on either side, and all **4,932 equity rows agree on NAV and on
position count**. There is no drift to characterise.

**The earlier version of this section drew the opposite conclusion from the same table, and the
refutation was a column it printed.** Runs 422, 440 and 457 carry code stamps `d00ee243`,
`3b831e96` and `08ff10e3` — three different engines, not three runs of one. 422 and 440 predate the
stable-sort fixes. They were never evidence of non-determinism, and the search for a cause was a
search for something that was not happening.

The lesson worth keeping: `code_stamp` exists precisely so that runs can be compared only when it
matches, and a comparison that ignores it is not a comparison.

Consequently:

- a golden parity vector **can** be written, and run 484 is a valid one to pin against;
- differences between runs at equal `code_stamp` are real, not noise;
- the live daily desk can be held to the strategy that was measured.

What this does **not** establish: reproducibility across a code change, across a numpy or pandas
version, or against a tape that has since been re-ingested. The pinned requirements exist for the
second of those; the third is what §4.3's data-quality items are about.

### 4.3 Other limits on the evidence

- **No out-of-sample data exists.** All twenty years were examined, and the configuration was
  chosen after examining them. A re-run on this tape is not validation. The genuinely clean tests
  are a forward record starting now, and the same rule unchanged on another market — both recorded
  as future work, neither done.
- **~200 distinct specs have been run** in this programme. The deflated Sharpe for this family
  reads `"not scored"`. The claim is undiscounted for that search.
- **Execution convention moves the result by up to 6 points** and is not settled. Next-open
  same-morning is used because it is what will actually be traded, not because it scores best.
- **Duplicate listings are unfixed.** `src/dedupe_scan.py` is built and report-only; it cannot be
  dispatched from a feature branch because GitHub only registers `workflow_dispatch` for workflows
  on the default branch. The book can still hold one company twice.
- **The universe carries foreign securities on `.US` tickers** — `PLZL.US` is Polyus in roubles on
  MOEX, and EODHD's own metadata calls it NYSE / USD / USA. Their local-currency price × volume
  clears the $10m liquidity gate on an FX rate. Seven confirmed names traded 21 times in run 484
  for **−$3,075 against +$1,601,608, or −0.19%** — real, negative, and not the source of the
  headline. The gate is built (`min_participation`) and the ladder that prices its threshold is in
  [`wo-a16-foreign-listings.md`](wo-a16-foreign-listings.md). **The universe-wide count is still
  unknown**, and the numbers in this document are pre-gate.
- **Effective bets is 2.48** across all fifty grid cells, both windows. The five-name book is
  approximately a two-and-a-half-name book, and no band setting changes that.
- **Min-history 210 was never measured** (189/210/252 not run).

---

## 5. What adoption would require

1. `docs/yuna_plan.md` §3.2 carries the rule and all nine constants explicitly.
2. ~~The reproducibility defect in §4.2 closed~~ — settled; a golden parity vector still to be
   written, and run 484 is the vector to pin.
3. The dedupe scan run and applied.
3b. A threshold ruled for the participation gate (WO-A16), and the chosen cell re-run under it.
4. The M4 refactor in `src/fundamentals.py` covered by a differential test before it reaches main.
5. The daily desk built to `docs/wo-a11-daily-desk-spec.md`, against the amended plan.

Nothing in this document has been merged toward production. The strategy is research output,
measured and recorded, awaiting a plan amendment that is Zak's to write.
