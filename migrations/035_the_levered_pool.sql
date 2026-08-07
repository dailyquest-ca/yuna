-- 035 — §2.5's levered pool reaches the brief.
--
-- Ruled 2026-08-06, law in the 2026-08-07 plan: **drawn levered capital is never idle — its
-- resting state is the ETF.** Borrowed dollars buy the qualified name when it is trading behind the
-- market and hand it back to the ETF when it has run well ahead of it.
--
-- The lag and lead thresholds are Zak's and he has not ruled them, so §2.5 says exactly what the
-- machine does in the meantime: "until set, the brief carries a levered status line (utilization
-- per facility, headroom, holdings) and **proposes nothing**." `score` computes that status every
-- night (§4.2 gives it every derived number) and stores it on the nightly brief; this exposes it
-- to the one read (§5.6) so `compose` and the sessions can speak it without crawling tables.
--
-- Nothing here decides anything. The one config key that would — `levered_cycle_params` — is
-- deliberately NOT seeded: it is a ruling, and a ruling is Zak's (§4.5). Seeding a placeholder
-- would be the exact shape of learnings #21 in reverse — a rule that looks enforced and is not.

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
  -- the full blackout wall, holdings included (§5.1 step 9): every name we hold or queue with a
  -- report inside 7 calendar days — the 5-trading-day law with weekend slack, resolved exactly
  -- by the session against the holiday calendar
  (select jsonb_agg(row_to_json(e)) from (
     select e.ticker, e.report_date, e.report_when from earnings e
      where e.report_date between current_date and current_date + 7
        and (e.ticker in (select ticker from book where status='open')
          or e.ticker in (select ticker from queue))
      order by e.report_date) e)                                           as blackout_wall,
  -- §3.1: a bench name reaching its hurdle is ruled in the next session before its GTC is placed.
  -- The population is "at the line": within 10% of the hurdle, or armed tonight at any distance —
  -- a name the job proposed and a rule held back still needs its ruling before anything ships.
  -- Unruled = no c2 ruling in the ledger at all. Nothing else belongs on this docket.
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
  -- The companion: the same population, already ruled, each with the verdict and the ruling id R1
  -- cites. A name here is not a question — it is an answer the desk already gave.
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
  -- §5.6's third state, which the old view had no room for: escalated and awaiting Zak. Not a
  -- ruling Yuna may make and not a docket item she can clear — a question, listed as one.
  (select jsonb_agg(row_to_json(x)) from (
     select b.ticker, b.ccn, b.hurdle_price, b.last_close, b.gap_to_hurdle,
            r.verdict, r.ruling_id, r.at as escalated_at, r.confidence
       from bench b
       join v_rulings_latest_c2 r on r.ticker = b.ticker and not r.decides
      where b.c1_pass
      order by b.gap_to_hurdle nulls last) x)                              as escalated_awaiting_zak,
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
    grant select on v_session_payload to yuna_session;
  end if;
exception when insufficient_privilege then
  raise notice 'view grants not applied here (%): mirror them in the dashboard', sqlerrm;
end $$;

insert into observations (kind, ticker, body, detail)
select 'note', null,
       '§2.5''s levered pool is computed nightly and carried on the brief (migration 035): '
       'utilization per facility, headroom to the plan''s cap rather than to the credit limit, '
       'levered holdings, and each name''s 126-session return against GSPC.INDX. Proposals stay '
       'empty until Zak rules config.levered_cycle_params — that emptiness is the ruling, not a gap.',
       '{"migration":"035_the_levered_pool","work_orders":["WO-10"]}'::jsonb
 where not exists (select 1 from observations where body like '§2.5''s levered pool is computed%');
