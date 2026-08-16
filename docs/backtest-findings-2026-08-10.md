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

`backtest_runs.id = 15` — the whole tape: 5,276 tickers including 2,031 delisted names, ten years
of report dates, Zak's 2026-08-10 hair-trigger ruling in force. Conformance 15/15.

| | law-v0 | VOO |
|---|---:|---:|
| CAGR | **−0.73%** | **+15.46%** |
| Expectancy / trade | −0.43% net · −0.25% gross | — |
| Win rate | 29.0% | — |
| Max drawdown | −12.6% | — |
| Average exposure | 11.9% of NAV | 100% |

403 trades. Costs are $9,261 over nine years — 19 bps a trade, and not the problem.

**What moved it from the first run** (id 14: −1.53%, 21.6% win rate, −20.0% drawdown) was not
survivorship, which only ever flatters. It was two fixes landing at once:

* **The hair-trigger ruling.** Waiting out the confirmation window cut `unconfirmed` exits from 158
  to 95. Each one costs more when it does fire (−1.61% → −2.12%, exactly the wider-stop exposure
  the ruling accepts) but the bucket's total loss fell from −$23,276 to −$18,737.
* **The ten-year earnings calendar.** `earnings` exits went from 4 to 47 and are **profitable**
  (+1.52% each, +$8,939) — §3.3's hold-through cushion could not be tested at all before the
  backfill, and it works: those names return −0.11% over the next 60 days while VOO returns +4.04%.

### The survivorship correction is only half done

2,033 delisted names are in the universe and in the ranking pool, and **zero of them were
tradeable**: only 2 carry a fundamentals row, so M4 is unknown for the rest, and an unknown M4 is
not a pass. M4 coverage fell from 99.9% to **80.4%** for exactly this reason, and the conformance
table says so.

So the dead now dilute the percentiles and leave the census the day their bars stop — but the
system still cannot *buy* a name that later dies. **The headline remains flattered.** Closing it
needs a fundamentals sweep over the delisted census (2,031 names × 10 units ≈ 20k of a 100k daily
budget).

---

## 2. It is not the picks — it is the capture

The decisive test: take every entry the system made and ask what simply *holding* it would have
paid, against VOO over the identical windows.

| | per trade |
|---|---:|
| What the rules captured | **−0.51%** |
| Hold the same pick 25 sessions | +0.79% |
| Hold 63 sessions | +2.85% |
| **Hold 125 sessions** | **+8.00%** |
| VOO over those same 125 sessions | +7.09% |

n = 373. **The rules destroy roughly eight and a half percentage points per trade.** The selection
is mildly positive — 0.9pp better than the index over six months, under 2%/yr of edge — and the
mechanics turn it into a loss. Both figures survived the survivorship correction essentially
unchanged.

Confirmed exit by exit. What each name did in the 60 days *after* we sold it:

| Exit | n | We made | Name's next 60d | VOO's next 60d | Verdict |
|---|---:|---:|---:|---:|---|
| `unconfirmed` | 87 | −2.07% | **+4.96%** | +3.95% | sold winners at a loss |
| `gap` | 27 | −2.05% | **+6.26%** | +4.54% | sold winners at a loss |
| `template` | 20 | −3.49% | **+6.65%** | +4.55% | sold winners at a loss |
| `stop` | 121 | −1.92% | +2.23% | +3.17% | defensible |
| `stalled` | 67 | +5.07% | +1.98% | +1.50% | roughly neutral |
| `earnings` | 45 | +1.61% | **−0.11%** | +4.04% | **excellent** |
| `score` (MCN<55) | 3 | +3.12% | **−9.73%** | +0.38% | **excellent** |

Three exits sell names that then beat the market — `unconfirmed`, `gap` and now `template`, which
looked defensible on the smaller sample and does not here. The two that clearly earn their place
are the two judgement-shaped ones: the earnings cushion and the relative-strength score, both of
which get out immediately before the name underperforms badly.

The two exits that work are the two that look crudest — a four-week clock and a relative-strength
score. `score` exits immediately before names fall 9%. The mechanical volume exit is the killer:
143 names sold at a loss that then beat the market.

*(An earlier reading of this session blamed the stalled-pyramid rule for capping the right tail.
The forward returns refute it: stalled names go flat afterwards. The rule exits at the right
moment. What caps the right tail is the stop — see §4.)*

---

## 2b. The hair-trigger ruling, priced

Zak ruled on 2026-08-10 that a name inside its confirmation window waits it out. Both readings were
run over identical data (`backtest_runs` 15 and 16) so the ruling could be measured rather than
argued.

| | **Ruling: wait out window** | Rejected: cut while pending |
|---|---:|---:|
| CAGR | −0.73% | **−0.28%** |
| Total P&L | −$12,711 | **−$5,012** |
| Expectancy / trade | −0.434% | **−0.361%** |
| Win rate | **29.0%** | 27.0% |
| Max drawdown | −12.57% | **−12.17%** |
| Average loss | −2.95% | **−2.66%** |

The ruling costs about **$7,699 over nine years, 0.45pp of CAGR** — and the mechanism is visible
bucket by bucket:

| Bucket | Ruling | Rejected | Δ for waiting |
|---|---:|---:|---:|
| `unconfirmed` | 95 exits, −$18,737 | 151 exits, −$25,244 | **+$6,507** |
| `stop` | 129 exits, −$21,214 | 120 exits, −$16,625 | **−$4,589** |
| `stalled` | +$31,028 | +$31,610 | −$582 |

**Waiting does not avoid the loss, it relocates it.** Fewer names are cut at −1.73%; those held run
to the −7.6% stop instead.

Two qualifications. The expectancy difference is 0.073pp against a standard error near 0.25pp on
400 trades — directionally the ruling costs money, statistically it is a coin flip. And **both
variants lose money**, which is the finding that matters: there is no answer to *when to cut a
pending breakout* that pays, because the entry is what is wrong. Proposal A deletes the question
instead of answering it.

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

## 7b. The hypothesis grid (2026-08-11)

Zak's direction: *stop planning for the median, catch the big winners, press where there is
conviction, be looser on the stops.* The eight proposals in §8 were coded as opt-in variants —
law-v0 untouched, every default the law — and staged into presets so that each contains the one
before it. All runs sit on the same tape: 5,276 tickers, M4 coverage 97.9%, VOO +15.46%.

