# WO-A30 to A33 — Four mechanisms on the cell of record

*Pre-registered 2026-09-03, before any code ran. Zak, on each: "Sure. Do this!" · "Sure. Check
it out." · "Let's run the numbers on this too." · "seems worth looking into."*

## Why these four

A25 measured what the repo's existing smoothers cost: a governor, a trail and a gate each buy
their drawdown with return, roughly one for one, and none reaches the bar. Each mechanism here is
different in kind. It changes WHAT is ranked, or WHEN the book is allowed to hold, using a
documented regularity of momentum returns rather than a volatility brake. Each is one axis off
the cell of record, priced against run 624 (SPY park, the §3.1 convention) on A24's window.

**The bar, shared.** A25's holdable bar: full-window maxDD no worse than −35% AND CAGR at least
21.8%. **The secondary claim, per mechanism:** beats the control's full-window drawdown by at
least 10 points at a CAGR cost of at most 3 points — cheaper than the governor, whose price A25
measured. A mechanism that meets neither is a scored prediction and nothing else.

## A30 — residual momentum

**What.** Rank names by the part of their 12-1 return the market did not explain. Each name's
daily returns are regressed on SPY's over the 504 sessions ending at `i − SKIP`; the residuals
over the formation window are the signal; the score is their mean over their standard deviation,
the risk-adjusted flavour the cell of record already uses. Eligibility, pool and everything else
are unchanged.

**Why it might work.** Blitz, Huij and Martens (2011) find residual momentum earns returns
similar to total-return momentum with about half the time-varying market exposure and far
smaller crashes, because the 2009-style crash is the market-beta component reversing, not the
stock-specific component.

**Prediction.** The 2007–09 and 2025–26 episodes each improve by at least 10 points; CAGR falls
2 to 5 points; the verdict stays unproven.

**What kills it.** If the top two of a large-cap pool are already beta-light, the book barely
changes. If daily-return betas are noisy, the rank gets noisier and CAGR falls further than the
drawdown improves.

## A31 — the crash-state veto

**What.** While SPY's 504-session return is negative AND its 126-session realized volatility
annualizes above 25%, the book may not hold stocks: it sells as `crash_off` and re-enters under
the (1, 3) latch once the state clears. Both thresholds are declared here, not fitted. The
negative two-year return is Daniel and Moskowitz's bear indicator verbatim. The 25% is a
research parameter of this WO, chosen as a level 2008–09, 2020 and 2022 all exceeded and calm
years do not; the run reports which percentile of the tape's own vol history it sits at, so the
next reader can judge it.

**Why it might work.** Daniel and Moskowitz (2016): momentum's worst months are concentrated in
the state where the market has been falling for two years and volatility is high — the rebound.
A rule that steps aside only then keeps most of the premium, where a governor steps aside a third
of the time.

**Prediction.** 2007–09 improves by at least 15 points (the spring-2009 rebound is skipped);
2020 improves by 5 to 10; the other episodes are unchanged within 3; CAGR falls 1 to 3 points;
the veto is on for fewer than 10% of sessions.

**What kills it.** Volatility staying high into the recovery, so the veto lifts late and the
book misses the re-entries: a CAGR cost above 5 points.

## A32 — the January veto

**What.** The sleeve parks for January every year: it sells at the first January session
(`jan_off`) and re-enters from the first February session under the ordinary entry rules.

**Why it might work.** Jegadeesh and Titman (1993, 2001): momentum returns are negative in
January, when the prior year's losers reverse, and positive in every other month.

**Prediction.** Small. CAGR within one point of the control either way; drawdowns within three;
the December-to-February round trip costs about half a point a year in spread. Honest prior: on
a large-cap pool in 2007–2026 this is the mechanism most likely to show nothing.

**What kills it.** Exactly that: the effect is strongest in small caps and has faded in large
caps since the 1990s.

## A33 — the breadth gate

**What.** The gate watches a different series. Instead of SPY above its own 200-day, the share
of liquid names above their own 200-session average must be at least 50%, the majority, declared
here. Same (1, 3) latch, same exits.

**Why it might work.** Breadth turns before the cap-weighted index at bottoms (March 2009, April
2020) and deteriorates before it at tops (2007, late 2021), because the index late in a cycle is
a few large names. The A4 grid's own learning was that the gate watched the wrong series.

**Prediction.** Earlier re-entry in 2009 and 2020: CAGR 1 to 3 points above the control. Earlier
exit at the 2021 top: the 2022 episode improves by at least 5 points. 2007–09 within 5 points
either way.

**What kills it.** Whipsaw. Breadth crosses 50% more often than SPY crosses its 200-day; if the
latch cannot smooth it, `gate_off` exits multiply and CAGR falls.

