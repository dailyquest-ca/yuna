# WO-A13 · Decision sheet

**Written:** 2026-08-14. Replaces Part A of `wo-a12-gaps-and-rulings.md`, which mixed two
different kinds of decision together and was hard to rule on as a result.

Every item below has the same shape: **what it is** in plain terms, **why it matters** with the
number if there is one, **the options**, **how much it could move the result**, and **what I
recommend and why**.

They are split into two groups. **Group 1 changes what the backtest produces** — those need ruling
before the verification run. **Group 2 only matters once the live desk is running** — nothing is
blocked on them today, and they are listed at the end so they are not lost.

---

# Group 1 · Decisions that change the backtest

## 1.1 Starting capital — **RULED: $100,000**

**What it is.** The hypothetical account the simulation starts with.

**Why it matters.** Almost not at all, and it is worth knowing why. The cost model charges a spread
that depends on *the stock's* daily dollar volume, not on how much we are buying. So a $100k
account and a $10m account pay the same percentage cost, and the CAGR comes out identical. Only the
dollar figures on the report change.

**Impact:** none on return. Cosmetic.

**One caveat worth recording.** Because cost does not scale with our size, the model would be
optimistic for a genuinely large account — buying $2m of a stock that trades $10m a day moves the
price, and the simulation does not know that. At $100k a 20% slice is $20,000 against a $10m
minimum daily volume, which is 0.2% of a day's trading. Invisible. **The model is honest at this
size and would stop being honest somewhere north of a few million.**

**Note for comparisons:** every stored run used $200,000. Switching to $100k leaves CAGR, drawdown
and Sharpe unchanged and halves every dollar figure.

---

## 1.2 Contributions — **RULED: none**

**What it is.** Whether new money arrives during the test.

**Why it matters.** Regular contributions change the compounding path — money added after a crash
buys cheap and flatters the result. Keeping it at a single lump means the number measures the
strategy and nothing else.

**Impact:** none, given the ruling.

**You are right that this is the correct call for a test.** Worth remembering later: if you do
contribute regularly in real life, your actual outcome will differ from this number, and not in a
way the backtest can be blamed for.

---

## 1.3 Execution — when do we assume the trade actually fills?

**This is the most consequential item on the sheet.**

**What it is.** The strategy decides what to buy using Monday's closing prices. But you cannot buy
at Monday's close — you learned the answer *at* the close. You buy the next morning.

The backtest currently pretends you bought at Monday's close, at Monday's closing price.

**Why it matters.** It means every trade in the simulation gets a price nobody could actually have
got. Between Monday's close and Tuesday's open the stock gaps — sometimes several percent. For a
momentum strategy buying stocks that just moved sharply, those gaps are not random: you are
systematically buying things that are running, and the overnight gap tends to run the same way.

The backtest has never modelled this. Worse, the cell's configuration contains `next_open=True`,
which reads as though it had — but that flag is only consumed inside the trailing-stop exit path,
and this strategy has no trailing stop, so it never fires.

**What we know about the size.** We have a partial probe. "Rank lag" tests use a deliberately stale
signal — decide on Friday's data, trade Monday — which is a rough proxy:

| variant | CAGR | vs base |
| --- | ---: | ---: |
| base (same-close fill) | 43.91% | — |
| rank lagged one session | 43.08% | −0.83 |
| rank lagged two sessions | 46.59% | **+2.68** |

Lagging *two* days beating the base tells us this is noise rather than a systematic free lunch,
which is genuinely reassuring. But it is not the same test — a stale signal traded at the close is a
different thing from a fresh signal traded at the open.

**Options.**

| option | what it assumes | honest? |
| --- | --- | --- |
| **(a) Same close** (current) | You bought at the price that told you to buy | No |
| **(b) Next open** | You bought at the next morning's opening price | Yes — matches how you would trade |
| **(c) Next close** | You waited a full day | Overly conservative |

**Impact: unknown, potentially several points, and I cannot bound it without running it.** Opening
prices are already in the database, so this is measurable, not speculative.

**Recommendation: (b), next open.** It is what you would actually do, it is what the live spec
says, and a backtest whose execution differs from the plan is measuring a strategy nobody will
trade. Report (a) alongside it so the size of the correction is visible rather than buried.

---

## 1.4 Sort stability — which stock wins a tie

**What it is.** We score 500 stocks and sort them best-first, then take the top 5. The sorting
function we use (`numpy.argsort`) defaults to an algorithm called quicksort, which is **unstable** —
meaning when two stocks have *exactly* the same score, which one lands higher is an internal
implementation detail. It can differ between numpy versions, and in principle between machines.

**Why it matters.** Two reasons, and the second is the real one.

1. If stock #5 and stock #6 score identically, which one we buy is arbitrary.
2. **The backtest is not reproducible.** Run it twice and you can get different books. That means
   we can never build the "golden parity vector" — a frozen test proving that the live daily job
   and the backtest produce the same picks. Without that, we have no way to know the live system
   implements the strategy we measured.

