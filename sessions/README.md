# Sessions — the judgment layer

The pipeline speaks first (§4.2: **ingest → score → check → speak**, where `compose` writes the
words and `notify` proves they exist); judgment happens in two interactive chats and two letters
(§4.4, 2026-08-04). Each runbook here is the session's code: same review, same care as a formula.
A session that did not write its `briefs` row did not happen.

**These five files are a mirror.** §4.8: the scheduled sessions have no repo checkout by design —
a session that needs the repo to know the law has two laws — so the runbooks they actually read
are the Project docs, and these copies exist for whoever is reading the code. They are the
**read-side contract this repo must satisfy**: `compose` writes what these sessions read, and if
it stops emitting `detail.composed='true'` or renames a `kind`, the sessions go silent and the
only symptom is a missing message.

| Surface | When (PT) | Runbook | Reads |
|---|---|---|---|
| Morning chat | ~06:00 Mon–Fri | `R1_preopen.md` | `v_session_payload` — one row |
| Stop sheet (push) | ~midnight, after the chain | `R2_stopsheet.md` | `briefs` `kind='stopsheet'`, composed, within 3h |
| Saturday letter (push) | ~10:00 Sat | `R3_deepdive.md` | `briefs` `kind='deepdive'`, composed, within 8h |
| Sunday reconciliation | ~09:00 Sun · interactive | `R4_reconcile.md` | `v_session_payload` — one row |
| Monthly letter | Sundays ~11:00, if the month has none | `R5_approval.md` | `briefs` `kind='monthly'` — its own month guard |

**The automated Claude sessions live inside the Yuna chat/cowork project** — ruled 2026-08-05.
The Routines above fire fresh sessions in the project's environment, carrying its Supabase and
EODHD connectors; `config.push_channel = 'cowork'` names them as `notify`'s delivery vehicle,
**and they are the §5.0 voice layer** — Claude runs here on Zak's plan, never on a metered API
key, which is why `compose` renders mechanically and stops. The stop sheet and Saturday letter
Routines author no data: one read of the composed `briefs` row, every number delivered intact,
voice in the framing only (their runbooks say exactly what happens when the row is missing).
The morning chat and Sunday/monthly sessions are where judgment happens.

The jobs those sessions read, per §4.2 — the canonical schedule, all UTC; **nothing joins it
without a plan edit**. **Only the ingests are scheduled** (ruled 2026-08-05): the four verbs behind
them chain in `pipeline.yml` by `needs:`, so their ordering is a data dependency and cannot invert
however late Actions queues the night.

| Job | When | What it owns |
|---|---|---|
| `ingest-daily` | `0 2 * * 2-6` and `0 3 * * 2-6` | bars, FX, corporate actions, earnings calendar, quarantine. The second firing exits if the night is already green |
| `ingest-universe` | `0 10 * * 6` | the L0 census — **rebuilds if the month's universe is unbuilt, else exits** |
| `ingest-filings` | `0 11 * * 6` | the filings sweep |
| `score` | chained to every ingest | every derived number, one writer. The Saturday chain is the full weekly rank |
| `check` | chained to every `score`, and at every session dispatch | every assertion plus the pre-flight; writes nothing but its report row |
| `compose` | chained to every `check` | writes the words down, mechanically and **keyless** (ruled 2026-08-05 — no metered model key, ever): the stop sheet + the next morning's brief sections nightly; the Saturday letter sections weekly. The monthly letter stays with the R5 session — rulings are judgment |
| `notify` | chained to every `compose` | proves the composed words exist before the doorbell rings; red when they don't (§4.7) |
| `backup` | `0 14 * * 6` (1st Sat) | the dump, minus daily bars — **and** GitHub's 60-day schedule keep-alive |
| `fills` | dispatch only | folds a broker export in `data/fills/` into tickets → transactions → book, when the Sunday path missed one |

**Two clocks, and only one of them decides anything.** The chain has no clock; the sessions keep
appointments. Each session fires at a fixed hour chosen to sit after the chain and opens with the
freshness line — a session that beats the chain says so rather than speaking stale. `late: <job>
+NNNm` on that line is a queue note and **holds nothing** (§4.7): lateness is not staleness, and
tickets are held only by old bars, a failed price-critical job, or a chain that ran out of order
(§5.6).

## The Routines are part of the system — keep them in sync

Each Routine's prompt points at `docs/yuna_plan.md` and the runbook beside it. The prompt is
deliberately a **pointer, not a copy**: the runbook is the code, and a prompt that restates it
drifts from it — silently, and in the direction of whatever the prompt was written against.

**So: any change to a runbook, to §4.4, or to §5 is not finished until the Routine prompt agrees
with it.** Review it the way you review a migration.

The prompts also carry one exclusivity rule, because a session that reaches outside this system
cannot be audited: the plan, the runbooks and the Supabase project are the whole world. Anything
else a session is pointed at — another store, another document, another connector — is not part
of this system, and the session says so in its output instead of using it.

