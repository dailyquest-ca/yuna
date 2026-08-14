# Yuna — momentum research synthesis

**As of 2026-08-14 · window 2017-08-15 → 2026-08-12 · 2,260 sessions · $200k start · US equities ·
costs charged · next-open execution**

This is the complete state of the momentum research programme, written to be read outside the repo
by someone assessing it independently. Every number is a measurement from a stored run, identified
by run ID, not a recollection. Where a number has been withdrawn or corrected, the correction is in
the text rather than quietly applied.

**Read §3 and §4 together or not at all.** §3 is the case for the selected strategy; §4 is the case
against it, and the case against is specific and load-bearing.

---

## 1 · The decision

**Zak's selection: the five-name weekly staggered book with no trailing stop** (`w5_notrail`, run
350). Chosen on 2026-08-14 after the adversarial audit in §4, with its objections on the table.

| | CAGR | Sharpe | max DD | bootstrap DD | entries/yr | 9-yr costs |
|---|---:|---:|---:|---:|---:|---:|
| **w5_notrail** (selected) | **43.91%** | 0.954 | −48.7% | −60.2% | 165 | $141k |
| A6 banded book, family mean | 24.14% | 0.917 | −36.6% | −36.6% | 106 | $107k |
| **SPMO** (the bar) | 21.12% | **0.989** | −30.9% | −30.9% | 0 | 0 |
| VOO (S&P 500) | 15.45% | 0.865 | −34.0% | −34.0% | 0 | 0 |

$200,000 → **$5,273,482** over 8.97 years.

**The standing research recommendation was against this arm** — §4.3 sets out why, and that
recommendation has not changed. Zak has read it and chosen the arm anyway, on a stated objective of
highest compounding with drawdown explicitly accepted. That is a risk-posture decision, it is his to
make, and the rest of this document is written to support it honestly rather than to re-argue it.

**Nothing here is `proven` under the programme's own statistical bar.** See §8.

---

## 2 · The strategy, specified

Precise enough to implement from this section alone.

### 2.1 Universe and ranking

1. Take all US-listed common stocks, living and delisted (survivorship-free).
2. Filter to the **500 most-traded by 50-session median dollar volume**, measured point-in-time.
   Additional floors: price ≥ the plan's minimum, ≥ the plan's minimum bar count in the formation
   window.
3. Score each name: **twelve-month return skipping the most recent month** — `close[t−21] /
   close[t−252] − 1` — **divided by realized volatility** over the trailing volatility window.
4. Rank descending. This is SPMO's published methodology plus a volatility denominator.

### 2.2 The book — five slots on five weekly phases

The account holds **five names, equal weight, 20% each, fully invested.** Idle cash sits in SPMO,
as a residual rather than an allocation.

Each slot is on its own weekly review cycle, staggered one weekday apart:

| weekday | slot reviewed |
|---|---|
| Monday | 1 |
| Tuesday | 2 |
| Wednesday | 3 |
| Thursday | 4 |
| Friday | 5 |

**On its review day, a slot does one thing:** if the name it holds is still the highest-ranked name
not held by another slot, keep it. Otherwise sell it and buy the one that is.

That is the whole rule. The staggering is what removes the "which weekday did you start on" problem
— see §5.3.

### 2.3 Exits

**There is no stop.** A name leaves only when its slot's weekly review replaces it. This is the
selected arm's single deviation from `docs/yuna_plan.md` §3.2, it is the largest open question in
the programme, and §4 is about it.

### 2.4 Operating load

165 new positions a year — **about 3 buys and 3 sells a week**, arriving as one slot review per
weekday. Most reviews are "keep." Realized trading cost over nine years: **$141,368**, charged in
every number in this document.

### 2.5 Configuration of record

`n=5, tranches=5, every_sessions=1, top_by_addv=500, risk_adjusted=True, trail=False, sleeve=1.00`,
park `SPMO.US`. Run 350.

---

## 3 · The case for it

### 3.1 It beats the benchmark by a wide margin on every cut

| | w5_notrail | SPMO | 
|---|---:|---:|
| CAGR | 43.91% | 21.12% |
| total return | **+2,538.6%** | +456.2% |
| bootstrap median CAGR | 43.21% | 21.31% |
| bootstrap 5th-percentile CAGR | 10.72% | 10.39% |
| out-of-sample cut (2025-08 → 2026-08) | **+160.7%** | +33.6% |
| skew | **+0.37** | −0.36 |

