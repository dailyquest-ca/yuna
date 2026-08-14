# Yuna — momentum research synthesis

**As of 2026-08-14 · window 2017-07-26 → 2026-08-12 · $200k start · US equities · costs charged**

This is the complete state of the momentum research, written to be read outside the repo. It
covers what was tested, what survived testing, what was found broken along the way, and what is
genuinely unknown. Every number is a measurement from a stored run, not a recollection.

---

## 1 · The headline, stated honestly

**No calendar-clocked version of this strategy beats holding SPMO once it is tested properly.**
Every rebalance clock tested — weekly, monthly, bi-monthly, semi-annual — is heavily sensitive to
*which dates* it rebalances on, and averaged across those dates none of them beats the ETF
risk-adjusted.

**The word "calendar" is doing real work in that sentence, and it was added on 2026-08-14.** The
arm in §11 removes the calendar entirely — continuous observation, conditional transaction — and
its centre returns **26.73% at Sharpe 0.980** against SPMO's 21.38% / 0.989 on the identical window,
moving only **2.4 points** across start offsets and **5.0** across rank lags where the calendar
moves 17.6.

**But the centre is not the number to carry.** A6's sensitivity grid, run after the falsifiers,
found the centre is the best cell in its own neighbourhood on *every* axis tested — exit band
either way, N either way, all below it. The family mean is **24.14% at Sharpe 0.917**: still ahead
of the ETF on return, still behind it risk-adjusted. Every cell is `unproven` on the deflated
Sharpe (best 0.788 against a 0.95 bar). So: the best-supported arm this programme has produced,
above the ETF on return, below it on Sharpe, and formally unproven. The default has not moved.

| clock | phases tested | mean CAGR | **spread across phases** | **mean Sharpe** | mean bootstrap DD | names/yr |
|---|---:|---:|---:|---:|---:|---:|
| weekly (5 sessions) | 5 (all) | **36.25%** | 14.1 pts | 0.970 | −51.2% | 247 |
| monthly (21 sessions) | 6 | 23.26% | 8.3 pts | 0.803 | −47.2% | 83 |
| bi-monthly (42 sessions) | 6 | 20.58% | 15.1 pts | 0.790 | −40.7% | 46 |
| semi-annual | 6 | 22.04% | 17.6 pts | 0.933 | −33.3% | 17 |
| **SPMO** (the bar) | — | **21.12%** | — | **0.987** | **−31.0%** | 0 |

**Read the Sharpe column. Every clock is below the ETF.** The best of them, weekly at 0.970, is
still under SPMO's 0.987 — and it gets there with 247 trades a year, a −51% expected drawdown and
$273k of spreads on a $200k account.

### The methodological error that produced the earlier version of this document

An earlier draft reported bi-monthly at "33.37% with a 2.0-point spread" and recommended it. That
spread was measured with `start_offset`, which drops the first few rebalances but **leaves the
calendar phase untouched** — every one of those cells still rebalanced in the same months. It
measured start-date sensitivity and was reported as phase stability.

The real test moves *which dates* the rebalance falls on. On the same bi-monthly cadence it gives
**15.1 points**, not 2.0, and the mean drops from 33.37% to **20.58% — below SPMO**. The calendar
version has only two phases at all, and they differ by 16.5 points (33.32% against 16.87%).

The reasoning behind that draft was also wrong on its own terms. "54 samples beats 18" predicted
that bi-monthly would be stable where semi-annual was not; measured properly, bi-monthly spreads
15.1 against semi-annual's 17.6. Sampling more often bought almost nothing.

### The weekly clock — and a reading of it that was too flat

Weekly returns **36.25% mean against SPMO's 21.12%** — about 1.7× — at a −51% expected drawdown
against −31%, also about 1.7×. Earlier revisions of this document called that **"leverage, not
edge"** on the strength of its 0.970 mean Sharpe, and left it there.

**That reading was too flat, and §13 corrects it.** The mean hides the distribution: **three of the
five weekly phases carry a Sharpe above SPMO's 0.987** (1.058, 1.026, 1.012), and one phase at 0.810
drags the average under. The arm's real defect was never that it was uniformly leverage — it was
that **you get one phase, and which one is decided by the weekday you started on.**

That is a fixable defect rather than a verdict, and §13 fixes it.

### What survives regardless

