# WO-A18 · The complete programme record

**Written 2026-08-15.** Everything tried, every ruling made, every number measured, in the order it
happened. Where an earlier document conflicts with this one, this one is later and was written
against a screened tape.

This is the record a stranger would need to reconstruct the whole exercise without asking a
question. It is deliberately long. `wo-a17-regime-synthesis.md` is the shorter argument; this is
the evidence behind it.

---

## PART I — WHAT THE STRATEGY IS

## 1. The rule, complete

Every session:

1. **Screen.** A name is rankable if it has ≥210 finite bars in the last 252, a **raw** close ≥
   $5.00, and a 50-session median of `adj_close × volume` ≥ $10,000,000.
2. **Pool.** Keep the 500 highest by that median. Stable sort — ties must not reorder between runs.
3. **Score.** `(adj[i−21] / adj[i−252] − 1) ÷ stdev(daily returns, 252 sessions)`. Descending,
   stable sort.
4. **Exit.** Any holding now ranked worse than 12 is queued to sell.
5. **Entry.** If a slot is free, the best unheld name **inside the top 2** takes it. If none is
   free, that name **displaces the worst-ranked holding**, strictly-better only, **one per
   session**.
6. **Fill.** Everything decided at session *i* executes at session *i+1*'s **adjusted open**. No
   print that morning → the order is cancelled, not carried.
7. **Cost.** Spread by liquidity: 5bps above $50m ADDV, 10bps above $10m, 18bps above $2m, 35bps
   above $500k, 60bps below.

Five names, equal weight, always fully invested. No stop, no cash reserve, no sector cap, no
volatility target, no regime gate.

### 1.1 The thirteen constants

| # | Constant | Value | Source |
| --- | --- | --- | --- |
| 1 | `FORMATION` | 252 | `src/concentrated.py:103` |
| 2 | `SKIP` | 21 | `:104` |
| 3 | `VOL_WINDOW` | 252 | `:105` |
| 4 | `L0_MIN_BARS` | 210 | `:106` |
| 5 | `L0_MIN_RAW` | $5.00 | `:107` |
| 6 | `L0_MIN_ADDV` | $10,000,000 | `:108` |
| 7 | `ADDV_WINDOW` | 50 | `:109` |
| 8 | `top_by_addv` | 500 | cell spec |
| 9 | `n` | 5 | cell spec |
| 10 | `exit_rank` | **12** | WO-A14 grid, confirmed WO-A16 |
| 11 | `entry_rank` | **2** | WO-A16 grid — **corrected from 3** |
| 12 | `sleeve` | 1.00 | Zak's ruling |
| 13 | `months` | 6 | inert under the banded rule |

---

## PART II — THE PORTFOLIO, IN NUMBERS

## 2. The account, twenty years (run 508, `b5_12_2`)

| | |
| --- | --- |
| Start | **$100,000**, 2007-01-05 |
| End | **$3,473,235**, 2026-08-13 |
| Total return | **33.75×** (+3,373%) |
| CAGR | **19.84%** |
| Max drawdown | **−82.5%** |
| Sessions | 4,932 |
| Trades | 777 (≈40/yr) |
| Total costs | **$37,136** |
| Benchmark (SPY) | 6.91× / 11.15% CAGR |

### 2.1 The NAV path, year by year

| year | book | SPY | NAV at year end | drawdown state |
| ---: | ---: | ---: | ---: | --- |
| 2007 | +13.4% | +6.0% | $113,305 | |
| 2008 | **−69.7%** | −36.2% | $34,278 | −70% |
| 2009 | −5.2% | +22.7% | $32,676 | −71% |
| 2010 | −0.8% | +13.1% | $33,611 | −70% |
| 2011 | −25.2% | +0.9% | $25,971 | **−77%, the trough** |
| 2012 | +26.9% | +14.2% | $32,795 | −71% |
| 2013 | +32.0% | +29.0% | $44,688 | −61% |
| 2014 | +28.5% | +14.6% | $58,126 | −49% |
| 2015 | −7.7% | +1.3% | $54,375 | −52% |
| 2016 | +5.9% | +13.6% | $55,742 | **−51%, ten years in** |
| 2017 | +48.5% | +20.8% | $82,138 | −27% |
| 2018 | −5.9% | −5.2% | $79,613 | −30% |
| 2019 | +49.9% | +31.1% | $116,800 | **above water, year 13** |
| 2020 | **+146.9%** | +17.2% | $298,419 | |
| 2021 | +36.0% | +30.5% | $423,063 | |
| 2022 | +5.5% | **−18.6%** | $442,481 | |
| 2023 | +34.3% | +26.7% | $581,038 | |
| 2024 | +64.7% | +25.6% | $913,541 | |
| 2025 | +75.7% | +18.0% | $1,670,691 | |
| 2026 | +102.5% | +14.5% | $3,473,235 | 154 sessions |

