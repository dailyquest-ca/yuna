# E0 … E4 — Momentum Sleeve Backtest Programme — **v2.0**

**Issued:** 2026-08-12 · **Author:** Yuna (synthesis of the 2026-08-12 clean-engine session + external evidence review) · **Approver:** Zak (§4.5)
**Standing:** law-v0 (§3.2 as written) **remains the law**. Every run is opt-in via `params.hypothesis` and changes nothing in production until it clears the §2.5 statistical bars, the §3 bear gate, and Zak rules. Run numbering continues from the current ledger.
**Basis:** $200k USD (per the clean-baseline session), fully deployable, long-only, no leverage, no derivatives, manual execution. All math USD; no FX.

## Changelog v1.2 → v2.0 (supersession)

The 2026-08-12 session answered WO-0's question (the engine had six defects, now fixed; clean baselines re-run) and proved the capital layer (A1V beat VOO). v2.0 reorganizes the programme around what the clean data + research now say. Disposition of prior WOs:

| Prior | Disposition |
|---|---|
| WO-P (SPMO, bills ingestion) | **Done.** SPMO now used (§2.3, E4). |
| WO-0 (engine integrity) | **Done** — six defects (incl. ADDV split-factor look-ahead, 660 names / 170,220 name-days) fixed; clean baselines are the new record. |
| WO-13 (floor sweep) | **Superseded by evidence** — A1V's config (10% cash, VOO park) is the proven chassis; sweep retired. |
| WO-14 (marathon build) | **Folded into E4** (buy alternative) + §2.4.1 buy-vs-build pre-commitment retained. |
| WO-15 ladder (sprint mechanics) | **Superseded by E3** (rebuild at breadth) after C1/C3 isolated the exit lesson. |
| WO-16 (census battery) | **Partially executed**; remaining falsification is **E2**. |
| WO-17 (vol governor) | **Parked** pending E-series; revisit only at the bear-gate stage. |
| WO-P2 (2004 history extension) | **Retained** — it is the bear gate (§3, E-final). |

