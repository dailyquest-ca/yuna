# yuna_plan.md — v1.0

**Status: LAW. Promoted by Zak, 2026-08-15. This is the sole authoritative document; where any other text disagrees, this document wins.**

---

## §0 — Governance

**0.1 The plan is law.** This document governs everything Yuna does. If the plan and a habit disagree, the plan wins. If the plan is wrong, the plan gets amended — it does not get ignored.

**0.2 Division of rule.** Zak alone rules the law, the risk posture, the leverage, and executes every order. Yuna rules names inside the plan's gates and never places or simulates a trade execution. Ambiguity escalates to Zak; it is never resolved by improvisation.

**0.3 Law-change discipline.** Every edit to this document is announced with exact old and new lines. Zak rules on each before promotion. Yuna may draft; only Zak promotes.

**0.4 The one-read law.** Every interactive session reads `v_session_payload` once from Supabase, then judges. Scores, ranks, and gate states are never recomputed by hand in chat. A stale or red pipeline means no new tickets. Gate-off exit sheets are never blocked by pipeline color (§5.4).

**0.5 Credentials.** No credentials, API keys, or tokens ever appear in chat. Secrets live only in GitHub Actions repository secrets (`dailyquest-ca/yuna`). Any secret that touches a chat is rotated immediately.

**0.6 Record-keeping.** Rulings, tickets, book history, and run records are never deleted. The database and git carry the full history for audit.

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

---

## §3 — The engine

**Cell of record: `b5_12_2_L1_3` · run 589 · code stamp `235bef5fd174dcab` · park SPY.US · regime source SPY.US.** The engine's authority is the code at that stamp. Where any document and the code disagree, the code is authoritative and an erratum is recorded.

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
- Latch: 1 red session → OFF · 3rd consecutive green session → ON. If the gate cannot be evaluated on fresh data, it reads OFF.
- **Gate OFF:** the entire book sells at the next executable open; queued exits clear; all proceeds to park (SPY.US). No buys of any kind while OFF.
- **Gate ON (after latch):** normal operation resumes; seeding/refill per §3.5.

**3.5 Book mechanics.**
- **Slots:** 5, equal weight. Position size = engine NAV ÷ 5, marked at the decision close; fills occur at the next open (drift accepted).
- **Exit:** a holding ranked below 12 queues that night and sells at the next open; a no-print retries nightly until filled.
- **Displacement:** if the best unheld name in the top 2 ranks strictly better than the worst holding — swap. At most one displacement per session.
- **Free slots:** fill from the top 12 by rank. Multiple slots may fill in one session. Seeding fills all five in one session.
- **Cash sequencing:** sells execute first, buys the same morning on unsettled proceeds. Shortfall draws from park; residue returns to park. A buy that gets no print (no executable trade that session — e.g., a trading halt at the open) is cancelled, not retried; the slot refills from the next ranking. Exits are obligations; entries are options.
- **Participation cap:** an order may not exceed 0.98 of the name's ADDV — a correctness check, not a live constraint at current size.

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
| Sizing | NAV ÷ 5 at decision close |
| Participation | ≤0.98 ADDV |
| Park | SPY.US |
| Regime source | SPY.US |

**3.7 Sim-vs-live divergence register.** Accepted, in writing:
1. Gate-off: sim sells at the same session's close; live sells at the next open (~35 crossings/20yr; that overnight is unmodeled).
2. Sizing marks at decision close; live fills at next open — drift accepted.
3. Dual-listed / share-class twins inside the top 12: hold at most one of a pair; prefer the higher-ADDV line.
4. Fractional shares where the broker supports them; otherwise round down, residue parks.
5. Data revisions: adjusted-close restatements can move a replayed rank; the shadow (§6.4) compares same-vintage data only.

**3.8 Known limitations (quoted with the engine, always).** The verdict is unproven by our own bar. Twenty years of tape contains exactly two crash shapes; the engine has never been shown a grinding multi-year decline, and its edge is derived from V-shaped recoveries. The park is SPY: gated-off capital rides the index down (2008 modeled: −37.3% while gated). Five vol-adjusted momentum slots are ~2.5 independent bets, one mechanism. Modeled costs: $132,055 across 752 trades. A −61% drawdown has never been tested against a human.

---

## §4 — Pipeline & data

**4.1 Jobs (nightly, exchange sessions).**

| Job | Does |
|---|---|
| `ingest` | EOD bars for the universe + SPY |
| `score` | §3.2–3.5 logic: screen, rank, gate, queue, order decisions |
| `compose` | The order sheet + morning brief payload |
| `check` | Gauge suite (§4.4) |
| `reconcile` | Broker state vs book table, post-execution |

Weekly: the Saturday letter (clinical: gate, rank stability, DD status, divergences, learnings, NAV vs the §1 destination).

**4.2 The payload.** `v_session_payload` carries: gate state & latch, current book with ranks, the nightly order sheet, top-12 with scores, the exclusion table, NAV & DD status, levered facilities & tranche schedule, pipeline freshness, learnings. It is the single read of every session.

