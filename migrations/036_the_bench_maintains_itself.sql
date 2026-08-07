-- 036 — the bench stops being maintained by hand.
--
-- Five columns on `bench` were kept by hand and read by the machine: `c2_status`, `c2_memo`,
-- `c2_confidence`, `approved`, `owner_fcf_suspect`. Every one of them is a copy of a judgment that
-- already lives in `rulings`, and every one of them is destroyed the moment `score` rebuilds that
-- row — which it does whenever a name fails C1 for a quarter. A hand-kept copy of a ledger is not
-- a record; it is a countdown.
--
-- From here the bench derives all five, every night, in two plain sentences:
--
--   * **A name is approved when the desk's most recent C2 verdict on it is a blind PASS.**
--   * **A name is quarantined when a live quarantine ruling stands on it.**
--
-- Nothing new to remember, and no new vocabulary: lifting a quarantine is a logged reversal, which
-- §3.1 already names as the only way a verdict is overturned.
--
-- Two things this file does so that deriving is safe rather than destructive.

-- ---------- 0. the ledger view carries the memo ----------
-- `bench.c2_memo` is derived from here now, and 034 did not project it. Appended rather than
-- rebuilt, because `create or replace` can add a column at the end and nothing reads by position.
create or replace view v_rulings_latest as
  select distinct on (r.ticker, r.kind)
         r.ticker, r.kind, r.id as ruling_id, r.at, r.verdict,
         yuna_verdict(r.verdict) as verdict_canon,
         yuna_verdict(r.verdict) <> 'escalate' as decides,
         r.blind, r.confidence, r.cooldown_until, r.ccn_at_ruling, r.session_id, r.memo
    from rulings r
   where not exists (select 1 from rulings x where x.reverses = r.id)
     and yuna_verdict(r.verdict) is distinct from 'reversal'
   order by r.ticker, r.kind, r.at desc, r.id desc;

create or replace view v_rulings_latest_c2 as
  select * from v_rulings_latest where kind = 'c2';

-- ---------- 1. the quarantine becomes its own question ----------
-- The desk's own DLO ruling says it out loud: "QUARANTINE — owner-cash (§3.1), not entry-eligible;
-- **PASS/FAIL deferred to R5**". The float and the business are two questions, and forcing them
-- through one verdict slot is what made a later PASS look like it should lift a quarantine. It
-- should not: a card issuer can be a wonderful business and still report other people's money as
-- free cash flow. So a quarantine is `kind='quarantine'` from now on, and the C2 verdict stays
-- free to answer the question it was asked.
create or replace view v_quarantine_live as
  select distinct on (ticker) ticker, id as ruling_id, at, verdict, memo, confidence
    from rulings r
   where not exists (select 1 from rulings x where x.reverses = r.id)
     -- a reversal withdraws its target and then steps aside; it is not itself a quarantine
     and yuna_verdict(r.verdict) is distinct from 'reversal'
     and (r.kind = 'quarantine' or (r.kind = 'c2' and yuna_verdict(r.verdict) = 'quarantine'))
   order by ticker, at desc, id desc;

comment on view v_quarantine_live is
  '§3.1 owner-cash quarantine: a name is quarantined while a live quarantine ruling stands on it. '
  'Reading kind=''c2'' with a QUARANTINE verdict too, because that is how the first two were '
  'written. To lift one, log a reversal — §3.1''s only route for overturning a verdict.';

-- ---------- 2. the marks that were never rulings ----------
-- Seven bench rows carry an owner-cash quarantine set by hand at R5 with nothing in the ledger
-- behind them: AMP, APO, AXP, HQY, PCTY, SCHW, SYF — a card issuer, an HSA custodian, a payroll
-- processor, a broker and three lenders. Every mark is right. None would survive its bench row.
--
-- Transcribed, not invented: the judgment was made, and this is it being written down where the
-- machine can read it. `blind` is false because a transcription is not a blind ruling, and the
-- provenance says exactly what happened.
insert into rulings (ticker, kind, verdict, blind, confidence, memo, session_id, detail)
select b.ticker, 'quarantine',
       'QUARANTINE — owner-cash (§3.1): reported FCF is materially customer float or credit-book '
       'funding. Scored, ranked, watched, never ticketed.',
       false, 'transcribed — not a fresh ruling',
       'Transcribed from bench.owner_fcf_suspect, which was set by hand and carried no ruling. '
       'The mark predates this row; the row is what makes it survive a bench rebuild.',
       'migration/036',
       jsonb_build_object('transcribed_from', 'bench.owner_fcf_suspect',
                          'transcribed_at', current_date)
  from bench b
 where b.owner_fcf_suspect
   and not exists (select 1 from v_quarantine_live q where q.ticker = b.ticker);

-- ---------- 3. the C2 columns follow the ledger ----------
comment on column bench.c2_status is
  '§3.1 — derived every run from the latest live c2 ruling. Never set by hand: a hand-kept copy '
  'of a ledger dies with its row.';
comment on column bench.approved is
  '§3.1 — derived: the latest live c2 verdict is a blind PASS. Withdrawn by any other verdict.';