| | law-v0 | H1 | H2 | H3 | H3b | **H4** |
|---|---:|---:|---:|---:|---:|---:|
| | *baseline* | *+S1 S2 S3 E1* | *+R1 R2 R3* | *+P1 P2* | *P1 fixed* | *H2 + stagnation* |
| CAGR | −0.52% | +0.20% | −0.32% | −0.54% | −0.66% | **+0.04%** |
| Expectancy | −0.429% | −0.732% | −0.491% | −0.708% | −0.805% | **−0.304%** |
| Win rate | 29.8% | 16.0% | 16.3% | 15.8% | 13.7% | 16.7% |
| Average win | +5.29% | +11.58% | +11.48% | +11.15% | — | **+12.33%** |
| **Payoff** | 1.85:1 | 3.77:1 | 4.08:1 | 3.80:1 | — | **4.36:1** |
| Break-even win rate | 35.1% | 21.0% | 19.7% | 20.8% | — | **18.7%** |
| **Gap to break-even** | 5.3 pts | 5.0 pts | 3.4 pts | 5.0 pts | — | **2.0 pts** |
| Trades > +50% | **0** | 2 | 2 | 2 | — | 2 |
| Best trade | +35.1% | +89.6% | +89.6% | +89.6% | — | +89.6% |
| Max drawdown | −13.7% | −16.2% | −14.6% | −15.6% | −16.7% | **−12.4%** |
| Exposure | **12.3%** | 8.67% | 6.35% | 7.16% | 7.60% | 6.20% |
| Total P&L | −$9,090 | +$3,573 | −$5,652 | −$9,385 | — | **+$641** |

**H4 is the best variant on every per-trade measure** — payoff 4.36:1, two points from break-even,
the shallowest drawdown, and the only run besides H1 with positive total P&L. Its `stagnant` bucket
is the single best in the entire grid: **10 exits, +17.20% average, +$18,919**, held 36.3 sessions.
Making the stall clock's accidental profit-taking deliberate — and independent of pyramid size —
recovers most of what E1 destroyed, and keeps the runners a fixed four-week clock would have cut.

H4's remaining leaks are `gap` (−$10,514) and `template` (−$8,272 across 29 exits at −5.48%, the
worst per-trade bucket in the run). §2's forward returns already showed `template` sells names that
go on to beat the market.

**And H4's selection is materially better**, which the capture diagnostic isolates:

| | baseline | **H4** |
|---|---:|---:|
| What the rules captured | −0.51% | −0.08% |
| Hold the same picks 125 sessions | +8.00% | **+9.27%** |
| VOO over identical windows | +7.09% | +6.63% |
| **Selection edge over the index** | **+0.91pp** | **+2.64pp** |

S1 + S2 + S3 roughly tripled the six-month edge of the names chosen — from under 2%/yr to about
5.4%/yr. The mechanics still destroy ~9pp a trade, but the raw material improved.

**Nothing beat VOO. Nothing turned expectancy positive.** What the grid did establish is which
of the eight changes are real, and one of them is the opposite of what anyone expected.

### E1 is the one clear win

Confirming before entry deletes the `unconfirmed` bucket by construction — **−$20,726 gone** — and
flips `stop` from −$11,702 to **+$16,413**, because a position that reaches full size arms its
breakeven. The payoff ratio doubles, and a right tail exists for the first time: best trade +89.6%
against the law's +35.1%, two trades over +50% where nine years of law-v0 produced none.

### E1 also destroys the law's only profit centre

`stalled` was **+$29,284 of a −$9,090 total.** Under H1 it collapses to −$1,484, and not because
the rule changed: completing the pyramid on 56–62% of positions instead of 22% means "below full
size at four weeks" stops describing anything, so the clock never fires.

**That clock was profit-taking and nobody designed it as such.** It read as housekeeping — "no
permanent sub-scale positions" — and it only worked because a 29% volume-confirmation rate left
two thirds of the book sub-scale by accident. Every gain E1 makes is roughly cancelled by the rule
it silently switches off.

### The press layer is dead, and it inverts the premise

P1 was the mechanism for "press where there is conviction." Its first implementation demanded a
valid base *and* a breakout on the exact session the four-week clock expired — a coincidence, not
a rule, and it fired **zero times in 285 trades**. That was a bug in the proposal, not a result;
the uninitialised counter is what proved it (a green run with `conf["pressed"] += 1` in the path
means the path never ran).

Rebuilt with a 20-session window (H3b), it fired **once in 284 trades** — 25 windows opened, 1
press, 2 expiries, and 22 positions that leaked out through stops and template exits while
waiting. H3b is the worst run in the grid.

P2 is dead too: ten seats moved exposure from 6.35% to 7.16%. **The funnel is the exposure
constraint, not the seat count** — the screen does not produce enough qualifying names to fill
four seats, let alone ten.

So the two tests point the same way, against the instinct that motivated them: **what paid was
exiting a position that stopped advancing, not adding to it.**

### R1 narrowed the gap but moved the leak

The volatility stop gave H2 the best per-trade economics in the grid — 4.08:1, needing 19.7% wins
against 16.3% actual. Stop exits fell 154 → 111. But `template` exits jumped **6 → 32 at −4.21%
each**, and §2's forward-return table already showed `template` sells names that then beat the
market by two points. The binding constraint moved from the stop to the trend-template exit; it
was not removed.

---

## 7c. Why the +100% names are missed — it is one clause

The grid raised the obvious question: SMCI (+1,231% best year), MU (+1,029%), TSLA (+1,004%),
PLTR (+656%), MRVL (+409%), AMD (+373%) were all in L0 with full price history for the whole
window, and law-v0 traded **none of them**. NVDA once, for +12.6%. VST twice, for −2.9%.

Decomposing the funnel over those names against the ones we did trade:

| | names we traded | **big winners** |
|---|---:|---:|
| Base unbroken | 64.0% | 62.8% |
| **Base depth ≤ 25%** | **37.9%** | **11.5%** |
| **→ valid base on a given day** | **21.9%** | **5.9%** |
| Passes M2's "within 25% of the 52-week high" | 80.4% | 63.7% |
| **Average consolidation depth** | **29.4%** | **42.1%** |

The base-*break* test does not discriminate at all — 64% against 63%. **The depth limit does.**
A stock that doubles in a year corrects **42% on the way**, so §3.2 calls its base invalid seven
times out of eight, and M2's off-high tolerance rejects it another third of the time.

Every gate is individually reasonable and calibrated for orderly names: 25% depth, 25% off-high,
an 8% stop, a volatility divisor in the score, an ATR-tightness bonus. Together they describe a
stock that does not go up 100% in a year.

### We are wrong about the moment, not the name

Of 200 positions stopped out in H1:

| After we sold | |
|---|---:|
| Recovered above our exit price within 60 days | **96.0%** |
| 10% above our exit within 125 days | 68.5% |
| 25% above our exit within 125 days | 41.0% |
| Average best move after the exit | **+26.8%** |

The law offers no way back: re-entry needs a fresh valid base, and for a 42%-correcting name that
takes months it does not have.

---

## 7d. H5 and H6 — the eligibility gate, and a second door (2026-08-11)

Everything through H4 changes what we do with a position. §7c says the miss happens earlier than
that: the winners are excluded before ranking ever sees them. Zak's ruling — *"allow bigger
depths... allow buying back in on a name we trust... and it doesn't have to be where we sold... we
have to just buy back into strength on a strong name"* — turns into two variants, split so that the
contribution of each is separable.

### Which clause to move, measured before writing any code

Zak also asked whether the 25-session base minimum is right. It is worth measuring rather than
arguing, so both clauses were swept over the +100% names' full history:

