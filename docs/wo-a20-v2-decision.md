# WO-A20 · V2 — the strategy, the decision, and everything behind it

**Written 2026-08-15.** Supersedes WO-A15 (wrong cell, defective tape) and the recommendation in
WO-A17 (right cell, no gate). WO-A18 remains the programme history; this is the current decision.

**The cell of record is `b5_12_2_L1_3`.** Two changes from WO-A15's `b5_12_3`: the entry band moves
from 3 to 2, and the regime gate is switched on with a tight latch. Both are Zak's rulings, both
made against measurements taken after the tape was screened.

---

## 1. The strategy, complete

Every session:

1. **Regime check.** Is SPY above its own 200-session moving average? **One** session below turns
   the book off; **three** consecutive sessions above turn it back on. (`latch = (1, 3)`.)
2. **If off** — hold nothing. The whole account sits in the park until the latch flips back.
3. **If on** — screen, rank, and run the band rule below.
4. **Screen.** ≥210 finite bars in the last 252; **raw** close ≥ $5.00; 50-session median of
   `adj_close × volume` ≥ $10,000,000.
5. **Pool.** The 500 highest by that median. Stable sort.
6. **Score.** `(adj[i−21] / adj[i−252] − 1) ÷ stdev(daily returns, 252 sessions)`, descending,
   stable sort.
7. **Exit.** Any holding ranked worse than **12** is queued to sell.
8. **Entry.** A free slot goes to the best unheld name in the pool. With no free slot, an unheld
   name in the **top 2** displaces the worst holding — strictly better only, one per session.
9. **Fill.** Everything decided at session *i* executes at *i+1*'s **adjusted open**; no print,
   no fill.

Five names, equal weight, fully invested when the gate is open.

### 1.1 Every constant

| # | Constant | Value | Note |
| --- | --- | --- | --- |
| 1 | `FORMATION` | 252 | the 12 months scored |
| 2 | `SKIP` | 21 | minus the most recent month |
| 3 | `VOL_WINDOW` | 252 | volatility denominator |
| 4 | `L0_MIN_BARS` | 210 | of 252 |
| 5 | `L0_MIN_RAW` | $5.00 | raw print, not adjusted |
| 6 | `L0_MIN_ADDV` | $10,000,000 | 50-session median |
| 7 | `ADDV_WINDOW` | 50 | |
| 8 | `top_by_addv` | 500 | |
| 9 | `n` | 5 | |
| 10 | `exit_rank` | **12** | |
| 11 | `entry_rank` | **2** | corrected from 3 |
| 12 | `gate_window` | **200** | the moving average's length |
| 13 | `latch` | **(1, 3)** | 1 session out, 3 to return |
| 14 | `sleeve` | 1.00 | |

Off, each measured and rejected: trailing stop, state door, diversification floor, volatility
target, theme cap, partial gate caps.

---

## 2. The result, on all three windows

**Three standalone runs**, each starting fresh at $100,000 with its own warmup:

| window | sessions | park | CAGR | max DD | trades |
| --- | ---: | --- | ---: | ---: | ---: |
| **2007-01-05 .. 2017-08-14** (disjoint) | 2,671 | SPY | **+10.66%** | −60.4% | 426 |
| **2017-08-15 .. 2026-08-14** | 2,262 | SPMO | **+51.28%** | −54.3% | 325 |
| **2007-01-05 .. 2026-08-14** (full) | 4,933 | SPY | **+26.54%** | **−61.2%** | 752 |

Against the ungated book on the same three: **−0.96% / 52.63% / 20.06%**, drawdowns
−81.8% / −51.2% / −82.5%.

**The decisive line is the first one.** WO-A18 §3 established that *zero of twenty-five ungated
configurations made money over 2007–2017*. Gated, that decade returns **+10.66% a year**. The
strategy is no longer a bet on one regime — it works in both, for the first time in this
programme.

**Those three rows do not compose, and it matters more here than it did before the gate.** The
nine-year run parks in **SPMO** and the full run parks in **SPY**, and under a gate the park *is*
the return for every session the book is off — 175 gate exits over twenty years. Laying the rows
end to end implies 27.72% against the 26.54% actually reported. The true decomposition, taken from
run 589's **own** curve:

```
2007-01-05 .. 2017-08-14    $99,950 →   $285,402    +10.40%/yr    ×2.86
2017-08-15 .. 2026-08-14   $289,667 → $10,089,809   +48.39%/yr    ×34.8
──────────────────────────────────────────────────────────────────────
2007-01-05 .. 2026-08-14   $100,000 → $10,089,809   +26.54%/yr    ×99.9
```

