# Backtest work-order review — WO-11–14, 2026-08-10

*Read of the 2026-08-09 batch against the repo and the live database. Not law, not a proposal —
what I would change before a line of it is built, and why. Every number below was queried, not
recalled; the queries are inline so they can be re-run.*

**Verdict.** The premise is right and the evidence for it is stronger than the batch states. The
batch is worth doing. But as written it (1) builds a *second* implementation of the law instead of
retiring the one that already drifted, (2) sets an acceptance test that cannot pass or fail for the
reason it claims to, (3) tests two bull-market years when ten years of bars are sitting in the
database, (4) leaves the largest bias — survivorship — off a conformance list of thirteen items,
and (5) does not contain the thing Zak actually asked for: the side-by-side against the investors
we'd otherwise pay to do this. Six changes fix it. None of them is large; one of them deletes more
code than it writes.

---

## 1. What I verified

| Claim in the batch | Verdict | Evidence |
|---|---|---|
| `backtest_runs` max id 12, all ran 2026-07-31 | **True** | 12 rows, every `ran_at::date` = 2026-07-31 |
| Run 5's largest loss bucket is `volume unconfirmed` | **True** | 171 trades, −$9,486, 1.1 bars avg |
| Runs 6/10 gate entry on volume | **True** | `VOL_MODE=confirm_first`, `backtest.py:311` |
| No run models costs or FX | **True** | no cost layer exists in either backtest |
| Average deployed exposure ~9–17% | **Overstated** | `backtest_runs.avg_exposure` is 0.3%–12.7% across the ten momentum runs; 12.66% on run 5. Two definitions of "exposure" are in circulation — fix one in `stats` and cite it everywhere |
| The ratified mechanic has never been backtested | **True, and understated** | see §2 |

---

## 2. The premise is stronger than the batch claims

The batch argues the runs don't match the law because of the volume mechanic. That's the small
half. The bigger half:

```sql
select run_id, count(*) trades, count(*) filter (where mcn < 70) below_70, min(mcn)
  from backtest_trades group by run_id;
```

| Run | Trades | Entered at MCN < 70 | Lowest MCN entered |
|---|---|---|---|
| 5 (baseline) | 296 | **211 — 71.3%** | **15.1** |
| 6 (variant B, "the winner") | 84 | 59 — 70.2% | 9.1 |
| 7–10 | 81–328 | 69–71% each | 9.1–15.1 |

§3.2 is unambiguous: **"MCN < 70 never tickets — BUY-state names below 70 stay queued."**
`src/backtest.py` has no MCN floor anywhere — not in `rank_week`, not in the entry loop, which
reads `budgets[85] if r.mcn >= 85 else budgets[70]` and quietly hands the 70–84 risk budget to a
name scoring 15. Seven in ten trades in every headline run are entries the law forbids.

This matters beyond conformance. `backtest-findings-2026-07-31.md` builds its central conclusion —
*"strip the volume churn and the remaining 125 trades look like a working momentum system … the
selection is not the problem"* — on a trade population that is ~70% names the selection rule would
have refused. That sentence should be retracted when law-v0 lands, whichever way the new number
goes. It is currently the most load-bearing claim in the evidence base and it rests on trades that
never should have existed.

Add it to the conformance checklist explicitly as an acceptance query, not a unit test:
`select count(*) from backtest_trades where run_id=<law-v0> and mcn < 70` must be **0**.

---

## 3. The one structural change: stop writing the law twice

This is the most important paragraph in this review.

`src/signals.py` already holds the canonical, pure, unit-tested implementation of nearly every
clause WO-11 lists: `market_gate` (M1), `trend_template` (M2), `base_scan` (M3), `momentum_quality`
/ `setup_proximity` / `mcn`, `breakout_confirmed`, `pyramid_orders`, `entry_order`, `initial_stop`,
`ratchet_stop`, `momentum_size`, `in_blackout`, `holds_through_earnings`, `trading_days_between`.
`tests/test_signals.py` has **107 tests** over them, including `test_setup_proximity_has_exactly_
three_sub_scores` and `test_confirmation_takes_any_of_the_first_three_sessions`.