| finding | status |
|---|---|
| Restricting to large caps is worth ~10 points of CAGR | **holds** |
| A per-name trailing stop cuts expected drawdown from ~50% to ~31% | **holds across all phases** |
| Volatility-adjusting the momentum rank is worth ~12 points | **holds** |
| A market-regime gate is a bad trade | **holds on 2017–2026 — re-test at backfill** |
| The Barroso–Santa-Clara volatility governor adds nothing once a trail exists | **holds on 2017–2026 — re-test at backfill** |
| A market-observed re-entry door replaces the calendar's date luck | **holds — and returns 1.5%** |
| Raw return rises with sampling frequency | **holds** |
| Any *clock* beats the ETF risk-adjusted | **no — all four are below SPMO's Sharpe** |
| Separating the observation clock from the transaction clock removes the date sensitivity | **holds — 17.6 pts → 2.4 (§11)** |
| §3.2's percentage trail beats an ATR trail of the same intent | **only where the trail is the exit — 26.7% vs 15.6% on A6, a dead heat on the weekly arm (§13)** |
| The euphoria tighten earns its place | **holds — worth 2.55 pts (§11)** |
| A concentrated momentum book can be diversified to 5 effective bets | **no — the ceiling is ~3.7 at any N (§11)** |
| Semi-annual beats monthly · bi-monthly is stable · the calendar arm beats the ETF | **all withdrawn** |
| The 12-1 rank is a weak signal amplified by luck | **withdrawn — see §10's amendment** |
| A6's centre is a plateau | **no — it is a peak on every axis tested (§11)** |
| The weekly clock is uniformly "leverage, not edge" | **no — 3 of its 5 phases beat SPMO's Sharpe (§13)** |
| Staggering a clock's phases collects their mean | **holds — 32.13% against a 32.82% control mean (§13)** |
| Blending the phases lowers volatility | **no — they are one series; Sharpe fell 0.9465 → 0.9306 (§13)** |
| The weekly tranched centre is a peak, like A6's | **no — it is a plateau; 4 of 7 rungs above it (§13)** |
| Tranching is how you escape the phase lottery | **no — the daily book escapes it too, and returns more (§13)** |
| Tranching is worth doing anyway | **holds — a third of the turnover for 1.5 pts of CAGR (§13)** |
| §4.1's top-250 pool lift carries to a fast clock | **no — −2.9 pts on the weekly arm (§13)** |
| The weekly arm beats A6 risk-adjusted | **no — family to family, 0.905 against 0.917 (§13)** |

---

## 2 · The benchmarks everything is measured against

Same window, same costs, §2.5 statistics applied identically.

| | CAGR | max drawdown | bootstrap median DD | bootstrap p5 DD | longest underwater |
|---|---:|---:|---:|---:|---:|
| **SPMO** (Invesco S&P 500 Momentum) | **21.12%** | −30.95% | −30.95% | −42.86% | 23.2 months |
| VOO (S&P 500) | 15.45% | −33.99% | −33.99% | −46.32% | — |
| VOO/SPMO 50/50 | 18.44% | −32.42% | — | — | — |

**SPMO is the bar.** It is a liquid ETF, requires zero decisions, and returned 21.12% on this
window. Anything active has to beat that after costs and after honest statistics, or the correct
answer is to hold it.

---

## 3 · The strategy that was built

