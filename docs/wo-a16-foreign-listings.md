# WO-A16 — foreign securities on `.US` tickers

**2026-08-14.** Found while verifying run 484 for WO-A15. The universe contains securities that do
not trade in the United States and are not quoted in dollars, carried under `.US` tickers, and no
field in the vendor's own metadata admits it.

## 1. What was found

`PLZL.US` is Polyus, the Russian gold miner. Its price series is the MOEX line, quoted in **roubles**.

Our stored bars are byte-for-byte identical to what EODHD serves — every OHLCV value on every date
checked. **The ingest is faithful and the defect is upstream.** What the vendor says about the
ticker is this:

| field | EODHD's answer | the truth |
| --- | --- | --- |
| `Exchange` | `NYSE` | MOEX |
| `CurrencyCode` | `USD` | RUB |
| `CountryName` | `USA` | Russia |
| `Type` | `Common Stock` | correct |

Polyus has never been NYSE-listed. Every identifying field is wrong, so **no metadata check can
catch this** — including the one `src/backfill.py` already performs, which reads `Currency` from
the exchange symbol list and passes it through faithfully. It received `USD` and stored `USD`.

Confirmed cases, all reached through the delisted census (`added_at` 2026-08-10 / 2026-08-14):

| ticker | company | home market | quoted in | median "dollar volume" |
| --- | --- | --- | --- | --- |
| `NVTK.US` | Novatek | MOEX | roubles | $833,212,860 |
| `PLZL.US` | Polyus | MOEX | roubles | $426,141,232 |
| `IVL.US` | Indorama Ventures | SET | baht | $344,104,800 |
| `MGROS.US` | Migros Türk | BIST | lira | $15,390,528 |
| `KSL.US` | Khon Kaen Sugar | SET | baht | — |
| `KKP.US` | Kiatnakin Bank | SET | baht | — |
| `VJC.US` | VietJet Aviation | HOSE | dong | — |

The liquidity screen is where this bites. §3.0's L0 gate requires $10m of average daily dollar
volume, computed as price × volume. In roubles that product is a rouble figure compared against a
dollar threshold, so **Polyus cleared a $10m gate on nothing but an FX rate** and was ranked as one
of the most-traded names in America.

## 2. What it cost

Direct P&L of the seven confirmed names in run 484 (b5_12_3, 2007-01-05 → 2026-08-13):

| ticker | trades | P&L | avg return |
| --- | --- | --- | --- |
| `NVTK.US` | 2 | +$527 | +2.08% |
| `KKP.US` | 1 | +$160 | +3.06% |
| `IVL.US` | 5 | −$109 | −0.34% |
| `MGROS.US` | 2 | −$112 | −0.32% |
| `KSL.US` | 1 | −$426 | −7.75% |
| `PLZL.US` | 9 | −$726 | −0.42% |
| `VJC.US` | 1 | −$2,389 | −16.67% |
| **total** | **21** | **−$3,075** | |

Against the run's total P&L of **+$1,601,608**, that is **−0.19%**. The contamination is real, it is
slightly *negative*, and **it did not manufacture the 15.49% CAGR.**

That figure is a floor on the honesty of the headline, not a full accounting. Two effects it does
not capture:

- **Path.** Removing 21 trades changes which slots were occupied when, so the counterfactual is not
  simply +$3,075. Only a re-run prices it.
- **Selection.** A contaminated name with fake dollar volume displaces a real name from the top-500
  ADDV pool whether or not it is ever bought.

## 3. The detection rule

Since the metadata lies, the test has to be intrinsic to the price series. The one thing a foreign
line cannot fake is **trading when the NYSE is open and its own market is shut.**

Two things had to be established before that could be used as a gate.

**SPY is a trustworthy calendar.** Weekdays with no SPY bar run 8–11 per year across 2005–2026,
which is the US market holiday schedule — including the extra closures in 2012 (Hurricane Sandy)
and 2025. There are no unexplained holes to generate false positives.

**The obvious test does not work.** Bars printed on a US holiday catch `CNGL.US`, `SCCC.US`,
`WOW.US`, `ESSA.US` and `CIND.US` — real volume on Labor Day, Memorial Day and July 4th — but catch
none of the seven above. The reason is that EODHD serves those series **already aligned to the US
calendar**: the vendor's `PLZL.US` has no bar on 2021-07-05, though MOEX traded that Monday.

