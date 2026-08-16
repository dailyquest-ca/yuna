# WO-A23 — §6.3: the engine takes production

**2026-08-16.** Branch `claude/pickup-previous-session-s3wduf`.

§6.3 reads: *"Retire legacy jobs from the schedule · implement the nightly score job from the code
of record · compose the order sheet & rebuilt payload · check suite (§4.4) · shadow harness (§6.4) ·
downgrade the data plan to EOD Historical Data — All World once legacy jobs are retired."*

All of it is built except the plan downgrade, which is Zak's at the vendor. This is the record of
what changed, what it decided on the live tape, and what is still blocking.

---

## 1. The first live sheet

`research=desk` against production, 2026-08-16:

```
### engine · session 2026-08-14 · gate ON

universe 3204 · ranked 500 · NAV 200,000.00

top 12: SNDK.US, AXTI.US, MU.US, WDC.US, RVMD.US, ASX.US, TSEM.US, STX.US,
        LITE.US, CIEN.US, INTC.US, TD.US
held:   NUE.US

  SELL NUE.US     qty         32   rank 72   (rank)
  BUY  SNDK.US    qty         24   rank 1   mark 1,641.11
  BUY  AXTI.US    qty        489   rank 2   mark 81.64
  BUY  MU.US      qty         41   rank 3   mark 971.66
  BUY  WDC.US     qty         78   rank 4   mark 508.80
  BUY  RVMD.US    qty        196   rank 5   mark 203.71
```

Four things worth reading off it:

- **The sizing is right.** Every buy lands between $39,686 and $39,927 against §3.5's NAV/5 =
  $40,000, with §3.7(4)'s round-down accounting for the shortfall. Nothing exceeds §3.5's 0.98
  ADDV cap.
- **§3.2's pool cap binds exactly.** 3,204 names in the universe after the exclusions, 500 ranked.
- **NUE.US is in the book at 32 shares, tagged `momentum`,** and the engine queues it as a rank
  exit at rank 72. That is one of §6.1's seven liquidation names, already correct.
- **Ten of the top twelve are semiconductors or optical.** §3.3 has no sector cap and the plan
  states none — *"the rank is the entire opinion"* — so this is the design working, not a defect.
  Flagging it because a five-slot book filled from that band is a one-industry book, and that is a
  property of the cell of record you have already ruled on, not a new decision.
- **TD.US at rank 12** is Toronto-Dominion's NYSE line — a genuine US listing, unlike PLZL/NVTK/
  MGROS/IVL, which the WO-A22 exclusions removed. The distinction held.

---

## 2. What runs now

| §4.1 job | File | Was |
|---|---|---|
| `ingest` | `src/ingest.py` | unchanged, minus the earnings calendar |
| `reconcile` | `src/reconcile.py` | **new** — did not exist |
| `score` | `src/sheet.py` | `src/score.py` (fundamentals → CCN → hurdles → arming) |
| `check` | `src/gauges.py` | `src/check.py` |
| `compose` | `src/brief.py` | `src/compose.py` |
| `notify` | `src/notify.py` | unchanged, new brief kinds |
| §6.4 shadow | `src/shadow.py` | **new** |

The chain is **reconcile → score → check → compose → notify**, plus `shadow` beside `check`.

`reconcile` runs first, and that ordering is a correctness argument rather than a preference.
`score` reads `book` to decide what is held, so a fill taken this morning and not yet folded leaves
the book a day stale and the engine proposes a buy of a name it already owns. This repository has
paid for that once: four unrecorded fills on 2026-08-04 put RS.US through four consecutive briefs
as a new entry at the price you had already paid for it.

**Retired from the schedule, not from disk.** `score.py`, `check.py`, `compose.py`, `fills.py`,
`signals.py`, `arming.py`, `rank.py`, `fundamentals.py` and `ingest-filings.yml`'s cron are all
still present and dispatchable; none of them is on a schedule or in a chain. Deleting six thousand
lines in the same change that repoints production is how you get a night with no desk. Deletion
belongs after §6.4's shadow passes, and `test_workflows_parse.py` now fails if any of them creeps
back into the chain.

**`ingest-daily` no longer fetches the earnings calendar** (flag `INGEST_EARNINGS`, default off).
§4.5: *"No fundamentals, news, intraday, or calendar feeds are read by any decision."* It is also
the practical blocker on the plan downgrade — the calendar endpoint is not on EOD Historical Data —
All World, so those two calls would fail the night on the first billing cycle after you downgrade.

