# Open questions — things the code needs ruled

*Against `docs/yuna_plan.md` as of the **2026-07-31 16:37 UTC** stamp.*

The plan is law and I don't fill gaps. Everything below is a place where the code
either **had to decide something the plan doesn't state**, or **does something the
plan doesn't say**. Each names the exact plan line, what the code does today, and
what I need.

Items marked **DEVIATION** are live right now and are shaping the lists you've
already seen. Those matter most.

---

## Closed by the 16:37 amendment

- **X2** — dissolved rather than bounded. Both pyramid adds now carry limit
  pivot × 1.05, so a skipped band completes at the open and a gap beyond +5% fills
  nothing. Implemented in `policy.pyramid_orders`.
- **X3** — ruled. A base breaks on a later **close** above the pivot *or* a later
  **high** beyond pivot × 1.005. Implemented in `policy.scan_base`, along with the
  window moving to 120→25 and the deletion of near-BUY, base age and the forming
  state.
- **D4, engine tolerance** — the plan states **5 percentage points, flat**. My
  `max(5pp, half the observed CAGR)` was looser and is now corrected to flat 5pp.
  It changes which names get underwritten at their engine growth. (One consequence
  is unresolved — see Q7.)
- **D2, foreign issuers** — I was wrong to raise this as unstated. §3.0 already
  says it plainly: US-listed foreign issuers and ADRs are full L0 and momentum
  members, and are compounder-eligible when FCF and market cap are in one currency
  — **financials converted at fiscal-period-end FX, market cap the vendor's USD
  figure**, and no conversion data routes to the data-confidence path. The code
  excludes them instead. That is a straight implementation gap, not a question, and
  it is on my list.

---

## Live deviations

### D1 — the 35% theme cap is being applied to *sector* **DEVIATION**
§2.2: *"A **theme** is a shared macro driver… no data field catches it. Theme is
**Yuna's judgment, assigned in the session that writes the ticket**… Sector and
industry are inputs, never the definition."*

`phase0.py` needs the 35% entry cap and is a **job**, not a session, so it
substitutes the vendor **sector** field. That is precisely what §2.2 says not to
do, and it has already changed outcomes: your real concentration is the AI complex,
which spans Technology, Industrials and Utilities — three sectors, so a
sector-based cap sees three compliant themes where there is one large breach. §2.7
records the true figure as *"theme ~76% of invested equity"*, which the proxy would
never have found.

**What I need:** until sessions write tickets, should a job (a) apply the cap on
sector as an explicitly-labeled approximation, (b) not apply it and print raw
exposure for you to judge, or (c) apply it against a theme map you maintain? I lean
(b) — an approximation that reads 76% as three compliant themes is worse than no
check, because it reports green.

### D3 — the data-confidence floor is stricter than §3.3 **DEVIATION**
§3.3: *"never assume a missing value — drop the component, renormalize remaining
weights to 100, mark the name as scored on 2 of 3."*

Applied literally, a name with no measurable engine *and* no measurable cash
conversion still scores — on **size alone**, which is available to nearly
everything and inverted, so the smallest company in the universe scores ~99. A $4
ethanol microcap topped the compounder bench this way.

I added a floor: **two components, at least one a business measure, or the name is
not ranked.** Stricter than the plan.

The amendment made this more pressing, not less: §3.1 now routes *three separate
conditions* down the data-confidence path — engine with under 3 fiscal years, an
engine diverging beyond 5pp, and a missing vendor market cap. Two of those can fire
on the same name, and the plan's phrase *"scored on 2 of 3"* implies 2 is the
minimum without saying which 2.

**What I need:** bless the floor, or tell me what §3.3 should say.

### D5 — the fair multiple uses a 3-year window, not 5 **DEVIATION, already announced**
§3.1: fair multiple = *"lower of the stock's own 5-yr median P/FCF or 30×. Names
with < 3 yrs of history: fair = lower of current or 25×."*

We hold 3 years of bars, so the median is taken over the quarters we can price and
`pfcf_obs` records how many. Under 8 observations the name falls back to the
short-history rule. We cannot compute the plan's number.

**What I need:** confirm this stands, or authorize buying more history. Bars are
cheap now that Supabase is on Pro — 5 years is affordable if you want the real
number, and it directly moves every hurdle price.

