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
27. **A human writes prose; a job reads tokens. Canonicalise once, in the database.** Yuna logs
    verdicts the way a person does — `PASS`, `ESCALATE`,
    `QUARANTINE — owner-cash (§3.1), not entry-eligible; PASS/FAIL deferred to R5` — and every
    reader asked `verdict in ('pass','fail')`. Sixty-eight rulings were invisible on 2026-08-07:
    the payload called 44 already-ruled names unruled, the nightly armed a name ruling 66 had
    quarantined, and every growth-derived candidate sat behind a §3.3 sign-off the ledger had
    already granted. The verdict should stay prose — the memo is the point — so the parsing lives
    in `yuna_verdict()` and `v_rulings_latest`, once, where every reader must pass through it.
    **Corollary:** when a job starts reading a table a session writes, the interface between them
    is now load-bearing and needs a test that writes the way the session actually writes.
28. **A gate nothing can open is worse than no gate.** §3.3 capped incompletely-scored names and
    "required manual sign-off", and no path in the system could ever grant one — so 13 of 19 armed
    rows were parked behind it indefinitely, which reads to the desk as the machine being broken
    rather than as the machine being careful. Every blocking condition needs a named key and
    someone who holds it; if the key is a judgment, the judgment needs a row a job can read.
29. **The clean-slate list must cover ledgers the jobs *read*, not just the ones they write.** The
    harness derives its truncate list from the guard triggers, which by construction only cover
    job-written tables. `rulings` is session-written and therefore unguarded — so a ruling from one
    test governed every later test *and every later pytest run*, since the database outlives the
    process. Found on a sign-off no test in that file had logged. Ledgers leak in the direction
    nobody is watching.
30. **A denormalized membership flag will drift, in both directions at once.** `universe.is_holding`
    still said VRT (closed 2026-08-05) and had never heard of NUE or RS (filled 2026-08-04),
    because nothing maintained it — so the queue seated a position we had sold and dropped two we
    owned. §3.0 says membership lists never drop a name the book owns; the way to keep that true is
    to ask the book at run time and re-derive the flag from it, never to remember separately.
31. **A guard calibrated on the defect it caught will fire on everything that resembles it.** The
    price-basis fix came with an integrity guard that halted the run on any adjusted daily move
    beyond 85%. Measured against the real tape it condemned **819 of 5,264 names** — the
    re-derivation of runs 18-44 could never have started. Worse, the second draft counted moves
    in *both* directions and quarantined GME, DJT, LUNR, INSM and CHK: the January 2021 squeeze
    (+93% then +135%), the Trump Media announcement (+357%), a lunar-lander contract, a phase-3
    readout. **A data guard that deletes the decade's biggest momentum events from a momentum
    backtest is worse than no guard**, because it removes precisely the trades under study, and
    it does it silently — the run still completes and still prints a number.
    **The asymmetry is the fix:** falling is evidence, rising is momentum. After a real -85% the
    price sits at 15% of its old level, so a second one from above $5 needs a ~6.7x recovery in
    between, which equities do not do. Repetition *down* is a discontinuous series; repetition
    *up* is the thing we are hunting.
    **Corollary, and the more general lesson:** every threshold in that guard was picked by
    querying the tape and counting what it would condemn, then checking the survivors by name.
    Three candidate rules were measured and discarded before one held — magnitude alone (cannot
    separate Yellow Corp's bankruptcy from a broken series), share-of-names (19.5% on a raw
    basis against 15.6% on an adjusted one, so no threshold sits between them), and the
    corporate-action record (`corporate_actions` holds four split rows, all from August 2026 —
    a live feed for the book, not a historical archive). A threshold that was never counted
    against the data is a guess wearing a constant's clothing.
32. **Distinguish a broken security from a broken tape, or you get neither.** The first guard
    conflated them and so had exactly one response — halt — to two problems with opposite
    remedies. One bad ticker among 5,264 should be *removed*; the same symptom across the whole
    universe means the price basis is wrong and nothing can be trusted. The gate now halts on a
    tape invariant asserted directly (the decision series must differ from the raw print on at
    least 20% of bars; the real tape differs on 58.9% across 2,999 names), quarantines individual
    securities with a named reason recorded in `stats.excluded_discontinuous`, and halts anyway
    if the quarantine exceeds 10% of the universe — because at that point "bad tickers" is the
    wrong diagnosis. Current reality is 2.70%.
33. **The invalid unit is often the bar, not the security.** Vendors pad the delisting tail with
    `0.0000` after an acquisition — CONN 5 bars, HIBB 7, AEL 2, PACW 1. Condemning the ticker
    throws away years of valid history *and* biases the sleeve against takeouts, which are the
    good ending for a momentum position. Masking those bars to NaN — which is already what "no
    bar" means to the engine — cut the traded-name casualty list from 16 to 5. Before excluding
    a thing, check whether the corruption is the whole thing or one row of it.
