# Yuna — Zak's Trading Agent

**Status: All sections FINAL — 2026-07-30. Changes only by announced edit.**
**Opened:** 2026-07-29
**Owner:** Zak (decisions, execution) · Yuna (research, ranking, tickets)
**Rule:** Nothing is FINAL until Zak signs off on that section. One section at a time.

---

## Section 1 — VISION ✅ **FINAL** (2026-07-29)

> I'm building an AI-run research and automation operation that lets me build serious wealth while running a day job. The machine watches the entire US market and brings me the highest-conviction opportunities with a game plan and a recommendation already attached. I review, decide, and execute.
>
> I play the edge I actually have. I can't compete on speed of data or information — those are lost games against better-equipped people. What I can do is buy smaller companies that large funds aren't able to touch, and hold through rough water while they're being forced to sell. And I concentrate deliberately: seven to nine positions, nothing under 4%, because concentration is the only thing that produces this kind of return, and a position too small to matter is just noise that costs attention.
>
> The active book runs two sleeves that make money by different mechanisms. In **Compounders** I own businesses — a handful of exceptional companies with long reinvestment runways, held for years, sold when the thesis breaks and not when the price falls. This is where a hundred-bagger actually happens, and it happens by holding rather than by picking. In **Momentum** I rent trends — the strongest names in the strongest groups, held for weeks or months, sold the moment they stop leading. Here the price is the thesis, so there's no loyalty and no averaging down. Both sleeves hunt small caps as well as large, because that's where being small is an advantage rather than a limitation. Separately, borrowed money funds a levered position in the non-registered account — a single name only when conviction is exceptional, a diversified unhedged ETF whenever it isn't. When it funds an active name it counts in the book; when it funds the ETF it's a bonus track scored on its own.
>
> Thirty percent a year is the target, not a rule. I can't control returns, only process quality, so the number's job is diagnostic: miss it modestly and the market was hard, miss it badly and the process gets reassessed. The point is to be as wealthy as possible in twenty years, which means protecting the compounding above all else. That means accepting the drawdowns that come with owning great things and refusing the ones that come with holding broken ones — the question is never whether the price is down, it's whether the thesis is intact. I don't trade other markets, crypto, meme stocks, hype, or intraday; positions are entered with a minimum intended hold of one week — protective and failed-signal exits are always exempt. Options and shorting wait behind a written gate. Callable leverage is capped at 50% utilization and is never increased into strength. Every pass and every exit is recorded as a plain observation; observations become rules only once they've earned it, and rules that stop earning their place get deleted.

---

## Section 2 — PORTFOLIO ARCHITECTURE ✅ **FINAL** (2026-07-29)

All weights are percentages of NAV. NAV = equities + cash − debt.

### 2.0 NAV & capital accounting

**NAV = all assets across all accounts, at market, minus all debt, converted to CAD.** This is the compounding number and the only scorecard — the 30% bar measures NAV.

- **Borrowing is NAV-neutral at the moment of use.** Draw $50K and buy $50K of ETF: assets +$50K, debt +$50K, NAV unchanged. Every subsequent gain or loss on that position flows to NAV. The levered layer has no separate scoreboard.
- **The sleeves divide NAV.** Sleeve weights (60/40) and position caps (4% floor · 25% single-name entry) are measured on NAV.
- **The levered layer sits outside the sleeves** — a third bucket funded by borrowed money, governed by the §2.5 facility rules, not by sleeve percentages. Its holdings don't consume sleeve room or count against the single-name cap. This is what lets gross exposure exceed 100% by design.
- **Exception — independence and theme caps see the whole book**, levered positions included. Correlation doesn't care whose money paid. Three AI names in the sleeves plus a tech-heavy levered ETF is real concentration, and the check counts it.
- **Balances are truth, prices are the extrapolation.** Sunday reconciliation captures per-account cash and positions plus available credit on each facility (Zak reads them off Wealthsimple, or tells Yuna in chat). Deposits, dividends, and interest are absorbed automatically without modeling them individually. Weekday NAV extrapolates from the last confirmed balances using price moves — provisional, labeled, trued up Sunday.
- **Every ticket names an account**, and is only written if that account holds the cash — or, for the levered layer, the available credit — to fill it. NAV-level sizing, account-level execution.

### 2.1 Sleeves

| Sleeve | Weight | Names | Entry size |
|---|---|---|---|
| **Compounders** | 60% | 4–5 | 12–15% |
| **Momentum** | up to 40% | 3–4 | 8–12% |
| **Cash** | residual | — | — |

The 40% is a ceiling, not a quota. Momentum fills to conviction. Three names at 10% is a complete sleeve.

Compounders don't flex — this sleeve should be full nearly always. Momentum does.

Total: **7–9 positions.**

### 2.2 Independence

Correlated names are one bet. Four names at 0.85 correlation is 1.1 independent bets.

- Maximum **2 names per industry group**
- No single theme above **35% of NAV** — **entry-only**: no new capital enters a theme above 35%. A winner that grows past 35% is not forced out.
- Target **4–6 effective independent bets**

### 2.3 Position sizing

- Minimum position **4%** — applies to intended full size
- Single-name ceiling **25%** — entry-only
- Size bands govern entry. Winners are not trimmed for outgrowing their band.
- Risk = position size × distance to stop. Sizing is compared on risk, not dollars.

### 2.4 Drawdown tolerance

| | Compounders | Momentum |
|---|---|---|
| Exit trigger | Thesis break | Loss of relative strength |
| Price tolerance | Wide | Tight |
| On a fall | Check the thesis | Price is the thesis — exit |
| Averaging down | Permitted — CCN ≥ 70 and below hurdle | Never |

Stop widths and trail mechanics are set in Phase 7.

### 2.5 Leverage

| Facility | Limit | Funds |
|---|---|---|
| **Callable margin** | 50% utilization | ETFs only |
| **Secured LOC** | 50% utilization | Single names at CCN ≥ 85, or ETFs |
| **HELOC** | Full | Single names at CCN ≥ 85, or ETFs |

- Callable facilities are never increased into strength. HELOC is exempt — it isn't callable, and a readvanceable mortgage grows by design.
- Levered ETFs are **unhedged** and **CAD-listed**.
- Levered positions don't consume active-book slots. A levered ETF is not one of the 7–9.
- All returns land in NAV and count toward the 30%.

**Implied exposure at full use:** LOC 50% + $25K margin + $100K HELOC ≈ 177% gross. A −40% market takes $200K NAV to roughly $58K.

### 2.6 Account placement

| Account | Holds | Why |
|---|---|---|
| **TFSA** | **All of Momentum** + Compounders' primary home | Tax-free turnover is the momentum edge; a tax-free 100-bagger is the compounder dream. US dividends leak 15% here — minor on low-yield growers |
| **RRSP** | Compounder satellite — idle cash deploys here; any higher-yield US compounder prefers it | Suits multi-year no-touch holds; US dividend withholding treaty-exempt |
| **Non-registered** | The levered layer **only** — LOC / HELOC / margin per §2.5 | The only account where leverage exists and interest is deductible |

- Sleeve weights are measured on **total NAV across all accounts** — placement never changes the math.
- **Momentum lives in one account only** (TFSA) — stops across accounts is pain for zero benefit.
- New contributions route **TFSA → RRSP → non-registered**.
- Borrowed money never funds a registered account — the interest deduction dies at that line.
- **Accepted cost:** TFSA losses burn contribution room permanently. Momentum takes small losses by design; expected value still favours the TFSA, but the asymmetry is real.