The bootstrap is 10,000 draws of 63-session blocks, seed 0. Even its **5th percentile clears SPMO's
5th percentile** — the pessimistic case is not worse than holding the ETF's pessimistic case.

**Positive skew is unusual and worth noting.** Most leveraged-looking equity strategies have
negative skew — small gains, occasional catastrophes. This one is the other way round: the A6 banded
book runs −0.63, SPMO runs −0.36, and this runs **+0.37**. Its return distribution has a long right
tail, not a long left one. Kurtosis is 8.15, so the tails are fat in both directions.

### 3.2 It is not a handful of lucky trades

Trade-level jackknife — recompute the result with the best trades deleted:

| | total return multiple |
|---|---:|
| all trades | 26.08× |
| **excluding the best 3** | **14.39×** |
| excluding the best 5 | 11.11× |
| SPMO | 4.56× |

**Delete its five best trades and it still triples the benchmark.** 1,468 trades across 238 distinct
names over nine years.

### 3.3 It survives the execution-lag falsifier

The concern, raised in §4 and tested: the rank is computed from bars up to and including session
*i*, and the book then trades at session *i*'s close — a one-bar advantage nobody can take, since
you need that close to compute the rank. This had **never been tested on any calendar arm** in the
programme; the falsifier was wired to a different code path.

| | lag 0 | lag 1 | lag 2 |
|---|---:|---:|---:|
| w5_notrail | 43.91% | **43.08%** | 46.59% |
| the stopped centre | 37.76% | 37.01% | — |
| **advantage** | +6.15 | **+6.07** | — |

Reading the rank a full session late costs **0.83 points** and the advantage over the stopped
version is unchanged. The one-bar edge is real, worth ~0.8 points to *every* calendar arm in the
ledger, and applied evenly. It is not what produces this result.

### 3.4 Removing the stop lengthened holds rather than removing protection

| | stopped centre | w5_notrail |
|---|---:|---:|
| trades | 1,617 | 1,468 |
| average hold | **10.4 sessions** | **23.7 sessions** |
| average P&L per trade | +2.29% | **+6.87%** |
| losses worse than −10% | 276 | **205** |
| average size of those | −14.5% | −20.1% |

The big losses get **deeper but fewer**, and the aggregate damage is roughly unchanged. What changes
is the winners: they run more than twice as long. On this arm §3.2's stop was cutting winners, not
protecting against losers.

### 3.5 The mechanism, measured

The stopped version stopped out of a name and re-bought it within 21 days **78.6% of the time**,
averaging 6.4 days out. One name (ACL) was round-tripped **28 times in ten months for a net $294**.
Testing the obvious fix — refusing re-entry without a valid base — made everything **worse** by 10.76
points, which identified the actual causal chain:

> **The stop creates the loss. The re-entry repairs it. Removing the stop avoids it entirely.
> Blocking the repair while keeping the stop is the worst of the four.**

---

## 4 · The case against it

### 4.1 The advantage is two years, and both are the same kind of year

| year | stopped centre | w5_notrail | gap |
|---|---:|---:|---:|
| 2017 (part) | +7.0% | 0.0% | −7.0 |
| 2018 | −25.3% | −25.1% | +0.2 |
| 2019 | +38.5% | +42.7% | +4.1 |
| **2020** | +116.3% | **+169.0%** | **+52.8** |
| 2021 | +33.1% | +30.8% | −2.2 |
| **2022** | +4.8% | **−1.5%** | **−6.3** |
| 2023 | +32.2% | +44.1% | +11.9 |
| **2024** | +99.7% | +62.1% | **−37.6** |
| **2025** | +11.9% | **+71.3%** | **+59.5** |
| 2026 (part) | +80.6% | +78.0% | −2.6 |

**The entire +6.15-point advantage comes from 2020 and 2025.** In the other eight years the no-stop
book is *behind* in five, including by 37.6 points in 2024. Remove those two years and removing the
stop is a mild deterioration.

**2020 is COVID. 2025 is the April tariff crash. Both are V-shaped: crash, then snap back.** The
mechanism is plain — in a decline that recovers quickly, the stop sells the bottom and the no-stop
book holds through it.

