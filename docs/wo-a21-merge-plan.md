# WO-A21 · The merge plan

**Written 2026-08-15.** What is on `claude/pickup-previous-session-s3wduf`, what is safe to put on
`main`, and what must not go until the plan is amended.

**Scope of this merge: the verification instrument and the research tooling. Nothing that changes
what the nightly machine decides, and nothing that adopts V2.**

---

## 1. The situation

`main` is at `e57dd34` (2026-08-12) and has not moved. The merge base **is** main's head, so all
183 commits are this programme: 73 files, +24,003 / −475.

That is far too large to merge as one reviewed change, and most of it is not the same *kind* of
change. It splits into four groups.

| group | files | risk | verdict |
| --- | --- | --- | --- |
| **A. Research tooling** | 10 new `src/` modules, 11 new test files, 27 docs | none — nothing imports them from the pipeline | **merge** |
| **B. Verification instrument** | `backtest.py`, `signals.py`, `db.py`, `check.py` | changes the law backtest; production surface proven unchanged | **merge, with §3** |
| **C. Production refactors** | `arming.py`, `fundamentals.py` | moved live arithmetic into `signals.py` | **merge — parity now proven** |
| **D. Migrations & workflows** | 11 migrations, 4 workflow files | changes the database and the schedule | **hold — §5** |

---

## 2. What is verified, and how

### 2.1 The production path is untouched

The nightly machine is: `ingest-daily` / `ingest-universe` / `ingest-filings` on cron, then
`slot → score → check → compose → notify` chained by `workflow_run`. Those scripts import
`db`, `signals`, `arming` and `rank`.

**`rank.py` is byte-identical to main.** It is the only consumer of `signals` in the scoring path,
so if `signals` returns what it returned before, scoring is unchanged.

**Differential test, 300 random bar sets, every `signals` function `rank.py` calls:**

| function | result |
| --- | --- |
| `momentum_quality` | identical |
| `trend_template` | identical |
| `base_scan` | identical |
| `setup_proximity` | identical |
| `initial_stop` | identical |
| `mcn` | identical |
| `pct_rank` | identical |
| `market_gate` | identical |

Two of those gained keyword arguments — `momentum_quality(vol_divisor=True)` and
`trend_template(off_high=0.25)` — and **both defaults reproduce main**. The new values exist so the
backtest can price the alternative; the law is the default.

`signals.py`'s +482 lines are otherwise **additive**: new functions the backtest needs, called from
nowhere in the nightly path.

### 2.2 The two refactors that moved live arithmetic

These are the ones that could have changed a real number without changing a caller, and
`wo-a15-v1-synthesis.md` §5 named the first as a condition of reaching main.

| refactor | from | to | proof |
| --- | --- | --- | --- |
| M4 acceleration | `fundamentals.py:441-449` | `signals.m4_acceleration` | `tests/test_refactor_parity.py`, 10 named cases + a **4,096-case generated sweep** |
| breakout confirmation | `arming.py:288-292` + `signals.breakout_confirmed` | `signals.confirmation_state` | 11 cases spanning confirmed / pending / failed |

Both transcribe main's implementation into the test rather than importing it, so the tests keep
their meaning after main moves.

**Worth recording: the first draft of the confirmation test failed twice, and the test was wrong,
not the code.** It compared against `breakout_confirmed` alone when the tri-state also depends on
`arming.py`'s expiry line, and it took the window from the end of the list when main takes it from
the front. Transcribing from a diff instead of from the source is how that happens.

### 2.3 `db.py` and `check.py`

`db.py` **+57/−1**: adds `DECISION_KEYS` and `config_digest`. Purely additive.

`check.py` **+39/−1**: adds `check_backtest_is_current`. This is a **new guard that will fire** —
it ambers when the newest backtest is older than eight days or was run under a different config
digest. That is the intended behaviour and the reason it exists, but it is a change in what the
nightly reports, and it should be expected rather than discovered.

---

## 3. What merging group B actually changes

**`backtest.py` +2,916.** It runs on PR and on push to `main` for its own paths, and on the weekly
chain. It is not on the nightly critical path. Merging it changes the law backtest's numbers,
because the discontinuity guard was broken in three ways and is now fixed:

- the basis floor hid mis-stated split factors under $1 — **136 names, 1,865 bars**
- the comparison was row-adjacent, so seams across trading gaps were invisible — `CLSK.US` at 9,372×
- neither is a strategy change; both are the guard doing what it already claimed to do

