# Yuna — Zak's Trading Agent

*This repository is the machine. The plan is the law — it lives with Yuna's project and ships here at cutover (Phase F).*

## Architecture (mirror of plan §4.0)

| Layer | What it is |
|---|---|
| **Data** | EODHD All-In-One: bulk prices nightly · FX · fundamentals on filing · earnings calendar. Bars kept 3 years, fundamentals forever |
| **Compute** | Five GitHub Actions jobs: `nightly-ingest` · `nightly-retry` · `weekly-rank` · `monthly-funnel` · `monthly-backup` |
| **Store** | One Supabase Postgres project — 11 tables (universe → book → briefs) + human views for browsing |
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
migrations/   numbered SQL, applied via Supabase
src/          ingest + compute jobs (Python)
.github/      workflows (all times UTC)
```

*First light: 2026-07-30.* 🌙
