# WO-A22 · The cell of record, audited

**Written 2026-08-16.** Zak ruled on 2026-08-15: audit run 589 — the cell of record `yuna_plan.md`
§3.1's three numbers rest on — before deciding what run 607's failures mean for the law.

Read-only audit, CI run [31927539682](https://github.com/dailyquest-ca/yuna/actions/runs/31927539682),
`research=verify run_ids=589,607`. `verify_run.py` issues no INSERT, UPDATE, DELETE or COMMIT, so
nothing was written to production to produce this.

---

## 1. The answer, in one line

**The arithmetic is real. The book that produced it is not the book §3.6 describes.**

| run 589 · `b5_12_2_L1_3` · 2007-01-05 → 2026-08-14 · 4933 sessions · 752 trades | |
| --- | --- |
| **13 passed** | every headline, the cash identity, every fill, every session, and the tape |
| **3 failed** | all three are about **which names were in the book**, none about the numbers |

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

## 3. What failed — one defect, wearing three hats

| check | finding |
| --- | --- |
| **D1 slot discipline** | trade list shows **7 concurrent names on 2018-01-05**; engine reported max 5 |
| **B7 one company, one slot** | **7 pairs** held concurrently are one security under two symbols: `DINO/HFC` (100.0% of 1405 shared sessions), `TBSI/TBSIQ` (100.0% of 1675), `BALL/BLL` (99.4% of 1445), `BBBY_old/BBBY` (97.7% of 2273), `VVUS/VVUSQ` (96.1% of 3853), and two more |
| **B4 listed where we think** | **7 traded names** miss >3% of the benchmark's sessions while active — probable foreign listings: `RXDX` (946/1723), `LDG` (1146/1398), `SGT` (1147/1398), `NBIS` (3164/3829), `AOI` (3463/3811), `MGROS` (920/960) |

### 3.1 D1 and B7 are very likely the same bug

Seven concurrent tickers in a five-slot book is a violation of §3.6's `Slots = 5`. But B7 says
seven *pairs* of tickers in this run are one company each. **If two duplicate pairs were live on
2018-01-05, then "7 names" is 5 companies in 7 tickers** — the slot count was right in companies
and wrong in symbols.

That is a hypothesis, not a finding, and it is the first thing to test. It matters because the two
readings have very different consequences:

- **If it is only miscounting:** the book held 5 companies, and §3.7(3)'s live rule — "hold at most
  one of a pair; prefer the higher-ADDV line" — already covers it. The modeled numbers are close to
  honest and the defect is cosmetic.
- **If the seventh position carried its own capital:** §3.5 sizes every position at NAV ÷ 5, so
  seven positions is **140% of NAV deployed**. That is unintended leverage, and it inflates both the
  return and the drawdown. The cash identity passing does not rule this out — it proves the money was
  *tracked*, not that the exposure was *authorised*.

**The distinguishing test is cheap:** sum position value on 2018-01-05 and divide by NAV. One
query against the stored trades.

### 3.2 B4 is a known class and is not new

Foreign securities on `.US` tickers — the defect `wo-a16-foreign-listings.md` documents, where a
name quoted in a foreign currency clears the $10M ADDV gate on an FX rate. The participation gate
is built; its threshold has never been ruled. §3.2 of the new plan makes this squarely a
`universe_excluded` question, which is data hygiene and permitted.

---

## 4. What this does and does not mean for the law

**It does not impeach §3.1's arithmetic.** Nothing in the audit suggests the CAGR, the drawdown or
the trade count were computed wrongly. They are exactly what the stored run contains.

**It does question what §3.1 is a number *about*.** A twenty-year record produced by a book that
sometimes held seven positions is not a record of the five-slot engine §3.6 defines, whatever the
arithmetic. §3.1's own framing — "the engine's modeled record" — presumes the model is the engine.

**The fix is mostly already written and deliberately held back.** Migration 041 excludes
`SGI/TPX`, `PENG_old/SGH`, `GEFB/GEF-B` and others by exactly this reasoning, and §3.2 of the new
plan names duplicate listings as a permitted exclusion category — "ticker renames where the vendor
carries both the dead line and the live one; keep the line still printing". `BALL/BLL`,
`DINO/HFC`, `BBBY_old/BBBY`, `TBSI/TBSIQ` and `VVUS/VVUSQ` are that category precisely. They are
not in 041 because 041 predates finding them.

---

## 5. Recommended sequence

1. **Run the 140%-deployment test** on 2018-01-05. One query. It decides whether this is cosmetic
   or material, and nothing else should be decided before it.
2. **Fix the deduplication at the engine, not only in the exclusion table.** An exclusion list is a
   patch that goes stale; `verify_run.py` B7 already detects the general case, so the engine can
   refuse to hold two symbols the scan calls one company.
3. **Re-run all three windows and re-derive §3.1** — as one amendment, with the old numbers kept
   beside the new ones so the size of the correction is on the record.
4. **Then rule on B4's threshold**, which is a separate and smaller question.

**This should complete before §6.5 seeds capital.** §6.4's ten-session shadow compares live output
against the sim's decision on same-vintage bars; if the sim can hold seven names and the live
engine holds five, the shadow will diverge by construction and the divergence will be blamed on
the pipeline.

---

## 6. The instrument found this, which is the point

`verify_run.py` was built during this programme and is the subject of PR #11. It caught three
defects in the programme's own headline result — the one already promoted to law — and it did so
without re-running anything, by re-deriving the numbers from the stored trades instead of trusting
the run's summary.

That is the argument for landing it before the engine is rebuilt, not after.