Same discipline as WO-A17 §3.4: use a run's own curve to split it, and separate runs only to rank
cells within one window.

### 2.1 The account, year by year

| year | book | SPY | NAV |
| ---: | ---: | ---: | ---: |
| 2007 | +20.4% | +6.0% | $120,354 |
| 2008 | **−37.3%** | −36.2% | $74,835 |
| 2009 | +16.0% | +22.7% | $89,444 |
| 2010 | −1.4% | +13.1% | $91,529 |
| 2011 | −1.2% | +0.9% | $93,432 |
| 2012 | +15.7% | +14.2% | **$107,515** ← above water, year 6 |
| 2013 | +32.2% | +29.0% | $146,506 |
| 2014 | +15.7% | +14.6% | $171,598 |
| 2015 | +0.9% | +1.3% | $175,698 |
| 2016 | +16.6% | +13.6% | **$202,010** ← doubled at ten years |
| 2017 | +49.5% | +20.8% | $298,906 |
| 2018 | −9.0% | −5.2% | $280,267 |
| 2019 | +32.4% | +31.1% | $371,337 |
| 2020 | **+163.1%** | +17.2% | $1,011,135 |
| 2021 | +33.8% | +30.5% | $1,412,630 |
| 2022 | **−17.4%** | −18.6% | $1,156,990 |
| 2023 | +53.8% | +26.7% | $1,771,796 |
| 2024 | +65.6% | +25.6% | $2,799,152 |
| 2025 | +50.4% | +18.0% | $4,382,426 |
| 2026 | +124.3% | +14.2% | **$10,089,809** |

Compare the ungated path at the same two checkpoints: **$32,795 in 2012 and $55,742 in 2016**, and
first back above $100,000 in **2019**. The gate moves that from year thirteen to year six.

### 2.2 Trade and distribution statistics (full window)

| | |
| --- | --- |
| Trades | 752 (38.4/yr) |
| Win rate | 50.4% |
| Average win | +16.23% |
| Average loss | −7.52% |
| Profit factor | 2.95 |
| Median hold | 13 sessions |
| Mean hold | 25.0 sessions |
| Annualised Sharpe | 0.789 |
| Kurtosis | 9.73 |
| Effective bets | 2.513 of 5 |
| **Total costs** | **$132,055** |
| Total return | **99.95×** |
| Benchmark (SPY) | 6.90× |

**Exits:** `rank_band` 366 · `displaced` 206 · `gate_off` 175 · `open_at_end` 5.

**Jackknife:** removing the five best trades still returns **50.46×** against SPY's 6.90×.

---

## 3. What the gate costs — stated plainly

The gate is **crash insurance**, and insurance has a premium. Three places it is visible:

**2022.** Ungated returned **+5.5%** through that bear market by riding energy and defence. Gated
returned **−17.4%**, because it sold out and waited in a falling SPY. One year, 23 points.

**The recent window.** 51.28% gated against 52.63% ungated. On 2017–2026 alone the gate is a
**1.35-point drag**, and the drawdown is *worse* — −54.3% against −51.2%. If the next decade looks
like the last one, the gate loses.

**Costs.** $132,055 against the ungated $37,136 — **3.6×**. Every gate crossing is a full round
trip on the whole book. This is already inside the 26.54%, but it is real money and it is why the
slow latches exist.

### 3.1 Why the latch is 1/3 and not 1/10

| latch | 2007–2017 | 2017–2026 | full |
| --- | ---: | ---: | ---: |
| 1 out / 1 in | +10.22% | — | 26.16% |
| **1 / 3** | **+10.66%** | **51.28%** | **26.54%** |
| 1 / 5 | +10.52% | — | 25.99% |
| 1 / 10 | +11.08% | 41.98% | 23.82% |
| 1 / 20 | — | 38.22% | 21.30% |
| 3 / 20 | — | — | 19.91% |
| 5 / 40 | — | — | 17.50% |

**1/10 is marginally better in the crash decade (+11.08% vs +10.66%) and 9.3 points worse in the
recent one.** Long confirmations pay for themselves only in 2008-shaped events; in V-shaped dips
they keep the book parked through the rebound. 1/3 gives up 0.4 points of crash protection to keep
9 points of normal-market return.

**This inverts WO-A10's finding, and the inversion is explainable.** On the `w5` arm 1/10 won,
because that book re-decided twice a year and a slow gate matched its clock. This book re-decides
every session, so it can afford to come back quickly and re-rank immediately. **The `w5` rungs were
never evidence about this book** — a lesson worth more than the rung itself.