What survives the alignment is the *residue* — the name's own market holidays, which fall on days
the NYSE is open. That is the signal:

> **no-trade rate** — the share of US sessions inside a name's own listed window on which it did not
> actually trade: no bar at all, **or** a bar with zero volume.

The zero-volume clause is not decoration. The vendor pads some foreign series flat rather than
omitting them: `IVL.US` carries **271 zero-volume bars in 1,483**, which is why its session count
matches SPY's exactly and why a check counting *finite* bars sees nothing wrong.

Measured over the 457 names run 484 traded:

| population | no-trade rate |
| --- | --- |
| `AAPL.US`, `MSFT.US`, `XOM.US`, `NVDA.US`, `JWN.US`, `X.US` | **0.00%** |
| `NVTK.US` | 3.46% |
| `PLZL.US` | 3.80% |
| `MGROS.US` | 4.17% |
| `KKP.US` | 5.96% |
| `KSL.US` | 9.15% |
| `IVL.US` | 18.27% |

Across the whole universe, restricted to names liquid enough to matter, the distribution is
bimodal: it decays from 0% to a trough at 2–3% (32 names), then rises again through 3–5% (67),
5–10% (78) and 10%+ (227). Roughly 8–12 home-market holidays a year is 3–5%, which is where the
second mode sits.

**The rate is a screen, not a verdict.** It conflates a foreign calendar with genuinely thin
history — `QUBT.US`, `ONDS.US` and `CLSK.US` appear alongside the foreign lines because they were
penny stocks with real no-trade days before they became liquid. An attempt to separate the two by
testing whether the gap dates recur annually failed: a name with thousands of gap days hits 100%
recurrence by pigeonhole, so the statistic is only meaningful where gaps are few.

That failure does not matter, because **the gate should not try to separate them.**

## 4. The gate

Implemented in `src/concentrated.py` as `min_participation`: a name is eligible only if it actually
traded on at least that fraction of the sessions in its formation window.

It is deliberately a **liquidity rule, not a nationality rule.** It says a name must trade on the
sessions this book would have to fill on. It ejects foreign lines and untradeable ones by the same
test, needs no list of countries to maintain, and rests on no assumed constant — the threshold is a
declared rung, and the ladder below prices each one.

`bars >= L0_MIN_BARS` could never have done this job: it admits 210 of 252, so missing 4% of
sessions passes with room to spare, and it counts finite bars, which the pads defeat.

**Default off.** A test proves the gate is inert rather than merely lenient when unset, so every
cell ruled before WO-A16 reproduces to the last decimal.

## 5. The ladder

Five rungs, each the gate alone off `b5_12_3` — Zak's chosen cell — plus the ungated control, which
must return the known 15.494835% and so doubles as proof the code change moved nothing.

Window 2006-01-01 → open, park and calendar SPY.US, start NAV $100,000.

| cell | participation floor | sessions it may miss in 252 |
| --- | --- | --- |
| `b5_12_3` | — (control) | any |
| `b5_12_3_p100` | 1.00 | 0 |
| `b5_12_3_p99` | 0.99 | 2 |
| `b5_12_3_p98` | 0.98 | 5 |
| `b5_12_3_p95` | 0.95 | 12 |
| `b5_12_3_p90` | 0.90 | 25 |

Anything from 0.99 down to 0.97 separates the two populations cleanly. The rungs exist because
1.00 also ejects a real name for a single trading halt, and that cost is exactly what needs pricing
before a threshold becomes law.

### 5.1 Results — runs 485–490

| cell | floor | CAGR | max DD | end NAV | trades | foreign trades | `BMNR.US` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `b5_12_3` | — | 15.4948% | −80.59% | $1,683,440 | 974 | 21 | 14 |
| `b5_12_3_p90` | 0.90 | 16.1828% | −80.98% | $1,891,281 | 1,004 | **23** | 12 |
| `b5_12_3_p95` | 0.95 | 16.6215% | −79.21% | $2,036,308 | 995 | **12** | 0 |
| `b5_12_3_p98` | 0.98 | 16.7206% | −78.30% | $2,070,515 | 986 | **0** | 0 |
| `b5_12_3_p99` | 0.99 | 17.6285% | −77.64% | $2,410,154 | 977 | **0** | 0 |
| `b5_12_3_p100` | 1.00 | 18.8985% | −77.35% | $2,974,836 | 961 | **0** | 0 |

