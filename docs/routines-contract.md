# The Routines contract — what Yuna's scheduled sessions must read

**2026-08-17.** The one part of the desk that does not live in this repository.

`push_channel = cowork`. Nothing in this repo messages Zak. `notify.py` proves the composed words
exist and goes red when they do not — the **delivery** is the scheduled Routines inside the Yuna
chat/cowork project, which fire on their own crons, read one row, and push it to his phone.

§6.3 changed everything upstream of them. **A Routine written against the old engine reads nothing
now.** This file is the new contract, in the form a Routine needs it.

---

## 0. Where the Routines read the law — `v_law` (§0.7)

The Routines run in the claude.ai project with no checkout of this repository. Since plan v1.2
(§0.7) they read the law the way they read the brief: from Supabase, every run.

```sql
select document, version, left(sha256, 12) as hash, published_at, body
  from v_law;
```

`v_law` holds the newest published text of two documents: `plan` (`docs/yuna_plan.md` on `main`)
and `routines-contract` (this file). The `law` job publishes them on every merge to `main` that
changes either. **There is no other copy.** The project files `yuna_plan.md` and
`runbooks/routines_contract.md` are retired, and a prompt never quotes the plan's text inline — it
reads it here.

Every brief's first line names the law it was read under — `# Yuna · 2026-10-08 · law v1.2 ·
3f9c1a2e4b7d` — and the payload carries the same (`v_session_payload.law`). A Routine whose law
differs from `v_law`'s version and hash is reading a copy, and says so rather than reporting on it.

Why: until 2026-10-07 both prompts read project copies of the plan and of this contract. The
project's plan had drifted. It carried v1.1, which the repository did not, and lacked the
repository's 2026-09-02, 09-13 and 09-14 amendments. So a Routine reading its law could contradict
the pipeline it reported on, and nothing could see it (migration 076).

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
  NAV and drawdown, the levered layer, account cash, the top 12, reconciliation, learnings. Send
  it as-is.
- **`summary`** is a one-liner for a push title: `gate ON · 6 order(s)`. The count is of ORDERS —
  proposed and approved tickets. A ticket the engine withdrew, Zak cancelled, or Zak already
  executed is not one; the body lists those apart, under "Not orders" (migration 068).
- **`detail->>'engine' = 'v1'`** matters. The retired `compose.py` also wrote `kind = 'nightly'` —
  its rows for sessions 2026-07-31 to 08-17 are still in `briefs` — and its source is still on
  disk, though no workflow runs it (learning 66). Without this filter a Routine can pick up the old
  engine's row.

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
destination — and §3.2's exclusion table, which §3.2 says "is surfaced in the payload and the
Saturday letter". The destination line is the household as the store holds it on the session:
every holding at its close, every account's cash anchor carried by the ledger, less the facility
(it used to print a `nav_snapshots` row nothing has written since 2026-08-15). It is composed by
the chain hanging off `ingest-universe`, Saturdays.

The letter does **not** carry a count of the week's sessions with the gate ON or of the week's
orders — neither §4.1 nor this contract asks for one. A Routine that wants either has no number in
the body to copy, and must not compute one in chat (§0.4).

---

## 3. Is the brief current?

**Do not use wall-clock age.** The market is shut most of the time this system is awake: Friday's
close is the newest session all weekend, so a brief composed Friday night is *correct* on Sunday and
a three-hour window would call it silence. That exact bug was live on 2026-08-17 and is what this
file exists to stop being repeated in the Routines.

**The session is the anchor — the session that ought to exist, not two tables agreeing with each
other.** Until 2026-10-07 this section compared `max(engine_sessions.session_date)` with
`max(briefs.session_date)` and called them equal "the desk has spoken". Both lag together: on a
night the chain has not run, both still name the previous session, and the test passes. That is how
the morning note served 2026-08-25's sheet on 08-27 and 08-26's on 08-28 as that morning's orders,
when the queue held the night's ingest past the note (learning 58). Nobody traded a wrong order —
the desk was still in shadow on 08-27, and a person caught 08-28 — but on any night both firings
are dropped it would re-serve a sheet Zak has already executed.

The expected session is the last trading day before the morning the Routine fires, in New York:
the close whose sheet executes at that morning's open. Three facts about it, one read:

```sql
with e as (
  select d as fire_date,
         d - case extract(isodow from d)::int
               when 1 then 3              -- Monday: the Friday before
               when 7 then 2              -- Sunday: the Friday before
               else 1 end                 -- any other day: the day before
           as expected_session
    from (select (now() at time zone 'America/New_York')::date as d) f
)
select e.fire_date, e.expected_session,
       (select max(session_date) from engine_sessions where mode = 'live') as newest_session,
       (select max(session_date) from briefs
         where kind = 'nightly' and detail->>'engine' = 'v1')            as briefed_session,
       exists (select 1 from runs
                where job = 'ingest-daily' and status = 'green' and not dry_run
                  and not (detail ? 'awaiting_vendor')
                  and started_at > (e.expected_session + time '16:00')
                                   at time zone 'America/New_York')       as ingest_landed
  from e;