34. **The run that "improved suspiciously" was the clean one; the old run was contaminated.**
    Run 46 came back +5.65% where run 18 said -4.55%, with drawdown halved, immediately after a
    change to data handling — which `.claude/rules/trading-code.md` says to treat as a look-ahead
    bug until proven otherwise. The obvious innocent story was wrong: splits were NOT arriving as
    crashes in the trade list, and the proof is that both runs have **zero** trades losing more
    than 12% and an identical worst trade of -9.87%. An 8% stop cannot produce a -50% trade, so
    if the defect had been reaching the book that way it would have been visible there. It wasn't.
    The real mechanism ran the other way. ADDV was computed as `raw_close x volume` while volume
    was already split-adjusted, so a name's *past* liquidity was inflated by its own *future*
    split factor — CMG's pre-split ADDV read $79bn, 660 names were affected, and 170,220 name-days
    entered L0 on the strength of it alone. **Run 18 had the look-ahead. Run 46 removed it**, and
    the names it stopped admitting were junk that lost money: the 147 trades that vanished lost
    $7,857 between them, and they are ~1.8x more likely than the retained trades to sit on a name
    that later split 2:1 or more (8.8% against 4.9%).
    Two lessons. **A result improving after a data fix is not by itself evidence of a new bug — it
    is equally consistent with removing an old one**, and the way to tell them apart is to name the
    mechanism and find it in the data, not to argue from the direction of the number. And the
    reason this could only be *partly* settled is that the law surface changed between the two runs
    while `law_stamp` stayed at 2026-08-09; with the stamp broken, no two runs can be cleanly
    differenced, so a residual will always remain unattributable. Fix the stamp before trusting
    any delta.
35. **A guard that ran and wrote rows is not a guard that worked.** Three migrations have now
    attacked duplicate listings — 045 by hand, 047 on sampled closes, 048 on sampled daily
    returns — and each one completed, inserted a plausible number of exclusions, and left behind
    the case its own header named as the motivating example. 047 compared closes with exact float
    equality at a 99% bar; BBBY_old against BBBY agrees on 2,245 of 2,274 shared closes — 98.72%,
    short by 0.28 points on sub-cent vendor rounding. Its byte-exact sibling BYON was excluded, so
    the migration looked like it had handled the group. 048 moved to daily returns, which is the
    right invariant, and then kept a 1e-9 tolerance that splits the duplicate population in half:
    on the current tape SPWR_old/SPWRQ scores 0.467 exact and 0.952 at 1e-4, BALL/BLL scores
    0.0015 and 0.994, and both are one company.
    **Two general lessons.** A tolerance has to be looser than the noise it must survive: two
    vendor copies of one series, quoted in cents, differ in the fifth decimal of a daily return
    from rounding alone, so any test tighter than that measures the vendor's rounding rather than
    the securities. And **evidence baked into a migration goes stale the moment the data moves** —
    both files sampled eight dates in 2018-2025, so when the backfill extended the census to 2005
    every pair that died before 2018 (ANR/ANRZ, WLT/WLTGQ, TBSI/TBSIQ) became invisible to both,
    and the series the thresholds had been calibrated against were re-fetched underneath them.
    048 had recorded BBBY as unfixable residue — "plainly below any threshold this file could
    defend" — which was true of its tape and false of the tape three days later.
    The remedy is that the scan is now a job (`src/dedupe_scan.py`), takes its probe anchors from
    the benchmark's own session list rather than hard-coded dates, and **reports the census
    distribution before proposing a threshold**. Measured across the co-held pairs, duplicates
    score 0.85-1.00 on daily-return agreement and genuinely different securities score 0.006-0.033
    — a 25x gap with nothing in it. The cut is the geometric midpoint of the widest gap the scan
    actually finds, and it proposes nothing when no gap is there. A threshold read off a bimodal
    distribution is a rule; the same number written into a file is a guess with a good history.
36. **A blank `workflow_dispatch` input is set, not unset, so `os.environ.get(k, default)` never
    fires.** The park, calendar and window became env-level for WO-A9's deep test, and the
    workflow passes `PARK: ${{ inputs.park }}` — which for a blank input is the empty string. Four
    dispatches died on `contains no session of ,` before the cause was obvious, and the workflow's
    own help text said blank meant the default. Use `os.environ.get(k, "").strip() or default`.
    It failed loudly, which is the only reason this cost runs instead of a silently mis-parked
    equity curve — the window guard added alongside those inputs caught the empty calendar. The
    general form: **a default that only fires on `KeyError` is not a default in a CI environment**,
    because CI sets everything it mentions.
