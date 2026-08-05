-- 033_handover.sql — the E1–E13 handover batch (plan 2026-08-04) as schema.
--
-- Judgment transfers to Yuna inside the gates, and the database is where that transfer becomes
-- enforceable rather than promised. Four things happen here:
--
--   1. `rulings` — every name-level verdict, append-only, binding on later sessions (§4.3).
--      Jobs read it: only ruled names ship entry tickets (§3.1's rulings law).
--   2. `learnings` — the §5.8 ladder, append-only. No falsifier, no learning — enforced by check
--      constraint, not by memory.
--   3. The session write list changes: §4.3 now reads "briefs, tickets, observations, rulings,
--      learnings, and config" — transactions leaves the list. A fill now travels as ticket state
--      (§4.5: chat or flip → tickets row provisional), and the nightly job derives the
--      transactions row. Tickets gain the fill fields that carries.
--   4. `v_session_payload` — the one-read law (§5.6) as a view: an interactive chat reads this
--      single row, then judges. It never crawls tables.

-- ---------- 1. rulings (append) ----------
create table if not exists rulings (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  kind text not null,              -- c2 | exit | conversion | sweep_void | entry_timing | reversal
  ticker text not null,
  verdict text not null,           -- pass | fail | hold | exit | convert | void
  blind boolean not null default false,   -- §3.1: business verdict recorded before price/gap/CCN
  confidence text,                 -- high | medium | low (low escalates by choice, §5.6)
  memo text,                       -- the C2 memo / review memo text itself
  evidence jsonb,                  -- the §3.3 three lines: score · filings · outside world
  cooldown_until date,             -- FAIL rows carry the 12-month date; escape clause in §3.1
  ccn_at_ruling double precision,  -- recorded on every rejection — the escape arithmetic needs it
  reverses bigint references rulings(id),  -- a reversal is a NEW row citing the old, never an edit
  session_id text,
  brief_id bigint,
  detail jsonb
);
create index if not exists rulings_ticker_idx on rulings(ticker, at desc);
create index if not exists rulings_kind_idx on rulings(kind, at desc);
comment on table rulings is
  '§4.3: every name-level verdict — Yuna''s, exercised inside the gates and never over them. '
  'Append-only; a logged verdict is overturned only by the cooldown escape clause or a logged '
  'reversal citing new evidence. Jobs read it: only ruled names ship entry tickets.';
alter table rulings enable row level security;

-- ---------- 2. learnings (append) ----------
-- The ladder: observation → learning → proposal → promoted | expired. Rows are never edited —
-- a rung climbed is a new row whose `supersedes` points at the last, so the ledger holds the
-- whole life of every hypothesis and `v_learnings_current` shows the live rung.
create table if not exists learnings (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  key text not null,               -- stable name for the hypothesis across rungs
  status text not null default 'observation',
                                   -- observation | learning | proposal | promoted | expired
  lane text,                       -- mechanics (fast) | strategy (slow, evidence-gated) — §5.8
  hypothesis text,
  falsifier text,                  -- the condition that kills it
  occurrences integer not null default 1,
  observation_ids bigint[],        -- the observations rows that earned the rung
  scorecard jsonb,
  proposal_edit jsonb,             -- {section, old_line, new_line} — exact, per §5.8 rung 3
  loosens_risk boolean not null default false,  -- routes as a risk-posture item, Zak's (§5.8)
  ruled_by text,                   -- 'zak' on rung 4 rows
  supersedes bigint references learnings(id),
  detail jsonb,
  -- §5.8, the law verbatim: every learning must name its falsifier. No falsifier, no learning.
  constraint learnings_falsifier_required
    check (status = 'observation' or falsifier is not null)
);
create index if not exists learnings_key_idx on learnings(key, at desc);
comment on table learnings is
  '§5.8 ladder, append-only. A rung climbed is a new row superseding the last. '
  'Loosening proposals always route as risk-posture items — Zak''s under §4.5.';
alter table learnings enable row level security;

create or replace view v_learnings_current as
select distinct on (key) * from learnings order by key, at desc, id desc;

-- ---------- 3. the write list moves ----------
-- Tickets carry the fill so sessions no longer write transactions. The nightly job reads these
-- fields off provisional/confirmed tickets and owns the transactions ledger (src/arming.py).
alter table tickets add column if not exists fill_price double precision;
alter table tickets add column if not exists fill_qty   double precision;
alter table tickets add column if not exists fill_date  date;
alter table tickets add column if not exists fill_fx    double precision;
alter table tickets add column if not exists fill_fees  double precision;
comment on column tickets.fill_price is
  '§4.5 fill loop: Zak''s reported fill lives on the ticket; the job derives the transactions row';

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'yuna_session') then
    -- §4.3 (2026-08-04): sessions write briefs, tickets, observations, rulings, learnings, config.
    -- Rulings and learnings are ledgers — insert only, rows never edited.
    grant insert on rulings, learnings to yuna_session;
    drop policy if exists yuna_session_rw on rulings;
    create policy yuna_session_rw on rulings to yuna_session using (true) with check (true);
    drop policy if exists yuna_session_rw on learnings;
    create policy yuna_session_rw on learnings to yuna_session using (true) with check (true);

    -- transactions leaves the session write list; the ledger becomes job-written like the book.
    revoke insert, update on transactions from yuna_session;
    drop policy if exists yuna_session_rw on transactions;
  end if;
exception when insufficient_privilege then
  raise notice 'yuna_session grants not applied here (%): mirror them in the dashboard', sqlerrm;