```

`ingest_landed` asks for the night's own ingest: a green, non-dry `ingest-daily` that started
after the expected session's 16:00 New York close, which every slot follows (22:23 UTC on
weekdays). A first firing that found the vendor not yet published is green and landed nothing
(`awaiting_vendor`, learning 58), so it does not count; a retry that exits because the night is
already green does, because it found a firing that landed.

The first row that matches, top to bottom, is the reading:

| reading | when | what the Routine does |
|---|---|---|
| **scored, not composed** | `newest_session > briefed_session` | says the chain scored a session it never composed — out loud, not swallowed — and relays **no order** from the older sheet |
| **not in yet** | `briefed_session < expected_session` | says the sheet for `expected_session` is not in — the night's run never came (`ingest_landed` false) or has not finished (true) — and relays **no order** from the older sheet. The older brief may ride as the attachment, under its own date |
| **sheet current, night red** | not `ingest_landed` | the sheet is the right session's but the night's ingest is red or missing: FLAT, the order sheet exactly as the body prints it (its banner already holds the buys; exits stand), and §6 names the job |
| **current** | otherwise | delivers the brief |

Only *older* than expected reads not in yet, never merely different: a hand run in the evening,
after the chain, sees tonight's session, which is newer than the morning's expected one and just as
current.

**The calendar is weekends only, on purpose.** This system holds no exchange holiday calendar
(`db.next_session`, `ingest.tape_already_landed`), and a list typed in here would be a constant
with no source. So the morning after an NYSE holiday reads *not in yet* though nothing was missed:
the safe direction. The note says what it sees, never decides the market was shut, and the previous
session's sheet — the one that still stands — rides as the attachment under its own date. The store
cannot settle it alone: on Labor Day 2026 the vendor posted a 311-row tape dated 2026-09-07, the
ingest went green writing 132 of its bars, and the engine's newest session stayed 2026-09-04
because SPY did not print — the same shape a real session with a missing SPY bar would leave.

Replayed over the 37 weekday mornings from 2026-08-17 to 10-06 (from `runs`, which keeps the time
each compose finished): the old test passed all 37; this one passes 33, catches 08-27, 08-28 and
09-01 (session 08-31 never scored), and reads 09-08 — the morning after Labor Day — as not in yet.

**The Saturday letter** uses the same read with `kind = 'saturday'`: it is current when its session
is at or after the expected one (Friday's) and equals `newest_session`. Its chain hangs off the
census, whose red holds nothing (§5.6, 2026-09-13), so it needs no ingest of its own; when it is not
current, §6 says which job has not run.

---

## 4. The one-read law (§0.4)

An interactive session — as opposed to a Routine pushing a message — reads **`v_session_payload`**
once and then judges. It never recomputes a score, a rank or a gate in chat.

Its keys carry §4.2's nine items, and they are all new:

`gate` · `book` · `order_sheet` · `top12` · `exclusions` · `nav` · `facilities` · `tranches` ·
`check_report` · `pipeline` · `reconciliation` · `learnings` · `not_orders` · `law`

`law` (migration 076) is the plan's published version and hash; the law's text is in `v_law` (§0).

Three of them answer for tonight and nothing else (migration 068):

- **`order_sheet`** is the orders: tonight's tickets in `proposed` or `approved`. **`not_orders`**
  is the rest of tonight's tickets — withdrawn (`cancelled`, `expired`) or done (`executed`,
  `reconciled`). Never present a `not_orders` row as something to execute.
- **`check_report`** is the newest live, non-dry `check` that began after tonight's session row
  was written, naming that session — or a check that died before it could name one. **Null means
  no check has proved tonight's sheet, and buys are held.** A row with no `verdict` (a crash, a
  pre-heartbeat death, still `running`) holds them too; only a finished green or amber verdict
  releases them.
- **`nav`**'s drawdown is measured on engine NAV (positions + TFSA cash, USD), not on the
  positions alone. `nav.household` is the last `nav_snapshots` row — dated, provisional, and not
  refreshed by any scheduled job; the Saturday letter computes the household itself.

The old keys — `armed`, `queue`, `bench`, `unruled_at_the_line`, `ruled_at_the_line`,
`escalated_awaiting_zak`, `quarantined_watchlist` — are gone. They belonged to the fundamentals
engine. The ruling docket survives at `v_ruling_docket` for as long as `arming.py` does, but **no
session should read it to decide anything**: §3.3 leaves v1.0 with no bench, no hurdle and no
per-name ruling. *The rank is the entire opinion.*

---

## 4b. Writing the ledger — transactions, from a CSV or from Zak's word

Zak, 2026-08-18:

> There are a list of transactions… And those will always come in with a transaction ledger csv from
> Wealthsimple or another bank… **Those are law**… You keep them in the transaction ledger and they
> should all match. That's our actual history. I will upload those to the chat so the chat should be
> able to write them… And know how… And then additionally sometimes those transactions are lagged…
> By days… So I will just tell the chat other sales so it can process the books correctly… Those are
> true to me… But they might change or be tweaked by the transactions later. Maybe the pennies are
> different…. **But the engine should run assuming both.**

`transactions` is the history and `book` is its arithmetic. **A session writes the ledger and never
the book** — `yuna_book_from_ledger` moves the position, on a deferred trigger, at commit. There is
no fold to remember and no job to wait for.

Every row carries a `grade` saying where its authority comes from:

| grade | what it is | when |
| --- | --- | --- |
| `broker` | a row from the bank's export | **law** — never contradicted, only replaced by a later export of the same trade |
| `stated` | Zak's word, ahead of the export | **true, and provisional** — the engine runs on it until the export trues it |

and one of four verbs in `side`: `buy`, `sell`, `confirm` or `split`. **`confirm` is an opening
balance** — a position that predates the ledger, recorded with its cost basis so the sells that
follow it have something to net against. It moves no cash.

**`split` is written by the pipeline** (Zak's ruling of 2026-10-07, "Pipeline records splits": a
vendor-reported split on a held name enters the ledger, quantity only and no cash, before score
runs, and the brief shows it; ticker changes and takeovers still fail closed until he records
them). Each night `reconcile` writes one `split` row per position the split reaches — `qty`
is the ratio (2 for a 2:1, 0.1 for a 1:10), `price` 0, `trade_date` the vendor's ex-date — once it
has checked the split against the raw closes, and the row restates every earlier row of the
position: the shares move, the cost basis carries, no cash moves (migration 075). **Do not write
one yourself, and do not record a split as a `confirm`.** If Zak reports a post-split count before
the pipeline has recorded the split, say so and leave the ledger alone — the next reconcile records
it once the vendor has posted it (`select * from corporate_actions where ticker = '<name>' and kind
= 'split'`). The one exception is a split his broker shows that the pipeline will not record —
the vendor never posts it, or reconcile's amber says the tape contradicts the vendor's posting:
that is his word like any other statement, and on it you write the row exactly as reconcile would
(`side = 'split'`, `qty` the ratio, `price` 0, `trade_date` the first session his broker shows on
the new count, `grade = 'stated'`, `source` naming his words). One per position and date, ever, so
a later posting of the same date collides instead of doubling, and a vendor posting the tape
contradicts goes quiet once a split row after it restates the position. Quantity-only rows (price
0) on or after a split's date are read as his own record of that split: reconcile leaves rows that
are the split's arithmetic as they are, and goes red, by name, on rows that are not.

### Zak says he sold something

```sql
insert into transactions (ticker, account, side, qty, price, currency, trade_date,
                          confirmed, confirmed_at, grade, source)
