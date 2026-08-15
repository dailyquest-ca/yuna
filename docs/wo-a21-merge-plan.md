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

## 4. Recommended sequence

Four PRs, smallest risk first. Each is independently revertible.

**PR 1 — the auditor and the tooling.** `verify_run.py`, `dedupe_scan.py`, `capture_audit.py`,
`push_study.py`, `blend.py`, `bars.py`, `finding.py`, `backtest_report.py`, `concentrated.py`,
their tests, and the docs. Nothing in the nightly path imports any of it. *Also fixes the CI
email spam:* `tests/integration/conftest.py` adds `push_study` to the truncate list.

**PR 2 — the parity proof.** `tests/test_refactor_parity.py` alone, against the current
`arming.py` and `fundamentals.py` on main. It must pass **before** the refactors land, so the
proof exists independently of the thing it proves.

**PR 3 — the production refactors.** `signals.py`, `arming.py`, `fundamentals.py`, `db.py`,
`check.py`. PR 2's tests turn green against the new code and stay green.

**PR 4 — the verification instrument.** `backtest.py` and `test_price_integrity.py`. Record the
current law-backtest headline in the PR body, merge, re-run, and record the new one.

---

## 5. What must NOT merge yet

**The eleven migrations (038–048).** They change production data: benchmarks and a riskless rate,
warrant and test-symbol exclusions, the deduplicated universe, the push ledger becoming a table,
and two passes at duplicate listings. `migrate.yml` is dispatch-only, so merging does not apply
them — but it makes them applicable, and several were written against a tape that has since been
re-fetched. **Each needs its evidence re-checked against the current census before it is
dispatched**, which is exactly the staleness learning 35 records.

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
