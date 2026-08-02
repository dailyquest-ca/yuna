# Vetting the entry hurdle — the growth cap, not the drag

*Four independent proposals, each adversarially critiqued twice for overfitting and for economics,
then synthesised. Two load-bearing claims were re-verified against the live solver and the stored
filings before this was accepted; both held. The working diagnosis it corrects — mine — did not.*

---

## FINAL RECOMMENDATION — the compounder entry hurdle

Zak: read §1 before the variants. The working diagnosis in the brief is wrong, and the correction changes what you should approve.

---

### 1. The diagnosis, corrected

**The zero drag floor is not the cause.** Three of the four schools independently checked this and I reproduced it against the live solver at `/home/user/yuna/src/signals.py:443-477`. For a name pinned at 25% growth with a 30× fair multiple, the hurdle solves to **56.15× TTM FCF, and the drag at that price is 11.8%/yr — fully active, nowhere near the floor.** The "34 of 65 with drag exactly zero" is measured at *today's* price. It is a diagnostic column, not a mechanism. Un-flooring the drag would not move MELI a dollar, and would move it the wrong way. This finding should be recorded in §3.1 regardless of what you rule below, because it was about to drive a change to the wrong term.

**The algebra is not the cause either.** I priced the honest five-year statement the formula is approximating — exit at the fair multiple on year-5 FCF, plus the free cash flow collected along the way, annualised. For a 25% grower exiting at 30×, honest maths permits **50.6×**. The formula says 56.1×. For a 20% grower it is 41.6× against the formula's 43.8×. The formula is a linearisation that runs about 5–11% generous. That is a rounding error next to the pathology.

**So 56× is roughly the *correct* answer to the question being asked.** The question is the problem. The formula is sincerely instructing you to pay 56× free cash flow for a business it believes will compound free cash flow at 25% a year for five straight years and then sell at 30× — and for **93 of 108 bench rows that 25% is a trailing three-year *revenue* CAGR**, capped, held flat, and implicitly assumed to convert to free cash flow one-for-one. A trailing revenue CAGR is the number that peaks immediately before it breaks. The falling-knife bias is exactly this: a stock down 60% still carries a stale high trailing CAGR that has not yet rolled through the data, so it gets the most generous licence at the moment it deserves the least.

There is one structural fact underneath it worth naming plainly. **The growth cap (25%) is larger than the return floor (15%).** Below 11.67% growth the hurdle multiple is bounded by 1/(0.15 − g) — 10× at 5%, 20× at 10% — and price is a binding constraint. Above it, growth alone clears the underwriting floor, the yield term stops being required to contribute, and the hurdle floats free of the fair multiple entirely. Twelve names sit exactly at the cap and therefore all receive the identical 56× licence regardless of business, history or drawdown.

