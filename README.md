# Yuna — Zak's Trading Agent

*This repository is the machine. The plan is the law — it rides along verbatim at [`docs/yuna_plan.md`](docs/yuna_plan.md); where this README and the plan disagree, the plan wins.*

## Architecture (mirror of plan §4.0)

| Layer | What it is |
|---|---|
| **Data** | EODHD All-In-One: bulk prices nightly · FX · fundamentals on filing · earnings calendar. Bars kept 3 years, fundamentals forever |
| **Compute** | GitHub Actions jobs: `nightly-ingest` (+ `daily` duties) · `nightly-retry` · `weekly-rank` · `monthly-funnel` (census → `fundamentals` → `score`) · `monthly-backup` · one-shot `migrate` and `phase0` |
| **Store** | One Supabase Postgres project — universe → book → briefs, plus `fundamentals` as the point-in-time asset, and human views for browsing |
| **Judge** | Five Yuna sessions: evening stop sheet · pre-open brief · Sat deep-dive · Sun reconciliation · monthly approval |
| **Execute** | Zak places every order: entry pairs · stop moves · gap exits · fill confirmations · monthly approvals |
| **Protect** | GTC stop-limits living at Wealthsimple — protection that never sleeps with the pipeline |
| **Health** | Heartbeat: every job logs a run · every output opens with freshness · a missing message is the alarm |

## Ground rules

- **Yuna never executes.** She reads, computes, and writes briefs. Zak places every order.
- Every job is idempotent, carries `DRY_RUN`, and writes a heartbeat row. A missing message *is* the alarm.
- Computation never calls the API — every score reads the database.

## Layout

```
docs/            the plan (law) and build handoffs
migrations/      numbered SQL, applied by the dispatch-only `migrate` workflow
src/yuna/        the package
  rules.py       the plan-to-code ledger: every clause, its status, the @implements decorator
  policy.py      the plan's rules as pure functions — no db, no network, no clock
  db.py          shared plumbing: connection, config, vendor fetch, the heartbeat contract
  <job>.py       one module per job; each is plumbing that calls into policy
tests/           pytest; test_conformance.py enforces the ledger in both directions
.github/         workflows (all times UTC)
```

Jobs run as `python -m yuna.<job>`. Dependencies are pinned in `pyproject.toml` and
installed with `pip install -e .` — no workflow installs anything by hand.

## How a rule gets into the code

The plan is law, and the standing risk is drift in either direction: code that
quietly does something the plan never said, or a clause everyone assumed was built
and nobody built. Neither shows up in ordinary tests, because code that does the
wrong thing correctly still passes.

So every rule is written once, in `policy.py`, as a pure function that names its
clause:

```python
@implements("3.2/stop-8pct", "initial stop is the higher of the final-contraction low or entry - 8%")
def initial_stop(entry: float, contraction_low: float | None = None) -> float:
    ...
```

and every clause appears in `rules.py` with a status and — separately — whether any
running job actually calls it. Those are different questions, and conflating them is
how a build convinces itself it is finished. `tests/test_conformance.py` fails if a
decorator cites a clause that does not exist, if a clause cites a plan section that
does not exist, if something claims BUILT with no implementation, or if something
marked OPEN turns out to have code behind it. Migrations join the same ledger with a
`-- implements:` marker, so the rules that live in SQL are counted too.

Run `pytest -s tests/test_conformance.py` for the honest build state.

## Jobs, in the order the day runs them

| Job | Reads | Writes |
|---|---|---|
| `ingest.py` | EODHD bulk + per-ticker EOD | `prices` |
| `daily.py` | earnings calendar, `prices`, `book`, `bench`, `queue` | stops/trails, `nav_snapshots`, a `preopen` brief |
| `rank.py` | `prices`, `universe`, `v_fundamentals_latest` | `gate_state`, `candidates`, `queue` |
| `funnel.py` | EODHD symbol list + bulk + screener | `universe` (L0 census) |
| `fundamentals.py` | EODHD fundamentals | `fundamentals`, `universe` decorations |
| `score.py` | `fundamentals`, `prices` | `bench` (C1 → CCN → hurdle) |
| `phase0.py` | `book`, `bench`, `candidates`, `queue`, `balances` | `tickets`, a `phase0` brief |
| `backup.py` | everything but the bars | a compressed dump committed here |

Debug from `runs.detail`, never from Actions log downloads — those 302 to a blob store that
403s even unauthenticated. Every job embeds its traceback in the heartbeat, and an
`if: failure()` autopsy step catches deaths that happen before the heartbeat opens.

*First light: 2026-07-30.* 🌙