**How often do exact ties happen?** Rare with real prices — but they happen reliably in one case we
know exists: **duplicate listings.** BBBY and BBBY_old carry identical price histories, so they
score identically, and which one gets bought is decided by the sort.

**Options.**
- (a) Leave it — ties resolve arbitrarily
- (b) Use a stable sort — ties resolve in the order the data was loaded, which is ticker
  alphabetical

**Impact:** essentially zero on return. Binary on reproducibility.

**Recommendation: (b).** One line of code. It cannot change any result except by making it
repeatable.

---

## 1.5 Duplicate listings — do we remove them before the run?

**What it is.** The data vendor sometimes carries one company under two ticker symbols with
identical price histories — a bankruptcy adds a "Q" (CLVS and CLVSQ), a ticker change keeps the old
symbol alive (BALL and BLL), a re-listing appends "_old" (BBBY and BBBY_old).

**Why it matters.** A 5-stock book can buy the same company twice and call it two positions. You
would think you held five companies; you held four.

**What we measured.** Small in P&L terms — duplicates were 0.6–2.3% of trades with negligible
profit impact. But two of them appeared together in the book repeatedly across 2017–2021.

**Status.** `src/dedupe_scan.py` is built and tested. It currently only reports; it has never been
run against the live database.

**Options.**
- (a) Run the verification without removing them
- (b) Run the scan, look at what it proposes, apply it, then run the verification

**Impact:** small on return. Larger on the concentration numbers, and it is a hard blocker for
reproducibility (see 1.4).

**Recommendation: (b).** The scan reports before it writes, so you see the list before anything is
excluded. It is one job run.

---

## 1.6 The slot clock — how the backtest decides which position to review today

**What it is.** The strategy holds 5 stocks and reviews one per day, so each gets looked at weekly.
The backtest picks which one using a counter: `session_number mod 5`.

The live spec uses a different rule: review whichever position has gone longest without a review.

**Why it matters.** Under normal operation they are identical. They differ only after something
goes wrong — a missed run, a holiday miscount. The counter version would then be permanently out of
phase with no way to detect it; the "longest since reviewed" version just catches up.

**Why it is on this sheet at all:** if the backtest and the live system use different rules, the
backtest is not measuring the live system.

**Options.**
- (a) Leave the backtest on the counter, live uses the other rule
- (b) Change the backtest to match the live rule

**Impact:** zero under clean operation. This is about the two systems being the same system.

**Recommendation: (b).**

---

## 1.7 Is the regime warning part of the strategy, or just a display?

**What it is.** The 200-day SPY filter. You already ruled it advisory — a warning you act on at
your discretion, not something the system does automatically.

**Why it is here.** It determines what the verification run actually tests. If the filter is
advisory, the backtest should test the strategy **without** it, because that is what will run.

**The consequence worth stating plainly:** if you sometimes act on the warning, your real results
will land somewhere between the filtered and unfiltered numbers, and **neither backtest describes
what you actually did.** That is not an argument against your ruling — it is why the "drift report"
in the live spec matters. It is the only thing that would ever tell you whether your calls helped.

**Impact of the choice:** filtered vs unfiltered is worth +6.4 points a year over 20 years and
−9.45 points over the last 9.

**Recommendation: confirm advisory, test unfiltered.** Report both so the warning's value stays
visible.

---

## 1.8 Top-up threshold — do we rebalance a winner back down?

**What it is.** Each of the 5 slots targets 20% of the account. When a stock runs, its slot drifts
above 20%. At its weekly review the backtest tops the *other* slots back up to 20%, buying a little
more of them.

Measured over 9 years: **58 genuine new positions a year** (~1/week, ~17% of the account each) and
**106 top-ups a year** (~2/week, ~3.2% of the account each).

**Why it matters.** Two things at once.

1. **Effort.** 106 extra small orders a year is real work for you.
2. **It is not neutral.** Skipping top-ups lets winners grow past 20%. For a momentum strategy with
   no stop-loss, that means holding more of what is working — which could help *or* hurt badly,
   since it also means holding more of something at its peak. Genuinely uncertain.

**Options.** Only place the top-up when the gap exceeds a threshold: 0% (current), 1%, 2%, 5% of
account value.

**Impact:** unknown. Could be a few points in either direction.

**Recommendation: measure all four.** This is not a question anyone should answer by reasoning.

---

## 1.9 Concentration cap — should the book be allowed to be 80% one sector?

**What it is.** Today the book is SanDisk, Micron, Western Digital, AXT and Revolution Medicines.
The first three are the same memory-chip cycle — **64.8% of the account in one trade.** Add AXT and
it is **80.8% in semiconductors.**

Measured across the 20-year run, "effective bets" — how many genuinely independent positions you
hold — averaged **2.54** against a nominal 5.

**Why it matters.** The strategy is more concentrated than it looks. A memory-cycle downturn takes
two-thirds of the account at once. This is not a bug — a top-5 momentum screen naturally piles into
whatever is leading — but it is the difference between what the table shows and what you own.

