# yuna_plan.md — v1.2

**Status: LAW. v1.0 promoted by Zak, 2026-08-15. v1.1 promoted by Zak, 2026-10-06. v1.2 promoted by Zak, 2026-10-07 (§7). This is the sole authoritative document; where any other text disagrees, this document wins. Its one copy is on `main`, published to `v_law` (§0.7).**

---

## §0 — Governance

**0.1 The plan is law.** This document governs everything Yuna does. If the plan and a habit disagree, the plan wins. If the plan is wrong, the plan gets amended — it does not get ignored.

**0.2 Division of rule.** Zak alone rules the law, the risk posture, the leverage, and executes every order. Yuna rules names inside the plan's gates and never places or simulates a trade execution. Ambiguity escalates to Zak; it is never resolved by improvisation.

**0.3 Law-change discipline.** Every edit to this document is announced with exact old and new lines. Zak rules on each before promotion. Yuna may draft; only Zak promotes.

**0.4 The one-read law.** Every interactive session reads `v_session_payload` once from Supabase, and the law from `v_law` (§0.7), then judges. Scores, ranks, and gate states are never recomputed by hand in chat. A stale or red pipeline means no new tickets. Gate-off exit sheets are never blocked by pipeline color (§5.4).

**0.5 Credentials.** No credentials, API keys, or tokens ever appear in chat. Secrets live only in GitHub Actions repository secrets (`dailyquest-ca/yuna`). Any secret that touches a chat is rotated immediately.

**0.6 Record-keeping.** Rulings, tickets, book history, and run records are never deleted. The database and git carry the full history for audit.

**0.7 One copy of the law.** This file, on `main` of `dailyquest-ca/yuna`, is the only copy of the law, and `docs/routines-contract.md` beside it is the only copy of how the Routines read it. Every merge that changes either is published — full text, version and SHA-256 — to Supabase by the `law` job, the only writer of the append-only `law` table. Sessions and Routines read the law from there (`v_law`), never from a project file, a paste or a local draft. The payload carries the published version and hash, so every brief names the law it was read under. A promotion is a merge to `main`; §0.3 still decides who promotes.

---

## §1 — Vision (Zak's words)

Learn about investing. Become a master investor.

Get to $5M as fast as possible, so I can retire and do whatever work I want — with no risk.

The way there: one momentum engine, run by rules. Numbers ship, not a feelings ship. I execute every order myself, and I follow the law especially on the days that's annoying.

---

## §2 — Capital structure

**2.1 Accounts are the allocation.** There are no percentage targets.

| Account | Role | Holds |
|---|---|---|
| **TFSA** | **The engine** | The engine's five names (+ park when gated off) |
| **RRSP** | Reserve | SPMO (US-listed; treaty-exempt withholding) |
| **NONREG** | Reserve + levered layer | VXC.TO (unlevered residue and all levered lots) |

New contributions land per Zak's direction; the default is each account's designated holding.

**2.2 Reserve layer.** SPMO in the RRSP, VXC.TO in the NONREG. One holding per account. No rebalancing, no targets, no maintenance decisions. Reserve names are Yuna's to rule inside this structure; changing the *structure* is Zak's.

**2.3 Levered layer.**

- Facilities: the TFSA-secured LOC is the only live facility (limit $75,200 as of 2026-08). HELOC and margin are not opened; opening either is a law change.
- **Hard cap: drawn balance ≤ 50% of the facility limit** ($37,600 today). The cap binds hardest when the book is red; that is its purpose.
- Every draw purchases VXC.TO in the NONREG the same day — one draw, one purchase, so interest deductibility under ITA 20(1)(c) has a clean paper trail.
- **The draw and the purchase are both CAD** (the LOC is CAD; VXC.TO is CAD-listed). No FX step exists at any tranche — no conversion cost, no gambit, ever.
- **Ramp (ruled 2026-08-15):** three tranches to the cap — $12.5K immediately · $12.5K ~Sep 15 · $12.6K ~Oct 15. Each tranche requires the gate (§3.4) ON that week; a skipped tranche shifts one month; never two tranches in one month. Tranche one is independent of Phase 0 liquidation — LOC headroom does not depend on sale proceeds. The legacy draw ($7,980) is repaid from its position's own sale proceeds (§6.1).
- The facility is callable. The levered layer holds no defense against a call other than the cap and the reserve. This is accepted in writing.