| valid base on a given day | depth ≤ 25% (law) | depth ≤ 40% |
|---|---:|---:|
| **base age ≥ 25 (law)** | 5.9% | **29.3%** |
| **base age ≥ 12** | 6.8% | 33.7% |

**Depth is worth twenty-three points; base length is worth one.** The 25-session minimum is very
nearly irrelevant — it is in H5 to close the question, and it is the first thing to ablate if H5
wins. This is also the answer to "maybe there is a better indicator there": there is, and it is the
depth clause sitting next to it.

### H5 · eligibility scaled to how much the name moves

A flat 40% would hand a quiet utility a licence it has no use for, and that is not the hypothesis.
`signals.volatility_tolerance` floors at the law's number and widens only in proportion to the
name's own ATR, ceiling 60%. The multiplier is **8**, read off the measured median ATR of 2.86% of
price:

| the name's ATR | 2.24% (quiet) | 2.86% (median) | 5.00% | 7.50%+ |
|---|---:|---:|---:|---:|
| depth allowed | 25% (the law) | 25% (the law) | 40% | 60% (capped) |

So H5 is inert on the median name by construction. Applied to both the M3 depth clause and M2's
"within 25% of the 52-week high", plus base age 12.

One thing worth recording about the off-high half: it is narrower than it looks. An ordinary 30%
drawdown also puts a name under its own 50- and 200-day, so those conditions reject it first and
the off-high clause never gets a vote. It binds only where the SMA stack is far below — the shape
a name that has already tripled actually has. Depth is the big term; off-high is the small one.

### H6 · a way back in

§3.2 has one door into a name and none back through it. The trigger is deliberately **not** our
exit price: a close above every close of the prior 20 sessions, on a name that still passes M2, M4
and the MCN floor, with a five-session cool-off. Where we happened to sell is our history, not the
stock's — and 96% of stopped-out names traded back through it inside 60 days anyway, so anchoring
on it would mostly re-buy at a level the market had already left behind.

The new high is treated as the confirmation; no volume multiple is demanded on top of it. **That is
the clause to falsify if the re-entry bucket churns.** Timing follows E1 exactly — judged at last
night's close, filled at this open — and a re-entry gets its own volatility stop and pyramids off
its own fill, since there is no base and therefore no contraction low.

Every re-entry is stamped `backtest_trades.entry_kind = 'reentry'`, and on a run that did not
declare `reentry_window` it counts as a **conformance violation**, so a variant can never pass as
law-v0.

### Results — H5 and H6 are both refuted

| | H4 *(reference)* | H5 | H6 |
|---|---:|---:|---:|
| CAGR | **+0.04%** | −1.79% | −1.63% |
| Expectancy | **−0.304%** | −1.232% | −1.394% |
| Trades | 252 | 402 | 458 |
| Average loss | **−2.83%** | −3.57% | −3.44% |
| Max drawdown | **−12.4%** | −21.0% | −20.8% |
| Total P&L | **+$641** | −$29,752 | −$27,288 |
| **Best trade** | **+89.6%** | **+89.6%** | **+89.6%** |

The last row is the finding. 150 extra positions under H5, 206 under H6, and **the best trade does
not move by a hundredth of a point.** The widening admitted volume, not tail.

**The pre-run measurement that justified H5 was one-sided, and this is the lesson to keep.** It
asked whether the +100% names get a valid base under each clause — the numerator — and never asked
how many ordinary setups each clause also admits. `min_base_age=12` turns every twelve-day-old
local high into a candidate pivot, and no sweep over the winners could have shown that.

There is also a mechanical reason the depth clause cannot work as wired. A name that fell 40% has
its pivot at the pre-crash high, and under E1 the entry needs a close **above** the pivot — so we
buy only after the name has round-tripped, by which point the recovery is the move we missed. The
winners' +100% years happen *during* the climb back. Widening what counts as a valid base does not
help while the trigger sits at the top of the hole.

### X1 — re-entry on the best base, not the worst

H6 measures re-entry stacked on a widening that lost money, so X1 re-ran it on H4.

| | H4 | X1 |
|---|---:|---:|
| CAGR | **+0.04%** | −0.56% |
| Trades / of which re-entries | 252 / — | 362 / **209** |
| Win rate | 16.7% | **19.1%** |
| Average loss | **−2.83%** | −3.65% |
| Total P&L | **+$641** | −$9,746 |
| Best trade, re-entry bucket | — | +45.9% |

The falsifier written into the rule — *"that is the clause to falsify if the bucket churns"* —
fired: **209 re-entries.** And re-entry does not add to the strategy, it **displaces** it. The book
caps at four names, so those 209 crowded H4's 252 base entries down to 153. Per trade the
re-entries are slightly better than the base entries beside them (−1.15% against −1.06% in H6,
20.6% wins against 17.0%) and they hold longer, but their best is +45.9% against the base door's
+89.6%. A 20-session high catches bounces, not the names that run.

---

## 7e. The duration set — and the one thing that ever worked (2026-08-11)

Five variants had now tried to put more names in the book and every one lost money, while the only
profitable bucket in the whole grid was `stagnant`: +17.20% over 36.3 sessions. **Average hold
across every run ever measured is 10 to 13 sessions. A +100% year takes 250.** So the question
changed from what we buy to what cuts the hold short.

Three diagnostics ran first, and two of them saved a run each:

* **`gap` is not earnings.** Zero of H4's 43 `gap` exits fall within two days of a report — the
  blackout and cushion rules are working.
* **`gap` is the breakeven rung wearing a disguise.** 38 of the 43 are between −4.1% and −0.1%,
  6.4 sessions in. That is not a stock gapping through a 14% volatility stop; it is a position that
  popped, ratcheted its stop to average cost, and got taken out at cost on the first pullback. The
  109 `stop` exits at −0.49% and 9.4 sessions are the same event. **Together, 60% of H4's exits.**

| | H4 | T1 *(no template exit)* | B2 *(no euphoria)* | B3 *(stall clock 40)* | B1 *(no breakeven)* | **B5** *(rung ½R under cost)* |
|---|---:|---:|---:|---:|---:|---:|
| CAGR | +0.04% | −0.01% | −0.17% | −0.32% | −0.21% | **+0.10%** |
| Trades | 252 | 246 | 252 | 252 | 183 | 195 |
| **Avg hold** | 11.9 | 12.8 | 11.9 | 12.0 | **23.9** | **21.7** |
| **Win rate** | 16.7% | 17.1% | 16.7% | 16.3% | **37.2%** | **33.8%** |
| Average win | +12.33% | +12.30% | +11.32% | +11.48% | +10.79% | +11.00% |
| Average loss | −2.83% | −2.94% | −2.83% | −2.82% | −7.60% | −6.13% |
| Max drawdown | −12.4% | −13.2% | −13.7% | −14.6% | −13.9% | **−10.96%** |
| Total P&L | +$641 | −$204 | −$3,031 | −$5,652 | −$3,760 | **+$1,874** |