**Options.** Cap the maximum weight in any one sector: none (current), 70%, 50%, 40%.

**A complication that needs its own answer:** 1,375 of 6,333 stocks (22%) have no sector recorded
by the data vendor. A cap needs a rule for them — either treat "unclassified" as one bucket, or
exempt them. Exempting creates a loophole an entire book could walk through.

**Impact: potentially large.** A cap on a 5-stock book binds often and would force genuinely
different picks.

**Recommendation: measure none / 0.70 / 0.50, and treat unclassified as its own bucket.** Then
rule with the numbers in front of you. My prior is that a cap costs return and buys real safety, but
that is a guess and this is exactly the kind of guess that should not survive contact with a
measurement.

---

## 1.10 Minimum trading history — the one constant with nothing behind it

**What it is.** To be eligible, a stock needs at least **210** days of price history within the
last 252 trading days. It excludes recent IPOs and stocks with big gaps in their data.

**Why it is on this sheet.** Eight of the nine constants in this strategy have either an academic
source or a measurement behind them. This one has neither — it is roughly 83% of a year and nobody
recorded why.

**Impact:** expected to be near zero, but that is an assumption, and this repo's whole doctrine is
that an unmeasured constant is a guess wearing a constant's clothing.

**Recommendation: run 189 / 210 / 252 and confirm it is inert.** If it is, record that. If it is
not, that is a finding.

---

## 1.11 Which windows and which benchmark get reported

**What it is.** Not really a ruling, but it should be decided in advance rather than after seeing
the results — that is how a number gets cherry-picked without anyone intending to.

**Recommendation: report all three, always, in this order.**

| window | why |
| --- | --- |
| 2007–2026, 20 years | The full cycle. **This is the number to plan capital around.** |
| 2017–2026, 9 years | The recent regime, and the source of the 44.79% headline |
| 2007–2013, 7 years | The crash stress test |

Benchmark SPY throughout, because it is the only one with history across all three.

---

## 1.12 The multiple-testing discount

**What it is.** Over this programme, **176 distinct strategy variants have been run**, and the best
one was selected. If you try 176 things, some will look good by luck alone.

There is a standard correction for this — the "deflated Sharpe ratio" — and the machinery for it
already exists in this repo. For this family of runs the field currently reads `"not scored"`.

**Why it matters.** It does not change the strategy or the backtest. It changes **how much of the
result you should believe.** This is the single largest unpriced risk in everything I have shown
you.

**Impact:** it will reduce the confidence attached to the number, not the number itself.

**Recommendation: compute it over the honest count of 176, not over the number of cells in whatever
grid ran last.** And report it whatever it says.

---

# Group 2 · Live-desk decisions — nothing is blocked on these

These were on the earlier sheet and should not have been mixed in with backtest questions. They
matter when the daily job runs, not now. Recorded here so they are not lost.

| # | question | what it means | when it bites |
| --- | --- | --- | --- |
| **2.1** | **Sleeve NAV in real money** | How much of *your actual money* the momentum sleeve is, and whether that is a fixed dollar amount in the TFSA or a percentage of total household NAV. Determines every real position size. **My recommendation: the TFSA's own value — a self-contained account, which is what the backtest models.** A percentage-of-household definition would make a compounder drawdown force momentum selling, which nothing has tested. | Before the first live trade |
| **2.2** | **Stale prices** | Sometimes there is no fresh price for a stock you hold — a trading halt, a suspension pending news, a vendor outage. The backtest's rule is "never buy on a stale price, but do sell on one." Live, selling on a stale price means dumping into whatever caused the halt. **Recommendation: skip that slot and flag it to you.** | First halt or suspension |
| **2.3** | **Stale universe** | The live system needs a weekly-refreshed list of tradeable stocks. If that job fails for a fortnight, the desk is ranking against an out-of-date list. **Recommendation: halt after 10 sessions without a refresh.** Irrelevant to a backtest, where the whole history is already loaded — which is exactly the confusion in the earlier sheet. | First multi-week ingest outage |
| **2.4** | **What a RED warning changes** | You have already answered this: advisory, you decide. **Recommendation: the job proposes exactly the same thing either way and shows the flag.** No further ruling needed — noted only so it is written down. | Already ruled |
| **2.5** | **Where the constants live in the plan** | All nine need a home in §3.2 with their provenance recorded — which are academic standards, which were measured, and which (see 1.10) are conventions. A documentation task, not a strategy choice. | Before go-live |

---

# What I need from you to start

**Nothing, for the fixes.** Items 1.3, 1.4, 1.5 and 1.6 all point the same way under any ruling —
they make the backtest measure the thing we intend to trade. I can start on those now.

**Your call on:** 1.7 (confirm advisory — I think you already have), 1.9's cap ladder (or just let
me measure and rule after), and whether 1.8's top-up sweep is worth the runs.

**Expectation on the record before the run rather than after:** the corrected number will be lower
than 44.79%. Next-open fills remove a price nobody could have got, dedupe removes some
double-counted winners, and the deflation discounts 176 attempts. I am not going to guess by how
much.
