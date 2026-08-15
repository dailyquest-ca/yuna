# WO-A17 · The strategy, exactly — and the regime that produces its entire result

> ### ⚠️ Superseded in two specific places. The rest stands.
>
> **§3's central finding is stated too broadly.** "Zero of twenty-five configurations made money
> over 2007–2017" is true of twenty-five **ungated** configurations. With the regime gate reaching
> the banded book — it was inert when this was written — that decade returns +11.08% a year. The
> regime dependence is a property of momentum *held through downtrends*, not of momentum.
>
> **§3.1's decomposition lays separate runs end to end**, which does not compose: the nine-year run
> parks in SPMO and the twenty-year run parks in SPY, and under a gate the park *is* the return for
> every session the book is off.
>
> The current strategy of record is [`wo-a20-v2-decision.md`](wo-a20-v2-decision.md).
>
> **Still good here:** §1's rule and constants, §2, the clean-tape grid, §4's mechanism, and §5's
> established/not-established split.

**Written 2026-08-15.** Supersedes the recommendation in `wo-a15-v1-synthesis.md`, which named the
wrong cell on a defective tape. Every number here comes from runs 497–546, produced on a screened
tape by code at `49904e7`, and every one is reproducible to the digit.

This document has one job the earlier ones did not: **to be explicit enough that no question is
left to inference.** §1 is the rule with every constant. §2 is what changed and why. §3 is the
regime finding in full. §4 is the mechanism — *why* it behaves this way. §5 is what is and is not
established. §6 is what follows.

---

## 1. The strategy, stated completely

### 1.1 The one-paragraph version

Every session, rank every liquid US stock by its **12-month return skipping the most recent
month, divided by its 12-month realised volatility**. Hold **five** names, equally weighted, fully
invested. A holding is **sold when its rank falls past 12**. An unheld name in the **top 2**
takes the slot of the worst current holding, **one swap per session**. All fills happen at the
**next session's opening price**.

### 1.2 Every constant, with its source

| # | Constant | Value | Where it comes from |
| --- | --- | --- | --- |
| 1 | `FORMATION` | 252 sessions | 12-1 momentum, standard. `src/concentrated.py:103` |
| 2 | `SKIP` | 21 sessions | the skipped recent month. `:104` |
| 3 | `VOL_WINDOW` | 252 sessions | volatility denominator. `:105` |
| 4 | `L0_MIN_BARS` | 210 of 252 | minimum history to be rankable. `:106` |
| 5 | `L0_MIN_RAW` | $5.00 | price floor, on the **raw** print. `:107` |
| 6 | `L0_MIN_ADDV` | $10,000,000 | median dollar volume floor. `:108` |
| 7 | `ADDV_WINDOW` | 50 sessions | window for that median. `:109` |
| 8 | `top_by_addv` | 500 | pool narrowed to the 500 most-traded before ranking |
| 9 | `n` | 5 | positions held |
| 10 | `exit_rank` | **12** | eject when rank > 12 |
| 11 | `entry_rank` | **2** | an unheld top-2 name may displace |
| 12 | `sleeve` | 1.00 | fully invested, no cash reserve |
| 13 | `months` | 6 | the calendar rebalance, **inert** under the banded rule |

Switched **off**, deliberately, each having been measured and rejected: the trailing stop
(`trail=False`), the state door (`base_door=False`), the diversification floor (`rider=False`),
the volatility target (`vol_target=None`), the regime gate (`index_px=None` — advisory only, see
WO-A10).

### 1.3 The exact daily procedure

1. **Eligibility.** A name is rankable at session *i* if it has ≥210 finite bars in the last 252,
   its **raw** close ≥ $5.00, and its 50-session median of `adj_close × volume` ≥ $10m.
2. **Pool.** Of those, keep the 500 highest by that median. Ties broken by a **stable** sort — the
   engine's reproducibility depends on it (learning 25).
3. **Score.** `score = (adj[i-21] / adj[i-252] − 1) ÷ stdev(daily returns over 252 sessions)`.
   Sorted descending, stable.
4. **Exit gate.** Any holding whose rank is now worse than 12 is queued to sell.
5. **Entry gate.** If a slot is free, the best-ranked unheld name **inside the top 2** fills it.
   If no slot is free, that name **displaces the worst-ranked holding** — but only if it ranks
   strictly better. One displacement per session.
6. **Fills.** Everything decided at session *i* executes at session *i+1*'s **adjusted open**. If
   the name does not print that morning, the order is cancelled, not carried.
