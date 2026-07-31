# Sessions — the judgment layer

Five sessions, specified in plan §4.4 and §5. Each runbook here is the session's code: same
review, same care as a formula. A session that did not write its `briefs` row did not happen.

| Session | When (PT) | How it starts | Runbook |
|---|---|---|---|
| Evening stop sheet | ~20:30 Mon–Fri | scheduled Routine | `R2_stopsheet.md` |
| Pre-open brief | ~06:00 Mon–Fri | scheduled Routine | `R1_preopen.md` |
| Saturday deep-dive | ~08:00 Sat | scheduled Routine | `R3_deepdive.md` |
| Sunday reconciliation | Sun morning | Zak opens it | `R4_reconcile.md` |
| Monthly approval | 1st weekend | Zak opens it | `R5_approval.md` |

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
  from armed order by urgency desc, kind, score desc nulls last;
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
