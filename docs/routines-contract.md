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

and one of three verbs in `side`: `buy`, `sell`, or `confirm`. **`confirm` is an opening balance** —
a position that predates the ledger, recorded with its cost basis so the sells that follow it have
something to net against. It moves no cash.

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
identifier in `external_ref`. Then supersede whatever he had already said about the same trade —
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
  row with the quantity and cost the book already holds, then re-record the sell.
- **`NOPE.US is not in universe`** — check the symbol in EODHD form (`NUE.US`, `CNQ.TO`).
- **anything about `guard_book`** — you tried to write `book`. Write `transactions` instead.

### Zak says how much cash he has

> *"…or the current dollar availability etc."*

That is not a trade and does not belong in `transactions`. §2.0: **balances are truth, prices are the
extrapolation.** `balances` is an append ledger read latest-wins per account, and it is
session-writable — a new row is a new reading, never an edit of the old one:

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

`cash_by_account` carries the newest anchor forward by the ledger, so a fill recorded after the
reading is already accounted for — do not subtract it by hand.

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
side without the other. A row with `predates_the_ledger = true` is a holding older than its own
history — true of the book today, not a defect, and it heals itself when the export lands. Today
that is SPMO in the TFSA and the RRSP, bought with the §6.1 proceeds.

---

## 5. What a Routine must never do

- **Never place, modify or cancel an order** (§0.2). The brief is a proposal; Zak executes.
- **Never write a ticket to `approved`.** That is Zak's word, in chat, and `reconcile` looks for a
  receipt against it afterwards.
- **Never write `book` directly.** Write the ledger (§4b) and let the position follow. A book poked
  by hand is a book that agrees with nothing, and `guard_book` refuses it.
- **Never invent a price, a quantity or a date to complete a ledger row.** If the export is
  ambiguous, say which row and which field — a `stated` row with a number Zak did not give is worse
  than no row, because it looks exactly like one he did.
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