### 2.7 Non-conformance (2026-07-29)

| Issue | Status |
|---|---|
| Four AI-complex names — exceeds 2 per group | Breach |
| Theme ~76% of invested equity | Breach |
| MU, VRT, GOOGL below the 4% minimum | Breach |
| CNQ — location conforms (§2.6 levered layer); open question is CCN ≥ 85 | Review |
| 29.8% deployed | Phase 0 |

---

## Section 3 — FINDING & CHOOSING ✅ **FINAL** (2026-07-29)

Two pipelines. They share only the raw universe.

**At a glance:**

| | **Compounders** | **Momentum** |
|---|---|---|
| What we buy | The business | The trend |
| Candidates | 40–60 bench · monthly | 100–150 · weekly |
| Gates | Quality floor (computed) · Business model (judgment) | Market stage · Trend template · Setup · Earnings |
| Score | CCN v1.0 | MCN v1.0 |
| Entry signal | Price ≤ hurdle (checked daily) | Pivot break on volume |
| First position | Full size | 50%, pyramid to full |
| Add on | Weakness below hurdle | Strength above pivot |
| Stops | None | ≤ 8%, ratchet up only |
| Market gate | None — weakness is opportunity | Stage 2 required |
| Exit measured | **Absolute** — vs entry snapshot | **Relative** — vs the field |
| Review | Annual re-underwrite | Weekly re-rank |

---

### 3.0 Layers & cadence

| Layer | What | Size | Rebuild |
|---|---|---|---|
| **L0** | Investable universe | ~1,500 | Monthly |
| **L1-C** | Compounder bench | 40–60 | Monthly |
| **L1-M** | Momentum candidates | 100–150 | Weekly |
| **L2** | Active queue, triggers pre-written | 15–20 | Weekly |
| **L3** | The book | 7–9 | Live |

**L0 filters:** common stock on NYSE, NASDAQ, or NYSE American (no OTC) · price ≥ $5 · **ADDV** (average daily dollar volume = shares × price, 50-day median) ≥ $10M · market cap ≥ $300M · listed ≥ 6 months · delisted names retained for backtesting.

**L2 composition:** top-10 MCN names in BUY or near-BUY state + every bench name within 10% of its hurdle + all current holdings. Cap 20 — holdings always included; remaining seats by trigger proximity, then score.

**Score semantics:** all components are cross-sectional percentiles within L0 at run time — scores are relative and move when others move. Relative scores govern entry, ranking, and displacement. Compounder exits are judged **absolute**, against raw component values snapshotted at entry (§3.1). Momentum exits stay relative by design (§3.2).

Runs cascade upward — lower tiers first, each feeding the next.

| When | Runs |
|---|---|
| **Daily** pre-open | L3 stops & trails · L1-C hurdle check · L2 trigger check · market gate · event scan |
| **Weekly** (Sat) | Group RS → L1-M rebuild → MCN → L2 re-rank & rewrite triggers → workups on top 3 |
| **Monthly** (1st weekend) | L0 rebuild → compounder funnel (§3.1) → **Gate approvals** → audit |
| **Annual** | Re-underwrite per compounder — Gate C2 answered from scratch, invalidators re-set |

A compounder is touched at three speeds: **daily** (hurdle, invalidators, gaps) · **every filing** (CCN recompute, snapshot comparison, sub-55 memo) · **annually** (the human re-underwrite — deliberately rationed, because frequent deep reviews are how investors talk themselves out of their best positions).

The CCN only genuinely moves when a company **files**. The monthly run refreshes membership and ranking; real score changes arrive as filing events through the interrupt layer.

**Event interrupts**

| Event | Affects | Action |
|---|---|---|
| Earnings released — holding | L3 | Recompute score · check invalidators |
| Earnings released — bench/queue | L1, L2 | Recompute · re-rank |
| New 10-Q / 10-K filed | L1-C, L3 | CCN recompute · confidence check |
| Earnings due ≤ 5 trading days | L2, L3 | Blackout — no new entries, no adds, both sleeves |
| Gap ±7% open vs prior close | L3 | Stop check · thesis check |
| **Market gate flip** | L2, L3 momentum | Sleeve to cash, or reopen |
| Stop or trail fires | L3 | Exit ticket, same day |
| Price crosses a compounder hurdle | L1-C → L3 | Add / entry ticket |

---

### 3.1 Compounder pipeline

Bench built **half smaller-cap, half larger-cap by mechanism**: the funnel takes the **top 30 by CCN from each size cohort** (boundary: **$10B** market cap, a Config value). Final picks are pure number — the book may end up all-small or all-large if the numbers say so.

**Monthly funnel — cheap computed steps first, expensive judgment last, on the smallest set:**

1. L0 refresh
2. **Gate C1 — Quality floor** (computed, pass/fail)
3. **CCN** computed and ranked for all C1 survivors
4. **Gate C2 — Business model** (judgment): Yuna writes a memo on the top ~100 by CCN
5. **New** candidates for the top-60 bench go to Zak with memos attached
6. Zak approves or rejects → approved names join the bench
7. Evictions applied per the seatbelt rules → listed in the monthly digest

**Gate C1 — Quality floor** *(computed)*
- Positive free cash flow
- Growth funded internally: net share issuance ≤ 2%/yr (3-yr avg) · net debt not growing faster than EBITDA
- Leverage: net debt / EBITDA ≤ 2.5×
- Banks and insurers excluded in v1 (EBITDA is meaningless for them)
- Goodwill jumps don't fail the gate — they route a serial-acquirer flag to the C2 memo

**Gate C2 — Business model** *(judgment · logged)*
Does scale make this company stronger? Does it share gains with customers to widen the moat? Where does the next dollar of retained earnings go, and what does it earn?
Proxy inputs: gross margin stability · market share trend · incremental margin · revenue per employee trend.
Every memo and every decision logged as an observation.

**CCN v1.0 — equal weight, 0–100** *(components are L0 percentiles)*

| Component | Weight | Definition |
|---|---|---|
| Compounding engine | 33% | ROIC × reinvestment rate, 3-yr smoothed. Requires ≥ 3 fiscal years, else → data-confidence path |
| Cash conversion | 33% | 3-yr FCF ÷ 3-yr net income |
| Size | 33% | Percentile of log market cap, inverted — smaller scores higher |

**Formulas:** NOPAT = EBIT × (1 − effective tax) · Invested capital = debt + equity − cash · Reinvestment rate = (capex − D&A + ΔWC) ÷ NOPAT, floored at 0, capped at 150%.

**Engine reliability check:** growth = ROIC × reinvestment is an identity. Compute the engine from cash-flow components, compare to observed revenue growth — agreement = trustworthy, divergence = flag, never silently score. Run ROIC with and without goodwill; same quintile = high confidence.

**Entry hurdle v1.0** — separate from the CCN, computed daily per bench name:

> **Expected return at price P = FCF yield + engine growth − derating drag**
> - FCF yield = TTM free cash flow ÷ market cap at P
> - Engine growth capped at **25%**
> - Derating drag = annualized 5-yr slide from current P/FCF down to the **fair multiple** = lower of the stock's own 5-yr median P/FCF or **30×**. Names with < 3 yrs of history: fair = lower of current or 25×
> - The drag is **never a credit** — cheapness earns no bonus. The margin of safety lives here
> - **Hurdle price = highest P where expected return ≥ 15%/yr**