7. **Costs.** A spread charge by liquidity bucket, from `SPREAD_CURVE`: 5bps above $50m ADDV,
   10bps above $10m, widening to 60bps at the bottom. Total cost over 20 years: **$37,136**.

### 1.4 What "rank past 12" means, precisely

Rank 1 is the best-scoring name in the 500-name pool. A holding is sold the session **after** its
rank is worse than 12 — that is, at 13 or below. It is *not* sold at 12. The book therefore holds
names that have drifted from top-2 quality down to 12th before it lets them go, which is what
makes the average hold **31.7 sessions** rather than one.

---

## 2. What changed: 3/12 → 2/12

`wo-a15-v1-synthesis.md` named **entry 3 / exit 12**. That was chosen from a grid computed on a
tape carrying corrupt price series (WO-A16 §6b: 18 names with fabricated overnight moves, 55
trades, −$166,343, plus foreign listings quoted in roubles and baht). On a screened tape the same
grid gives a different answer.

**Entry-band column means, three windows:**

| entry band | 2007–2017 | 2017–2026 | 2007–2026 | verdict |
| ---: | ---: | ---: | ---: | --- |
| 1 | −3.80% | +51.31% | 17.38% | strong |
| **2** | **−2.61%** | +50.99% | **18.27%** | **best or 2nd on all three** |
| **3** | **−6.55%** | **+46.59%** | **14.93%** | **worst on all three** |
| 4 | −5.15% | +48.03% | 16.07% | weak |
| 5 | −4.35% | +50.79% | 17.92% | degenerate (see below) |

**Exit-band row means:**

| exit band | 2007–2017 | 2017–2026 | 2007–2026 | ranks |
| ---: | ---: | ---: | ---: | --- |
| 8 | −4.81% | 46.85% | 15.60% | 4, 5, 5 |
| 10 | −4.68% | 52.32% | 17.39% | 3, 1, 2 |
| **12** | **−3.56%** | 50.39% | **18.10%** | **1, 2, 1** |
| 14 | −4.30% | 49.03% | 17.04% | 2, 4, 3 |
| 16 | −5.11% | 49.11% | 16.45% | 5, 3, 4 |

**So the exit band was right all along at 12. The entry band was wrong at 3.**

### 2.1 Why cell selection used worst-case rank, not the maximum

`b5_10_2` has the highest CAGR on both the 20-year (20.57%) and 9-year (59.95%) windows. It is
**not** the recommendation, because those two windows are **nested** — 2017–2026 sits inside
2007–2026 and dominates its compounding. Their agreement is close to one observation, not two.

Ranking every cell by its **worst** rank across three windows, one of which (2007–2017) shares no
sessions with the nine-year grid:

| cell | worst rank | 2007–17 | 2017–26 | 2007–26 |
| --- | ---: | ---: | ---: | ---: |
| `b5_12_1` | 3 of 25 | −2.62% | 54.03% | 20.10% |
| **`b5_12_2`** | **4 of 25** | **−0.96%** | 52.03% | 19.84% |
| `b5_10_2` | 5 of 25 | −3.26% | 59.95% | 20.57% |
| `b5_14_1` | 6 of 25 | −2.67% | 51.12% | 18.65% |
| `b5_12_3` ← old choice | **17 of 25** | −5.22% | 48.03% | 16.51% |

`b5_12_2` is **the single best cell of all 25 on the disjoint window** (−0.96%, the least-bad) and
top-4 on the other two. `b5_10_2` wins the nested pair and falls to 5th on the independent one.

**Honest caveat:** `12_1`, `12_2` and `10_2` differ by about one CAGR point on the 20-year — inside
the noise. The defensible claim is **the region: entry 1–2, exit 12–14.** `2/12` is a defensible
point inside it, not a proven optimum.

### 2.2 Why entry 5 is excluded despite scoring well

At `entry_rank = n = 5` the rule degenerates. Any top-5 name not held displaces the worst holding,
so the book is dragged toward owning exactly the top 5 and the exit band never binds. It is a
different strategy wearing the same parameters — and it costs **2,527 trades against 777**.

---

## 3. The regime finding

### 3.1 The headline decomposes into two different strategies

Taken from run 508's **own equity curve**, split at the nine-year boundary — so this is a true
decomposition of the quoted figure and not two separate runs laid end to end (§3.4 explains why
that distinction is not pedantic):