**2.4 No idle cash.** Cash that is not awaiting a same-week engine order sits in the account's designated holding.

**2.5 Review checkpoint.** At the first completed gate cycle (ON→OFF→ON) **or** 12 months of live engine record, whichever comes first: one full-structure review in one sitting — allocation walls, levered cap, reserve names, and the engine's live record against its modeled numbers. Any change is a ruling.

**2.6 Cash of record.** An account's cash is Zak's last stated balance (an anchor in `balances`) plus every recorded fill since. Engine NAV (§3.5) is derived from it nightly; a negative derived balance, an unpriced or stale holding, or missing FX makes engine NAV unknown, which holds buys while sells stand. The anchor's date is printed beside the cash. Dividends, withholding, contributions and interest reach cash only through a new anchor.

---

## §3 — The engine

**Cell of record: `b5_12_2_L1_3` · run 589 · code stamp `235bef5fd174dcab` · park SPY.US · regime source SPY.US.** The engine's authority is the code at that stamp. Where any document and the code disagree, the code is authoritative and an erratum is recorded. *Live park is USD cash on an interim ruling (§3.4, v1.1) — a recorded divergence from the cell of record (§3.7(6)).*

**3.1 The three-numbers law.** The engine's modeled record is quoted as all three windows or none:

| Window | CAGR |
|---|---|
| 2007–2017 | **+10.66%/yr** |
| 2017–2026 | **+51.28%/yr** |
| Full 20yr | **+26.54%/yr** |

Max modeled drawdown **−61.2%**. Deflated Sharpe **0.214** against a 0.95 bar over 448 in-sample trials: verdict **UNPROVEN**. The live record is the experiment. There are no stops, by design.

**3.2 Universe & screen (nightly).**
- Universe: `.US` common stocks from `universe` (kind='stock'), minus `universe_excluded`, minus delisted.
- **Exclusion policy:** `universe_excluded` is data hygiene only — duplicate listings (ticker renames where the vendor carries both the dead line and the live one; keep the line still printing), non-common equity (preferreds, warrants, thin share-class lines), quarantined vendor data defects, and exchange test symbols. The live table is surfaced in the payload and the Saturday letter. Excluding a real, tradable common stock for any editorial reason is a strategy change and requires a ruling.
- Screen, per name: ≥210 finite bars in the last 252 · raw close ≥ $5 · 50-session median ADDV ≥ $10M · finite prices at i−252 and i−21.
- Pool: top 500 survivors by ADDV.

**3.3 Score & rank.** `score = (adj[i−21] / adj[i−252] − 1) ÷ stdev(daily returns, 252)`, ranked descending. The rank is the entire opinion. The engine ignores earnings dates, themes, fundamentals, and news by design.

**3.4 Regime gate.**
- Signal: SPY adjusted close strictly above the mean of its last 200 adjusted closes (inclusive of today).
- Latch: 1 red session → OFF · 3rd consecutive green session → ON. If the gate cannot be evaluated on fresh data — SPY missing from the newest session's tape, or the tape older than §5.6's 4-day constant — it is **unevaluated**: the sheet proposes nothing new, buys are held, and the brief names the stale bar. A data outage alone never sells the book.
- **Gate OFF:** the entire book sells at the next executable open; queued exits clear; all proceeds to park. **Park, interim (ruled 2026-10-06): USD cash in the TFSA** — no park purchase is executed while OFF. The cell of record parks in SPY.US; a T-bill park (SGOV.US) is under research (§5.3) and is promoted only on evidence. No buys of any kind while OFF.
- **Gate ON (after latch):** normal operation resumes; seeding/refill per §3.5.