### 3.2 The moving-average window

| window | full-period CAGR | max DD |
| ---: | ---: | ---: |
| 100 | 20.25% | −63.1% |
| 150 | 21.64% | −60.8% |
| **200** | **26.54%** (at 1/3) | −61.2% |
| 250 | 25.76% | −63.2% |

200 is inherited from Clenow and had never been varied here. It survives the test; 250 is within
noise of it, and short windows whipsaw.

---

## 4. What was rejected, with the measurement

| variant | full-period CAGR | max DD | why rejected |
| --- | ---: | ---: | --- |
| ungated | 20.06% | −82.5% | the drawdown, and a decade of losses |
| theme cap 1/industry | 18.20% | −65.4% | helps, but dominated by the gate on every axis |
| theme cap 2 | 19.20% | −75.7% | barely binds |
| theme cap 3 | 21.69% | −78.5% | 129 blocks — cosmetic |
| hold 1 name in downtrends | 21.95% | −68.2% | strictly worse than holding none |
| hold 2 | 19.86% | −70.7% | monotone: more exposure in a downtrend is worse |
| hold 3 | 19.78% | −76.7% | |
| hold 4 | 19.81% | −79.6% | |
| gate + rising proof | 23.30% | −60.9% | costs 3.2 points, buys nothing |
| sampled gate (no latch) | 26.78% | −63.0% | best raw CAGR, worse drawdown, and untestable on a live desk |

### 4.1 On the theme cap specifically

Zak asked for "2 semis max, 2 defence max". It was built on `universe.industry` (239 values, the
granularity the question is actually asked in) and measured. **It cuts the drawdown — −82.5% to
−65.4% at one per industry — but does not diversify the book.** Effective bets moved 2.435 → 2.441.

The mechanical effect was real: the largest same-industry cluster fell from 5 names to 3. The book
was no less correlated for it. **The five names move together for reasons the industry taxonomy
does not capture** — they are all high-momentum speculative growth, whatever sector label the
vendor files them under. Capping semiconductors at two does nothing if the replacement is a quantum
computing name that trades identically.

That is an honest negative result on the *mechanism*, and it is why the gate — which addresses
*when* to be exposed rather than *to what* — dominates it.

---

## 5. What is still not established

- **§2.5 says `unproven`.** Deflated Sharpe **0.214** against a 0.95 bar, over **448** logged
  trials. Roughly tripled from the ungated 0.072, and still nowhere near the bar.
- **No out-of-sample data exists.** All three windows were examined before the cell was chosen. The
  gate in particular has now been selected on all three.
- **There is nowhere safe to park.** The only park tickers in the universe are SPY, SPMO and VOO,
  so "defensive" currently means *holding the index while it falls*. In 2008 that was −37.3%
  rather than the −69.7% ungated, but a T-bill park would plausibly have been near zero. **Every
  gate figure here understates a cash-parked gate in a crash and overstates nothing.** Backfilling
  a bill or short-bond ticker is the single highest-value data task outstanding.
- **Kurtosis 9.73.** Fat tails; any single-number risk estimate is optimistic.
- **A −61% drawdown has never been tested against a human**, and it is still a −61% drawdown.
- **Sector and industry labels are the vendor's current ones**, not point-in-time. Mild look-ahead;
  stated rather than corrected.
- **The tape moves.** A `..open` window is not reproducible across days — three runs in this
  programme differ only because the nightly ingest added a session. Compare only at equal
  `code_stamp` **and** equal session count.

---

## 6. The decision

1. **`b5_12_2_L1_3` is the cell of record.** Entry band 2, exit band 12, gate on, latch 1/3,
   200-session average.
2. **The honest headline is three numbers, not one:** *+10.66% a year 2007–2017, +51.28%
   2017–2026, +26.54% over the full twenty years, with a −61% worst drawdown.* Quote all three or
   none.
3. **The gate is insurance and should be described as such.** It costs 1.35 points a year in
   normal markets and 23 points in 2022; it saved 32 points in 2008 and turned a losing decade
   profitable.
4. **Backfill a cash-like park ticker** and re-run. It is the one change likely to improve every
   number in this document.
5. **A forward record remains the only evidence that moves a deflated Sharpe.** 448 in-sample
   trials cannot be undone by a 449th.

**Nothing here is merged toward production, and nothing in this repository places an order. Yuna
proposes; Zak decides.**