**Thirteen years under water.** The account did not see $100,000 again until 2019.

### 2.2 The trade distribution

| | |
| --- | --- |
| Trades | 777 |
| Win rate | **54.2%** |
| Average win | **+16.52%** |
| Average loss | **−10.22%** |
| Profit factor | **2.98** |
| Median hold | **17 sessions** (~3.5 weeks) |
| Mean hold | 31.7 sessions |
| Skew | −0.023 |
| Kurtosis | **10.16** |
| Effective bets | **2.435** of 5 |

**Exit reasons** (the closest run, 992-trade `b5_12_3`): displaced 560, rank_band 431,
open_at_end 5. **Displacement is the dominant exit** — the book is pushed out by a better name
more often than it falls out of the band.

### 2.3 Per-trade expectancy is not stable — this is the core fact

| year | trades | win rate | **avg return per trade** |
| ---: | ---: | ---: | ---: |
| 2007 | 49 | 51% | +1.35% |
| **2008** | 26 | **31%** | **−17.17%** |
| 2009 | 44 | 43% | +0.23% |
| 2010 | 44 | 50% | +2.77% |
| 2011 | 59 | 41% | −2.56% |
| 2012 | 39 | 62% | +3.04% |
| 2013 | 50 | 64% | +3.13% |
| 2014 | 31 | 48% | +6.72% |
| 2015 | 41 | 39% | −3.27% |
| 2016 | 45 | 64% | +4.88% |
| 2017 | 34 | 71% | +5.54% |
| 2018 | 36 | 47% | +0.68% |
| 2019 | 46 | 48% | +3.80% |
| **2020** | 41 | **68%** | **+27.95%** |
| 2021 | 33 | 39% | +0.62% |
| 2022 | 41 | 63% | +1.92% |
| 2023 | 40 | 70% | +6.69% |
| 2024 | 40 | 65% | +5.27% |
| **2025** | 29 | 62% | **+26.06%** |
| **2026** | 9 | 56% | **+30.85%** |

**A 45-point swing in per-trade expectancy between 2008 and 2020**, and it is scale-free — it is
not compounding. The 54.2% / +16.5% / −10.2% aggregate describes no year in the record.

### 2.4 What it actually held — the ten largest wins

| ticker | entered | exited | return | P&L | theme |
| --- | --- | --- | ---: | ---: | --- |
| `WDC` | 2025-12-11 | open | +175.8% | $636,544 | memory |
| `SNDK` | 2026-02-18 | open | +162.3% | $412,513 | memory |
| `RKLB` | 2025-02-11 | 2025-10-29 | +114.8% | $258,420 | space |
| `RGTI` | 2025-04-14 | 2025-12-15 | +177.3% | $252,098 | quantum |
| `BE` | 2026-02-11 | open | +53.9% | $235,783 | power |
| `LITE` | 2026-01-29 | 2026-02-19 | +52.7% | $225,767 | optical/AI |
| `PLTR` | 2025-03-10 | 2025-11-11 | +132.1% | $221,971 | AI software |
| `OKLO` | 2025-07-15 | 2025-10-31 | +123.6% | $217,376 | nuclear |
| `QBTS` | 2025-06-16 | 2025-12-11 | +74.5% | $151,788 | quantum |
| `TSLA` | 2020-05-19 | 2021-01-26 | +446.7% | $115,315 | the 2020 melt-up |

**Eleven of the top twelve entered 2025–26.** And the *themes* repeat: WDC+SNDK are one trade,
RGTI+QBTS are one trade, RKLB+OKLO+BE are one trade. **Roughly four independent ideas in the top
ten** — which is effective bets of 2.435 showing up in the blotter rather than a correlation
matrix.

### 2.5 The distribution of outcomes (10,000-draw block bootstrap, 63-session blocks, seed 0)