## Arms

Four dispatches, `park=SPY.US`, `calendar=SPY.US`, `start_date=2006-01-10`, `start_nav=100000`,
one stamp, two at a time (learning 62). Each cell is the cell of record plus one key —
`residual`, `crash_veto`, `jan_veto`, `breadth_gate` — and is declared in the grid test's
lineage. Four trials. Any mechanism that meets the secondary claim on the SPY park is then run
on the bill park before anything is called a candidate for a ruling.

## Amendment, 2026-09-03 03:25 UTC — declared after the first pair and before any other run

The first pair (A30 run 635, A31 run 634, both SPY park) exposed a flaw in the design above. On
a SPY park the full-window drawdown is the PARK's: gated-off capital rides SPY to the 2009-03-09
trough whatever the sleeve does, so a mechanism that changes WHEN the sleeve holds — the crash
veto, the January veto, the breadth gate — cannot move the number the secondary claim is scored
on. Run 634 held the book out for 75 sessions and reproduced run 624 to the first decimal. The
comparison is not wrong; it is uninformative, and the pre-registration should have said so.

So every mechanism is also run on the bill park, control run 623 (24.22%, −45.8%), where the
full-window drawdown is the sleeve's own 2025–26 episode and the mechanisms can be seen. The
secondary claim is scored on the bill-park pair for the three gate-like mechanisms and on both
pairs for residual momentum. Four more trials. The SPY-park arms of A32 and A33 still run as
pre-registered, so the record shows the same fact twice rather than a quietly dropped arm.

## Gates

As A25: `finding.py`, `capture_audit.py`, `verify_run.py`, learning 40's episode cut. These cells
fill at the next open like the cell of record, so verify's C2 should pass on all four; if it does
not, the mechanism has touched the fill path and the run is void.

## Result — 2026-09-03, runs 634 to 642

Eight arms on code stamp `55353058db496b93`, A24's window (first decision 2007-01-12, last
2026-09-01, 4,940 sessions), start NAV $100,000, two at a time. The controls are A24's runs 624
(SPY park) and 623 (bill park) on stamp `473a07e6a060dcf1`; the cell of record was not re-run on
the new stamp, and WO-A23's caveat applies. The bound on what the stamp change could be worth:
run 634, whose veto bit for 75 sessions, lands within 0.03 CAGR points and five trades of run
624. Episodes are the 2007-01-01 to 2009-12-31 cut and its siblings, the convention every table
uses from A25 on.

| arm | park | CAGR | maxDD (date) | 2007–09 | 2010s | 2020 | 2022 | 2025–26 | ≥20% below | trades | Sharpe | DSR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| control (624) | SPY | 26.08% | −60.3% (2009-03) | −60.3% | −50.0% | −37.2% | −46.4% | −45.9% | 47.6% | 748 | 0.78 | 0.210 |
| A30 residual (635) | SPY | 19.46% | −56.3% (2009-03) | −56.3% | −36.2% | −31.1% | −34.1% | −34.9% | 31.5% | 1,049 | 0.75 | 0.177 |
| A31 crash veto (634) | SPY | 26.05% | −60.3% (2009-03) | −60.3% | −50.8% | −37.2% | −46.4% | −45.9% | 48.1% | 743 | 0.78 | 0.217 |
| A32 January (637) | SPY | 19.85% | −60.3% (2009-03) | −60.3% | −49.8% | −37.2% | −44.6% | −45.9% | 48.2% | 759 | 0.66 | 0.093 |
| A33 breadth (638) | SPY | 23.03% | −61.3% (2009-03) | −61.3% | −48.6% | −37.1% | −42.2% | −46.8% | 43.4% | 697 | 0.73 | 0.159 |
| control (623) | bills | 24.22% | −45.8% (2025-11) | −27.3% | −37.5% | −28.4% | −40.3% | −45.8% | 34.3% | 748 | 0.78 | 0.205 |
| A30 residual (639) | bills | 17.80% | **−48.0% (2021-07)** | −15.4% | −26.8% | −20.5% | −30.7% | −34.6% | 21.6% | 1,049 | 0.78 | 0.222 |
| A31 crash veto (640) | bills | 23.31% | −45.8% (2025-11) | **−37.7%** | −37.5% | −28.4% | −40.3% | −45.8% | 35.3% | 743 | 0.76 | 0.192 |
| A32 January (642) | bills | 17.52% | −45.8% (2025-11) | −27.3% | −37.9% | −28.4% | −32.7% | −45.8% | 41.0% | 759 | 0.63 | 0.076 |
| A33 breadth (641) | bills | 20.03% | −46.8% (2025-11) | −23.9% | −39.0% | −32.4% | −29.4% | −46.8% | 34.1% | 697 | 0.70 | 0.131 |