values ('NUE.US', 'TFSA', 'sell', 32, 266.81, 'USD', '2026-08-17',
        true, now(), 'stated', 'stated in chat 2026-08-18');
```

That is the whole operation. The position moves on commit; tonight's sheet sees it.

### Zak uploads a bank export

Same insert per trade row, with `grade = 'broker'`, `source = 'csv <filename>'`, and the bank's own
identifier in `external_ref`. **When the export carries no per-row id — Wealthsimple's activities
export does not — synthesize one as `<filename>#<row>`** (e.g. `activitiesexport20260819.csv#2`).
`external_ref` is UNIQUE, and that is the protection: the same file uploaded twice collides on
insert instead of silently doubling every position it touches — the one failure mode the ledger and
the book cannot catch, because they agree on the doubled number. **Never work around the collision
by inventing a fresh ref for a row you have already imported.** Then supersede whatever he had already said about the same trade —
matched on **account, ticker, side and the day, never on quantity or price**, because the whole
reason the export supersedes his word is that those numbers differ slightly:

```sql
update transactions s
   set superseded_by = b.id
  from transactions b
 where b.external_ref = 'ws-nue-1'                          -- the row just imported
   and s.grade = 'stated' and s.superseded_by is null
   and s.account = b.account and s.ticker = b.ticker
   and s.side = b.side and s.trade_date = b.trade_date;
```