**T1 — the template exit is a label, not a leak.** Deleting H4's worst bucket (29 exits, −$8,272)
recovers almost none of it: `stagnant` goes 10 → 20 exits for the same total dollars and `stop` and
`gap` absorb the rest. The positions it was selling did not go on to make money for us; another
rule took them out days later for the same loss.

**B2 — refuted in the opposite direction to the one predicted.** Removing the euphoria tightening
left trade count, win rate and average loss *identical* and made the winners **smaller** (average
win 12.33% → 11.32%, best 89.6% → 84.9%). A 5% trail on a parabolic leg captures more of that leg
than a 25% trail does. §3.2 is right and the prediction against it was wrong.

**B3 — a rule can be slowed until it ceases to exist.** B3 is H4 with the stall clock at 40
sessions instead of 20; H2 is H4 with no stall clock at all. They produced the same 252 trades and
the same final NAV, **$194,348.12, to the cent.** Nothing survives 40 sessions, so the clock never
fires. The same happened to B4 (breakeven earned at 3R): byte-identical to B1, because with a
14–20% stop, 3R is +42% and nothing reaches it. `stagnant` is therefore not well described as
profit-taking — it is *the only rule in the system that ever meets a position at 36 sessions*.

**B1 and B5 — the rung, and where it sits.** Deleting the breakeven rung doubled the hold (11.9 →
23.9) and more than doubled the win rate (16.7% → 37.2%). It is the only intervention in fourteen
runs that moved duration at all. It also tripled the average loss, because every loser then runs
the full volatility stop. **The rung is not the enemy; a rung parked exactly on cost is** — price
oscillates around entry, so a stop sitting there is a magnet. B5 moves it half a risk *under* cost
and keeps nearly all of B1's duration at a third of the cost: best CAGR, best drawdown, and the
only positive P&L besides H4.

## 7f. The exposure ceiling — why none of this could ever have reached VOO

| | law-v0 | H4 | B5 | **VOO** |
|---|---:|---:|---:|---:|
| Days holding anything | 65.9% | 59.8% | 64.2% | **100%** |
| **Average exposure** | 12.31% | 6.20% | 9.76% | **100%** |
| Average names held | — | 1.28 | 1.82 | — |
| Days completely flat | — | 40.2% | 35.8% | **0%** |
| CAGR | −0.52% | +0.04% | +0.10% | **+15.46%** |

§3.2 sizes a position at `risk budget / stop distance`, capped by a 12% band. The budget is
0.7–0.9% of NAV, so against B5's 20% volatility stop a position is **4.5% of the account**, and the
book averages under two names. Fourteen runs were grading a ~10%-invested sleeve against a
100%-invested index. No entry, exit, stop or holding rule can close a 10× gap in capital at work.

**Zak's ruling, 2026-08-11:** *"to be fair we should say 100k USD is the amount and we can use all
of it... with up to 25% on high conviction... and that's vs. 100% in VOO."* Preset `z1` implements
it — budgets raised until a full-conviction name reaches a 25% ceiling against its own stop
(ordinary names land at 12.5%), sleeve cap 100%, $100k, and the whole position taken at entry
rather than §3.2's half-at-the-pivot, which hedges an unconfirmed breakout that E1 has already
confirmed.

## 7g. The trim ladder (M1)

Zak's own method: *"trimming 25% at 50% or so and trimming 25% at 100%. And then letting the rest
ride until the stock completely dies."*

§3.2 has no partial exit anywhere — a position is opened once and closed once — so this is the
first variant that required the **engine** to change rather than a threshold. `realise()` books any
quantity out of a position and writes that slice its own trade row, so `trim50`, `trim100` and the
runner's eventual exit are separately measurable; the lots shrink pro rata, leaving the basis, the
stop and the next rung measured against what the position actually paid. Each rung is a resting
limit sell at avg cost × (1 + level), not an end-of-day decision, so it cannot use a price the
session had not yet printed.

**"Until the stock completely dies" is read as immunity from the housekeeping exits** — template,
MCN floor, stall clock, stagnation clock — because those are how a position that is merely
*resting* gets closed, and a trimmed position is not resting. The runner keeps its stop, the market
gate and delisting. **That reading is an assumption**, and it is the first thing to revisit if the
runner bucket bleeds.

Trims are declared in the conformance table and count as a violation on any run that did not ask
for them, the same guard the variant exits and the re-entry door get.

### Results — the edge turned positive and the account still lost

| | H4 *($200k, §3.2 sizing)* | M1 *(void)* | **M1b** | **M2** |
|---|---:|---:|---:|---:|
| CAGR | +0.04% | −3.92% | −4.41% | −3.97% |
| **Expectancy** | −0.304% | **+1.392%** | **+1.272%** | **+1.549%** |
| Win rate | 16.7% | 33.9% | **39.6%** | 39.5% |
| Average win | +12.33% | +15.75% | +15.14% | **+15.82%** |
| Average loss | −2.83% | −5.98% | −7.82% | −7.78% |
| **Avg hold** | 11.9 | 20.0 | **24.5** | **24.9** |
| **Exposure** | 6.20% | 37.29% | 41.89% | **42.09%** |
| **Best trade** | +89.6% | +102.7% | +102.7% | **+178.5%** |
| **Max drawdown** | −12.4% | −49.4% | −53.5% | **−54.8%** |

**Run 33 (M1) is void and is kept only as the record of a preset error.** `entry_fraction=1.0`
marks a position step 3, which trips §3.2's "breakeven at full pyramid size" on its *first*
session — so B5's rung, whose value is that it sits below cost only after +1R, became an initial
stop of half the intended width applied before the position had earned anything. The `stop` bucket
alone was −$81,536 of a −$30,036 total, 95 exits at −3.48% against an intended ~10%, while every
other bucket netted +$51,500. The pairing is now asserted by test for any preset that opens full.

**M1b — the corrected run, and the diagnosis flips.** With the stop at its intended width, the
scratches stop (95 → 22 `stop` exits) but positions live long enough to fail the trend template
instead: `template` goes 28 → **64 exits, −$37,121**, and the six gaps that do occur cost
**−27.94%** each rather than −6%.

**M2 — the runner rule, confirmed by the name Zak named.** In run 33 all three runners died two to
four sessions after their second trim, on the euphoria rung: a stock up 100% is by construction far
above its own 50-day, so §3.2 cuts its trail to 5%, and 5% is one ordinary session for it. Give the
runner a 35% trail and exempt it:

| MU.US | exit | P&L | held |
|---|---|---:|---:|
| entered 2025-09-08 | `trim50` | +49.9% | 20 |
| | `trim100` | +99.9% | 67 |
| | **runner** | **+178.5%** | **130** |

Under M1b that runner was stopped at **+91.7% on bar 69**. AVAV went from a bar-60 exit at +102.7%
to bar 78; ATI 58 → 62; FTAI to 48. **+178.5% is the largest single trade in the grid** — the
number was welded to +89.6% through eleven variants of selection tinkering, went to +102.7% with
the ladder, and to +178.5% once the runner was allowed to run.

