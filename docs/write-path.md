# The session write path

*Migration: `migrations/018_session_api.sql`. Written 2026-07-31, against `docs/yuna_plan.md`
as of the 16:37 UTC stamp.*

This document is for someone who was not in the room. It explains what the write path is, what
it is defending against, what a leaked session token can and cannot do, and how to switch the
whole thing off in one statement.

---

## 1. The problem

Yuna's scheduled sessions (§4.4 — R1 through R5) have to record things: the brief they just
wrote, a fill Zak reported in chat, a cash balance he read off Wealthsimple, a ruling he made, a
ticket they want him to look at. Every one of those is a database write.

Until now the database had exactly one writer: the jobs, holding `DATABASE_URL`. §4.8 calls that
credential what it is — *"the connection string is god-mode and exists nowhere else."* It can
drop tables, rewrite the book, and read every row. Handing it to a session that reads chat
messages, follows links, and processes vendor JSON is not a risk anyone should take on purpose.

The obvious middle path — a second database role with `INSERT` on `briefs`, `tickets`,
`observations` and `config` — is worse than it looks. `INSERT` on `tickets` is `INSERT` of
*any* ticket in *any* state, including `confirmed`. `INSERT` on `config` is a wider stop. Table
privileges describe *which table*, never *which row* and never *which shape*, so every rule that
matters ends up enforced by convention — which is to say, not enforced.

## 2. The shape of the answer

Sessions get **no table access at all**. They get **verbs**.

- A schema **`api`** holds eight `SECURITY DEFINER` functions. That is the entire surface.
- A role **`yuna_session`** holds **zero privileges on every table in the database**. Not
  `SELECT`, not `INSERT`, nothing. It can `EXECUTE` the eight verbs and that is the complete
  list of things it can do. Reaching a table is not *forbidden*, it is *impossible* — there is
  no grant to bypass, no policy to find a hole in.
- A schema **`yuna_priv`** holds the shared machinery. It is granted to nobody; the verbs reach
  it only because a definer function runs as its owner.
- Transport is **PostgREST RPC**. `api` is the only exposed schema. `public` is deliberately not
  exposed over HTTP, so there is no `GET /tickets` to find.
- PostgREST logs in as `authenticator` and assumes `yuna_session` from a signed JWT
  (`GRANT yuna_session TO authenticator`). The session is handed a **pre-minted, role-scoped,
  expiring token**. It never sees the JWT signing secret, which stays with Zak, because the
  secret can mint `service_role` and `service_role` is god-mode again.

Every verb validates its own arguments, is idempotent, stamps provenance, and can be called in
dry-run mode.

## 3. Why this is safe — the actual reason

The security of this surface does not rest on the SQL being clever. It rests on one line of the
plan:

> §4.5 — **Zak places every order.** *(and §4.0: "Yuna judges · Zak acts")*

**Yuna never executes.** There is no broker connection anywhere in this system. Every verb below
either (a) proposes something Zak reads and decides on, or (b) records something Zak said.
Nothing in `api` moves a share or a dollar, and nothing in `api` can cause anything else to.

That is the whole argument. Compare the worst case honestly:

| | If the write path is compromised | If `DATABASE_URL` is compromised |
|---|---|---|
| Money moved | none — Yuna cannot trade | none — the jobs cannot trade either |
| Damage | false rows Zak reads; noise; a corrupted NAV input | the entire database, read and destroyed |
| Detection | every row is stamped with the session and key that wrote it | almost none |
| Undo | one statement (§7) | restore from the monthly backup |

The write path can *lie to Zak*. It cannot *act*. Those are very different sizes of problem, and
the second one is the one that would end the project.

## 4. Threat model — what a leaked session token can and cannot do

Assume the worst realistic case: a token leaks (prompt injection in a news article a session
read, a log that captured a header, a compromised session transcript) and the attacker can call
every verb until the token expires.

### It cannot

- **Read anything.** No verb returns a row. There is no `SELECT` privilege and no exposed table.
  The book, the balances, the theses, the cost basis — all unreachable. This is worth stating
  loudly: the write path is genuinely **write-only**.
- **Reach a table directly.** `insert into tickets …` returns *permission denied for table
  tickets*. So does `select`. So does reaching `yuna_priv` (*permission denied for schema*).
