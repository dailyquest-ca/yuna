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

*Results appended when the run lands.*

## 6. What is still open

- **The universe-wide count is unknown.** 372 names sit at a no-trade rate of 3%+ among those
  liquid enough to matter, but that set mixes foreign lines with thin ones and has not been
  resolved name by name. The gate does not require resolving it; an accurate census would.
- **`CNGL.US` is a separate defect.** It trades with real volume on US holidays, and its price
  jumps from 20.5 to 204.6 across the 2018 new year — a series with more than one security in it.
  Ticker recycling is not what this gate is for.
- **Nothing here has been ruled into the plan.** §3.0's L0 gate is unchanged. Adding a
  participation floor is a plan amendment, and the ladder is the evidence for it, not the decision.