**3.5 Book mechanics.**
- **Slots:** 5, equal weight. Engine NAV is the TFSA's engine capital — the slots, the TFSA park, and TFSA cash; reserve and levered holdings (§2.2, §2.3) are outside it. Slot weight = engine NAV ÷ 5, marked at the decision close. **Order size = the lesser of slot weight and deployable TFSA cash** — TFSA cash on the book plus the same session's sell proceeds, marked at the decision close. When several buys share a session, deployable cash divides equally among them, each capped at slot weight. Fills occur at the next open (drift accepted). A slot filled below weight counts as filled and is reported; it is never topped up.
- **Exit:** a holding ranked below 12 queues that night and sells at the next open; a no-print retries nightly until filled.
- **Displacement:** if the best unheld name in the top 2 ranks strictly better than the worst holding — swap. At most one displacement per session.
- **Free slots:** fill from the top 12 by rank. Multiple slots may fill in one session. Seeding fills all five in one session.
- **Cash sequencing:** sells execute first, buys the same morning on unsettled proceeds. **Buys never draw on capital outside the TFSA**; a shortfall beyond TFSA park and cash is reported as held-below-weight, not funded. Residue returns to park. A buy that gets no print (no executable trade that session — e.g., a trading halt at the open) is cancelled, not retried; the slot refills from the next ranking. Exits are obligations; entries are options.
- **Participation cap:** an order may not exceed 0.98 of the name's ADDV — a correctness check, not a live constraint at current size.
- **Corporate actions on held names:** a split the vendor reports on a held name, once the raw closes across its date agree, is applied to the ledger as a quantity adjustment — no cash, cost carried — before `score` runs, and the brief names it. A ticker change, merger, takeover, or a held name with no bar on the decision session is never turned into a rank exit or a refill by inference: the name keeps its last recorded quantity and its slot, buys are held, and the brief names it until Zak records what happened. A gate-off still lists it to sell (§5.4), marked unpriced.

**3.6 Constants of record.**

| Constant | Value |
|---|---|
| Slots | 5 |
| Exit rank | >12 |
| Fill band | top 12 |
| Displacement band | top 2 vs worst holding |
| Gate SMA | 200 sessions, SPY adj close, inclusive |
| Latch | 1 red → OFF · 3 green → ON |
| Screen | ≥210/252 bars · ≥$5 · ≥$10M median ADDV (50-sess) |
| Pool | top 500 by ADDV |
| Score | 21/252 lookback ÷ 252-day vol |
| Sizing | lesser of NAV ÷ 5 and deployable TFSA cash, at decision close (v1.1) |
| Participation | ≤0.98 ADDV |
| Park | USD cash, interim (v1.1) · cell of record: SPY.US · T-bill variant under research |
| Regime source | SPY.US |

**3.7 Sim-vs-live divergence register.** Accepted, in writing:
1. Gate-off: sim sells at the same session's close; live sells at the next open (~35 crossings/20yr; that overnight is unmodeled).
2. Sizing marks at decision close; live fills at next open — drift accepted.
3. Dual-listed / share-class twins inside the top 12: hold at most one of a pair; prefer the higher-ADDV line.
4. The sheet sizes whole shares, rounded down, at the decision close; residue stays in the park (§3.4). Zak may execute the same dollar amount as a fractional order where the broker supports it, and the fill — not the ticket — is the record.
5. Data revisions: adjusted-close restatements can move a replayed rank; the shadow (§6.4) compares same-vintage data only.
6. Park (v1.1): live parks gated-off capital in USD cash on an interim ruling; the cell of record parks in SPY.US. Gate-OFF stretches in the live record will not match the sim's until the T-bill research rules and the code of record is updated.
7. Sizing (v1.1): live caps a buy at deployable TFSA cash; the cell of record sizes every fill at NAV ÷ 5 from a same-account park. A live slot may therefore open below weight where the sim's would not.
8. A held name with no bar on the decision session (rename, merger, takeover, halt, vendor omission): live keeps its quantity and its slot and holds the buys until Zak records what happened (§3.5); the cell of record queues it as below 12 and retries the sell until it prints.

