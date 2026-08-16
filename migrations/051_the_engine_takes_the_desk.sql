-- 051_the_engine_takes_the_desk.sql — 2026-08-16. §6.3's store.
--
-- v1.0's engine decides differently from everything this schema was built for, and the difference
-- is not a tweak. The old machine scored fundamentals, armed pivots, carried stops and trails, and
-- held a bench of candidates ruled one at a time. §3.3 replaces all of it with one number —
-- `(adj[i-21]/adj[i-252] - 1) / stdev(daily returns, 252)` — and §3.3 says the rank is the entire
-- opinion. There is no hurdle to clear, no thesis to write, and no stop to move.
--
-- So this migration adds the engine's own store rather than bending the old one:
--
--   `engine_sessions` — one row per decision close: the gate, the latch, the counts, the digest
--   `engine_ranks`    — the ranked pool for that close, score included
--   `tickets`         — §4.3's four states, and an idempotence key so a re-run cannot double a
--                       ticket the way `pipeline.yml`'s retry chain would otherwise let it
--
-- **Additive only.** Nothing here drops, rewrites or re-states a legacy row: the old tables keep
-- working until §6.3 retires the jobs that write them, and a migration that half-retires a live
-- pipeline is how you get a night with no desk at all.
--
-- Nothing here places an order (§0.2). A ticket is a proposal with a state; Zak's execution is the
-- event, and `reconcile` closes the loop against the broker's receipt.

-- ---------- engine_sessions ----------------------------------------------------------------
-- The decision close, and what the engine concluded on it. §3.5 marks position size "at the
-- decision close" and the orders execute at the NEXT open, so the session date here is the close
-- whose bars decided — never the morning the sheet is traded.
--
-- The gate is stored but not sourced from here. §3.4 derives the latch by walking the tape, and
-- `engine.gate_history` is the only definition; a stored flag that survived a failed ingest would
-- read ON while the data behind it was missing, which is the precise state §3.4 forbids. This row
-- is the RECORD of a decision, so the shadow (§6.4) can compare last night's answer to today's
-- recomputation and name a divergence rather than discover one.
create table if not exists engine_sessions (
  id bigint generated always as identity primary key,
  session_date date not null,              -- the decision close (§3.5)
  gate_on boolean not null,                -- §3.4's latched state
  gate_green boolean not null,             -- §3.4's raw signal: SPY strictly above its 200-day SMA
  index_close double precision,            -- SPY's adjusted close at the decision
  index_sma double precision,              -- the mean of its last 200, today included
  universe_count integer not null,         -- names with a column on the tape after §3.2's exclusions
  ranked_count integer not null,           -- names that survived the screen and scored finite
  nav double precision,                    -- engine NAV the sheet was sized at (§3.5); null = unsized
  param_digest text not null,              -- §3.6's constants, hashed — see engine.digest()
  mode text not null default 'live',       -- live | shadow (§6.4 runs ten sessions nobody trades)
  detail jsonb,
  created_at timestamptz not null default now()
);
-- One decision per close per mode. A re-run overwrites its own row rather than appending a second
-- opinion — `pipeline.yml`'s retry ingest fires the whole chain again by design, and two rows for
-- one close would make "what did the engine decide on the 14th" a question with two answers.
create unique index if not exists engine_sessions_key on engine_sessions(session_date, mode);

comment on table engine_sessions is
  'S3 decision record: one row per decision close per mode. The gate here is a RECORD of what was '
  'decided, not its source - S3.4 derives the latch from the tape on every read (engine.gate_history).';

-- ---------- engine_ranks --------------------------------------------------------------------
-- §3.3's output for a close: the ranked pool, best first. The whole pool rather than the top 12,
-- because a subset is a choice and §3.2's pool cap of 500 is already the plan's own cut. Storing
-- what the engine computed makes §4.4's rank-reproducibility gauge a real comparison and gives
-- §6.4's shadow something to diff; storing the top 12 would only prove the top 12 reproduced.
create table if not exists engine_ranks (
  id bigint generated always as identity primary key,
  session_date date not null,
  mode text not null default 'live',
  ticker text not null,
  rank integer not null,                   -- 1 = best (§3.3, descending score)
  score double precision not null,         -- (adj[i-21]/adj[i-252] - 1) / stdev(daily returns, 252)
  mark double precision,                   -- raw close at the decision (§3.5 sizes off this)
  addv double precision,                   -- 50-session median dollar volume (§3.2)
  created_at timestamptz not null default now()
);
create unique index if not exists engine_ranks_key on engine_ranks(session_date, mode, ticker);
create index if not exists engine_ranks_session_idx on engine_ranks(session_date desc, mode, rank);