Production (`arming.py`) calls those functions. The compounder backtest calls those functions —
after being burned, and it says so in its own source:

> *"The previous body was a private copy with its own constants, which meant the backtest silently
> measured a different formula than production priced — the exact failure mode a backtest exists to
> rule out."* — `backtest_compounders.py:47`

**`src/backtest.py` imports none of them.** It imports `db` and re-derives M1, M2, the base scan,
MCN, the stops, the pyramid and the sizing by hand. That copy is now provably stale in at least
nine places:

| § | The law | `backtest.py` |
|---|---|---|
| MCN setup | three sub-scores | **four** — the deleted pullback score is still there (`:148`) |
| Sizing | MCN < 70 never enters | no floor at all |
| Pyramid | adds at +2% / +4% | **+2.5% / +4.5%** (`:274`) |
| Pyramid | both limits pivot × 1.05 | no ceiling — fills at `max(trigger, open)` |
| Confirmation | freeze at 50%, three sessions to confirm late | no freeze, no late window — `vol_ok` is fixed at entry |
| Confirmation | exit only on a close back below pivot | exits next open on volume alone (`:256`) |
| Pyramid | stalled 4 weeks → completes or exits | absent |
| M3 | daily trigger check, re-scanned nightly | **weekly** — the Friday queue's pivot is used all week |
| §3.3 | earnings blackout, both sleeves | absent |

WO-11 as written adds a fourteenth variant to this file and thirteen new unit tests. Those tests
would test the copy. Every future plan amendment would then have to be made twice, and the drift
that produced eight non-conforming variants recurs by construction — this is `learnings.md` #22
(*implement the mechanism, not the intent*) with a second codebase attached.

**Do instead:** rewrite `backtest.py` as a *driver* — data loading, the day loop, portfolio
accounting, persistence — that calls `signals.py` for every rule evaluation, exactly as
`backtest_compounders.py` does. Where a clause has no `signals.py` home yet (the late-confirm
window state machine, the stalled-pyramid rule, the freeze), add it *there* and let `arming.py` use
it too. Net effect: WO-11's conformance checklist becomes mostly a citation of existing tests, the
diff is smaller than the one proposed, and the law has one implementation for the first time.

That is the difference between a backtest that tests our rules and a backtest that tests a
sincere restatement of our rules.

---

## 4. The acceptance test can't do the job asked of it

WO-11's acceptance is: run law-v0 to 2026-08-07 and reproduce NUE/RS entering 8/4 off pivots
270.90 / 419.83, both unconfirmed, both frozen, RS flagged 8/7, NUE not.

The book confirms the live facts (`book`: RS.US and NUE.US, both `opened_at` 2026-08-04, both
`confirmed=false`, both `pyramid_step=1`, `confirm_deadline` 2026-08-06). The problem is the test
design. A full-history simulation arrives at 2026-08-04 carrying **its own** book, its own NAV, its
own `fired` ledger and its own four-name cap, none of which match production's. If the sim happens
to hold four names that Tuesday, NUE and RS are never even considered, and the acceptance fails for
a reason that says nothing about rule fidelity. Worse is the near-miss: someone makes it pass by
adjusting the portfolio layer, and a conformance test becomes a curve-fit.

**Split it in two:**

1. **Signal-level conformance (the real test).** For a given (ticker, date), the engine's rule
   evaluation — state, pivot, confirmation verdict, freeze, flags, stop — must equal what
   production wrote, with portfolio state excluded from the comparison. Then run it not on two
   names but on every name the pipeline has armed since the ledger started: `armed` and the 47
   `pass` observations from 2026-08-01 onward give ~100+ name-days already, growing nightly. Wire
   it into the Saturday chain as a differential test between `arming.py` and the backtest engine —
   which, after §3, is a test that they still call the same functions. **This is the WO-14 "make it
   standing" item that's actually worth standing up.**
2. **State-seeded replay (the portfolio test).** Seed the sim from production's real book on a
   date and step forward. Useful, but it tests accounting, not law. Keep it, name it separately.