- **Trade.** Nothing here reaches a broker. Nothing anywhere in Yuna does.
- **Create a ticket in any state but `proposed`.** `session_propose_ticket` has no `state`
  parameter; the literal `'proposed'` is in the INSERT.
- **Skip the ticket state machine.** A fill cannot be forged onto an unapproved ticket, and a
  `confirmed` ticket — one already matched against the broker's settled record — is frozen.
- **Widen a stop, raise a size cap, or move any plan number.** `session_set_config` refuses
  every key that exists today, every key matching a risk-shaped pattern, and anything a job or
  migration has ever written (§6).
- **Make a fat-fingered balance become NAV.** Order-of-magnitude statements go to quarantine, not
  to `balances` (§5).
- **Duplicate a fill or a ticket by retrying.** Idempotency keys are enforced in the database.
- **Escalate.** `yuna_session` is `NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOBYPASSRLS`. Every definer function pins `search_path` (see §9), so none of them can be
  tricked into resolving `balances` to an attacker's table. No verb builds SQL from a string.
- **Hold a connection open.** `statement_timeout` and `idle_in_transaction_session_timeout` are
  10s on the role.
- **Persist past expiry.** The token expires and cannot be reminted without the signing secret.

### It can

- **Write false records Zak reads.** A fabricated brief, a fabricated observation, a plausible
  ticket for a name he doesn't want, a fabricated ruling. This is the real residual risk, and it
  is a *social* attack: it works only if Zak acts on it without checking. Mitigations: every row
  carries `written_by='session'` and a `session_call_id`; nothing is auto-executed; §5.6's
  freshness discipline means a brief that contradicts the pipeline is visible.
- **Forge a "ruling".** `session_rule` writes a row that says Zak decided something. **A ruling
  row has no mechanical effect** — that is a deliberate design property, not an oversight.
  Nothing in this codebase reads a ruling and changes behaviour; the numbers a ruling would move
  live in `config`, and `config` is protected. The row is attributed to the *session* that wrote
  it, never to Zak. Treat a ruling row as "a session claims Zak said this", because that is
  exactly what it is.
- **Push a provisional balance into NAV.** An accepted (non-quarantined) balance becomes the
  newest row, and `db.nav_cad` reads the newest row per account. Within the quarantine
  thresholds this can move NAV by up to ~10K per statement. Sunday reconciliation (§2.0, §5.4)
  is the control that catches it.
- **Flood the tables with noise.** There is no rate limit on the verb count. Nothing is
  destroyed — the ledgers are append-only — but a brief could be buried. Worth adding a
  per-session daily call cap later; not built.
- **Move one of its own tickets to `cancelled` or `expired`.** Annoying, not dangerous — the
  order lives at the broker, not in this table.

### What it is not defended against

An attacker who has **`DATABASE_URL`**, or the **JWT signing secret**, or Zak's Supabase login.
Those are outside this design. `DATABASE_URL` lives only in GitHub Actions secrets (§4.8); the
signing secret lives only with Zak.

## 5. The verbs

All eight take `idempotency_key` first and `dry_run` last, all return `jsonb`, all are
`SECURITY DEFINER` with `SET search_path = pg_catalog, public, pg_temp`.

```
api.session_write_brief(idempotency_key, kind, summary,
                        detail := null, body := null, freshness := null,
                        session_date := null, dry_run := false)

api.session_propose_ticket(idempotency_key, ticker, account, action,
                        reason := null, sleeve := null, order_type := null,
                        trigger_price := null, limit_price := null, qty := null,
                        stop := null, stop_limit_price := null, brief_id := null,
                        note := null, dry_run := false)

api.session_set_ticket_state(idempotency_key, ticket_id, new_state,
                        note := null, dry_run := false)

api.session_record_balance(idempotency_key, account, currency, amount,
                        as_of := null, note := null, dry_run := false)

api.session_record_cash(idempotency_key, account, currency, amount, kind,
                        as_of := null, note := null, dry_run := false)

api.session_record_observation(idempotency_key, topic, body,
                        detail := null, kind := 'note', ticker := null,
                        score := null, price := null, dry_run := false)

api.session_rule(idempotency_key, topic, ruling, note := null, dry_run := false)

api.session_set_config(idempotency_key, key, value, note := null, dry_run := false)
```