```
2007-01-05 .. 2017-08-14   $99,950 →    $78,452    −2.26%/yr    −21.5% cumulative
2017-08-15 .. 2026-08-13   $79,621 → $3,473,235   +52.16%/yr      x43.6
──────────────────────────────────────────────────────────────────────────────
2007-01-05 .. 2026-08-13   $100,000 → $3,473,235  +19.84%/yr    (the quoted number)
```

Recomposing: `0.9774^10.61 × 1.5216^8.99` gives 19.75% a year, against the 19.84% the run reports.
The residual is the single session at the boundary. **The identity closes.**

**Zero of twenty-five configurations made money over 2007–2017.** Run separately on that window,
the whole 5×5 grid returns between −0.96% and −7.49% a year, every cell, each with a drawdown near
−80%.

### 3.2 Year by year — the book against SPY

| year | book | SPY | NAV at year end | note |
| ---: | ---: | ---: | ---: | --- |
| 2007 | +13.4% | +6.0% | $113,305 | |
| 2008 | **−69.7%** | −36.2% | $34,278 | lost **twice** the market |
| 2009 | −5.2% | +22.7% | $32,676 | **missed the recovery by 28 points** |
| 2010 | −0.8% | +13.1% | $33,611 | |
| 2011 | −25.2% | +0.9% | $25,971 | trough — down 74% from start |
| 2012 | +26.9% | +14.2% | $32,795 | |
| 2013 | +32.0% | +29.0% | $44,688 | |
| 2014 | +28.5% | +14.6% | $58,126 | |
| 2015 | −7.7% | +1.3% | $54,375 | |
| 2016 | +5.9% | +13.6% | $55,742 | **ten years in, still −44%** |
| 2017 | +48.5% | +20.8% | $82,138 | the regime turns |
| 2018 | −5.9% | −5.2% | $79,613 | |
| 2019 | +49.9% | +31.1% | $116,800 | back above water, year 13 |
| 2020 | **+146.9%** | +17.2% | $298,419 | |
| 2021 | +36.0% | +30.5% | $423,063 | |
| 2022 | +5.5% | −18.6% | $442,481 | **positive through a bear market** |
| 2023 | +34.3% | +26.7% | $581,038 | |
| 2024 | +64.7% | +25.6% | $913,541 | |
| 2025 | +75.7% | +18.0% | $1,670,691 | |
| 2026 | +102.5% | +14.5% | $3,473,235 | partial year, 154 sessions |

**It took thirteen years to get back above the starting NAV.** A real investor would not have been
there for year fourteen.

### 3.3 The per-trade expectancy is itself regime-dependent

This is the part that matters most, because it rules out the easy explanation. If the rule had a
constant edge and simply compounded on a larger base, the *average trade* would look the same in
every era. It does not:

| year | trades | win rate | **avg return per trade** |
| ---: | ---: | ---: | ---: |
| 2008 | 26 | 31% | **−17.17%** |
| 2011 | 59 | 41% | −2.56% |
| 2015 | 41 | 39% | −3.27% |
| 2021 | 33 | 39% | +0.62% |
| … | | | |
| 2020 | 41 | 68% | **+27.95%** |
| 2025 | 29 | 62% | **+26.06%** |
| 2026 | 9 | 56% | **+30.85%** |

**A 45-point swing in per-trade expectancy between 2008 and 2020.** The rule is not one edge
applied to varying capital. It is a rule whose payoff distribution changes completely with the
regime.

Full-period aggregates for `b5_12_2`: **777 trades, 54.2% win rate, average win +16.52%, average
loss −10.22%, profit factor 2.98, median hold 17 sessions, mean hold 31.7.**

Read those aggregates carefully, because they are the most misleading numbers in this document. A
54.2% win rate with a 1.6:1 win/loss ratio sounds like a stable, well-behaved edge. §3.3 shows it
is an average over two populations that do not resemble each other: a 31%-win-rate, −17%-per-trade
regime and a 68%-win-rate, +28%-per-trade regime. **No year in the record actually looks like the
average year.**

### 3.3a How long the book holds anything

Median hold **17 sessions**; mean **31.7**. The six-month rebalance clock in the spec is inert —
under the banded rule the book turns over on rank movement, not on the calendar, and it re-decides
every session. In practice this is a **three-to-six week** holding period, at ~40 entries a year.