| percentile | CAGR |
| --- | ---: |
| 5th | **+0.67%** |
| 50th | 19.79% |
| 95th | 41.48% |

**One run in twenty of this rule's own return distribution is a two-decade round trip to nothing.**

### 2.6 The jackknife — is it one lucky trade?

| | total return |
| --- | ---: |
| all trades | 33.75× |
| minus best 1 | 27.38× |
| minus best 3 | 20.67× |
| minus best 5 | **15.79×** |
| SPY | 6.91× |

**No.** Strip the five best trades and it still returns 15.79× against the benchmark's 6.91×. The
concentration is in a *period*, not in a handful of positions.

---

## PART III — THE REGIME

## 3. The decomposition

From run 508's **own** equity curve, split at the nine-year boundary:

```
2007-01-05 .. 2017-08-14    $99,950 →    $78,452     −2.26%/yr    −21.5% cumulative
2017-08-15 .. 2026-08-13    $79,621 → $3,473,235    +52.16%/yr        ×43.6
────────────────────────────────────────────────────────────────────────────────
2007-01-05 .. 2026-08-13   $100,000 → $3,473,235    +19.84%/yr    ×33.75
```

Recomposing: `0.9774^10.61 × 1.5216^8.99` = 19.75%/yr against the 19.84% reported. The residual is
the boundary session. **The identity closes.**

### 3.1 Run separately, the first decade loses in every configuration

Twenty-five cells on 2007-01-05 → 2017-08-14 (runs 547–571):

**Zero positive. Range −0.96% to −7.49% a year. Every drawdown −80% to −84%.**

### 3.2 Why the mechanism is a momentum crash, not bad luck

The defining failure of momentum is not the crash — it is **the rebound**. After a collapse the
highest-momentum names are defensive survivors; the violent recovery is led by exactly the beaten
names momentum does not own.

**2009 is that, in one line: the book returned −5.2% while SPY returned +22.7%.** A 28-point miss
in a year the market rose a fifth. 2008's −69.7% hurt more at the time; 2009 is what made the
decade unrecoverable. This is Daniel & Moskowitz's documented signature, and Barroso &
Santa-Clara's volatility-scaling paper exists because of it.

### 3.3 The counter-evidence, recorded fairly

**2022: the book returned +5.5% while SPY returned −18.6%** — 24 points of outperformance in a
bear market. The rule is *not* simply long beta to a rising market; it found trends (energy,
defence) while the index fell. Any account claiming "it only works when markets go up" has to
explain 2022, and cannot.

---

## PART IV — EVERYTHING TRIED

## 4. The arms, in order, with measured results

All figures 20-year window unless stated. Superseded runs are marked — they predate the tape screen.

### 4.1 The trail arm (`w5_*`) — the starting point

| cell | what it is | 20yr CAGR | 20yr DD | 9yr CAGR | trades |
| --- | --- | ---: | ---: | ---: | ---: |
| `w5_notrail` | 5 names, weekly, no stop | **15.02%** | −82.5% | 44.79% | 3,207 |
| `w5_door` | + state door | — | — | 27.00% | 1,686 |
| `w5_vt40` | + vol target 40% | — | — | 35.12% | 1,755 |
| `w5_vt55` | + vol target 55% | — | — | 38.50% | 1,746 |
| `w5_noeuph` | − euphoria exit | — | — | 39.47% | 1,586 |
| `w5_init15` | initial stop 15% | — | — | 40.30% | 1,568 |

**Ruling: the trailing stop was removed.** Every stop variant scored below `w5_notrail`. The
earlier hypothesis that stops reduce churn was tested and **falsified** — re-entry repairs the loss
the stop creates.

### 4.2 The regime arm (`w5_g_*`) — SPY versus its 200-day

The most important arm in the programme, and the one whose ruling should now be revisited.