**4.3 Orders & tickets.**
- The nightly sheet is the only source of engine orders. Zak executes at the open: market orders (sells first, then buys). **No GTC orders exist anywhere in this system.**
- Ticket states: proposed → approved → executed → reconciled. Yuna writes rows; Zak's execution is the event; reconcile closes the loop with the receipt.
- Amber/red pipeline: no new buy tickets. Gate-off exit sheets dispatch regardless of pipeline color — the gate's own data is its authority, and if that data is missing the gate already reads OFF (§3.4).

**4.4 Check suite.** Gate reproducibility from raw bars · screen survivor count within historical band · rank reproducibility on same-vintage data · order sheet completeness & sizing arithmetic · book-vs-broker reconciliation age · data freshness. Any red holds buys; nothing holds exits.

**4.5 Data.** EODHD end-of-day bars (adjusted close carries splits/dividends) for US common stocks + SPY, plus exchange symbol lists and delisted lines. **Required product: EOD Historical Data — All World.** No fundamentals, news, intraday, or calendar feeds are read by any decision. Plan downgrade executes after §6.3 retires legacy jobs; billing is Zak's outside this law.

---

## §5 — Operations

**5.1 Sessions.** The morning brief renders: freshness · gate & latch · the order sheet · book with ranks & P/L · DD status vs milestones · tranche schedule status. Judgment happens in chat; arithmetic happens in the pipeline. Zak asks in plain words; no command vocabulary exists.

**5.2 Drawdown milestones — information, never action.** Pager at **−10%** engine DD; informational lines at −20 / −30 / −40 / −50. **No mechanical intervention exists at any level.** Any intervention is Zak's explicit ruling in chat. This is the design, chosen with the three numbers in view.

**5.3 The learning loop.** Observations → learnings with required falsifiers → proposals → Zak's ruling → promotion or expiry. No rule changes ship without this path.

**5.4 Protective actions.** Gate-off exits and rank-exit sells are protective-direction and are never blocked — not by freeze, not by amber, not by any throttle.

**5.5 Freeze.** Zak may halt buying at any time, in any words; that state is a freeze. A freeze halts all buys (entries, refills, displacement buys, levered tranches). Exits fire normally; proceeds park. Lifted only by Zak's word.

**5.6 Erratum register.** Where engine documentation disagrees with the code of record, the code wins and the erratum is logged (standing entry: 2026-08-15, free-slot fill band is top-12; earlier engine research documentation said otherwise).

---

## §6 — Phase 0: Deployment (one-time; self-archives to the changelog on completion)

**6.1 Liquidation & first draw (Zak, at Wealthsimple).**
1. Cancel all resting orders — every GTC, stop-limit, and pyramid order, without exception.
2. Sell at market: ANET 40 · NVDA 40.0437 · TSM 15.1647 · NUE 32 · ISRG 26 · AVGO 30.0964 · CNQ.TO 142. (Names appear here as positions-to-liquidate only.)
3. Same session: TFSA proceeds → SPMO (bridge) · RRSP cash → SPMO · CNQ proceeds → repay LOC $7,980, residue → VXC.TO.
4. Tranche one ($12.5K → VXC.TO) may execute the same morning, independent of the sells — it does not wait on proceeds.

**6.2 System close-out (Yuna, at score-green).** Sell rows for all seven; void all open tickets; retire all armed rows; close the book table to zero with a paper trail reconcile can read; close the six brewing learnings as *retired with engine*.

**6.3 Build (work orders, repo).** Retire legacy jobs from the schedule · implement the nightly score job from the code of record · compose the order sheet & rebuilt payload · check suite (§4.4) · shadow harness (§6.4) · downgrade the data plan to EOD Historical Data — All World once legacy jobs are retired.

**6.4 Shadow — 10 sessions.** The pipeline runs live producing order sheets nobody trades. Each night: live output vs the sim's decision on the same-vintage bars, attested in writing. Pass = 10/10 matches, or every divergence named and ruled. Capital waits in SPMO throughout.

**6.5 Seed.** Conditions: shadow passed · pipeline green · **gate ON** · Zak's seed ruling in chat. Then all five slots fill from the first live ranking in one session. If the gate is OFF when the shadow completes, capital holds in SPMO until the first ON latch, then seeds.

Target: ~mid-September 2026.

---

## §7 — Changelog

**v1.0 — 2026-08-15 — Founding law. Promoted by Zak.** Establishes: a single momentum engine (cell of record `b5_12_2_L1_3`) housed entirely in the TFSA; accounts-as-allocation with no percentage targets; reserve layer SPMO (RRSP) and VXC.TO (NONREG); a levered layer hard-capped at 50% of the LOC limit with a three-tranche gate-conditional ramp; deployment via Phase 0 — liquidation → build → 10-session shadow → seed, target mid-September 2026. Park is SPY per the cell of record; a T-bill park variant is a research work order, promoted only on evidence. Drawdown milestones are informational only. Exclusions are data-hygiene only. No stops, no GTC orders, no command vocabulary.

---

## §8 — Glossary

**Engine** — the ranked five-slot book of §3. **Gate** — the SPY/SMA200 latch of §3.4. **Park** — SPY.US, where engine capital sits while gated off. **Reserve** — SPMO/VXC.TO per §2.2. **Cell of record** — the exact backtest configuration whose code governs live behavior. **Print** — an actual executed trade on the tape; "no print" means the order never executed that session. **Shadow** — §6.4. **Freeze** — §5.5. **The three numbers** — §3.1, quoted together or not at all.
