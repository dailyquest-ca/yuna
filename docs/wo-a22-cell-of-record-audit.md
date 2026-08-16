# WO-A22 · The cell of record, audited

**Written 2026-08-16.** Zak ruled on 2026-08-15: audit run 589 — the cell of record `yuna_plan.md`
§3.1's three numbers rest on — before deciding what run 607's failures mean for the law.

Read-only audit, CI run [31927539682](https://github.com/dailyquest-ca/yuna/actions/runs/31927539682),
`research=verify run_ids=589,607`. `verify_run.py` issues no INSERT, UPDATE, DELETE or COMMIT, so
nothing was written to production to produce this.

---

## 1. The answer, in one line

**The arithmetic is real, the slot count is real, and one defect survives: the book held the same
company under two symbols.**

| run 589 · `b5_12_2_L1_3` · 2007-01-05 → 2026-08-14 · 4933 sessions · 752 trades | |
| --- | --- |
| **14 passed** | every headline, the cash identity, every fill, every session, the tape, **and slot discipline** |
| **2 failed** | B7 duplicate listings — real. B4 foreign listings — real, known, unruled. |

> ### Correction, 2026-08-16 — the slot breach was the auditor's, not the engine's
>
> This document first reported **"7 concurrent names on 2018-01-05 against `Slots = 5`"** and raised
> the possibility of 140% of NAV deployed. **That was wrong, and the fault was in `verify_run.py`.**
>
> D1 counted a name as live on its exit date *and* on its entry date, which double-counts ordinary
> same-session turnover: §3.5 sequences sells before buys inside the same morning, and
> `concentrated.py:1603-1605` books the exit and drops the position from `held` on that date. Sell
> one name at the open, buy another at the open, and a five-slot book momentarily reads as six.
>
> Counting positions held at the **close** — which is what `backtest_equity.positions` records and
> what §3.6 governs — the sweep returns **max 5 concurrent names, engine reported 5.** The engine
> and its own counter agree, on every one of 4,933 sessions.
>
> **The leverage question is therefore answered: no.** The book never held a sixth position, so it
> never deployed more than 100% of NAV. §3.1's numbers are not inflated by unintended leverage.
>
> Two tests now pin both directions — a two-session breach must still FAIL, and same-session
> turnover must PASS. A check that had only ever been asserted in one direction is how this got in.

---

## 2. What verified

§3.1's numbers are not approximations of the run. They are the run, to the digit:

| §3.1 says | the auditor re-derived, from the stored trades and equity curve |
| --- | --- |
| +26.54%/yr full 20yr | **+26.5377%** |
| −61.2% max drawdown | **−61.1937%** |
| 752 trades (§3.8) | **752 entries, all filling at their session's OPEN** |

And the things most able to hide a fake result all passed:

- **A3 cash identity** — bought 104,992,504, sold 114,449,941, net +9,457,437 against a NAV move of
  +9,989,809. The money is accounted for.
- **B1 fills are real bars** — 1504 fills: 1310 at the open, 223 at the close, 16 on delisted names,
  every one of them present in `prices` on that date.
- **B3 sessions are real** — all 4933 print on SPY.US.
- **B5 the tape is prices** — **no traded name carries an impossible adjusted move.** The defect
  class that invalidated runs 18–44 is absent here. Run 607 still shows `SUG.US 2021-09-07 0.85→85`;
  589 is clean.
- **C1** no exit precedes its entry. **C2** every entry fills at the open, as §3.7(2) requires.

**This matters and should not be lost in what follows.** The engine is not lying about its own
result, the tape underneath it is sound, and the money adds up.

---

## 3. What failed

| check | finding |
| --- | --- |
| ~~**D1 slot discipline**~~ | **withdrawn — the check was wrong.** See the correction in §1. Max 5, every session swept. |
| **B7 one company, one slot** | **7 pairs** held concurrently are one security under two symbols: `DINO/HFC` (100.0% of 1405 shared sessions), `TBSI/TBSIQ` (100.0% of 1675), `BALL/BLL` (99.4% of 1445), `BBBY_old/BBBY` (97.7% of 2273), `VVUS/VVUSQ` (96.1% of 3853), and two more |
| **B4 listed where we think** | **7 traded names** miss >3% of the benchmark's sessions while active — probable foreign listings: `RXDX` (946/1723), `LDG` (1146/1398), `SGT` (1147/1398), `NBIS` (3164/3829), `AOI` (3463/3811), `MGROS` (920/960) |

### 3.1 B7 is the defect that survives, and it is a real one

Seven pairs, each one company under two symbols, **held at the same time**. `DINO/HFC` agree on
100.0% of 1,405 shared sessions; `BALL/BLL` on 99.4% of 1,445; `BBBY_old/BBBY` on 97.7% of 2,273.

The slot count was never breached, which means the harm is not leverage — it is **concentration**.
When two of five slots hold one company, the book is running **four distinct bets, not five**, at
1.25× the intended weight in that name. §3.8 already says five vol-adjusted momentum slots are
~2.5 independent bets; this makes the real number lower still, and unevenly across the record.

It also front-runs a live rule. §3.7(3) requires holding at most one of a pair, preferring the
higher-ADDV line — so the modelled numbers were produced by a book breaking a rule the live engine
is required to keep. That is a sim-vs-live divergence in the direction that flatters the sim.

### 3.2 B4 is a known class and is not new

Foreign securities on `.US` tickers — the defect `wo-a16-foreign-listings.md` documents, where a
name quoted in a foreign currency clears the $10M ADDV gate on an FX rate. The participation gate
is built; its threshold has never been ruled. §3.2 of the new plan makes this squarely a
`universe_excluded` question, which is data hygiene and permitted.

---

## 4. What this does and does not mean for the law

**It does not impeach §3.1's arithmetic.** Nothing in the audit suggests the CAGR, the drawdown or
the trade count were computed wrongly. They are exactly what the stored run contains.

**It does question what §3.1 is a number *about*, though far less than first reported.** The slot
count holds. What does not hold is the assumption that five slots meant five companies: on the
sessions where a duplicate pair was live, the record is of a four-bet book carrying a double weight,
which is not the engine §3.6 defines. That is a smaller correction than leverage would have been,
and it is still a correction.

**The fix is mostly already written and deliberately held back.** Migration 041 excludes
`SGI/TPX`, `PENG_old/SGH`, `GEFB/GEF-B` and others by exactly this reasoning, and §3.2 of the new
plan names duplicate listings as a permitted exclusion category — "ticker renames where the vendor
carries both the dead line and the live one; keep the line still printing". `BALL/BLL`,
`DINO/HFC`, `BBBY_old/BBBY`, `TBSI/TBSIQ` and `VVUS/VVUSQ` are that category precisely. They are
not in 041 because 041 predates finding them.

---

## 5. Recommended sequence

1. ~~Run the 140%-deployment test.~~ **Done — and it was the check that was broken, not the
   engine.** No position was ever bought with money the design did not have.
2. **Fix the deduplication at the engine, not only in the exclusion table.** An exclusion list is a
   patch that goes stale; `verify_run.py` B7 already detects the general case, so the engine can
   refuse to hold two symbols the scan calls one company.
3. **Re-run all three windows and re-derive §3.1** — as one amendment, with the old numbers kept
   beside the new ones so the size of the correction is on the record.
4. **Then rule on B4's threshold**, which is a separate and smaller question.

## 6. Measured — §3.7(3) costs nothing, it pays

Run 612 (control) against run 613 (`dedupe_pairs=True`), same window, same tape, one axis apart.
**The control reproduces run 589 to the digit**, which is what makes the comparison quotable
against §3.1 — CI [31951546462](https://github.com/dailyquest-ca/yuna/actions/runs/31951546462).

| | control · 612 | **pair rule · 613** | |
| --- | --- | --- | --- |
| CAGR, full 20yr | +26.5377% | **+26.7504%** | +0.21 pts |
| max drawdown | −61.1937% | **−59.0493%** | 2.14 pts shallower |
| total return | +9994.85% | **+10332.81%** | |
| trades | 752 | 754 | +2 |
| **B7 duplicate pairs** | **7** | **1** | |
| deflated Sharpe | 0.214 | **0.229** | still UNPROVEN vs 0.95 |

**The duplicated holdings were costing money.** That is the right sign and it should not be
surprising: two slots on one company is concentration without compensation — the same
single-company exposure, bought twice, displacing a fifth independent bet.

So §3.1's numbers are **conservative rather than flattering**. A book obeying §3.7(3) does slightly
better with a shallower drawdown. That is a smaller correction than either direction this document
first entertained, and it points the other way.

### 6.1 The pair that survives, and why it is the exclusion table's job

`QRVO.US/RFMD.US` — 95.3% over 2,377 shared sessions, RF Micro Devices merged into Qorvo.

It gets through because the entry test reads a **trailing 252-session window** and requires 30
shared sessions inside it. At the moment the second line was taken the pair had not yet accumulated
that overlap, so there was nothing to judge on. **That is the overlap floor working, not failing** —
it is the same floor that stops two quiet names from being called twins and evicting a real holding.

Loosening it to catch this one would trade a rare miss for a common false positive. The merger is
squarely §3.2's "ticker renames where the vendor carries both the dead line and the live one", so
it belongs in `universe_excluded` — added here as evidence for the 041 re-check rather than fixed
by moving a threshold.

---

### 5.1 Open for ruling — §3.7(3)'s "prefer the higher-ADDV line"

The engine now holds at most one of a pair. It does **not** yet implement the preference, and the
clause has two readings that differ in what they cost:

| reading | behaviour | cost |
| --- | --- | --- |
| **selection** | when neither line is held and both are eligible, buy the higher-ADDV one | none — it only breaks a tie the rank already had to break |
| **replacement** | if a held line's twin has higher ADDV, sell the held one and buy the twin | a real round trip on a liquidity tiebreak, for no change in exposure |

Today the engine does neither: it keeps whichever copy the rank reached first. That is
deterministic — the sort is stable — but it is not what §3.7(3) says.

**This is not resolved here.** §0.2 sends ambiguity to Zak rather than to improvisation, and the
replacement reading generates turnover the plan nowhere else asks for. The selection reading is the
one I would recommend, and it is a one-line change once ruled.

Worth noting the practical size of it: `DINO/HFC` and `BALL/BLL` are renames where the dead line
stops printing, so the live line wins on ADDV anyway and the two readings agree. The clause only
bites on a genuine dual listing where both lines keep trading.

**This should complete before §6.5 seeds capital.** §6.4's ten-session shadow compares live output
against the sim's decision on same-vintage bars. §3.7(3) makes the live engine hold one of a pair;
the sim held both. Wherever a duplicate pair sits in the top 12 during the shadow, the two will
disagree by construction — and the divergence will be blamed on the pipeline rather than on the
exclusion table it actually comes from.

---

## 6. The instrument found this, which is the point

`verify_run.py` was built during this programme and is the subject of PR #11. It caught three
defects in the programme's own headline result — the one already promoted to law — and it did so
without re-running anything, by re-deriving the numbers from the stored trades instead of trusting
the run's summary.

That is the argument for landing it before the engine is rebuilt, not after.

It also got one of them wrong, in the direction that accuses the engine of a defect it did not
have, and that is worth as much as the finding. A check asserted in only one direction — "does it
fire?" — will eventually fire on something legal. Both directions are pinned now.

---

## 7. Zak's rulings, 2026-08-16

| # | ruling | consequence |
| --- | --- | --- |
| **1** | §3.7(3) means **selection only**, not replacement. Where one line of a pair is already held, **keep it**. | **No code change.** The engine already keeps the incumbent, so today's behaviour is now the law's behaviour. §5.1 is closed. |
| **2** | **Adopt the corrected cell** (`dedupe_pairs=True`) as the cell of record. | §3's cell-of-record line and code stamp change once the sub-windows are in. |
| **3** | **Adopt the corrected run's numbers** for §3.1. | Full 20yr measured: +26.7504% / −59.0493%. Both sub-windows still required — §3.1 is quoted as three or none. |
| **4** | **Exclude the foreign listings.** *"We can only trade on the US stock market, don't care what name someone has or currency if it seems like it's US."* | Data hygiene under §3.2. See §7.1 — Zak also proposed a better mechanism than the participation threshold. |
| **5** | **Re-verify migration 041 and apply what survives.** | 041 is never dispatched. A successor migration carries only rows re-checked against the current tape, plus the six pairs the audit found. |

### 7.1 The exchange filter — Zak's question, and why it is the better instrument

> *"Can't we just use like… NYSE and NASDAQ as a filter?"*

**Yes, and it is strictly better than what was proposed.** The participation gate infers "this is not a US listing" from a name missing too much of SPY's calendar — a statistical proxy, needing a threshold nobody has ruled, and carrying a false-positive risk against any real US stock with a long halt.

The exchange is a **fact we already store**: `universe.exchange` has existed since `001_core.sql` and `ingest.py` writes it. A filter on it needs no threshold and cannot mis-fire on a halted US name.

Two things to establish before writing it, and neither is a ruling:

1. **What `universe.exchange` actually holds for the seven offenders.** The vendor got `currency` wrong on exactly these names — it called roubles USD — so its `exchange` value has to be checked rather than trusted. `MGROS` does not resolve to a US listing in EODHD's own search today (nearest match is Jakarta); `PLZL` does not resolve at all.
2. **Which exchange codes count as "the US stock market".** NYSE and NASDAQ are certain. `NYSE ARCA` and `NYSE MKT` are the same market and hold real ETFs and small caps. **OTC / PINK is the live question** — US-quoted, but thinly, and it is where a delisted foreign line would most plausibly sit. That list is a plan constant and needs Zak's word once the census is in.

**Recommendation:** census first — `select exchange, count(*) from universe where kind='stock' group by 1` — then a filter on an explicit allow-list, with the participation gate kept as a **detector** rather than a gate. It is the thing that found this class in the first place, and `verify_run.py` B4 should keep firing on anything the exchange filter lets through.