**Caveat on the record:** three of the five ladder positions exited on `gate_off` rather than on
their own merits, MU among them. The March 2026 gate closure ends them, so the ladder's headline
numbers are partly a function of where the window stops. Treat +178.5% as demonstrated-possible,
not as representative, until the same behaviour appears on trades that complete mid-window.

## 7h. Heat — the primitive §3.2 never needed

Read the two headline numbers of M1b together: **average trade +1.27%, drawdown −53.5%.** A
positive edge and a halved account are not a contradiction. That is what over-betting a real edge
looks like, and the cause is a missing constraint rather than a bad rule.

`sleeve_cap` limits how much of NAV is **invested**. Nothing limited how much could be **lost**.
Under the capital regime a 25% position behind a 20% stop puts **5% of NAV at risk**, and the book
holds four or five at once — so a fifth to a quarter of the account can be on the line
simultaneously. §3.2 never needed the concept because its 0.7–0.9% budget made every position 4.5%
and the question could not arise. Raising the budgets to honour "up to 25% on high conviction"
raised the risk per name by the same factor, and nothing caught it.

`heat_cap` sums what every open stop would cost if it all fired today and refuses an entry that
would breach it. At 6% the book carries one full-conviction name at full stop width, or several
whose stops have already ratcheted up — **heat rather than cash becomes the binding constraint**,
which is the right way round for a sleeve meant to press on conviction. Refusals are counted in the
conformance table so a heat-constrained run cannot look like one that found nothing to buy.

M3's result: CAGR −2.54% against M2's −3.97%, **drawdown −45.5% against −54.8%**, 127 trades with
**176 entries refused on heat**, exposure 26.4%. The lever is real and 6% is still too loose.

### A correction: expectancy never turned positive

Four write-ups in this session reported that the M-series had turned expectancy positive. **That
was an artefact of instrumentation added in the same change.** Partial exits made a trade row a
*slice* rather than a position, and a trim rung can only be hit by a name already up 50% or 100% —
the slices are winners by construction, and averaging them beside full exits is circular.

| run 36 | n | equal-weighted | avg position | total |
|---|---:|---:|---:|---:|
| trim slices | 5 | +69.85% | $3,359 | +$11,706 |
| **full exits** | **122** | **−0.56%** | $18,183 | **−$32,246** |

Headline `expectancy` +2.208%; **return on the dollar deployed −1.45%.** `summarise` now reports
`expectancy_full_exits`, `return_on_deployed`, `trim_slices` and `trim_usd`, and a test fails if
the headline and the full-exit figure ever silently agree on a run that trims.

---

## 7i. A1 — average in, trim early, then never sell (2026-08-11)

Zak: *"what if our biggest winners that made it to +100%... we never sold. We just kept them
long-term? ... averaged in ... on proven strength we widen the stops ... 25% at 35% and 25% at 75%
and if it makes it that high... never sell... unless the financials on the profitability of the
company dies."*

Four changes: three equal tranches 5% apart instead of §3.2's 50/25/25 at +0/+2/+4%; +25% of gain
earns a 40% trail and exemption from the euphoria cut; rungs at +35%/+75%; and past the last rung
the position stops being a trade — every §3.2 exit is a *price* exit, so the stop, trail, template,
score, clocks **and the market gate** all go, leaving only `profitability_dead` (two consecutive
reported quarters ≤ 0) and delisting.

| | M3 | **A1** | VOO |
|---|---:|---:|---:|
| **CAGR** | −2.54% | **+3.24%** | +15.44% |
| Total return | −20.5% | **+33.0%** | — |
| Win rate | 39.4% | 37.8% | — |
| Average win | +17.81% | **+25.75%** | — |
| Average loss | −7.92% | **−5.51%** | — |
| **Payoff** | 2.25:1 | **4.67:1** | — |
| **Avg hold** | 24.5 | **34.8** | — |
| **Max drawdown** | −45.5% | **−16.5%** | — |
| **Best trade** | +178.5% | **+524.3%** | — |
| Return on deployed | −1.45% | **+3.43%** | — |

**The first positive run in the grid**, and it improves on every axis at once — payoff, hold,
drawdown and tail. The forever hold does what it was designed to do:

| name | rungs | the remainder |
|---|---|---|
| **MU** entered 2025-09-08 | +34.9% @ 19 bars, +74.9% @ 43 | **+524.3%, still held at 240 bars** |
| **AVAV** entered 2018-06-27 | +34.9% @ 38 bars, +74.7% @ 56 | held **1,158 sessions (4.5 years)**, exited `profitability` Dec-2022 at +40.7% |

AVAV is the design working exactly as specified — held four and a half years through everything
price could say, and released only when the earnings test failed.

### The result is one position, and it is not closed

| A1's +$33,003 | n | USD |
|---|---:|---:|
| Realised | 89 | **−$4,999** |
| **Still open, marked to market (MU)** | **1** | **+$38,002** |
| Everything except MU | 87 | **−$8,980** |

**Every dollar of A1's profit is one unrealised position.** Strip MU and the run is −$8,980; strip
only the open mark and the realised book is −$4,999.

Two readings, and both are true. This is what a momentum sleeve is *supposed* to look like — the
tail is the whole return, and a strategy built to hold one name for 240 sessions and take 524% out
of it is behaving as designed. But a single open mark carrying the entire result is not evidence of
repeatability, and the position has not been sold: the +524% is a price on 2026-08-10, not money.

**Before A1 is treated as better than law-v0, the things to settle:**

* Re-run ending 2025-08 and 2024-08. If the result is positive only on windows whose last year
  contains MU, that is the finding.
* `template` remains the largest realised loss: 15 exits, −7.72%, **−$11,207**.
* A4 removed the §3.3 crash protocol from a live position. A1's −16.5% drawdown does **not** test
  that — the forever holds never met a bear market while open, since AVAV was released in Dec-2022
  by the earnings rule rather than by 2022's decline. A window with a forever hold running through
  2008 or 2022 would.
* 4 trims and 2 forever holds across nine years is a very small sample for the mechanism carrying
  the whole thesis.

### The pre-MU window settles it — and reframes the problem

Same variant, window ending 2025-08-31, before MU is entered:

| | A1 to 2026-08 | **A1 to 2025-08** |
|---|---:|---:|
| CAGR | +3.24% | **−1.43%** |
| Total return | +33.0% | **−10.9%** |
| Return on deployed | +3.43% | **−1.21%** |
| Best trade | +524.3% | **+74.7%** |
| **Trim slices in nine years** | 4 | **2** |
| Average hold | 34.8 | 32.6 |
| Max drawdown | −16.5% | −15.4% |

**A1's entire positive result is MU.** Without it the same rules lose 10.9% over nine years.

But the number that matters is not the CAGR, it is **2**. Across 2016–2025 — nine years, 84
trades — exactly **one position** ever reached the +35% rung: AVAV, which then produced the two
slices and the 4.5-year hold. One tail candidate per decade.