That matters for two reasons the CAGR hides. It is a **taxable-turnover** strategy, which is why
the plan puts momentum in the TFSA (§2.6, and `.claude/rules/investment-tax.md`) — and it is why
`entry_rank = 5` must be excluded: it triples turnover to 2,527 trades without improving anything
that survives a window change.

---

### 3.4 A subtlety found while checking this section, which every reader needs

The same cell, the same window, the same code, run two ways:

| run | window | end NAV at 2017-08-14 | trades |
| ---: | --- | ---: | ---: |
| 558 | 2007-01-05 .. **2017-08-14** (standalone) | **$90,257** | 451 |
| 508 | 2007-01-05 .. 2026-08-13, sliced at 2017-08-14 | **$78,452** | — |

A 13% difference over identical settings and an identical decade. This is not non-determinism —
both runs reproduce exactly — and it is not a defect. It is a property of **back-adjusted prices**
that anyone reading these numbers has to understand:

> `adj_close` is computed by adjusting history backwards from the present. A mis-stated split
> factor in 2025 therefore corrupts that name's **entire prior series**, 2007 included. The tape
> screen quarantines such names whole, because their old bars really are wrong.

Run 508 loads 2006–2026 and can see breaks that occur after 2017. Run 558's tape stops in 2017 and
cannot. **The two runs are therefore simulating different eligible universes over the same
decade**, and neither is wrong — they answer different questions.

Three consequences, stated because they bind on every number in this document:

1. **A backtest on adjusted prices is unavoidably a hindsight exercise.** The adjusted series is by
   construction a function of every corporate action that followed. This is true of every study in
   this repository and of essentially every published equity backtest; it is not a defect
   introduced here, but it is rarely written down.
2. **Sub-window runs are not slices of longer runs.** Cross-window comparisons in §2 are valid for
   *ranking cells inside a given window*, which is what they are used for. They are **not** valid
   as a decomposition of a longer run. §3.1 therefore uses run 508's own curve.
3. **The direction here is conservative.** The run with more future knowledge (508) did *worse*
   over the early decade (−2.26% against −0.96%), so the screen is not flattering the result.

## 4. Why — the mechanism

Four mechanisms, each independently documented in the literature and each visible in this data.

### 4.1 Momentum crashes (Daniel & Moskowitz; Barroso & Santa-Clara)

Momentum's defining failure is not the crash itself but **the rebound**. After a market collapse,
the highest-momentum names are the defensive survivors; the violent recovery is led by the
beaten-down names momentum does not own. The strategy is left holding exactly the wrong book.

This is 2009 in one line: **the book returned −5.2% while SPY returned +22.7%.** A 28-point miss
in a year the market rose a fifth. 2008's −69.7% hurt more in the moment, but 2009 is what made
the decade unrecoverable, and it is the textbook signature.

### 4.2 Five names, but only ~2.4 independent bets

Measured effective bets: **2.435** (`1 / Σ wᵢwⱼρᵢⱼ`). This figure was 2.44–2.50 across all fifty
grid cells and both windows — **no band setting changes it.**

Momentum selects names that are rising for the same reason at the same time. The book says five
positions and behaves like two and a half. That is why the drawdown is −80% and not −40%, and why
no parameter inside the rule can fix it: the concentration is a property of *what momentum
selects*, not of how many slots you give it.

### 4.3 The 2017–2026 regime is exactly what this rule is built to exploit

Look at what the top trades actually are:

| ticker | entered | return | P&L | theme |
| --- | --- | ---: | ---: | --- |
| `WDC` | 2025-12 | +175.8% | $636,544 | memory / AI build-out |
| `SNDK` | 2026-02 | +162.3% | $412,513 | memory |
| `RKLB` | 2025-02 | +114.8% | $258,420 | space |
| `RGTI` | 2025-04 | +177.3% | $252,098 | quantum |
| `BE` | 2026-02 | +53.9% | $235,783 | fuel cells / power |
| `LITE` | 2026-01 | +52.7% | $225,767 | optical / AI |
| `PLTR` | 2025-03 | +132.1% | $221,971 | AI software |
| `OKLO` | 2025-07 | +123.6% | $217,376 | nuclear |
| `QBTS` | 2025-06 | +74.5% | $151,788 | quantum |
| `TSLA` | 2020-05 | +446.7% | $115,315 | the 2020 melt-up |

**Eleven of the top twelve trades were entered in 2025–2026.** Part of that is compounding on a
larger book — a 50% gain in 2026 is worth more dollars than a 400% gain in 2010 — but §3.3 rules
out compounding as the whole story, because **per-trade expectancy also tripled**, and that is
scale-free.

