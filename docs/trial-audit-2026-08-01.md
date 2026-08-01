# Trial-brief teardown — three rounds, adversarial
*Yuna · 2026-08-01 · scope: yuna_trial_briefs.md (Parts 1 + 2) · method: every number re-derived from source (DB full-precision recompute, live vendor cross-check, independent arithmetic), picks judged against practitioner standards, voice judged against §5.0*

**Severity key:** ❌❌ critical · ❌ must-fix · ⚠️ should-fix · ✅ verified clean

---

## Round 1 — Engine: is every number clean?

### ❌❌ F1 · AVGO is valued at a stale price — NAV is wrong, and everything downstream inherits it
Live vendor cross-check of six closes: MEDP 577.11 ✓ · VEEV 203.78 ✓ · DELL 405.37 ✓ · CNQ.TO 66.78 ✓ · ISRG 353.33 ✓ · **AVGO 389.28 vs ~300.41 implied by the book ❌.** The `prices` table itself is **clean** (07-31 bar = 389.28, matches live to the penny) — the bug is in the **agent's positions/NAV valuation**, which prices 39 AVGO shares off a stale bar. Six holdings reconcile against real closes; one doesn't.

**Corrected shadow numbers:** NAV **~$205,813** (briefs used 200,954 — understated C$4,859 / 2.4%) · AVGO weight 10.3% not 8.2% · AI-infra theme 24.9% not 23.1% (still ✓ <35) · effective bets 2.88→**2.73** before, 4.12→**4.05** after fills, ~4.2→**4.17** after DELL (all conclusions survive; the digits don't) · 12% sizing = C$24,698 → under the ceil-into-band share rule the tickets become **MEDP 31 sh · VEEV 87 sh** (DELL's risk-budget sizing floors instead — stays 9). *Proposed handoff fix: agent repairs the valuation join + §4.2 `verify` gains a hard rule — every holding's valuation price must equal its latest `prices` bar, mismatch = FAIL.* My own process gap, closed: the trial's penny-verification covered the compounder ten but not the seven holdings. Every book name is a canary now.

