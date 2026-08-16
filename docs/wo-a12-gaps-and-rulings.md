# WO-A12 · Gap rulings and the verification design

**Written:** 2026-08-14. Companion to `wo-a11-daily-desk-spec.md`.
**Purpose:** every open gap, with a recommended ruling, split by what kind of thing it is — then
the design of a backtest that could actually be trusted with real money.

Zak rules on Part A. Part B is measurement, not opinion. Part C must be fixed whatever is ruled.
Part D is the verification design.

---

## Part A · Decisions — recommend and rule

### A1. Rank tie-break
**Recommend: `np.argsort(-score, kind="stable")`.**

This is not really about ties. `numpy.argsort` defaults to quicksort, which is **not stable**, so
the order of equally-scored names is an implementation detail of whichever numpy build ran. The
tape is loaded ordered by ticker, so a stable sort makes ties resolve ticker-ascending for free and
makes the book reproducible by construction rather than by accident.

One line. No behavioural change except determinism. Required before any parity vector can exist.

### A2. Sleeve NAV definition — *the most consequential ruling here*
**Recommend: the sleeve's own positions plus its own cash. In practice, TFSA NAV.**

Not a percentage of household NAV. Three reasons:

1. It is what the backtest models — a self-contained account compounding on itself.
2. §2.6 already puts momentum in the TFSA alone, and the TFSA is a distinct account.
3. A household-percentage definition couples the sleeves: a compounder drawdown would force
   momentum selling. Nothing has tested that, and it is not the strategy that was measured.

This ruling determines every position size, so it should be settled first.

### A3. Stale-mark behaviour
**Recommend: flag, do not instruct.**

The backtest's rule is *never buy on a stale mark; hold and sell on one*. Live, selling on a stale
mark means dumping into whatever print caused the staleness. If the slot's held name has no fresh
mark, the brief says so and proposes nothing for that slot that session.

A deliberate deviation toward caution, and it should be written as the live rule rather than left
as a difference nobody declared.

### A4. Universe staleness bound
**Recommend: 10 sessions, then halt.**

`ingest-universe` runs weekly. Ten sessions absorbs one missed run and refuses on two.

### A5. What a RED regime flag changes
**Recommend: nothing. Identical proposal, flag shown.**

This is Zak's stated intent, and it has a second virtue: the traded strategy and the tested
strategy stay identical, so the backtest keeps describing what is actually being run. The moment
the flag changes the proposal, every stored number describes a different system.

### A6. Account and funding
**Zak's entirely.** TFSA per §2.6. Two things to settle beyond that:

- Starting capital.
- **Whether contributions arrive on a cadence.** If they do, the backtest should model them —
  regular contributions change the compounding path materially and every number in this programme
  assumes a single lump at the start.

### A7. Where the constants live
**Recommend: §3.2 carries all nine explicitly.** But they are not equally well-founded, and the
plan should say which is which rather than presenting them as uniformly derived:

| constant | value | standing |
| --- | --- | --- |
| `FORMATION` | 252 | Academic 12-1 standard, and SPMO's published method. **Justified.** |
| `SKIP` | 21 | Same. **Justified.** |
| `VOL_WINDOW` | 252 | SPMO's own volatility adjustment. **Justified.** |
| `top_by_addv` | 500 | **Measured** — full universe returned 16.66% at −56.5% DD against the top-500 pool |
| `n` | 5 | **Measured** — the N sweep |
| `L0_MIN_RAW` | $5 | Standard penny-stock screen. Defensible convention. |
| `L0_MIN_ADDV` | $10m | Defensible: at $200k a 20% slice is $40k, 0.4% of a $10m day |
| `ADDV_WINDOW` | 50 | Convention. Inert within reason. |
| `L0_MIN_BARS` | 210 | **Weakest — no measurement behind it.** See B4 |

---

## Part B · Measurements — these need numbers, not opinions

### B1. Top-up threshold
Sweep **0 / 1% / 2% / 5%** of sleeve NAV.

Worth stating the prior honestly: **not topping up is not neutral.** Letting a winner drift past
20% is momentum-positive — you end up holding more of what is working — and with no stop-loss to
cap it, that could help as easily as hurt. This is genuinely uncertain and must be measured rather
than reasoned about.

### B2. Regime confirmation length
**This does not need a backtest.** It is a property of the SPY signal, not of the strategy: sweep
1–10 sessions and find the length that best separates the 13 sustained defensive regimes from the
39 flickers. One query over the benchmark series.

The loss function is Zak's attention, not money — the flag is advisory — so the objective is
alerts-per-real-regime, not return.

### B3. Concentration cap
Cells at **none / 0.70 / 0.50 / 0.40** maximum sector weight, using the existing `sector_cap`.

Caveat that needs its own decision: **1,375 of 6,333 stocks (22%) carry no vendor sector.** A cap
needs a rule for them. Recommend treating "unclassified" as its own bucket rather than exempting
it — exempting creates a hole a whole book could walk through.

### B4. `L0_MIN_BARS`
Run 189 / 210 / 252 and confirm it is inert. If it is, say so in the plan; if it is not, that is a
finding.

---

## Part C · Defects — fix regardless of any ruling

### C1. `next_open` is inert for this cell — **found 2026-08-14**
`next_open` is consumed at exactly one place in `simulate()`: the trail-stop exit path. `w5_notrail`
sets `trail=False`, so it never fires. **Every entry and exit prices at `adj[i]` — the same close
the rank was computed from.**