The envelope every call returns:

```json
{"ok": true, "verb": "session_record_cash", "idempotency_key": "R4-2026-08-02-tfsa-cad",
 "dry_run": false, "replayed": false, "action": "written",
 "table": "balances", "id": 41, "at": "...", "...": "verb-specific fields"}
```

`action` is one of `written` · `quarantined` · `observed` · `would_write` · `would_quarantine`.

**Recording a fill** is `session_set_ticket_state(key, ticket, 'provisional', 'filled 176.20
x40')` — §4.5's *"chat or flip → tickets row provisional"*. There is no separate fill verb,
because a fill that corresponds to no ticket is not something this system has.

### Idempotency

Every write claims a row in `session_calls`, unique on `(verb, idempotency_key)`.

- **Same key, same arguments** → the stored envelope is replayed verbatim, with one field
  changed: `replayed` flips to `true`. Nothing is written a second time. (The one-field
  difference is deliberate — a retrying session should be able to tell it retried, and the
  material answer, `table` and `id`, is byte-identical.)
- **Same key, different arguments** → refused (`PT409`). Replaying a stored result for a request
  nobody made is a silent lie; writing again defeats the ledger.
- **Keys are scoped per verb**, so `R4-2026-08-02-tfsa` can be used once by each verb.
- **A dry run claims nothing.** It writes no ledger row at all, so it cannot burn the key the
  real call needs.

### Provenance

`tickets`, `briefs`, `observations`, `balances` and `config` each gained two columns:

- `written_by` — `'job'` (the default, and the truth for every row written before 018) or
  `'session'`.
- `session_call_id` → `session_calls`, which holds the verb, the session id, the idempotency
  key, the timestamp, the arguments and the result.

So any row answers "job or session?" on sight, and "which session, which verb, when, under what
key?" with one join. `v_session_writes` and `v_quarantine` are the browsing views.

The session id comes from the JWT's `session` / `sid` / `sub` claim. A request with no claims
still writes, recorded as `session_id = 'unknown'` with `identified = false` — refusing would be
a rule the plan does not state, and a write attributed to *something* beats a write lost.
`identified = false` is worth alarming on.

### Dry run

Every verb takes `dry_run => true`: full validation (a bad argument still raises exactly as it
would), the outlier check still runs, the arithmetic is still computed, and the envelope comes
back with `action = would_write` or `would_quarantine`. **Nothing is written — verified against
`session_calls`, `balances`, `observations`, `tickets` and `balance_quarantine`.**

## 6. The decisions this design had to make

The plan does not state these. They are chosen, defensible, and **Zak's to confirm** — they are
open questions Q4 and Q5 in `docs/open-questions.md`, and the migration records both as
observations so they stay visible.

### 6.1 Ticket state machine

States are the six already in `tickets.state` (005), and no others: `proposed` · `approved` ·
`provisional` · `confirmed` · `cancelled` · `expired`.

| From | To | Why |
|---|---|---|
| proposed | approved | Zak approved it; it goes to the broker (§4.5) |
| proposed | cancelled | he declined it, or the setup died first |
| proposed | expired | the trigger aged out — base broke, gate flipped |
| approved | provisional | fill reported in chat or by flipping the ticket (§4.5) |
| approved | cancelled | order pulled — blackout cancels live entries and adds (§3.3) |
| approved | expired | GTC lapsed unfilled (90 days at Wealthsimple, §4.6) |
| provisional | confirmed | matched against the broker's settled record on Sunday (§5.4) |
| provisional | cancelled | the record contradicts the reported fill — **note required** (§5.4) |

`confirmed`, `cancelled` and `expired` are **terminal**. Self-transitions are refused. Everything
else is refused with the legal next states named in the error.

**The one likely to bite:** `proposed → provisional` is *not* legal. A session recording a fill
on a ticket Zak never flipped to `approved` must make two calls. That is strict, and it follows
§4.3's chain literally. If Zak in practice just executes without flipping, this is the rule to
relax first — and it is a one-line change to `yuna_priv.ticket_transitions()`.

