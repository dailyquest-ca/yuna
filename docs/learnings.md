# Learnings — the scar tissue

Facts this build paid for. Every line here is still true as of 2026-07-31; anything that stopped
being true was deleted rather than archived. Not law — the law is `yuna_plan.md`. The build order
is `roadmap-2026-07-31.md`.

## The vendor (EODHD)

1. **Pull broad, filter locally.** The symbol filter on the earnings calendar and the section
   filter on fundamentals both lie. Client-side filtering is the law of this codebase.
2. **The screener is a decorator, never a census.** `market_capitalization` is null for most US
   names. Full-tape truth is `eod-bulk-last-day` (≈1 call per 1,000 symbols).
3. Screener `offset` hard-caps at **999** → paginate by market-cap band descent. One condition per
   field per call (dual bounds risk a 422). Never let a null cap update a descending ceiling — one
   bad row collapses the sweep to `< $1`.
4. **`General.CurrencyCode` and `CountryISO` lie for depositary receipts.** TSM reads USD/US and
   files in TWD. `Financials.*.currency_symbol` and `General.PrimaryTicker` tell the truth. EODHD's
   own `PriceSalesTTM` divides a USD market cap by TWD revenue, so its ratios cannot cross-check it.
5. **A fundamentals request bills 10 units.** Three sweeps of L0 is 84k of the 100k daily budget.
   Ask the usage endpoint before spending, and truncate the sweep rather than dying two-thirds in.
6. Ten concurrent workers draws occasional 429s; eight does not.

## Postgres / Supabase

7. **A view defined `select *` freezes its column list at creation.** Any migration that adds a
   column to `fundamentals` must recreate `v_fundamentals_latest` in the same file.
8. **`%s is false` inside a batch statement failed silently**, the flush fell back to row-by-row,
   and the fallback skipped a per-row step — so a whole column came back null and a bad name
   sailed through. **Anything that degrades must reach the heartbeat, never just stdout.**
9. Storage discipline is real: 2.2M price rows ≈ 285 MB. Backups exclude bars by design (they are
   a vendor-re-pullable cache); the 3-year prune is not optional.
10. Guard triggers keyed on `current_user` carry no session state, so a pooler cannot silently drop
    them. That is why the "jobs compute, sessions judge" boundary is role-based.

## GitHub Actions

11. **Cron `dom` and `dow` are OR'd** — `0 10 1-7 * 6` fires every day 1–7 *and* every Saturday.
    Schedule weekly and guard the date in-job.
12. A dispatch seconds after a push can check out the **stale** ref. Wait, then assert the run's
    `head_sha` is the SHA you pushed.
13. **Run and job log downloads are unreachable** (302 → blob store → 403 even unauthenticated).
    The heartbeat is the only reliable diagnostic: fatal handlers embed tracebacks, and the
    `if: failure()` autopsy step catches deaths that happen before the heartbeat opens.

## The formulas, as implemented

14. **§3.3's data-confidence rule renormalizes around *one* missing component.** Size is available
    to almost everything, so without a floor a company whose engine and cash conversion are both
    unmeasurable scores on smallness alone — a $4 ethanol microcap topped the first bench. The
    current floor (≥2 components, at least one a business measure) is a builder's rule, not the
    plan's, and is on the ratification list.
15. **The engine reliability check is the load-bearing part of the hurdle.** Growth dominates
    expected return, so a loose tolerance lets a 7% grower underwrite at 16%.
16. **Reinvestment comes out at zero for asset-light compounders.** ANET, AVGO and VRT all show
    `reinvest_rate = 0` because working capital released more cash than capex consumed, and §3.1
    floors reinvestment at 0 — so the engine reads 0 for a company growing 27% a year. The
    implementation is faithful; the consequence is that the CCN systematically ranks
    negative-working-capital compounders last. This wants a plan decision, not a code change.
17. **Everything the hurdle surfaces is a de-rated former high-multiple name**, because `fair` is
    the stock's own median P/FCF and the drag is never a credit. That is the design working — but
    it means the buyable list will always look like a fallen-growth screen.
18. **An amber must mark its own domain stale, not the whole machine.** Two ways this nearly
    bricked trading: 30 permanently unscorable shells (SPACs, preferreds) held the pipeline amber
    forever, and the freshness gate treated any amber as blocking — so a Friday debugging session
    would have stopped Monday's orders. Only the price feed gates tickets. Freshness must also read
    the *latest* run per job, not every run in the window.

## Postgres / Supabase, continued

25. **Never `force row level security` on a table a job writes.** FORCE applies RLS to the table
    owner as well, so the nightly job loses the ability to write its own brief — on the last line
    of the night, after every conclusion has been computed. Plain `enable row level security` keeps
    default-deny for anon/public and leaves the owner free; the write boundary is carried by the
    guard triggers and the `yuna_session` grants, which is what §4.3 actually describes. Caught in
    review, reverted in `021`, before it ever ran a night.
26. **Status reads lag — from both APIs, by minutes.** A run that had already finished red kept
    reading as `running` across several Supabase MCP queries, and the GitHub Actions API reported a
    job `in_progress` for four minutes after it had finished successfully in 43 seconds. Never
    conclude a job is slow or hung from a status read alone: check the finished timestamp against
    the clock, and prefer the artefact the job leaves behind (a `runs` row, a committed file) over
    any API's opinion about whether it is still running.

## Process

19. **Green is not a result.** Every serious defect shipped green: 9 trades in two years, a $4
    microcap ranked #1, a 1.6× P/FCF on the buy list. The heartbeat proves a job *ran*, never that
    it was *right*. What works is cross-checking the model's own output against an independent
    query on the raw data — the SQL saying 29% of breakouts confirm on volume is what exposed a 2%
    simulation.
20. **Write the check before the feature.** Four of seven bugs in one session were unit-testable in
    ten lines. None were written, because each piece looked obviously correct. They always do.
21. **A rule stored is not a rule enforced.** Twelve config keys and five schema columns encoded
    plan rules that no line of code read. Seeding a value *feels* like implementing it. Therefore:
    **seed a config key in the same commit as the code that reads it**, never earlier.
22. **When the plan describes a mechanism, implement the mechanism, not the intent.** §5.1 says the
    volume condition is verified *after* the order fills. "Refuse to enter" is a different system,
    and it returned nine trades.
23. **Say the deviation out loud, at the time.** The announced ones caused no trouble. The
    unannounced ones — theme = sector, the base-detection algorithm — are the ones that mattered.
24. **Verify magnitudes, not just status.** A green census with 688 names was wrong three times
    before it was right at 2,783. Broker screenshot beats stored records; reconcile against
    reality, then migrate the correction (`003_seed_fix.sql` is the precedent).