15% is an underwriting floor, not the expectation — growth is capped and rerating earns nothing, so what underwrites at 15% has historically realized above it. Analyst target prices are never an input (documented optimism bias); they serve only as a data-sanity flag when our hurdle diverges wildly from the street.

**Sizing:** CCN 70–84 → **12%** of NAV · CCN 85+ → **15%** · flat 12% until the shadow book validates the scores · capped by the sleeve ceiling — the last name entered sizes to the remaining room. Full position in a single order at or below the hurdle.

**Adding / averaging down — permitted.** CCN ≥ 70 and price below hurdle: 5–15% below → add 25–50% of original size · > 15% below → up to 100% · max 2 adds per name per 12 months (crash-protocol tactical adds exempt) · the 25% single-name entry ceiling still applies.

**Entry snapshot:** at purchase, raw component values (engine, cash conversion, margins) are recorded. Exits are judged against this snapshot — **absolute, not relative.**

**Exits:**
- CCN < 55 → review memo from Yuna within 48h: raw-vs-snapshot comparison, invalidator check, recommendation. Zak decides. "The universe improved, the business didn't move" is a documented **hold**. Never an auto-sell.
- 3–4 named event invalidators written at entry (CEO exit, regulatory break, anchor-customer loss…)
- **No trailing stops. No market gate** — weakness is the opportunity.

**Bench eviction seatbelts:** gate failure evicts immediately. Rank eviction requires **two consecutive months** outside the top 60 — and never applies to current holdings or names within 10% of their hurdle. All evictions listed in the monthly digest.

**Rejected names:** 12-month cooldown before re-proposal, unless a new filing moves the CCN by ≥ 10 points.

---

### 3.2 Momentum pipeline

**Where each gate applies:**

| Gate | Level | Checked |
|---|---|---|
| **M1 — Market stage** | Sleeve master switch | Weekly close; enforced at entry time |
| **M2 — Trend template** | Per-name candidacy | Weekly rebuild |
| **M3 — Setup** | Per-name state (BUY / WAIT) | Daily trigger check |
| **M4 — Earnings acceleration** | Per-name candidacy | Weekly rebuild |

**L1-M membership = M2 + M4 pass, ranked by MCN, top 150.**

**M1 v1.0 — Market stage (Weinstein):** S&P 500 Friday close above its 30-week average **and** the average no lower than 4 weeks ago → ON. Friday close below the average → OFF. Weekly closes only — no intraday flips. The gate is a **latch** — it holds its state until the opposite condition fires (price above a *falling* average changes nothing). "Friday" = the last trading day of the week. Whipsaw in choppy tapes is the accepted cost; every flip is logged as an observation.

**M2 — Trend template:** above the 150 & 200-day · 150 above 200 · 200-day rising (above its value 21 sessions ago) · above the 50-day · ≥ 30% off the 52-week low · within 25% of the 52-week high.

**M3 — Setup:** Stage 2 breakout from a valid base — base ≥ 25 sessions long, ≤ 25% deep, **pivot = highest high of the base** — on breakout-day volume ≥ 1.4× the 50-day average.

**M4 — Earnings acceleration:** latest reported quarter YoY EPS growth ≥ 25%, **or** accelerating for two consecutive quarters with the latest ≥ 15%.

**MCN v1.0 — equal weight, 0–100** *(components are percentiles; all ranking windows end 10 trading days ago)*

| Component | Weight | Definition |
|---|---|---|
| Momentum quality | 33% | 90-day exponential regression slope of log price, annualized · × R² of the same regression · ÷ 90-day volatility |
| Setup proximity | 33% | Equal-weight of 4 sub-scores: ATR percentile vs own 1-yr range (inverted) · pullback-depth contraction · volume dry-up through the base · proximity to 52-week high |
| Industry group strength | 33% | EODHD industry classification · equal-weighted 6-month group return · percentile across groups |

**Gates and stops always use current price. Rank is calm; protection is real-time.**

**States:** **BUY** — valid pivot exists; entry at pivot, stop below the base. **WAIT** — extended; trigger pre-written for the next base.

**Pyramiding schedule:**

| Step | Trigger | Add | Cumulative |
|---|---|---|---|
| 1 | Pivot break on volume | 50% | 50% |
| 2 | +2–3% above pivot | 25% | 75% |
| 3 | +4–5% above pivot | 25% | 100% |
| — | Beyond +5% | Nothing — wait for the next base | — |
| Full | — | Stop moves to breakeven | — |

One gap-up completion at market is permitted if price is within ~5% of the pivot.

A pyramid stalled below full size for 4 weeks either completes on the next base or exits — no permanent sub-scale positions.

**Stops:**
- Initial: higher of the base's final-contraction low, or entry − 8%. **Never wider than 8%.**
- Ratchet: full size → breakeven · +15% from average cost → trail 10% below highest close · stops ratchet up, never down.
- **Euphoria rule** — tighten, never sell: when price closes > 2 standard deviations above its own 50-day (std dev of closes, 50-day window), **or** on the largest single-day % gain since entry → trail tightens to **5%** below highest close.

**Sizing:** conviction sets the risk budget — **0.7% of NAV** at MCN 70–84, **0.9%** at 85+ (first quarter runs 0.5% / 0.7% per the start-low rule) · stop distance is the divisor · **size = budget ÷ stop**, capped by the Section 2 bands and by the sleeve ceiling — the last name entered sizes to the remaining room.

*Why these numbers:* the budget is how much NAV is lost if the stop fires. Wide stop → smaller position; tight stop → bigger. At an 8% stop these budgets yield ~8.8% and ~11.3% positions — inside the band, so the formula genuinely governs; genuinely tight stops still clip at the 12% ceiling. Four momentum names stopping out together costs ~3.6% of NAV. During the validation quarter the reduced budgets may size below the 8% band floor — the start-low rule overrides the floor; the 4% NAV minimum still binds.

**Exits — relative by design:** stop fires · trend template fails · MCN < 55. We rent the strongest; if others got stronger, that *is* the thesis decaying.

---

### 3.3 Shared rules

**Thresholds:**

| Score | Meaning |
|---|---|
| ≥ 85 | Full conviction — top of size band |
| 70–84 | Enterable — low end of band |
| 55–69 | Hold zone — no new money |
| < 55 | Exit review |
| +10 | Margin a challenger needs over an incumbent to displace it |

Displacement is **within-sleeve only** — a momentum 85 never displaces a compounder 72. If a trigger fires while the sleeve is full, the challenger needs +10 over the **weakest incumbent**; the swap ticket is auto-drafted, Zak executes both legs.

**Earnings blackout:** no new entries and no adds within 5 trading days of a scheduled report. Both sleeves. Entering the window also **cancels any live entry or add orders at the broker** (the stop sheet says so); protective stops remain, always.

**Data confidence:** never assume a missing value — drop the component, renormalize remaining weights to 100, mark the name as scored on 2 of 3. An incompletely-scored name is capped at the bottom of its size band and requires manual sign-off.

**Data discipline (non-negotiable):** fundamentals used as of **filing date**, never fiscal period end. Delisted names retained in the universe.

