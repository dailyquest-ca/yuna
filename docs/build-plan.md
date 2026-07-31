# Yuna — build plan to full plan-conformance

*Draft 2 · 2026-07-31 · against `docs/yuna_plan.md` (16:37 UTC stamp) and `docs/audit-2026-07-31-v4.md`.*

**Purpose.** Get the running system to do exactly what the plan says — no more, no less — at a
quality and security standard fit for a system that touches CAD 200K of real money.

**This plan is not the law.** `docs/yuna_plan.md` is. Where this document and the plan disagree,
the plan wins and this document is wrong.

---

## 0. Standing rules for every step

These apply to all work below and are not repeated per step.

**Definition of done.** A step is done when *all* of:

1. The clauses it claims are `wired` in `src/yuna/rules.py`, verified by the call-graph test —
   not asserted.
2. For every clause it claims, a **substitution test**: monkeypatch the policy function to
   return a sentinel and assert the job's output changes. The call-graph test sees a call
   expression; it cannot see the inline duplicate still deciding beside it — which is the exact
   failure the audit found seventeen times. Without this, adding `from yuna.policy import
   initial_stop` and calling it in a log line flips `3.2/stop-8pct` to wired while
   `phase0.py:161` still sets the stop that goes on the ticket.
3. Tests exist that would fail if the rule were wrong, written against the **plan text**, not
   against the code's current behaviour.
4. `ruff`, `mypy` (strict list) and `pytest` pass — and CI asserts the `db`-marked selection
   collected more than zero tests and did not skip all of them. "pytest passes" is otherwise
   satisfied by a suite that never ran.
5. **Compute gate.** The change ran once in production with `DRY_RUN=true` and the heartbeat
   carried *the numbers the step changed*, not a count of them. Every job wraps its writes in
   `if not dry()`, so a dry heartbeat of counts is a liveness check, not a diff: halving the
   entry ticket produces a byte-identical `phase0` dry heartbeat today. Any step that alters a
   written value must surface that value in `hb.detail` — per-ticket qty / trigger / limit /
   stop for S9, per-name pivots for S7, the deduped key set for S7.7 — and the step names the
   `jsonb` diff against the last live run that constitutes the comparison.
6. **Write gate.** The change was exercised against S10's throwaway Postgres with
   `DRY_RUN=false`, asserting the rows that land. Steps that ship before S10 defer this gate and
   run nothing live until S15's recompute, which is after S10.
7. Migrations have **no** `DRY_RUN` — `migrate` has no such mode, so the phrase is undefined for
   them. Their gate is S2's `MIGRATE_PLAN` output, the read-only pre-flight counts the step
   records, and S10's scenario-(b) test that applies the new file alone onto a
   production-shaped fixture.
8. Anything the plan does not state, that the code now does, is recorded as a deviation in the
   ledger **and** raised in `docs/open-questions.md`.

**Never.** No step may:

- introduce a rule the plan does not state, or resolve an ambiguity that is Zak's — it goes in
  §1.1 with the exact question instead;
- widen a risk parameter;
- make a job write a ticket that §4.3 reserves to sessions;
- add a workflow to the schedule — §4.2 fixes the set at five and says nothing joins it without
  a plan edit;
- reference a database role without the guard 018 uses (`if exists (select 1 from
  pg_catalog.pg_roles where rolname = …)`), because a bare Postgres — a local restore, CI — has
  none of the Supabase roles and must still migrate;
- ship a behaviour change without a test that distinguishes old from new;
- leave the artifacts of the rule it replaced standing. A clause is not done while the old
  code's output is still actionable — the ledger measures the code, and Zak reads the table.

**The ledger is the index.** Every clause at OPEN or PENDING must be named by a step or by §5
"Deliberately not doing" with a reason. §4 carries the map and S10.7 makes it a test, so a
clause cannot fall out of scope silently.

**Safety posture.** The system is live. The book is seeded, Phase 0 tickets sit in `proposed`,
and the nightly runs against real data every weekday. Therefore:

- Every job change ships behind `DRY_RUN` first and is compared against the previous run's
  artifact before it writes — and where the previous artifact is empty because the step is
  fixing exactly that (S14), the step names a different, real comparison instead.
- **No `DRY_RUN` verification run is dispatched against production for `nightly-ingest`,
  `nightly-retry` or `daily` until S4 lands.** A dry run writes a `runs` row like any other and
  `freshness` does not filter it, so a dry green at 15:00 UTC currently overwrites a real red
  from 02:00 for 36 hours.
- **`phase0` is not dispatched live again until S17.2.** It writes tickets, which §4.3 reserves
  to sessions (D6); re-running it before the arm-only conversion extends the deviation rather
  than closing it.
- Migrations are applied only via the dispatch-only `migrate` workflow, never automatically,
  and after S2 only with an explicit target — the glob applies every unapplied file, so a
  dispatch meant for 019 applies 018 too.
- A migration that could lose data is preceded by a `monthly-backup` run, on demand — **except
  for `prices`, which the backup excludes by design** (§4.2 dumps everything *except* daily
  bars, and we do not widen that: the plan rules it out). The rows S13's prune deletes are
  covered by S13's verified archive and by a job-local dump of the affected ticker/date range,
  or they are not covered at all.
- Until the §2.7 reconciliation gap closes (S0.2), every NAV-percentage figure the machine
  prints is directional and says so.

**Commit discipline.** One work package per commit series; each commit builds green. The commit
message states what changed *and why the plan required it*, and carries any pre-flight count the
step required.

---

## 1. Preconditions

### 1.1 Rulings needed before certain steps (see `docs/open-questions.md`)

| Ruling | Question | Blocks |
|---|---|---|
| **D1** | theme is judgment, not sector — what does a job do meanwhile? | S9.7 theme cap; closed by S17.2 |
| **D5** | 3-year bar window, or buy 5 years? | S13.6 prune (the archive half proceeds) |
| **Q1** | TWR window and observation cadence | S17.4 performance line |
| **Q4** | legal ticket state transitions | S11b, S17.2 supersede/cancel, S17.3 fill loop |
| **Q5** | balance-outlier quarantine threshold | S12 apply |
| **Q6** | CNQ / levered single-name eligibility (CCN ≥ 85) | S18 |
| **Q7** | what growth the hurdle uses when the engine diverges | S6.6 |
| **Q8** | sequencing FX conversion with effective shares | S6.8 |
| **§4.3 vs §2.0/§5.4** | may a session write `balances` **and `transactions`**? One ruling, both tables — §4.3's list names neither, and §5.4 has R4 writing both | S12; S11a leaves `transactions` alone |
| **Q9** *(new)* | §3.1's two stated missing-data cases inside C1 fail **open** and name the gap on the C2 memo. Does that extend to a missing issuance, netDebt or EBITDA input, or should those fail the gate? | S6.4 |
| **Q10** *(new)* | how does a position born outside the system get its trail memory? §3.2 defines the trail as 10% below the highest close **since entry**; §6 Step 0 says existing GTC stops stand. Seed `highest_close` from pre-system history, from the sleeve-assignment date, or leave it null? | S14 |
| **Q11** *(new)* | what is `filing_date` when the vendor supplies none? §3.3 says what it must never be and never says what it is | S6.7 |
| **Q12** *(new)* | after a split restatement the stop's *number* falls without the stop loosening. Does §3.2's ratchets-up-never-down need an explicit unit-change exception, and what does Zak do with the resting broker GTC the broker has already adjusted? | S13.2 |
| **Q13** *(new)* | 018 needs a JWT signing secret (Zak's machine) and a per-session token (pasted in chat). §4.8 says credentials live in Actions secrets **and nowhere else**. Where do these live, and what is the token's `exp`? | S12.3 |

Everything not listed proceeds without waiting.

### 1.2 Raised with Zak alongside — blocking nothing, but on the record

- **The PAT scope.** §4.8 states Contents + Workflows + Actions read-write. S2 shows that scope
  plus one branch push is arbitrary SQL on production through `migrate`. The scope is in the
  law, so narrowing it is a plan edit, not our call — raised, not changed.
- **`005_book.sql:221`** already widens §4.3's session-writable list in a migration comment —
  "balances / transactions / tickets / observations / briefs / config stay session-writable by
  design". That widening is live today; record it as a deviation in the ledger.
- **`fundamentals.py:245`** fails C1 on `n_years < 3`. §3.1 assigns short history to the
  data-confidence path for the **engine component**, not to the gate. Recorded as a deviation
  until S6.3 removes it.
- **Not a gap: the 23,211.23 CAD TFSA figure.** An earlier round of this build reported that as a
  reconciliation break. It was not one — the broker screenshot it came from showed
  *available to trade*, which the portfolio-LOC collateral hold depresses, and the later figures
  reconciled to 912.84 CAD of ordinary settlement drift. Recorded here because the number has now
  been re-derived twice from the same stale source, and a finding that keeps coming back needs a
  written answer rather than another investigation.

### 1.3 Environment work

- A throwaway Postgres in CI (service container) so migrations and SQL can be tested at all —
  built in S10, with the target guard S10.1 specifies.
- **A restore procedure, written down and rehearsed once against a scratch Supabase project.
  This is a precondition of S10**, not a parallel task: S10 is the first suite in this repo
  whose job is to drop and rebuild a schema, and it must not exist before a restore path does.

---

## 2. The steps

Ordered by dependency, and the order is not the audit's. The audit put the wiring first; this
plan puts three things ahead of it — retiring wrong output that is actionable today (S0),
stopping a credential leak with a deadline of tomorrow (S1), and closing the path by which a
branch push becomes production DDL (S2). None of the three is a rule fix; all three are live
exposure. After that, the no-SQL rule fixes come **before** the database harness, because none
of S5–S9 needs a Postgres container and the money bugs run every weekday.

Each step lists what it closes.

### S0 — Withdraw what is standing (day zero)

*The rows in `tickets` at `proposed` were written by the code S6–S9 correct: momentum entries at
full intended size instead of §3.2's 50%, no `gate_state` check anywhere in `phase0.py`,
compounder buys on unapproved bench names carrying the note "C2 memo pending", accounts assigned
with no cash test. `tickets` is append-only (§4.3) and `phase0.py` contains no update and no
cancel — three bare inserts — so nothing retires them. Zak can place any of them by hand today,
and S21's re-run would append a second, contradictory generation beside them.*

1. Enumerate every `proposed` row — ticker, account, action, trigger / limit / qty / stop,
   `brief_id` — and send Zak the list with the defect named against each line and one
   instruction: **place nothing from these; void at the broker anything already placed.** No
   state change: `cancelled` is a Q4 transition and Q4 is unruled, so this is a message, not a
   write. The state-changing version ships in S17.2 behind Q4.
2. In the same message, ask Zak to confirm current per-account cash and positions once, so the
   withdrawal and the re-run in S21 start from an anchored NAV rather than a weekday
   extrapolation. This is §5.4's Sunday capture asked early, not a new obligation — and it is a
   confirmation, not an investigation: the 23,211.23 figure a previous round called a
   reconciliation break was an artifact of reading *available to trade* off a screenshot while
   the portfolio-LOC collateral hold was applied (see §1.2).

**Done when:** Zak has confirmed the withdrawal, and balances are anchored.

**Closes:** no clause — it retires wrong output rather than building anything. It is a
precondition of S6, S7, S8, S9, S14 and S21.

### S1 — Scrub the backup before the first dump lands (day zero, hard deadline)

*`backups/` does not exist and `git log -- backups` is empty: no dump has ever been committed.
`monthly-backup` fires Saturdays with an in-job guard that passes on any day-of-month ≤ 07, and
**2026-08-01 is a Saturday** — the first dump lands tomorrow at 14:00 UTC. `backup.py` skips only
`prices`, so it dumps `runs.detail`, which carries `report_fail`'s `output_tail` (the last 1,400
characters of raw `2>&1` job output) and `fundamentals`' `quota_check_failed` (`f"{type(e)}: {e}"`
from around a `get()` whose URL carries `api_token=<key>`). Once a `.json.gz` is committed,
scrubbing stops being a code change and becomes a history rewrite — and gitleaks reads bytes, not
gzip, so the tripwire built for exactly this credential cannot see inside the file. Actions log
masking never applies: this text goes into Postgres and from there into a commit.*

