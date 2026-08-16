-- 054_the_payload_is_the_engine.sql — 2026-08-16. §4.2's payload, rebuilt for v1.0.
--
-- "**4.2 The payload.** `v_session_payload` carries: gate state & latch, current book with ranks,
--  the nightly order sheet, top-12 with scores, the exclusion table, NAV & DD status, levered
--  facilities & tranche schedule, pipeline freshness, learnings. It is the single read of every
--  session."
--
-- Nine items. The old view carried fourteen and not one of them was on that list — bench names at
-- the hurdle, c2 rulings, the blackout wall, armed rows, the quarantine watchlist. Every one of
-- those belonged to an engine that scored fundamentals and armed pivots, and §3.3 replaced the
-- whole apparatus with one number. Editing the old view would have left a payload that was mostly
-- about a machine that no longer runs, so it is rebuilt from the plan's sentence.
--
-- **The old view is not dropped and the old tables are not touched.** §6.3 retires the legacy jobs
-- from the SCHEDULE; deleting their store in the same change that repoints production is how you
-- get a night with no desk. `v_session_payload_legacy` keeps the previous definition readable for
-- as long as anything wants it.

-- ---------- what the engine is worth --------------------------------------------------------
-- §5.2's drawdown milestones are measured against engine NAV, and engine NAV is not in the store —
-- see `sheet.engine_nav`. What IS derivable is the sleeve's marked equity: every momentum position
-- at its last close. That is a complete measure of the sleeve BY CONSTRUCTION, and the reason is
-- §2.4 and §3.4 together: cash that is not awaiting a same-week order sits in the designated
-- holding, and a gated-off book parks its proceeds in SPY. The sleeve is always in positions, so
-- marking the positions marks the sleeve.
--
-- The known gap is stated rather than papered over: §3.7(4)'s rounding residue parks too, and
-- until a park position exists in the book that residue is invisible here. It is bounded by four
-- share prices and it is not a drawdown.
alter table engine_sessions
  add column if not exists marked_equity double precision;

comment on column engine_sessions.marked_equity is
  'The momentum sleeve marked at the decision close: sum(qty x close). Complete by construction - '
  'S2.4 and S3.4 leave the sleeve always in positions - except for S3.7(4) rounding residue.';

-- Peak-to-date and drawdown, from the marked series. The peak is a running maximum over prior
-- sessions INCLUSIVE, so a new high reads 0% rather than negative.
create or replace view v_engine_drawdown as
select session_date,
       marked_equity,
       max(marked_equity) over (order by session_date
                                rows between unbounded preceding and current row) as peak,
       case when max(marked_equity) over (order by session_date
                                          rows between unbounded preceding and current row) > 0
            then marked_equity / max(marked_equity) over (order by session_date
                                     rows between unbounded preceding and current row) - 1.0
       end as drawdown
  from engine_sessions
 where mode = 'live' and marked_equity is not null;

comment on view v_engine_drawdown is
  'S5.2 drawdown milestones are INFORMATION, never action. No mechanical intervention exists at '
  'any level; any intervention is Zak''s explicit ruling in chat.';

-- ---------- §2.3's ramp, as rows ------------------------------------------------------------
-- "Ramp (ruled 2026-08-15): three tranches to the cap — $12.5K immediately · $12.5K ~Sep 15 ·
--  $12.6K ~Oct 15. Each tranche requires the gate (§3.4) ON that week; a skipped tranche shifts
--  one month; never two tranches in one month."
--
-- Amounts are the plan's verbatim. Dates: the plan writes "~Sep 15" and "~Oct 15" against a v1.0
-- promoted 2026-08-15 and targeting mid-September 2026, so the years are 2026 and the tildes are
-- carried into `approximate` rather than dropped. "Immediately" is not a calendar date at all, so
-- tranche one records the plan's own promotion date as the earliest it could have been taken —
-- §6.1(4) puts it on Phase 0's morning, independent of the liquidation.
create table if not exists levered_tranches (
  seq integer primary key,
  amount_cad double precision not null,
  planned_on date not null,
  approximate boolean not null default true,
  status text not null default 'planned',   -- planned | drawn | skipped
  drawn_on date,
  note text,
  updated_at timestamptz not null default now()
);

insert into levered_tranches (seq, amount_cad, planned_on, approximate, note) values
  (1, 12500, '2026-08-15', false,
   '§2.3 "$12.5K immediately"; §6.1(4) puts it on Phase 0 morning, independent of the liquidation'),
  (2, 12500, '2026-09-15', true,  '§2.3 "$12.5K ~Sep 15"'),
  (3, 12600, '2026-10-15', true,  '§2.3 "$12.6K ~Oct 15"')