---

## 3. What each new job does, in one line each

- **`engine.py`** — §3 as pure functions, every constant quoted from §3.6 with its clause. The one
  definition of what the engine decides. `engine.digest()` stamps §3.6 on every decision, so two
  sessions that disagree while carrying the same digest disagree about the *data*, and two with
  different digests disagree about the *law*.
- **`desk.py`** — reads the tape, computes tonight's sheet, renders it. **Writes nothing.**
- **`sheet.py`** — persists the decision: `engine_sessions`, `engine_ranks`, and §4.3's tickets in
  state `proposed`. Idempotent on (session, mode) and (session, ticker, action).
- **`gauges.py`** — §4.4's six gauges, four of them recomputations from the raw bars.
- **`brief.py`** — §5.1's morning brief and §4.1's Saturday letter, rendered from one payload read.
- **`reconcile.py`** — folds your broker receipt and compares the book against the broker's own
  position list. Only the comparison is reconciliation; folding a fill and trusting the arithmetic
  that folded it proves nothing.
- **`shadow.py`** — §6.4's attestation: the live engine against `concentrated.py` on the same bars,
  written to `shadow_attestations`.
- **`closeout.py`** — §6.2's five clauses, in one guarded pass. Dispatch-only, `CLOSEOUT_APPLY`.

---

## 4. Three judgement calls you should know about

**Engine NAV is not inferred.** §3.5 sizes at engine NAV / 5, and that number is not in the store:
`nav_snapshots.nav_cad` is every account converted to CAD, and the engine is a USD sleeve. Using
one for the other would be wrong by the FX rate *and* by the other two accounts, and it would not
throw — it would produce a plausible position size. So `sheet.py` reads `ENGINE_NAV` or a logged
`config.engine_nav` row, and when neither exists it writes the session, the ranks and **every sell**
(§5.4 makes exits unblockable), leaves the buy quantities null, and goes amber. §4.3 already
describes that state: *"Amber/red pipeline: no new buy tickets."*

