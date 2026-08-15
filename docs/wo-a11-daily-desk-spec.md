# WO-A11 · The momentum desk — daily proposal spec

**Status:** specification only. No code exists. Nothing here has been implemented.
**Purpose:** turn the `w5_notrail` backtest into a daily instruction Zak can execute.
**Written:** 2026-08-14, against `src/concentrated.py` at commit `d3c4e6e`.

This document is written to be read outside the repo, so it restates what it depends on rather
than pointing at it. §9 is the part that needs Zak's rulings before code exists.

---

## 1. Authority

- The job **proposes**. Zak executes. Nothing in it places, modifies or cancels an order.
- Output is rows in `tickets` with `state='proposed'`, plus a section in the existing `preopen`
  brief. Approval is Zak's, out of band.
- The regime flag is **advisory** (Zak's ruling, 2026-08-14). It is reported; it does not change
  what the job proposes. See §4.
- Sleeve: `momentum`. Account: **TFSA only**, per plan §2.6 — momentum's turnover belongs in the
  tax-free account, and the accepted cost is that losses burn contribution room permanently.

---

## 2. Where it runs — this adds no new schedule

`ingest-daily` already fires at 02:00 and 03:00 UTC, Tue–Sat — Monday to Friday evenings Pacific.
`pipeline.yml` chains `score → check → compose → notify` off every ingest by `needs:`.

**The momentum desk is a new sleeve inside `score` and a new section in `compose`'s existing
`preopen` brief.** It is not a new cron and does not change the shape of §4.2's chain. That should
make the plan edit smaller than it first appears.

The timing is correct by construction rather than by luck: the strategy ranks on session *i*'s
close and fills at session *i+1*'s open. The chain runs between them.

---

## 3. The strategy as live rules

Every constant below was used unchanged in every A-series run. All of them are currently in
`src/concentrated.py` and **none has a home in the plan** — see gap 8.

### 3.1 The eligible universe

On the most recent complete session *i*:

| filter | value | constant |
| --- | --- | --- |
| kind | `stock`, ticker matching `%.US` | — |
| exclusions | not in `universe_excluded` | — |
| history | ≥ **210** finite closes within the last 252 sessions | `L0_MIN_BARS` |
| price | **unadjusted** close ≥ **$5.00** | `L0_MIN_RAW` |
| liquidity | **median** dollar volume over the last **50** sessions ≥ **$10,000,000** | `L0_MIN_ADDV`, `ADDV_WINDOW` |
| pool cap | of the survivors, the **500** highest by that same median | `top_by_addv` |

The pool cap is applied **after** the other filters, not before. Dollar volume is the
point-in-time proxy for index membership; a real S&P membership series is not in the store and
reconstructing one from today's index would be look-ahead.

### 3.2 The score

Two windows, and they deliberately end at different places.

```
past    = adj_close[i - 252]
recent  = adj_close[i - 21]
momentum = recent / past - 1.0

window  = adj_close[i - 252 .. i]          # 253 closes
rets    = diff(window) / window[:-1]       # 252 simple returns, NOT log
vol     = stdev(rets)                      # population sd, ddof = 0, NOT annualised

score   = momentum / vol      (where vol > 0; otherwise the name is dropped)
```

Rank descending by `score`.

Three details that are load-bearing and easy to get wrong:

1. **The momentum window ends 21 sessions ago, not today.** It measures 252-sessions-ago to
   21-sessions-ago — roughly eleven months, ending a month back. That skip is the whole point of
   "12-1": the most recent month reverses.
2. **The volatility window ends today.** Momentum is a lagged signal; volatility is current risk.
   This asymmetry is intentional and is SPMO's own construction.
3. **`vol` is not annualised and the returns are simple, not log.** The score is a ratio so the
   annualisation factor would cancel — but only if applied consistently. Do not "fix" it.
   `numpy.nanstd` defaults to `ddof=0`; the pinned-version doctrine applies here.

### 3.3 The book

- **5 slots**, each targeting **20%** of sleeve NAV.
- Sleeve fraction **1.00** — fully invested, no cash buffer (Zak's ruling, 2026-08-14).
- **No stop-loss of any kind.** Positions leave only at their own slot's review. This is the
  defining property of the strategy and the thing being adopted.

### 3.4 The clock — implement this differently from the backtest

In the backtest the slot on duty is `session_ordinal % 5`. **Do not do that live.** A missed run,
a holiday miscount or an outage shifts the phase permanently and there is no way to detect it
afterwards.

Instead, **the slot is a property of the position**. Add to `book`:

```sql
alter table book add column slot smallint;              -- 0..4, momentum sleeve only
alter table book add column last_reviewed date;
```

Each run: the eligible slot is the one whose `last_reviewed` is oldest **and** at least **5
sessions** old. If several qualify — after an outage — review **only the oldest**. Never catch up
in a burst.

**This is a stated deviation from what was tested.** Under normal operation the two are identical;
after a gap they differ. It is self-healing and observable, which the ordinal is not. It belongs in
the plan as the live rule, not buried in code.

### 3.5 The proposal

On the eligible slot, using the ranked pool from session *i*:

1. `carried` — the names held in the **other four** slots. They are neither sold nor re-bought
   today; they belong to books that are not being reviewed.
2. `pool` — the ranked list minus `carried`.
3. `want` — the single highest-ranked name in `pool`.
4. If `want` is the name this slot already holds → propose a **top-up** only (§3.6).
5. Otherwise → propose **sell** the held name and **buy** `want`.

At most one swap per session. Never two.

### 3.6 Sizing

```
per_slot = sleeve_nav * 1.00 / 5
have     = qty * last_close        (0 if the slot is empty)
spend    = max(per_slot - have, 0)
```

Order quantity is `spend / expected_fill`, rounded down to whole shares.

The backtest tops up with **no minimum**, which live means roughly **106 orders a year averaging
3.2% of NAV**. A threshold is needed and it must be measured, not chosen — gap 2.

### 3.7 Fill convention

Every proposal is a **market order at the next open**. That is where the backtest prices it. A
limit order is a different rule and would need its own measurement before it could be claimed to
produce these numbers.

### 3.8 Measured trading load

Over the nine-year window, per year:

| | count | ≈ per week | average size |
| --- | ---: | ---: | ---: |
| new positions (a name enters) | 58 | 1.1 | 17.1% of NAV |
| top-ups of a held name | 106 | 2.0 | 3.2% of NAV |
| sells | 58 | 1.1 | — |

So the real decision load is about **one swap a week**, plus maintenance orders whose necessity is
gap 2.

---

## 4. The regime flag — advisory only

- **Signal:** SPY adjusted close versus its own **200-session simple moving average**.
- **States:** `GREEN` (close > SMA), `RED` (close ≤ SMA), `UNKNOWN` (fewer than 200 bars).
  `UNKNOWN` is treated as `RED` — a gate that cannot be evaluated must not wave the book through.
- **Confirmation:** gap 3. Raw, the signal flips 52 times in 19 years; only 13 of those became
  sustained defensive stretches. A confirmation length is needed and has not been measured.
- **Storage:** the existing `gate_state` table is weekly (`week_end`, `sma30`, `sma30_4w_ago`) and
  serves §3.3's compounder gate. **Do not overload those rows.** Either a `kind` column with a
  daily variant, or a separate table.
- **Effect on the proposal: none.** The flag appears in the brief. Zak decides.

Current state as of the 2026-08-13 close: SPY 777.88, 200-day 705.00, **10.3% above — GREEN.**

---

## 5. Output

### 5.1 Tickets

One row per proposed action in the existing `tickets` table:

| column | value |
| --- | --- |
| `sleeve` | `momentum` |
| `account` | `TFSA` |
| `action` | `sell` / `buy` |
| `reason` | `swap` (exists in the enum) — top-ups need a new value, e.g. `topup` |
| `order_type` | `market` |
| `qty` | whole shares |
| `state` | `proposed` |
| `brief_id` | the brief this came from |

### 5.2 Brief section

Added to `compose`'s existing `preopen` brief:

- **Slot on duty** and the name it holds
- **The action** — hold / swap / top-up, with names, target dollars, target shares
- **The book** — five names, weight each, days held, rank now
- **Concentration** — §6, mandatory
- **Regime flag** — state, SPY vs its 200-day, sessions in the current state
- **Freshness banner** — the existing mechanism

---

## 6. Concentration reporting — mandatory, non-blocking

The book as of 2026-08-13:

| name | ticker | weight |
| --- | --- | ---: |
| SanDisk | SNDK | 30.4% |
| Revolution Medicines | RVMD | 19.2% |
| Micron | MU | 17.8% |
| Western Digital | WDC | 16.6% |
| AXT Inc | AXTI | 16.0% |

SNDK + MU + WDC is **64.8% in one memory cycle**. Adding AXTI it is **80.8% in semiconductors**.
Measured effective bets across the twenty-year run: **2.54** against a nominal 5, with a structural
ceiling near 3.7 at any book size.

The brief must report, every session:

- weight by vendor sector / industry
- the single largest issuer weight
- effective bets, `1 / Σᵢⱼ wᵢwⱼρᵢⱼ`

**Whether a cap constrains the proposal is gap 4. Reporting it is not optional.** A five-name table
that looks diversified and is not is precisely the failure this system exists to avoid.

---

## 7. Reconciliation — the model book against the real one

Zak will not always execute, and fills differ from the modelled open. Two books therefore exist and
must not be conflated.

- **The proposal is always computed from `book`** — what is actually held — never from a modelled
  position set. A desk that proposes against a fiction diverges silently and forever.
- A held name the strategy would not have bought is still a held name. Its slot reviews it on
  schedule and the rank decides whether it stays.
- If a slot is **empty** — a sell executed, a buy did not — the next run re-proposes the buy for
  that slot against a **fresh** rank, not the stale one.
- **Drift report**, in the Saturday letter: the model book against the actual book, and the
  cumulative return difference since inception.

That last item is what makes Zak's advisory-flag decision measurable. Without it, discretion is
invisible and the question of whether it helped can never be settled.

---

## 8. Failure modes — halt, never guess

`.claude/rules/trading-code.md`: *a guard that detects a bad state must halt, not warn and
continue.* The job must refuse to emit a proposal, and say why, when:

1. SPY has no bar for the session being scored — no flag and no proposal
2. Any name in the **top 20** of the ranked pool carries a stale mark
3. `universe` was last refreshed more than *N* sessions ago (gap 5)
4. Sleeve NAV is unavailable, or older than the session being scored
5. Fewer than 5 names survive §3.1
6. The eligible slot cannot be determined — no `slot` values, or duplicates
7. A name in `book` is absent from `universe`, or present in `universe_excluded`

**Stale marks specifically.** The backtest's rule is *never buy on a stale mark; hold and sell on
one*. Live, selling on a stale mark risks dumping into a bad print. Recommendation: **flag rather
than instruct**, and let Zak look. This is a deviation and needs a ruling (gap 6).

---

## 9. Plan gaps — what this spec cannot decide

Per the no-assumed-values doctrine, none of these may be filled with a plausible default. An
invented constant here does not throw; it produces a plausible number and places a real order.

| # | gap | why it cannot be defaulted | how to settle it |
| --- | --- | --- | --- |
| 1 | **Rank tie-break** | Two identical scores must resolve deterministically or the book is irreproducible and no parity vector can be written | Ruling. Recommend `universe.kind='stable'` first, then ticker ascending |
| 2 | **Top-up threshold** | Zero gives ~106 small orders a year; too high and the book drifts off equal weight | **Measure.** Re-run `w5_notrail` at thresholds 0 / 1% / 2% / 5% of NAV and read the cost |
| 3 | **Regime confirmation length** | 52 raw flips against 13 sustained regimes. I never measured which confirmation separates them | **Measure.** Sweep 1–10 sessions against the episode list |
| 4 | **Concentration cap** | The book is 80.8% one sector today. A cap changes the tested strategy and must be priced | Ruling **and** measurement. WO-A6 measured a theme cap; re-read that number first |
| 5 | **Universe staleness bound** | How old may the universe be before the rank is untrustworthy | Ruling |
| 6 | **Stale-mark behaviour** | Backtest sells; live selling on a stale mark could dump at a bad print | Ruling |
| 7 | **Sleeve NAV definition** | Is momentum's NAV its own positions plus a share of cash, or a fixed allocation of total NAV? **This determines every position size** | Ruling |
| 8 | **The nine constants** | 210 bars · $5 · $10m · 50-day median · 500 names · FORMATION 252 · SKIP 21 · VOL_WINDOW 252 · n=5. They have a source — every A-series run — but **no plan home** | §3.2 of the plan must carry them explicitly |
| 9 | **What a RED flag does** | Advisory means Zak decides — but does the job propose anything different? Recommend: no, identical proposal, flag shown | Ruling |
| 10 | **Account and funding** | TFSA per §2.6, but starting capital, and whether the sleeve is topped up from elsewhere | Ruling |
| 11 | **Duplicate listings** | `src/dedupe_scan.py` exists and is report-only. Until it is applied the book can hold one company twice | Run the scan, read the distribution, then rule on applying it |

---

## 10. Out of scope

- Order placement, modification or cancellation — in any form
- Stop-losses — the strategy has none by design
- Leverage
- Anything intraday. One decision per session, computed overnight
- Any automatic response to the regime flag

---

## 11. Honest status of the evidence

The spec implements `w5_notrail`. Its numbers, both from the survivorship-corrected universe:

| window | park | CAGR | max drawdown | Sharpe | bootstrap 5th %ile |
| --- | --- | ---: | ---: | ---: | ---: |
| 2017-08 → 2026-08 (9 yr) | SPMO | **44.79%** | −48.7% | 0.965 | +11.5% |
| 2007-01 → 2026-08 (20 yr) | SPY | 15.02% | **−82.5%** | 0.535 | **−3.4%** |

Identical rules; different measurement periods. Carried into live use:

- **Plan capital around −82.5%, not −48.7%.** The shallower figure is the recent decade only.
- **The bootstrap floor is negative over twenty years.** In the worst 5% of resampled orderings the
  strategy ends below where it started. The regime filter closes that (to +5.6%) and Zak has ruled
  it advisory rather than automatic — that ruling is what §7's drift report exists to evaluate.
- **Execution asymmetry is unresolved** (WO-A8 §4). Removing the stop removed the only
  conservatively-filled exits in the model: 100% of this arm's exits are rebalances at the deciding
  close, where the trailed variant filled 47% of its exits at the next open. Part of the margin may
  be execution rather than strategy. This was never settled and should not be forgotten.
- **Effective bets 2.54.** The five-name book is roughly a two-and-a-half-name book.