| cell | latch | 20yr CAGR | 20yr DD | 9yr CAGR | trades |
| --- | --- | ---: | ---: | ---: | ---: |
| `w5_notrail` | **ungated** | 15.02% | **−82.5%** | 44.79% | 3,207 |
| `w5_g_plain` | gate, no latch | **21.39%** | **−62.9%** | 35.34% | 2,527 |
| `w5_g_1_3` | 1 out / 3 in | 18.64% | −62.2% | 40.45% | 2,492 |
| `w5_g_1_5` | 1 / 5 | 19.86% | −61.1% | 38.23% | 2,426 |
| `w5_g_1_7` | 1 / 7 | 19.83% | −60.6% | 40.85% | 2,413 |
| `w5_g_1_10` | 1 / 10 | **20.12%** | **−60.7%** | 38.34% | 2,325 |
| `w5_g_1_14` | 1 / 14 | 17.06% | −60.4% | 32.61% | 2,251 |
| `w5_g_1_20` | 1 / 20 | 16.11% | −60.2% | 31.40% | 2,237 |
| `w5_g_1_10r` | + rising proof | 18.98% | −60.7% | 35.48% | 2,213 |
| `w5_g_3_20` | 3 / 20 | 16.31% | −67.9% | 34.03% | 2,306 |
| `w5_g_3_20r` | + rising | 13.63% | −67.9% | 28.60% | 2,179 |
| `w5_g_5_40r` | 5 / 40 + rising | 10.49% | −69.1% | 23.09% | 2,055 |

**The plain gate turned 15.02% / −82.5% into 21.39% / −62.9%.** Nearly 20 points of drawdown
removed and 6.4 points of CAGR added.

Supporting measurements from that work:
- Split by state: with SPY **above** its 200-day the arm returned **+272.4%**; **below**, **−87.9%**.
- The edge is **avoidance, not the park**: invested periods returned **26.6%/yr**, parked periods
  **3.6%/yr**.
- Bootstrap 5th percentile moved from **−3.4% to +5.6%**.
- Confirmation days beyond ~10 destroy it (1/14 and 1/20 fall away); requiring a *rising* 200-day
  before re-entry costs 1.1 points.

### 4.3 The crash-frequency question

Asked directly: are crashes less likely now? Measured:

| window | filter edge |
| --- | ---: |
| full record | **+6.38 pts** |
| excluding 2008–09 | **+1.40 pts** |
| 2012–2026 only | **+0.13 pts** |

And **drawdown speed**: 2008 took **356 sessions** to reach its bottom; 2020 took **24**.

**Ruling (Zak): the regime filter is advisory, not automatic.** A 200-day filter needs time to
signal, and crashes have become faster, not rarer — so the filter that would have saved 2008 would
not have caught 2020. It stays as a warning flag Zak acts on, not a rule the engine executes.

**This ruling now deserves re-examination** — see §7.2.

### 4.4 The banded arm (`b5_*`) — the current family

Zak's rule: hold five, eject past an exit band, let a top-*E* outsider displace the worst holding.

| cell | what it varies | 20yr CAGR | note |
| --- | --- | ---: | --- |
| `b5_8_3` (pre-screen) | the root | 11.97% | superseded |
| `b5_nodisp` | no displacement | 12.79% | superseded |
| `b5_close` | fill at close not open | 14.13% | superseded |
| `b5_12_gap` | slot idles a session | — | preserved deliberately |
| `b5_8_3` (screened) | the root | 14.35% | current |
| `b5_12_3` | WO-A15's choice | 16.51% | **superseded** |
| `b5_12_2` | **the cell of record** | **19.84%** | current |

### 4.5 The 5×5 band grid — three windows

**20-year (runs 497–538):**

| exit \ entry | 1 | 2 | 3 | 4 | 5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 | 14.08 | 15.00 | 14.35 | 16.73 | 17.86 |
| 10 | 17.59 | **20.57** | 15.15 | 15.90 | 17.72 |
| 12 | 20.10 | 19.84 | *16.51* | 16.17 | 17.87 |
| 14 | 18.65 | 18.75 | 14.07 | 15.65 | 18.08 |
| 16 | 16.49 | 17.19 | 14.58 | 15.91 | 18.08 |

**9-year (runs 515–546):**

| exit \ entry | 1 | 2 | 3 | 4 | 5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 | 43.21 | 44.80 | 45.55 | 49.79 | 50.89 |
| 10 | 56.66 | **59.95** | 46.92 | 47.85 | 50.23 |
| 12 | 54.03 | 52.03 | *48.03* | 47.18 | 50.67 |
| 14 | 51.12 | 48.88 | 46.66 | 47.42 | 51.07 |
| 16 | 51.53 | 49.27 | 45.78 | 47.89 | 51.10 |

**2007–2017, disjoint (runs 547–571):**