`provisional → cancelled` is the other judgement call. It exists because a fill Zak reported that
the broker record contradicts must be undoable, or the ledger lies; §5.4 says discrepancies are
*"flagged in the summary, never silently absorbed"*, so the note is mandatory.

### 6.2 Protected config

§4.3: *"The plan is law; config is its runtime copy. Any config change that moves a plan-stated
number requires the announced plan edit first — a config row never quietly overrules this
document."* Five gates, any one of which refuses:

1. **The exact list of every key seeded to date** (all 33 from 002, 005, 009, 016):
   `stop_limit_buffer` · `entry_limit_over_pivot` · `gap_threshold` · `blackout_trading_days` ·
   `bars_retention_years` · `small_large_boundary_usd` · `queue_cap` ·
   `new_entry_tickets_per_brief` · `api_alarm_fraction` · `position_floor_nav` ·
   `mcn_risk_budget` · `mcn_risk_budget_validation` · `base_currency` · `hurdle_min_return` ·
   `hurdle_growth_cap` · `hurdle_fair_multiple_cap` · `hurdle_fair_multiple_cap_short` ·
   `c1_max_net_debt_ebitda` · `c1_max_net_issuance` · `ccn_size_band` · `ccn_flat_size` ·
   `sleeve_ceiling` · `single_name_entry_cap` · `theme_entry_cap` · `max_names_per_group` ·
   `score_thresholds` · `momentum_max_stop` · `momentum_trail` · `bench_size` ·
   `bench_cohort_take` · `c2_memo_top_n` · `engine_agreement_tolerance` · `levered_etf`
2. **A substring deny-list** so a key invented next month is refused by default: `size` `cap`
   `stop` `trail` `risk` `budget` `hurdle` `sleeve` `weight` `threshold` `floor` `ceiling`
   `limit` `margin` `leverage` `utilization` `facility` `nav` `currency` `fx` `ccn` `mcn`
   `score` `theme` `group` `blackout` `pivot` `volume` `tranche` `quarantine` `position` `entry`
   `exit` `drawdown` `allocation` `percent` `pct` `ratio` `rate` `buffer` `gate` `drawn`
   `credit` `cash` `order` `qty` `share` `tier` `band` `bar` `target` `idempot`
3. **Anything Zak set** (`set_by = 'zak'`).
4. **Anything whose note cites a plan section** (`§`) — §4.3's runtime copy of law.
5. **Anything a job or a migration has ever written** (`written_by = 'job'`). This is the gate
   that matters most, because it does not depend on anyone naming a key well.

What is left is a key a session invented and maintains itself. That is a very small door, and
it is meant to be. The deny-list errs heavily toward refusing: a wrongly-refused key costs one
migration, a wrongly-allowed key costs real money.

### 6.3 Quarantine thresholds

§4.1 quarantines a *price* until two sources agree. A balance has no second source until Sunday,
and the failure being defended against is specific: **a typo in a chat message becoming NAV**.

- **Materiality floor — 10,000** in the stated currency, no FX conversion. NAV is ~200K CAD, so
  a change under 10K cannot meaningfully move the scorecard, and cash sloshes by that much in
  ordinary trading. Below the floor, nothing is quarantined.
- **Anchor ratio — ≥ 10× or ≤ 0.1×** the last known value for that account and currency. This is
  the extra-zero signature exactly. `7,933 → 79,331` trips it; `78,085 → 178,085` (a real 100K
  deposit) does not, and should not. A stated balance below zero always quarantines. No prior
  value means no baseline: the first statement is accepted and labelled, because inventing a
  baseline is worse.
- **Movement — ≥ 50,000** in the stated currency, or **≥ 10×** the last known balance (above the
  floor). 50K is a quarter of NAV; a transfer that size is rare enough that one confirmation is
  cheap, and it catches the extra zero on the plan's own worked example: *"I deposited $5,000
  CAD"* mistyped as 50,000.

**Honest residue, named rather than hidden:** a typo *inside* one order of magnitude
(`78,085 → 87,085`) is not caught, and nothing available to a single SQL function would catch it.
Sunday's reconciliation against the broker's settled record is the real control (§2.0, §5.4);
quarantine only stops the damage that would be done before Sunday arrives.