**§4.4's "historical band" is taken literally.** The plan names six gauges and no tolerances, so
none are invented. Where a gauge needs a comparison it comes from the plan's own arithmetic
(§3.5's NAV/5, §3.2's screen, §3.4's SMA) or from the stored history. "Screen survivor count within
historical band" compares against the observed range of every prior session. A tighter band would
be a better gauge and would also be a number nobody ruled — that is §0.3's call, not the code's.
**If you want a tighter band, that is a plan edit and I will implement whatever you rule.**

**§6.2's "close the book table to zero" is implemented as sell tickets, not as zeroing the book.**
Until you sell, the broker still holds those shares; a book zeroed ahead of you would put
`reconcile` in exactly the state it exists to detect. The book reaches zero through the receipts —
ticket → transaction → position closed — and that path *is* §6.2's "paper trail reconcile can read".

---

## 5. What is blocking, and whose it is

**Yours, and nothing moves without them:**

1. **§6.1 liquidation** — cancel every resting order, sell the seven, route the proceeds. The
   system has no way to do this and must not.
2. **`config.engine_nav`** — until this row exists the nightly sheet writes unsized buys and goes
   amber every night. One row: `insert into config (key, value, set_by) values ('engine_nav',
   '<number>', 'zak')`. Say the number and I will write it.
3. **A `balances` row for the LOC** — §2.3 states a $75,200 limit as of 2026-08 and a $7,980 legacy
   draw. The plan states them; the store does not hold them, and `v_levered_facility` reports
   headroom to the **cap** (50%), which is $29,620 rather than the $67,220 a limit-based reading
   would give. Confirm the two numbers and I will write the row.
4. **The data plan downgrade** — §4.5's required product is EOD Historical Data — All World. The
   code no longer reads anything outside it.

**Mine, and queued:**

5. Apply migrations 051–055 to production (`migrate` dispatch). All additive except 054, which
   rebuilds `v_session_payload`; nothing in the database depends on the old definition, and the
   legacy ruling docket moved to `v_ruling_docket` rather than being dropped.
6. Run `closeout.py` at score-green, once §6.1 has happened.
7. Ten sessions of `shadow.py`, then read `v_shadow_progress`.

**§6.5's seed** needs all four of: shadow passed · pipeline green · **gate ON** · your seed ruling
in chat. The gate is ON today. The other three are the list above.

---

## 6. What §6.4 does and does not attest

`shadow.py` compares two things against `concentrated.py` — the research engine that produced the
cell of record — on the same arrays:

- §3.3's rank, against `concentrated.rank_at(risk_adjusted=True, top_by_addv=500)`
- §3.4's gate, against `concentrated.regime_latch(confirm_out=1, confirm_in=3)`, walked forward

It does **not** compare §3.5's order rule, and the report says so where it is read. That rule's only
implementation outside `engine.orders` is inline in `simulate()`, carried on a book that has evolved
from the start of its own window, so there is no way to ask it "what would you do tonight" without
also handing it a year of its own history. What stands in its place is named in the file:
`tests/test_engine_parity.py` (42 assertions that the two ranks agree over adversarial tapes) and
`tests/test_engine_book.py` (14 tests pinning `engine.orders` to §3.5's clauses one at a time).

An attestation that claimed more than it checked would be worse than none, because §6.5 gates the
seed on this record.

---

## 7. Tests

682 unit · 233 integration. New this work order:

| File | What it pins |
|---|---|
| `test_sheet.py` (14) | idempotence, withdrawal-not-deletion, the approved ticket that survives a re-score, the unsized-but-protective sheet |
| `test_reconcile.py` (13) | both break directions, the doubled fold, the negative-position refusal, the dry run that still compares |
| `test_gauges.py` (18) | every gauge, each with one thing broken |
| `test_brief.py` (13) | §4.2's nine payload items, §5.1's six sections, §2.3's ramp, headroom-to-cap |
| `test_shadow.py` (7) | live/sim agreement on real arrays, and a divergence that blocks the pass until ruled |
| `test_closeout.py` (10) | §6.2's five clauses, and the one thing it must not do |
| `test_workflows_parse.py` (+6) | the chain's shape, and the brief-kind/notify seam that fails green and delivers silence |

---

## 8. What the migration actually changed, measured

Migrations **049–055** were all pending — which means the WO-A22 exclusions you ruled on this
morning had never reached production. They are applied now, and the effect was measured rather
than assumed: the desk sheet after the migration is **byte-identical** to the one before it, and
the universe is still 3,204.

That is the correct outcome and the census says why. `PLZL`, `NVTK`, `MGROS` and `IVL` all carry
`status = delisted`, and `desk.py` already filters delisted names. The four duplicate lines
(`BLL`, `HFC`, `BBBY_old`, `RFMD`) are dead symbols by construction — each is a rename or a merger
into a survivor. **So 050's exclusions bind on the historical tape run 589 was measured over, and
change nothing about today's ranking.** Both statements needed to be true and now both are checked.

Two things the census surfaced that were not on anybody's list:

**Eight active names are being excluded right now.** The census counts 3,212 active stocks; the
desk ranks 3,204. That gap is `universe_excluded`, and **041 is applied in production** — today's
dry run proved it by listing only 049 onward as pending. So `APPS.US` and `BDN.US` are excluded
today under a 041 row whose own text reads *"identical 653-bar series … pending a re-pull"*, and
the re-pull has since happened. If the vendor defect is gone, two live tradable common stocks have
been kept out of §3.3's ranking on evidence nobody re-checked — and §3.2 calls a standing exclusion
of a live tradable common stock a strategy change, not hygiene. The census now runs that test
(`bars.same_security`, daily returns at 1e-4 with the variation floor) and prints RELEASE or
STANDS. **The release itself is your ruling, not mine.**

**An NYSE/NASDAQ allow-list still keeps zero of 3,212.** `universe.exchange` holds `US` for all
6,332 stocks — it is EODHD's bulk-feed bucket, not a listing venue. That confirms the WO-A22 §8.1
finding on today's data: the exchange filter you asked about cannot be built from this column, which
is why the four foreign names are excluded by name.

---

## 9. Still open from earlier work orders

- **Runs 616/618** — the sub-window controls, and the §3.1 amendment they would justify. Not yet
  read.
- **LDG and SGT** — each missing roughly a year of contiguous history (252 and 251 sessions). A
  re-fetch, not a defect in the engine.
- **041's three quarantine rows** (VGNT, APPS, BDN) and **TBSI/TBSIQ, VVUS/VVUSQ** — held back from
  migration 050 on stated evidence. Each needs one query, and each is documented in 050 itself.