| exit \ entry | 1 | 2 | 3 | 4 | 5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 | −4.28 | −3.88 | −6.74 | −4.56 | −4.59 |
| 10 | −3.85 | −3.26 | −6.47 | −5.47 | −4.33 |
| 12 | −2.62 | **−0.96** | *−5.22* | −4.69 | −4.33 |
| 14 | −2.67 | −1.56 | −7.49 | −5.54 | −4.24 |
| 16 | −5.56 | −3.41 | −6.84 | −5.50 | −4.24 |

**Entry-band means:** 1 → −3.80 / +51.31 / 17.38 · **2 → −2.61 / +50.99 / 18.27** ·
**3 → −6.55 / +46.59 / 14.93 (worst on all three)** · 4 → −5.15 / +48.03 / 16.07 ·
5 → −4.35 / +50.79 / 17.92.

**Exit-band means:** 8 → −4.81 / 46.85 / 15.60 · 10 → −4.68 / 52.32 / 17.39 ·
**12 → −3.56 / 50.39 / 18.10 (ranks 1, 2, 1)** · 14 → −4.30 / 49.03 / 17.04 ·
16 → −5.11 / 49.11 / 16.45.

**Selection by worst rank across all three:**

| cell | worst rank | early | nine | twenty |
| --- | ---: | ---: | ---: | ---: |
| `b5_12_1` | 3 | −2.62 | 54.03 | 20.10 |
| **`b5_12_2`** | **4** | **−0.96** | 52.03 | 19.84 |
| `b5_10_2` | 5 | −3.26 | **59.95** | **20.57** |
| `b5_14_1` | 6 | −2.67 | 51.12 | 18.65 |
| `b5_12_3` | **17** | −5.22 | 48.03 | 16.51 |

`b5_10_2` wins both **nested** windows and drops to 5th on the independent one. Spearman between
the nested pair is **+0.872**; between disjoint windows **+0.592**.

**Ruling: `2/12`.** Region entry 1–2 × exit 12–14 equally defensible; the cells differ by ~1 point,
inside noise. `entry_rank = 5` excluded despite scoring well — at `entry = n` the rule degenerates
toward owning exactly the top 5, the exit band never binds, and turnover triples to 2,527.

### 4.6 The participation ladder (WO-A16)

| floor | CAGR (screened) | foreign trades |
| --- | ---: | ---: |
| none | 16.32% | 21 |
| 0.90 | 18.08% | **23** |
| 0.95 | 16.14% | **12** |
| 0.98 | 17.40% | **0** |
| 0.99 | 16.83% | 0 |
| 1.00 | 17.78% | 0 |

On the *unscreened* tape this ladder was perfectly monotone 15.49 → 18.90. **On a screened tape the
monotonicity vanishes.** The apparent effect was the gate accidentally removing corrupt series.
**Recommendation: adopt at 0.98 for correctness only — the loosest rung that removes every foreign
trade. Do not quote a performance benefit.**

---

## PART V — THE DATA

## 5. Seven defects found in the tape

| # | defect | measured | status |
| --- | --- | --- | --- |
| 1 | foreign securities on `.US` tickers | 7 names, 21 trades, −$3,075 | gate built, threshold unruled |
| 2 | `concentrated.py` had **no tape screen** | 18 names, 55 trades, **−$166,343** | **fixed** |
| 3 | guard blind under $1 | 136 names, 1,865 bars | **fixed** |
| 4 | guard blind across trading gaps | `CLSK.US` at 9,372× | **fixed** |
| 5 | duplicates held concurrently | `BBBY_old`/`BBBY`, 9 sessions | open, detected by B7 |
| 6 | bar geometry violations | 1,432 bars | **none reached a fill** |
| 7 | runs never audited | everything to WO-A15 | **fixed**, audit gates the build |

**Specifics.** `PLZL.US` is Polyus on MOEX quoted in **roubles**; EODHD reports it as NYSE / USD /
USA — every field wrong. Rouble price × MOEX volume read as **$426m** of daily dollar volume and
cleared the $10m gate on an FX rate. `NVTK.US` showed $833m. `LAN.US` oscillates between $0.0050
and $4,730 **on alternating days** — two securities under one symbol, 465 times. `BMNR.US`
reverse-split 2025-05-16 with the raw close stepping exactly **400×** and the vendor's adjustment
exactly **20×**, leaving a fabricated 20× gain inside the formation window.

**Clean:** zero duplicate `(ticker,date)` rows; SPY/VOO/SPMO carry no discontinuity; cash identity
reconciles within costs; positions never exceeded 5 in 4,932 sessions; 974/974 entries filled at
the adjusted open.