The week of 8/4 is then one case in a growing corpus, not the whole exam.

---

## 5. Two years is a choice, not a constraint

The batch inherits the 2024-08 → 2026-07 window without questioning it. The database has moved:

| | |
|---|---|
| `prices` | 6,410,951 rows, 3,268 tickers, **2016-08-05 → 2026-08-07** |
| tickers with bars back to 2016 | **2,050** (2,291 to 2019; 2,590 to 2021) |
| `GSPC.INDX` | 758 bars, **only 2023-08-01 →** ← the actual binding constraint |
| `USDCAD.FOREX` | 854 bars, **only 2023-08-01 →** (every other pair goes to 2016) |
| `Earnings.History` in `raw_doc` | 2,949 tickers, **avg 98.8 quarters**, each with `reportDate` + `epsActual` |

Three consequences:

- **The window is limited by two backfills, not by data we don't own.** Backfilling `GSPC.INDX` and
  `USDCAD.FOREX` to 2016 is one vendor call each and unlocks a ten-year test spanning Q4-2018, the
  2020 crash and the 2022 bear. A momentum sleeve whose entire evidence base is a 16%/yr bull tape
  is barely evidence; M1's whole purpose is regimes this window doesn't contain.
- **M4 is feasible now, point-in-time, with no new vendor call.** `raw_doc->'Earnings'->'History'`
  carries `reportDate` per quarter (verified on NUE: 2026-07-27, 2026-04-27, 2026-01-26 …). The
  batch's item 4 can be honest rather than skipped. The restatement caveat from §4.8 still applies
  and should be stated on the run.
- **The blackout is feasible too — and only from that source.** The `earnings` table starts at
  **2025-06-27** (`CAL_BACK = 400` days), so item 11 would be silently unenforceable across most of
  any longer window. The same `Earnings.History` `reportDate` field backfills it to 2016.

