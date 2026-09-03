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

## Gates

As A25: `finding.py`, `capture_audit.py`, `verify_run.py`, learning 40's episode cut. These cells
fill at the next open like the cell of record, so verify's C2 should pass on all four; if it does
not, the mechanism has touched the fill path and the run is void.