## 6. Four learnings recorded (37–40)

- **37 — `code_stamp` is the first column to read when two runs disagree.** WO-A15 declared the
  engine non-reproducible and hunted a cause; the three runs simply carried three different code
  stamps. Held constant, runs 457/484/485 agree on all 974 trades and all 4,932 equity rows.
- **38 — vendor metadata is a claim, not a fact.** Three traps: the obvious holiday-print test is
  blind because the vendor serves foreign series already aligned to the US calendar; counting
  *finite* bars is blind because pads are finite; and `L0_MIN_BARS` admitting 210 of 252 lets a
  name absent 4% of the year pass.
- **39 — a gap measured as a RATIO is wrong for a score that is a proportion.** The dedupe scan
  proposed a cut of **0.0175** and put Randgold up for deletion in favour of Barrick. Fixed by
  selecting the gap by *difference* plus a `MIN_SAMENESS = 0.5` floor.
- **40 — a twenty-year backtest is not twenty years of evidence until you cut it.**

---

## PART VI — WHAT IS AND ISN'T PROVEN

## 7. The verdict

### 7.1 §2.5 says `unproven`

| | |
| --- | --- |
| Deflated Sharpe | **0.180** (bar: 0.95) |
| Trials logged | **361** |
| Observed Sharpe | 0.0396/session, 0.629 annualised |

After discounting for 361 trials of search, the observed Sharpe is not distinguishable from what
searching that many configurations produces by itself.

### 7.2 The regime gate — raised, and ruled against

**The regime gate has never been tested on the banded book.** Every gate number in §4.2 was
measured on the `w5` arm, where it converted 15.02% / −82.5% into 21.39% / −62.9% — nearly twenty
points of drawdown removed.

It was put to Zak on 2026-08-15 as the highest-value outstanding run, on the grounds that the
banded book's binding constraint is a −82.5% drawdown present in every cell on every window, and
that the gate is the only intervention ever measured to move it.

> **Ruling (Zak, 2026-08-15): there is no regime limit, and that is accepted.**

> **SUPERSEDED the same day by measurement.** Zak then asked for the gate to be tested anyway. It
> had never run on this book — `gated_off` was consulted by the calendar rebalance and nothing
> else, so the gate sold the book and the banded entry bought it back the same session. Once that
> was fixed, §7.2a. The ruling above was made on the honest belief that the gate was untested; it
> was in fact **untestable**, and what it measures now is not what anyone was ruling on.

### 7.2a What the gate does once it actually reaches the book

Twenty years, 4,933 sessions, against the ungated control at **20.06% / −82.5%**:

| cell | gate | CAGR | max DD | bootstrap p5 | deflated Sharpe |
| --- | --- | ---: | ---: | ---: | ---: |
| `b5_12_2` | **none** | 20.06% | **−82.5%** | 1.16% | 0.072 |
| `b5_12_2_gp` | sampled, no latch | **26.78%** | −63.0% | **10.62%** | — |
| `b5_12_2_L1_3` | latch 1 out / 3 in | **26.54%** | **−61.2%** | 9.90% | **0.214** |
| `b5_12_2_L1_1` | 1 / 1 | 26.16% | −62.1% | 9.41% | 0.202 |
| `b5_12_2_L1_5` | 1 / 5 | 25.99% | −61.3% | 9.51% | 0.203 |
| `b5_12_2_w250` | 250-day average | 25.76% | −63.2% | 9.46% | — |
| `b5_12_2_gate` | 1 / 10 | 23.82% | −60.9% | 8.04% | 0.159 |
| `b5_12_2_gr` | 1 / 10 + rising | 23.30% | −60.9% | 7.80% | — |
| `b5_12_2_w150` | 150-day | 21.64% | −60.8% | 6.60% | — |
| `b5_12_2_L1_20` | 1 / 20 | 21.30% | −61.8% | 6.24% | 0.109 |
| `b5_12_2_w100` | 100-day | 20.25% | −63.1% | 5.43% | — |
| `b5_12_2_L3_20` | 3 / 20 | 19.91% | −68.0% | 4.80% | — |
| `b5_12_2_L5_40` | 5 / 40 | 17.50% | −68.4% | 3.50% | — |