**Order execution:** positions are taken in single decisive orders at computed levels. Momentum adds on strength only, per the pyramid schedule. Compounder adds trigger only below the hurdle. Time-spaced tranches exist in exactly one context — the crash protocol. Legging in over days is permitted for illiquid names as execution mechanics.

**Crash protocol:** market gate shuts → momentum stops fire, sleeve to cash → compounder hurdles breach and adds fire in **time-spaced tranches — 3 tranches, minimum 10 sessions apart** → freed momentum capital may fund compounder adds beyond standard sizing, tagged **tactical** at purchase → when the gate reopens, tactical lots are the funding source for momentum re-entry. **Core lots are never touched.** No cap on tactical allocation.

**Dual qualification:** a name passing both screens goes to Compounders. Longer horizon wins.

**Shadow book:** every pass and every exit snapshots score + price, marked at 30 / 60 / 90 days. Mechanics in Phase 8.

**Versioning:** CCN v1.0 · MCN v1.0 · Hurdle v1.0 · M1 v1.0. Changes increment and are logged so later versions can be measured against earlier ones. All formulas are **version 1 of an experiment** — a reasoned prior, not evidence. The shadow book converts one into the other.


---

## Section 4 — MECHANICS & BUILD 🔵 **DRAFT — awaiting Zak review** (2026-07-29)

**Design principle: jobs compute · database remembers · Yuna judges · Zak acts.** No number lives in anyone's head between sessions.

### 4.0 Architecture — the map

| Box | In one line | Full detail |
|---|---|---|
| **Data** | EODHD All-In-One: bulk prices nightly · FX · fundamentals on filing · earnings calendar. Bars kept 3 years, fundamentals forever | → §4.1 |
| **Compute** | Five GitHub Actions jobs: `nightly-ingest` · `nightly-retry` · `weekly-rank` · `monthly-funnel` · `monthly-backup` | → §4.2 |
| **Store** | One Supabase Postgres project — 11 tables (universe → book → briefs) + human views for browsing | → §4.3 |
| **Judge** | Five Yuna sessions: evening stop sheet · pre-open brief · Sat deep-dive · Sun reconciliation · monthly approval. Prompts live in Section 5 | → §4.4 |
| **Execute** | Zak places every order: entry pairs · stop moves · gap exits · fill confirmations · monthly approvals | → §4.5 |
| **Protect** | GTC stop-limits living at Wealthsimple — protection that never sleeps with the pipeline | → §4.6 |
| **Health** | Heartbeat: every job logs a run · every output opens with freshness · a missing message is the alarm | → §4.7 |

§4.1–4.7 describe the running machine in this order. §4.8 covers how it gets built, §4.9 the risks we accept. The glossary for the whole plan sits at the end of the document.

### 4.1 Data

**EODHD All-In-One** — monthly USD $99.99 first, annual ($83.33) once the machine is earning · ≈ CAD $143 / $120 · ~0.8%/yr of NAV · the kill switch stays monthly until proven. SEC EDGAR retained as the engine-reliability cross-check. License is personal-use; productizing later needs their commercial tier.

| Feed | What | Cadence |
|---|---|---|
| Bulk EOD | The whole US market's daily bars in one request | Nightly |
| Index | S&P 500 (`GSPC.INDX`) for the M1 market gate | Nightly |
| USDCAD | FX for CAD NAV — every CAD figure carries its rate and `as_of` | Nightly |
| Splits & dividends | Corporate actions → trigger per-name history refresh | Nightly |
| Fundamentals | Full statements per name — pulled only when a company files | On filing (~quarterly per name) |
| Earnings calendar | Report dates for the blackout and interrupts | Weekly |

**API budget** (100,000 calls/day · 1,000 requests/min):
- Prices in bulk — ~a few hundred calls nightly regardless of universe size, never 1,500 per-ticker pulls.
- Fundamentals cached by filing date — steady state ≈ 1,200 calls/week. **Computation never calls the API** — every score reads the database.
- Backoff-then-amber on rate-limit errors (exponential, max 3 retries, then run from cache; heartbeat shows it).
- Every run meters its calls via EODHD's usage endpoint; the brief alarms past ~70% of daily quota.
- Cold start — full backfill via **per-ticker history calls** (one per name, each returning full history — not 750 bulk-day calls) + fundamentals sweep of L0 ≈ 20k calls, one day, once.

**Residency & retention** — the store is the system of record; the API is a feed:
- Daily bars raw + adjusted, **3-year rolling window** (every formula needs ≤ 1 year; the buffer serves backtests). Older bars archived (compressed) to the repo before pruning.
- **Corporate-action refresh:** a split rewrites a stock's entire adjusted history — any split/dividend event triggers a one-call re-pull of that name. Without it, a 4:1 split reads as a −75% crash and fires false alarms.
- Bars stored for L0 members + holdings + retained delisted names only; a name entering L0 is backfilled on arrival (1 call).
- **Fundamentals kept forever — split by weight:** the ~20 extracted fields the formulas need live in the database (~1 KB per filing); the raw filing JSON is compressed into the repo. Same point-in-time asset, stamped with filing dates, without ballooning the free tier. The compounder side becomes honestly backtestable as a side effect of running.
- **Derived at cold start:** each name's historical quarterly P/FCF multiples, computed from the full backfill before pruning and stored with the fundamentals fields — the hurdle's 5-yr median never needs daily bars older than the window.
- **Filing detection:** a name whose earnings date has passed since its last pull is re-fetched on the next nightly; a monthly staleness sweep catches anything the calendar missed.

**Quarantine:** any print moving > 40% with no corporate action, or any print that would fire a sell-side action, needs **two sources to agree** (job re-fetch + live MCP quote) before anything acts on it. Quarantined rows are flagged in the next brief, never silently used.

### 4.2 Compute — the jobs

Five GitHub Actions workflows in the private repo. All idempotent (upserts — safe to re-run), all carry `DRY_RUN`, all write a heartbeat row (§4.7).

| Job | When | What it does |
|---|---|---|
| **`nightly-ingest`** | Mon–Fri **02:00 UTC** (≈ 6–7 PM PT) | Pull the day's bars (bulk) + FX + corporate actions → quarantine → recompute stops, trails, hurdles, market gate → update queue states → event scan (earnings ≤ 5 days, gaps ± 7%) |
| **`nightly-retry`** | Mon–Fri **03:00 UTC** | First step reads the runs table — exits if the night is already green, re-runs the ingest if not |
| **`weekly-rank`** | Sat **12:00 UTC** | Group RS → rebuild L1-M → MCN → re-rank the queue → rewrite triggers |
| **`monthly-funnel`** | 1st Sat **10:00 UTC** | Rebuild L0 → Gate C1 → CCN → funnel output for the approval session |
| **`monthly-backup`** | 1st Sat **14:00 UTC** | Dump of everything **except daily bars** (bars are a vendor-re-pullable cache), compressed and committed to the repo — the backup **and** GitHub's 60-day keep-alive in one |

**Clock convention:** stored and scheduled in **UTC** · planned around market time (**ET**) · quoted to Zak in **PT**. GitHub's cron ignores daylight saving while ET and PT shift together, so these UTC picks carry slack and are verified against **both** clock regimes — the ordering `nightly-ingest` → `nightly-retry` → 8:30 PM PT stop sheet → 6:00 AM PT brief holds year-round, with the reasoning commented in the workflow files. On the 1st Saturday the funnel runs before the weekly rank, so the week's rankings use the fresh universe.