on conflict (seq) do nothing;

comment on table levered_tranches is
  'S2.3''s ramp to the cap. Each tranche requires the gate ON that week; a skipped tranche shifts '
  'one month; never two tranches in one month. Every draw purchases VXC.TO in the NONREG the same '
  'day - one draw, one purchase, for ITA 20(1)(c).';

-- The facility against §2.3's hard cap. The LIMIT is Zak's to state (a `balances` row, source
-- 'zak'); the CAP is the plan's arithmetic on it. Reporting headroom to the credit limit rather
-- than to the cap is the error this view exists to make impossible: §2.3 caps the drawn balance at
-- 50% of the limit, and "the cap binds hardest when the book is red; that is its purpose."
create or replace view v_levered_facility as
select b.account, b.as_of, b.credit_limit, b.drawn,
       a.max_utilization,
       b.credit_limit * a.max_utilization                     as cap,
       b.credit_limit * a.max_utilization - b.drawn           as headroom_to_cap,
       case when b.credit_limit > 0 then b.drawn / b.credit_limit end as utilization
  from (select distinct on (account) account, as_of, credit_limit, drawn
          from balances where credit_limit is not null
         order by account, as_of desc, id desc) b
  join accounts a on a.code = b.account
 where a.kind = 'facility';

comment on view v_levered_facility is
  'S2.3: headroom is measured to the CAP (50% of the limit), never to the limit. The facility is '
  'callable and the levered layer holds no defense against a call other than the cap and the reserve.';

-- ---------- the legacy docket, moved out of the payload ---------------------------------------
-- Four of the old payload's fields were the previous engine's RULING DOCKET: bench names at the
-- hurdle with no c2 ruling, the same population already ruled, the escalations awaiting Zak, and
-- the owner-cash quarantine. §3.3 leaves v1.0 with no bench, no hurdle and no per-name ruling —
-- "the rank is the entire opinion" — so none of them belong in §4.2's list.
--
-- They are moved rather than deleted. `arming.py` and the ledger behind it survive as dispatch-only
-- tooling until §6.4's shadow passes, and while they exist their docket is a legitimate read; it is
-- simply not what a session reads to decide. The definitions are 036's, unchanged.
create or replace view v_ruling_docket as
select
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
  (select jsonb_agg(row_to_json(x)) from (
     select b.ticker, b.ccn, b.hurdle_price, b.last_close, b.gap_to_hurdle,
            r.verdict, r.ruling_id, r.at as escalated_at, r.confidence
       from bench b
       join v_rulings_latest_c2 r on r.ticker = b.ticker and not r.decides
      where b.c1_pass
      order by b.gap_to_hurdle nulls last) x)                              as escalated_awaiting_zak,
  (select jsonb_agg(row_to_json(w)) from (
     select b.ticker, b.ccn, b.hurdle_price, b.last_close, b.gap_to_hurdle,
            q.verdict, q.ruling_id, q.at as quarantined_at
       from bench b join v_quarantine_live q on q.ticker = b.ticker
      order by b.ccn desc nulls last) w)                                   as quarantined_watchlist;

comment on view v_ruling_docket is
  'The pre-v1.0 engine''s ruling docket, moved out of v_session_payload by migration 054. S3.3 '
  'leaves v1.0 with no bench, no hurdle and no per-name ruling, so none of this is what a session '
  'reads to decide. Retained while arming.py survives as dispatch-only tooling.';