**Now read 2022, the only grinding bear market in the window. The no-stop book loses 6.3 points
there.** When a decline is slow and does not snap back, §3.2's stop earns its place exactly as the
plan intends.

### 4.2 The window contains no momentum crash

Every drawdown estimate in this document is resampled from 2017–2026. **There is no 2008 and no 2001
in it.** Momentum crashes are grinding declines, not V's — which is the shape the selected arm
handles worst, on the one example available.

A no-stop, five-name, 100%-invested momentum book is precisely the configuration a momentum crash is
most dangerous to. The measured cost of removing the stop is 1.6 points of bootstrap drawdown. **The
unmeasured cost is the left tail this window never sampled, and no number in this document can size
it.**

### 4.3 The research recommendation, unchanged

> On a window whose crashes all snapped back, removing the stop was worth 6 points, and the two
> years that produced it were both snap-backs. In the one grinding decline available, it cost 6.3.
> **Removing the stop is a bet that the next crash is a V.**

This is not a claim that a number is wrong. Six adversarial checks were run (§4.5) and five cleared.
It is a claim that **the thing the arm depends on is not in the data.**

### 4.4 Three further caveats the audit did not resolve

**End-point sensitivity.** The headline moves a lot depending on where the clock stops:

| end date | w5_notrail | stopped centre |
|---|---:|---:|
| full run | 44.03% | 37.86% |
| one week earlier | 44.09% | 37.42% |
| one month earlier | 45.75% | 39.03% |
| three months earlier | 48.69% | 40.10% |
| six months earlier | 39.53% | 33.54% |
| one year earlier | 34.91% | 31.47% |
| **range across endpoints** | **24.7% – 51.1%** | 21.8% – 41.6% |

**100% of terminal NAV sits in open positions**, carrying $881k of unrealized gain. The *relative*
advantage held at every endpoint tested (+3.4 to +8.6 points), but **43.91% is not a stable number
and should never be quoted as one.**

**Drawdown depth and frequency.** Five separate ~45% drawdowns in nine years — 2018-12 (−44.5%),
2020-03 (−43.9%), 2021-05 (−46.3%), 2022-01 (−46.7%), 2025-04 (−44.9%). Roughly one every eighteen
months. Bootstrap median −60.2%.

**Year-to-year variability is extreme and not reducible.** Annual Sharpe ranges **−0.72 to +1.84**;
annual realized volatility ranges **19.8% to 83.9%**. §6.3 records that four separate attempts to
stabilise this all failed.

### 4.5 What the adversarial audit checked and cleared

| check | result |
|---|---|
| CAGR arithmetic | $200,000 → $5,273,482 / 2,260 sessions recomputes to 44.03% vs 43.91% stored — day-count convention |
| stale marks on dark names | 17 of 1,468 exit legs >3 days stale, none >10 days, $30,371 of $5.07m |
| the 58% cost drop | explicable — gross traded fell $213.2m → $136.4m |
| name concentration | ex-top-3 jackknife 14.39× vs benchmark 4.56× |
| liquidity | minimum 60-session ADDV across every name held: **$272m** |
| execution lag | refuted the concern — both arms lose ~0.8 points, advantage holds |

---

## 5 · Every arm tested

### 5.1 Ranked, all on the identical window

| arm | run | CAGR | Sharpe | boot DD | entries/yr | DSR |
|---|---:|---:|---:|---:|---:|---:|
| w5_nt_lag2 | 353 | 46.59% | 0.991 | −60.5% | 163 | 0.826 |
| **w5_notrail** ← selected | **350** | **43.91%** | **0.954** | **−60.2%** | **165** | **0.793** |
| w5_nt_lag1 | 352 | 43.08% | 0.943 | −62.7% | 164 | 0.787 |
| weekly phase 1 (N=8) | 305 | 41.47% | 1.058 | −51.9% | 248 | 0.831 |
| w5_init15 (15% stop) | 351 | 40.30% | 0.945 | −60.0% | 175 | 0.785 |
| w5_noeuph | 346 | 39.47% | 0.939 | −60.7% | 177 | 0.779 |
| five-name centre | 340 | 37.76% | 0.927 | −58.6% | 180 | 0.761 |
| weekly tranched N=10 | 338 | 32.13% | 0.918 | −49.9% | 341 | 0.742 |
| semi-annual champion † | 255 | 32.07% | **1.236** | −30.3% | 17 | **0.965** |
| A6 banded centre | 324 | 26.73% | 0.980 | −36.6% | 106 | 0.788 |
| **SPMO** | 87 | 21.12% | 0.989 | −30.9% | 0 | — |
| VOO | 83 | 15.45% | 0.865 | −34.0% | 0 | — |