comment on table engine_ranks is
  'S3.3 rank for a decision close. The full pool, not the top 12 - a subset would make S4.4 rank '
  'reproducibility a check on the answer rather than on the computation.';

-- ---------- tickets: §4.3's state machine ----------------------------------------------------
-- "Ticket states: proposed → approved → executed → reconciled. Yuna writes rows; Zak's execution
-- is the event; reconcile closes the loop with the receipt."
--
-- The columns the engine needs and the old schema has no place for: which decision close produced
-- the row, what rank justified it, and which §3.5 clause fired.
alter table tickets
  add column if not exists session_date date,
  add column if not exists rank         integer,
  add column if not exists clause       text,     -- rank_exit | displaced | fill | gate_off | phase0
  add column if not exists mark         double precision,   -- the decision close the qty was sized at
  add column if not exists executed_at  timestamptz,
  add column if not exists reconciled_at timestamptz;

comment on column tickets.session_date is
  'S3.5 the DECISION close whose bars produced this ticket. Execution is the next open; a ticket '
  'dated the morning it trades would misstate which bars decided it.';
comment on column tickets.clause is
  'Which S3.5 clause fired: rank_exit (below 12), displaced (top-2 swap), fill (free slot), '
  'gate_off (S3.4 sells the book). A ticket whose reason is not a clause of the plan is a bug.';

-- Idempotence. §4's jobs are re-run on failure and chained by `needs:`, so the same close can be
-- scored twice in one night. One ticket per (close, ticker, action) — a second pass updates the
-- row it already wrote. Partial, so the legacy rows (which carry no session_date) are untouched
-- and unconstrained.
create unique index if not exists tickets_engine_key
  on tickets(session_date, ticker, action)
  where session_date is not null;

-- §4.3's vocabulary, enforced on new rows only. NOT VALID is the point: the legacy rows carry
-- `provisional` and `confirmed` from the old fill loop, and rewriting a historical ticket's state
-- to fit today's law would falsify the record of what was actually proposed and filled. Old rows
-- keep their words; anything written from here forward uses §4.3's.
--
-- `cancelled` and `expired` are in the permitted set and are NOT inventions: §6.2 requires voiding
-- every open ticket at close-out, and §4.3's amber rule withdraws unissued buy tickets. §4.3 names
-- the states a ticket passes THROUGH on the happy path; it does not claim a ticket may never be
-- withdrawn.
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'tickets_state_vocabulary') then
    alter table tickets add constraint tickets_state_vocabulary
      check (state in ('proposed', 'approved', 'executed', 'reconciled',
                       'cancelled', 'expired',
                       'provisional', 'confirmed'))   -- legacy, never written by the engine
      not valid;
  end if;
end $$;

create index if not exists tickets_session_idx on tickets(session_date desc, action);

-- ---------- v_engine_sheet -------------------------------------------------------------------
-- The nightly sheet as one readable row per order. §4.3: "the nightly sheet is the only source of
-- engine orders", so there is exactly one query that answers "what does Zak do at the open".
--
-- Sells sort first — §3.5 executes sells before buys, and a sheet that lists them in any other
-- order invites the one mistake that costs money (buying with proceeds that have not landed).
create or replace view v_engine_sheet as
select t.session_date,
       t.id                                as ticket_id,
       case t.action when 'sell' then 0 else 1 end as execution_order,
       t.action,
       t.ticker,
       t.qty,
       t.mark,
       t.rank,
       t.clause,
       t.state,
       t.account,
       t.sleeve,
       t.note,
       t.created_at
  from tickets t
 where t.session_date is not null
 order by t.session_date desc, execution_order, t.rank nulls last, t.ticker;

comment on view v_engine_sheet is
  'S4.3 the nightly sheet: the only source of engine orders. Sells sort before buys because S3.5 '
  'executes them in that order.';