1. Land **before 2026-08-01 14:00 UTC**, or disable the `monthly-backup` schedule until it
   lands. Those are the only two acceptable outcomes.
2. One shared redactor: any string matching the two `.gitleaks.toml` patterns — the DSN rule and
   the EODHD key rule — becomes `<redacted sha256=… len=…>`.
3. Redaction happens **at write time**, so the database never stores an unfiltered tail:
   `db.Heartbeat.__exit__` (`trace`, `fatal`), `report_fail.main` (`output_tail`),
   `fundamentals`' `quota_check_failed`.
4. `backup.py` drops the free-text `trace` / `output_tail` / `fatal` fields from `runs.detail`
   and keeps a SHA-256 plus a length, so a dump still identifies which failure it was.
5. Test: a `runs` row carrying a planted `postgres://u:p@h/db` and `api_token=<32 hex>` comes out
   of both the writer and the dump clean.
6. The same discipline binds S13.6's archive — a second compressed artifact gitleaks cannot read
   into.

**Closes:** no plan clause; it protects `4.8/secrets-in-actions`, whose entire content is
"and nowhere else".

### S2 — Own the `migrate` path

*`migrate.yml` is a bare `workflow_dispatch` with no `permissions:`, no ref condition, no
environment and no concurrency; `actions/checkout` takes whatever ref the caller names; and
`migrate.py` runs `cur.execute(p.read_text())` for every `.sql` file it finds, as the database
owner. "Push a branch containing `migrations/019_anything.sql`, then dispatch migrate" is
therefore arbitrary SQL on the production database — no review, no checksum, no approval, no
lock. §4.8 hands Yuna a PAT with Actions read-write and `docs/write-path.md` §4 names prompt
injection as the realistic compromise of a session, so the 83 KB least-privilege design in 018 is
bypassable through the one workflow the previous draft leaned on twice and hardened nowhere.*

*Second defect, same file: the glob applies **every** unapplied migration in filename order. A
dispatch meant for 019 applies `018_session_api.sql` first — the write path S12 says must wait
for Q4, Q5 and the §4.3 ruling, which permanently alters live tables. Forward-only, no undo.*

1. `permissions: {}` · `if: github.ref == 'refs/heads/main'` · `concurrency: {group: migrate,
   cancel-in-progress: false}`.
2. A GitHub Environment holds `DATABASE_URL` with Zak as a required reviewer. That is the control
   that actually stops a PAT-driven dispatch; everything else here is defence in depth.
3. `migrate.py` takes a Postgres advisory lock before it reads `_migrations`, so two dispatches
   cannot both see 019 pending and both apply it.
4. An explicit target — `MIGRATE_ONLY` (comma-separated filenames) or `MIGRATE_UPTO` — plus a
   `migrations/BLOCKED` manifest the runner refuses to apply. `018_session_api.sql` goes into
   `BLOCKED` until S12 clears it.
5. `MIGRATE_PLAN=true` prints the pending files and their SHA-256 and exits without executing.
   This is what §0.7 means by a migration's gate.
6. Checksums: `_migrations` gains `sha256`, and a file whose stored checksum no longer matches
   the repo aborts the run before anything executes.

**Done when:** a dispatch from a non-`main` ref fails; a plan run prints 019 and not 018; a
second concurrent dispatch blocks rather than double-applying; an edited applied file aborts.

**Closes:** no plan clause. The PAT scope itself is §1.2, raised rather than narrowed.

### S3 — Twelve workflows, one standard

*The previous draft said eleven secret-holding workflows. `grep -l secrets.DATABASE_URL
.github/workflows/*.yml` returns **twelve** — every workflow except `ci.yml`. An off-by-one in a
security sweep leaves one mutable action tag beside the god-mode DSN, and nobody notices because
a sweep is prose. Pinning is also only half the exposure: a compromised action step inherits the
job's `GITHUB_TOKEN`, and only `ci.yml` and `monthly-backup.yml` declare `permissions:` at all —
`monthly-backup` holds `contents: write` and pushes, so a compromised step there rewrites the
code `migrate` later executes against production.*

1. SHA-pin every `uses:` in all twelve, named so the count cannot drift again: `backtest`,
   `backtest-compounders`, `daily`, `fundamentals`, `migrate`, `monthly-backup`,
   `monthly-funnel`, `nightly-ingest`, `nightly-retry`, `phase0`, `score`, `weekly-rank`.
2. `permissions: contents: read` on all twelve; `monthly-backup` keeps `contents: write` scoped
   to the job that pushes; `migrate` is `permissions: {}` (S2.1).
3. A CI check, not a one-off sweep: fail when any workflow referencing `secrets.` carries a
   `uses:` without a 40-hex SHA, or omits a `permissions:` block. A sweep decays; a gate does not.
4. **`DRY_RUN` parity.** §4.2: "All idempotent (upserts — safe to re-run), all carry `DRY_RUN`."
   `weekly-rank` passes none and offers no input; `monthly-funnel` passes `FORCE`/`STALE_ONLY`
   to both write steps and no `DRY_RUN`; `nightly-retry` hardcodes `DRY_RUN: 'false'`. Give all
   three a `dry_run` input wired to the env var. Without this the §0.5 compute gate is
   unachievable for S4, S7 and S8 — this is conformance, not scope. Add
   `4.2/all-carry-dry-run` to the ledger, quoting §4.2, and close it here.
5. `sslmode`: `db.db_url` and `migrate.db_url` both decide by substring on the whole URL, so a
   DSN already carrying `sslmode=disable` is left untouched and the append never fires — the
   control can be switched off from the secret's value with no signal anywhere. Parse the query
   string, raise on anything weaker than the required mode rather than accepting it, and roll
   `verify-full` out behind an env var on one dispatch-only workflow first, confirming its
   heartbeat before flipping the other eleven: a CA or hostname mismatch kills every job at
   02:00 UTC, which `db.py`'s own comment calls the invisible death. Unit test: a DSN carrying
   `sslmode=disable` is rejected.