Rank the **500 most-traded US stocks** by twelve-month return skipping the most recent month
(12-1 momentum, the academic standard and SPMO's own published methodology), divided by realized
volatility. Hold the top **8**, equal weight. Rebalance on a fixed clock. Per name, run §3.2's
trailing stop:

- initial stop at **entry − 8%**
- once the name is **+15% from average cost**, trail **10% below its highest close since entry**
- tighten to **5%** when the close is more than 2 standard deviations above its own 50-day
- stops ratchet up, never down

Exits execute at the **next morning's open**. Everything not in a name sits in SPMO.

Every constant above traces to `docs/yuna_plan.md` §3.2. None was tuned.

---

## 4 · What the measurements say, axis by axis

### 4.1 The universe filter is the single biggest lever — **holds**

Identical rules, only the ranking pool changes:

| pool | CAGR | max DD |
|---|---:|---:|
| all ~3,000 liquid US names | 27.31% | −47.3% |
| top 500 by dollar volume | 36.02% | −46.9% |
| top 250 | 37.54% | −44.9% |

Ranking 12-1 momentum across the whole market reaches into small and mid caps where the signal is
mostly volatility that mean-reverts. Ranking inside the most-traded 250–500 is the neighbourhood
SPMO ranks in, and it is worth roughly **ten points of CAGR**.

*(These are the no-stop variants, which is why the drawdowns are large. They are included because
the pool comparison is cleanest without the stop confounding it.)*

### 4.2 The trailing stop is a real mechanism — **holds across every phase**

| | CAGR | bootstrap median DD | DSR |
|---|---:|---:|---:|
| no exit between rebalances | 36.02% | **−51.9%** | 0.897 |
| with §3.2's trail | 29.19% | **−31.0%** | 0.969 |

Six points of return for **twenty-one points of expected drawdown**. Critically, this effect is
stable across all six calendar phases (−30% to −39% with the trail, −47% to −52% without), which
is what separates it from the clock result below.

### 4.3 Volatility-adjusting the rank — **holds**

| rank | CAGR |
|---|---:|
| raw 12-1 momentum | 14.86% |
| 12-1 ÷ realized volatility | 27.31% |

Twelve points, larger than the effect of concentration, the clock, or any risk overlay. It is also
exactly what SPMO's published methodology does.

### 4.4 Risk overlays that do not earn their place — **rejected on 2017–2026; re-test at backfill**

| overlay | effect | status |
|---|---|---|
| market regime gate (index below its 200-day → go to park) | −6.2 CAGR points to save 2.3 points of drawdown | rejected on 2017–2026; re-test at backfill |
| Barroso–Santa-Clara volatility governor | −6.2 points for 1 point of drawdown, at 2× turnover | rejected on 2017–2026; re-test at backfill |

The governor was a genuine hypothesis — momentum crashes *are* forecastable from the strategy's
own realized volatility — but the per-name trail collects the same information and acts faster.

**The label matters.** Both overlays are crash insurance, and they are being priced on a window
that contains no momentum crash — no 2009, no 2001. An insurance policy tested only in years the
house did not burn down will always look like a waste of premium. What is established is that
**neither overlay pays for itself on 2017–2026**; what is *not* established is that they are
worthless. Both come back to the bench when the 2003–2016 backfill lands, and neither should be
described as "tested, rejected" without the window attached.

### 4.5 The clock — **withdrawn**

On the Jan/Jul phase, slower looked strictly better:

| clock | CAGR | max DD | names/yr | spreads paid |
|---|---:|---:|---:|---:|
| monthly | 33.59% | −39.4% | 83.5 | $108,332 |
| bi-monthly | 33.32% | −35.5% | 46.2 | $70,237 |
| quarterly | 30.95% | −32.2% | 32.0 | $46,967 |
| semi-annual | 32.07% | −31.3% | 16.7 | $32,310 |
| annual | 31.45% | −29.9% | 8.8 | $14,524 |

Then the phase test ran the same semi-annual rule started one month later:

| starting months | CAGR | DSR | §2.5 |
|---|---:|---:|---|
| **Jan/Jul** | **32.07%** | 0.965 | **proven** |
| Feb/Aug | 23.44% | 0.858 | unproven |
| Mar/Sep | 18.57% | 0.724 | unproven |
| Apr/Oct | 18.73% | 0.741 | unproven |
| May/Nov | 24.99% | 0.886 | unproven |
| Jun/Dec | 14.45% | 0.568 | unproven |

**17.6 points of spread from the starting month alone.** Quarterly spans 12.84% to 30.95%. Nine
years of semi-annual rebalancing is eighteen decision points — far too few to measure a calendar
against itself. That clock ranking was date luck and is withdrawn.

#### The frequency axis, measured properly

Every interval was then re-measured at several arbitrary start dates, so each row is a mean and a
spread rather than a single cell. Calendar months bottom out at monthly, so the axis continues in
sessions.

| interval | cells | mean CAGR | spread | mean Sharpe | mean bootstrap DD | names/yr | spreads paid |
|---|---:|---:|---:|---:|---:|---:|---:|
| daily | 2 | 37.01% | 0.6 | 0.939 | −56.4% | 861 | $416k |
| weekly | 3 | 38.17% | 7.2 | 1.003 | −51.8% | 247 | $273k |
| fortnightly | 3 | 33.22% | 4.5 | 0.963 | −46.4% | 147 | $167k |
| monthly | 5 | 32.79% | 2.1 | 1.021 | −44.5% | 84 | $98k |
| **bi-monthly** | 4 | 33.37% | **2.0** | **1.113** | −40.1% | 46 | $70k |
| semi-annual | 6 | 22.04% | 17.6 | 0.933 | −33.3% | 17 | $32k |

**The sampling benefit and the turnover cost cross at bi-monthly.** Below that interval the
ranking is stale and the estimate is noisy — semi-annual is both. Above it, the extra freshness
is real but is paid for in spread, whipsaw and drawdown faster than it earns.

Two cautions on reading the top of the table. Weekly's mean rests on three cells spanning 34.46%
to 41.68% — a 7.2-point spread, wider than monthly's or bi-monthly's, so its headline is the same
kind of lucky-offset number the 32.07% was. And daily's 861 names a year is three to four trades
every session, which is not a strategy a person with a job runs regardless of what it returns.

### 4.6 A loose sector cap is free — **holds, with a caveat**

| | CAGR | max DD | DSR |
|---|---:|---:|---:|
| uncapped | 32.07% | −31.3% | 0.965 |
| max 70% of book in one sector | 32.42% | −30.7% | 0.968 |

Costs nothing. *Caveat: `universe.sector` is the vendor's current label, not point-in-time — a
mild look-ahead, so the capped cell is not strictly comparable to the uncapped ones.*

---

## 5 · What the strategy actually holds, and why that matters

### The book is frequently one bet

The July 2026 book: **MU, SNDK, WDC, STX, LITE, CIEN, BE, AXTI** — the memory/storage/optical
complex. Eight names, one trade. Every one stopped out between 6 and 8 July, all at a loss, in two
to five sessions.

Measured against the plan's own §2.2 formula on the 126 sessions before entry:

| | |
|---|---|
| average pairwise correlation | **0.477** |
| **effective bets** (1 ÷ Σ wᵢwⱼρᵢⱼ) | **1.84** |

The plan flags any book below 4. This was 1.84. The January 2026 book was half gold miners (AU, B,
HL, KGC). This is not bad luck — it is what 12-1 momentum over a 500-name pool does, because the
names running hardest at any moment usually run for the same reason.

### The trade profile is healthy

150 closed positions on the champion cell: **54% hit rate, +8.7% average return, worst single
trade −15.5%, average hold 35 sessions.** The trail caps individual losses hard — no single
position ever lost more than 16%.

### The names it caught

Real large-cap winners, held through real moves: GE +74%, ENPH +74%, SQ +71%, OKTA +64%, ETSY
+50%, STX +51%, NVDA +40%, VRT +38%. And in the no-stop variants: MSTR +445%, AppLovin +629%.
The selection rule does find the names Zak named. The difficulty was never finding them.

### The risk number that matters more than drawdown depth

| | longest stretch without a new high |
|---|---|
| **the champion** | **26.4 months** (2021-11-15 → 2024-01-31) |
| SPMO | 23.2 months |

**More than two years underwater, longer than the ETF it is trying to beat.** It also lost to VOO
outright in 2023 (+14.8% against +26.8%). Maximum drawdown depth is the number usually quoted;
time-to-recovery is the one actually lived through, and it is worse.

---

## 6 · Execution mechanics are worth 6 points a year

The same rules, filled three different ways:

| model | execution path | CAGR | DSR | §2.5 |
|---|---|---:|---:|---|
| close-based | none — a modelling artefact | 31.75% | 0.962 | baseline |
| **intraday** | GTC stop resting at the broker | **25.89%** | 0.922 | unproven |
| **next-open** | reviewed at night, market-on-open | **32.07%** | 0.965 | proven |

Nothing about *which stocks to own* differs. The resting stop loses because it fires on intraday
spikes the close recovered from, surrendering the rest of each move. **Ruled: next-open.** The
accepted cost is that a crash between one close and the next open is unprotected.

---

## 7 · Defects found and fixed (why earlier numbers were withdrawn)

Every one of these was found by querying the trade ledger rather than reading a summary. They are
listed because they are the reason to trust the current numbers more than the earlier ones — and
because the same classes will recur.

| # | defect | effect |
|---|---|---|
| 1 | **Market holidays counted as sessions.** The session list came from the union of all tape dates; ~26 junk listings print on New Year's Day, VOO does not. The first session of each half-year landed there, no name cleared the $5 floor, the rank came up empty — so the book sold everything and bought nothing, parking in SPMO until July. Fired in 2018, 2019, 2020, 2026. | Every A4 cell was ~half-parked. Explained why all cells pinned to SPMO's exact −30.95% drawdown. |
| 2 | **Duplicate listings.** Vendor back-fills a renamed symbol *and* keeps the old one. On 2021-01-04 every book held BBBY + BBBY_old + OSTK + BYON — four slots, one company, through a +82.5% meme window. | 36 lines excluded across two migrations. |
| 3 | **Rebalance sized from cash alone**, ignoring carried names — a cell labelled `sleeve=1.00` really ran ~0.78. | ~0.2 CAGR points. |
| 4 | **Intraday stop tested against the entry session's own bar** — a look-ahead running backwards, stopping names out at prices that printed before the position existed. | Manufactured a 0.7-point loss it then attributed to realistic fills. |
| 5 | **Open positions stored NULL P&L**, so the jackknife could never reach a winner still being held. | The robustness test was silently disarmed on the arm that most needed it. |
| 6 | **Euphoria rule read a flat window as euphoric** (`> mean + 2×0` is any uptick). | Halted names returned on a 5% leash. |
| 7 | **Initial stop hard-wired to the module constant**, so the ladder probe that varied it varied nothing. | One robustness axis was never actually tested. |

---

## 8 · Statistical method

Every run is scored by `src/finding.py` against `docs/yuna_plan.md` §2.5:

- **Block bootstrap** — 63-session blocks, 10,000 draws, seed 0. Reported as median and 5th
  percentile of both CAGR and max drawdown.
- **Deflated Sharpe** (Bailey–López de Prado) against a **63-trial ledger**, using non-excess
  kurtosis and skew because this family's returns are violently right-skewed. Bar: 0.95. The work
  order's aspiration is 0.9987 (t ≈ 3); **nothing has ever reached it.**
- **Winner-exclusion jackknife** — does the result still beat the benchmark after deleting its
  three largest trades? The champion returns +952.6% ex-top-3 against the benchmark's +282%.
- **Out-of-sample cut** at 2025-08-01.
- **Robustness ladder** — every parameter moved one step either side, criteria fixed in advance.
- **Phase test** — the same rule on a shifted calendar. This is the test that broke the champion.

---

## 9 · What is genuinely unknown

1. **The window contains no momentum crash.** `prices` reaches 2003 for SPY alone; the stock
   universe starts 2016-08. There is no 2008 and no 2009 — the exact regime where concentrated
   momentum historically loses 60%+ in months. Every drawdown estimate here is resampled from a
   window that does not contain the event it most needs to model. Closing this requires a bulk
   backfill of ~3,000 names × 13 years. **Deferred to V2 by ruling.**
2. **Earnings are invisible.** The book holds through every earnings date with an 8% stop. A gap
   does not respect a stop.
3. **One bear market (2022) and a one-year OOS cut.** Not enough of either.
4. **No theme/correlation control has been priced** beyond the 70% sector cap.
5. **Nothing has been tested with a market-observed re-entry rule** — see below.

---

## 10 · The re-entry rule was tested. It passed the robustness test and failed the strategy test.

The calendar was removed entirely and replaced with a market observation: a slot fills the session
a qualifying name prints a new 252-day high; names leave only via the trail.

| | spread across arbitrary starting choices | mean CAGR |
|---|---:|---:|
| calendar rule (6 phases) | **17.6 points** | ~22% |
| event rule (5 start offsets) | **5.5 points** | **1.54%** |

**The phase sensitivity vanished, as predicted.** And the return vanished with it. The book is
fully invested throughout — eight names on essentially every sampled date — so this is not cash
drag. It is stable, and stably worse than the index.

**Why:** when a slot frees, only names printing a new high *that day* qualify. That is a handful
of names, so the book takes the best of a tiny set rather than the strongest name in the pool. It
becomes a portfolio of "whatever broke out today" instead of "the strongest names" — 155 distinct
names against the calendar's 128, only 44 shared, and a best trade of +60.6% against +169.7%. It
never held the 4-6x names at all.

### What the two results say together

- The calendar rule earns 32% on one phase and 14% on another → the return depends on **when** the
  rank is sampled.
- Removing the sampling date drops the return to ~1.5% → the return came from **holding
  top-ranked names**, which the door prevents.

Both point the same way: **the 12-1 rank has value that decays fast and unevenly.** Sampled at the
right moment on the right phase it produces a spectacular number; sampled the wrong way it
produces the index or worse.

**Amended 2026-08-14.** An earlier revision of this document closed the paragraph "that is a weak
signal amplified by luck, not a robust edge." **The frequency table already refuted that sentence
and I did not read it that way.** Raw return rose monotonically as the clock got faster, all the
way to daily. A signal that was only luck would do the opposite — acting on it more often would
average the luck out toward the index, not amplify it. Rising return under rising frequency is the
signature of information that is real and decays quickly; the Sharpe peak at bi-monthly is where
turnover cost overtakes what the freshness earns.

The supported reading is therefore **real signal, fast decay, one door design refuted** — the door
being the calendar, and the event-door replacement being the second design to fail. Not the signal.
§12 is what happened when the door was rebuilt a third time and the signal was left alone.

---

## 10b · The original next hypothesis, now answered

Monthly rebalancing re-bought a name within 45 days of stopping out of it **at a loss** 213 times,
average 13.5 days out of the name — and **111 of those 213 lost money again.**

That is not a clock problem. It is the absence of a **re-entry rule**: the book re-buys whatever
still ranks, including the name it was stopped out of a fortnight ago. The calendar was only ever
standing in for a rule, and a bad one — which is exactly why shifting it by a month changes
everything.

`docs/yuna_plan.md` §3.2 already legislates the answer, and this arm has no concept of it:

> *"A stop-out carries no cooldown — re-entry requires a valid base and all gates, nothing more."*

**A valid base is an observation of the market, not a date.** The obvious next experiment is to
replace the calendar entirely: hold up to N names, re-enter whenever a qualifying name presents a
valid setup and a slot is free. If that removes the phase sensitivity, the strategy is real. If
the result still swings 17 points on an arbitrary starting choice, it is not.

---

## 11 · The banded continuous book (WO-A6) — passes its falsifiers, fails its sensitivity grid

Full pre-registration and results: [`docs/wo-a6-banded-2026-08-14.md`](wo-a6-banded-2026-08-14.md).
Centre is **run 324** (`a6_floor0`), same window and same $200k as everything above; run 318 is the
identical earlier stamp, reproduced to the digit across a refactor.

### What changed in the design

Every previous arm welded the **observation clock** to the **transaction clock**: the date the rank
was sampled was also the date the book was forced to match it. That is what made the calendar
phase-sensitive (17.6 points) and what made the daily cell churn. A6 separates them:

- **Observation is continuous.** The rank is computed every session.
- **Transaction is conditional.** A name enters only when a slot is free *and* it passes a **state
  door** — within 10% of its own 252-day high, above its 50-day average, and that average rising
  over the last 10 sessions. A name leaves only when the trail takes it or its rank falls out of a
  **hysteresis band** at rank 40. Between rank 12 and rank 40 nothing happens: the book does not
  re-trade rank flicker.
- **A correlation rider** caps the book at two names per correlation cluster (single-linkage,
  ρ > 0.70, trailing 126 sessions), at formation only. It never forces an exit.

### The result

| | CAGR | Sharpe | max DD | total return | names/yr |
|---|---:|---:|---:|---:|---:|
| A6 centre (run 324) | 26.73% | 0.980 | −33.4% | +741.5% | 105.6 |
| **A6 family mean (6 cells)** | **24.14%** | **0.917** | ~−36% | — | 93–133 |
| SPMO, identical window | 21.38% | 0.989 | −30.9% | +456.2% | 0 |

The family row is the one to read, for the reason in "Where it fails" below.

**And it holds still when you shake it.** The two falsifiers the WO pre-registered:

| falsifier | what it perturbs | spread | bar | |
|---|---|---:|---:|---|
| start offset {0, +21, +42, +63} | which date the run begins | **2.39 pts** | ≤ 6 | **pass** |
| rank lag {0, +1, +5} | reading the rank *k* sessions stale | **5.00 pts** | ≤ 6 | **pass** |

Against the calendar's **17.6 points** on the same class of arbitrary choice. All six cells beat
SPMO, mean excess ≈ +4.5 points. The rank-lag test is the sharper of the two and was added by
amendment precisely because a start offset cannot see a specific-day effect: a door reading a slow
state should barely notice being read a week late, and this one barely does.

### Where it fails

**The centre is a peak on every axis the sensitivity grid moved.** WO-A6 §3 varied one parameter at
a time off the centre: exit band to 25 and to 60, N to 10 and to 15, the euphoria tighten off, an
ATR trail, a path-quality gate. **All seven land below the centre; not one lands above.** On the
four genuine small perturbations it is four out of four, a one-in-sixteen result under a coin flip.

| axis moved | CAGR | Sharpe | Δ |
|---|---:|---:|---:|
| — (centre) | 26.73% | 0.980 | — |
| euphoria tighten off | 24.18% | 0.910 | −2.55 |
| exit band 40 → 25 | 24.15% | 0.915 | −2.58 |
| exit band 40 → 60 | 23.68% | 0.915 | −3.05 |
| N 12 → 15 | 23.53% | 0.929 | −3.20 |
| N 12 → 10 | 22.55% | 0.852 | −4.18 |
| path-quality gate on | 20.18% | 0.839 | −6.55 |
| ATR trail | 15.58% | 0.603 | −11.15 |

The falsifiers asked **when** the rule looks and A6 barely noticed. The sensitivity grid asks
**what** it looks for, and the answer moves on every axis with the centre on top. That is the
signature of a value fitted to the sample whether or not it was fitted deliberately — and §1's spec
was written after the A4 results were on the table, so it was not independent of them. **The number
to carry forward is the family's 24.14% at Sharpe 0.917, not the centre's 26.73% at 0.980.** Read
that way, A6 is ahead of the ETF on return and behind it risk-adjusted, which is the same shape as
every other arm here — at a smaller magnitude, and without the phase sensitivity.

**The deflated Sharpe is 0.788 against a 0.95 bar** — and every cell in the grid is `unproven`, the
best of them at 0.788. At 187 logged trials the deflation asks the observed Sharpe to clear what
the best of 187 random searches would produce, and it clears it by z = 0.75: a 77th-percentile
result where the bar wants the 95th. Stated without softening: *having searched this hard, a Sharpe
this good would turn up by chance about one time in four.*

**The trial count is mine, not the strategy's**, and that cuts both ways. Every falsifier and
sensitivity cell also enters the ledger and raises the bar — correct behaviour, since any run is
still a look at the data, but it means **this number cannot be improved by running more cells.**
Only out-of-sample evidence moves it, which makes the 2003–2016 backfill the instrument that
decides A6 rather than another grid.

**And it trips the livability flag**: 105.6 names/yr is 2.03 trades a week, just over the WO's
2-per-week line. That is a ruling for Zak, not a number to tune.

### The rider works — and cannot fix what it was commissioned for

Turning §2's correlation rider off (one axis, run 325) costs 1.64 CAGR points and 0.054 Sharpe, and
lets the held book's worst correlation cluster grow from four names to eight. **A constraint that
improves the return is worth noting: stepping down the rank to the next uncorrelated name beats
taking the top name twice.**

But the continuous effective-bets read — §2's own reporting clause, now measured — says the rider
did not move the thing it was built for. p5 effective bets is **1.841 with the rider and 1.849
without**: the same number, and the same 1.84 that motivated §2 in the first place. Across the
centre's 2,213 measured sessions the book runs a mean of 2.90 effective bets, and **98.2% of
sessions sit below 5**.

Reading that back through §2.2's formula under an equicorrelation approximation, the implied average
pairwise correlation is ≈0.27 in a typical session and ≈0.49 in the worst 5%. Since
`k / (1 + (k−1)ρ̄)` tends to `1/ρ̄`, **the effective-bets ceiling is ≈3.7 in calm conditions and
≈2.0 in stress, at any book size.** Five effective bets needs ρ̄ ≤ 0.20 sustained, which a
large-cap momentum book does not have; adding names cannot help, because the ceiling is set by the
average correlation and not by the count.

**A concentrated momentum book is structurally a levered bet on one factor.** That is not a
parameter to tune, it is what the strategy is, and Q2's tail — nine of the twenty worst trades on
six macro dates — is the same fact seen from the other end. The honest response is a sizing
decision, which is Zak's.

### What the tail is actually made of

Nine of the twenty worst trades fall on **six dates** — the vaccine Monday, the Feb-2021 crypto/EV
unwind, the China-ADR leg, the tariff crash. **Zero of the twenty exited on an earnings gap**,
against a 6.0% base rate across all 949 trades. The risk this book carries is *thematic
correlation*, not single-name event risk, which is the risk the §2 rider is aimed at and the one an
earnings filter would not have touched. No earnings gate is legislated; the measurement is in the
WO under Q2.

### Two findings from the grid that stand on their own

1. **§3.2's percentage trail beats an ATR trail decisively** — 26.73% against 15.58%, and −33.4%
   drawdown against −53.3%. The 3×ATR(20) / +1R / 8×ATR(22) Chandelier holds positions roughly half
   as often and gives back far more of each move. The plan's stop is not an arbitrary set of
   percentages, and this is the first time it has been tested against a different *shape* rather
   than different levels.
2. **The euphoria tighten is worth 2.55 CAGR points and 0.070 Sharpe.** The 5% leash on a name 2σ
   above its own 50-day pays for itself, and had never been priced alone before.

### What has not been run yet

The WO's decision line is **not reached**. Outstanding: the B-arm — two tranches on alternating
bi-monthly dates, across six phases. It is built and tested but deliberately not run: every cell
enters the trial ledger and lowers A6's deflated Sharpe, so a fallback for an arm that is still
standing should exist without being priced. It gets run if A6 is abandoned, or on Zak's call.

---

## 12 · Where this leaves a V1

### Zak's rulings, 2026-08-14 — these override what follows

Four decisions were taken on the questions this document raised, and they change the frame rather
than the measurements. Full text in [`docs/wo-a7-2026-08-14.md`](wo-a7-2026-08-14.md) §0.

1. **Sleeve is 100%.** The park is a residual — unutilised cash — not an allocation. The §2
   effective-bets floor is **withdrawn**: it was measured unreachable at any N, and the
   concentration it was meant to prevent is now an accepted, explicit position.
2. **The 2-trades-per-week flag is cleared** at 2.03. Turnover is a reporting line, not a bar.
3. **Deployment goes ahead on the `unproven` verdict** — a start-low slice, with
   `docs/yuna_plan.md` amended first. **This retires the deflated Sharpe as a gate.** It cannot be
   met on 2017–2026 at any trial count and the backfill that would move it is declined. The DSR is
   still computed and still reported; it no longer decides. **No arm below is "proven" — a bar was
   removed, which is not the same as a bar being cleared.**
4. **Only work that could confirm or find a 30%+ return gets run.** That retired the bi-monthly
   B-arm — its own phase mean is 20.58%, below the ETF, and tranching collects a mean rather than a
   maximum — and opened WO-A7 on the weekly clock instead. **WO-A7 met the target: 32.13%,
   phase-independent.** See §13.

The recommendation below stands as the research conclusion. Ruling 3 is a decision to act ahead of
it, taken with the gap stated.

**Research conclusion: hold SPMO — with the best candidate this programme has produced sitting
behind it, and known to be weaker than its headline.**

SPMO returned 21.12% on this window with a −31.0% expected drawdown and a Sharpe of 0.987, and
requires no decisions, no infrastructure and no spreads. It remains the default because **nothing
here has cleared §2.5 in full**, and a default should not move on an `unproven` verdict.

Two things changed, in opposite directions, and both belong in the same paragraph.

**A6 broke the phase problem.** The sentence this document carried two revisions ago — *every active
variant is below the ETF risk-adjusted once the phase test is applied* — no longer describes the
whole picture. A6 moves 2.4 points across start offsets where the calendar moves 17.6, and every
one of its cells beats SPMO on return. Separating the observation clock from the transaction clock
was the right diagnosis.

**And A6's own sensitivity grid took most of the win back.** The centre is the best cell in its
neighbourhood on every axis tested, so the number that survives is the family's **24.14% at Sharpe
0.917** — ahead of the ETF on return, behind it risk-adjusted. That is a real result and a smaller
one than the 26.73%/0.980 the falsifiers alone suggested. I ran the falsifiers first and reported
them first; the grid is what a pre-registered §3 is for, and it is the reason the headline moved
down rather than up.

The honest position: **A6 is a candidate for a start-low live slice at family-mean expectations,
and the size is Zak's ruling — made knowing it is a ~2 to 3-effective-bet position, not a
twelve-name diversified book.**

### If an active book is wanted now

A6 is still the better answer than the weekly clock this document used to point at here. For the
record, the weekly clock returns **36.25% mean across all five phases against 21.12%**, but at
Sharpe 0.970, a −51% expected drawdown, 247 trades a year and $273k of spreads on $200k — that is
leverage, not edge. A6's family gets 24.14% at ~105 trades a year, a −36.6% bootstrap-median
drawdown and $107k of costs, and it survives the phase test the weekly clock does not. **Less
return, materially better mechanics, and the advantage does not depend on a start date.**

### What would actually change the picture

1. **The 2003–2016 backfill.** Every drawdown estimate here is resampled from a window with no
   momentum crash in it, and it is now also the *only* instrument that can move A6's deflated
   Sharpe — more cells can only lower it. This was already the largest single gap; A6 makes it the
   deciding one.
2. **A ruling on sizing, not on the floor.** §2's effective-bets floor of 5 was found to be
   unreachable at *any* book size, not merely at five names: the measured ceiling is ≈3.7 effective
   bets in calm conditions and ≈2.0 in stress. There is no version of this strategy that is five
   independent bets. What is left is a decision about how much capital belongs in a one-factor
   position, which is Zak's and not a parameter.
3. **A different signal — downgraded, not withdrawn.** The claim that 12-1 momentum is "weak and
   fast-decaying, and its strength came from *when* it was sampled" was written before A6, and the
   *when* half is now refuted: A6 keeps the same rank, changes only the door, and holds its number
   across every timing perturbation. The signal was not the problem; two door designs were. Ranking
   on something else is still worth doing, and it is no longer the only route left.
4. **The B-arm**, if A6 is abandoned. Built and tested, deliberately not run — see §11.

### The weekly arm, tranched (WO-A7) — the 30% target, met

Pre-registration and full results: [`docs/wo-a7-2026-08-14.md`](wo-a7-2026-08-14.md). Runs 333–338.

The weekly clock always had the highest returns in this programme and was set aside as "leverage,
not edge" on the strength of a 0.970 mean Sharpe. That reading was too flat: **three of its five
phases beat SPMO risk-adjusted**, and the mean was dragged under by one. Its actual defect was that
you get *one* phase, drawn from a 12–14 point spread, decided by the weekday you started on.

Tranching is the fix — five sub-books on five weekly phases, refreshing in stagger, held at once.
It is the machinery built for WO-A6's bi-monthly B-arm, pointed at the clock where the return
actually is. **The B-arm itself does not run and should not**: its own phase mean is 20.58%, below
the ETF, and tranching collects a mean rather than a maximum.

| | CAGR | Sharpe | bootstrap DD | trades/wk | 9-yr costs |
|---|---:|---:|---:|---:|---:|
| SPMO | 21.38% | **0.989** | −31.0% | 0 | 0 |
| A6 family mean (6 cells) | 24.14% | **0.917** | **−36.6%** | **2.03** | **$107k** |
| **weekly family mean (6 cells)** | **31.67%** | 0.905 | −50.0% | 6.55 | $248k |
| — w10_t5, the centre | 32.13% | 0.931 | −49.6% | 6.55 | $248k |
| — its five phase controls | 32.82% mean, 12.28 pt spread | 0.9465 | −49.2% | ~5.8 | $219k |

**Tranching converts the lottery.** 32.13% against a control mean of 32.82% — a 0.69-point gap, and
on bootstrap medians 32.71% against 32.63%, essentially exact. That was the pre-registered central
prediction and it holds.

**Two of the three predictions did not.** The blended Sharpe came in *below* the component average
(0.9306 against 0.9465) where it was predicted to beat it — the five phases hold the same names
offset by days, so they are effectively one series and blending buys no volatility reduction.
Tranching removed the *phase* risk, not the risk. And turnover ran 13% above the controls (340.7
against ~300/yr) on cross-tranche rotation, with costs tracking exactly.

### The grid ran, and it went the opposite way to A6's

Seven cells, mirroring A6's §3 axis for axis (runs 339–345). I predicted the weekly headline would
fall 2–4 points as A6's did, and pre-registered that landing within one point would mean the arm is
a plateau where A6 was a peak. **It landed within half a point: family mean 31.67% against a centre
of 32.13%, and four of the seven rungs came in ABOVE the centre.** A6's grid put zero of seven
above.

| | rungs above centre | family mean vs centre |
|---|---:|---:|
| A6 (banded) | **0 of 7** | −2.59 pts |
| weekly (tranched) | **4 of 7** | −0.46 pts |

**That contrast is the finding.** A6's centre is a fitted value; the weekly arm's is not. It is
also the reverse of what I expected when I recommended running this grid, and it changes which arm
looks better on the evidence rather than on the headline.

**One correction it forces.** §13 previously compared the weekly *centre's* Sharpe (0.931) against
A6's *family* Sharpe (0.917) and called the weekly arm marginally better risk-adjusted. Like-for-
like it is not: family against family, **0.905 against 0.917**. The weekly arm buys +7.53 points of
CAGR with 13 points more drawdown, 3.2× the turnover, 2.3× the costs, and slightly *worse*
risk-adjusted return.

Three more things the grid overturned, each worth carrying:

- **Tranching is not what escapes the phase lottery.** The un-tranched daily book (`d10_p0`) returns
  33.66% — 1.53 points *more* than the tranched centre — and it has no phase to be unlucky in
  either, because you cannot draw a bad weekday if you trade every weekday. Tranching is a
  **lower-turnover approximation of the daily book**: it gives up 1.53 points of CAGR for a third
  of the turnover (341 against 1,011 names/yr), +0.024 Sharpe, and 5.6 points less drawdown. A good
  trade, but a different claim than "it is how you beat the phase problem."
- **The ATR trail is arm-specific, not bad.** It cost A6 11.15 points and costs the weekly arm 0.10
  — at a quarter of the trading cost. On A6 the trail is the *only* exit; on a weekly clock the
  rebalance is, and the trail is a backstop. **No component's value should be quoted without naming
  its arm.**
- **§4.1's top-250 lift does not carry.** Predicted to be the rung most likely to beat the centre;
  came in second-worst at −2.92. That +1.5 was measured on no-stop variants at a slow clock, and I
  generalised it past its conditions.

**Flagged, not adopted:** `w10_n5` — five names, one per tranche — returns **37.76% on 180 names/yr**
(3.46 trades a week, *below* the centre's 6.55) at the centre's Sharpe, for a −58.6% drawdown. It
topped this grid, which is exactly why it does not get adopted off it. It needs its own centre,
controls and grid first.

### What was tried and did not work

- **Every rebalance clock** from weekly to annual — all phase-sensitive, all below SPMO's Sharpe.
- **A market-observed re-entry door** (WO-A6e) replacing the calendar — robust, and returned 1.5%:
  it filled the book with "whatever broke out today" instead of the strongest names.
- **A market regime gate** — costs 6.2 points to save 2.3, *on 2017–2026*; re-test at backfill.
- **The Barroso–Santa-Clara volatility governor** — the trail does the same job faster, *on
  2017–2026*; re-test at backfill.
- **An effective-bets floor of 5 at formation** — arithmetically unreachable as specified; it capped
  the book at 3.81 names and 32.6% deployed. Now known to be unreachable at *any* book size: the
  measured ceiling is ≈3.7 bets calm, ≈2.0 in stress. Not a number to fix.
- **An ATR trail** (3×ATR(20) / +1R / 8×ATR(22) Chandelier) in place of §3.2's percentages —
  15.58% against 26.73%, at a −53.3% drawdown against −33.4%.
- **A path-quality entry gate** (%-positive-days over formation, against the pool median) — blocked
  3,168 entries and cost 6.55 points. Momentum's payoff includes the names that gapped there.
- **An earnings-gap exit filter** — never built, because the measurement refused it: zero of the
  twenty worst trades exited on an earnings gap, against a 6.0% base rate.

None of this repo places, modifies, or cancels an order. Every trade is placed by hand.

---

### Reproducing any number here

Runs are stored in `backtest_runs` with `params`, `stats` and full equity and trade ledgers. Key
run IDs: **338** (`w10_t5`, the weekly tranched arm), **333–337** (its five N=10 phase controls), **339–345** (the weekly sensitivity grid),
**324** (A6 centre, `a6_floor0`; **318** is the identical earlier stamp), **319–323** (A6
falsifiers: start offsets and rank lags), **325** (rider off), **326–332** (the §3 sensitivity
grid), **286, 305–308** (the stored N=8 weekly phases), **317** (`a6_floor4`, the crippled book — kept as the record of the unreachable floor),
**309–316** (the first A6 pass, before the floor was diagnosed), **255** (calendar champion,
next-open), **229** (close-based), **230** (intraday), **256** (sector cap), **258–263** (phase
test), **251** (monthly), **87** (SPMO alone), **83** (VOO alone).

The cell name is in `params->>'variant'`. `stats->'bars_25'` carries the full §2.5 scoring —
bootstrap, jackknife, OOS cut, deflated Sharpe and the trial ledger it was deflated against.

The strategy code is `src/concentrated.py`; the §2.5 scorer is `src/finding.py`; the statistics
are `src/bars.py`. Work orders `docs/wo-a4-*`, `docs/wo-a5-*`, `docs/wo-a6-*` and `docs/wo-a7-*` carry the
pre-registrations — `docs/wo-a6-banded-2026-08-14.md` is the current one and holds the Q-query
answers in full.
