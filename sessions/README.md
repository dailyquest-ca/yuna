# Sessions — the judgment layer

Five sessions, specified in plan §4.4 and §5. Each runbook here is the session's code: same
review, same care as a formula. A session that did not write its `briefs` row did not happen.

| Session | When (PT) | Runbook | Routine | Cron (UTC) |
|---|---|---|---|---|
| Pre-open brief | ~06:00 Mon–Fri | `R1_preopen.md` | `trig_01W7BGqssY4sCztZp4L4H5ND` | `0 13 * * 1-5` |
| Evening stop sheet | ~20:30 Mon–Fri | `R2_stopsheet.md` | `trig_012LkXUzXqXwj2xD7Fqwqxxy` | `0 4 * * 2-6` |
| Saturday deep-dive | ~08:00 Sat | `R3_deepdive.md` | `trig_01RKq8cdVHsnFvCUQY287KT6` | `0 16 * * 6` |
| Sunday reconciliation | Sun morning | `R4_reconcile.md` | `trig_014bPbo18uPXJTWncvduwKTT` | `0 16 * * 0` |
| Monthly approval | 1st weekend | `R5_approval.md` | `trig_01WSDzax7TCUeZrGPqWSurMs` | `0 17 * * 0` + guard |

## The Routines are part of the system — keep them in sync

Each session is started by a scheduled Routine whose prompt points at `docs/yuna_plan.md` and the
runbook beside it. The prompt is deliberately a **pointer, not a copy**: the runbook is the code, and
a prompt that restates it drifts from it. That drift is not hypothetical — until 2026-08-01 both
scheduled Routines still ran the superseded Airtable system, read `claude/strategy.md` as law, and
spoke a vocabulary (campaigns, ladder marks, the regime dial) that appears nowhere in this plan. They
were rewritten and the old ones deleted.

**So: any change to a runbook, to §4.4, or to §5 is not finished until the Routine prompt agrees
with it.** Review it the way you review a migration.

Cron is UTC and does not shift with daylight saving, so each pick is stated against both regimes and
chosen to sit after the jobs it depends on. R2 fires at 04:00 UTC — after `nightly-retry` at 03:00 —
so it can act as §4.7's nightly receipt for a night that has actually finished. R3 fires at 16:00
UTC, after `weekly-rank` at 12:00 and `monthly-funnel` at 10:00. R5 fires weekly and exits silently
outside the first seven days of the month, because cron cannot express "first Sunday" (its day-of-
month and day-of-week fields are OR-ed, not AND-ed).

R4 and R5 are **interactive** by §4.4: the Routine opens the session and prepares everything it can,
then waits for Zak. It is a start, not an autopilot.

> ⚠️ **Open dependency:** Routines created through the MCP tool store no connector grants — this
> organization does not permit passing them — so a fired session has no `mcp__Supabase__*` tools and
> cannot reach state. Until either (a) the connectors are attached to each Routine in the claude.ai
> Routines UI, or (b) `DATABASE_URL` and `EODHD_API_KEY` are set on the CCR environment so the
> sessions can connect directly, these Routines will fire and produce nothing. Neither credential is
> currently present in the environment.

## The write boundary — read this before touching anything

**Jobs arm. Sessions judge. Zak executes.** §4.3 enforces the first half with guard triggers: the
computed tables (`universe`, `prices`, `candidates`, `queue`, `bench`, `book`, `armed`,
`gate_state`, `nav_snapshots`, `earnings`, `fundamentals`, `group_strength`) reject any write that
does not arrive as the owner role. A session may write exactly four things:

- `briefs` — its own output, always, even when the news is "nothing"
- `tickets` — the ticket a Zak-facing instruction implies, with the **theme** attached (§2.2:
  theme is judgment, assigned in the session that writes the ticket)
- `observations` — passes, exits, gate flips, C2 calls, breaches, learnings
- `transactions` — a provisional fill Zak reports in chat (§4.5); the nightly job folds it into
  the book and Sunday confirms it

Never compute a score by hand. If a number you need is not in the database, say so in the brief
and stop — that is the §5.6 no-improvise law, and it is the difference between a research desk and
a guess.

## Reading the night's work

`duties.py` writes one `armed` row per conclusion, already priced and cap-checked:

```sql
select kind, ticker, reason, urgency, order_type, trigger_price, limit_price,
       stop, stop_limit_price, qty, size_pct, score, blocked_by, note
  from v_armed_latest order by urgency desc, kind, score desc nulls last;
```

- `urgency='protective'` — stop moves, fired stops, gap-throughs, gate-off exits, blackout
  cancels. **These go to Zak even on a stale-data night.** Protection never waits for the pipeline.
- `blocked_by` non-null — the machine armed it and a §2 or §3.3 rule holds it back. Report the
  best ones as context ("MSFT is at its hurdle but the tech group already has two names"), never
  as a ticket.
- `kind='check'` — judgment asked of you: an invalidator read, a sub-55 CCN wanting a memo.

## Turning an armed row into a ticket

```sql
insert into tickets (ticker, account, sleeve, action, reason, order_type, trigger_price,
                     limit_price, qty, stop, stop_limit_price, theme, effective_bets, state,
                     brief_id, arm_key, note)
values (…, 'proposed', …);
```

`arm_key` is `ticker|action|reason|price` — a unique index refuses a duplicate while the ticket is
live, so re-running a session cannot double-publish. **Two new-entry tickets per brief, maximum**
(§5.1 step 6); extras wait in queue order and get named as context. Adds, exits and protective
moves are never throttled.

The ticket lifecycle is `proposed → approved → provisional → confirmed`. Zak saying "placed" moves
it to approved; a fill (his word, or the price trading through a resting order) makes it
provisional; Sunday's reconciliation confirms it against the settled record.

## Setup, once

The Routines need a Supabase MCP connector whose credential is the `yuna_session` role — read
everything, write only those four tables (migration `020_session_role.sql`). The owner credential
`DATABASE_URL` stays in GitHub Actions secrets and nowhere else.