**Against the claims: no arm meets the holdable bar, and no arm meets the secondary claim.** The
secondary claim asked for ten points off the full-window drawdown at three points of CAGR. The
closest is residual momentum on bills, which takes 6 to 11 points off four of the five episodes
and then posts a NEW worst episode, −48.0% in July 2021, for 6.4 points of CAGR.

### What each one did

1. **Residual momentum changes the shape, not the edge.** Sharpe 0.78 on bills, exactly the
   control's; DSR 0.222 against 0.205. It earns the same return per unit of risk with less of
   both. Four of five episodes are 6 to 14 points shallower on either park — the 2025–26 crash
   would have been −34.6% instead of −45.8% — and the price is 6.4 CAGR points, 1,049 trades
   instead of 748 (rank-band exits 592 against 357: the rank is noisier), thirteen twin-listing
   pairs held at once instead of four (identical series have identical residuals, so the rank buys
   both), and July 2021: residual momentum concentrates in the stock-specific runners of 2020–21
   and unwinds with them. Its efficiency, about 1.8 points of episode drawdown per CAGR point, is
   twice the governor's and a twentieth of the bill park's.
2. **The crash veto fired exactly where predicted and hurt exactly as the kill clause said.** On
   for 75 sessions, all in the second half of 2009, when SPY's two-year return was still negative
   and its volatility still above 25%. On a SPY park it changed nothing: the 2009 drawdown belongs
   to the park. On bills it held the book out of the July-to-September 2009 rally, re-entered into
   the October pullback, and made 2007–09 ten points WORSE (−37.7% against −27.3%) for 0.9 points
   of CAGR. The volatility window lifts late by construction; the mechanism is late by
   construction.
3. **January was this book's good month.** Sitting it out cost 6.2 points on SPY and 6.7 on bills
   and improved no episode but 2022. The documented January reversal is a small-cap effect; a
   top-two-of-500 book in 2007–2026 earned its turn-of-year flows and this veto gave them away.
4. **The breadth gate whipsaws.** 220 gate exits against 175, ON for 69% of sessions, and it
   trades one episode for another: 2022 improves by 4 points on SPY and 11 on bills, 2020 worsens
   by 4 on bills, and CAGR falls 3 to 4 points. The latch could not smooth a series that crosses
   50% more often than SPY crosses its 200-day.

### The predictions, scored

| prediction | outcome |
|---|---|
| A30: 2007–09 and 2025–26 each improve ≥10 points | 2025–26 yes (+11.0 / +11.2); 2007–09 no on SPY (+4.0), yes on bills (+11.9) |
| A30: CAGR −2 to −5 | no: −6.6 and −6.4 |
| A31: 2007–09 improves ≥15 | no: unchanged on SPY, ten points worse on bills |
| A31: veto on <10% of sessions | yes: 1.5% |
| A32: CAGR within ±1 | no: −6.2 and −6.7 |
| A33: CAGR +1 to +3 | no: −3.1 and −4.2 |
| A33: 2022 improves ≥5 | no on SPY (+4.2), yes on bills (+10.9) |

Two right, four wrong, two split. The honest prior on the January veto was that it would show
nothing; it showed six points, in the direction that condemns the mechanism.

### What we learn

Nine sleeve-side mechanisms have now been priced against the cell of record across A25 and this
WO: a governor, a trail, three gate variants, a residual rank, a calendar veto, a crash-state
veto and a breadth series. Every one of them buys drawdown with return, and the cheapest of them
is twenty times more expensive than the park. The sleeve's crash behaviour is the sleeve; the
park's is the park; and the only lever with a measured large effect at a small price is still the
park (A24). The trial count is now 483 (A29's ladder will make it 491), which is the freeze
argument in one number.

One thread is worth pulling later, behind the freeze: a residual rank with less noise — monthly
returns over thirty-six months, as the paper does, rather than daily returns over two years —
might keep the four shallower episodes without the extra 300 trades and the 2021 concentration.
Candidate WO, pre-registered before it runs, not before.

### Gates, as run

Conformance OK on all eight. `finding.py` UNPROVEN on all eight (DSR 0.076 to 0.222 against the
0.95 bar). `verify_run`: every arm passes C2 — all entries fill at their session's open — and D1;
every arm fails B4 and B7 only, the two tape properties A24 and A25 already carry (the residual
arms carry thirteen twin pairs, the others four). Nothing here is a promotion or a demotion.