Superseded rows stay (§0.6) and stop counting — the history then shows both what Zak believed on the
day and what the bank confirmed after.

**Read the export's non-trade rows and skip them.** Dividends, interest, contributions and journal
entries sit beside the trades, and every one folded in as a trade moves a position that never moved.
`src/ledger.py` does exactly this from a shell (`import` · `state` · `confirm` · `check`) and is the
reference for the rules; a session does it in SQL because a session has no shell.

### Three things that will stop you, and what each means

- **`ledger drives TFSA SPMO.US to -810 shares — the history for this name is incomplete`** — a sell
  of a position bought before this ledger existed. Record the opening balance first, as a `confirm`
  row with the quantity and cost the book already holds, then re-record the sell. **Unless the sell
  is larger than everything ever bought** — the share count after a split, or a mistyped quantity.
  After a split the vendor has posted (`select * from corporate_actions where ticker = '<name>' and
  kind = 'split'`), the sell is right and early: write it on its exit ticket (`fill_qty`,
  `fill_price`, `fill_date`) instead, and tonight's reconcile records the split first and lands the
  sale after it. Otherwise the sell is the wrong row, and a `confirm` row would invent shares and
  move the cost basis: check it against the broker and ask Zak.
- **`NOPE.US is not in universe`** — check the symbol in EODHD form (`NUE.US`, `CNQ.TO`).
- **anything about `guard_book` or `book_one_open_row_per_position`** — you tried to write `book`.
  Write `transactions` instead: a second purchase of a position is a second ledger row, never a
  second book row (migration 069).

### The NAV is derived — the chat no longer relays it

Since 2026-08-19 the pipeline derives engine NAV itself: TFSA marked equity (park included) + TFSA
cash, CAD at the session's USDCAD. A session never computes it (§0.4) and never needs to pass it.
`config.engine_nav` still works and OUTRANKS the derivation — writing it is a ruling, so only do it
when Zak states a number in so many words, and prefer telling him the derived figure already on the
sheet. Keeping the cash anchors current (below) is what keeps the derived number honest — and no
clause says who keeps them current or how often: v1.0 defines neither engine NAV nor an anchor duty,
so an anchor moves only when Zak states his cash. That gap is a §0.3 amendment waiting on Zak, not
something a session fills by habit.