**3.8 Known limitations (quoted with the engine, always).** The verdict is unproven by our own bar. Twenty years of tape contains exactly two crash shapes; the engine has never been shown a grinding multi-year decline, and its edge is derived from V-shaped recoveries. The park in the cell of record is SPY: gated-off capital rides the index down (2008 modeled: −37.3% while gated); the live interim park is cash, which removes that ride and also the first days of each modeled recovery — the T-bill research measures the trade. Five vol-adjusted momentum slots are ~2.5 independent bets, one mechanism. Modeled costs: $132,055 across 752 trades. A −61% drawdown has never been tested against a human.

---

## §4 — Pipeline & data

**4.1 Jobs (nightly, exchange sessions).**

| Job | Does |
|---|---|
| `ingest-daily` | EOD bars for the universe + SPY; a retry firing an hour later exits if the first landed (§5.6), and the chain behind it re-runs on the same tape |
| `reconcile` | First, a vendor-reported split on a held name enters the ledger, quantity only (§3.5); then receipts into the ledger, and book vs a broker statement when Zak supplies one |
| `score` | §3.2–3.5 logic: screen, rank, gate, queue, order decisions; writes the sheet |
| `shadow` | The live decision vs the cell of record's on the same bars, attested (§6.4, standing) |
| `check` | Gauge suite (§4.4) |
| `compose` | The morning brief, rendered from `v_session_payload` |
| `notify` | Confirms the composed brief exists for delivery |