**Closes:** `4.2/all-carry-dry-run` (added by this step).

### S4 — Heartbeat honesty, and exactly five scheduled jobs

1. `policy.domain_is_stale` replaces the inline status test in `daily.freshness` — with both
   halves the swap needs, or it inverts into a silent nightly outage. `Heartbeat.__enter__`
   inserts a `running` row **and commits it** before the body runs; `freshness` takes
   `distinct on (job) … order by job, id desc`; `domain_is_stale` returns stale for `running`
   with no age test; and `daily` is in the price-feed list that gates tickets. Wired naively,
   `daily` reads itself as running, ambers itself and sets `tickets_allowed: false` every night
   forever, behind a plausible-looking "⚠️ daily running — tickets held". So: **(a)** the query
   excludes the caller's own open run (`and id <> %s` with `hb.id`); **(b)** `running` counts as
   stale only past that job's workflow `timeout-minutes` — 20 `daily`, 90 `nightly-ingest`, 30
   `nightly-retry` and `weekly-rank`, 300 `monthly-funnel`, 20 `monthly-backup` — so
   `domain_is_stale` takes the row's age and the caller passes it. Test: `freshness` called
   inside an open `Heartbeat` for the same job returns ok.
2. Freshness judges only `dry_run = false` rows, and reports the last dry run separately as
   `last dry run: <job> <status> <ts>`. Today a `DRY_RUN` dispatch writes a `runs` row exactly
   like a live one, and `ingest` marks green whenever no fetch errored regardless of `DRY` — so
   a dry verification run at 15:00 UTC papers over a real 02:00 red for 36 hours, and a dry
   `phase0` (which ambers whenever no balances are captured) holds tickets. `ingest`'s own retry
   guard already filters `dry_run=false`; the code knows this hazard in one place and not the
   other. Test: a red live run followed by a green dry run still reads stale.
3. The expected schedule lives in one module-level table, and it is the law's five —
   `nightly-ingest`, `nightly-retry`, `weekly-rank`, `monthly-funnel`, `monthly-backup` — plus
   `daily`, which has **no cron of its own**: it runs as a step inside `nightly-ingest` and
   writes its own `runs` row under its own name. The two monthly jobs fire weekly on Saturday
   and gate themselves in-job to the first Saturday, so the table carries that predicate; a
   table derived from cron alone reports `monthly-funnel` missing on three Saturdays in four,
   and a false "never ran" alarm and a missed one are the same bug. `freshness(conn, now)` takes
   an explicit UTC instant, defaulting to real time, so table-driven tests can walk a Monday, a
   Saturday, a first Saturday, a US market holiday and a month boundary. A test parses the
   `cron:` lines out of `.github/workflows/*.yml` and asserts the scheduled set equals the
   table — the two definitions cannot drift.
4. **The sixth cron goes.** §4.2 authorises five scheduled jobs and says "nothing new joins the
   schedule without a plan edit"; `fundamentals.yml` carries `schedule: - cron: '0 8 * * 6'`.
   Delete the block, keep `workflow_dispatch` for cold start and repairs. §4.1 puts the
   filing-triggered pull "on the next nightly" and a "monthly staleness sweep" — the sweep
   already exists as `monthly-funnel`'s stage 1.5, and the nightly half lands in S5.4 under the
   quota meter. Between this step and S5 the monthly sweep is the only refresh: a named
   one-step loss of freshness, not a silent one.
5. `nightly-retry` re-runs the `daily` duties — **gated**, because `daily` is not idempotent.
   The retry's skip lives inside `ingest.py` and returns 0, so the workflow's later steps run
   regardless; an unconditional `daily` step would write two `nav_snapshots` rows for the same
   date and two `preopen` briefs for the same session every ordinary weekday, and
   `nav_snapshots` is the only raw material for S17.4's time-weighted line, where a duplicated
   boundary date makes a chained return arbitrary. So the step queries `runs` for a green live
   `daily` today and sets a `GITHUB_OUTPUT`, mirroring the ingest guard. `nightly-ingest`,
   `nightly-retry` and `daily` share one `concurrency:` group so a manual dispatch cannot
   overlap the scheduled run. The unique indexes are defence in depth and land in S11a.
6. A missing or stale USDCAD stops being an FX rate of 1.0. `db.nav_cad` does `fx =
   float(row[0]) if row else 1.0` with no staleness test; the book is almost entirely USD, so a
   missing rate understates NAV by about a quarter, and §2.3's floor and ceiling, §2.1's sleeve
   weights and every momentum risk budget are percentages of that number. §3.3 says never assume
   a missing value and §4.1 says every CAD figure carries its rate and `as_of`: no rate, or one
   older than the bar window, ambers the domain and NAV reports unanchored.
7. Job-written dates are UTC — `(now() at time zone 'utc')::date`, not `current_date`. §4.7:
   all timestamps and `as_of` stamps are UTC, and these jobs run at 02:00 UTC.
8. The autopsy step moves before `pip install`, or is made installation-independent, so a
   failure during dependency install still leaves a trace.

**Closes:** `4.7/stale-detects-silence` · `4.2/five-scheduled-jobs`. Strengthens `4.7/heartbeat`,
`4.7/stale-data-no-tickets`, `2.0/nav-from-balances`.

### S5 — Meter the budget before spending it, and keep the filings

*S6 and S8 each imply a full fundamentals re-extract and Q8's fix implies another. A fundamentals
request bills 10 units and L0 is ~2,300–2,780 names, so one sweep is 23k–28k of the 100k daily
budget; 2026-07-31 already spent ~88k on three. The quota meter cannot sit downstream of the
steps that spend the quota: a sweep colliding with the nightly's calls gets the vendor to cut us
off, `nightly-ingest` goes red, and §4.7's "stale data ⇒ no new tickets" locks the day. And
§4.1's second archive obligation — "the raw filing JSON is compressed into the repo" — is
unbuilt, which is why every rule fix costs a full-price sweep instead of a free local
re-extract.*

1. The quota meter on **every** job, not only the sweep: calls used against the usage endpoint,
   recorded in `runs`, and the brief alarms past ~70% of the daily quota (§4.1).
2. A stated call budget per re-sweep, recorded in the run before it starts, and the rule that no
   sweep runs on a night the ingest also runs.
3. The raw filing JSON compressed into the repo per §4.1, keyed by ticker and filing date, so a
   re-extract is a local operation. S1's redaction discipline applies — it is another compressed
   artifact gitleaks cannot read into.
4. §4.1's filing detection moves to where the law puts it, under the meter: a name whose earnings
   date has passed since its last pull is re-fetched on the next nightly. This is the half S4.4
   removed the sixth cron from.