**Expect the law backtest's headline to move on the first run after merge.** That is the correct
outcome and the reason to merge it, but the current numbers should be recorded first so the
before/after is legible rather than surprising.

---

## 3A. The cleanup, done 2026-08-15

Three things were owed before any of this is reviewable by someone who was not here.

**Dead code.** There is no linter in CI, so this was measured rather than assumed: `ruff --select
F,E9` against `main`'s tree flags **33**, against this branch **37**. Seven of the branch's were
introduced here; the rest are `main`'s and are deliberately left alone, because an unrelated
cleanup inside a 24k-line diff is how a real change hides. The seven were two dead locals in
`backtest.py` (`j = col[tk]` left behind when dividends went to zero, `k = t - entry_idx + 1`
replaced by the `window` range — neither read anywhere, both checked), unused imports in
`concentrated.py`, `push_study.py`, `test_concentrated.py` and `test_verify_run.py`, and a dead
`n = 500` in a fixture. **The branch now flags 30 against `main`'s 33.** Both suites re-run after:
567 unit, 151 integration, green.

**A docs directory that had stopped being navigable.** 42 files at one level, against a root
README that says *"three documents, and only three."* `docs/README.md` is now the index — the three,
then the programme, then the earlier record — and it marks what is superseded.

**Superseded documents that did not say so.** This is the one that could have cost something.
`wo-a15-v1-synthesis.md` states at the top what *it* supersedes and nothing about being superseded
itself, so a reader would have taken `b5_12_3` — a cell selected on the defective tape — as the
answer. Four documents now carry a warning block: `wo-a15` (wrong cell, defective tape), `wo-a17`
(§3's finding stated too broadly, §3.1's decomposition invalid), `synthesis-2026-08-14.md` (all
numbers pre-screen, one window), and the `backtest-findings` pair, which already had theirs. Each
block also says **what still stands**, because a superseded document is not a worthless one.

`roadmap-2026-07-31.md` — one of the three — had not moved since 08-11. It now carries a dated
addendum: what closed, what new debt this created, and the fact that production is untouched. Its
"both backtests bypass `signals.py`" debt row is closed and marked: `backtest.py` went from **0 to
45** `signals` calls across 33 distinct functions.

---

## 4. Recommended sequence

### 4.0 The first draft of this section was wrong three times

Written from the shape of the diff rather than from the imports, and **each error would have put a
red build on `main`.** Recorded rather than quietly fixed, because the lesson is the reusable part.

1. **PR 1 could not have contained `concentrated.py` or `blend.py`.** They import eight symbols
   from `backtest.py` — `SPREAD_CURVE`, `BENCH`, `PARK_BAND`, `PARK_CHECK_EVERY`, `param_digest`,
   `_discontinuous`, `MAX_QUARANTINE_SHARE`, `DataIntegrityError` — and **`main` has none of them.**
   Collection-time `ImportError`. Same for `push_study.py`, which needs `signals.regression_momentum`.
2. **PR 2 as written was impossible.** "Land the parity test first, against `main`'s `arming.py`
   and `fundamentals.py`" — except the test calls `sg.m4_acceleration` and `sg.confirmation_state`,
   and neither function exists on `main`. It cannot run before the refactor it proves. The instinct
   was right and the mechanism was wrong: **what makes the test independent is that it transcribes
   `main`'s implementation instead of importing it.** That property does not need an ordering.
3. **The `conftest.py` change was described as a free bonus.** It truncates `push_study`,
   `bill_rates` and `universe_excluded` — three tables created by migrations §5 holds back. Taken
   without them, **every one of the 153 integration tests errors**, not just the new ones.

**4. `tests/test_concentrated.py` reads `src/backfill.py` off disk at runtime** and `exec`s its
   `probe_dates`. Main's `backfill.py` has no such function, so the test raises `ValueError` on a
   tree without it. Found while assembling PR 4 — and **no import graph would have shown it**,
   because the dependency is a file read, not an import.

The first three were found by building PR 1 in a worktree on top of `origin/main` and running it
against a fresh database; the fourth by doing the same for PR 4. That is now the standard: **a PR in this sequence is not proposed until it has
been assembled and run against the branch point it targets.**

### 4.1 One dependency the plan had missed entirely