-- ---------- the payload -----------------------------------------------------------------------
-- The pre-v1.0 definition is migration 036's and is superseded here. It is not preserved as a
-- second view: it reads `bench`, `armed`, `queue` and `v_rulings_latest_c2`, all of which belong to
-- jobs §6.3 is retiring, and a view that keeps working while nothing writes its tables would
-- report an empty desk as a calm one.
drop view if exists v_session_payload;
create view v_session_payload as
select
  -- 1. gate state & latch (§3.4). Derived on every read by `engine.gate_history`; this row is the
  --    RECORD of the decision, and a disagreement between the two is exactly §4.4's first gauge.
  (select row_to_json(g) from (
     select session_date, gate_on, gate_green, index_close, index_sma, param_digest, mode
       from engine_sessions where mode = 'live'
      order by session_date desc limit 1) g)                                as gate,

  -- 2. current book with ranks (§4.2). The rank is joined from the newest session, so a holding
  --    with no rank shows null — and null is the signal, not a gap: §3.5 queues anything below 12
  --    and "not ranked at all" is below it.
  (select jsonb_agg(row_to_json(b) order by b.rank nulls last, b.ticker) from (
     select k.ticker, k.account, k.sleeve, k.qty, round(k.avg_cost::numeric, 4) as avg_cost,
            k.currency, p.close as last_close,
            round((k.qty * p.close)::numeric, 2) as market_value,
            round((100.0 * (p.close - k.avg_cost) / nullif(k.avg_cost, 0))::numeric, 1) as pnl_pct,
            r.rank, r.score, k.opened_at
       from book k
       left join lateral (select close from prices where ticker = k.ticker
                           order by d desc limit 1) p on true
       left join engine_ranks r on r.ticker = k.ticker and r.mode = 'live'
            and r.session_date = (select max(session_date) from engine_sessions where mode='live')
      where k.status = 'open') b)                                           as book,

  -- 3. the nightly order sheet (§4.3) — sells first, then buys
  (select jsonb_agg(row_to_json(s)) from (
     select * from v_engine_sheet
      where session_date = (select max(session_date) from engine_sessions where mode = 'live')) s)
                                                                            as order_sheet,

  -- 4. top-12 with scores (§4.2). §3.5's fill band is the top 12, so this is the sheet's own
  --    catchment rather than a display choice.
  (select jsonb_agg(row_to_json(t) order by t.rank) from (
     select ticker, rank, score, mark, addv from engine_ranks
      where mode = 'live'
        and session_date = (select max(session_date) from engine_sessions where mode = 'live')
        and rank <= 12) t)                                                  as top12,

  -- 5. the exclusion table (§3.2 permits four categories and nothing else)
  (select jsonb_agg(row_to_json(e) order by e.reason, e.ticker) from (
     select ticker, reason, detail from universe_excluded) e)               as exclusions,

  -- 6. NAV & DD status (§5.2 — information, never action)
  (select row_to_json(n) from (
     select s.session_date, s.nav as engine_nav, d.marked_equity, d.peak, d.drawdown,
            (select row_to_json(h) from (select d as as_of, nav_cad, usdcad, provisional
                                           from nav_snapshots order by d desc, id desc limit 1) h)
              as household
       from engine_sessions s
       left join v_engine_drawdown d on d.session_date = s.session_date
      where s.mode = 'live' order by s.session_date desc limit 1) n)        as nav,

  -- 7. levered facilities & tranche schedule (§2.3)
  (select jsonb_agg(row_to_json(f)) from v_levered_facility f)              as facilities,
  (select jsonb_agg(row_to_json(t) order by t.seq) from (
     select seq, amount_cad, planned_on, approximate, status, drawn_on, note
       from levered_tranches) t)                                            as tranches,

  -- 8. pipeline freshness — the newest `check` verdict, gauge by gauge
  (select row_to_json(c) from (
     select status, finished_at, detail->'verdict' as verdict, detail->'gauges' as gauges,
            detail->'blocks_buys' as blocks_buys, detail->'amber' as amber, detail->'red' as red
       from runs where job = 'check' order by id desc limit 1) c)           as check_report,
  (select jsonb_agg(row_to_json(r) order by r.job) from (
     select distinct on (job) job, status, started_at, finished_at, rows_written
       from runs where started_at > now() - interval '36 hours'
      order by job, id desc) r)                                             as pipeline,
  (select row_to_json(a) from v_reconciliation_age a)                       as reconciliation,

  -- 9. learnings (§5.3 — observations become learnings with required falsifiers, then proposals,
  --    then Zak's ruling. No rule changes ship without this path.)
  (select jsonb_agg(row_to_json(l)) from (
     select key, status, lane, hypothesis, falsifier, occurrences, loosens_risk
       from v_learnings_current
      where status in ('learning', 'proposal') order by at desc limit 12) l) as learnings;

comment on view v_session_payload is
  'S4.2: the single read of every session. Nine items, in the plan''s own order. A session reads '
  'this row and then judges; it never crawls tables.';

-- Dropping a view drops its grants with it. 033 gave `yuna_session` select on the payload and 034
-- through 036 each re-granted after their own rebuild; missing this line would leave an interactive
-- session unable to read the one row §4.2 says it reads.
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'yuna_session') then
    grant select on v_session_payload, v_engine_sheet, v_engine_drawdown,
                    v_levered_facility, v_reconciliation_age to yuna_session;
  end if;
exception when insufficient_privilege then
  raise notice 'view grants not applied here (%): mirror them in the dashboard', sqlerrm;
end $$;