The control reproduced run 484 exactly — 15.4948%, −80.5949%, $1,683,440, 974 trades — on a third
dispatch with the new code in the file. The gate is inert when unset on the real tape, not merely
on a fixture.

**Only p98 and above do the job.** p95 still trades foreign lines twelve times, and p90 trades them
**twenty-three** times, three more than the ungated book: a partial gate reroutes the book into them
rather than out of them. A threshold that half-separates the populations is not a half-fix.

### 5.2 The performance gain is two episodes, and must not be quoted as the benefit

CAGR rises monotonically as the gate tightens, and drawdown falls. That surface is clean enough to
distrust on sight, and this repository's own rule is that **a backtest improving sharply after a
change to data handling is a look-ahead bug until proven otherwise.**

It is not look-ahead — the gate reads `dv` over the window ending at the observation bar, the same
window the existing `bars` count uses, and nothing after it. But the gain is not general either.
Splitting the twenty years at the two points where the curves separate, ungated against p100:

| period | years | ungated | p100 | delta |
| --- | ---: | ---: | ---: | ---: |
| 2007-01-05 → 2008-12-31 | 1.99 | −47.0% | −35.7% | **+11.32** |
| 2008-12-31 → 2024-12-31 | **16.00** | 20.6% | 20.8% | **+0.27** |
| 2024-12-31 → 2026-08-13 | 1.62 | 96.7% | 115.7% | **+18.92** |
| full record | 19.60 | 15.5% | 18.9% | +3.40 |

**Over the sixteen-year middle of the record the gate is worth a quarter of a CAGR point.** The
entire +3.40 comes from the crash at one end and the last eighteen months at the other.

The recent episode is one stock. `BMNR.US` — BitMine Immersion, an OTC shell that uplisted in 2025
— was bought fourteen times between 2025-10 and 2026-02 for **−$139,850**, momentum repeatedly
buying a falling knife. Those trades are genuine: real prices, real volume, a real collapse. The
gate excludes the name because it had not traded on most of the sessions in its formation window,
which is a defensible statement about tradeability and an accidental one about that P&L.

Direct removal accounts for about $120k. The run ends $1.29m higher, so most of the difference is
capital freed early and compounded — which is exactly why a two-episode edge can look like a
twenty-year one in a single CAGR number.

## 6. Recommendation

**Adopt the gate for correctness. Do not adopt it for performance, and do not quote the +3.40.**

The reason to exclude `PLZL.US` is that it is a rouble-denominated MOEX line that cannot be bought
in a US brokerage account in dollars — the strategy could never have made these trades. That
argument stands whether the gate helps or hurts the backtest. The performance number is two
episodes and will not repeat on demand.

**Recommended threshold: 0.98.** It is the *loosest* rung that removes every foreign trade, which
means it does the correctness job while tolerating five halted sessions in a formation year. p100
scores best and is the wrong choice for that reason: it is the extreme end of a monotone surface,
it ejects a real name for a single halt, and picking the maximum of a noisy grid is the error this
programme has already made three times.

What adopting it changes, honestly stated: the headline for V1 moves from **15.49% to 16.72%**, the
drawdown from −80.59% to −78.30%, and every number in `wo-a15-v1-synthesis.md` becomes stale.

## 6a. What the ladder looks like once the tape is screened

The numbers in §5.1 were measured on an unscreened tape. Re-run on a screened one (runs 491–496):

| cell | floor | CAGR before | CAGR after | max DD after |
| --- | ---: | ---: | ---: | ---: |
| `b5_12_3` | — | 15.4948% | **16.3169%** | −80.47% |
| `b5_12_3_p90` | 0.90 | 16.1828% | 18.0753% | −79.82% |
| `b5_12_3_p95` | 0.95 | 16.6215% | 16.1408% | −81.27% |
| `b5_12_3_p98` | 0.98 | 16.7206% | 17.4021% | −82.48% |
| `b5_12_3_p99` | 0.99 | 17.6285% | 16.8342% | −82.72% |
| `b5_12_3_p100` | 1.00 | 18.8985% | 17.7838% | −77.35% |