Cron is UTC and does not shift with daylight saving, so each pick is stated against both regimes
and sits after the jobs it depends on. §4.2 makes the dependency a sequence — **ingest → score →
check → compose → notify → the session** — so every delivery fires after the words it delivers
exist, and every chat fires after a `check` has cleared the numbers it will read. The first four
links are `needs:` edges inside `pipeline.yml` and hold by construction; the last is an
appointment, and it can be beaten. A session that arrives before its words says so — the freshness
line is the first thing it prints — rather than delivering yesterday's.

**R5 fires every Sunday and exits if the month already has a `monthly` brief.** The guard keys on
the work, never the date: cron cannot express "first Sunday" (day-of-month and day-of-week are
OR-ed, not AND-ed), and the date-keyed version — "exit outside the first seven days" — skipped
August 2026 in silence. `ingest-universe` carries the same work key, in code (`funnel.py`).

**A red check blocks the brief.** §4.2: ambers print at the top of what you write; a red means a
published number cannot be rebuilt from its own row, so nothing derived from it may be spoken.
`compose` enforces this at authoring time (stale banner + protective lines only); the deliverers
enforce it again by refusing to author anything themselves. Protective instructions are the one
exception the plan keeps — §4.6 says protection survives everything.

R4 and R5 are **interactive** by §4.4: the Routine opens the session and prepares everything it
can, then waits for Zak. It is a start, not an autopilot.

## The write boundary — read this before touching anything

**Jobs compute · database remembers · Yuna judges · Zak acts** (§4.0). §4.3 enforces the first
half with guard triggers: the computed tables (`universe`, `prices`, `candidates`, `queue`,
`bench`, `book`, `armed`, `gate_state`, `nav_snapshots`, `earnings`, `fundamentals`,
`group_strength`, and — since migration 033 — `transactions`) reject any write that does not
arrive as the owner role. A session may write exactly six things (§4.3, 2026-08-04):

- `briefs` — its own output, always, even when the news is "nothing"
- `tickets` — with the **theme** attached (§2.2: theme is judgment, assigned in the session that
  writes the ticket), and the **fill fields** when Zak reports a fill (§4.5: chat or flip →
  ticket goes provisional; the nightly job derives the `transactions` row)
- `observations` — passes, exits, gate flips, breaches, notes
- `rulings` — every name-level verdict: C2 pass/fail (blind), exit reviews, conversions, sweep
  voids — each with its evidence block; **binding on later sessions**, reversible only by a new
  row citing new evidence
- `learnings` — the §5.8 ladder; every learning names its falsifier or the insert is refused
- `config` — insert-only, and never a value the plan states without the plan edit first (§4.3)

Never compute a score by hand. If a number you need is not in the database, say so in the brief
and stop — that is the §5.6 no-improvise law, and it is the difference between a research desk
and a guess.

## Reading the night's work

The interactive chats make **one read** (§5.6):

```sql
select * from v_session_payload;
```

Everything is on that row: the check report (freshness, blocks_dispatch, ambers, preflight), the
armed conclusions, the book, the queue, the gate, NAV, the full blackout wall, the unruled
docket, open tickets, brewing learnings, and the composed briefs. Notes on the armed rows:

- `urgency='protective'` — stop moves, fired stops, gap-throughs, gate-off exits, blackout
  cancels. **These go to Zak even on a stale-data night.** Protection never waits.
- `blocked_by` non-null — armed but held back by a §2 or §3.3 rule. Context, never a ticket.
- `detail->>'needs_ruling' = 'true'` — §3.1: rule it blind before its GTC ships.
- `kind='check'` — judgment asked of you: an invalidator read, a sub-55 CCN wanting a memo.

## Turning an armed row into a ticket

```sql
insert into tickets (ticker, account, sleeve, action, reason, order_type, trigger_price,
                     limit_price, qty, stop, stop_limit_price, theme, effective_bets, state,
                     brief_id, arm_key, note)
values (…, 'proposed', …);
```

`arm_key` is `ticker|action|reason|price` — a unique index refuses a duplicate while the ticket
is live, so re-running a session cannot double-publish. **Two new-entry tickets per brief,
maximum** (§5.1); extras wait in queue order and get named as context. Adds, exits and
protective moves are never throttled. **No ticket for an unruled name, ever** (§3.1).

The ticket lifecycle is `proposed → approved → provisional → confirmed`. Zak saying "placed"
moves it to approved; a fill (his word, or the price trading through a resting order) writes the
`fill_*` fields and makes it provisional; Sunday's reconciliation trues the fill fields and flips
it to confirmed — the nightly job mirrors each step into `transactions`.

## Setup, once

The Routines carry the project's Supabase MCP connector. The write boundary is enforced by the
guard triggers regardless of role; the `yuna_session` role (migration `020` + `033`) is the
belt-and-braces lock for a least-privilege connector when one is pointed at it. The owner
credential `DATABASE_URL` stays in GitHub Actions secrets and nowhere else.