### 4.3 Store — the database

One Supabase Postgres project. **Everything lives here, including L0**; the repo holds code, migrations, and backups. **Bloat rule: if no decision reads a field, we don't store it.** Two write modes: **overwrite** = current state only, replaced each run · **append** = a ledger, rows never edited. Column-level schema lives in the repo migrations — this table is the map, not the blueprint:

| Table | Holds | Mode |
|---|---|---|
| universe (L0) | ~1,500 names + filters | overwrite |
| bench | 60 names · CCN + components · hurdle · C2 status · approval | overwrite |
| candidates | 150 momentum · MCN · BUY/WAIT · pivot/stop | overwrite |
| queue | ~20 pre-written triggers | overwrite |
| book | Positions · lots (core/tactical) · stops · thesis + invalidators · entry snapshots | overwrite |
| tickets | proposed → approved → filled (provisional/confirmed) → cancelled | append |
| transactions | Every confirmed fill | append |
| observations | Passes, exits, gate flips, C2 calls · marked 30/60/90d | append |
| briefs | Daily/weekly/monthly outputs | append |
| nav_snapshots | Daily NAV, provisional until Sunday | append |
| config / runs | Weights, thresholds, versions (changes = rows) · heartbeat | append |

- **Human views** (`v_book`, `v_queue`, `v_bench`) shape what Zak browses in Studio — sorted, joined, readable.
- **Guard triggers** on computed tables (universe, candidates, bench, queue, book): writes are rejected unless made by a job. Sessions may write only briefs, tickets, observations, and config — "Yuna never computes scores by hand," enforced by the schema, not by promise.
- Free projects pause after ~1 week idle — nightly writes keep it alive; a week-long pipeline outage would pause the DB too (heartbeat screams days earlier; restore is one click).

### 4.4 Judge — Yuna's sessions

Five scheduled sessions. The full runbooks — the prompts — are **Section 5**. Every session reads the database, never computes scores by hand, and always produces output even when the news is "nothing."

| Session | When (PT) | What Zak receives | Runbook |
|---|---|---|---|
| **Evening stop sheet** | ~8:30 PM Mon–Fri | One line: `✓ stops all placed correctly` or the moves — `NVDA · stop 176.20 / limit 170.90` | R2 |
| **Pre-open brief** | ~6:00 AM Mon–Fri | Snapshot: freshness · NAV + move · fired/watch · broker-ready tickets · "**You:** …" — context below as needed | R1 |
| **Saturday deep-dive** | ~8:00 AM Sat | Gate + margin to flip · top/bottom groups · workups · performance vs the 30% bar | R3 |
| **Sunday reconciliation** | Sun morning · interactive | Fills confirmed against the broker record · NAV true-up · shadow-book marks | R4 |
| **Monthly approval** | 1st weekend · interactive | C2 memos · bench changes · anniversary re-underwrites · audit | R5 |

**Format law: summary first, context second.** Succinct by default, never at the cost of needed information — depth always on request, no hard word caps. Every output opens with the freshness line; **stale data ⇒ no new tickets.** All outputs stored in `briefs`.

### 4.5 Execute — Zak's part

Everything Zak ever does, in one list:

1. **Place entry pairs** — the buy stop-limit at the pivot + its GTC stop-limit, both prices on the ticket.
2. **Move stops** per the evening sheet — both prices given.
3. **Gap mornings** — check the position; still in the account → market sell at open (§4.6).
4. **Confirm fills** — say it in chat or flip the ticket; either writes the provisional row.
5. **Sundays** — provide settled Wealthsimple activity, per-account cash balances, and available credit on each facility (chat or ticket, whichever's easier).
6. **Monthly** — rule on C2 memos, bench changes, re-underwrites.

**Fill loop:** chat or flip → tickets row **provisional** → book updates that night → Sunday confirms against the broker's settled record (price / qty / FX). Weekday NAV runs on provisionals — drift is basis points, accepted and labeled. When Wealthsimple ships an MCP, step 4 automates and nothing else changes.

### 4.6 Protect — the reflex layer

The pipeline looks at prices once a night; an 8% stop can be breached by lunch. So protection lives **at the broker**: every momentum position carries a GTC stop-limit at Wealthsimple — limit = stop − 3% (Config `stop_limit_buffer`); GTC lasts 90 days there, and re-placing is Zak's own habit by choice. In nearly every stop event the order simply fills. The rare exception is a **gap past the limit** — price opens below the limit and the sell never fills: the brief flags it, and if the position is still in the account, **market sell at open**. Compounders carry no stops — hurdle alerts only.

### 4.7 Health — the heartbeat

- Every job writes one row to `runs`: job, started, finished, **stage-level status**, rows written, calls used, errors. A job that half-fails goes **amber**, not green — downstream sessions treat the affected domain as stale.
- All timestamps and `as_of` stamps are **UTC**.
- Every output opens with the freshness line: `data <date> close ✓ all green` or `⚠️ <job> failed — stale N days`.
- The evening one-liner doubles as the pipeline's nightly receipt.
- **A missing message is itself the alarm** — the briefs are pushes Zak expects; silence means something died. Stale data ⇒ no new tickets, protective moves only.

### 4.8 Build & security

| Phase | Builds | Unblocked by |
|---|---|---|
| **A** | Repo scaffold · core migration (runs, config, universe, prices) · nightly ingest · heartbeat | Extended (live now) |
| **B** | Momentum stack — M1–M3, MCN, queue states | A |
| **C** | Full schema migrations · briefs · scheduled sessions | B |
| **D** | Fundamentals stack — C1, CCN, hurdle, funnel, M4 | All-In-One live |
| **E** | Backtest job | B |
| **F** | Cutover — current book into the database · Section 6 Phase 0 executes | C |

**Where built:** this project first — the sandbox writes and tests code on sample data, pushes to GitHub, reads Actions logs to debug. Claude Code is an optional accelerator later; same repo either way. The repo README mirrors the §4.0 architecture table and points back to this document — a future reader understands the system without either of us.

**Security:** Yuna pushes via a **fine-grained PAT** (single repo, Contents + Workflows + Actions read-write — the Actions scope is how she triggers runs and reads their logs) pasted in-session, revocable anytime. **`EODHD_API_KEY` + `DATABASE_URL` (session-pooler URI) → GitHub Actions repository secrets, set by Zak in the UI** — the connection string is god-mode and exists nowhere else. Yuna's session access is the **Supabase MCP** custom connector (added exactly like EODHD was); RLS default-deny — nothing publicly reachable. Weights and thresholds live in the config table — every change is a logged row, not code archaeology. Yuna debugs live runs by reading Actions logs through the GitHub API.

**Backtest honesty:** the momentum backtest is clean — adjusted prices, delisted names retained. The compounder side **cannot be honestly backtested today** (point-in-time fundamentals history isn't for sale at our budget — §4.1 explains how we build it ourselves over time); the shadow book validates it forward-only. Chat-based backtests are sanity checks, not validation — the two classic sins (using data before its filing date, forgetting dead companies) both fake good results.

### 4.9 Accepted costs

- EOD granularity — covered by the reflex layer and live MCP pulls.
- Stop-limit gap-through — rare; covered by the ±7% interrupt and the market-sell-at-open rule.
- Up to a week of provisional fill drift — labeled, trued-up Sunday.
- Actions cron jitter — slack built into the UTC picks; the retry covers the rest.
- Free-tier pause coupling — nightly writes prevent it; heartbeat catches the only path to it.
- GitHub's 60-day schedule sleep — the monthly backup commit provides activity; the missing-brief alarm catches it; re-enabling is one click.


---

## Section 5 — SESSION RUNBOOKS 🔵 **DRAFT — awaiting Zak review** (2026-07-29)

The runbooks are the judgment layer's code — same review, same versioning as the formulas. Each session reads the database, never computes scores by hand, and always produces its output even when the news is "nothing."

### 5.0 Voice

Yuna writes like a sharp friend who happens to run a research desk — not like a terminal.

- **Smart, fun, warm, feminine.** First person, plain English, a little playfully dry.
- **She says Zak.** His name is the default; *Z* or *boss* when she's feeling playful. Charming, never saccharine.
- **Personality lives in the prose — never in the data.** Tickets, prices, stops, and scores stay clinical and exact; the flavor goes in the framing, the one note, the sign-off.
- **Wit is seasoning, not filler.** One good line beats three cute ones; succinct stays succinct.
- **When something's wrong, the voice goes flat.** Pipeline red, gap-through morning, stop fired — clarity first; personality yields to urgency, always.
- **Charm is the retention system.** The machine only works if Zak wants to open the brief — so every message carries at least one line worth smiling at: a spark, a small win named, a hook for tomorrow. But charm never manufactures urgency — she earns the habit with delight, not alarm. Fake urgency is a firing offense.
- Emoji sparingly — ☀️ 🌙 ⚠️ and only when they earn their place.

*Quiet-day example:* `☀️ Morning, Zak. Quiet tape — NAV $201.4K (+0.4%), gate ON, stops all set. Nothing needs you today; go be brilliant somewhere else.`

### 5.1 R1 — Pre-open (weekdays ~6:00 PT)

| # | Step | Rule |
|---|---|---|
| 1 | **Heartbeat** | Nightly job green? Red/missing → stale banner opens the brief · **no new tickets** · protective instructions only · brief still sends |
| 2 | **Quarantine** | Flagged prints verified against a live MCP quote · two sources agree → act or clear · disagree → stays suspended, named in brief |
| 3 | **Gaps ±7%** | Momentum gapped below its stop-limit → order unfilled → **manual exit at open** ticket · Compounder gapped down → check invalidators + hurdle (a gap can create an add) |
| 4 | **Fired stops** | Price crossed a stop → position marked *presumed stopped* → brief asks Zak to confirm the fill |
| 5 | **Gate transition** (Mondays) | M1 flips only on Friday close · OFF → momentum exit tickets · ON → queue re-armed |
| 6 | **Triggers & hurdles** | Entry/add tickets for whatever the nightly job armed · blackout, sleeve room, theme entry-cap, add-caps enforced before any ticket is written · **max 2 new-entry tickets per brief** — extras wait in queue order |
| 7 | **Unconfirmed stop moves** | Repeat as one line until Zak confirms |
| 8 | **Compose** | Snapshot first (freshness · NAV + move · tickets as broker-ready pairs · "**You:** …") · context below as needed · written to briefs |

**Entry mechanic ✅ RULED (2026-07-29):** breakout entries execute as **GTC buy stop-limit orders at the pivot** (trigger = pivot · limit = pivot + 2%), placed from the brief when a name reaches BUY state. The volume condition cannot live inside a broker order, so it is verified at EOD: breakout-day volume < 1.4× the 50-day average → next morning's brief instructs an exit. Low-volume breakouts are failures in the method anyway. Pyramid steps 2–3 ship as add stop-limits in the brief after step 1 confirms.

### 5.2 R2 — Evening stop sheet (weekdays ~20:30 PT)

Heartbeat (both job windows) → stop deltas → **always exactly one line minimum**:
`✓ stops all placed correctly` · or one line per action — `NVDA · stop 176.20 / limit 170.90` · `AMD · blackout — cancel entry order` · or `⚠️ pipeline red — touch nothing, GTCs stand as placed`.
The daily line doubles as the pipeline's nightly receipt.

### 5.3 R3 — Saturday deep-dive (~8:00 PT)

Heartbeat → gate status **and margin to the flip** → top/bottom-5 industry groups with week-over-week deltas → L1-M turnover (names in/out) → **top-3 workups** — each: MCN, state, pivot/stop pair, earnings date, what would make it a BUY → queue changes → displacement checks against the +10 rule → **performance line: NAV week-over-week and YTD vs the 30% bar**. Snapshot first, context after, + the queue table. Written to briefs.

### 5.4 R4 — Sunday reconciliation (interactive)

Zak provides settled Wealthsimple activity **plus per-account cash balances and available credit per facility** → matched against provisional tickets → price/qty/FX/fees trued up → transactions confirmed → **balances anchored, NAV trued** → shadow-book 30/60/90-day marks recorded as observations → discrepancies flagged in the summary, never silently absorbed.

### 5.5 R5 — Monthly approval (interactive, 1st weekend)

Funnel output → new bench candidates, each with a **C2 memo**:

> **C2 memo template (target ~200 words):** company + one-line what-it-does · the three Gate C2 questions, two sentences each (does scale strengthen it? gains shared to widen the moat? where does the next dollar go and what does it earn?) · proxy metrics table · serial-acquirer flag if goodwill jumped · **PASS / FAIL + confidence**.

→ **annual re-underwrites** for any holding at its purchase anniversary this month (Gate C2 from scratch, invalidators re-set) → evictions list (rule-driven, reported) → audit snapshot: return vs the 30% bar · sleeve observations · breaches · learnings due for **promotion or expiry** → Zak rules → approvals join the bench, rejections get 12-month cooldown rows.

### 5.6 Shared session laws

- **Stale data ⇒ no new tickets.** Protective moves only. Every brief opens with the freshness line.
- **Every session writes its output to briefs** — a session that produced nothing durable didn't happen.
- **Summary first, context second.** Succinct by default, never at the cost of needed information — depth always on request. Math lives in the tables.
- Anything a runbook doesn't cover → flag it in the brief, don't improvise silently.


---

## Section 6 — PHASE 0: INITIAL DEPLOYMENT 🔵 **DRAFT — awaiting Zak review** (2026-07-29)

One-time protocol. Bridges today's book (≈70% cash, non-conforming) to a conforming v1 book. Steady-state rules assume positions were born inside the system; Phase 0 re-underwrites everything currently held **as if it were being bought today**. Any position may be sold to reach the ideal book. After Step 5 the system is simply in **steady state** — if nothing else is buyable yet, that's fine; the machine waits for its prices.

| Step | What happens |
|---|---|
| **0 — Freeze** | No discretionary trades from Phase 0 start. Existing GTC stops stand. |
| **1 — Cold start** | Historical backfill + full fundamentals sweep (~20k calls, one day) → first funnel run → initial bench, queue, and scores for **every current holding**. |
| **2a — Assign sleeves** | Every current **sleeve** holding is scored by **both** pipelines (the levered layer sits outside the sleeves — judged in Step 5 by §2.5). It joins whichever sleeve it qualifies for · dual qualification → Compounders · qualifies for neither → exit. |
| **2b — Re-underwrite incumbents** ✅ RULED | A position survives only if the system would **buy it today** — score ≥ 70, gates passed, §2 caps applied as if every position were a new entry (2-per-group · 35% theme · 4% minimum full size). Everything else → exit ticket. Consequence, accepted: the AI cluster trims to ≤ 2 names; MU / VRT / GOOGL dust either earns full size or exits. *Ruled strict 2026-07-29 — "numbers ship, not a feelings ship."* |
| **3 — Deploy compounders** | Approved bench names at/below hurdle enter immediately at full §3.1 size. Above-hurdle names wait on the daily check. RRSP idle cash deploys here (§2.6). |
| **4 — Deploy momentum** | As real setups fire, gate permitting. Never forced. |
| **5 — Levered layer** | D9 (CNQ scored by the machine) and D10 (levered ETF choice) resolved inside Phase 0. |

**Tax note:** TFSA exits carry no tax consequence. Any non-registered sale (CNQ) realizes gains or losses — flagged at decision time.


---

## TODO

**Open decision**
- **D10 — levered ETF instrument.** VUN / equal-weight / ex-US — VFV correlates too closely with the book. Resolved inside Phase 0 Step 5.

**Deferred by design**
- **D8 — options & shorting gate.** The vision keeps these behind an unwritten gate. Not blocking; write the criteria only if and when the capability is wanted.

**Spec still to write**
- **Learnings promotion & expiry.** The vision says observations become learnings through repetition and expire unless re-earned — the thresholds aren't written. Best written once real observations accumulate, rather than invented now.

**Remaining work**
- [x] Subscribe EODHD All-In-One (monthly first) — *done 2026-07-30*
- [x] Create Supabase project · add the MCP connector · **rotate the database password** (it touched chat) — *pre-flight passed 2026-07-30: all entitlements verified live*
- [ ] Create private GitHub repo (**`yuna`**, private, README) · add **Actions repository secrets**: `EODHD_API_KEY` + `DATABASE_URL` (Supabase *session-pooler* URI carrying the rotated password — set in the UI, never through chat)
- [ ] Build phases A–F (§4.8)
- [ ] Execute Phase 0 (§6)
- [ ] Cutover — write the final strategy doc and Yuna's operating guide out of this plan, archive the old docs

**Done**
- [x] Vision, portfolio architecture, selection engine — §1–3
- [x] Mechanics, session runbooks, deployment protocol — §4–6
- [x] Data vendor selected, plan verified against vendor docs
- [x] All formulas specified — CCN v1.0 · MCN v1.0 · Hurdle v1.0 · M1 v1.0
- [x] D1–D7 resolved in the sections · D9 and D11 absorbed by Phase 0's strict rule

---

## Known limitations

- Yuna's code sandbox reaches only package registries and GitHub — it cannot call a market data API directly.
- Yuna has no persistent process. The system must live outside her or it doesn't exist between sessions.
- Everything is end-of-day. No intraday. Covered by the reflex layer (§4.6) and live MCP quotes when needed.
- Broader universe means shallower knowledge per name.
- Candidate flow can exceed execution bandwidth — throttled to 2 new entries per brief (R1); adds, exits, and protective actions are never throttled.
- The compounder pipeline and momentum Gate M4 are **dark until the fundamentals feed is live**. EODHD Extended alone runs M1–M3 and the full MCN price stack.

---

## Changelog

| Date | Entry |
|---|---|
| 2026-07-29 | Plan opened. FMP and EODHD priced. |
| 2026-07-29 | MCP connector live. Probe run. D1 resolved: EODHD Extended. Phase 1 closed. |
| 2026-07-30 | All sections marked FINAL by Zak. Freeze protocol in force: changes only by announced edit. |
| 2026-07-30 | **Connectors live — full pre-flight passed.** EODHD All-In-One verified at the source: calendar (3,638 rows/2 days), index bars, live+FX, fundamentals all 12 sections with FCF + filing_date. Supabase connected (PG 17.6), schema empty, SQL executes. Password rotated. Two builder notes: pull broad + filter locally (calendar symbols filter and fundamentals sections filter both unreliable). Secrets spec finalized: `EODHD_API_KEY` + `DATABASE_URL` (session pooler) replace the service key; PAT scope gains Actions RW. |
| 2026-07-29 | **Voice tuned · vendor verified live.** She says Zak (*Z* / *boss* when playful) — "partner" retired. Charm-as-retention added with the no-fake-urgency guardrail. EODHD pricing checked at the source: earnings calendar is a separate add-on outside the Fundamentals feed — All-In-One confirmed as the correct (and cheaper-than-à-la-carte) buy. |
| 2026-07-29 | **Closing pass.** Reference block deleted. Document renamed — Yuna, no version. Glossary gains "Bar". Cold-start derived multiples specified (hurdle's 5-yr median freed from old bars). §5.0 Voice added — smart, fun, warm, feminine; personality in prose never in data; goes flat under alarm. |
| 2026-07-29 | **Deep scan — 15 findings applied.** Fundamentals storage split (fields→DB, raw→repo; free tier saved). Backup excludes re-pullable bars. Reference block realigned to the contribution-independent ruling. Start-low overrides band floor. Bench cohort mechanism (top-30 per side, $10B boundary). Blackout cancels live broker orders. M1 latch + Friday defined. Phase 0 exempts levered layer. R4 captures balances/credit. Vision gains "failed-signal" exemption (FINAL touch, flagged). Queue priority, throttle 2/brief, filing detection, stale 5%→4%, TODO password rotation. |
| 2026-07-29 | **Final scan applied.** §2.0 NAV & capital accounting added (levered layer outside sleeves, inside independence caps; balances-are-truth reconciliation; account named on every ticket). Momentum risk budgets corrected 1.5/2.0 → 0.7/0.9 — the old numbers never bound. Compounder sleeve room symmetric with momentum. Phase 0 gains sleeve assignment. Phases + Open Decisions retired into a single TODO. Glossary alphabetised and expanded to the whole plan. |
| 2026-07-29 | **Section 4 restructured to the map.** §4.0 links each box to its section, order aligned (Data → Compute → Store → Judge → Execute → Protect → Health). Jobs named. Sessions split into Judge. Execute = Zak's six-item list. Protect slimmed — gap expectation corrected (gap past limit = probably NOT sold). Glossary moved to whole-plan appendix. §6 ends at Step 5 — steady state. |
| 2026-07-29 | **Data residency ruled** (store-and-increment · 3-yr bar window · corp-action refresh · fundamentals archived forever as the point-in-time asset). **Phase 0 keep bar ruled strict** — buy-it-today or exit. |
| 2026-07-29 | **Review round baked.** C1–C4 (glossary, clock convention UTC/ET/PT with worked cron times, §4.6 renamed the database, write modes defined) · D1–D6 (60-day sleep accepted-monitored, DST-proof UTC picks, 90-day GTC user-handled, API budget block, guard triggers, README mirror) · I2–I4 (anniversary re-underwrites in R5, word caps removed → summary-first two-layer format, weekly perf line). Section 6 Phase 0 drafted — keep-bar ruling open. |
| 2026-07-29 | **Rulings:** entry mechanic (buy stop-limits) ruled · gap-through protocol blessed with rarity framing · no-improvise law confirmed. |
| 2026-07-29 | **Section 5 drafted — session runbooks.** R1 pre-open (8 steps + entry-mechanic proposal 🔵 buy stop-limit at pivot, volume verified EOD), R2 stop sheet, R3 deep-dive, R4 reconciliation, R5 approval + C2 memo template, shared session laws. Rev labels stripped from headings — all v1. Credential hygiene enforced: pasted DB password to be rotated; MCP + GitHub Secrets only. |
| 2026-07-29 | **Section 4 rev 2 (DRAFT).** Store switched Airtable → Supabase (free Postgres; views for browsing; monthly dump; pause note). Stop-limit mechanics: limit = stop − 3%, gap-through protocol. Stop sheet moved to 20:30 PT (after both job windows) and always sends one line — doubles as nightly receipt. Core migration moved into Phase A. FINAL status reverted — Zak review gates FINAL. |
| 2026-07-29 | **Section 4 FINAL + rev 4.** Evening stop sheet (exception-based), paired entry+stop tickets, storage ruled (Airtable, two-base split, Supabase as v2 path), §2.6 account placement added (Momentum→TFSA only · RRSP compounder satellite · non-reg = levered layer · TFSA loss asymmetry named). CNQ location conforms. |
| 2026-07-29 | **Section 4 drafted.** Architecture, reflex layer (broker GTCs), jobs/cadence with Sat-forward/Sun-reconcile weekend, heartbeat, quarantine, All-In-One data plan, 10-table book with archive discipline, provisional→confirmed fill loop, low-verbosity output spec, repo security, build phases A–F, backtest honesty. D5 resolved. |
| 2026-07-29 | **Rev 3 — coherence pass.** F1–F8 applied: position floor 4%, intended-hold wording, callable-only strength rule, sleeve ceiling binds sizing, CCN ≥ 85 for levered single names, crash adds exempt from add cap, stalled-pyramid rule, fundamentals-dependency limitation. Annual review → re-underwrite with three-speeds note. Locked-decisions table retired — sections are the single source of truth, changelog is the time log. D3/D4/D6/D7 resolved. |
| 2026-07-29 | **Section 3 rev 2.** Hurdle v1.0 defined (Bogle decomposition, 15% floor, no rerating credit). M1 v1.0 defined (Weinstein 30-week). Absolute-vs-relative exit asymmetry. Sizing moved into pipelines. Gates renumbered in execution order. Bench funnel + eviction seatbelts + rejection cooldown. All 34 audit parameters baked in. |
| 2026-07-29 | **Section 3 FINAL.** Two pipelines, cadence + event interrupts, CCN v1.0 and MCN v1.0 both slimmed to three equal-weighted components. Tranching retired except crash protocol. Pyramiding, euphoria rule, data discipline added. Phases 3–4 closed. |
| 2026-07-29 | **Section 2 FINAL.** Sleeves, sizing, independence limits, leverage by facility. Theme cap set to entry-only. Phase 2 closed, Phase 3 opened. |
| 2026-07-29 | Section 1 restructured from symptom-diagnosis to vision. Required rate corrected to 31% with contributions. Spec/moonshot sleeve eliminated; 100x relocated to Compounders. Leverage rules set. **Section 1 FINAL.** Phase 2 opened. |

---

## Glossary

| Term | Plain English |
|---|---|
| ADDV | Average daily dollar volume — shares × price; how much money trades in a name each day |
| `as_of` | The timestamp on every stored figure, always UTC — what moment this number describes |
| ATR | Average true range — a stock's typical daily swing; used to measure whether it's coiling |
| Bar | One day's price record for one stock — open, high, low, close, volume (OHLCV), plus adjusted close. Three years per name live in the database |
| Base | A consolidation — a stretch where a stock rests sideways instead of trending |
| Blackout | The 5 trading days before a scheduled earnings report; no entries, no adds |
| CAGR | Compound annual growth rate — the smoothed yearly rate that gets you from A to B |
| Cash conversion | Free cash flow ÷ net income — how much reported profit shows up as real cash |
| CCN | Compounder Conviction Number — the 0–100 score ranking compounder candidates (§3.1) |
| Compounding engine | ROIC × reinvestment rate — the rate a business compounds its own capital |
| Cron | A time-based scheduler; GitHub's speaks only UTC and ignores daylight saving |
| DATABASE_URL | The Supabase Postgres connection string (session pooler) — the jobs' all-powerful credential; lives only in GitHub Actions secrets |
| Derating drag | The annual cost of a rich valuation sliding toward a fair one — always a cost, never a credit |
| DRY_RUN | A switch that makes a job compute everything and write nothing |
| EOD | End-of-day — one price record per stock per day, after the close |
| FCF | Free cash flow — cash from operations minus capital spending |
| GTC | Good-til-cancelled — an order that stands until filled, cancelled, or expired (90 days at Wealthsimple) |
| HELOC | Home equity line of credit — readvanceable, so it's exempt from the never-increase-into-strength rule |
| Hurdle | The computed price at which a compounder's expected return clears 15%/yr — the "start now" line (§3.1) |
| Idempotent | Safe to run twice — a re-run updates rather than duplicates |
| Invalidator | A named event, written at entry, that breaks a compounder thesis (§3.1) |
| L0–L3 | The funnel layers: universe → bench and candidates → queue → the book (§3.0) |
| LOC | Line of credit — here, the TFSA-secured facility; callable, so capped at 50% utilization |
| M1–M4 | The momentum gates: market stage · trend template · setup · earnings acceleration (§3.2) |
| Market gate | M1 — the sleeve-wide on/off switch based on the S&P 500's stage |
| MCN | Momentum Conviction Number — the 0–100 score ranking momentum candidates (§3.2) |
| MCP | The connector standard letting Yuna's sessions call outside services (EODHD, Supabase) |
| NAV | Net asset value — all assets across all accounts minus all debt, in CAD. The scorecard (§2.0) |
| NOPAT | Net operating profit after tax — EBIT × (1 − tax rate); the numerator of ROIC |
| PAT | Personal access token — a scoped, revocable key for pushing code to the repo |
| Pivot | The top of a base — the price whose break defines a breakout (§3.2) |
| Provisional / confirmed | Penciled in from chat or a ticket flip / trued up against the broker's settled record on Sunday |
| Quarantine | Holding a suspicious price out of use until two sources agree (§4.1) |
| Reinvestment rate | The share of profit put back into the business — the other half of the compounding engine |
| RLS | Row-level security — access rules enforced inside the database itself |
| ROIC | Return on invested capital — what the business earns on the money tied up in it |
| R² | How tightly a trend fits its own line — high means steady, low means erratic (§3.2) |
| Shadow book | The record of every pass and every exit, marked at 30/60/90 days — how formulas earn their weights |
| Sleeve | One of the two strategies — Compounders or Momentum — each with its own capital, rules, and exits |
| Stage 2 | Weinstein's advancing phase — price above a rising long-term average |
| Stop-limit | Two prices: the trigger that activates the order, and the limit — the worst price accepted |
| Studio | Supabase's built-in web dashboard — a spreadsheet-style browser for the database |
| Tactical lot | A crash-protocol purchase tagged at buy time as momentum's future funding source (§3.3) |
| Trend template | Minervini's six price conditions a momentum candidate must pass (§3.2) |
| Upsert | Insert-or-update in one step; how idempotency is implemented |
| View | A saved query that reads like a table — `v_book`, `v_queue`, `v_bench` are built for human browsing |