A quarantined statement writes **no balance row**. It writes the quarantine row and an
observation (`kind='breach'`) so it lands in the next brief — §4.1: *"Quarantined rows are
flagged in the next brief, never silently used."* **No verb releases a quarantine.** Resolution
is a human with `DATABASE_URL` updating `balance_quarantine.resolution`. That is the point: the
whole mechanism exists to force a second pair of eyes, so the eyes cannot be the same session.

The thresholds are **constants in the function, not config rows**, on purpose: a session that
could widen its own quarantine could defeat it. Changing them takes a migration.

### 6.4 Provisional balances (§2.0)

§2.0: *"Balances are truth, prices are the extrapolation"*, and *"Weekday NAV extrapolates from
the last confirmed balances using price moves — provisional, labeled, trued up Sunday."* Two
verbs, because Zak says two different things:

- **`session_record_balance`** — the Sunday reconciliation anchor (§5.4). *"TFSA CAD cash is
  8,100.55."* Written with `provisional = false`. For a facility the amount is the **drawn**
  balance, CAD always (016, Zak 2026-07-31); credit limits are capacity, not debt (§2.0), and
  are not restated.
- **`session_record_cash`** — the mid-week conversational path, always `provisional = true`, and
  it distinguishes two shapes:
  - `kind = 'anchor'` — *"TFSA cash is now X"* → the balance **is** X.
  - `kind = 'movement'` — *"I deposited $5,000 CAD"* → the balance is **last anchor + movements
    since**, this one included. The anchor and the running sum are stored (`stated_as`,
    `movement_amount`, `movement_currency`) so the arithmetic is auditable rather than a number
    that appeared.

  Both write **two** rows: an observation of what Zak actually said (the words are the primary
  record — the derived number can always be recomputed, and Sunday will), and the provisional
  balance row.

**A movement with no anchor behind it writes the observation and no balance row.** With no last
anchor there is no honest number, and zero is not a safe guess; `db.nav_cad` takes the newest row
per account outright, so a row saying "cash unknown" would blank the account's cash in NAV. The
envelope returns `action: "observed"`, `needs_anchor: true`.

**Carry-forward is load-bearing.** `db.nav_cad` reads `distinct on (account) … order by as_of
desc, id desc` — the newest row wins outright. A row stating only CAD cash, written naively,
would leave `cash_usd` null and NAV would silently lose the 78,085 USD in the TFSA. Every
session-written balance row therefore copies the previous row's other fields forward and
overwrites exactly the one field being stated. `total_value` is the deliberate exception: it is
the broker's stated total, a reconciliation check (016), and carrying a stale one forward would
fake a variance of zero — so session rows leave it null.

## 7. Revocation

**One statement kills the entire path, instantly, for every token already minted:**

```sql
revoke usage on schema api from yuna_session;
```

`EXECUTE` on a function is unusable without `USAGE` on its schema, so all eight verbs die at
once. No restart, no redeploy, no PostgREST reload. Every call returns *permission denied for
schema api*. Verified against a live server.

To restore: `grant usage on schema api to yuna_session;`

Escalations, in order of severity:

```sql
-- 2. also stop PostgREST assuming the role at all, for any grant path present or future
revoke yuna_session from authenticator;

-- 3. remove the surface entirely (the tables, the ledgers and the quarantine all survive —
--    they live in public, not in api)
drop schema api cascade;
```

And the ordinary hygiene, which is not revocation but is the first move in an incident: **stop
minting tokens, and let the outstanding one expire.** Token minting is Zak's, because the signing
secret is Zak's.

**What revocation does not do:** it does not roll back writes already made. Use `session_calls`
to find them — every row a session wrote points back to it:

```sql
select * from v_session_writes where session_id = '<the compromised session>';
select * from tickets where session_call_id in (select id from session_calls where …);
```

## 8. The guard triggers do not protect these tables from this path

**This must be understood by anyone reading `005_book.sql` and assuming they are covered.**

005 installs `yuna_jobs_only()` on the computed tables (universe, prices, candidates, queue,
bench, book, gate_state, nav_snapshots, earnings — plus fundamentals in 006 and the backtest
tables in 015). It refuses a write when `current_user` is not the migrator.