### D6 — jobs are writing tickets **DEVIATION**
§4.3: *"jobs arm candidates; only sessions write tickets."* `phase0.py` writes
tickets directly. On my list to fix; recorded here so it's on the record.

### D7 — MCN is computed on the superseded setup definition **DEVIATION**
The amendment dropped **pullback contraction** from setup proximity, leaving three
sub-scores. `rank.py` still averages four. Every MCN currently in the database is
computed on the old definition, so the momentum rankings you've seen are stale.

Not a question — a fix, and a re-rank afterwards. Flagging because it changes the
list, not just the code.

---

## Needs a ruling

### Q7 — what growth does the hurdle use when the engine diverges? **NEW**
§3.1: *"beyond 5pp = divergence: the engine component routes down the
data-confidence path (§3.3) and the flag lands on the C2 memo · never silently
score."*

The data-confidence path governs the **CCN** — drop the component, renormalize,
mark 2-of-3, cap at the bottom of the size band, require manual sign-off. Clear.

But the **hurdle** separately needs a number for *"engine growth"*, and the plan
doesn't say what it should be when the engine has just been declared untrustworthy.
Underwriting at that rate would contradict "never silently score"; using zero would
make almost every diverging name un-buyable.

The code currently caps the hurdle's growth input at observed revenue growth. That
is conservative and defensible, and it is **not in the plan** — it's my judgment,
and it moves hurdle prices. Options: (a) cap at observed revenue growth as now,
(b) growth = 0, (c) no hurdle at all for that name, (d) something else.

### Q1 — what period does the 30% bar measure?
You ruled time-weighted return, which settles deposits. It doesn't settle **over
what window** or **at what observation frequency** — and time-weighting chains
sub-period returns, so the boundaries change the answer.

Sunday reconciliation is the natural boundary; it's the only moment balances are
confirmed. But is the bar **since inception**, **rolling twelve months**, or **per
calendar year**?

I'd default to sub-periods bounded by Sunday reconciliations, reported both
since-inception annualized and rolling 12-month. Say the word.

### Q2 — is 4 compounders a floor or a description?
§2.1 gives compounders *"4–5"* names and says the sleeve *"should be full nearly
always."* If only 3 clear the hurdle, is the machine content at 3, or obliged to
report the sleeve under-filled and treat it as a condition to fix? Nothing pushes
toward 4 today.

### Q3 — the blackout window's exact bounds
§3.3: *"no new entries and no adds within 5 trading days of a scheduled report… The
blackout lifts the first session after the report session."*

I read that as blacked out from 5 sessions before the report **through the report
session** — six sessions. Confirm, or tell me it's five inclusive of the report day.

### Q4 — the ticket state machine
The write path refuses any transition not on a list, so the list has to exist. The
schema has `proposed`; the plan describes tickets being placed, filled, cancelled
and expiring, but never enumerates the states. I'll propose a set with the design —
flagging that it's yours to set, not mine to assume.

### Q5 — the balance-outlier quarantine threshold
When you tell a session "TFSA cash is now X", how far from the last known value
before the machine refuses to accept it silently and asks you to confirm? A
fat-fingered extra zero must not become NAV. I'll propose a number; it's yours.

### Q6 — CNQ and the CCN ≥ 85 question
§2.7 lists CNQ as **Review**: *"location conforms (§2.6 levered layer); open
question is CCN ≥ 85."* §2.5 permits single names in the LOC/HELOC layer only at
CCN ≥ 85. An oil producer will not score 85 on a scale built around reinvestment
and cash conversion — which makes it a §2.5 breach rather than an open question,
unless the levered layer's single-name test is meant to be something other than CCN.

### Q8 — effective shares vs reported shares **NEW**
§3.1: *"cap at price P uses **effective shares = vendor cap ÷ last close**."*

The hurdle currently divides by reported shares outstanding. For an ADR those are
different objects and the hurdle is wrong by the depositary ratio. This is an
implementation gap I'm fixing — but it interacts with the currency rule, because
the vendor cap is USD while the statements are not, so the fix has to land with the
FX conversion or not at all. No ruling needed unless you disagree with sequencing
them together.

---

## How these land

Amend the plan and I'll implement the amendment. Nothing here is implemented on my
own reading, and every deviation is recorded in `src/yuna/rules.py` so it cannot
quietly become normal.
