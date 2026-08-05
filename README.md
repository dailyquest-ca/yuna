# Yuna — Zak's Trading Agent

*This repository is the machine. The plan is the law — it rides along verbatim at [`docs/yuna_plan.md`](docs/yuna_plan.md); where this README and the plan disagree, the plan wins.*

**Three documents, and only three.** [`docs/yuna_plan.md`](docs/yuna_plan.md) is the law.
[`docs/roadmap-2026-07-31.md`](docs/roadmap-2026-07-31.md) is the build order — what is done, what
drifted from the law, what gets built next and in which order. [`docs/learnings.md`](docs/learnings.md)
is the scar tissue: facts this build paid for, worth reading before touching anything.
(`docs/backtest-findings-2026-07-31.md` is dated evidence, not instruction.)

## Architecture (mirror of plan §4.0)

| Layer | What it is |
|---|---|
| **Data** | EODHD All-In-One: bulk prices nightly · FX · fundamentals on filing · earnings calendar. Bars kept 10 years, fundamentals forever |
| **Compute** | One sentence — **ingest → score → check → speak**. Eight scheduled jobs: `ingest-daily` ×2 · `ingest-filings` · `ingest-universe` · `score` · `check` · `compose` + `notify` (the speak pair) · `backup`. Everything else — `migrate`, `phase0`, `backfill`, both backtests — is **dispatch-only tooling**; nothing joins the schedule without a plan edit (§4.2) |
| **Store** | One Supabase Postgres project — universe → book → briefs, plus `fundamentals` as the point-in-time asset, the `rulings` + `learnings` ledgers, and human views for browsing |
| **Judge** | Two chats (weekday morning · Sunday reconciliation) + two letters (Saturday · monthly); the stop sheet and all alarms are pipeline pushes delivered by the Routines in the Yuna chat/cowork project. Yuna rules names; Zak rules law and risk |
| **Execute** | Zak places every order: entry pairs · stop moves · gap exits · fill confirmations · monthly law-and-risk rulings |
| **Protect** | GTC stop-limits living at Wealthsimple — protection that never sleeps with the pipeline |
| **Health** | Heartbeat: every job logs a run · every output opens with freshness · a missing message is the alarm |

## Ground rules

- **Yuna never executes.** She reads, computes, and writes briefs. Zak places every order.
- Every job is idempotent, carries `DRY_RUN`, and writes a heartbeat row. A missing message *is* the alarm.
- Computation never calls the API — every score reads the database.

## Layout

```
docs/         the plan (law), the roadmap (build order), the learnings (scar tissue)
migrations/   numbered SQL, applied by the dispatch-only `migrate` workflow
src/          ingest + compute jobs (Python); db.py holds the shared heartbeat contract
.github/      workflows (all times UTC)
```

## Jobs, in the order the day runs them

| Job | Reads | Writes |
|---|---|---|
| `ingest.py` | EODHD bulk + per-ticker EOD | `prices` |
| `daily.py` | earnings calendar, `prices`, `book`, `bench`, `queue` | stops/trails, `nav_snapshots`, a `preopen` brief |
| `rank.py` | `prices`, `universe`, `v_fundamentals_latest` | `gate_state`, `candidates`, `queue` |
| `funnel.py` | EODHD symbol list + bulk + screener | `universe` (L0 census) |
| `fundamentals.py` | EODHD fundamentals | `fundamentals`, `universe` decorations |
| `score.py` | `fundamentals`, `prices` | `bench` (C1 → CCN → hurdle) |
| `compose.py` | `v_session_payload` | composed `briefs` — the stop sheet, morning-brief and Saturday-letter sections, rendered mechanically and keyless; the project's scheduled sessions apply the §5.0 voice on Zak's Claude plan (§4.2 speak, first half) |
| `notify.py` | composed `briefs`, `config.push_channel` | nothing but its runs row — proves the words exist before the Routines deliver them |
| `phase0.py` | `book`, `bench`, `candidates`, `queue`, `balances` | `tickets`, a `phase0` brief |
| `backup.py` | everything but the bars | a compressed dump committed here |

Debug from `runs.detail`, never from Actions log downloads — those 302 to a blob store that
403s even unauthenticated. Every job embeds its traceback in the heartbeat, and an
`if: failure()` autopsy step catches deaths that happen before the heartbeat opens.

*First light: 2026-07-30.* 🌙
