# Momentum, measured against its own law — 2026-08-10

> **Read this instead of `backtest-findings-2026-07-31.md`.** That document's runs entered 211 of
> their 296 trades below MCN 70, which §3.2 forbids outright, and modelled a `volume unconfirmed`
> exit the plan had already replaced. Its central sentence — *"the selection is not the problem"* —
> was drawn from a trade population the selection rule would have refused. It is withdrawn.

First backtest of the momentum sleeve that calls the same `signals.py` functions the nightly calls,
over ten years, with costs charged, benchmarked on VOO total return, USD-native (ruled 2026-08-10).
Conformance 15/15 on every run cited here.

---

## 1. The headline

| | law-v0 | VOO |
|---|---:|---:|
| CAGR | **−1.53%** | **+15.57%** |
| Total return, 2017-09 → 2026-08 | −12.8% | +263.7% |
| Expectancy / trade | −0.71% net · −0.52% gross | — |
| Win rate | 21.6% | — |
| Average win / loss | +6.67% / −2.74% (2.4:1) | — |
| Max drawdown | −20.0% | — |
| Average exposure | 12.3% of NAV | 100% |

449 trades. Costs are 19 bps a trade and are not the problem.

---

## 2. It is not the picks — it is the capture

The decisive test: take every entry the system made and ask what simply *holding* it would have
paid, against VOO over the identical windows.

| | per trade |
|---|---:|
| What the rules captured | **−0.79%** |
| Hold the same pick 25 sessions | +0.71% |
| Hold 63 sessions | +2.78% |
| **Hold 125 sessions** | **+7.40%** |
| VOO over those same 125 sessions | +6.80% |
| Picks up at 125 days | 61.1% |

**The rules destroy roughly eight percentage points per trade.** The selection is mildly positive —
0.6pp better than the index over six months, about 1.2%/yr of edge — and the mechanics turn it into
a loss.

Confirmed exit by exit. What each name did in the 60 days *after* we sold it:

| Exit | n | We made | Name's next 60d | VOO's next 60d | Verdict |
|---|---:|---:|---:|---:|---|
| `unconfirmed` | 143 | −1.59% | **+4.69%** | +3.73% | sold winners at a loss |
| `gap` | 36 | −2.72% | **+5.99%** | +4.73% | sold winners at a loss |
| `stop` | 134 | −1.88% | +2.81% | +3.27% | defensible |
| `template` | 21 | −3.32% | +2.31% | +4.07% | fine |
| `stalled` | 69 | +4.73% | +0.90% | +2.28% | **well timed** |
| `score` (MCN<55) | 6 | +6.01% | **−9.19%** | −0.34% | **excellent** |

The two exits that work are the two that look crudest — a four-week clock and a relative-strength
score. `score` exits immediately before names fall 9%. The mechanical volume exit is the killer:
143 names sold at a loss that then beat the market.

*(An earlier reading of this session blamed the stalled-pyramid rule for capping the right tail.
The forward returns refute it: stalled names go flat afterwards. The rule exits at the right
moment. What caps the right tail is the stop — see §4.)*

---

## 3. MCN does not rank

Win rate and outcome by entry score, within the enterable band:

| MCN | n | Avg P&L | Win rate |
|---|---:|---:|---:|
| 70–75 | 186 | −0.60% | 21.0% |
| 75–80 | 159 | −0.45% | 22.0% |
| 80–85 | 90 | −1.47% | 21.1% |
| 85–89 | 13 | −0.21% | 30.8% |

Flat across 435 trades. Three components, cross-sectional percentiles, windows ending t−10 — and no
measurable separation inside the band the score itself defines as enterable. Range restriction
attenuates this, but a flat win rate across fifteen points is a finding, not noise.

Note also that the 85+ "full conviction" band fired **14 times in nine years**, so §3.2's
0.9%-vs-0.7% conviction sizing is very nearly decorative.

---

## 4. The stop and the holding period are incompatible

Worst drawdown from entry, measured on every entry the system took:

| Horizon | Average worst drawdown | Breaching 8% | Breaching 15% | Breaching 20% |
|---|---:|---:|---:|---:|
| 25 sessions | 7.0% | 33.6% | — | — |
| 125 sessions | 15.3% | **64.8%** | 40.3% | 26.9% |

§3.2 caps the initial stop at 8% and it averaged 7.57% below entry in practice. **Two thirds of
positions breach that inside 125 sessions**, so the +7.40% six-month return is unreachable by
construction: the stop fires first on 65% of the names that would have produced it.

An 8% stop buys a two-to-four-week swing sleeve. A six-month hold needs roughly a 20% stop. The
plan cannot have both, and it currently specifies the first while the evidence for an edge sits in
the second.

---

## 5. The arithmetic ceiling

`NAV return = deployed return × exposure`. §2 caps the momentum sleeve at 40% of NAV.

Even with perfect capture — the full +7.40% per 125-day trade, roughly 15%/yr on deployed capital —
four names held for months gives about 36% exposure and therefore **~5.4%/yr on NAV** against VOO's
15.6%. To match the index at the 40% cap the sleeve would need **39%/yr on deployed capital**.

The picks beat VOO by about 1.2%/yr. That is two orders of magnitude short of what the cap demands.

**So no exit rule reaches the benchmark.** Fixing the mechanics moves this sleeve from *losing
money* to *roughly market-on-deployed*, which is worth doing and is a precondition for measuring
anything else. Beating VOO requires either deployment far above 40% or a selection edge that does
not currently exist.

---

## 6. What the market gate did

| | Days | VOO over those days | Us |
|---|---:|---:|---:|
| Gate OFF | 621 | +17.6% | −1.5% |
| Gate ON | 1,554 | **+221.1%** | **−11.1%** |

M1 sat out 2.5 years during which the market rose 17.6% — real opportunity cost, no visible
protection. But it is second order. **The sleeve loses money while deployed, in the best tape
available.** That is a mechanics problem, not a timing one.

---

## 7. What this does not yet prove

- **The engine has not been differentially tested against `arming.py`.** Three of the findings
  above are conclusions about *interactions between rules*, which is exactly what a subtly wrong
  engine invents. The nightly agreement test (plan Phase 4) is the gate on trusting any of this.
- Survivorship was absent from the first run and is corrected in the runs that follow this
  document's first section; the delisted census added 2,031 names and 2.4M bars.
- One regime family. Ten years, one country, one currency.

---

## 8. Proposals (§5.8, drafted — none of these is law)

**A · §5.1 entry mechanic — confirm before entering.**
*Old:* breakout entries execute as GTC buy stop-limit orders at the pivot; the volume condition is
judged at EOD.
*New:* a session that **closes** above the pivot on volume ≥ 1.4× its own trailing 50-day is a
confirmed breakout, filled at the next open, limit pivot × 1.05. A close above the pivot without
the volume spends the base.
*Removes:* 143 trades at −1.59% whose names then beat the market. Collapses the freeze, the
late-confirm window and the hair-trigger — every position is confirmed at entry.
*Falsifier:* net expectancy does not cross zero.

**B · §3.2 Stops — breakeven at +1R, not at full pyramid size.**
*Old:* full size → breakeven.
*New:* unrealized gain ≥ the initial stop distance → breakeven.
*Why:* 141 stopped trades reached +6.98% unrealized and exited at −2.04%; breakeven is tied to a
sizing milestone that 305 of 449 positions never reach.
*Falsifier:* the 07-31 grid's "breakeven at step 2" converted winners into scratches. If 1R does
the same, revert.

**C · The fork, and it is Zak's.** Keep the 8% cap and accept a swing sleeve whose available return
is ~0 after costs; or move to a volatility stop (`2.5×ATR(14)`, capped at 20%), which requires
8–10 names instead of 3–4, positions near 3.5% — below §2's 4% floor and the 8–12% band — and
roughly doubled per-trade losses. **C is not tuning: it converts the sleeve from concentrated swing
trading into diversified trend following.**