end $$;

-- transactions joins the guarded tables — job-written only, same trigger as the book
drop trigger if exists guard_transactions on transactions;
create trigger guard_transactions before insert or update or delete on transactions
  for each row execute function yuna_jobs_only();

-- the guard's error message still names the old list; refresh it once, here
create or replace function yuna_jobs_only() returns trigger
language plpgsql as $$
begin
  if current_user not in ('postgres','supabase_admin') then
    raise exception '% is job-written only — sessions may write briefs, tickets, observations, rulings, learnings, config', TG_TABLE_NAME
      using hint = 'jobs compute · database remembers · Yuna judges · Zak acts (plan §4.0)';
  end if;
  return coalesce(NEW, OLD);
end $$;

-- ---------- 4. the one-read payload (§5.6) ----------
-- One row, one select. Each column is a domain, already shaped; an interactive chat reads this
-- and judges. Composed briefs ride along so the morning chat opens onto the pipeline's words
-- instead of rebuilding them (§5.1).
create or replace view v_session_payload as
select
  (select row_to_json(r) from (
     select status, finished_at, detail->>'freshness' as freshness,
            detail->'blocks_dispatch' as blocks_dispatch, detail->'amber' as amber,
            detail->'preflight' as preflight
       from runs where job='check' order by id desc limit 1) r)            as check_report,
  (select jsonb_agg(row_to_json(a)) from v_armed_latest a)                  as armed,
  (select jsonb_agg(row_to_json(b)) from v_book b)                         as book,
  (select jsonb_agg(row_to_json(q)) from v_queue q)                        as queue,
  (select row_to_json(g) from (select week_end, state, flipped, spx_close, sma30
     from gate_state order by week_end desc, id desc limit 1) g)           as gate,
  (select row_to_json(n) from (select d, nav_cad, provisional from nav_snapshots
     order by d desc, id desc limit 1) n)                                  as nav,
  -- the full blackout wall, holdings included (§5.1 step 9): every name we hold or queue with a
  -- report inside 7 calendar days — the 5-trading-day law with weekend slack, resolved exactly
  -- by the session against the holiday calendar
  (select jsonb_agg(row_to_json(e)) from (
     select e.ticker, e.report_date, e.report_when from earnings e
      where e.report_date between current_date and current_date + 7
        and (e.ticker in (select ticker from book where status='open')
          or e.ticker in (select ticker from queue))
      order by e.report_date) e)                                           as blackout_wall,
  -- unruled names at the line: §3.1 — a bench name reaching its hurdle is ruled in the next
  -- session before its GTC limit is placed
  (select jsonb_agg(row_to_json(u)) from (
     select b.ticker, b.ccn, b.hurdle_price, b.last_close, b.gap_to_hurdle
       from bench b
      where b.c1_pass and b.hurdle_price is not null and b.last_close is not null
        and b.last_close <= b.hurdle_price * 1.10
        and not exists (select 1 from rulings r
                         where r.ticker = b.ticker and r.kind = 'c2'
                           and r.verdict in ('pass','fail')
                           and not exists (select 1 from rulings x where x.reverses = r.id))
      order by b.gap_to_hurdle) u)                                         as unruled_at_the_line,
  (select jsonb_agg(row_to_json(t)) from (
     select id, ticker, account, action, state, order_type, trigger_price, limit_price, qty,
            stop, stop_limit_price, theme, created_at
       from tickets where state in ('proposed','approved','provisional')
      order by created_at desc) t)                                         as open_tickets,
  (select jsonb_agg(row_to_json(l)) from (
     select key, status, lane, hypothesis, falsifier, occurrences, loosens_risk
       from v_learnings_current
      where status in ('learning','proposal') order by at desc limit 12) l) as learnings_brewing,
  (select jsonb_agg(row_to_json(c)) from (
     select kind, at, session_date, freshness, summary, body from briefs
      where detail->>'composed' = 'true' and at > now() - interval '30 hours'
      order by at desc) c)                                                 as composed;

comment on view v_session_payload is
  '§5.6 one-read law: an interactive chat reads this single row, then judges — it never crawls '
  'tables. Live MCP quotes remain the sanctioned exception, for protection and verification only.';

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'yuna_session') then
    grant select on v_learnings_current, v_session_payload to yuna_session;
  end if;
exception when insufficient_privilege then
  raise notice 'view grants not applied here (%): mirror them in the dashboard', sqlerrm;
end $$;

-- ---------- config the new code reads (learnings #21 — ships with its reader) ----------
insert into config (key, value, note, set_by) values
 ('push_channel', '"cowork"',
  '§4.4/§4.7: notify''s delivery service. "cowork" = the scheduled Routines inside the Yuna '
  'chat/cowork project deliver the composed words — and apply the §5.0 voice on Zak''s Claude '
  'plan, never a metered API key (ruled 2026-08-05); notify verifies the payload exists and is '
  'fresh, and goes red when it is missing — a missing message is itself the alarm', 'zak');

insert into observations (kind, ticker, body, detail)
select 'note', null,
       'Handover batch provisioned (plan 2026-08-04, E1–E13): rulings and learnings ledgers '
       'live; session write list is now briefs, tickets, observations, rulings, learnings, '
       'config; transactions is job-written and derived from ticket fills; v_session_payload '
       'carries the one-read law.',
       '{"migration":"033_handover","plan_stamp":"2026-08-04"}'::jsonb
 where not exists (select 1 from observations where body like 'Handover batch provisioned%');