**The monotone ladder is gone.** Before, the rungs ordered perfectly from 15.49 to 18.90; after,
they scatter between 16.14 and 18.08 with no relationship to the threshold at all. The clean
surface was the gate accidentally removing names whose price series were corrupt — not a
selection effect, and not something that would have repeated.

Two things follow. **§6's recommendation stands but its justification narrows**: adopt the gate
because a rouble-denominated MOEX line cannot be bought, not because of any measured lift. And the
1.9-point spread across rungs is a better estimate of this cell's sensitivity to small changes in
the eligible universe than anything measured so far — **larger than most of the differences the
band grid was read for.**

## 6b. Every defect found, and where each one stands

| # | defect | measured | status |
| --- | --- | --- | --- |
| 1 | Foreign securities on `.US` tickers | 7 names, 21 trades, −$3,075 | gate built, threshold unruled |
| 2 | `concentrated.py` had **no tape screen** | 18 names, 55 trades, −$166,343 | fixed — screen imported |
| 3 | Guard blind under $1, where reverse splits happen | 136 names, 1,865 bars | fixed — quantization bound |
| 4 | Guard blind **across trading gaps** | `CLSK.US` at 9,372× | fixed — last printed bar |
| 5 | Duplicate listings held concurrently | `BBBY_old`/`BBBY`, Feb 2018 | scan now dispatchable |
| 6 | Bar geometry violations | 1,432 bars | **detected, none reached a fill** |
| 7 | Runs were never audited | every run to WO-A15 | fixed — audit gates the build |

Two classes were checked and found clean: **duplicate `(ticker, date)` rows: zero**, and the park
and calendar series themselves — SPY, VOO and SPMO carry no discontinuity, their worst sessions
being −10.9% and +14.5%, both real market days.

## 6c. The §2.5 verdict on the chosen cell is *unproven*

Run 491 scored itself against §2.5 and the machinery reports:

```
deflated Sharpe 0.113, below the 0.95 bar        n_trials_used: 347
observed Sharpe 0.0355/session (0.563 annualized)
verdict: unproven
```

**This is the single most important number in the programme and it is not the CAGR.** After
discounting for 347 distinct trials of search, the observed Sharpe is not distinguishable from
what searching that many configurations would produce by itself.

The supporting figures are better than that sounds — full-window CAGR 16.35% against the
benchmark's 11.15%, bootstrap median 16.37% with a 5th percentile of −2.0%, and the jackknife
holds (ex-top-3 still beats the benchmark). But the deflation is the test that prices the search,
and this programme has run a great deal of search.

It does not say the strategy is bad. It says **the evidence does not yet clear the bar the plan
sets**, and that a forward record is what would change it — not another grid.

## 6d. The duplicate listings cannot be closed by a threshold, and that is the finding

The scan was made dispatchable, given a second pass on the vendor's own `_old` reuse marker, had
its threshold metric corrected, and had the coverage test moved off the scored population. After
all four it proposes **nothing**, from either pass:

```
reused symbols (`_old`): widest gap 0.2714 -> 0.6552 (0.3838 wide, 2.4x)  — not separated by 3.0x
the whole census:        widest gap 0.2134 -> 0.3316 (0.1182 wide, 1.6x)  — not separated by 3.0x
```

That is the correct answer, not a failure to fix. The `_old` population contains a genuine
continuum — `GCI` at 0.27, `CBIO` at 0.54, `WFRD` at 0.67 are a corporate split and two
reorganisations, sitting squarely between "one company" and "two companies." A cut placed in that
region would be fitted, which is precisely what the scan exists to refuse.

**So the duplicate defect stays open, and its size is known rather than guessed:** `BBBY_old.US`
and `BBBY.US` held together for nine sessions in February 2018, one episode across a twenty-year
run. `verify_run.py`'s B7 check now fails any run that repeats it.