**This closes the loop the grid opened.** The capture problem is solved: A1 holds MU for 240
sessions and 524%, and AVAV for 1,158 sessions, which is everything the 2026-07-31 findings said
the system could not do. What A1 cannot fix is that **the funnel delivers roughly one tail
candidate every nine years**, and no amount of holding discipline can compound a sample of one.

That is the same wall §7c identified from the other side, and H5/H6/X1 failed to move: the gates
are individually reasonable and jointly describe a stock that does not go up 100% in a year. The
difference is that we now know it is the *only* remaining problem — the mechanics behind it work.

**So the next question is not "how do we hold better" but "how does a name like MU get into the
book more than once a decade", and the answer is not a wider depth clause** — that was H5, and it
admitted 150 positions without moving the tail at all. It is something about the selection that
none of the eighteen runs has tested.

---

## 9. The census of winners — the gates are inverted (2026-08-11)

Zak: *"those can't be the ONLY stocks that performed really well... it's almost like our grading
criteria is off... Can we do a query on every stock that performed 70%+ in a 3-6 month window...
and ask what their similarities are?"*

Built `research_monthly` — 425,341 monthly bars, all 5,276 US names including the delisted, 2016-08
to 2026-08 — and defined a winner-month as one where the name's high reaches **+70% within six
months**. Restricted to L0 liquidity (close ≥ $5, ADDV ≥ $10M, 12 months of history): **230,007
name-months, of which 15,155 are winner-months across 2,390 distinct names.** Half the liquid
universe produced a 70% six-month run at some point in the decade. Base rate **6.59%**.

### What a winner looks like the month before it runs

| median, the month before | non-winners (212,320) | **winners (14,990)** |
|---|---:|---:|
| Off its 12-month high | −15.3% | **−29.9%** |
| **12-month depth (low vs high)** | −40.9% | **−65.5%** |
| Prior 3-month return | — | positive |
| Prior 6-month return | +4.2% | +8.4% |
| **Prior 12-month return** | **+8.5%** | **+7.7%** |
| Price | $53.10 | $26.30 |

**Trailing twelve-month return does not discriminate at all** — the winners' is marginally *lower*.
The entire MCN quality score is a trailing-momentum measure (S1: slope × R² ÷ volatility over 90
days), which is why §3 found MCN does not rank within its own band. It is measuring something that
does not predict the thing we care about.

### The two core gates are anti-predictive

Lift = a rule's hit rate ÷ the 6.59% base rate. Below 1.00 means the rule selects names **less**
likely to run than a coin flip over the liquid universe.

| rule | n | hit rate | **lift** | share of all winners |
|---|---:|---:|---:|---:|
| DEEP (>50% off) + TURNING (3m > +10%) + 25%+ off high | 9,577 | 20.33% | **3.08×** | 13.0% |
| DEEP + TURNING | 35,382 | 15.63% | **2.37×** | 36.9% |
| 12-month depth worse than 50% | 78,609 | 15.37% | **2.33×** | **80.6%** |
| trailing 12m return, top quintile | 37,201 | 12.01% | 1.82× | 29.8% |
| more than 25% off the high | 72,786 | 11.65% | 1.77× | 56.6% |
| **— base rate —** | 227,310 | **6.59%** | 1.00× | 100% |
| **M2: within 25% of the 52-week high** | 154,524 | **4.21%** | **0.64×** | 43.4% |
| **M3: base depth ≤ 25%** | 23,590 | **0.25%** | **0.04×** | **0.4%** |

**M3's depth clause has a lift of 0.04.** A name passing it is twenty-five times *less* likely to
produce a 70% move than a random liquid stock, and **99.6% of every winner in the decade fails
it.** M2's off-high clause is also below the base rate at 0.64×. §7c said the depth clause was
excluding the winners; this says it is very close to a perfect filter for doing so.

### It is not a regime artefact — it holds in all ten years

| year | base rate | deep+turning | M2 near-high | M3 shallow base |
|---|---:|---:|---:|---:|
| 2017 | 3.37% | **12.98%** | 2.38% | 0.60% |
| 2018 | 2.80% | **8.76%** | 1.94% | 0.21% |
| 2019 | 2.95% | **9.06%** | 1.73% | 0.03% |
| 2020 | 19.43% | **29.05%** | 13.18% | 1.78% |
| 2021 | 4.07% | **7.33%** | 3.15% | 0.00% |
| 2022 | 3.75% | **8.12%** | 1.38% | 0.09% |
| 2023 | 4.86% | **11.34%** | 2.88% | 0.09% |
| 2024 | 5.15% | **13.02%** | 3.35% | 0.19% |
| 2025 | 11.39% | **27.36%** | 8.20% | 0.38% |
| 2026 | 6.11% | **10.85%** | 4.29% | 0.00% |

Deep+turning beats the base rate in ten years out of ten. M2 is below it in ten out of ten. M3 is
near zero in ten out of ten.

### And the hit rate is not the whole story — the forward returns agree

Hit rate could reward volatility rather than edge, so the same buckets by actual six-month
close-to-close return:

| bucket | n | mean fwd 6m | median | % up | mean worst drawdown | 90th pct |
|---|---:|---:|---:|---:|---:|---:|
| DEEP + TURNING + 25%+ off high | 8,653 | **+16.51%** | +6.94% | 56.1% | −26.3% | **+76.0%** |
| DEEP + TURNING | 31,545 | **+12.93%** | +5.92% | 57.0% | −22.9% | +63.6% |
| top-quintile 12m momentum | 32,569 | +6.94% | +0.16% | 50.2% | −23.7% | +51.8% |
| all liquid names | 209,855 | +5.71% | +1.96% | 53.5% | −19.6% | +39.2% |
| M2 only | 142,632 | +4.06% | +1.91% | 53.8% | −17.6% | +33.4% |
| **M2 + M3 (what we buy)** | 22,161 | **+0.28%** | +0.39% | 51.0% | −14.3% | **+19.5%** |

**The set our two gates admit returns +0.28% over six months** — against +5.71% for picking a
liquid US stock at random, and +16.51% for the deep-and-turning set. Its 90th percentile is +19.5%,
so the gates do not merely miss the tail, they select a population that **has no tail to miss**.
They do buy the calmest names — worst drawdown −14.3% against −26.3% — which is the trade §3.2
made, and it is the wrong one for a sleeve whose whole return is supposed to come from the tail.

### What this does and does not establish

It establishes that §3.2's selection is pointed at the wrong population, in every year, on both
hit rate and forward return, and that the alternative is not a loosened version of the same idea —
it is close to the opposite one. This is why H5 failed: widening depth from 25% to 40% still
selects on shallowness, and the winners live past 50%.

It does **not** establish that a deep-and-turning sleeve is tradeable. The bucket's mean worst
drawdown is −26.3% and 44% of it goes down. A signal with 3× lift and a 20% hit rate still needs
the entry, sizing, stop and hold discipline the B/M/A series built — and those were developed
against a different population, so none of their calibration transfers for free.