### Zak says how much cash he has

> *"…or the current dollar availability etc."*

That is not a trade and does not belong in `transactions`. **Balances are truth, prices are the
extrapolation** — the retired plan's §2.0, which v1.0 does not carry; the derived NAV above stands
on it by Zak's 2026-08-19 ruling. `balances` is an append ledger read latest-wins per account, and
it is session-writable — a new row is a new reading, never an edit of the old one:

```sql
insert into balances (account, as_of, cash_cad, cash_usd, source)
values ('TFSA', current_date, 47.33, 16.47, 'zak in chat 2026-08-18');
```

The facility is the same table with different columns — `drawn` and `credit_limit` instead of cash,
and §2.3 caps the draw at half the limit:

```sql
insert into balances (account, as_of, drawn, credit_limit, source)
values ('LOC', current_date, 12000, 75000, 'zak in chat 2026-08-18');
```

**Write both currencies when you have both.** `cash_cad` and `cash_usd` are separate columns because
a USD buy takes USD out and leaves the CAD side alone; collapsing them loses the distinction that
decides whether an account can fund a trade. And do not carry a figure forward: if Zak gives one
currency, write that one and leave the other null rather than repeating yesterday's number as if it
were today's reading.

`cash_by_account` carries the newest anchor forward by the ledger, so a fill after the reading is
already accounted for — do not subtract it by hand. **Write the reading when Zak gives it**: the
row's `recorded_at` is the only clock the store has for it. A reading written before the open is
known to precede that day's fills, and they count. A reading written after the open is taken to
include every fill dated that day — right for a screenshot taken after the trades, wrong for a
figure Zak gave before he traded — and the derived NAV's breakdown names those fills
(`cash_same_day_assumed_inside`). So if you are writing a pre-open figure after the open, date it to
the previous session instead: `as_of` is the last session whose fills the reading includes.

### A statement the export passed over

Zak, 2026-08-18:

> if a stated transaction in an account pre-dates broker transactions… that's a bad sign and likely
> the stated transaction should be matched to one of the broker transactions or removed… because I
> had stated data that didn't actually come to pass.

Supersession covers the export **confirming** what he said. This is the other case: the export
arrives, covers the day, and does not mention the trade at all. That is not neutral — the thing he
believed happened did not, and the stated row is still counting.

```sql
select * from v_stale_statements;
```

Each row is a stated buy or sell the broker has reported *past* without confirming. It is the worst
shape the ghost book takes, because the ledger and the book **agree** — a stated sell that never
executed empties a slot that is still full. Two resolutions, both Zak's:

- **match it** — supersede it with the broker row it was reaching for (the update in the section
  above), or
- **void it** — `update transactions set superseded_by = id where id = <n>` marks it self-superseded
  so it stops counting while the row survives (§0.6).

**Never guess which.** Only Zak knows whether a statement was a mis-remembered fill, a trade that
was cancelled, or one the export simply has not reached yet.

### An opening balance no export explains

```sql
select * from v_unexplained_opening_balances;
```

A `confirm` row says a position **exists** and what it cost — not that a trade happened that day —
so an export covering the date without mentioning the name does not refute it. It just does not
explain it, and the cost basis stays an estimate.

`broker_has_this_name = true` is the one to act on: an export now covers the name, so the opening
balance **and** the real purchases are probably both counting and the position has doubled. Retire
one. Today that is SPMO in the TFSA and the RRSP.

### Does it all match?

```sql
select * from v_ledger_vs_book;
```

Empty is the goal. A row with `predates_the_ledger = false` is a real break and something wrote one
side without the other — a row left open after the ledger sold the name out included, and a
position held in more than one open book row (`open_rows`), which the ledger refuses to move. A row
with `predates_the_ledger = true` is a holding with no ledger rows behind it at all — not a defect,
and it heals itself when the export lands.