**Therefore:** the conformance table shipped in `stats.conformance` must carry, per clause, not just
`implemented: true` but **coverage** — the fraction of the window over which the data required to
enforce it actually existed. A green checkmark on a clause that had no data for 80% of the run is
the exact failure this batch exists to end (`learnings.md` #19, *green is not a result*).

---

## 6. Survivorship is the missing fourteenth clause

`universe`: **3,244 active, 2 delisted.** §3.3's *"Delisted names retained in the universe"* is not
running, and `backtest.py:49` filters `status='active'` on top of that. Every number in every run
is measured on the tape that survived.

The batch's own framing is "make the verification instrument faithful," and then omits the largest
known infidelity from a thirteen-item list. It cannot be fully fixed cheaply — EODHD exposes
delisted tickers per exchange, but rebuilding a point-in-time L0 census for 2016–2026 and pulling
bars for dead names is real work, plausibly the biggest single item in the whole programme.

Two honest options, either acceptable, silence is not:

- **Scope it in** as WO-11b with its own budget, and treat law-v0's first result as provisional
  until it lands.
- **Scope it out** explicitly, and make the run *quantify* it: count names that left the L0 census
  during the window (the monthly universe rebuild can start recording membership from now), and put
  a stated haircut in `stats.biases` rather than a sentence.

---

## 7. WO-12: FX is two problems, and the ruling shouldn't block the run

**First — the missing piece is translation, not the fee.** The sim prices US stocks in USD and
books `pnl_cad` against a CAD `START_NAV` at an implicit rate of 1.00. There is no FX conversion in
the P&L at all. USDCAD moved materially over the tested window; that is a return component, not a
friction. Fixing it is mandatory and independent of Zak's ruling: price in local currency, translate
at the daily rate, book NAV in CAD (`config.base_currency = 'CAD'` already says so).

**Second — the fee decides whether the momentum sleeve should exist in that account.** The batch
calls this "open input" and defaults `fx_fee_per_side` to 0.015 pending the answer. The default is
the verdict:

| | Momentum (run 6, the best variant) | Compounders (run 12) |
|---|---|---|
| Avg hold | 6.1 days | 290 days |
| Gross expectancy / trade | **+0.44%** | +36.1% |
| Less spread (5bps/side, ≥$50M ADDV) | +0.34% | +36.0% |
| Less FX at 1.5% **per side** | **−2.56%** | +33.1% |

If the TFSA converts per trade, momentum's round-trip FX cost is roughly **seven times its best
observed per-trade edge**, and no exit-rule tuning in phase 2 recovers that. The compounder sleeve
doesn't notice. That is not a footnote pending a ruling — it is close to a strategy-placement
decision, and it belongs in R3 the week it's known.

**So don't let the ruling gate the batch.** Run law-v0 three ways and print all three: zero-cost ·
USD-held (spread only) · CAD-converting (spread + 1.5% × 2). Zak then rules on the FX question with
the number in front of him instead of the number waiting on him. Once ruled, one of the three is
the headline and the others stay as the sensitivity.

---

## 8. The benchmark is broken three ways

Not mentioned anywhere in the batch, and it's the axis Zak actually cares about:

1. **`backtest_equity.benchmark` is NULL in all 5,988 rows across all 12 runs.** `backtest.py:369`
   reads `SPY.US`, which is not in `prices` (only `GSPC.INDX` is), so the guard silently writes
   `None` every day. No stored run can currently draw a side-by-side curve.
2. **`GSPC.INDX` is a price index.** Our NAV is total return; the benchmark it's compared against
   drops dividends — roughly 1.5–2%/yr handed to us for free. Use a total-return series, or SPY
   with dividends, and say which.
3. **Currency mismatch.** SPX in USD against NAV in CAD. Once §7's translation exists, translate the
   benchmark too — the honest comparator for a Canadian is the index *in CAD*.

Acceptance for WO-12 should include: `select count(*) from backtest_equity where run_id=<law-v0>
and benchmark is null` = 0.

---

## 9. WO-13: sound, with one correction to its rationale

The work order is right and cheap — re-run the compounder side mechanically, label it
indicative-only per §4.8, publish it as the floor. No objection.

One correction. Its stated justification is: *"The C2/quarantine layer's value-add is measured
forward by the shadow book."* Read `arming.py:1226` — the shadow book records a name only when it
appears in `armed` as an entry that a rule **blocked**, or as an exit. A name that a C2 FAIL ruling
kept off the bench entirely never reaches `armed`, so the judgment layer's most consequential
decisions — the refusals — are invisible to the instrument that's supposed to measure them. If
WO-13's floor is to mean anything as a comparison, the rulings scorecard needs its own snapshot at
ruling time (§5.5 already asks for one). Worth a work order; it is the other half of the same
question.

Also note the DB says both compounder runs already exist mechanically (ids 11 and 12, the second
with financials excluded per the C1 bug fix). WO-13 is closer to "re-run under the current stamp
and set `params.policy`" than to new construction — cheaper than it reads.

---

## 10. WO-14 item 3: the marking mechanism exists — here is its state

The batch asks for this to be reported immediately if missing. **It is not missing.**
`arming.py:1243` marks `mark_30` / `mark_60` / `mark_90` on `observations`, nightly, inside the
`score` chain. Three findings on it:

- **It has never executed its write path.** 47 `pass` rows and 1 `exit` row exist, earliest
  2026-08-01; nothing is 30 days old yet, so `marked_30 = 0` everywhere and the branch is untested
  in production. The dispatch test WO-14 proposes is exactly right — and **due sooner than the
  batch says**: first marks come due **2026-08-31**, not ~Sep 5.
- **Defect: the mark is an unadjusted close.** `select close from prices …` is compared against a
  decision-time `close`. A split in between corrupts the mark by the split factor. `prices` carries
  `adj_close`; use it at both ends, or store the adjustment factor with the observation.
- **Defect (minor): the lookup is unbounded.** `where d >= <at + horizon> order by d limit 1` takes
  the next available bar however far away it is, so a halted or delisted name gets a mark from an
  arbitrary later date, or retries forever. Bound it to a few sessions and record a miss.

Also worth noting: the code comment says "30, 60 and 90 **sessions** later" while the code uses
calendar days. §3.3 says days, so the code is right and the comment is wrong — fix the comment
before someone fixes the code.

---

## 11. The missing work order — what Zak actually asked for

Zak's framing: *back-test both sleeves and run them side by side against a back-tested version of
the top investor firms — otherwise we might as well let them manage our money.* Nothing in WO-11–14
does this. WO-14 adds one letter line against SPX only. This is the deliverable the batch is for,
and it should be written down as **WO-15** rather than assumed.

What exists to build on: `config.named_investors` — Fundsmith · Akre · Polen · TCI Fund · Pershing ·
WCM Invest · Giverny — set by **Zak on 2026-08-02**, before this question was asked. That date is
the most valuable property of the list: a comparison set chosen after the fact is hindsight, and
this one wasn't. Use it as-is; do not re-pick "top firms" in 2026.

What does **not** exist: any holdings history. The only holder data we hold is
`raw_doc->'Holders'`, a *current* snapshot per stock. A firm's 2019 portfolio is not recoverable
from it, and no 13F history endpoint is available on the EODHD surface we use. A clone therefore
needs a new source — SEC 13F-HR filings are free and quarterly back to 2013, but that is an ingest
job, a parser, and a network-policy question, not a config change.

If it's built, build it honest, and state all of this on the label:

- Form each firm's portfolio **at its filing date, never the quarter end** — the same discipline
  §3.3 already imposes on fundamentals. 13F lands ~45 days late; a clone that trades on quarter-end
  data is the classic look-ahead.
- A 13F clone **is not the fund's return**: US long equity only, no cash, no shorts, no options, no
  non-US book, no intra-quarter trades. For a UK global manager it may cover half the portfolio;
  for a derivatives-heavy activist, less.
- **Deduct their fees.** The question is "should we pay them to do this," so the comparison must be
  net of what we'd pay. A gross 13F clone flatters them.
- Compare on three lines, not one: NAV CAGR (which includes our cash drag) · return on deployed
  capital · max drawdown. Run 5 sat 12.7% invested; a 100%-invested clone will beat it on the first
  line while losing on the second, and only reporting both is honest.

**And say the plain thing in the letter.** The decision Zak faces is not "are we better than
Fundsmith," it is "should this money be in an index fund." He cannot buy most of these firms in a
TFSA. So the benchmark ladder should be, in order: **(0) what he can actually buy** — SPX total
return in CAD, the real alternative · **(1) the mechanical floor** — WO-13 screen-only · **(2) the
opinion benchmark** — the 13F clones, graded indicative-only · **(3) Yuna live**, forward from
cutover, which is the only one of the four that is evidence rather than reconstruction. Tier 0 is
one backfill away and answers the actual question; tiers 2 and 3 answer the interesting one.

---

## 12. Sequencing

The batch's order is WO-11 + WO-12 → WO-14 → WO-13. Adjusted:

1. **Ask Zak the FX question now** (§7) — one sentence, no code, and it changes what the rest of the
   work means. Meanwhile build the three-way cost run so the answer isn't a blocker.
2. **Refactor `backtest.py` onto `signals.py`** (§3), and backfill `GSPC.INDX` + `USDCAD` to 2016
   (§5). Small, and everything downstream gets cheaper and truer.
3. **WO-11 as law-v0**, over ten years, with M4 and the blackout on from `Earnings.History`, MCN ≥ 70
   asserted, per-clause coverage in `stats.conformance`, and survivorship either scoped in or
   quantified (§6).
4. **WO-12** with translation *and* fees, and a non-null benchmark (§8).
5. **WO-14**, but with the differential conformance harness as its standing item (§4), and the
   marking fixes from §10 — that test is due 2026-08-31.
6. **WO-13**, cheap, largely a re-label.
7. **WO-15** — the investor side-by-side (§11), scoped separately, after our own side is faithful.
   A comparison against Fundsmith is worthless while 71% of our trades are ones the law forbids.

Phase 2 (the exit-rule ablation grid) stays parked, and the reason to keep it parked is now
sharper: a grid searched against a baseline that enters names at MCN 15, in one bull regime,
with no costs, on a survivor-only tape, will find parameters that fit those four defects.
