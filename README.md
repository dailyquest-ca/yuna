# Yuna — Zak's Trading Agent

*This repository is the machine. The plan is the law — it rides along verbatim at [`docs/yuna_plan.md`](docs/yuna_plan.md); where this README and the plan disagree, the plan wins.*

**Three documents, and only three.** [`docs/yuna_plan.md`](docs/yuna_plan.md) is the law.
[`docs/roadmap-2026-08-16.md`](docs/roadmap-2026-08-16.md) is the build order — what is done, what
drifted from the law, what gets built next and in which order. [`docs/learnings.md`](docs/learnings.md)
is the scar tissue: facts this build paid for, worth reading before touching anything.

Everything else in `docs/` is **dated evidence, not instruction** — and some of it has been
overturned by a later run. [`docs/README.md`](docs/README.md) is the index: what to read, what is
superseded, and why.

**v1.0, promoted 2026-08-15, replaced the engine.** One momentum sleeve in the TFSA, ranked by a
single number, gated on SPY's 200-day. The fundamentals machine that came before it — CCN, hurdles,
the bench, arming, stops and trails — is retired from the schedule and survives only as dispatch-only
tooling. [`docs/wo-a23-the-engine-takes-production.md`](docs/wo-a23-the-engine-takes-production.md)
is the record of that changeover.

## Architecture (mirror of plan §4)

| Layer | What it is |
|---|---|
| **Data** | EODHD **EOD Historical Data — All World** (§4.5): end-of-day bars for US common stocks + SPY, exchange symbol lists, delisted lines. **No fundamentals, news, intraday or calendar feeds are read by any decision** |
| **Compute** | **ingest → reconcile → score → check → compose → notify.** Three scheduled workflows (`ingest-daily` ×2 · `ingest-universe` · `backup`) and the chain hanging off them by `needs:` in `pipeline.yml`, with §6.4's `shadow` beside `check` — **the chain has no clock; the sessions keep appointments** (2026-08-05). Everything else — `migrate`, `backfill`, `closeout`, both backtests, and every retired legacy job — is **dispatch-only tooling**; nothing joins the schedule without a plan edit |
| **Store** | One Supabase Postgres project — universe → tape → `engine_sessions` / `engine_ranks` → tickets → book, plus the `learnings` ledger and human views for browsing |
| **Judge** | The morning brief and §4.1's Saturday letter, delivered by the Routines in the Yuna chat/cowork project. Judgment happens in chat; arithmetic happens in the pipeline (§5.1) |
| **Execute** | Zak places every order — at the open, **sells first, then buys** (§3.5) |
| **Protect** | §3.4's gate. **No stops and no GTC orders exist anywhere in this system** (§4.3) — a red session sells the whole book at the next executable open, and that is the entire defence |
| **Health** | Heartbeat: every job logs a run · every output opens with freshness · a missing message is the alarm (§4.7) |

## Ground rules

- **Yuna never executes.** She reads, computes, and writes proposals. Zak places every order (§0.2).
- **The rank is the entire opinion** (§3.3). No earnings, no themes, no fundamentals, no news.
- **Every constant traces to §3.6.** A number with no clause behind it does not throw — it produces a
  plausible position size and places a real order. `engine.py` quotes the clause beside each one, and
  `engine.digest()` stamps them on every decision so a change is visible after the fact.
- **Any red holds buys; nothing holds exits** (§4.4). §5.4 makes gate-off exits and rank-exit sells
  protective-direction and never blocked — by freeze, by amber, or by any throttle.
- Every job is idempotent, carries `DRY_RUN`, and writes a heartbeat row. A missing message *is* the
  alarm.
- Computation never calls the API — every score reads the database.
- **`briefs.session_date` is the market session an output serves**, derived from the newest bar, not
  from `now()::date` in UTC — the chain runs in the evening of the session it reports on. §3.5 marks
  position size at the *decision close*, and the sheet executes at the *next open*.

## Layout

```
docs/         the plan (law), the roadmap (build order), the learnings (scar tissue)
              + dated evidence — see docs/README.md for what supersedes what
migrations/   numbered SQL, applied by the dispatch-only `migrate` workflow
src/          ingest + compute jobs (Python); db.py holds the shared heartbeat contract
.github/      workflows (all times UTC)
```

## Jobs, in the order the day runs them

| Job | Reads | Writes |
|---|---|---|
| `ingest.py` | EODHD bulk + per-ticker EOD, corporate actions, FX | `prices`, `corporate_actions`, `quarantine`, FX pairs on `universe` |
| `reconcile.py` | `data/reconcile/*.json` — the broker's receipts **and its position list** | `transactions` → `book`; advances tickets `approved → executed → reconciled` (§4.3) |
| `sheet.py` | the tape, `book`, `config.engine_nav` | `engine_sessions`, `engine_ranks`, and §4.3's tickets in state `proposed` |
| `gauges.py` | the tape and everything `sheet` wrote | nothing but its own report row — a checker that can edit what it checks is a participant, not a witness |
| `shadow.py` | the tape, `concentrated.py` | `shadow_attestations` — §6.4's written record |
| `brief.py` | `v_session_payload`, one read | a composed `briefs` row: §5.1's morning brief, or §4.1's Saturday letter |
| `notify.py` | composed `briefs`, `config.push_channel` | nothing but its runs row — proves the words exist before the Routines deliver them |
| `backup.py` | everything but the bars | a compressed dump committed here |

**Dispatch-only.** `desk.py` (tonight's sheet, read-only) · `closeout.py` (§6.2, once) ·
`migrate.py` · `backfill.py` · `verify_run.py` · `concentrated.py` and the rest of the research
grid · and the retired legacy machine (`score.py`, `check.py`, `compose.py`, `fills.py`,
`signals.py`, `arming.py`, `rank.py`, `fundamentals.py`, `funnel.py`, `phase0.py`).

Debug from `runs.detail`, never from Actions log downloads — those 302 to a blob store that
403s even unauthenticated. Every job embeds its traceback in the heartbeat, and an
`if: failure()` autopsy step catches deaths that happen before the heartbeat opens.

*First light: 2026-07-30. The engine took production: 2026-08-16.* 🌙