---

## 5. What a Routine must never do

- **Never place, modify or cancel an order** (§0.2). The brief is a proposal; Zak executes.
- **Never write a ticket to `approved`.** That is Zak's word, in chat, and `reconcile` looks for a
  receipt against it afterwards.
- **Never write `book` directly.** Write the ledger (§4b) and let the position follow. A book poked
  by hand is a book that agrees with nothing. `guard_book` refuses it for every role but the owner
  — and the chat connector logs in as the owner, which is how a second VXC.TO row reached the book
  on 2026-09-28 and the brief showed 418 shares against 279 held for nine days. Since migration 069
  a second open row for a position is refused for every role.
- **Never invent a price, a quantity or a date to complete a ledger row.** If the export is
  ambiguous, say which row and which field — a `stated` row with a number Zak did not give is worse
  than no row, because it looks exactly like one he did.
- **Never recompute a rank, score or gate in chat** (§0.4). If a number is not in the payload, the
  answer is that the pipeline has not produced it — not that the session should derive it.
- **Never suppress the brief because the check is red.** §4.4 holds the *buys*; §5.4 makes exits
  unblockable. The brief already carries `**buys held; exits stand**` at the top when that applies,
  and a red night is exactly the night Zak needs the message.
- **Never relay an older session's orders as this morning's.** When §3 reads anything but current,
  no order from the older sheet goes into the note or the push line (§0.4: a stale pipeline means
  no new tickets). The older brief may still ride as the attachment, named for its own session —
  which is also how a sheet that still stands, the morning after a market holiday, reaches Zak.

---

## 6. Health, in one line

The chain behind the session being delivered — the last trading session's, §3's expected one —
not a fixed window:

```sql
with e as (
  select d - case extract(isodow from d)::int when 1 then 3 when 7 then 2 else 1 end
           as expected_session
    from (select (now() at time zone 'America/New_York')::date as d) f
)
select r.job, r.status, r.finished_at, r.detail->'amber' as amber, r.detail->'red' as red
  from e, lateral (select distinct on (job) * from runs
                    where not dry_run
                      and started_at > (e.expected_session + time '16:00')
                                       at time zone 'America/New_York'
                    order by job, id desc) r
 order by r.job;
```

The newest non-dry run of each job since the expected session's close. Seven jobs on an ordinary
weeknight: `ingest-daily · reconcile · score · shadow · check · compose · notify`. On a Monday it is
Friday night's chain and Saturday's re-run of it, plus `ingest-universe` and `backup` — the whole
weekend, which is exactly what the Monday note has to vouch for.

Until 2026-10-07 this read `started_at > now() - interval '36 hours'`. Thirty-six hours is
`db.freshness`'s constant of record (§5.6, 2026-09-13) and it is right where it lives, at compose
time, inside the night it describes. Read at a fixed morning hour it is wrong one weekday in five:
on a Monday the window opens on Sunday evening, when nothing runs, so it returned no rows at all on
09-07, 09-21, 09-28 and 10-05. On 09-07 the weekend it hid held a red backup, a red census and a red
check (learnings 63, 64 and 67). It also read DRY_RUN rows, which `db.freshness` stopped doing on
2026-09-13 (learning 67).

- `notify` **green** means the words exist and are deliverable.
- `notify` **red** means the doorbell is about to ring on an empty doorstep — say so.
- `score` **amber** with `frozen: true` in its detail is not a fault; it is §5.5, and the brief
  leads with Zak's own words.
- `ingest-universe` **red** is a warning on the freshness line and holds nothing (§5.6,
  2026-09-13).
- **No row** for a nightly job means it has not run since that close. On a weekday morning with no
  `ingest-daily` row, §3 already reads *not in yet*.

---

## 7. §6.4, while the shadow runs

```sql
select * from v_shadow_progress;
```

`sessions` of 10 · `divergences` · `unruled` · `passes`. §6.5 gates the seed on this reaching ten
with every divergence named **and ruled** — a later matching session does not clear an earlier
disagreement.