The two honest ways forward are a ruling on specific named pairs, or leaving it at that measured
size. What must not happen is a threshold adjusted until it emits exclusions — the near-miss in
§6b's register began exactly that way, and it nearly deleted Randgold.

## 6e. The grid on a clean tape, and the thing it exposes

Fifty cells on the two windows WO-A14 used, plus twenty-five on a window **disjoint** from both.

**Entry-band column means (the exit band matters far less):**

| entry band | 2007-2017 | 2017-2026 | 2007-2026 |
| ---: | ---: | ---: | ---: |
| 1 | −3.80% | +51.31% | 17.38% |
| 2 | **−2.61%** | +50.99% | **18.27%** |
| **3** | **−6.55%** | **+46.59%** | **14.93%** |
| 4 | −5.15% | +48.03% | 16.07% |
| 5 | −4.35% | +50.79% | 17.92% |

**Entry band 3 is the worst column on all three windows**, including the disjoint one. Zak's chosen
`b5_12_3` ranks 14th, 15th and 17th of 25. The band finding is real — Spearman between the two
*disjoint* windows is **+0.592** (the overlapping comparison flattered it at +0.872) — and it says
the entry band should be tighter than 3. **3/12 was chosen from a contaminated grid and does not
survive a clean one.**

### But that is the second-order finding. This is the first-order one:

> **Zero of twenty-five configurations made money between 2007 and 2017.**
> The range is −0.96% to −7.49% a year, every cell, with drawdowns of −80% to −84%.

The twenty-year headline is not a twenty-year record. It is:

    2007-01-05 .. 2017-08-14   (2,671 sessions)   −5.22%/yr   →  about −43% cumulative
    2017-08-15 .. 2026-08-13   (2,261 sessions)   +48.03%/yr  →  about 33x
    ------------------------------------------------------------------------------
    2007-01-05 .. 2026-08-13   (4,932 sessions)   +16.51%/yr

**Every dollar of the edge comes from the last nine years, and the first ten lost money in every
configuration tested.** No band setting, no participation floor and no tape fix changes that; the
whole 5x5 surface is under water for the first decade.

This is what the §2.5 verdict was already saying in a single number. A deflated Sharpe of 0.113
over 347 trials is what it looks like when a result rests on one regime, and the regime here is
identifiable: post-2016, the era of persistent mega-cap momentum. **The honest description of this
strategy is not "16.5% a year for twenty years." It is "a bet that the 2017-2026 regime
continues," and it should be written down that way or not at all.**

Three things follow, and none of them is another grid.

1. **A plan amendment that quotes the twenty-year CAGR would be misleading**, even though the
   number is now arithmetically correct on a clean tape and reproduces to the digit.
2. **The regime question is the whole question.** WO-A10's regime work was ruled advisory on the
   grounds that the filter's edge was concentrated in 2008-09. That reasoning now cuts the other
   way: if the strategy only works in one regime, knowing which regime you are in stops being
   advisory.
3. **A forward record is the only evidence that would move this**, and it is worth starting for
   exactly that reason.

## 7. What is still open

- **The universe-wide count is unknown.** 372 names sit at a no-trade rate of 3%+ among those
  liquid enough to matter, but that set mixes foreign lines with thin ones and has not been
  resolved name by name. The gate does not require resolving it; an accurate census would.
- **The gate has been priced on one cell only.** `b5_12_3` at 0.98 is what §6 recommends; whether
  the band grid's chosen region survives the gate is not known, and the fifty-cell grid would have
  to be re-run under it to say. A gate that changes the eligible universe can move which bands win.
- **`BMNR.US` deserves its own look.** 2,662 bars back to 2005 with 1,049 at zero volume, a low
  close of $0.0001 against a high of $135, under a company that uplisted in 2025. That is the
  signature of a recycled ticker, and if the series splices two securities then its formation-window
  momentum is wrong on both sides of this gate.
- **`CNGL.US` is a separate defect.** It trades with real volume on US holidays, and its price
  jumps from 20.5 to 204.6 across the 2018 new year — a series with more than one security in it.
  Ticker recycling is not what this gate is for.
- **Nothing here has been ruled into the plan.** §3.0's L0 gate is unchanged. Adding a
  participation floor is a plan amendment, and the ladder is the evidence for it, not the decision.