### ❌ F2 · Both C2 memos misstate engine provenance — a §3.1 marking-law violation
Source of truth: `engine_agrees` = **false for MEDP, VEEV, NOW, ANET**; true only for **ADSK**. The R5 memos said MEDP *"engine measured… cross-check agrees"* (repeated on the Monday MEDP ticket) and implied the same for VEEV. Wrong: both engines are **growth-derived** (capped 3-yr revenue CAGR — MEDP 20.1%, VEEV 14.0%). §3.1: growth-derived is *"marked on the bench row and every memo that cites it"* + bottom-of-band + manual sign-off. Sizing consequence today: none (flat 12% collapses the band; Zak's approval = the sign-off). Text consequence: real. Corrected memo line: *"engine growth-derived (observed 3-yr revenue growth, capped) — measured engine failed the ±5pp cross-check; guardrails apply."*

### ❌ F3 · DELL risk "0.16% NAV" — FX dropped
True risk = 9 sh × $37.56 = US$338 = **C$474 = 0.24% NAV**. The 0.16% is US$338 ÷ CAD NAV — a unit mix. (Budget sanity: step-1 targets ≤0.25%; 0.236% after whole-share rounding ✓ — the *position* was sized right, the *label* was wrong.)

### ✅ F4 · Hurdles, ERs, gaps — exact to the digit
Full-precision recompute under the law (drag floored at 0 — never a credit ✓):

| Name | Close | Hurdle | ER@close | Gap | Briefs said |
|---|---|---|---|---|---|
| MEDP | 577.11 | **880.09** | 24.68% | −34.4% | 880.09 / 24.7 / −34 ✓ |
| VEEV | 203.78 | **240.46** | 19.08% | −15.25% | 240.46 / 19.1 / −15 ✓ |
| ADSK | 234.20 | **288.07** | 20.13% | −18.7% | 288.07 / 20.1 / −19 ✓ |
| NOW | 111.23 | **185.75** | 26.42% | −40.1% | 185.75 / 26.4 / −40 ✓ |
| ANET | 180.35 | **210.11** | 18.22% | −14.2% | 210.11 / 18.2 / −14 ✓ |

(My first hand-check bracketed MEDP at 841–889 — that spread was entirely my 1-decimal reconstruction of FCF; actual $733.5M pins it: 880.09 is mathematically exact.)

### ✅ F5 · Independence math — exact
Effective bets recomputed from the 126-day matrix: **2.88** before, **4.12** after MEDP+VEEV, **4.25** after DELL (printed "≈4.2" — inside its stated ≈; DELL pairs now pulled: 0.34–0.35 vs ANET/AVGO, −0.08 vs ISRG). On corrected AVGO: 2.73 / 4.05 / 4.17 — the "crosses into the 4–6 band on day one" conclusion **holds either way**.

### ✅ F6 · Everything else passes
M1 gate (+5.27% above, −5.0% to flip) ✓ · DELL pair internals (stop = trigger×0.92 exactly; trigger +15.8%; step-1 = 50% of a 6.25% full position) ✓ · MEDP 30 sh = 12.08%, VEEV 85 sh = 12.08% (both round *up* into the 12–15 band) ✓ · theme 30.57% / room $8.9K ✓ · deployment 58.4%, TFSA cash 46,238.31 ✓ · blackout wall dates ✓ · RRSP gap $1,367 ✓ · NAV invariance ✓.

### ⚠️ F7 · Cosmetics (three)
"583.00 (+1%)" is +1.02% · "≈US$4.5K" is the pre-rounding 9.54-share figure (ticket is US$4.2K) · sell limit printed 418.96, computed 418.95 (1¢).

### ⚠️ F8 · Boundary semantics
VEEV sits at −15.25% — just past the add-rule's ">15%" edge. Exactly −15.00% falls in the 50% band as written. One clarifying word in §3.1 (≥ vs >) someday.

---

## Round 2 — Picks: sane? Surprising?

**Compounders — the crown is legible to any practitioner.** MEDP (founder-led CRO, ~29% ROIC floor, buyback machine), VEEV (vertical-SaaS monopoly in pharma), ADSK (design-software duopoly) are precisely the businesses a Fundsmith/Akre screen blesses — and the machine wants them *below* fair, which is rarer discipline than the street's. The WAITs are as informative as the buys: **CORT at +170% above hurdle despite CCN 85.8** is the teaching case (conviction score ≠ price permission), NOW's −40% gap is quarantined on an unverified split rather than chased, and PDD/WSE/MELI sit in FX/identity/float quarantine — the system catching its own data instead of buying it.

**The honest caveat, said plainly: 58% of the scored field is growth-derived.** Among our five, only ADSK carries a measured, cross-checked engine. Today the "compounding engine" is mostly *revenue growth in a trenchcoat* — the waterfall marks it and guards it, but the label must actually appear (F2), and the R5 eye should weight measured engines a notch until the backfill lands.

**Momentum queue — a screen's face, correctly throttled.** The top is recognizable O'Neil/Minervini structure: DELL (AI-server cycle), RS/NUE tight bases in a steel upcycle, DDOG re-basing. Character notes for the R5 eye: ① **RS + NUE are the same industry** — if both ever enter, the 2-per-group cap binds and they're one bet wearing two tickers (the bets math would say so out loud). ② **BMA/YPF**: Argentine ADRs passing M4 on EPS through triple-digit inflation is a data mirage risk — suggest an R5 footnote when EM ADRs crest the queue. ③ SHO: legal, but M4-on-REIT-EPS is quirky (FFO is the native metric) — flag, don't block. ④ EBAY passing M1–M4 is the screen being honest, not inspired; the Zak veto exists for exactly this. ⑤ GWW's WAIT was **vindicated** — my independent base check found the pattern already broken.

**❌ F9 · DELL's ticket has no theme assignment.** Law: theme recorded on the ticket. DELL is AI-infra — post-fill the theme reads ~26% of (corrected) NAV, legal but it must be *printed*, because that theme's headroom is the scarcest in the book.

---

## Round 3 — Voice, clarity, customer-grade

**❌ V1** · Fri R2: "ANET **enters** earnings blackout Monday" — false. Blackout began ~7/28 (5 sessions pre-8/4). Wording rewrite.
**❌ V2** · Tue R1 stub omits **CNQ's 8/6 report** from its own blackout wall (a holding!). Each brief restates its full wall — no leaning on yesterday's.
**⚠️ V3** · R3 renders the queue as prose; §5 specifies a queue **table**. Tables scan; paragraphs hide.
**⚠️ V4** · Effective-bets line appears on the MEDP ticket but not VEEV's — law says every draft ticket. Print per-ticket (or label the shared figure on both).
**⚠️ V5** · Gap sign convention (−34% = *below* hurdle = good) is never keyed. One parenthetical in the first table fixes every future reader.
**⚠️ V6** · Part 1's Monday brief and Part 2's REVISED Monday coexist — fine as a rehearsal log, confusing as a customer artifact. A one-line "superseded ↓" banner on the old brief solves it.
**⚠️ V7** · The MEDP "calendar gap" flag over-alarmed: a July reporter absent from a forward-only calendar has most likely *already reported* (next ~late Oct). Correct flag: "confirm last-report date," not "unusual."
**✅ V8** · What's working: summary-first everywhere · broker-ready ticket blocks · "You:" line closes every R1 · one emoji per brief, charm in the sign-offs not the numbers ("The compounder sleeve turns on today, Z") · flat register held on all seven flags · memos ≈200 words · results panel leads with the table. **Customer-proud after the fixes above — yes.** The structure survives adversarial reading; the seven wording/format items are exactly the kind of polish a dress rehearsal exists to catch.

---

## Round 4 — fresh sweep (stragglers)

**⚠️ R4-1** · Compounder entry order type is unlegislated: a *day* limit can miss while the name stays below hurdle, but the law says "enter immediately." Propose: **GTC limit at the hurdle price** (fills anywhere at/below, self-expires when the thesis changes) — needs your ruling.
**⚠️ R4-2** · FX hardcoded at 1.402 on tickets; add "at prevailing FX (est. 1.402)" so a moved rate doesn't orphan the share counts.
**✅ R4-3** · Verified consistent: throttle + queue-priority application (proximity-0 compounders outrank DELL) · trial assumptions labeled as assumptions · NOW split quarantine held · duplicate 07-31 nav rows already flagged · instant-add / sub-70 / RRSP items already on your desk.

---

## Verdict

| Axis | Score | The one-liner |
|---|---|---|
| Engine | **B+** → A after F1–F3 | Formulas exact to the digit; one stale-price valuation bug (agent's, caught by live cross-check) and two labeling errors (mine) |
| Picks | **A−** | Crown any practitioner would recognize; caveats are data-provenance, not judgment — and the system quarantined its own worst inputs |
| Voice | **B+** → A after V1–V7 | Structure, register, and charm hold under hostile reading; seven wording/format fixes |

**Fix queue (on your word):** briefs **v2** with all ❌/⚠️ corrections + corrected-NAV numbers · handoff note: AVGO valuation-join bug + new verify rule (holding price must equal latest bar) · three standing rulings unchanged (instant-add, sub-70, RRSP letter) + one new (compounder order type, R4-1).
