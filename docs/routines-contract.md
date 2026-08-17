# The Routines contract — what Yuna's scheduled sessions must read

**2026-08-17.** The one part of the desk that does not live in this repository.

`push_channel = cowork`. Nothing in this repo messages Zak. `notify.py` proves the composed words
exist and goes red when they do not — the **delivery** is the scheduled Routines inside the Yuna
chat/cowork project, which fire on their own crons, read one row, and push it to his phone.

§6.3 changed everything upstream of them. **A Routine written against the old engine reads nothing
now.** This file is the new contract, in the form a Routine needs it.

---

## 1. The nightly brief — the whole message, already written

The brief is composed as prose by `brief.py`. A Routine does not need to assemble anything; it
reads one row and sends the body.

```sql
select session_date, summary, body, at
  from briefs
 where kind = 'nightly'
   and detail->>'engine' = 'v1'
 order by session_date desc, at desc
 limit 1;
```

- **`body`** is the complete brief — freshness banner, gate and latch, the order sheet, the book,
  NAV and drawdown, the levered layer, the top 12, reconciliation, learnings. Send it as-is.
- **`summary`** is a one-liner for a push title: `gate ON · 6 order(s)`.
- **`detail->>'engine' = 'v1'`** matters. The retired `compose.py` also writes `kind = 'nightly'`,
  and it is still dispatchable. Without this filter a Routine can pick up the old engine's row.

**What changed from the old contract**

| Old | New |
|---|---|
| `kind in ('preopen', 'stopsheet', 'deepdive')` | `kind in ('nightly', 'saturday')` |
| a fresh row appended per re-composition | **one row per session, upserted** — read the row, not the newest insert |
| freshness by `at > now() - 3 hours` | freshness by `session_date` (see §3) |

---

## 2. The Saturday letter

Same shape, `kind = 'saturday'`. It carries §4.1's six weekly items — gate flips on record, rank
stability across the week, drawdown, live-vs-shadow divergences, learnings, and NAV against §1's
destination. It is composed by the chain hanging off `ingest-universe`, Saturdays.

---

## 3. Is the brief current?

**Do not use wall-clock age.** The market is shut most of the time this system is awake: Friday's
close is the newest session all weekend, so a brief composed Friday night is *correct* on Sunday and
a three-hour window would call it silence. That exact bug was live on 2026-08-17 and is what this
file exists to stop being repeated in the Routines.

The session is the anchor:

```sql
select (select max(session_date) from engine_sessions where mode = 'live') as newest_session,
       (select max(session_date) from briefs
         where kind = 'nightly' and detail->>'engine' = 'v1') as briefed_session;
```

Equal → the desk has spoken for the current session. Different → the chain scored a session it
never composed, which is worth saying out loud rather than swallowing.

---

## 4. The one-read law (§0.4)

An interactive session — as opposed to a Routine pushing a message — reads **`v_session_payload`**
once and then judges. It never recomputes a score, a rank or a gate in chat.

Its nine keys are §4.2's list, and they are all new:

`gate` · `book` · `order_sheet` · `top12` · `exclusions` · `nav` · `facilities` · `tranches` ·
`check_report` · `pipeline` · `reconciliation` · `learnings`

The old keys — `armed`, `queue`, `bench`, `unruled_at_the_line`, `ruled_at_the_line`,
`escalated_awaiting_zak`, `quarantined_watchlist` — are gone. They belonged to the fundamentals
engine. The ruling docket survives at `v_ruling_docket` for as long as `arming.py` does, but **no
session should read it to decide anything**: §3.3 leaves v1.0 with no bench, no hurdle and no
per-name ruling. *The rank is the entire opinion.*

---

## 5. What a Routine must never do

- **Never place, modify or cancel an order** (§0.2). The brief is a proposal; Zak executes.
- **Never write a ticket to `approved`.** That is Zak's word, in chat, and `reconcile` looks for a
  receipt against it afterwards.
- **Never recompute a rank, score or gate in chat** (§0.4). If a number is not in the payload, the
  answer is that the pipeline has not produced it — not that the session should derive it.
- **Never suppress the brief because the check is red.** §4.4 holds the *buys*; §5.4 makes exits
  unblockable. The brief already carries `**buys held; exits stand**` at the top when that applies,
  and a red night is exactly the night Zak needs the message.

---

## 6. Health, in one line

```sql
select job, status, finished_at, detail->'amber', detail->'red'
  from (select distinct on (job) * from runs
         where started_at > now() - interval '36 hours'
         order by job, id desc) r
 order by job;
```

Six jobs on an ordinary night: `reconcile · score · shadow · check · compose · notify`.

- `notify` **green** means the words exist and are deliverable.
- `notify` **red** means the doorbell is about to ring on an empty doorstep — say so.
- `score` **amber** with `frozen: true` in its detail is not a fault; it is §5.5, and the brief
  leads with Zak's own words.

---

## 7. §6.4, while the shadow runs

```sql
select * from v_shadow_progress;
```

`sessions` of 10 · `divergences` · `unruled` · `passes`. §6.5 gates the seed on this reaching ten
with every divergence named **and ruled** — a later matching session does not clear an earlier
disagreement.