**Corollary, and it is the finding I would most want you to see.** 93 of 108 rows are growth-derived not because 93 businesses are unmeasurable, but because `reinvestment = (capex − D&A + ΔWC) / NOPAT` is floored at zero. Every asset-light compounder — D&A above capex, negative working capital — computes a reinvestment rate of exactly zero, therefore an engine of exactly zero, therefore fails the 5pp cross-check against real revenue growth, therefore falls through to the capped trailing CAGR. This is already in the learnings (#16: ANET, AVGO, VRT). It is the upstream disease. It is outside this ruling's scope, but it is the next piece of work and it is bigger than this one.

---

### 2. Adopt immediately, no backtest — these are data, not formula

**(a) Deduct stock-based compensation from free cash flow.** I verified this live against the vendor tonight. TTD, TTM to 2026-03-31: CFO $1,093.1M, capex $256.4M, reported FCF **$836.7M**, of which **SBC is $471.4M** — added back inside CFO as a non-cash item and never deducted anywhere. Fifty-six percent of TTD's "free cash flow" is compensation paid in shares.

This is not a bug in the vendor; it is the industry-standard FCF definition. Changing it is a ruling you make, and here is why you should make it: §3.1 **freezes effective shares at the filing**, so the dilution that pays for that compensation never appears anywhere in the hurdle — not in the share count, not in the cash flow. It is free. Meanwhile Gate C1 already fails a name for net issuance above 2%/yr, which concedes the cost is real. We are simultaneously policing dilution and capitalising it at a growth multiple.

Ship conditions, non-negotiable: apply it to the **historical quarterly series as well as the TTM figure**, or you manufacture drag out of a units mismatch; re-run **Gate C1** before publishing, because `fcf_ttm` feeds the positive-FCF test at `fundamentals.py:232` and a gate failure evicts immediately with no seatbelt; and where quarterly SBC is null for any quarter in a window, fall back to reported and stamp the row, per §3.3.

Effect on TTD alone: the hurdle is linear in FCF, so $87.80 → roughly $38.

**(b) Disclose the owner-FCF split; do not adjust for it yet.** MELI, TTM to 2026-03-31, verified live: CFO $11,946.8M, capex $1,238.9M, reported FCF **$10,707.9M**, of which **the change in working capital is +$6,322.2M**. That is Mercado Pago wallet balances and funds payable to users — customer money sitting in MELI's account overnight, divided by market cap, called a yield, and capitalised. On reported FCF MELI trades at 8.9× and looks absurdly cheap. On cash it actually owns, it is roughly 22×.

§3.1 already obliges us to write an "owner-FCF note for float and credit-book businesses (reported FCF can be customer float in costume)" — line 558, currently prose only. Make it computable: persist `fcf_ttm_reported`, the SBC component and the ΔWC component on every bench row, and require all three in the C2 memo. Zero risk, and it turns an obligation we cannot currently discharge into one we can.

**Do not adopt the `max(0, ΣΔWC)` clamp that was proposed to go with it.** It was tested and it fails. Because E[max(0,X)] > 0 for any noisy X, it charges working-capital *volatility*, not float: on the 39 bench rows with the data, 15 names whose five-year mean ΔWC is *negative* — net consumers of working capital, the opposite of float — are charged anyway. VRT, whose five-year mean ΔWC is −0.1% of FCF, gets charged 15.8%. The eleven names it actually bit were industrials, hardware and oil & gas; **zero** were Credit Services, Capital Markets or Insurance Brokers, which is the reversion trigger its own author wrote. And because the historical median is rebased on the same basis, the *level* of float algebraically cancels and only its *acceleration* survives — so it does not implement "don't capitalise customer money," it implements "penalise growing float," and it can raise a hurdle as easily as lower one.

The right treatment for float is a balance-sheet one — subtract customer funds payable from the equity value in the solve, which does not cancel against a P/FCF median. That is a separate proposal, uncritiqued, and it should be worked next. Do not smuggle it into this ruling.

---

### 3. Variants to test — two, plus the control. Both are the same one-line change

I am recommending **one mechanism**, tested at two breadths. Every fade proposal is rejected (§5) and every numerator adjustment beyond SBC is deferred (§2b). This is deliberately the smallest committed set I can defend.

**The mechanism.** §3.1 asserts two incompatible things about the same company at the same instant. It says the business grows 25% a year. And it says that in five years someone will buy it at 30× free cash flow while requiring 15%/yr — which, by the Gordon identity `h = 1/M + g`, is a statement that the business grows **11.67%**. There is exactly one growth rate consistent with a fair multiple M and a required return h, and it is `h − 1/M`. So:

> **g_used = min( engine growth , 0.15 − 1/M )**

where 0.15 is your ruled floor and M is the fair multiple already defined in the next bullet. Nothing else changes. Still `ER(P) = FCF/(P·S) + g_used − max(0, 1 − (M·FCF/(P·S))^(1/5))`. Still the highest P where ER ≥ 15%. Still a solve, still monotone, the existing bisection is untouched and still exact to the cent.

**Every constant, with its justification: there are none.** 0.15 is your ruled floor. M is the existing fair multiple. `h − 1/M` is not chosen, it is read off two numbers already in the document. The change is not net-negative one parameter either — a warning to whoever implements it: **do not delete `hurdle_growth_cap` from Config.** I checked: it is consumed at `score.py:100` by `engine_waterfall`, which sets the CCN engine and therefore bench membership. Deleting it uncaps the CCN. The 25% cap stays exactly where it is; the derived cap is applied additively at `score.py:150`, after `fair` is resolved.

**Variant 1 — universal.** Apply the derived cap to every bench name.

**Variant 2 — targeted.** Apply it only where `engine_provenance == 'growth-derived'`. Measured engines keep today's treatment. This is nested inside Variant 1 and isolates exactly one question: *should a growth rate we could actually measure earn the right to pay above the fair multiple?* The flag is already on every bench row and costs nothing.

**Two consequences, both provable, neither a separate rule.** At price = M × FCF/share the expected return is exactly `1/M + g_used ≤ h`, and ER falls with price, so **the hurdle multiple can never exceed the fair multiple** — you can never be instructed to pay above min(own 5-yr median P/FCF, 30×). And because the solve therefore always lands at or below M, **the drag is provably zero at the hurdle price**, and the hurdle collapses to closed form: `hurdle = FCF/share ÷ (0.15 − g_used)`, which equals `M × FCF/share` whenever the cap binds.

#### Pre-registered predictions — committed before anything runs

These are checkable against columns already stored, without a new run, which is the point.

1. **Exact identity.** New hurdle multiple = `min(1/(0.15 − g), M)` for every name, to the cent. Equivalently `new_hurdle = min(1/(0.15−g), fair_multiple) × fcf_ttm / effective_shares`.
2. **No hurdle rises. Not one.**
3. **Every name with engine growth ≤ 0.15 − 1/M is bit-identical.** This is the regression test — if any such name moves by a cent, the wiring is wrong, not the idea.
4. **No hurdle multiple exceeds 30× (25× short-history).** Today they run 39–56× for the pinned cohort. Any hurdle multiple above 30× falsifies the proof.
5. **Size of cut, by growth and fair multiple** (ratio new/old, computed, not estimated):

   | engine g | M=30 | M=25 | M=20 | M=15 | M=10 |
   |---|---|---|---|---|---|
   | ≤11.7% | 1.000 | 1.000 | 1.000 | 0.94–1.00 | 0.84–1.00 |
   | 15% | 0.864 | 0.842 | 0.813 | 0.769 | 0.697 |
   | 20% | 0.685 | 0.671 | 0.650 | 0.620 | 0.568 |
   | **25% (pinned)** | **0.534** | **0.525** | **0.511** | **0.491** | **0.455** |

   The twelve cap-pinned names fall **47–55%**, monotonically in growth, with the deepest cuts on the names most over-trusted. Unlike every fade proposal, this correction is monotone — I checked, there is no kink and no W.
6. **Worked examples, conditional on each being cap-pinned at 25% with fair = 30×** (the bench row will confirm): MELI $6,649 → **$3,552**; TTD $87.80 → **$46.9**, and with the SBC fix from §2a compounding on top, → **~$20.5** against an $18.04 price; NOW $217.83 → **$116.4**, i.e. essentially at its $111.23 price.
7. **Counts, honestly.** At-or-below-hurdle falls from 48/65 to **34–42**. More-than-40%-below falls from 27/65 to **12–18**. Under Variant 2 both move roughly two-thirds as far.
8. **The falsifier.** If at-or-below stays at 45 or more, the growth term was not where the generosity lived, the numerator was, and the next change belongs on TTM FCF — not on growth and not on the drag. Do not respond by stacking a second conservatism on growth. That is fitting the screen to a target hit rate.

**And what these variants do not fix, stated in advance so nobody claims otherwise:** MELI stays roughly 1.9× above its price and remains "buy at half of today," because 59% of its free cash flow is customer float and no growth cap repairs a numerator. That is §2b's problem and it is unsolved tonight.

---

### 4. The decision rule — one rule, about mechanism

> **Ship the variant that breaks the link between drawdown and permitted multiple.**
>
> For each of the 65 names compute the hurdle *multiple* (hurdle price × effective shares ÷ TTM FCF) and the name's drawdown from its three-year high. Take the Spearman rank correlation between them. Under the control this correlation is **positive** — the further a stock has fallen, the higher the multiple the formula authorises us to pay — and that single number *is* the falling-knife pathology, stated exactly. The winning variant is the one that drives it closest to zero.
>
> Subject to one veto: **Zak reads the C2 memos of every name the variant surfaces at or below hurdle, with the hurdle arithmetic hidden, and they must read like compounders.** If a surfaced set does not, that variant loses however good its correlation number is.

The indicative backtest may be run and reported. **Its returns are not an input to this decision.** Two years of bars cannot distinguish these variants and any ranking it produces would be noise dressed as evidence.

If both variants pass, ship **Variant 1** — it is simpler and it makes the least reliable number in the system (the growth-derived CAGR) irrelevant to the price we pay, while it continues to drive ranking through the CCN. If neither passes, ship neither and go fix the FCF numerator.

---

### 5. Rejected, with reasons, so they do not come back

- **Fading growth to the 10-year Treasury.** The five-year fade, the helper function and the config key compute `(g + r_f)/2` to within 0.35pp across the entire relevant range — it is a chosen 50/50 weighting wearing an integral as a disguise. It also imports a **wrong-signed** rate coupling into a system that has none: because the floor is fixed, a *higher* 10-year yield produces a *higher* hurdle, worth 7–12% per 100bp in the 10–18% growth band where the bench actually lives (the proposal disclosed 3%, sampled only where it is mildest). Varying the terminal from 4.75% to 0% moves the answer 12%; the other 88% is the fade itself. It buys a small share of the effect for all of the complexity.
- **The `max(0, ΣΔWC)` owner-FCF clamp.** See §2b. It is a noise rectifier, not a float detector, and it failed its own author's stated reversion trigger.
- **Halving growth / gliding to zero.** The cut is non-monotone and is **deepest at 15% growth (−62%) and shallowest at the 25% cap (−45%)**, so the cap-pinned cohort's advantage over the rest of the bench *widens* from 1.6× to 2.3×. It also asserts zero terminal growth while continuing to pay a 30× exit multiple — two different growth rates about the same company in the same line.
- **Any fade shape at all.** Three equally defensible shapes (linear-to-zero, glide-to-half, geometric decay) span a **5× range** in the resulting hurdle multiple. That makes the shape a high-gain dial with a respectable one-line derivation available for any value it is set to. The next disappointing bench will turn it. This system has been bitten by precisely that.
- **Correcting the linearisation to exact five-year compounding.** Mathematically right and it changes almost nothing — 50.6× instead of 56.1×. Not worth a change.
- **Moving the 15% floor.** All four schools left it alone and so do I. It is doing its job; the inputs were not.

---

### 6. What you must personally rule on

1. **Do we ever pay more than what this stock has historically been worth?** Variant 1 says no, ever: entry is capped at min(own 5-yr median P/FCF, 30×). Variant 2 says yes, but only where we could actually *measure* the engine. This is a strategy decision, not an engineering one, and it is the whole content of the variant choice. Variant 1's real cost: the entry price stops distinguishing a 30% compounder from a 13% one, and a great business with a cheap trading history gets a cheap hurdle. Variant 1's real benefit: the number we trust least stops setting the price we pay.
2. **Is stock-based compensation a cost?** §2a. It changes the definition of free cash flow across C1, the CCN's cash-conversion component, the hurdle and the P/FCF median. It needs your signature, not an engineer's.
3. **The short-history fair multiple is circular and must be repealed.** §3.1 sets `fair = min(current P/FCF, 25×)` for names with under three years of history. Because `effective shares = market cap ÷ the close on the cap's as_of date`, that expression makes `fair × FCF/share` **identically equal to the filing-date close** — algebraically, not approximately. Under Variant 1 the hurdle for every such name becomes exactly its own filing-date price, and "gap to hurdle" degenerates into "has this stock fallen since its last filing." Rule one of: flat 25×, or short-history names get no hurdle and are not buyable. I recommend flat 25×.
4. **Where the margin of safety lives.** §3.1 says "the drag is never a credit — the margin of safety lives here." Under both variants the drag is provably inert at the hurdle price. The sentence must move to the fair multiple. This is a repeal, presented as one, not an untouched bullet.
5. **Float and credit-book names in the interim.** MELI is unfixed by anything here and its top-of-book CCN is computed on a cash-flow figure that is 59% customer money. Rule whether such names stay hurdle-eligible while the balance-sheet treatment is worked, or are quarantined from entry with the reason recorded.
6. **The reinvestment floor.** Not a ruling tonight, but authorise the work: `reinvestment` flooring at zero is what pushes 93 of 108 names into the growth-derived fallback, and it does so hardest to exactly the asset-light compounders this sleeve exists to own. Fixing it is worth more than anything in this document.

---

Files: `/home/user/yuna/docs/yuna_plan.md` §3.1 (Entry hurdle bullets, lines ~232–240; owner-FCF obligation line 558); `/home/user/yuna/src/score.py:65` (leave `hurdle_growth_cap` alone), `:143-144` (short-history fair), `:150` (apply the derived cap here), `:181` (drag becomes diagnostic-only); `/home/user/yuna/src/signals.py:443-477` (`expected_return`, `hurdle_price` — **no edit required**); `/home/user/yuna/src/fundamentals.py:216` (TTM FCF), `:221-228` (quarterly series — the SBC fix must reach both), `:232` (C1 positive-FCF); `/home/user/yuna/src/backtest_compounders.py:32,46` (a **duplicate** hurdle solver with its own hard-coded constants that does not call `signals.expected_return` — fix or delete it in the same change, or the backtest will silently measure the old formula).