`verify_run.py`, `dedupe_scan.py` and `capture_audit.py` all query **`universe_excluded`** in SQL,
and migration 041 creates it. §5 holds all eleven migrations, so the auditor would have shipped
unable to run.

041 does two separable things: it creates the table, then inserts twelve hand-curated exclusions.
**The tools need the first. The twelve rows are exactly what should wait** — the tape has been
re-fetched since 041 was written, and its own APPS/BDN entry says "pending a re-pull". So
`049_the_exclusion_table.sql` carries the DDL alone, and 041 stays untouched: its
`create table if not exists` becomes a no-op, its inserts stay `on conflict do nothing`, and
dispatching it later still applies precisely the rows it always did.

**An empty exclusion table is the honest default** — "nothing has been ruled out yet" is true;
"these twelve were ruled out on evidence last checked in August" is not.

### 4.2 The sequence, corrected and verified

| PR | contents | why it can go |
| --- | --- | --- |
| **1** | `verify_run.py`, `dedupe_scan.py`, `capture_audit.py`, `finding.py`, `bars.py`, `backtest_report.py` · their tests · **all** docs · `migrations/049` · `conftest` + `universe_excluded` · `dedupe.yml` · `README.md` | imports only `db.connect/dry/Heartbeat/config`, all present on `main`. **Verified: 205 unit + 151 integration green on top of `origin/main`, fresh database.** |
| **2** | `signals.py`, `arming.py`, `fundamentals.py`, `db.py`, `check.py` · **`test_refactor_parity.py` in the same PR** | the parity test cannot precede the functions it calls. Its independence comes from transcription, not from ordering — §2.2 |
| **3** | `backtest.py` · `test_price_integrity.py` · `test_backtest_engine.py` | needs PR 2's `signals`. Record the current law-backtest headline in the PR body, merge, re-run, record the new one — §3 |
| **4** | `concentrated.py`, `blend.py`, `push_study.py` · `test_concentrated.py`, `test_blend.py`, `test_push_study.py`, `test_tail_equivalence.py` | needs PR 3's `backtest` symbols and PR 2's `signals.regression_momentum` |

Each is independently revertible. **PR 1 changes no production data**: migration 049 creates one
empty table and `migrate.yml` is dispatch-only, so merging does not even apply it.

---

## 5. What must NOT merge yet

**The eleven migrations (038–048)** — every one, including 041, whose DDL is carried separately by
049 precisely so that its twelve rows can keep waiting (§4.1). They change production data:
benchmarks and a riskless rate, warrant and test-symbol exclusions, the deduplicated universe, the
push ledger becoming a table, and two passes at duplicate listings. `migrate.yml` is dispatch-only,
so merging does not apply them — but it makes them applicable, and several were written against a
tape that has since been re-fetched. **Each needs its evidence re-checked against the current
census before it is dispatched**, which is exactly the staleness learning 35 records.

Two consequences of holding them, both intended. `push_study` and `bill_rates` do not exist until
the migrations land, so `push_study.py` (PR 4) cannot run against production until then — it can
still be reviewed and merged. And the `conftest` truncate list grows in step with the tables, one
line per PR, rather than arriving ahead of them.

**The workflow changes**, except the `dedupe` job and the `conftest` fix. `backtest.yml` gained
research jobs and an audit step that **fails the build on a failed audit** — correct, and it will
turn runs red that currently pass.

**Every V2 decision.** `2/12`, the regime gate, the tight latch, the theme cap — all of it is
research output in `docs/`, and none of it is adopted by any scheduled job. The cells exist in
`concentrated.py`, which is dispatch-only. **Nothing in this merge changes what the machine
decides, and adopting V2 is a `docs/yuna_plan.md` amendment, not a merge.**

---

## 6. Known-open, carried forward

- Duplicate listings: the scan correctly refuses to propose a cut; `BBBY_old`/`BBBY` held together
  for nine sessions in 2018 stands as a measured, unfixed defect. `verify_run.py`'s B7 detects any
  recurrence.
- Bar geometry: 1,432 malformed bars, **none of which reached a fill**.
- Foreign listings: the participation gate is built; its threshold is unruled.
- No cash-like park ticker exists, so every gated figure understates a cash-parked gate.
- §2.5 reads `unproven` at a deflated Sharpe of 0.214 against a 0.95 bar.