Look at what the names have in common. `WDC` and `SNDK` are the same trade (memory pricing).
`RGTI` and `QBTS` are the same trade (quantum). `RKLB`, `OKLO` and `BE` are the same trade
(speculative energy/space). `PLTR` and `LITE` are the AI complex. **Of the top ten positions,
there are perhaps four independent ideas** — which is §4.2's effective-bets figure of 2.435
appearing in the trade list rather than in a correlation matrix.

So the mechanism is: this rule pays when **persistent, thematic, multi-month trends exist in
liquid US equities**, and it pays most when several names ride the *same* theme simultaneously,
because then it holds all of them at once. 2017–2026 supplied that repeatedly — FANG, the 2020
melt-up, then AI/quantum/nuclear. 2007–2016 did not, and in 2009 it supplied the exact opposite.

### 4.4 What the rule has no defence against

The rule contains **no risk layer at all** — the trail, the state door, the diversification floor
and the volatility target are all switched off, each having been tested and found not to improve
the result. The consequence is that nothing in it responds to a change of regime. It ranks, it
holds five, it swaps. In a trending market that is its strength; in 2008–2011 it is why the
drawdown reached −80% and stayed there.

**One genuine counter-example deserves recording:** 2022. The book returned **+5.5% against SPY's
−18.6%** — a 24-point outperformance in a bear market. So the rule is *not* simply long beta to a
rising market. It found trends (energy, defence) when the index fell. That is real evidence
against the crudest version of the regime story, and it should not be argued away.

---

## 5. What is established, and what is not

### 5.1 Established

- **The arithmetic is exact.** Runs 457, 484 and 485 — same spec, three dispatches, one of them on
  changed code with the new path inert — agree on all 974 trades and all 4,932 equity rows, to
  every digit stored. `code_stamp` is what makes such comparisons valid (learning 37).
- **The tape is screened.** Seven defect classes found; four fixed (no tape screen in this driver;
  the guard's blind spot under $1 where reverse splits live; its blind spot across trading gaps;
  runs never audited). See WO-A16 §6b.
- **Every run now audits itself** against the raw tape, and a failed audit **fails the build**.
- **Entry band 3 is worst on all three windows**, including the disjoint one. Spearman between the
  disjoint windows is **+0.592** (the nested pair flattered itself at +0.872).
- **The first decade lost money in every configuration.**

### 5.2 Not established

- **The §2.5 verdict is `unproven`.** Deflated Sharpe **0.180** against a 0.95 bar, over **361**
  logged trials. Observed Sharpe 0.0396/session, 0.629 annualised.
- **The bootstrap 5th percentile is +0.67% a year.** Median 19.79%, 95th 41.48%. One run in twenty
  of this rule's own return distribution is a two-decade round trip to nothing.
- **No out-of-sample data exists.** All three windows were examined before the cell was chosen.
  2007–2017 is *disjoint*, not out-of-sample — it was used to select.
- **Kurtosis 10.16.** Fat-tailed to a degree that makes any single-number risk estimate optimistic.
- **The duplicate-listing defect is open**, at a measured size: `BBBY_old`/`BBBY` held concurrently
  for nine sessions in 2018. The scan correctly refuses to propose a threshold (WO-A16 §6d).
- **A −80% drawdown has never been tested against a human.** Every number here assumes the rule was
  followed through 2008–2011 without intervention.

### 5.3 What the jackknife says

Removing the best trades from the account, 20-year total return multiples:

| | multiple |
| --- | ---: |
| all trades | 33.75× |
| ex-best 1 | 27.38× |
| ex-best 3 | 20.67× |
| ex-best 5 | 15.79× |
| SPY | 6.91× |

**Even without its five best trades the book returns 15.79× against SPY's 6.91×.** The result is
not one lucky position. That is a genuine point in its favour, and it is compatible with everything
in §3 — the concentration is in a *period*, not in a handful of trades.

---

## 6. What follows

1. **`2/12` replaces `3/12`** as the cell of record, with the region entry 1–2 × exit 12–14 noted
   as equally defensible. This is a one-parameter correction to the entry band.
2. **No plan amendment should quote "19.84% a year."** The honest sentence is: *"−2.3% a year for
   the first decade, +52.2% a year for the last nine, and the second is the reason to be
   interested."* Anything shorter misleads.