**This is a proposal for a new selection hypothesis, not a ruling.** §3.2's M2 and M3 stand until a
run beats law-v0 on the same rails.

## 9b. Moving averages, volume, volatility, and the financials

Zak: *"is there some kind of pattern to catch, before they gained momentum. Is there anything in
their financials or otherwise about them as a stock... or in their DMAs?"*

Same census, one feature at a time. Lift against the 6.59% base rate.

| signal | n | precision | **lift** | recall |
|---|---:|---:|---:|---:|
| **dollar volume 2x its own 12-month average** | 6,738 | 22.16% | **3.36×** | 10.0% |
| volume expanding + deep + turning | 10,470 | 20.68% | 3.14× | 14.4% |
| volume expanding (1.5x) + deep | 14,687 | 20.54% | 3.11× | 20.1% |
| volume expanding (1.5x) | 20,939 | 15.64% | 2.37× | 21.8% |
| price under $20 | 43,604 | 13.96% | 2.12× | 40.6% |
| **6-month average range > 12% (it moves)** | 162,424 | 9.05% | 1.37× | **98.0%** |
| MA stack *down* (close < ma3 < ma7 < ma10) | 36,965 | 7.64% | 1.16× | 18.8% |
| long MA still falling | 89,980 | 7.50% | 1.14× | 45.0% |
| below the 200-day | 96,983 | 7.03% | 1.07× | 45.5% |
| **— base rate —** | 227,310 | **6.59%** | 1.00× | 100% |
| **MA stack up (the trend template)** | 64,973 | **6.37%** | **0.97×** | 27.6% |
| **6-month average range < 6% (calm)** | 2,557 | **0.47%** | **0.07×** | 0.1% |

**The moving averages carry no information whatsoever.** Minervini's stack — the spine of M2 — has
a lift of **0.97**: indistinguishable from picking at random. Being *below* the 200-day is very
slightly better (1.07). Every DMA condition in §3.2 could be deleted without changing the odds.

**Volume is the best single predictor found anywhere in this work.** Dollar volume at twice its own
twelve-month average: **3.36× lift**. Money arriving is visible before the move.

**And volatility is a hard gate in the direction opposite to §3.2's.** A name whose six-month
average range is under 6% has a **0.47%** chance of a 70% move — lift 0.07. Range above 12%
captures **98% of every winner in the decade**. This is Zak's "high beta" instinct, and it is the
single most reliable thing in the census: **you cannot get a 70% move out of a calm stock.** §3.2's
ATR-tightness sub-score and its 25% depth clause both explicitly select for calm.

### The financials say the same thing, and it breaks a rule we just built

Point-in-time, using only quarters *reported before* the observation month (`research_eps`,
297,761 rows, 4,616 names).

| signal | n | precision | **lift** | recall |
|---|---:|---:|---:|---:|
| still losing money, but the loss is shrinking | 12,088 | 17.74% | **2.74×** | 14.8% |
| **latest reported EPS is negative** | 34,104 | 17.54% | **2.71×** | **41.4%** |
| loss a year ago, profit now (the S3 swing) | 11,938 | 10.98% | 1.69× | 9.1% |
| **missed** the estimate | 57,978 | 7.95% | 1.23× | 31.9% |
| beat by more than 20% | 46,217 | 7.52% | 1.16× | 24.0% |
| **— base rate —** | 223,074 | **6.48%** | 1.00× | 100% |
| beat the estimate | 150,130 | 5.92% | 0.91× | 61.5% |
| **M4: EPS growing ≥25% year on year** | 57,619 | **4.96%** | **0.76×** | 19.8% |
| **latest reported EPS is positive** | 188,970 | **4.48%** | **0.69×** | 58.6% |

**M4 — our earnings-acceleration gate — has a lift of 0.76.** Worse: **being profitable at all has
a lift of 0.69**, and being unprofitable has 2.71 and captures 41% of all winners. Beating the
estimate is mildly anti-predictive (0.91); missing it is mildly predictive (1.23).

**This directly contradicts A4, the forever hold.** Its release condition is
`profitability_dead` — two consecutive reported quarters at or below zero. On this census that
condition describes **the entry state of 41% of all winners**, so as written it would sell the
best candidates on day one. A4 was designed against the population §3.2 selects (profitable,
calm, near its highs) and does not transfer to the population that actually runs.

### The net, tuned the way Zak proposed

Start with a net that catches nearly all of them, then tighten. Each row adds one condition:

| step | n | precision | recall | lift | mean fwd 6m |
|---|---:|---:|---:|---:|---:|
| 0 · every liquid US name | 212,407 | 6.76% | 100% | 1.00 | +6.01% |
| 1 · + it moves at all (range > 12%) | 150,243 | 9.37% | **98.1%** | 1.39 | +7.79% |
| 2 · + it has fallen hard (depth > 50%) | 70,188 | 16.44% | 80.4% | 2.43 | +13.15% |
| 3 · + still 25%+ off its high | 38,460 | 18.50% | 49.6% | 2.74 | +14.78% |
| **4 · + turning up (3m > +10%)** | **8,644** | **21.67%** | 13.1% | **3.21** | **+19.07%** |
| 5 · + money arriving (adv 1.5×) | 1,601 | 31.92% | 3.6% | 4.72 | +15.01% |
| 6 · + money arriving hard (2×) | 1,087 | 34.22% | 2.6% | **5.07** | +15.37% |

The method works — precision rises monotonically from 6.76% to 34.22%, a 5× lift — but **mean
forward return peaks at step 4 and then falls.** Steps 5 and 6 keep raising the odds of a +70%
move while *lowering* the average outcome, because the volume filter also admits names with worse
downside. Precision and expectancy are not the same objective, and the tell only appears because
both were measured.

Step 3 or 4 is the tradeable region: step 3 keeps half of every winner in the decade at 2.74× lift
and +14.78% mean; step 4 gives 3.21× and +19.07% on ~72 candidates a month, which is far more than
a five-name book needs.

### The synthesis

Every gate in §3.2's momentum sleeve selects for the same latent quality — an orderly, profitable,
calm stock near its highs — and that quality is **anti-correlated with the outcome the sleeve
exists to capture**. Not weakly correlated. Anti-correlated, in all ten years, on hit rate and on
forward return, in the price data and in the earnings data independently.

| §3.2 gate | lift |
|---|---:|
| M3 base depth ≤ 25% | **0.04×** |
| M2 within 25% of the 52-week high | 0.64× |
| M4 EPS accelerating ≥25% | 0.76× |
| M2 moving-average stack | 0.97× |
| *(implied) profitable company* | 0.69× |
| *(implied) low ATR — the S2 tightness score* | 0.07× |

That is the whole answer to "how could our net grab so many losers but miss so many winners". The
net was never mis-tuned; it was pointed at the opposite population. And it explains every earlier
result at once: why MCN does not rank (§3), why the winners are missed (§7c), why widening depth
admitted 150 positions and no tail (H5), and why A1 found exactly one candidate per decade.