† **Run 255 is the one cell in the entire ledger that clears the 0.95 deflated-Sharpe bar**, at a
−30.3% drawdown and 17 trades a year. It was withdrawn because it is a *single phase* of a calendar
whose phase spread is 17.6 points — its 32.07% is a lottery draw, not a repeatable number. Its
phase-averaged mean is 22.04%. This is stated because from the table alone it looks like the best
arm here, and on a single-phase reading it is.

### 5.2 The clock, phase-averaged

Every calendar clock is sensitive to *which dates* it rebalances on. Averaged across phases:

| clock | phases | mean CAGR | **spread** | mean Sharpe | entries/yr |
|---|---:|---:|---:|---:|---:|
| weekly (5 sessions) | 5 | **36.25%** | 14.1 pts | 0.970 | 247 |
| monthly (21) | 6 | 23.26% | 8.3 pts | 0.803 | 83 |
| bi-monthly (42) | 6 | 20.58% | 15.1 pts | 0.790 | 46 |
| semi-annual | 6 | 22.04% | 17.6 pts | 0.933 | 17 |
| SPMO | — | 21.12% | — | 0.987 | 0 |

**No calendar clock beats the ETF risk-adjusted once phase-averaged.** The weekly clock has the
highest return and the second-widest spread.

### 5.3 Staggering converts the lottery

Holding all five weekly phases simultaneously collects their mean instead of a draw from it:

| | CAGR | Sharpe |
|---|---:|---:|
| tranched book (one number) | 32.13% | 0.931 |
| its five phase controls | 32.82% mean, **12.28 pt spread** | 0.947 |

The gap is 0.69 points; on bootstrap medians it is 0.08. **This is the mechanism that makes the
selected arm's number reproducible rather than a draw** — and it was pre-registered as the central
prediction before the cells ran.

What it does *not* do is reduce volatility. The blended Sharpe came in slightly *below* the
component average, because five phases holding the same names offset by days are effectively one
series.

---

## 6 · What is established regardless of which arm is chosen

### 6.1 Findings that hold

| finding | evidence |
|---|---|
| The universe filter is the largest single lever | top-500 vs all-liquid is worth ~10 CAGR points |
| Volatility-adjusting the momentum rank | ~12 CAGR points |
| Raw return rises monotonically with clock speed | the frequency table, all the way to daily |
| Separating observation from transaction removes date sensitivity | 17.6 pt spread → 2.4 (A6) |
| Staggering a clock's phases collects their mean | 32.13% vs a 32.82% control mean |
| A market-regime gate is a bad trade | −6.2 CAGR points to save 2.3 — *on 2017–2026* |
| The Barroso–Santa-Clara volatility governor adds nothing | failed on two independent arms |
| A concentrated momentum book cannot reach 5 effective bets | ceiling is ~3.7 at any N — see §6.2 |
| A correlation cluster cap earns its place | +1.64 CAGR points, worst cluster 8 names → 4 |
| The value of a stop depends on the arm it sits in | −11.15 pts on one arm, +0.10 on another |

### 6.2 The diversification ceiling — a structural result

Measured across 2,213 sessions of the A6 book: mean **2.90 effective bets**, 5th percentile **1.84**,
**98.2% of sessions below 5**. Implied average pairwise correlation ≈0.27 in calm conditions and
≈0.49 in stress. Since effective bets tends to `1/ρ̄`, the ceiling is **≈3.7 in calm conditions and
≈2.0 in stress, at any book size.**

**Adding names cannot fix this**, because the ceiling is set by average correlation, not by count.
A concentrated momentum book is structurally a levered bet on one factor. That is what the strategy
is, not a defect sitting on top of it. The correlation rider removes *duplicates*; nothing removes
the factor.

Corroborating evidence from the other end: of the twenty worst trades in the A6 book, **zero exited
on an earnings gap** (against a 6.0% base rate), and nine of them fall on **six macro dates** — the
vaccine Monday, the Feb-2021 crypto unwind, the China-ADR leg, the tariff crash. **The tail is the
factor.**

### 6.3 Four attempts to stabilise the Sharpe, and what they cost