**Closes:** `4.1/quota-meter`. Adds and closes `4.1/filing-archive` (§4.1, "the raw filing JSON
is compressed into the repo").

### S6 — Wire the compounder rules and fix Gate C1

1. **Before any C1 outcome changes.** `score.py` deletes gate-failers with `delete from bench
   where ticker = any(%s) and ticker not in (select ticker from universe where is_holding)` — no
   `and not approved`, while the eviction delete three lines below has one. Bench rows carry
   `approved`, `approved_at`, `c2_status` and `c2_memo`; `bench` is an overwrite table with no
   history and the C2 memo store does not exist yet, so the first score run after this step
   deletes Zak's approvals and his memos — at the same moment S9.3 makes `bench.approved` the
   gate that decides whether a buy ticket may be written. Two changes, in this order: add
   `and not approved` to the gate-failure delete, and write the row's approval state and C2 memo
   into `observations` before any delete. §3.1 already says "every memo and every decision
   logged as an observation", so this needs no new table and no schema step.
2. `fundamentals.py` calls `policy.is_excluded_financial` — the live code excludes the entire
   Financial Services sector, dropping exactly the toll-booth compounders §3.1 names as eligible.
3. Remove the invented C1 criterion at `fundamentals.py:245` — `if n_years < 3:
   fails.append(...)`. §3.1 routes short history to the data-confidence path for the **engine
   component**; it is not a gate criterion, and C1 failure evicts immediately. Recorded as a
   deviation (§1.2) until this lands.
4. *(Blocked on Q9)* whether C1 fails **closed** on a missing leverage, issuance or
   debt-vs-EBITDA input. The previous draft decided this in a sub-bullet; it is not ours to
   decide. §3.1's two stated missing-data cases inside C1 — no vendor industry, goodwill jumps —
   both fail **open** and name the gap on the C2 memo, and §3.3 degrades rather than excludes;
   neither line covers a missing EBITDA. Behaviour is unchanged until ruled, and the deviation
   stands recorded.
5. The engine tolerance is flat 5pp in the sweep, matching §3.1 and `score.py`.
6. On engine divergence the **engine component drops out of the CCN** (§3.1's data-confidence
   path); today it is flagged and still contributes 33%. What the *hurdle* then uses for growth
   is Q7 and stays as it is until ruled.
7. `filing_date` never falls back to fiscal period end (§3.3, non-negotiable) — **and the fix
   carries a data migration, or it manufactures the §4.8 sin it exists to prevent.**
   `fundamentals` is keyed `(ticker, filing_date)` and upserted on that key, so removing the
   fallback changes the key: the next sweep inserts a new row under the true, later date and
   leaves the old one in place, stamped *before the filing existed*. §4.8 names that as one of
   "the two classic sins", and S20 re-grades the compounder backtest against this table. So: add
   `filing_date_source` (`vendor` | `period_end_fallback`), backfill it by comparing
   `filing_date` to the fiscal period end, and exclude `period_end_fallback` rows from
   `v_fundamentals_latest` and from every point-in-time read (`score.py`,
   `backtest_compounders.py`). The rows are marked, not deleted — §4.1's archive is a
   point-in-time asset and deleting rows falsifies it the other way. *(Blocked on Q11)* what to
   write when the vendor supplies no filing date at all; until ruled, the row is written with a
   null filing date and excluded from point-in-time reads.
8. *(Blocked on Q7/Q8)* effective shares and the FX conversion, sequenced together as Q8
   describes.

**Done when:** a dry `score` run reports the list of approved names the new C1 outcomes would
delete, and that list is reviewed before any live run.

**Closes:** `3.1/c1-excludes-financials` · `3.1/foreign-fx` and `3.1/effective-shares` (both on
Q8) · strengthens `3.1/engine-reliability`, `3.3/filing-date`, `3.1/bench-eviction`,
`4.1/point-in-time`. **Not** `3.1/compounder-sizing` — that clause fails because `phase0` reads a
flat size from config and never calls `policy.compounder_size`, so it closes in S9, where the
work is.

### S7 — Wire the momentum rules

1. `rank.py` calls `policy.scan_base` — the live scan is the superseded rule and diverges three
   ways (pivot window, break test, where the 0.5% grace applies).
2. MCN setup proximity at **three** sub-scores; the 2026-07-31 pass dropped pullback contraction
   and `rank.py:175` still averages four. The percentile helper moves into `policy` with it —
   `rank.py` carries its own `pct_rank` (an `argsort().argsort()`) beside `policy.pct_rank` (a
   sorted-list ordinal), and they disagree on ties, so the move is part of the rule, not tidying.
3. `policy.l1m_member` — M4 must **pass**, not merely "not fail".
4. `policy.trend_template` replaces the inline M2.
5. Remove the invented 210-bar scoreability threshold, which silently shortens the plan's
   52-week and 252-session windows.
6. `queue` insert deduplicated — `rank.py` dies on a duplicate primary key when a holding is
   also a top-10 BUY (`queue.ticker` is the PK and both loops append).
7. **The rebuild becomes safe and rehearsable.** `rank.py:202` does `truncate candidates;
   truncate queue` then inserts, and reports green regardless of row count — so a rewritten
   pivot rule that yields an empty `l1m` (the plausible failure, especially with S8 tightening
   L0) commits an empty `candidates` and `queue` and calls it a success; `phase0` then reads
   `mcn=None` for every holding, `mom_ok` is false, and the verdict is EXIT for every name not
   on the compounder bench. And `DRY` skips the truncate *and* both inserts, so old-vs-new can
   only be compared by the live run that has already destroyed the old — `runs.detail` keeps
   four integers, not the per-name pivots that moved. So: the dry path writes the computed
   `candidates` and `queue` rows into `runs.detail` (per-name pivot, trigger, limit, suggested
   stop) instead of the tables, and the live path replaces truncate-then-insert with a
   same-transaction rebuild that counts first and **aborts red without writing** if `len(l1m)`
   or `len(qrows)` falls below a configured fraction of the previous run's recorded counts.
8. `queue` is rewritten only on Saturdays while `daily.refresh_marks` recomputes proximity
   against the stored triggers every night, so between a merge and the next Saturday the brief
   quotes the superseded rule's numbers for up to six days. Dispatch `weekly-rank` live
   immediately after merge; the ordering in S15 governs the rest.

**Closes:** `3.2/base-detection` · `3.2/pivot-grace` · `3.2/m2-trend-template` ·
`3.2/l1m-top150` · `3.2/mcn-score`.

### S8 — One universe

`funnel.py` and `score.py` both call `policy.in_l0`. Today the census sets `in_l0` at $4 and one
day's $5M volume, `rank.py` re-applies the real filters, and `score.py` re-applies nothing — so
the two sleeves screen different universes off the same column.

`in_l0` is rewritten only on the 1st Saturday, so the same staleness applies as S7.8: the
recompute order in S15 governs, and `monthly-funnel`'s two write steps carry the `dry_run` input
from S3.4 with the same abort-on-collapse floor as S7.7 — a redefinition from $4/$5M to
$5/$10M/126-day is exactly the change that could empty the universe.

**Closes:** `3.0/l0-filters`.

### S9 — The ticket path: sizing, gates, approvals

*The arithmetic and the gates only. `book.sleeve` is not written here — that is S14, and turning
the ratchet on is its own hazard. No add order is armed here either: §3.2 freezes the pyramid at
step 1 until the breakout confirms, and the confirmation machinery does not exist until S16.*

1. **The entry ticket is 50% of intended size** (§3.2 step 1) and ships as the entry pair only —
   the buy stop-limit at the pivot plus its GTC protective stop (§4.5, §5.1). **No step may emit
   a pivot +2% / +4% order until breakout confirmation exists.** §3.2: below the volume
   standard the breakout is *unconfirmed* and "the pyramid **freezes at step 1 (50%)**";
   shipping all three orders at once carries every breakout, confirmed or not, to 100% of
   intended size on resting GTC orders that fill unwatched — and inside an earnings blackout, at
   that, since `policy.pyramid_may_arm` is called nowhere.
2. **M1 is checked at entry** — §3.2 enforces the gate at entry time; `gate_state` appears in
   `phase0.py` zero times.
3. **`bench.approved` is checked** — §6 Step 3 says *approved* bench names.
4. phase0 calls `policy.momentum_size`, `group_has_room`, `sleeve_has_room`,
   `size_is_admissible`, `compounder_size`, `initial_stop`, `in_blackout` — and the inline
   copies are **deleted**, not left standing beside them. §0.2's substitution test is what proves
   it.
5. Group counts, theme weights and the effective-bets print are computed over **every open
   `book` row, `sleeve='levered'` included** (§2.0: "independence and theme caps see the whole
   book, levered positions included"); sleeve room, sleeve name counts and the 25% single-name
   cap exclude them. Today a levered row returns at `phase0.py:79` before it can join
   `survivors`, and the group/theme accumulators loop `survivors` only — so CNQ is invisible to
   the 2-per-group count and the 35% theme weight, and `VXC.TO` will be too the moment it is
   added. The `2.2/max-2-per-group` claim is conditional on a test whose fixture holds a levered
   row that **must** be counted by the group cap and **must not** consume sleeve room.
6. A re-run supersedes its own prior generation instead of appending beside it. `tickets` has no
   unique key of any kind and `phase0.py` is three bare inserts; the idempotency key lands in
   S11a.3 and the code that uses it lands here.
7. *(Blocked on D1)* the theme cap. Closed in S17.2, where a session assigns theme by judgment
   as §2.2 requires.
8. The dry heartbeat carries the per-ticket artifact — qty, trigger, limit, stop, stop-limit,
   account, gate verdict, approval state, per name. Today the entire brief write sits inside
   `if not dry():` and `hb.detail` carries `keeps/exits/step5/compounders=len(...)/momentum=len(...)`,
   so §0.5's gate is unmeetable for the step that changes what Zak is told to buy.

**Closes:** `3.2/stop-8pct` · `3.2/momentum-sizing` · `3.1/compounder-sizing` ·
`2.1/sleeve-counts` · `2.2/max-2-per-group` · `2.3/position-floor` · `2.3/single-name-cap` ·
`2.3/risk-not-dollars` · `3.3/blackout` · `3.3/blackout-trading-days`. `3.2/pyramid` and
`3.2/pyramid-ceiling` are deliberately **not** claimed here — they close in S16, with the
confirmation rule that governs them.

### S10 — Make it verifiable: the database harness and the ledger gate

*Nothing in this repo has ever executed a line of SQL under test — including the 1,462-line
session write path. **Precondition: §1.3's restore procedure exists and has been rehearsed**,
because this is the first suite here whose job is to drop and rebuild a schema.*

1. **Target guard, as requirements rather than prose.** (a) The DB suite reads
   `TEST_DATABASE_URL` only, and a session-scoped `conftest` fixture aborts the run if
   `DATABASE_URL` is set at all, or if `TEST_DATABASE_URL`'s host is not `localhost` /
   `127.0.0.1`. (b) Each run creates and drops its own `yuna_test_<uuid>` database and never
   resets `public` in a database it was handed. (c) `pyproject.toml`'s marker line — today
   `"db: needs a live DATABASE_URL (skipped when absent)"` — is rewritten to name
   `TEST_DATABASE_URL`; `--strict-markers` checks the name, not the description, so the drift
   would otherwise stand. Anyone operating this system has `DATABASE_URL` exported.
2. CI gains a `postgres:17` service container. `TEST_DATABASE_URL` is a **plaintext literal** in
   `ci.yml`'s `env:` block (`postgresql://postgres:postgres@localhost:5432/postgres`) and never
   a repository secret: `ci.yml`'s opening invariant is no secrets ever, and a secret would also
   skip the DB suite on exactly the fork PR that changes a migration. The harness seeds the
   Supabase-provisioned roles — `anon`, `authenticated`, `authenticator`, `service_role` —
   before applying, because a bare `revoke all … from anon` errors with "role does not exist" on
   a vanilla `postgres:17`.
3. **Two migration scenarios, not one double-apply.** (a) empty → 001..N, asserting the schema
   (tables, columns, types, constraints, indexes) and every view's column list. (b) empty →
   001..N−1, seed a production-shaped fixture — migrations 002 / 007 / 013 / 014 already are one
   — then apply N alone: the only path a new migration ever takes. The old double-apply test
   exercised something `migrate.py` never does, since it skips names already in `_migrations`,
   while not exercising the thing it does. A third scenario mirrors production's actually-applied
   set (pre-018 until S12), so CI cannot assert a schema production does not have.
4. Guard triggers refuse a write from a non-migrator role.
5. `tests/db/test_jobs.py`: seed a minimal fixture — a few dozen universe rows with ~300 bars
   each, the seeded book, one `bench` and one `candidates` row — and run `daily.main()`,
   `rank.main()`, `score.main()` and `phase0.main()` with `DRY_RUN=false` against the scratch
   database, asserting the rows that land and their values. This is the only end-to-end
   verification anywhere in the plan, and it catches the class of defect schema assertions
   cannot see: `daily.py:56`'s `where sleeve='momentum'` selecting an empty set, the `queue`
   duplicate-key crash, the `nav_cad` lateral join every position size depends on.
6. A direct test of `fundamentals.flush` with one constraint-violating row in the batch: the
   other rows land, `_batch_fallback` is recorded, the heartbeat ambers. That path is
   unreachable by unit tests (it needs a database), unreachable by `DRY_RUN` (`flush` returns at
   line 338 before any SQL) and outside the schema assertions — and S11's new CHECK constraints
   are what will start tripping it.
7. **The ledger gate.** A test parses the `Closes:` lines out of `docs/build-plan.md`, asserts
   every key exists in `rules.CLAUSES` (a renamed clause otherwise orphans a step silently),
   asserts every clause at OPEN or PENDING is named by a step or by §5, and — for steps marked
   complete — asserts each claimed key is BUILT and wired. The call-graph test is a no-lying
   check; this is the completeness half it has never had.
8. The §0.2 substitution harness as a reusable fixture, so each step's claim costs one line.
9. **Golden fixtures**, as a named deliverable with the Postgres behind them rather than a
   floating aspiration. A frozen universe of ~30 names with fixed bars and fundamentals
   committed to the repo; expected CCN, MCN and hurdle values **hand-derived from the plan
   text**, never captured from current output; each fixture file carrying a `plan_stamp` equal
   to the `docs/yuna_plan.md` Updated stamp it was derived from, with a test that fails when the
   stamp moves and the fixture did not. §3.0 makes this shape mandatory — "all components are
   cross-sectional percentiles within L0 at run time", so a fixture of one name is a fixture of
   nothing and the frozen field *is* the fixture. Regeneration is an explicit act tied to a plan
   edit, not a re-bless of whatever the code now says. The MCN fixture depends on S7.2 having
   moved the percentile math out of `rank.py`.

**Closes:** no plan clause. It is what makes every other step's `Closes:` line mean something.

### S11 — Schema defences (migration 019)

#### S11a — the constraints whose domain is already fixed

*`migrate.py` runs each file as one `cur.execute(p.read_text())` in one transaction, so a single
`ADD CONSTRAINT` that fails validation rolls back the whole of 019 — the view hardening with it —
and `migrate` is dispatch-only with no rollback tooling.*

1. `CHECK` constraints enumerated **from the writers, not from the schema comments**. The
   comments are stale in one place, absent in another, and not authoritative in a third:
   - `book.sleeve in ('compounders','momentum','levered','unassigned')`. The 005 comment says
     three values; migration 007 seeded six of the seven live rows as `unassigned` **on purpose**
     ("§6 Step 2a assigns them by score"), and `phase0.py:103` sets `sleeve_assigned=None` for
     EXIT verdicts against a NOT NULL column, so `unassigned` survives S14 for anything not
     kept. A later migration narrows the set once nothing writes it.
   - `queue.state in ('BUY','WAIT','HOLD')`. `004_momentum.sql` declares `state text,` with **no
     comment at all**, so the derivation rule yields nothing; `rank.py:194` writes `HOLD` for
     holdings and `BUY`/`WAIT` for momentum rows. A `BUY|WAIT` check kills every `weekly-rank`
     run on insert and leaves last week's triggers live.
   - `book.status`, `runs.status`, `candidates.state`, `accounts.kind` — domains the seed data
     and the writers already fix.
2. A read-only pre-flight against production **before the migration is written**: one
   `select <col>, count(*) … group by 1` per target column, its result recorded in the commit
   message, every count outside the allowed set zero. The CI harness cannot substitute — it
   applies to an empty database and can never fail on data it does not have.
3. Idempotency keys, which later steps depend on: unique on `nav_snapshots(d)`, unique on
   `briefs(kind, session_date)`, and a ticket idempotency key `(brief_id, ticker, action)` so a
   repeated `phase0` run cannot double-write (S9.6). The `daily` inserts become
   `on conflict … do update`, which is also §4.2's "all idempotent" made true.
4. `security_invoker = true` on the **four** views that exist before 018 — `v_book`, `v_queue`,
   `v_bench`, `v_fundamentals_latest` — plus explicit `revoke` from `anon`/`authenticated`, each
   role reference guarded the way 018 guards `authenticator`. (`v_session_writes` and
   `v_quarantine` arrive with 018 and are hardened in S12.7; naming "all six" before 018 is
   applied would fail.) **Precondition:** run `select current_user, session_user` through the
   actual Supabase MCP connector and record the answer in the step before the migration is
   written. RLS is enabled on 24 tables with zero policies, so the views work today only because
   they run with the migrator's rights; if the connector is not a BYPASSRLS role, `v_book`
   returns **zero rows with no error** and R1, R2 and R5 read an empty book and report it as an
   empty book — which nothing detects, because §5.6's staleness tests read run status and bar
   age, not row counts. If it is not, the same migration adds `create policy … for select` per
   table plus `grant select` on the views, or the flip does not ship.
5. `v_fundamentals_latest` rebuilt with an explicit column list — the `select *` that already
   broke this system once — excluding `period_end_fallback` rows (S6.7).
6. Version stamps on the rows the formulas produce — `bench.ccn_version`, `bench.hurdle_version`,
   `candidates.mcn_version`, `gate_state.m1_version` — so §3.3's "changes increment and are
   logged so later versions can be measured against earlier ones" is true of the data and not
   only of the docstrings. The shadow book is the decision that reads them, so the §4.3 bloat
   rule is satisfied.
7. A prepared 020 reverting item 4 to `security_invoker = false` is written **before** 019 is
   dispatched. Migrations are forward-only and `migrate` has no rollback, so the revert has to
   exist in advance or it does not exist.

**Done when:** the pre-flight counts are recorded and zero; 019 applies cleanly in S10 scenario
(b); `v_book` returns seven rows read *through the MCP connector* after apply.

**Closes:** `3.3/versioning`. Strengthens `4.3/guard-triggers` — it makes it mean what it says.
`transactions` is deliberately **not** here: §4.3 authorises no writer for it, which is the same
ruling S12 waits on for `balances`, and building the writer first would put it on whichever side
of the line the ruling does not take.

#### S11b — `tickets.state` and `tickets.action` (blocked on Q4)

A CHECK on `tickets.state` **is** the enumeration Zak has not given. `005_book.sql:103` records a
set in a comment, but a comment is not a ruling, and a forward-only migration on a live database
is the worst place to put an invented one. `tickets.action` sits in the same position from the
other side: the comment lists `buy | add | sell | stop_move | cancel`, while S16 introduces the
displacement swap and S9 the pyramid add, so the comment is not authoritative either. Both wait
for Q4 and ship in their own migration, after it.

**Closes:** nothing until Q4 lands.

### S12 — Apply the session write path (018)

Blocked on Q4, Q5 and the §4.3 write-authority ruling — which covers **`balances` and
`transactions` together**. §4.3 enumerates the session-writable set as briefs, tickets,
observations and config; neither table is on it, and neither is on the guarded computed-table
list; §5.4 has R4 writing both at Sunday reconciliation. One ruling answers both, and until it
lands neither writer is built.

1. Clear `018_session_api.sql` from `migrations/BLOCKED` (S2.4) and apply it by explicit target,
   so it is an act rather than a side effect of a dispatch meant for something else.
2. **Record the credential deviation before minting anything.** 018 introduces two credentials
   §4.8 does not contemplate: the JWT signing secret on Zak's machine, and a per-session token
   that must be pasted into a chat to be usable and then lives in that transcript forever.
   `4.8/secrets-in-actions` says credentials live in Actions secrets and nowhere else. Record it
   in the ledger and raise it in `docs/open-questions.md` — Yuna does not decide where a new
   credential lives.
3. *(Blocked on Q13)* the token's lifetime as a number, minted per session and never reused
   across sessions. PostgREST, not the database, enforces `exp`.
4. A dispatch-only `revoke-session.yml` kill switch: one input (`revoke` | `restore`), its own
   Environment, running exactly the two grant/revoke statements. Otherwise a Friday-night
   revocation goes through `migrate`, the most dangerous workflow in the repo.
5. Verb tests that exercise the authorization design, not only the SQL. Every verb is
   `SECURITY DEFINER` owned by the migrator and the S10 harness connects as the owner, so inside
   a verb `current_user` is the migrator and both the 005 guard triggers and RLS are bypassed —
   `write-path.md` §8 records this as verified live. A test on that connection passes identically
   if `revoke all on function … from public` were dropped, or if `yuna_session` held SELECT on
   `book`. So: tests run under `set role yuna_session` with `set local request.jwt.claims`, and
   the suite carries negative assertions as first-class cases — `yuna_session` denied SELECT and
   INSERT on every table in `public`, denied USAGE on `yuna_priv`, no `api` or `yuna_priv`
   routine holding a PUBLIC grant (asserted against `information_schema.routine_privileges`),
   and the kill switch killing all eight verbs with the restore grant bringing them back.
6. Named as outside the harness and requiring a one-time manual check against the real
   deployment, owner Zak: `exp` enforcement, the PostgREST round trip, the exposed-schemas
   dashboard setting.
7. `security_invoker` and the `revoke` discipline extend to `v_session_writes` and
   `v_quarantine`. `yuna_session` holds zero table privileges by design (018:114-119), so
   `v_quarantine` needs an explicit grant or it empties for the role meant to read it.
8. The rotation cadence and the post-incident procedure (`v_session_writes` walk-back,
   `write-path.md` §7) ship as a runbook with the step, not as a doc appendix.

**Closes:** `2.0/provisional-balances`. **Enables** `2.2/jobs-arm-sessions-write` — it does not
close it. Giving sessions a write path takes nothing away from `phase0`; that happens in S17.2.

### S13 — Data integrity at the feed

1. **Bulk ingest.** §4.1 forbids per-ticker pulls *as the routine* by name; per-ticker survives
   for the four enumerated exceptions — cold start, corporate-action refreshes, gap repair, and
   names entering L0.
2. **Corporate actions: the re-pull and the restatement are one transaction, or neither ships.**
   §4.1 mandates the re-pull, and the re-pull is what creates the failure it prevents — before
   it, the stored history and the book agree; after it, they do not. So, in order: (a) detect
   the action; (b) re-pull that ticker's full history; (c) **in the same transaction** restate
   everything denominated in the old price scale — `book.qty`, `avg_cost`, `stop`, `stop_limit`,
   `highest_close`, `target_qty`, and any open ticket's `trigger_price` / `limit_price` / `stop`
   — and null `bench.hurdle_price` and `bench.gap_to_hurdle` so the name is un-buyable until
   `score` recomputes them; (d) name the restatement in the next brief. **(b) does not ship
   without (c).** Untreated, a 4:1 split leaves `book.stop` at four times the new scale, so the
   next `daily` reports a fired stop and a −75% position; `daily.refresh_marks` updates
   `bench.last_close` but never `hurdle_price`, so `gap_to_hurdle` reads −0.75 and §6 Step 3
   writes a *buy*; and `nav_cad` values the position at a quarter of its worth, which flows into
   every position size in that night's brief. Test: a synthetic 4:1 split leaves stop distance,
   `pnl_pct` and `gap_to_hurdle` unchanged to within rounding. *(Q12)* covers the resting broker
   GTC and whether §3.2's ratchets-up-never-down needs an explicit unit-change exception.
3. **Price quarantine — both triggers.** §4.1 names two, joined by "or", and `policy.price_is_suspect`
   is only the first: its own docstring says "The plan's second test — 'any print that would fire
   a sell-side action' — is the caller's, because only the caller knows where the stops are."
   That second test is the one that protects money: a bad print does not need to move 40% to trip
   an 8% stop, a 10% trail or an MCN < 55 exit. So `daily` quarantines any price that would fire
   a stop, a trail ratchet, a template or MCN exit, or a hurdle add; the row is named in the next
   brief and nothing acts on it until a second source agrees (job re-fetch + live MCP quote).
   The clause is not claimed until both triggers are wired.
4. **A bad bar is quarantined, not rejected.** The previous draft put `high >= low`,
   `high >= open`, `high >= close` and positivity on `prices` as a CHECK in the schema step.
   §4.1 states exactly one disposition for a suspicious print — held out of use, named in the
   next brief, "never silently used" — and a CHECK is a third behaviour the plan does not state:
   the row is refused, so it is never stored, never quarantined, and cannot be named anywhere.
   The operational failure is worse than the philosophy: `ingest.py`'s per-ticker `try` wraps
   only `fetch`, so the `executemany` raises to the outer handler, marks the run red and
   re-raises before the remaining tickers are touched; `nightly-ingest` therefore never reaches
   its `daily` step — no trail ratchet, no stop sheet — and because the insert aborted,
   `select max(d)` still returns the prior day, so tomorrow re-fetches the same bar and dies the
   same way, and `nightly-retry` (which skips only on a green primary) dies with it. One vendor
   typo becomes an indefinite nightly red with §5.6 blocking tickets throughout. Therefore:
   the writer routes a bar failing the sanity test into the quarantine store with its reason;
   `ingest` wraps the per-ticker insert so one bad bar costs one ticker and ambers, never the
   night; and the constraint lands only **after** the quarantine route exists, as
   `ADD CONSTRAINT … NOT VALID` in one migration and `VALIDATE CONSTRAINT` in a **separate**
   file — one file is one transaction, so a NOT VALID/VALIDATE pair inside one file holds the
   same locks and buys nothing — preceded by the read-only violator count over ~2.18M rows
   written verbatim from the vendor since cold start.
5. Quota meter and the 70% alarm land in S5; verify them here against bulk ingest's call profile.
6. **3-year rolling window: archive, verify, then prune — and the prune waits on D5.** Four
   ordered sub-steps: (a) write `archive/prices-<shard>-<year>.csv.gz`, shard key stated in the
   step; (b) re-open each file, parse it, and assert row count and a per-`(ticker, year)`
   checksum equal the same aggregates computed in SQL; (c) commit and confirm the commit landed;
   (d) only then delete, in bounded batches, behind `DRY_RUN`, and only rows proven present in
   (b). The retention number is read from `config.bars_retention_years`, never hardcoded —
   `ingest.py:61` derives `backfill_from` from the same row, so a hardcoded prune either fights
   the backfill or silently ignores a widened window. **D5 blocks (d):** Zak has been asked to
   confirm 3 years or authorise 5, and the number moves every hurdle price. Until ruled the
   archive half ships and the prune stays behind a config flag defaulted off.
7. **Delisted names retained** (§3.0, §4.8's second classic sin).
8. **The un-ratchet path.** `policy.ratchet_stop` clamps `if current_stop >= cand: return
   current_stop` — stops ratchet up, never down (§3.2) — so one bad print that survives one
   nightly permanently raises a stop, and correcting or deleting the price row afterwards does
   not lower it. No job un-ratchets, and `book` sits behind the guard triggers, so no session can
   either. A named job step recomputes `book.highest_close` and `book.stop` from bars after a
   quarantine correction or a split restatement, names the recompute in the brief, and is the
   only sanctioned downward move.

**This step precedes S14 by necessity.** S14 turns the ratchet on for the whole book; until
quarantine and the un-ratchet path exist, a single bad vendor print becomes a permanently wrong
stop with no way back, and S14 would be a step after which the system is strictly worse.

**Closes:** `4.1/bulk-prices` · `4.1/corporate-actions` · `4.1/price-quarantine` ·
`4.1/bar-retention` (archive; the prune ships behind D5) · `3.3/delisted-retained`.

### S14 — Turn the trailing stop on

*Writing `book.sleeve` is what switches `daily.ratchet` on — and switching it on retroactively is
not a neutral act. The live rows have `highest_close` and `stop` NULL but real `opened_at` and
`avg_cost` from migrations 013/014: TSM since 2024-05-01, NVDA at 203.24 since 2026-05-04.
`ratchet` loads every close from `d >= (opened_at or 1990-01-01)`, `policy.ratchet_stop` sets
`new_high = max(closes)` when `highest_close` is NULL, and any name up ≥ 15% on cost gets
`new_high × 0.90`. So night one invents a stop from up to two years of highs the system never
observed — and `daily.main` calls `event_scan` in the same run, which selects `where stop is not
null` and flags `lo <= stop`, so the same run writes the stop and reports it as fired with
`gapped_through: true`. Zak would get "N stop(s) fired — confirm the sale" plus a stop sheet
telling him to place GTC sells above market, from a code deploy rather than a market event, while
§6 Step 0 says "Existing GTC stops stand." And `DRY_RUN` cannot show it: `ratchet` skips its
UPDATE under dry (`daily.py:95`), so the dry run reports stop moves and zero stops fired.*

1. *(Blocked on Q10)* how a position born outside the system gets its trail memory. §3.2 defines
   the trail as 10% below the highest close **since entry** and is silent on an entry that
   predates the system; §6 Step 0 says existing GTC stops stand. This is a ruling, not a gap to
   fill.
2. Until ruled, nothing ships. When it is: `book.sleeve` and the trail state (`highest_close`,
   `stop`, `trail_mode`) are written in the **same commit**, and `daily.ratchet` skips a position
   whose `highest_close` is NULL on its first pass rather than inferring one from history.
3. The acceptance check, replacing the vacuous "compare against the previous night's output" —
   the previous night's output is the empty set this step is fixing. The first run's
   `stop_moves` and `stops_fired` are reviewed line by line against what Zak actually holds at
   the broker, and **no computed stop above the last close is ever emitted**. The step states
   plainly that `DRY_RUN` does not exercise this path.
4. Depends on S13: quarantine and the un-ratchet path must be live first.

**Closes:** no clause of its own. It is what makes `3.2/trail-10`, `3.2/breakeven-ratchet`,
`3.2/euphoria-ratchet` and S9's stop clauses true of the running book rather than of the function
— today `daily.ratchet` selects an empty set and no position carries a trailing stop.

### S15 — Recompute what the old rules wrote

*Fixing the code touches no stored row. Every overwrite table currently holds numbers the plan
says are wrong: `universe.in_l0` from the $4 / one-day-$5M screen (S8), `bench` CCN and hurdles
from the whole-sector financial exclusion and the period-end `filing_date` fallback (S6),
`candidates.mcn` from four setup sub-scores instead of three (D7), `queue` triggers from the
superseded base scan (S7). These tables are rewritten only by their scheduled jobs, so an S6 that
lands on the 3rd leaves the bench wrong for four weeks while briefs quote it.*

Run once, in this order, each with its dry run inspected first (§0.5) and each preceded by the
`monthly-backup` the safety posture requires:

1. L0 rebuild — `monthly-funnel` stage 1 (S8).
2. Fundamentals re-extract under S5's meter and call budget, on a night the ingest does not run
   (S6.2, S6.3, S6.7).
3. `score` — bench, CCN, hurdles (S6), with the approvals and memos already preserved by S6.1.
4. `weekly-rank` — candidates and queue, with the S7.7 floor armed (S7, D7).
5. `daily` — marks, proximities, gaps.
6. Book stops — only after S14's ruling, and under its acceptance check.

**No brief may be believed between a code landing and its recompute finishing**, and the
freshness line says so for the duration.

**Closes:** no clause; it is what makes S6, S7, S8 and S14 true of the data as well as the code.

### S16 — Steady-state arming (the job half)

*§4.3 splits this work and the split is load-bearing: jobs arm candidates, only sessions write
tickets, because theme is judgment. Everything in this step writes `candidates`, `queue`, `book`
or a brief — never `tickets`. The session half is S17.*

1. The pyramid state machine — `book.pyramid_step` is never advanced today, so the breakeven
   ratchet can never fire.
2. Breakout confirmation on the live path (`policy.classify_breakout`), with late confirmation
   and the failed-breakout exit (`policy.failed_breakout`), and `policy.pyramid_may_arm` so a
   breakout confirming inside a blackout arms no adds. **Only once this exists may an add be
   armed** at pivot +2% and +4%, both limited at pivot × 1.05 (§3.2, §5.1).
3. Momentum exits: trend-template failure and MCN < 55, not just a fired stop.
4. The stalled-pyramid rule — below full size for 4 weeks, completes on the next base or exits.
5. `3.0/l2-composition` in full: the hurdle-proximity arm (`price ≤ 1.10 × hurdle`) and the
   spare-seat fill from L1-M by MCN rank.
6. Add eligibility, which nothing enforces anywhere today: (a) a momentum add is refused unless
   it is a pyramid step above the pivot — §2.4's table says the momentum sleeve averages down
   **never**; (b) a compounder add is refused past 2 in a trailing 12 months, counted from
   `tickets`/`transactions` and excluding tactical lots (§3.1: "max 2 adds per name per 12
   months (crash-protocol tactical adds exempt)"). Both are hard blocks on money-moving tickets
   and both currently have nothing in the path to refuse them.
7. The earnings cushion, wired to `policy.holds_through_earnings`: on the last session before a
   scheduled report, a momentum position below 1.08 × average cost arms an exit for that evening
   (§3.3). The nightly reports the blackout today and never tests the cushion.
8. Displacement is **armed** here — weakest incumbent, +10 margin, within sleeve only — and
   **drafted** by R1 in S17.2, per `5.1/r1-drafts-swap`.

**Closes:** `3.2/breakout-confirmation` · `3.2/failed-breakout` · `3.2/pyramid` ·
`3.2/pyramid-ceiling` · `3.2/stalled-pyramid` · `3.2/momentum-exits` ·
`3.3/blackout-beats-pyramid` · `3.3/earnings-cushion` · `3.0/l2-composition` ·
`2.4/no-averaging-down-momentum` · `3.1/averaging-down`.

### S17 — The five sessions, one at a time

*Five runbooks and eleven clauses cannot be one step: a step that claims nothing satisfies §0.1
vacuously. Each runbook is its own unit with its own schema prerequisite and its own claim. R2
first — it is the nightly receipt §4.7 leans on and the smallest. Then R1, which is where tickets
stop being written by a job.*

**S17.1 — R2, the evening stop sheet.** Heartbeat over both job windows → stop deltas → always
exactly one line minimum (§5.2). It carries two rules nothing else does: entering a blackout
**cancels live entry and add orders at the broker** while protective stops remain, always (§3.3
— "the stop sheet says so"), and the reflex layer's order shape — GTC stop-limit with limit =
stop − 3% (`stop_limit_buffer`), plus the gap-past-limit instruction to market-sell at open
(§4.6).
**Closes:** `5.2/r2-stop-sheet` · `3.3/blackout-cancels-orders` · `4.6/reflex-layer`.

**S17.2 — R1, the pre-open brief, and the end of D6.** The eight steps of §5.1, the entry
mechanic, the effective-bets number printed on every draft ticket (⚠️ below 4, never blocking),
max 2 new-entry tickets per brief. In the same commit series `phase0.py` becomes **arm-only**: it
writes its verdicts to `candidates` / `queue` / `book` and a brief, and R1 writes the tickets from
them through the §4.3 session verbs. That is what closes D6 — S12 gave sessions a write path and
took nothing away from the job. Ticket rows carry the account and its cash test including T+1
same-account reuse, and the **theme assigned by judgment in the session that writes the ticket**
(§2.2), which is where D1 stops being a job's problem. The Q4-blocked half: superseding or
cancelling a prior generation, including the state-changing version of S0.1.
**Closes:** `5.1/r1-preopen` · `5.1/r1-drafts-swap` · `2.2/jobs-arm-sessions-write` ·
`2.2/theme-cap-35` (D1) · `2.2/effective-bets` · `2.0/ticket-names-account` · `2.0/t1-reuse` ·
`3.3/displacement`.

**S17.3 — R4, Sunday reconciliation.** The fill loop end to end: chat or ticket flip →
provisional → book that night → Sunday confirm against the settled record; price/qty/FX/fees
trued up, balances anchored, NAV trued; shadow-book 30/60/90-day marks recorded as observations;
discrepancies flagged, never silently absorbed. Needs the S12 ruling on `balances` and
`transactions`, and Q4's transitions.
**Closes:** `5.4/r4-reconciliation` · `3.3/shadow-book`.

**S17.4 — R3, Saturday deep-dive.** Gate status and margin to the flip, top/bottom groups,
L1-M turnover, top-3 workups, queue changes, displacement checks against the +10 rule, and the
performance line — NAV week-over-week and YTD against the 30% bar, time-weighted. *(Blocked on
Q1* for the window and the observation cadence; `nav_snapshots` must be unique per date first,
S11a.3.)
**Closes:** `5.3/r3-deep-dive` · `5.6/performance-twr`.

**S17.5 — R5, monthly approval.** C2 memos and their durable store, bench changes,
purchase-anniversary re-underwrites, the evictions list, the audit snapshot, rejections recording
their CCN at rejection with the 12-month cooldown and its new-filing + CCN + 10 escape, and the
dual-qualification conversion — a momentum holding becomes a compounder only here, never
automatically, and its stops come off that day.
**Closes:** `5.5/r5-monthly` · `3.1/rejected-cooldown` · `3.3/dual-qualification`.

**S17.6 — the shared laws and the remaining schema.** §5.0 voice and §5.6 format laws as testable
requirements: every session writes its output to `briefs`, every output opens with the freshness
line, stale data ⇒ no new tickets, anything a runbook does not cover is flagged rather than
improvised. Plus the database support the five need and do not have: entry snapshots,
invalidators, purchase anniversaries, the C2 memo store, the rejection cooldown store.
**Closes:** `4.4/sessions` · `5.6/session-laws`.

### S18 — Leverage, account placement and the levered layer

*Q6 blocked "S8 leverage" in the previous draft and no such step existed — a ruling consumed by
nothing, while §6 Step 5 is part of the Phase 0 protocol S21 re-runs and §2.7 records CNQ as an
unresolved Review on exactly this test.*

1. §2.5's facility table as enforced rules: callable margin 50% utilization / ETFs only; secured
   LOC 50% / single names at CCN ≥ 85 or ETFs; HELOC full / single names at CCN ≥ 85 or ETFs.
   Callable facilities are never increased into strength; HELOC is exempt because it is not
   callable.
2. The CCN ≥ 85 test for a levered single name — Q6's subject exactly, and the §6 Step 5 verdict
   on CNQ.
3. The levered layer's accounting: levered weights enter the independence and theme calculation
   (§2.0's explicit exception) while consuming no sleeve room, no sleeve name count and no
   single-name cap. S9.5 builds the counting side; this step builds the facility side.
4. §2.6 account placement as a check rather than a habit: momentum in TFSA only, RRSP for
   compounder satellites and idle cash, the levered layer non-registered only, contributions
   routing TFSA → RRSP → non-registered, borrowed money never funding a registered account.
5. `config.levered_etf` = `VXC.TO` (D10, resolved 2026-07-31) — unhedged and CAD-listed per §2.5.

**Closes:** `2.5/leverage` · `2.6/account-placement` · `2.0/levered-outside-sleeves`.

### S19 — The crash protocol

*The market gate is ON today, so this subsystem's first exercise is a bear tape — and it is the
plan's entire prescription for the one regime where the CAD 200K is most at risk. §4.3 already
requires `book` to hold "lots (core/tactical)", and `book.lot` exists with nothing ever writing
`tactical`.*

1. Lots are real: adds made under this protocol are tagged **tactical at purchase**, and **core
   lots are never touched**.
2. Tranche state per name: compounder adds fire in **3 tranches, minimum 10 sessions apart**, so
   a tranche cannot re-arm early.
3. The gate-shut cascade: gate shuts → momentum stops fire, sleeve to cash → compounder hurdles
   breach and adds fire in tranches → freed momentum capital may fund compounder adds beyond
   standard sizing, tagged tactical. No cap on tactical allocation.
4. The gate-reopen rule: tactical lots are the funding source for momentum re-entry.
5. §3.3's order-execution law as the constraint the whole protocol lives under — single decisive
   orders at computed levels, momentum adds on strength only, compounder adds only below the
   hurdle, time-spaced tranches in exactly one context, which is this one.

**Closes:** `3.3/crash-protocol` · `3.3/order-execution`.

### S20 — Re-run the evidence

The backtest currently simulates rules the plan deleted and has lookahead on re-rank days. After
S6–S9 and S13–S16 land: fix the simulator to share `policy` rather than reimplement it, then
re-run both sleeves and re-grade.

**Acceptance is mechanical and is not a return.** §4.8 forecloses that: the compounder side is
"runnable but graded indicative-only … it is never validation. Validation is the shadow book,
forward-only." So a CAGR cannot be a pass. Instead:

1. Assertions on the trade log: no trade's entry bar equals its ranking bar (the lookahead); every
   simulated add fills at or below pivot × 1.05; add triggers are exactly +2% and +4%; no entry
   inside a blackout once report dates are stored.
2. A differential run stored as a new `backtest_runs` row recording the prior run's id in
   `params`, **with the expected direction of change written down before the run** — that makes
   the re-run a falsifiable prediction rather than a number.
3. The grade and the surviving bias list are written into the output row, not into prose in a
   findings document. The simulator's own list still includes "no M4 gate (point-in-time EPS not
   stored)" and "no earnings blackout (historical report dates not stored)", so S7.3's M4 fix and
   S9's blackout enforcement are invisible to it; survivorship cannot be repaired retroactively,
   because delisted names' bars were never ingested and S13.7 only helps forward.
4. State explicitly that the residual biases make this evidence that the simulator now simulates
   the rules — not a licence to trade them.

**Closes:** `4.8/backtest-grade`.

### S21 — Re-run Phase 0

The highest-consequence action in this document, and therefore the last. Preconditions, all of
them: S0's withdrawal confirmed · S6–S9 landed and recomputed through S15 · S14's ruling in and
trail state seeded · S16 arming live · **S17.2 shipped, so the re-run arms and R1 writes** ·
S18 for §6 Step 5 · S20's re-grade read.

The re-run itself is arm-only. It produces verdicts, the two opportunity pools and a brief; every
resulting ticket is written by R1 inside a session, with theme assigned there (§2.2) and the
account cash test applied (§2.0). Re-running the current `phase0` instead would write a fresh
batch of job-authored entry and exit tickets against a live CAD 200K book — the exact act §2.2
and §4.3 forbid, and the deviation D6 already records.

**Done when:** Zak holds exactly one generation of tickets, each traceable to a rule the ledger
marks wired, and no `proposed` row from before S0 survives.

**Closes:** no new clause — it re-verifies `6/re-underwrite` and `6/conforming-target-book`
against conforming rules.

### S22 — Cutover

The law's own remaining-work list carries this unchecked, and §4.8 requires the README to mirror
the §4.0 architecture table. S11, S12, S13 and S17 change that architecture materially — bulk
ingest replaces the per-ticker loop, the `api` schema arrives, six new stores land — so the
README's job table goes stale as a side effect of executing this plan.

1. Refresh the README's §4.0 mirror and job table.
2. Write Zak's operating guide — what changes for him at each step that lands, not only at the
   end. S9 changes what a ticket looks like; S14 turns the trailing stop on for the first time;
   S16 adds two more resting orders per breakout.
3. Write the final strategy doc out of the plan; archive the superseded docs.

**Closes:** no clause; it is the law's own unchecked TODO item.

---

## 3. Cross-cutting

Everything that used to float here — SHA pins, `sslmode`, migration checksums, the backup scrub,
golden fixtures, secret rotation — now has an owning step, because an item with no step number is
an item nobody does. What is left is genuinely diffuse:

**Property tests** where a property exists: the hurdle monotonic in the fair multiple, stops never
ratchet down (S13.8's recompute being the one sanctioned exception, and it says so), percentiles
bounded, `size = budget ÷ stop` monotonic in stop distance.

**`nav_cad` gets a test** — it has none, every position size depends on it, and S4.6 changes its
FX branch.

**Types.** `mypy` strict module by module, starting with `policy`.

---

## 4. Clause coverage

Every clause at OPEN or PENDING, and the step that owns it. S10.7 turns this table into a test;
BUILT-but-unwired clauses are covered by the step `Closes:` lines and checked the same way.

| Clause | Step |
|---|---|
| `2.0/levered-outside-sleeves` | S18 (counted in S9.5) |
| `2.0/provisional-balances` | S12 |
| `2.0/ticket-names-account` | S17.2 |
| `2.0/t1-reuse` | S17.2 |
| `2.2/theme-cap-35` | S17.2 (D1) |
| `2.2/jobs-arm-sessions-write` | S17.2 |
| `2.4/no-averaging-down-momentum` | S16.6 |
| `2.5/leverage` | S18 |
| `2.6/account-placement` | S18 |
| `3.0/l2-composition` | S16.5 |
| `3.1/foreign-fx` | S6.8 (Q8) |
| `3.1/effective-shares` | S6.8 (Q8) |
| `3.1/rejected-cooldown` | S17.5 |
| `3.2/stalled-pyramid` | S16.4 |
| `3.2/momentum-exits` | S16.3 |
| `3.3/displacement` | S16.8 arms · S17.2 drafts |
| `3.3/blackout-cancels-orders` | S17.1 |
| `3.3/delisted-retained` | S13.7 |
| `3.3/order-execution` | S19.5 |
| `3.3/crash-protocol` | S19 |
| `3.3/dual-qualification` | S17.5 |
| `3.3/shadow-book` | S17.3 |
| `3.3/versioning` | S11a.6 |
| `4.1/bulk-prices` | S13.1 |
| `4.1/corporate-actions` | S13.2 |
| `4.1/quota-meter` | S5.1 |
| `4.1/bar-retention` | S13.6 (prune on D5) |
| `4.2/five-scheduled-jobs` | S4.4 |
| `4.4/sessions` | S17.6 |
| `4.6/reflex-layer` | S17.1 |
| `4.8/backtest-grade` | S20.3 |
| `5.1/r1-preopen` | S17.2 |
| `5.1/r1-drafts-swap` | S17.2 |
| `5.2/r2-stop-sheet` | S17.1 |
| `5.3/r3-deep-dive` | S17.4 |
| `5.4/r4-reconciliation` | S17.3 |
| `5.5/r5-monthly` | S17.5 |
| `5.6/session-laws` | S17.6 |

Two clauses are **added** to the ledger by steps in this plan, both quoting plan text the ledger
does not yet index: `4.2/all-carry-dry-run` (S3.4) and `4.1/filing-archive` (S5.3).

---

## 5. Deliberately not doing

- Money as `numeric` instead of `double precision` — correct, but a large migration touching
  every table; raised separately.
- Options, shorting (D8, deferred by the plan).
- Learnings promotion thresholds (the plan says write them once real observations accumulate).

Nothing else is deferred. Every other clause in the ledger has a step in §4, and S10.7 fails the
build if that stops being true.
