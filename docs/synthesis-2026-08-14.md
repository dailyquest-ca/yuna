# Yuna — momentum research synthesis

**As of 2026-08-14 · window 2017-07-26 → 2026-08-12 · $200k start · US equities · costs charged**

This is the complete state of the momentum research, written to be read outside the repo. It
covers what was tested, what survived testing, what was found broken along the way, and what is
genuinely unknown. Every number is a measurement from a stored run, not a recollection.

---

## 1 · The headline, stated honestly

**No version of this strategy beats holding SPMO once it is tested properly.** Every rebalance
clock tested — weekly, monthly, bi-monthly, semi-annual — is heavily sensitive to *which dates*
it rebalances on, and averaged across those dates none of them beats the ETF risk-adjusted.

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

### The one framing under which an active book still makes sense

Weekly returns **36.25% mean against SPMO's 21.12%** — about 1.7× — at a −51% expected drawdown
against −31%, also about 1.7×. Its Sharpe is essentially the ETF's. That is the signature of
**leverage, not of edge**: the same risk-adjusted return, scaled up. For a twenty-year horizon
with genuine indifference to drawdown that can be a rational thing to want, but it should be
called what it is, and it costs 247 trades a year and $273k in spreads to synthesise.

### What survives regardless

| finding | status |
|---|---|
| Restricting to large caps is worth ~10 points of CAGR | **holds** |
| A per-name trailing stop cuts expected drawdown from ~50% to ~31% | **holds across all phases** |
| Volatility-adjusting the momentum rank is worth ~12 points | **holds** |
| A market-regime gate is a bad trade | **holds** |
| The Barroso–Santa-Clara volatility governor adds nothing once a trail exists | **holds** |
| A market-observed re-entry door replaces the calendar's date luck | **holds — and returns 1.5%** |
| Raw return rises with sampling frequency | **holds** |
| Any clock beats the ETF risk-adjusted | **no — all four are below SPMO's Sharpe** |
| Semi-annual beats monthly · bi-monthly is stable · the arm beats the ETF | **all withdrawn** |

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

### 4.4 Risk overlays that do not earn their place — **holds**

| overlay | effect |
|---|---|
| market regime gate (index below its 200-day → go to park) | −6.2 CAGR points to save 2.3 points of drawdown |
| Barroso–Santa-Clara volatility governor | −6.2 points for 1 point of drawdown, at 2× turnover |

The governor was a genuine hypothesis — momentum crashes *are* forecastable from the strategy's
own realized volatility — but the per-name trail collects the same information and acts faster.
Tested, rejected.

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
right moment on the right phase it produces a spectacular number; sampled any other way it
produces the index or worse. That is a weak signal amplified by luck, not a robust edge.

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

## 11 · Where this leaves a V1

**Recommendation: hold SPMO.**

It returned 21.12% on this window with a −31.0% expected drawdown and a Sharpe of 0.987, requires
no decisions, no infrastructure and no spreads. Every active variant built here is below it
risk-adjusted once the phase test is applied, and the two that came closest did so by taking
substantially more drawdown.

That is a real conclusion rather than a failure. The research produced findings that are true
independent of the clock — the large-cap pool, the trailing stop, the volatility-adjusted rank,
and two risk overlays now known not to work — plus a test harness that found seven defects in its
own simulator and a statistical discipline that killed three of its own champions, including one
this document recommended two revisions ago.

### If an active book is wanted anyway

The weekly clock is the only variant returning materially more than the ETF: **36.25% mean across
all five of its phases, against 21.12%**. It is not better risk-adjusted — Sharpe 0.970 against
0.987 — so it is leverage rather than edge, and it costs a −51% expected drawdown, 247 trades a
year and $273k of spreads over nine years on $200k. Whether that trade is worth making is a
risk-posture call, and it should be made knowing it is a leverage decision.

### What would actually change the picture

1. **The 2003–2016 backfill.** Every drawdown estimate here is resampled from a window with no
   momentum crash in it. This is the largest single gap and it is a data problem, not an analysis
   problem.
2. **A different signal.** Nine years of testing says 12-1 momentum over a large-cap pool is a
   weak, fast-decaying signal whose apparent strength has repeatedly come from *when* it was
   sampled. Improving the clock has now been exhausted; the next real gain has to come from
   ranking on something else.
3. **A correlation control**, since the book is frequently a 1.84-effective-bet position.

### What was tried and did not work

- **Every rebalance clock** from weekly to annual — all phase-sensitive, all below SPMO's Sharpe.
- **A market-observed re-entry door** replacing the calendar — robust, and returned 1.5%.
- **A market regime gate** — costs 6.2 points to save 2.3.
- **The Barroso–Santa-Clara volatility governor** — the trail already does its job, faster.

None of this repo places, modifies, or cancels an order. Every trade is placed by hand.

---

### Reproducing any number here

Runs are stored in `backtest_runs` with `params`, `stats` and full equity and trade ledgers. Key
run IDs: **255** (champion, next-open), **229** (close-based), **230** (intraday), **256** (sector
cap), **258–263** (phase test), **251** (monthly), **87** (SPMO alone), **83** (VOO alone).

The strategy code is `src/concentrated.py`; the §2.5 scorer is `src/finding.py`; the statistics
are `src/bars.py`. Work orders `docs/wo-a4-*` and `docs/wo-a5-*` carry the pre-registrations.