| attempt | CAGR | Sharpe | annual-Sharpe dispersion | verdict |
|---|---:|---:|---:|---|
| five-name centre (baseline) | 37.76% | 0.927 | 0.789 | — |
| remove the euphoria tighten | 39.47% | 0.939 | **0.696** | **the only one that helped** |
| volatility target 40% | 35.12% | 0.914 | 0.803 | damped vol, worsened Sharpe stability |
| volatility target 55% | 38.50% | 0.934 | 0.829 | neutral |
| §3.2 valid-base entry gate | **27.00%** | 0.842 | **1.417** | far worse on every axis |

**Only removing the euphoria tighten improved stability**, and modestly — it also improved the worst
year materially (−19.3% vs −25.3%) and the worst-year Sharpe (−0.476 vs −0.719).

**The honest conclusion: with the levers tested, the Sharpe instability is not fixable.** An annual
Sharpe ranging −0.7 to +1.8 is what a five-name momentum book is.

### 6.4 What was tried and did not work

- **Every rebalance clock** weekly to annual — all phase-sensitive, all below SPMO's Sharpe averaged.
- **A market-observed re-entry door** replacing the calendar — robust, and returned 1.5%.
- **A market regime gate** — costs 6.2 points to save 2.3, *on 2017–2026*; re-test at backfill.
- **The Barroso–Santa-Clara volatility governor** — failed on two arms independently.
- **An effective-bets floor of 5** — unreachable at any N; see §6.2.
- **An ATR trail** (3×ATR(20) / +1R / 8×ATR(22)) — −11.15 points on the banded arm; neutral on the
  weekly one.
- **A path-quality entry gate** (%-positive-days vs pool median) — blocked 3,168 entries, cost 6.55
  points.
- **An earnings-gap exit filter** — never built; the measurement refused it (§6.2).
- **A top-250 universe on a fast clock** — −2.9 points, despite +1.5 on a slow one.

---

## 7 · Defects found and fixed

The instrument found nine defects in itself. They are listed because an instrument's credibility
rests on what it caught, and because several invalidated results that had already been reported.

| defect | consequence |
|---|---|
| Calendar taken from the tape union, not the market calendar | ~26 junk listings printing on holidays put New Year's Day in the grid; the book sold everything and parked until July. **Invalidated runs 95–164.** |
| Split-adjusted volume against raw closes | every split arrived as a crash. **Invalidated runs 18–44.** |
| Duplicate listings of one company | BBBY/BBBY_old/OSTK/BYON held simultaneously — four slots, one company |
| NAV read as cash alone at rebalance | a `sleeve=1.00` cell really ran ~0.78 |
| Intraday stop tested against the entry session's own bar | backwards look-ahead; a name bought 2020-01-02 "stopped" on 2020-01-02 |
| Open positions stored NULL P&L | disarmed the jackknife — a winner still held could never be jackknifed out |
| Euphoria rule read a flat window as euphoric | a halted name returned on a 5% leash |
| §2.5 verdicts scored against VOO, not SPMO | every `proven` verdict cleared 15.45% instead of 21.12% |
| Tranched NAV read as cash-plus-holdings | with everything parked, NAV came out zero and the book bought nothing — **silently, with no error** |

**A methodological error of mine, corrected in public:** an earlier revision reported bi-monthly at
"33.37% with a 2.0-point spread" and recommended it. That spread was measured with a parameter that
drops early rebalances but **leaves the calendar phase untouched**. The real phase test gives 15.1
points and the mean drops to 20.58% — below SPMO. The recommendation was withdrawn.

---

## 8 · Statistical method, and why nothing is `proven`

Each arm is scored on: **deflated Sharpe** (Bailey–López de Prado, adjusted for the number of
configurations tried), **block bootstrap** (63-session blocks, 10,000 draws, seed 0), a
**winner-exclusion jackknife**, and an **out-of-sample cut**.

**The deflated Sharpe bar is 0.95. The selected arm scores 0.793 at 200+ logged trials.** Read
literally: having searched this hard, a Sharpe this good would arise by chance roughly one time in
five.

Two things must be said about that.

**The trial count is the researcher's, not the strategy's.** Every falsification run also enters the
ledger and raises the bar. That is the statistic working correctly, but it means **this number
cannot be improved by running more cells — only by out-of-sample evidence.**