**2026-08-12 session open items, disposed:** O1 (`law_stamp` can't diff runs) → ticket **P1**. O2 (MU-excluded A1V) → **E1**. O3 (costs unsourced) → **closed**, §2.2 sourced curve. O4 (daily park rebalancing not manually implementable) → **closed**, §2.1 banded true-up. O5 (SPMO ingested, unused) → **closed**, §2.3/E4. T-bill fill → idle cash accrues at the historical 13-week bill coupon-equivalent series (unchanged).

---

## 1 · Established record (clean engine — do not re-derive)

Window 2017-09 → 2026-08, $200k. **VOO: +260.99% total, 15.44% CAGR, −33.99% max DD. 90/10 VOO/cash counterfactual: +222.10%.**

| Run | Total | CAGR | Trades | Win | Expectancy/trade | Notes |
|---|---|---|---|---|---|---|
| law-v0 | +5.65% | 0.62% | 405 | 30.6% | +0.02% | 12.3% avg exposure |
| A1 (tranches + trims + runner) | +56.53% | 5.15% | 96 | 38.5% | +8.44% | **MU = 71.4% of profit; top-5 = 106.4%** |
| C1 (census screen, screen-fail exit) | +17.10% | 1.78% | 175 | 49.7% | +9.80% | top-10 +$103k, rest −$69k; −22.7% DD |
| C3 (same entries, different exit) | +2.56% | 0.28% | 252 | 49.2% | +3.66% | exits alone swing expectancy 3× |
| M1 (trim ladder at size) | −8.07% | — | — | — | +2.21% | −39.89% DD @ 41% exposure — over-betting |
| **A1V (A1 + 10% cash, idle → VOO)** | **+295.25%** | **16.64%** | 97 | 38.1% | +8.35% | **only run to beat VOO; −30.23% DD** |

**Findings carried:** F1 only the capital layer beat the benchmark. F2 A1's headline is one trade. F3 the gap between per-trade edge and account return is sizing/exposure. F4 M1 = positive expectancy destroyed by over-betting. F5 C1-vs-C3 isolates the exit. F7 the capital rule is proven; the sleeve is not (A1V inherits MU dependency — E1 decides).

**External anchors (2026-08-12 evidence review):** Zarattini–Pagani–Wilcox 2025 (66,000+ trades, 1950–2024, survivorship-free): **<7% of trades produce the cumulative profits; ~56% of trades lose** — extreme concentration is the *signature* of the tail-capture family, and 96 trades is far below convergence. Family gross ceiling ≈ 15% CAGR / ~6% alpha with −32% DD; turnover control is the binding constraint at small AUM. Bessembinder: 4.3% of stocks = all net wealth creation. Kelly literature: over-betting past ~2× Kelly drives growth to zero; fractional risk-per-trade + heat is standard. MAX/lottery literature (Bali-Cakici-Whitelaw): high-MAX names carry **−1.18%/month** four-factor alpha — the C1 population overlaps it. Rebalancing literature: tolerance bands beat calendar and daily. Momentum 2020–2026: long-short factor decayed; **low-turnover long-only large-cap leader-holding (SPMO ~20%/10y) is the surviving implementation**; crash episodes 2020 / 2022 / 2023 reconstitution miss / 2025 unwind all sit at inflections our window lacks.

---

## 2 · Fixed inputs

### 2.1 Capital chassis (proven; standard on every E-run)
A1V config: **10% cash target; all idle capital parked in VOO** (total return, dividends → cash). Park is a vehicle, not a position (no caps/themes/rungs; zero heat). **Banded true-up:** entries always fund from cash; check weekly; trade the park only when cash deviates > 5 pts from the 10% target. Production posture remains Zak's D1 ruling; E-runs test at the proven config. **The cash-idle counterfactual is retired as a benchmark — every active design competes against being 100% invested.**

### 2.2 Transaction-cost curve v1 (sourced; replaces flat 5/15 bps)
Half-spread per side by point-in-time ADDV bucket — anchors: ~1–5 bps large-cap (Nasdaq S&P 500 spread data), ~18 bps small-cap (Frazzini–Israel–Moskowitz realized), 50+ bps micro-cap; retail price improvement (~47% of quoted spread in S&P names) treated as unmodeled conservatism.
| ADDV | ≥$50M | $10–50M | $2–10M | $0.5–2M | <$0.5M |
|---|---|---|---|---|---|
| bps/side | 5 | 10 | 18 | 35 | 60 |
Bucket edges may be refined by Code with sources; **anchors are fixed**. E2 additionally stresses micro names at 50+ bps.

### 2.3 Benchmark policy
Hierarchy: **bills < VOO < E4 blend (once established) < SPMO** (alpha-arm comparator; N/A pre-2015-10; SPY hands off for VOO pre-2010-09 on extended windows). VOO on every run, matched windows. Attribution on failures: comparator down too ⇒ regime; comparator up while we bled ⇒ craft.

### 2.4 Pre-commitments (carried)
1. **Buy-vs-build:** in-house edge over SPMO < ~2 pts/yr net (full + OOS) ⇒ the momentum-beta allocation is the ETF.
2. **SPMO in production (park or tilt) ⇒ §3.1-style concentration review first** (top-10 ≈ 50%, stacked on the compounders' mega-cap complex).
3. **Scout rule:** unhardened results are existence proofs, never findings.
4. **Grid discipline:** this document is the entire grid; off-grid exploration requires a new announced WO.

### 2.5 Statistical bars — the formal definition of "proven" (new)
A result is a **finding** only with all of: (a) full-window + Aug-2025 OOS cut; (b) **top-1/3/5 winner-exclusion (jackknife)** survival — the headline claim must hold ex-top-3; (c) **block-bootstrap** CIs (calendar blocks ≈ 63 trading days on daily strategy returns, 10,000 draws; report 5th/50th/95th of CAGR and max DD) with **bootstrap-median > benchmark**; (d) **Deflated Sharpe Ratio** using the logged configuration count for the whole programme (≥ 50 trials; log the exact number) and the trade distribution's skew/kurtosis, with t ≈ 3 as the aspiration bar; (e) costs per §2.2. Per-bucket P&L and conformance tables remain mandatory (§4).

---

## 3 · Work orders (execution order as listed)

### P1 — `law_stamp` diffability *(engineering ticket; parallel)*
Extend the stamp so any two runs can be parameter-diffed mechanically (param hash + structured param dump). Blocks nothing; required before E3's arm family reports.

### E0 — Measurement retrofit *(first; cheap; reinterprets everything already run)*
Re-score **A1, A1V, C1** (law-v0 optional) under §2.5 (a)–(e) with §2.2 costs. No strategy changes.
**Output:** a "proven / unproven / dead" verdict per arm under the formal bars.
**Interpretation:** an arm whose bootstrap-median falls below VOO **or** whose edge vanishes ex-top-3 is **unproven** — barred from scaling, not necessarily dead.

### E1 — The Micron question *(the decisive cheap experiment)*
A1V with all MU trades excluded; the capital MU consumed follows chassis rules (sits in the VOO park). Compare vs VOO and vs the 90/10 counterfactual, full + OOS, §2.5 bars.
**Reads:** still beats ⇒ the active overlay has support beyond one name. Doesn't ⇒ the overlay is unproven at current breadth — **E3 proceeds regardless** (breadth is the prescribed fix either way), but sizing ambition recalibrates.

### E2 — C1 falsification *(one honest execution, then it lives or dies)*
Re-run C1 with: (a) §2.2 costs including the 50+ bps micro stress; (b) hard floors — price ≥ $5 and ADDV ≥ {$2M, $10M} (two arms); (c) profitability gate — point-in-time TTM EPS > 0 (F-score proxy where data allows).
**Kill:** edge survives only in sub-$5 / thin names, or dies under sourced costs ⇒ retire the screen; the MAX/lottery literature predicted the mirage. **Pass:** survives all three ⇒ genuinely anomalous; re-opens as its own programme.

### E3 — Flagship rebuild: **A2 — trend-holding at breadth** *(the arm the evidence supports)*
Baseline machinery = A1's, with these pre-registered deltas. **Center spec:**
- **Universe:** point-in-time ADDV ≥ $10M and price ≥ $5 (floors kill the lottery corner).
- **Entry:** breakout to a new 252-day high close, **plus** the M2 trend template as quality gate (price > 50d > 150d > 200d, 200d rising). M4 earnings gate **dropped** (it starves breadth; price is the workhorse). Re-entry permitted on any fresh signal.
- **Breadth:** target **30 concurrent positions**; if fewer qualify, capital stays in the park — never force entries.
- **Sizing:** fixed **0.5% of equity risked per trade** to the initial stop; never conviction. Derived heat = N × r (center 15%); the governing risk constraint is the DD pass bar below, per the M1 lesson.
- **Exits:** initial hard stop at **3×ATR(20)** from entry; once price ≥ entry + 3×ATR (1R), switch to a **Chandelier trail: highest close since entry − 8×ATR(22), recalculated ATR, ratchets up only**. No profit targets on the runner.
- **Trims:** center = **none** (pure trend-hold); alt = 25% at +35% / +75% (A1 DNA).
- **Chassis:** §2.1 on every arm.
**One-axis sensitivity only (≈ 9 runs total):** positions {20, 50} · risk/trade {0.25%, 1.0%} · trail {5×, 10×ATR} · entry {252d high → all-time high} · trims {none → +35/+75}.
**Pass:** beats VOO net of §2.2 costs **with top-3 winners removed**, bootstrap-median CAGR > VOO, bootstrap max DD ≤ −34%, on full + OOS. **Kill for a cell:** bootstrap-median < VOO or DD bar broken — no re-tuning beyond the pre-registered arms.

### E4 — The buy alternative *(standing benchmark; possibly the destination)*
VOO core + SPMO tilt, banded per §2.1 mechanics: arms {100/0, 90/10, 80/20}. Full + OOS + §2.5(c).
**Role:** once run, the best E4 blend joins §2.3 as the bar every active result must clear on deflated, bootstrap-median terms. **If E3 cannot clear it, the honest terminus is: hold the blend, stop trading single names.** SPMO in any production role triggers §2.4.2 first.

### E-final — Bear gate *(before any production candidacy)*
Extend history to 2004-01 (WO-P2 spec: delisted coverage audit first; EPS columns partial where point-in-time unavailable; SPY pre-2010-09; SPMO N/A pre-2015-10). Re-run every surviving E-cell across 2004–2026 with regime slices: 2007-10→2009-06, 2011H2, 2015-08→2016-02, 2018Q4, 2020-02→04, 2022. **No arm reaches production candidacy without surviving one full bear in-sample** — 2017–2026 contains none, and momentum's documented crashes all live at inflections our window lacks.

---

## 4 · Shared protocol — non-negotiable

1. Conformance table every run; DEAD-rule flagging (heat scoping: park = zero heat by design; any *stop-bearing* position escaping heat is a defect).
2. Expectancy = deployed-dollar only; slices never averaged with positions.
3. §2.5 statistical bars before the word "finding"; single-name exclusion is the first robustness check, not the last.
4. Exits diagnosed from per-bucket P&L, never mechanism reasoning.
5. Benchmarks per §2.3, matched windows, seams explicit.
6. Costs per §2.2; cash at the 13-week bill series; USD only.
7. Grid discipline per §2.4.4.
8. Biases footer (vendor current-version statements; today's industry mappings; reconstructed L0; coverage audit on extended windows).
9. Scout rule per §2.4.3.
10. Regime-sliced reporting once E-final data lands.

---

## 5 · Decision points

- **D1 — Production posture (Zak):** chassis config for the live book (cash target, park vehicle, bands). E-runs assume the proven A1V config; the ruling formalizes it.
- **D2 — Buy vs build:** governed by §2.4.1 after E3/E4; SPMO in production ⇒ §2.4.2 review first.
- **D3 — C1 standing:** decided by E2. **D5 — vol governor:** parked to the bear-gate stage.
- **Kill-switches:** E0 demotes any arm failing the bars · E2 kill condition retires the census screen · E3 cells die on their bars with no re-tuning · E4 unbeaten ⇒ hold-the-blend terminus.
- Any cell clearing §2.5 + E-final ⇒ candidate for an **announced §3.2 edit** (exact old/new lines, Zak's approval). Until then: law-v0 is the law, the sleeve stays start-low, NUE/RS run unchanged, nothing touches production.

**Execution order: P1 (parallel) → E0 → E1 → E2 → E3 → E4 → E-final on survivors.**

---

## Corrections to §1 applied on receipt (2026-08-12)

Two figures in the established-record table were transcribed from the wrong run. Since §1 is
marked *do not re-derive*, they are corrected here against `backtest_runs` rather than left to
propagate into E0/E1, both of which score against A1V.

- **A1V** read 96 trades / 38.5% / +8.44% — those are A1's (run 48). Run 53 is **97 trades,
  38.1% win, +8.35% expectancy**. The return, CAGR and DD were correct.
- **C3** read ~175 trades; run 50 took **252**. The 3x expectancy swing against C1 stands, and
  is in fact slightly understated — C3 spread a weaker edge over more trades.