**Every one of the thirteen gate variants cuts the drawdown, from −82.5% to between −60.8% and
−68.4%.** There is no setting of this gate that does not remove fourteen to twenty-two points of
drawdown, and most raise the return as well.

**The latch ladder points the opposite way to WO-A10's.** On the `w5` arm 1/10 won and short
confirmations lost; here 1/3 wins and every long confirmation costs. Quick re-entry suits a book
that re-decides every session; slow re-entry suited one that re-decided twice a year. The `w5`
rungs were never evidence about this book.

### 7.2b And it turns the losing decade profitable

The disjoint window, 2007-01-05 to 2017-08-14, 2,671 sessions:

| cell | CAGR | max DD | trades |
| --- | ---: | ---: | ---: |
| `b5_12_2` ungated | **−0.96%** | −81.8% | 451 |
| `b5_12_2_t3` theme cap 3 | +1.18% | −79.2% | 447 |
| `b5_12_2_t2` theme cap 2 | +1.00% | −76.6% | 462 |
| `b5_12_2_t1` theme cap 1 | +2.89% | −68.7% | 551 |
| `b5_12_2_g2` cap 2 in a downtrend | +3.69% | −70.7% | 536 |
| `b5_12_2_g1` cap 1 in a downtrend | +7.60% | −68.2% | 459 |
| **`b5_12_2_gate`** full gate | **+11.08%** | **−60.2%** | 366 |

**§3's central finding needs restating because of this.** "Zero of twenty-five configurations made
money over 2007–2017" was true, and it was true of twenty-five **ungated** configurations. The gate
takes that decade from −0.96% a year to **+11.08%**, and takes 21.6 points off its drawdown.

So the regime dependence in §3 is not a property of momentum as such. It is a property of momentum
**held through downtrends**, which is the one thing this book was built never to stop doing. The
partial caps confirm the direction monotonically: the more the book holds in a downtrend, the worse
both windows get.

**What this does not do** is clear the §2.5 bar. The best deflated Sharpe here is 0.214 against
0.95, roughly tripled from the ungated 0.072 and still nowhere near proven. And the gate has now
been selected on both windows, so neither is out-of-sample for it.

The book runs ungated. This is consistent with §4.3's earlier ruling that the filter is advisory —
it makes the same choice at the strategy level rather than only at the desk level. **The −82.5%
drawdown is therefore an accepted property of the strategy, not an open problem**, and no document
should describe it as something a future change is expected to fix.

Two things this ruling does **not** settle, recorded so they are not later read as settled:

- The regime *dependence* in §3 is unaffected. Declining to gate on regime is a decision about
  what the book does; it is not evidence about whether the 2017–2026 result generalises.
- The gate's measured effect on the `w5` arm stands as a fact in the ledger. Anyone reopening this
  starts from `w5_g_plain` at 21.39% / −62.9% and the bracket in §4.2, not from scratch.

### 7.3 Everything else not established

- **No out-of-sample data exists.** All three windows were examined before the cell was chosen.
  2007–2017 is *disjoint*, not out-of-sample — it was used to select.
- **Kurtosis 10.16.** Fat tails make any single-number risk estimate optimistic.
- **A backtest on adjusted prices is unavoidably a hindsight exercise.** `adj_close` is
  back-adjusted from the present, so a 2025 split error corrupts a name's entire prior series.
  Measured consequence: run 558 ends the first decade at **$90,257**, run 508 sliced at the same
  date at **$78,452** — identical settings, different eligible universes, neither wrong.
- **A −80% drawdown has never been tested against a human.**

## 8. What follows

1. `2/12` replaces `3/12`. One-parameter correction to the entry band.
2. **No plan amendment should quote "19.84% a year."** Say: *−2.3%/yr for the first decade,
   +52.2%/yr for the last nine.*
3. **The book runs ungated** — ruled 2026-08-15, §7.2. The −82.5% drawdown is accepted, not
   pending a fix.
4. Because of 3, **the drawdown is a disclosure rather than a research task.** Anything written for
   a reader — a plan amendment, a product page — has to state that this strategy has historically
   lost four fifths of its value and taken thirteen years to recover, because no mechanism in it
   prevents that recurring.
5. A forward record is the only evidence that moves a deflated Sharpe. 361 in-sample trials cannot
   be undone by a 362nd.

**Nothing here is merged toward production, and nothing in this repository places an order. Yuna
proposes; Zak decides.**