comment on column bench.owner_fcf_suspect is
  '§3.1 — derived: a live quarantine ruling stands on this name (v_quarantine_live).';

-- ---------- 4. quarantined names stay visible ----------
-- §3.1 says a quarantined name is "scored, ranked, **watched**, never ticketed". Deriving
-- `approved` from the C2 verdict means a quarantined name no longer reaches the arming stage at
-- all — which is right, and would have made it invisible. Watched means on the brief.
--
-- This is the payload's third definition in three migrations, and the last: 034 fixed the docket,
-- 035 added the levered pool, and each was a `create or replace` that could only append. A view
-- cannot select from itself, so the field belongs beside the docket it qualifies rather than
-- bolted on the end — **this file is the canonical definition; 034's and 035's are superseded.**
drop view if exists v_session_payload;
create view v_session_payload as
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
  -- §2.5's levered pool: utilization per facility, headroom to the cap the plan permits (not to
  -- the credit limit), the holdings, and how far each name has run against the index. `proposals`
  -- is empty until `config.levered_cycle_params` exists — that emptiness is the ruling, not a gap.
  (select detail->'levered' from briefs
    where kind = 'nightly' and detail ? 'levered'
    order by at desc, id desc limit 1)                                     as levered,
  -- the full blackout wall, holdings included (§5.1 step 9)
  (select jsonb_agg(row_to_json(e)) from (
     select e.ticker, e.report_date, e.report_when from earnings e
      where e.report_date between current_date and current_date + 7
        and (e.ticker in (select ticker from book where status='open')
          or e.ticker in (select ticker from queue))
      order by e.report_date) e)                                           as blackout_wall,
  -- §3.1: a bench name at the line is ruled before its GTC ships. Unruled = no c2 ruling at all.
  (select jsonb_agg(row_to_json(u)) from (
     select b.ticker, b.ccn, b.hurdle_price, b.last_close, b.gap_to_hurdle,
            b.engine_provenance, b.data_confidence
       from bench b
      where b.c1_pass
        and ((b.hurdle_price is not null and b.last_close is not null
              and b.last_close <= b.hurdle_price * 1.10)
             or exists (select 1 from v_armed_latest a
                         where a.ticker = b.ticker and a.kind in ('entry','add')))
        and not exists (select 1 from v_rulings_latest_c2 r where r.ticker = b.ticker)
      order by b.gap_to_hurdle nulls last) u)                              as unruled_at_the_line,
  -- the same population, already ruled — R1 cites the ruling instead of re-deciding
  (select jsonb_agg(row_to_json(v)) from (
     select b.ticker, b.ccn, b.hurdle_price, b.last_close, b.gap_to_hurdle,
            r.verdict, r.verdict_canon, r.ruling_id, r.at as ruled_at, r.blind, r.confidence
       from bench b
       join v_rulings_latest_c2 r on r.ticker = b.ticker and r.decides
      where b.c1_pass
        and ((b.hurdle_price is not null and b.last_close is not null
              and b.last_close <= b.hurdle_price * 1.10)
             or exists (select 1 from v_armed_latest a
                         where a.ticker = b.ticker and a.kind in ('entry','add')))
      order by b.gap_to_hurdle nulls last) v)                              as ruled_at_the_line,
  -- §5.6's third state: escalated and awaiting Zak. A question, listed as one.
  (select jsonb_agg(row_to_json(x)) from (
     select b.ticker, b.ccn, b.hurdle_price, b.last_close, b.gap_to_hurdle,
            r.verdict, r.ruling_id, r.at as escalated_at, r.confidence
       from bench b
       join v_rulings_latest_c2 r on r.ticker = b.ticker and not r.decides
      where b.c1_pass
      order by b.gap_to_hurdle nulls last) x)                              as escalated_awaiting_zak,
  -- §3.1's owner-cash quarantine: scored, ranked, **watched**, never ticketed. It no longer
  -- reaches the arming stage at all, so watched has to mean listed.
  (select jsonb_agg(row_to_json(w)) from (
     select b.ticker, b.ccn, b.hurdle_price, b.last_close, b.gap_to_hurdle,
            q.verdict, q.ruling_id, q.at as quarantined_at
       from bench b join v_quarantine_live q on q.ticker = b.ticker
      order by b.ccn desc nulls last) w)                                   as quarantined_watchlist,
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
    grant select on v_quarantine_live to yuna_session;
  end if;
exception when insufficient_privilege then
  raise notice 'view grants not applied here (%): mirror them in the dashboard', sqlerrm;
end $$;

insert into observations (kind, ticker, body, detail)
select 'note', null,
       'The bench maintains itself (migration 036): c2_status, c2_memo, c2_confidence, approved '
       'and owner_fcf_suspect are all derived from `rulings` every run. Seven hand-set owner-cash '
       'marks with no ruling behind them were transcribed into the ledger first, so deriving '
       'preserves them instead of erasing them. A quarantine is now its own ruling kind, because '
       'the float and the business are two questions and the desk''s own DLO ruling says so.',
       '{"migration":"036_the_bench_maintains_itself"}'::jsonb
 where not exists (select 1 from observations where body like 'The bench maintains itself%');