Weekly (Saturday): `ingest-universe` refreshes membership (§5.6's census floors), and the chain behind it composes the Saturday letter (clinical: gate, rank stability, DD status, divergences, learnings, NAV vs the §1 destination). `backup` dumps the decision tables once a month. On every merge to `main` that changes this file or the routines contract: `law` (§0.7). Dispatch-only tooling (migrations, backfills, backtests) never runs on a clock.

**4.2 The payload.** `v_session_payload` carries: gate state & latch, current book with ranks, the nightly order sheet, top-12 with scores, the exclusion table, NAV & DD status, levered facilities & tranche schedule, pipeline freshness, learnings, and the law's published version and hash (§0.7). It is the single read of every session.

**4.3 Orders & tickets.**
- The nightly sheet is the only source of engine orders. Zak executes at the open: market orders (sells first, then buys). **No GTC orders exist anywhere in this system.**
- Ticket states: proposed → approved → executed → reconciled. Yuna writes rows; Zak's execution is the event; reconcile closes the loop with the receipt.
- Red pipeline: no new buy tickets. An amber from a price-critical job (`ingest-daily`, `score`) holds buys the same way, through §4.4's freshness rule; any other amber, the check suite's own gauges included, warns and holds nothing. Gate-off exit sheets dispatch regardless of pipeline color — the gate's own data is its authority; if that data is stale the gate is unevaluated, nothing new is proposed, and the last sheet decided on fresh data stands (§3.4).

**4.4 Check suite.** Gate reproducibility from raw bars · screen survivor count within historical band · rank reproducibility on same-vintage data · order sheet completeness & sizing arithmetic · book-vs-ledger agreement (red on any break in the TFSA, amber in other accounts), with the age of the last broker statement compared shown but never coloured — no statement feed exists · data freshness. Any red holds buys; nothing holds exits.

**4.5 Data.** EODHD end-of-day bars (adjusted close carries splits/dividends) for US common stocks + SPY, plus exchange symbol lists and delisted lines. **Required product: EOD Historical Data — All World.** No fundamentals, news, intraday, or calendar feeds are read by any decision. Plan downgrade executes after §6.3 retires legacy jobs; billing is Zak's outside this law. **Quarantine:** a nightly print that moves more than **40%** from the session before, with no corporate action logged for it, is held in quarantine until a second source — a live vendor quote — agrees within **2%**; while one is held, `ingest-daily` is amber, which holds buys (§4.3). The two numbers are config rows (`quarantine_move_threshold`, `quarantine_source_tolerance`) and change only by ruling.

---

## §5 — Operations

**5.1 Sessions.** The morning brief renders: freshness · gate & latch · the order sheet · book with ranks & P/L · any split the ledger recorded since the last sheet · DD status vs milestones, with the drawdown record beside it (§5.2) · tranche schedule status. Judgment happens in chat; arithmetic happens in the pipeline. Zak asks in plain words; no command vocabulary exists.

**5.2 Drawdown milestones — information, never action.** Pager at **−10%** engine DD; informational lines at −20 / −30 / −40 / −50. **No mechanical intervention exists at any level.** Any intervention is Zak's explicit ruling in chat. This is the design, chosen with the three numbers in view.

**The drawdown record rides with the milestones** (2026-09-02, Zak: *"the most important piece is having something to tell me and remind me... that's likely what you're gonna experience sixty percent of the time"*). Quoted from run 624 — the cell of record on 2007-01-12 → 2026-09-01, SPY park, 4,940 sessions, WO-A24's control — and re-measured only when the cell of record changes:

| at or below the running high by | share of sessions |
|---|---|
| 10% | 68.4% |
| 20% | 47.6% |
| 30% | 26.2% |
| 40% | 11.1% |
| 50% | 1.5% |

Its worst trough, −60.3% on 2009-03-09, made a new high on 2013-09-10, four and a half years later. The worst since, −45.9% on 2025-11-21, made one on 2026-04-30, five months later. The brief prints the share for the deepest milestone the book has passed and both recoveries, every session. **The bet is the rotation, not the name:** the record says the book recovered every time, and says nothing about the names it held at the trough.

**5.3 The learning loop.** Observations → learnings with required falsifiers → proposals → Zak's ruling → promotion or expiry. No rule changes ship without this path.

**5.4 Protective actions.** Gate-off exits and rank-exit sells are protective-direction and are never blocked — not by freeze, not by amber, not by any throttle.

**5.5 Freeze.** Zak may halt buying at any time, in any words; that state is a freeze. A freeze halts all buys (entries, refills, displacement buys, levered tranches). Exits fire normally; proceeds park. Lifted only by Zak's word.

**5.6 Erratum register.** Where engine documentation disagrees with the code of record, the code wins and the erratum is logged.
- 2026-08-15 — free-slot fill band is top-12; earlier engine research documentation said otherwise.
- 2026-08-05 (recorded 2026-09-13) — three operating rulings the code cites: **stale means the bars, not the clock**; **schedule drift is not a half-failure and never turns a job amber**; **monthly work is guarded by whether it has run, never by the date**.
- 2026-09-13 — §4.4's "any red holds buys" binds the check suite's own gauges and the price-critical jobs (`ingest-daily`, `score`). The census (`ingest-universe`) refreshes membership and writes no price; its red is a warning on the freshness line and never holds buys.
- 2026-09-13 — operating constants of record: bars older than **4 days** hold buys (one long weekend, measured in UTC); a job's newest run within **36 hours** is its current state; lateness under **30 minutes** is not printed; the retry looks back **4 hours** for a green first firing and past that re-ingests the same tape.
- 2026-09-14 — §4.4's "screen survivor count within historical band" is the band of session-to-session **change**, not of the level. A level band can never admit a new low, and three weeks of ordinary attrition (2,336 → 2,274 survivors, the summer tape rolling into the 50-session median) read as amber on every down day while the universe stood still. A jump the tape has never made is amber; a drift it makes every week is green.
- 2026-09-14 — §4.3 amended in place (old line: "Amber/red pipeline: no new buy tickets."): a **red** check holds buys; an **amber** from a price-critical job (`ingest-daily`, `score`) holds buys through §4.4's freshness rule; any other amber, the check suite's own gauges included, warns and holds nothing. The code had always read it this way; the plan now says so.
- 2026-09-13 — census admission floors: a listed US common stock gets a `universe` row when its census-day close is **≥ $4** and it traded **≥ $5M** that day. Looser than §3.2 on purpose: one day's volume is a noisier test than §3.2's 50-session median, which the nightly screen applies from our own bars. On the data, two of the eighteen names the live engine had ranked top-12 (AXTI, MXL) printed days under $10M in the prior year.
- 2026-10-07 — §3.2's "50-session median ADDV" is the median of the **adjusted** close × volume, the code of record's basis (`concentrated.build_grid`); the $5 floor reads the raw print. Live priced it on the raw close from 2026-08-17 to 2026-10-07, which read a re-pulled name's pre-split bars at the split factor (APH.US 1.67× on 10-05).
- 2026-10-07 — §3.4's "the newest session" is the newest bar among the names §3.2 ranks that night, not the newest stock bar in the store: OTC lines and dead tickers print on market holidays (2026-05-25, 06-19, 07-03, 09-07), and the names the engine ranks print exactly when the exchange does.

---

## §6 — Phase 0: Deployment (completed 2026-08-28; kept in place as the record the code cites)

**6.1 Liquidation & first draw (Zak, at Wealthsimple).**
1. Cancel all resting orders — every GTC, stop-limit, and pyramid order, without exception.
2. Sell at market: ANET 40 · NVDA 40.0437 · TSM 15.1647 · NUE 32 · ISRG 26 · AVGO 30.0964 · CNQ.TO 142. (Names appear here as positions-to-liquidate only.)
3. Same session: TFSA proceeds → SPMO (bridge) · RRSP cash → SPMO · CNQ proceeds → repay LOC $7,980, residue → VXC.TO.
4. Tranche one ($12.5K → VXC.TO) may execute the same morning, independent of the sells — it does not wait on proceeds.

**6.2 System close-out (Yuna, at score-green).** Sell rows for all seven; void all open tickets; retire all armed rows; close the book table to zero with a paper trail reconcile can read; close the six brewing learnings as *retired with engine*.

**6.3 Build (work orders, repo).** Retire legacy jobs from the schedule · implement the nightly score job from the code of record · compose the order sheet & rebuilt payload · check suite (§4.4) · shadow harness (§6.4) · downgrade the data plan to EOD Historical Data — All World once legacy jobs are retired.

**6.4 Shadow — 10 sessions.** The pipeline runs live producing order sheets nobody trades. Each night: live output vs the sim's decision on the same-vintage bars, attested in writing. Pass = 10/10 matches, or every divergence named and ruled. Capital waits in SPMO throughout. **Passed 2026-08-27: ten sessions from 2026-08-14, no divergence.** The shadow continues nightly as a standing attestation; a divergence is named and ruled like any erratum (§5.6).

**6.5 Seed.** Conditions: shadow passed · pipeline green · **gate ON** · Zak's seed ruling in chat. Then all five slots fill from the first live ranking in one session. If the gate is OFF when the shadow completes, capital holds in SPMO until the first ON latch, then seeds.

**Seeded 2026-08-28** from the 2026-08-27 sheet: SPMO 810 sold, five slots filled (AXTI, MU, RVMD, SNDK, WDC).

---

## §7 — Changelog

**v1.0 — 2026-08-15 — Founding law. Promoted by Zak.** Establishes: a single momentum engine (cell of record `b5_12_2_L1_3`) housed entirely in the TFSA; accounts-as-allocation with no percentage targets; reserve layer SPMO (RRSP) and VXC.TO (NONREG); a levered layer hard-capped at 50% of the LOC limit with a three-tranche gate-conditional ramp; deployment via Phase 0 — liquidation → build → 10-session shadow → seed, target mid-September 2026. Park is SPY per the cell of record; a T-bill park variant is a research work order, promoted only on evidence. Drawdown milestones are informational only. Exclusions are data-hygiene only. No stops, no GTC orders, no command vocabulary.

**2026-09-02 — §5.2 amended: the drawdown record rides with the milestones. Promoted by Zak in chat.** §5.1 lists it. The shares and the two recoveries are run 624's, re-measured only when the cell of record changes. Information, never action — unchanged.

**v1.1 — 2026-10-06 — Size to deployable TFSA cash; interim cash park. Promoted by Zak.**
- §3.5 Slots: order size becomes the lesser of slot weight (engine NAV ÷ 5) and deployable TFSA cash; engine NAV defined in words as the code already computes it (TFSA slots + park + cash); a slot filled below weight counts as filled and is never topped up. Triggered by the 2026-10-05 ASX sheet (580 proposed, 512.4837 fundable from the TFSA).
- §3.5 Cash sequencing: buys never draw on capital outside the TFSA; a shortfall is reported, not funded.
- §3.4 Gate OFF: park is USD cash in the TFSA on an interim ruling; no park buy executes while OFF. SPY.US remains the cell of record's park; a T-bill park (SGOV.US) is a research work order under §5.3, promoted only on evidence. §3.6, §3.7(6–7), §3.8 and §8 amended to match.
- **Transitional, until the score job implements both:** the sheet's buy quantity is a ceiling — Zak executes to deployable TFSA cash — and any SPY.US park buy the sheet prints on a gate-OFF morning is not executed; the sells are.
- Build work orders: `score` sizing cap and park change · `book`/`reconcile` TFSA cash line · `compose` prose (RRSP SPMO is reserve, not park; shortfall sits in the overweight slots) · `check` sizing test · T-bill park backtest on the cell of record.
- Zak's rulings of the same day, recorded: concentration in the book is accepted as the strategy ("that's the point; we just have to be quick on the move" — the exit rule is the quickness); the note v2 messaging plan of 2026-09-15 is dropped and the 2026-08-24 delivery spec stands.

**v1.2 — 2026-10-07 — One copy of the law; the rulings of 2026-10-07; the plan made to say what runs. Promoted by Zak, by delegation.** Drafted by Claude from the 2026-10-07 quality review and proposed line by line; Zak could not read the draft and ruled: *"if you think it's good, go ahead and wrap this all up."* Every edit below is on that word, and each is open to his ruling like any other line.
- §0.4, §0.7, §4.2: the law has one copy, this file on `main`, published by the `law` job to `v_law`; sessions and Routines read it there and the brief prints its version. The claude.ai project copies are retired.
- §3.4 latch and §4.3, Zak's ruling of 2026-10-07 ("hold buys, sell nothing"): a gate that cannot be evaluated on fresh data is unevaluated — nothing new is proposed, buys are held, a data outage alone never sells the book. What counts as stale is this entry's reading; §5.6 records how "the newest session" is read.
- §3.5 corporate actions and §5.1, Zak's ruling of 2026-10-07 ("pipeline records splits"): a vendor-reported split on a held name enters the ledger before `score`, quantity only, and the brief names it; a ticker change, merger or takeover fails closed until Zak records it. A halt or a vendor omission looks the same on the tape and is held the same way — this entry's reading. §3.7(8) registers the divergence from the cell of record.
- §2.6: the cash of record, as the derived engine NAV already used it (the retired plan's §2.0, which v1.0 did not carry).
- §3.7(4): the sheet sizes whole shares; Zak may execute the same dollars as a fractional order, and the fill is the record.
- §4.1: the job table lists what runs, including `shadow`, `notify`, the retry, the census, `backup` and `law`.
- §4.4: the reconciliation gauge reads the book against the ledger every night; the broker statement's age is shown, never coloured.
- §4.5: the nightly quarantine's two numbers, adopted as the code runs them.
- §5.6: two errata — ADDV's adjusted-close basis, and how the newest session is read.
- §6: Phase 0 completed; the shadow stays as a standing attestation.
- §3.4: v1.1's transitional clause has closed — the score job sizes to deployable TFSA cash and never printed a park buy — and its sentence is removed.
- Not adopted, open for Zak: dust after an exit (a position under one share), dropping the retry's second chain on a green night, and three tranche questions §2.3 leaves undecided (the window of a "~" date, when an unused week counts as skipped, calendar or rolling month).

---

## §8 — Glossary

**Engine** — the ranked five-slot book of §3. **Engine NAV** — the TFSA's engine capital: slots + park + TFSA cash; reserve (§2.2) and levered (§2.3) holdings are outside it. **Gate** — the SPY/SMA200 latch of §3.4. **Park** — where engine capital sits while gated off: USD cash in the TFSA (interim, v1.1); SPY.US in the cell of record. **Reserve** — SPMO/VXC.TO per §2.2. **Cell of record** — the exact backtest configuration whose code governs live behavior. **Print** — an actual executed trade on the tape; "no print" means the order never executed that session. **Shadow** — §6.4. **Freeze** — §5.5. **The three numbers** — §3.1, quoted together or not at all. **The law** — this file, as published to `v_law` (§0.7).