A `SECURITY DEFINER` function runs as its **owner**. Inside every verb in `api`, `current_user`
*is* the migrator. **The guards pass without comment.** Verified empirically against a live
server: a definer function owned by the migration role writes straight into a guarded table and
the trigger says nothing.

The consequences, stated plainly:

1. **The guards are not a control on this path.** They still do their original job — they stop a
   session connector, a pooler, or any other role writing directly. They do nothing about a
   definer function.
2. **Therefore every verb validates for itself.** Account existence, currency, ticket action,
   ticket reason, sleeve, order type, positive quantities, brief existence, state transitions,
   config protection, future dates, outliers — all checked in the verb body, none delegated to a
   trigger.
3. **Therefore no verb touches a guarded table.** The path writes to `briefs`, `tickets`,
   `observations`, `balances`, `config`, `session_calls` and `balance_quarantine`, and nothing
   else. §4.3 draws exactly this line — *"Sessions may write only briefs, tickets, observations,
   and config"* — and §2.0/§5.4 add balances. `book` is updated by the nightly job from
   confirmed tickets, never by a session; that is *"the machine computes; Yuna judges"* and it
   stays true here.
4. **If a future verb ever needs to write a guarded table, the guard will not stop it.** Anyone
   adding one is on their own honour, and should not add one.

## 9. Implementation notes worth knowing

- **`search_path` is pinned on every definer function**: `SET search_path = pg_catalog, public,
  pg_temp`. An unpinned definer function is a straight privilege escalation — the caller chooses
  which `balances` you insert into. `pg_temp` is pinned **last** deliberately: `CREATE` on a temp
  schema is granted to `PUBLIC` by default, so `pg_temp` first would let a caller shadow a table
  or an operator.
- **No verb builds SQL from a string.** The only dynamic SQL in the migration is in `DO` blocks
  that run once, at migration time, as the migrator.
- **`CREATE FUNCTION` grants `EXECUTE` to `PUBLIC` by default.** On a Supabase project `PUBLIC`
  includes `anon`, which is reachable with the publishable key and no login. The migration
  revokes from `PUBLIC` and grants to `yuna_session` only, and sets the default privilege so a
  function added later is not accidentally world-callable. Verified: the ACL on all eight verbs
  is owner + `yuna_session`, nothing else.
- **Errors carry PostgREST status codes.** `PT400` for a bad argument, `PT403` for a refusal,
  `PT404` for a missing ticket, `PT409` for an idempotency conflict, so the HTTP layer says
  something honest.
- **Refusals are not recorded in a table.** A `RAISE` aborts the transaction, which would erase
  any audit row written first, and Postgres has no autonomous transaction. Refusals land in the
  Postgres log (Supabase retains it) and in the caller's error. An attacker probing the protected
  config list therefore leaves a trace in the logs, not in the database. Named because it is the
  weakest point in the audit story.
- **Parameters are referenced as `<function>.<param>` throughout the verb bodies.** Verbose on
  purpose: `where key = key` is ambiguous in plpgsql, and the failure mode of getting it wrong is
  writing to the wrong row.

### Deploying it

1. Apply the migration (`python -m yuna.migrate` with `DATABASE_URL`).
2. **Supabase dashboard → Settings → API → Exposed schemas**: set it to `api`, and make sure
   `public` is *not* listed. This is the step that makes `public` unreachable over HTTP, and it
   is a dashboard setting on purpose — doing it in SQL (`alter role authenticator set
   pgrst.db_schemas = 'api'`) silently replaces whatever else was exposed.
3. Mint a token per session: role `yuna_session`, a `session` claim naming the run, a short
   `exp`. From Zak's machine, with Zak's signing secret. Never in chat, never in the repo — the
   same discipline §4.8 applies to `DATABASE_URL`.
4. Confirm: the session should be able to call a verb and should get *permission denied for
   table tickets* if it tries anything else.

## 10. Known gaps and things a human must verify

Listed rather than smoothed over.

1. **`db.nav_cad` does not distinguish provisional from confirmed balances.** It takes the newest
   row per account. So a provisional row written by `session_record_cash` becomes a NAV input
   immediately. §2.0 says weekday NAV extrapolates *"from the last confirmed balances"*, which
   argues NAV should prefer `provisional = false` and label itself. This migration deliberately
   did not touch `db.py`. **Someone must decide** whether `nav_cad` filters on `provisional`, or
   whether taking the newest row and labelling the NAV provisional is the intended reading.
