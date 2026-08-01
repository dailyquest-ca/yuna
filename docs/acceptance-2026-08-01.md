# Acceptance run — the whole cadence, fresh, on production

*Deployed `01e62fc` to `main`, then dispatched every scheduled job in cadence order against live
data. Nothing stubbed, nothing dry. This is what a Product Owner sign-off pass produced.*

## The run

| Step | Result |
|---|---|
| `monthly-funnel` · L0 census | **green** — 2,761 names |
| `monthly-funnel` · fundamentals | **green** — 23 filings (STALE_ONLY, the cadence's own setting) |
| `monthly-funnel` · score | **green** — 65 ranked · 200 not bench-eligible · 48 at-or-below hurdle |
| `weekly-rank` | **green** — effective L0 2,332 · L1-M 150 · 18 BUY · queue 20 · **143 industry groups** · gate ON |
| `nightly-ingest` | **green** — 65,677 bars |
| `duties` | **amber, correctly** — the quantity canary (below) |
| `verify` | **green — zero causes across all five checks** |

## What the acceptance actually proves

**`verify` is clean for the first time.** Five independent checks, each re-deriving a published
number from stored inputs: every hurdle reproduces the 15% floor · every gap agrees with the close
and hurdle beside it · every CCN is the mean of its own stored components · every scored row
declares an engine and a provenance · no hurdle's share count tracks the quote. This morning the
same job was amber on 13 hurdle mismatches.

**The industry wipe is gone.** 2,731 of 2,762 L0 names carry an industry, against 654 before. MCN's
group-strength component now scores against 143 real groups instead of returning a flat neutral 50
for three-quarters of the field, and §2.2's two-per-group cap has real groups to count.

**Durability and the waterfall hold under `verify`.** 108 bench rows, every one carrying a
provenance — 15 `measured`, 93 `growth-derived`. Zero dropped engines anywhere, which is the state
§3.1 now makes impossible. The 43 unranked rows are §3.1's two-month seatbelt, each refreshed with
current numbers rather than frozen at the scoring that ranked them.

**Both canaries fired the way they were designed to.**
- The §4.2 valuation canary stayed silent — all seven holdings priced at their latest bar, so the
  run was not red.
- The quantity canary went amber on all seven: *"last confirmed never."* Not one position has a
  confirming transaction behind it. That is true, it is worth saying every night, and it is exactly
  the failure a price check cannot see.

**Arming is conformant.** Seven momentum entries, lowest MCN 70.6 — no sub-70 name armed at all,
where the trial armed five. Every row names its account (TFSA, §2.6), its currency and FX estimate,
and its risk in C$ **and** as a % of NAV: 0.234%–0.250%, at or under the 0.250% start-low budget
(0.5% × the 50% first tranche). ACA sits at 0.103% because a tight stop pushed size into the 12%
band ceiling before the budget was spent — §3.2 makes the band cap the budget, so lower risk there
is the rule working, not a miss.

**One day, one NAV.** A single `nav_snapshots` row for the date, at C$200,954.12. Effective bets
2.83. `armed` now holds 17 rows across 2 run ids — the ledger §4.3 legislated, instead of a table
truncated nightly.

## What this run did NOT exercise — read no signal into these

1. **The compounder entry path.** No bench name is approved, and §3.1 only arms
   `approved AND c1_pass AND last_close <= hurdle`. So the GTC-limit-at-hurdle order, the §2.6
   account routing with its funding check, and ceil-into-band sizing were all built and unit-tested
   but never ran against production data. They need an R5 approval first.
2. **Adds from the entry fill.** Same reason — plus no holding is a compounder yet.
3. **Sleeve ceilings, the 35% theme cap, and the two-per-group check on the book.** All seven
   holdings read `sleeve='unassigned'` with `theme` null, so these rules computed against
   `unassigned` and passed vacuously. Phase 0 step 2a is what makes them real.
4. **Protective exits.** Zero protective rows tonight — no stop fired, no gap, no gate flip. The
   paths are tested in the integration suite, not by this run.
5. **The five sessions.** R1–R5 are Routines, not jobs; this pass covered the machine that feeds
   them.

## Standing gap

`verify` green is the gate the build plan set for Phase 0, and it is now met. The honest read is
that **the compute layer is accepted and the judgment layer is untested in production** — which is
the right order, and the next step is Phase 0 step 2a, where the sleeve and theme assignments turn
five vacuous checks into real ones.