**The bar has been retired as a gate, not cleared.** Zak's ruling of 2026-08-14: deployment proceeds
on the `unproven` verdict, because the bar cannot be met on 2017–2026 at any trial count and the
backfill that would move it is declined for now. **Removing a bar is not the same as clearing one,
and no arm in this document is proven.**

---

## 9 · What is genuinely unknown

1. **Behaviour in a momentum crash.** The single largest gap. See §4.2.
2. **Whether the selected arm's edge survives outside V-shaped recoveries.** §4.1 says its entire
   advantage came from two snap-backs and it lost the one grind.
3. **Whether 43.91% is anywhere near the expected value.** End-point range is 24.7%–51.1%; the
   bootstrap 5th percentile is 10.72%.
4. **Live execution slippage.** Costs are modelled from a dollar-volume spread curve. Market impact
   is not modelled; at current size it is immaterial (largest position ≈0.4% of a name's daily
   volume) but it is not zero and it is not measured.
5. **Tax.** Every figure here is pre-tax. The plan places momentum in the TFSA for exactly this
   reason, and high-turnover trading carries a business-income recharacterization risk that is a
   stated assumption, never a settled fact.

---

## 10 · How to keep improving it

Ordered by expected value, not by ease.

1. **The 2003–2016 backfill.** This is the third time the programme has arrived at this door, and
   it now blocks four separate questions at once: the momentum-crash behaviour (§4.2), the two
   rejected risk overlays (§6.4), the deflated Sharpe (§8), and whether the no-stop decision is
   sound at all (§4.1). **Nothing else on this list moves as many things.**
2. **A crash-shape conditional stop.** §4.1 identifies precisely when the stop helps and when it
   hurts: it wins grinding declines and loses V-shaped ones. A rule that distinguishes them is a
   genuine research question rather than a parameter — and it would keep the +6 points while
   removing the bet in §4.3.
3. **Drop the euphoria tighten.** The only change measured to improve Sharpe stability (§6.3),
   worth ~0.09 of annual-Sharpe dispersion and a materially better worst year. It is orthogonal to
   the no-stop decision and can be adopted independently of it.
4. **Re-test the two risk overlays at backfill.** Both were rejected on a window with no momentum
   crash — which is precisely the event they are insurance against. "Rejected on 2017–2026" is the
   correct label; "rejected" is not.
5. **A different ranking signal.** The 12-1 rank has been perturbed in every direction available. It
   is real and it decays fast; the remaining gains are unlikely to come from tuning it further.

**A caution on all of the above.** The programme has now run 200+ configurations against one nine-
year window. Each additional cell lowers every arm's deflated Sharpe and increases the chance that
the best-looking result is the luckiest one. **The next material gain should come from more data,
not more cells.**

---

## 11 · Reproduction

Runs are stored in `backtest_runs` with `params`, `stats`, and full equity and trade ledgers.
The cell name is in `params->>'variant'`; `stats->'bars_25'` carries the complete §2.5 scoring —
bootstrap, jackknife, out-of-sample cut, deflated Sharpe, and the trial ledger it was deflated
against.

**Key run IDs:** **350** (selected arm) · **352–353** (its lag falsifiers) · **340** (the stopped
five-name centre) · **346–351** (the WO-A8 stabiliser grid) · **338** (weekly tranched N=10) ·
**333–337** (its five phase controls) · **339–345** (the weekly sensitivity grid) · **324** (A6
banded centre) · **325–332** (A6's rider and sensitivity cells) · **305–308, 286** (the stored N=8
weekly phases) · **255** (semi-annual champion) · **87** (SPMO) · **83** (VOO).

**Code:** `src/concentrated.py` is the strategy engine; `src/finding.py` applies the §2.5 bars;
`src/bars.py` holds the statistics. **Work orders** carry the pre-registrations, each written before
its cells ran: `docs/wo-a4-*`, `wo-a5-*`, `wo-a6-*`, `wo-a7-2026-08-14.md` (the weekly arm),
`wo-a8-2026-08-14.md` (the five-name forensics and the adversarial audit).

**Governance.** Nothing in this repository places, modifies, or cancels an order. Every trade is
placed by hand. Adopting the no-stop configuration into the live sleeve requires an amendment to
`docs/yuna_plan.md` §3.2 before any code change, and the plan is the law where this document and it
disagree.