2. **`session_propose_ticket` does not check that the account holds the cash.** §2.0 requires it
   (*"is only written if that account holds the cash"*). It needs NAV, open positions and the
   T+1 rule (clause `2.0/t1-reuse`, still OPEN) — a calculation that belongs in `policy.py`, not
   in a definer function. The account is required; the cash test is not made.
3. **§5.1's "max 2 new-entry tickets per brief" is not enforced here.** It is an R1 runbook rule,
   and enforcing a runbook in SQL was judged out of scope. It is also the natural rate limit on
   ticket flooding, so it may deserve to move here later.
4. **Ticket state history lives in `session_calls`, not in a `ticket_events` table.** Every
   transition a session makes is reconstructible. A transition made by a *job* (or by hand with
   `DATABASE_URL`) is not recorded anywhere. §4.3 calls `tickets` an append table whose *"rows
   [are] never edited"*, while the schema gives it `state` and `updated_at` — a pre-existing
   tension this migration resolves the way the schema already had, by editing state in place.
5. **Vocabularies enforced from schema comments, not from the plan.** Brief kinds
   (`preopen` … `phase0`), ticket actions, ticket reasons, order types and observation kinds are
   the lists in 005's column comments. The plan never enumerates them. `ruling` is a **new**
   observation kind added here for `session_rule`.
6. **`sleeve` on a ticket is restricted to `compounders` · `momentum` · `levered`.** `book` also
   carries `unassigned`, but that is a Phase-0 cutover artifact (007) and a session proposing a
   ticket knows the sleeve.
7. **`session_record_balance` writes non-provisional rows.** Any session can therefore state a
   number NAV treats as anchored truth. This is what the reconciliation session (R4) needs, and
   it is bounded by the quarantine, but it is a real capability worth knowing about.
8. **Clause markers are withheld from the migration.** The clauses this file services —
   `2.0/provisional-balances`, `2.2/jobs-arm-sessions-write`, and half of
   `2.0/ticket-names-account` — are all recorded `OPEN` in `src/yuna/rules.py`, and
   `test_conformance.py` fails the build when a marker cites an OPEN clause. That is correct
   behaviour: the ledger decides when a clause is built, and `2.2/jobs-arm-sessions-write` is
   genuinely not satisfied while `phase0.py` still writes tickets directly. Flip the statuses in
   `rules.py` and add the markers in the same commit, not before.
9. **`identified = false` should alarm.** Nothing reads it yet.

## 11. What was verified, and how

There is no database in the build environment, so this was verified against a **local PostgreSQL
16 cluster** stood up for the purpose: all eighteen migrations applied in order through the same
single-`execute`-per-file path `yuna.migrate` uses, then the verbs exercised as `yuna_session`
with a JWT claim set, exactly as PostgREST would.

Confirmed live: all 18 migrations apply clean · `yuna_session` is denied `SELECT` and `INSERT` on
every table and denied `USAGE` on `yuna_priv` · idempotent replay returns the identical envelope
and writes once · a reused key with different args is refused · every illegal ticket transition
is refused with the legal set named · the full legal chain proposed → approved → provisional →
confirmed works and appends its notes · protected config is refused by all five gates · an
extra-zero anchor and an extra-zero movement both quarantine and NAV does not move · a legitimate
5,000 deposit is accepted and NAV moves by exactly 5,000 · a USD anchor does not blank the CAD
cash (carry-forward) · all seven dry-run calls leave every table byte-identical and leave the key
free · a movement with no anchor writes the observation and no balance row · `revoke usage on
schema api from yuna_session` kills every verb and the grant restores it · the verb ACLs contain
no `PUBLIC` · a `SECURITY DEFINER` function sails through the 005 guard trigger (§8).

Not verified, because it needs the real deployment: the PostgREST layer, the JWT round trip, and
concurrent duplicate calls racing on the same idempotency key (the code takes the unique index
and a bounded retry, which is the standard construction, but it was not exercised under
contention).