The live spec says market-at-next-open. So the backtest has never modelled the execution convention
we intend to trade. The `next_open=True` sitting in the cell's spec reads as though it had.

Partial evidence on the magnitude, from the rank-lag cells on the ten-year window:

| cell | CAGR | vs base |
| --- | ---: | ---: |
| `w5_notrail` | 43.91% | — |
| `w5_nt_lag1` (rank lagged one session) | 43.08% | −0.83 |
| `w5_nt_lag2` (lagged two) | 46.59% | **+2.68** |

Lag 2 beating the base says this is noise rather than a systematic same-close advantage, which is
mildly reassuring. It is **not** the same test as filling at the open, and cannot substitute for it.

**Fix:** make `next_open` govern every fill, not only stop exits, and re-measure. Open prices are
already in the store — `load_tape(with_range=True)` returns them.

### C2. Duplicate listings
`src/dedupe_scan.py` exists and is report-only. Run it, read the census distribution, then rule on
applying it. Until then the book can hold one company under two tickers. Measured impact on stored
runs was small (0.6–2.3% of trades) but it makes parity vectors impossible.

### C3. The slot clock deviates from the live rule
Backtest picks the slot with `session_ordinal % 5`; the live spec (§3.4 of WO-A11) uses
longest-since-reviewed. **Change the backtest to match the live rule**, so what is tested is what is
run. Under clean operation they are identical, which makes this cheap to do and pointless to skip.

### C4. 176 distinct specs, and I chose the best one
The deflated-Sharpe field for this family currently reads `"not scored — see the ledger's swept
runs"`. Bailey–López de Prado exists precisely to price this and has never been applied here.

**This is the largest unpriced risk in the programme.** It is not a defect in the code; it is a
defect in the claim.

---

## Part D · The verification design

### D0. What "locktight" can and cannot mean

It cannot mean out-of-sample, because there is no unseen data left. Every one of the twenty years
has been looked at, and the cell was selected after looking. Anyone who tells you a re-run on the
same tape is validation is wrong.

What it *can* mean is three things, and they are worth having:

1. **The instrument measures what we will actually trade** — fix C1–C3 so the simulated rule and
   the live rule are the same rule.
2. **The claim is discounted for the search that produced it** — C4.
3. **The result survives being attacked** — the robustness battery in D3.

And then one thing that is genuinely out-of-sample and starts today: **freeze the rule and run it
forward.** That is the only clean test, and it costs nothing but patience.

### D1. Order of work

Nothing is measured on a broken instrument. In sequence:

1. Fix C1 (`next_open` governs all fills), C3 (slot clock), A1 (stable sort).
2. Run C2's dedupe scan and apply.
3. **Pre-register**: write the exact rule, the exact metrics, and the pass/fail thresholds. Commit
   that file. *Then* run.
4. Re-measure the centre on the corrected instrument. **Expect the number to fall.**
5. Run the B-series measurements against the corrected centre.
6. Apply the deflation and the robustness battery.
7. Freeze and begin the forward record.

### D2. Pre-registration — what must be written down before the run

A run whose success criteria are chosen afterward proves nothing. Before step 4:

- the cell spec, complete, as a literal
- the window, the park, the universe snapshot
- the metrics that will be reported, in full, including the ones that might look bad
- the thresholds that would count as failure
- what will be concluded on each outcome

The existing `param_hash` / `code_stamp` machinery already stamps identity; this adds the intent.

### D3. The robustness battery — what substitutes for out-of-sample

| test | what it attacks | pass condition |
| --- | --- | --- |
| **Parameter neighbourhood** | Was the centre a spike? | n ∈ {4,5,6}, pool ∈ {250,500,750}, formation ∈ {189,252,315} — the majority of neighbours beat the benchmark |
| **Cost sensitivity** | Is the edge eaten by friction? | 1× / 2× / 3× the spread curve — survives 2× |
| **Slot phase** | Is it start-date luck? | all 5 phases of the slot cycle, spread reported, not just the best |
| **Sub-period stability** | Does it depend on one era? | rolling 3-year windows — report the share that beat SPY, and the worst |
| **Universe sensitivity** | Is it a data artefact? | with/without the delisted census, with/without dedupe |
| **Execution** | Is it the one-bar advantage? | same-close vs next-open vs lag-1 vs lag-2, all four reported |
| **Winner exclusion** | Is it one lucky name? | jackknife ex-top-1/3/5 (machinery exists) |
| **Deflated Sharpe** | Is it the search? | Bailey–López de Prado over **176** trials — the honest N, not the number in one grid |
| **Bootstrap** | Is the ordering luck? | 63-session blocks, 10k draws, seed 0 — report p5, not just the median |

Every one of these already has machinery in the repo except the deflation count and the execution
comparison.

### D4. Golden parity vectors

A frozen miniature tape — say 40 names over 400 sessions — with the expected book, session by
session, checked into the repo. The live desk and the backtest must produce identical books on it.

Without this there is no way to know that the daily job implements the strategy that was measured,
and every number in this document becomes a claim about code nobody compared.

**Blocked by C2** — a parity vector containing a duplicate listing is not reproducible.

### D5. The honest expectation

The corrected number will be **lower than 44.79%**. Next-open fills remove a one-bar advantage;
dedupe removes some double-counted winners; deflation discounts for 176 trials. I am not going to
guess by how much — that is what the run is for — but going in expecting the headline to survive
intact is how people end up arguing with their own instrument.

The twenty-year figures are the ones to plan around regardless: **15.02% CAGR, −82.5% drawdown,
bootstrap 5th percentile −3.4%.**