## 9c. The stop separates them — which is the opposite of the old population

Everything above says *what to buy*. This says whether it can be traded, and it is the best result
in the session. For the step-4 bucket (moves + deep + off its high + turning up), the drawdown that
comes **after** the observation:

| | n | 25th pct | **median** | 75th pct | breach −20% in 3m | breach −35% |
|---|---:|---:|---:|---:|---:|---:|
| **the ones that run +70%** | 1,958 | −20.5% | **−9.3%** | −3.1% | **20.2%** | 7.4% |
| the other 78% | 7,617 | −42.8% | **−24.9%** | −10.6% | **47.0%** | 21.5% |

**A stop is a discriminator here, not a tax.** A −20% stop removes 47% of the losers and only 20%
of the winners. §4 found the exact opposite on §3.2's population: the 8% stop was breached by 65%
of entries inside 125 sessions, so it fired on the winners first. **The risk machinery built in the
B/M/A series — volatility stops, the rung half a risk under cost, the heat cap — was built for a
population it could not help. On this one it can.**

### Expectancy with a stop, under a deliberately pessimistic assumption

Any breach in the six months is treated as a stop-out even if the gain came first, so these are
lower bounds. Six-month forward returns, no costs:

| population | n | no stop | stop 15% | stop 20% | stop 30% | stop 40% |
|---|---:|---:|---:|---:|---:|---:|
| **A · what §3.2 buys** | 22,603 | **+1.12%** | +0.80% | +0.82% | +0.83% | +0.81% |
| B · every liquid US name | 212,407 | +6.01% | +3.56% | +4.10% | +4.74% | +5.12% |
| C · step 3 | 38,460 | +14.78% | +8.51% | +9.88% | +11.52% | +12.55% |
| **D · step 4** | 8,644 | **+19.07%** | +11.44% | +12.67% | +13.59% | **+14.52%** |

**§3.2's population returns +1.12% per six months before costs** — about +2%/yr, which is precisely
what nineteen backtest runs produced from it. The census predicts the backtests, which is the
strongest evidence that it is measuring the right thing. Step 4 with a 40% stop is +14.52% per six
months on the same pessimistic basis.

## 9d. The C series — the screen on the rails, and an exit I misread three times

`c1` puts the census screen where M2 and M3 were, drops M4, and enters on a new 20-session closing
high because a name 50% off its low has no §3.2 base and will not have one for months. Everything
else is A1's machinery. $100k, fully deployable, 25% conviction ceiling.

| | C1 | C1b | C2 | **C3** | C4 |
|---|---:|---:|---:|---:|---:|
| screen exit | on *(by accident)* | **off** | **only from +10% profit** | **on, deliberate** | **quarter clause only** |
| CAGR | +0.51% | −0.98% | −1.52% | **+0.51%** | −0.11% |
| Total P&L | +$4,624 | −$8,459 | −$12,773 | **+$4,624** | −$951 |
| Trades | 253 | 178 | 210 | 253 | 198 |
| Win rate | **47.0%** | 42.7% | 43.8% | **47.0%** | 44.4% |
| Average win | +18.67% | **+28.02%** | +19.78% | +18.67% | +24.70% |
| Average loss | **−10.21%** | −12.47% | −13.24% | **−10.21%** | −10.99% |
| Avg hold | 14.3 | 29.1 | 20.2 | 14.3 | 20.3 |
| Max drawdown | **−18.0%** | −27.1% | −35.0% | **−18.0%** | −27.2% |
| Best trade | +148.4% | **+271.0%** | +149.5% | +148.4% | +148.4% |
| **Trim rungs fired** | **23** | 23 | 18 | **23** | **26** |

**The screen solves the problem it was built for.** 23 trim rungs against A1's 4 — six times the
tail candidates — and a 47.0% win rate, the highest of any run in the grid. "One candidate per
decade" is gone.

**The exit was read wrong three times, and every correction came from the bucket table rather than
from reasoning about the mechanism.** Recorded because the pattern is the lesson:

1. *"It is a bug destroying the winners."* 142 of C1's 253 exits fired on the screen at 9.1
   sessions, and the hold had collapsed from A1's 34.8. Removing it (C1b) doubled the hold to 29.1,
   took the best trade to +271% — and **lost $13,083.** The bucket had been **+$18,831**.
2. *"It is a profit-take."* Gating it on +10% of gain (C2) made the fired subset far better per
   trade — 27 exits at **+14.97%** for **+$40,449** — and the run far worse: **−$12,773**, drawdown
   −35.0%. The 115 positions it stopped selling did not recover, they rotted: `stagnant` went from
   −$335 over 9 exits to **−$21,267 over 30**, and `stop` from −$8,948 to −$17,677.
3. *"It is momentum death, so isolate that clause."* `deep_recovery`'s depth and off-high clauses
   can fail merely because the 252-day window rolls over, so only `r3` seemed to carry information.
   C4 fires on `r3 < 0.10` alone: **71 exits at −7.71% for −$36,287**, the worst bucket in its run,
   and the whole thing came in at −$951.

**The conjunction is the signal.** A soft quarter on a name that fell 50% and is grinding back is
normal and it recovers; the setup is only over when the quarter fades **and** the name has left the
cheap band. C3 reproduces C1 to the dollar through an entirely different code path — same 253
trades, same $4,624, same −18.03% drawdown — so the number is the rule's, not a side effect of the
mis-wiring, and it is now a declared exit (`no_longer_cheap`) rather than the template exit firing
on a screen.

**Where C3 actually stands:** +0.51% CAGR against VOO's +15.44%, full-exit expectancy −1.50%, the
run carried by 23 trims and the tail. Better raw material than anything before it, still not a
strategy. The outstanding test is the one that killed A1 — the window ending 2025-08, before MU.

### Is it "sentiment and attention"? Not quite — and the difference is testable

Zak's reading: *"high beta stocks that have high volume... as if we are riding sentiment and
attention, regardless of financials."* Two thirds right.

* **High beta — confirmed, hard.** Range under 6% → 0.47% hit rate. You cannot get a 70% move out
  of a calm stock, ever.
* **High volume — confirmed.** 2× its own twelve-month dollar volume is the strongest single
  signal in the census at 3.36×.
* **"Regardless of financials" — no.** The financials are not neutral, they are *inverted*.
  Unprofitable is 2.71× and covers 41% of winners; profitable is 0.69×. We were not ignoring them,
  we were reading them backwards.

And the drawdown table argues against pure attention-chasing. If this were froth, winners and
losers would be equally violent in both directions. Instead the winners are the **calmer** half
once the move starts — median −9.3% against −24.9%. That is not noise being chased; it looks like
**a depressed, high-operating-leverage business being re-rated**, where the market's re-rating,
once begun, does not give much back. The 3-month turn-up is the market's statement that the
re-rating has started; the volume is the money arriving to do it.

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