3. **The regime question stops being advisory.** WO-A10 ruled the 200-day filter advisory because
   its edge concentrated in 2008–09. That reasoning inverts here: if the rule only works in one
   regime, knowing the regime is not a warning light, it is the strategy. **This is the highest-
   value open research question and it is not another band grid.**
4. **The −80% drawdown is the binding constraint on ever running this**, not the CAGR. It appears
   in every cell, on every window, and effective bets of 2.4 says it is structural.
5. **A forward record is the only evidence that moves a deflated Sharpe.** 361 trials of in-sample
   search cannot be undone by a 362nd.

**Nothing here has been merged toward production, and nothing in this repository places an order.**

---

## Appendix A — every run behind this document

| run | cell | window | sessions | CAGR | max DD | trades | purpose |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 508 | `b5_12_2` | 2007-01-05 .. 2026-08-13 | 4,932 | 19.84% | −82.5% | 777 | **the cell of record** |
| 531 | `b5_12_2` | 2017-08-15 .. 2026-08-13 | 2,261 | 52.03% | −51.2% | 332 | nine-year window |
| 558 | `b5_12_2` | 2007-01-05 .. 2017-08-14 | 2,671 | −0.96% | — | 451 | disjoint early window |
| 509 | `b5_12_3` | 2007-01-05 .. 2026-08-13 | 4,932 | 16.51% | −80.2% | 992 | the superseded cell |
| 497–538 | 5×5 grid | 2007–2026 | 4,932 | 14.07–20.57% | −80 to −86% | — | twenty-year surface |
| 515–546 | 5×5 grid | 2017–2026 | 2,261 | 43.21–59.95% | −46 to −59% | — | nine-year surface |
| 547–571 | 5×5 grid | 2007–2017 | 2,671 | −7.49 to −0.96% | −80 to −84% | — | disjoint surface |

(The id ranges interleave because the three grids ran concurrently; each is 25 cells, confirmed by
grouping on `trading_days`.)
| 485–490 | participation ladder | 2007–2026 | 4,932 | 16.14–18.08% | — | — | WO-A16 foreign gate |
| 457/484/485 | `b5_12_3` | 2007-01-05 .. 2026-08-13 | 4,932 | 15.4948% | −80.5949% | 974 | determinism proof |

Every run carries a `param_hash` and a `code_stamp`; comparisons are only valid where the stamp
matches (learning 37). Runs 497 onward were produced on a screened tape at `49904e7`; runs 439–496
were not, and their numbers are superseded.

## Appendix B — the seven defects behind the tape these numbers rest on

| # | defect | measured | status |
| --- | --- | --- | --- |
| 1 | foreign securities on `.US` tickers | 7 names, 21 trades, −$3,075 | gate built, threshold unruled |
| 2 | `concentrated.py` had **no tape screen** | 18 names, 55 trades, −$166,343 | **fixed** |
| 3 | guard blind under $1, where reverse splits occur | 136 names, 1,865 bars | **fixed** |
| 4 | guard blind **across trading gaps** | `CLSK.US` at 9,372× | **fixed** |
| 5 | duplicate listings held concurrently | `BBBY_old`/`BBBY`, 9 sessions | open; B7 detects |
| 6 | bar geometry violations | 1,432 bars | detected, **none reached a fill** |
| 7 | runs never audited against the raw tape | everything to WO-A15 | **fixed**, audit gates the build |

Checked and clean: zero duplicate `(ticker, date)` rows; SPY, VOO and SPMO carry no discontinuity
(worst sessions −10.9% and +14.5%, both real market days); cash identity reconciles within costs
of $37,136; positions never exceeded 5 in 4,932 sessions; 974 of 974 entries filled at the
adjusted open.

## Appendix C — how to reproduce any of it

```bash
# the cell of record, twenty years
gh workflow run backtest.yml --ref <branch> \
  -f research=concentrated -f cells=b5_12_2 \
  -f park=SPY.US -f calendar=SPY.US \
  -f start_date=2006-01-01 -f start_nav=100000

# the disjoint early window
  ... -f start_date=2006-01-01 -f end_date=2017-08-14

# the nine-year window (park SPMO, calendar defaults to VOO)
  ... -f park=SPMO.US -f start_date=2016-08-01
```

The window input is the **tape** start; trading begins 252 sessions later, after the formation
window fills. Every run writes to `backtest_runs`, `backtest_equity` and `backtest_trades`, then
audits itself via `src/verify_run.py` — **a failed audit fails the build.**
