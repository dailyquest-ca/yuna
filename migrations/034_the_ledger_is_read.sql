-- 034 — the rulings ledger becomes readable, and the schema the 2026-08-07 work orders need.
--
-- One defect underlies WO-1, WO-3 and WO-7, and it is embarrassingly small: **verdicts are written
-- the way a person writes them and read the way a programmer guessed they would be.** The ledger
-- holds `PASS`, `FAIL`, `ESCALATE`, and
-- `QUARANTINE — owner-cash (§3.1), not entry-eligible; PASS/FAIL deferred to R5`; every reader in
-- the system asks `verdict in ('pass','fail')`. Sixty-eight rulings were therefore invisible: the
-- payload called 44 already-ruled names unruled, `score` armed a quarantined name, and every
-- growth-derived candidate sat behind a sign-off the ledger had already granted.
--
-- A verdict is prose because Yuna writes it in a session, and it should stay prose — the memo is
-- the point. So the canonicalisation lives here, once, as a function, and every reader goes through
-- it. §4.3: the database remembers, and it now remembers in a shape jobs can act on.
--
-- Four things:
--   1. `yuna_verdict(text)` — the verdict's leading word, lowercased. One home for the rule.
--   2. `v_rulings_latest` / `v_rulings_latest_c2` — latest-ruling-wins per ticker, reversals
--      excluded, as a view rather than as a lateral repeated in five queries.
--   3. `v_session_payload` rebuilt (WO-3, obs 113): unruled means *no live c2 ruling*, and the
--      ruled names at the line ride along with their verdict and ruling id so R1 can cite them.
--   4. The columns WO-2 and WO-8 write: the statement FX restatement, and the marker that stops
--      a name with no vendor coverage from being re-fetched forever.

-- ---------- 1. the canonical verdict ----------
-- The leading word decides. "QUARANTINE — owner-cash …; PASS/FAIL deferred to R5" is a quarantine,
-- not a pass — which is exactly why a naive substring scan is the wrong tool and the first token is
-- the right one. Anything whose first word is not a known verdict falls back to a precedence scan,
-- so a differently-phrased ruling degrades to the most restrictive reading rather than to silence.
create or replace function yuna_verdict(v text) returns text
language sql immutable as $$
  select case
    when v is null then null
    when lower(coalesce(substring(btrim(v) from '^[A-Za-z]+'), '')) in
         ('pass','fail','quarantine','release','escalate','hold','exit','convert','void',
          'keep','reversal')
      then lower(substring(btrim(v) from '^[A-Za-z]+'))
    when v ilike '%quarantine%' then 'quarantine'
    when v ilike '%escalate%'   then 'escalate'
    when v ilike '%fail%'       then 'fail'
    when v ilike '%pass%'       then 'pass'
    else lower(btrim(v))
  end
$$;
comment on function yuna_verdict(text) is
  '§3.1 rulings law: the canonical verdict token of a written verdict. Verdicts are prose because '
  'Yuna writes them in a session; jobs read them through this function and nowhere else. '
  'RELEASE is the §3.1 owner-cash quarantine''s only exit — the quarantine is a finding about the '
  'balance sheet and a later PASS is a finding about the business, so PASS never lifts it.';

-- ---------- 2. latest-ruling-wins, as a view ----------
-- §3.1: "Rulings bind later sessions — a logged verdict is overturned only by the cooldown escape
-- clause or a logged reversal citing new evidence." So the live ruling is the newest row that
-- nothing has reversed, per (ticker, kind), and a later QUARANTINE or FAIL overrides an earlier
-- PASS by being later. Ordered by `at` then `id`, so two rulings inside one session still resolve.
--
-- `decides` is the other half of the law. §5.6: "when Yuna's confidence is genuinely low, she asks
-- Zak instead of ruling — a question in the brief, logged either way." An ESCALATE is therefore a
-- logged question, not a verdict: the name stays unruled and keeps its place on the docket, which
-- is precisely the state TSM.US has been in since 2026-08-06.
--
-- A pure annulment is not a verdict either. §3.1's reversal "cites new evidence", and a reversal
-- that states one — `PASS — reversing ruling 47, the float is on the balance sheet` — canonicalises
-- to `pass` and stands as the new word. One that only withdraws — `REVERSAL — wrong name` — takes
-- its target out of the ledger and then steps aside, leaving whatever ruled before it in force.
create or replace view v_rulings_latest as
  select distinct on (r.ticker, r.kind)
         r.ticker, r.kind, r.id as ruling_id, r.at, r.verdict,
         yuna_verdict(r.verdict) as verdict_canon,
         yuna_verdict(r.verdict) <> 'escalate' as decides,
         r.blind, r.confidence, r.cooldown_until, r.ccn_at_ruling, r.session_id
    from rulings r
   where not exists (select 1 from rulings x where x.reverses = r.id)
     and yuna_verdict(r.verdict) is distinct from 'reversal'
   order by r.ticker, r.kind, r.at desc, r.id desc;

comment on view v_rulings_latest is
  '§3.1 latest-ruling-wins: the newest un-reversed ruling per (ticker, kind), with the verdict '
  'canonicalised. Jobs read this, never the raw table — a written verdict is prose. `decides` is '
  'false for an ESCALATE, which §5.6 makes a question for Zak rather than a ruling by Yuna.';

create or replace view v_rulings_latest_c2 as
  select * from v_rulings_latest where kind = 'c2';

comment on view v_rulings_latest_c2 is
  '§3.1 Gate C2, latest-wins. `verdict_canon` is pass | fail | quarantine | escalate | …';

-- ---------- 3. the columns the new readers write ----------
-- WO-2 (§3.0): a foreign issuer is compounder-eligible only when FCF and market cap are expressed
-- in one currency, financials converted at fiscal-period-end FX. The rate and its `as_of` live with
-- the row, because a restated number nobody can audit is worse than a number nobody uses.
alter table fundamentals
  add column if not exists statement_fx_rate  double precision,
  add column if not exists statement_fx_as_of date,
  add column if not exists converted_to_usd   boolean not null default false;

comment on column fundamentals.statement_fx_rate is
  '§3.0 — market-cap-currency units per statement-currency unit at the LATEST statement''s fiscal '
  'period end. Each period converts at its own period-end rate; this is the newest one, stored so '
  'the restatement can be audited from the row.';
comment on column fundamentals.statement_fx_as_of is
  '§4.1 — the date of the FX bar used for statement_fx_rate (the last bar at or before period end)';
comment on column fundamentals.converted_to_usd is
  '§3.0 — true when this row''s monetary fields were restated out of the statement currency into '
  'the currency the vendor''s market cap uses (USD for every US listing). `quote_ok` is the '
  'guarantee that the two are now in one currency; this says an FX conversion is what got them there.';

-- WO-8: a name the vendor has no statements for is not a gap to retry forever — it is a fact.
alter table universe
  add column if not exists no_vendor_data    boolean not null default false,
  add column if not exists no_vendor_data_at date;
comment on column universe.no_vendor_data is
  '§4.1 — the vendor served no fiscal years for this name (SPACs, trusts, preferreds). The coverage '
  'sweep skips it instead of spending ten units a week learning the same thing; a full sweep rechecks.';

-- A view's projection is frozen at creation (learnings #7), so the three columns above are
-- invisible to every reader until this runs. test_schema.py pins exactly this.
drop view if exists v_fundamentals_latest;
create view v_fundamentals_latest as
  select distinct on (f.ticker) f.*
    from fundamentals f
   order by f.ticker, f.filing_date desc;

-- ---------- 4. the one-read payload, corrected (WO-3, obs 113) ----------
-- The old definition predates a populated ledger and asked for `verdict in ('pass','fail')`, which
-- matches nothing the desk actually writes. It also drew its population from the hurdle alone, so a
-- name the job armed but whose hurdle sat further away never reached the docket at all.
--
-- Unruled at the line now means: at or within 10% of the hurdle **or armed tonight**, and no live
-- c2 ruling. Ruled names in the same population ride alongside with their verdict and ruling id, so
-- R1 can cite the ruling instead of re-deriving it — §5.6's one read, doing its job.
-- `create or replace` cannot insert a column in the middle of a view's projection, and the two new
-- fields belong next to the docket they qualify rather than bolted on the end. Dropped and rebuilt;
-- the grant below is re-applied for the same reason.
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
    grant select on v_session_payload, v_rulings_latest, v_rulings_latest_c2 to yuna_session;
  end if;
exception when insufficient_privilege then
  raise notice 'view grants not applied here (%): mirror them in the dashboard', sqlerrm;
end $$;

-- ---------- 5. config the new code reads (learnings #21 — a rule stored is a rule read) ----------
insert into config (key, value, note, set_by)
select * from (values
 ('earnings_calendar_stale_days', '110'::jsonb,
  '§3.3 / WO-4 — a name whose latest known report date is older than this has plausibly missed a '
  'quarter, so the blackout wall cannot vouch for it and the arming stage blocks it. Absence of a '
  'date is not absence of an event.', 'yuna'),
 ('earnings_refresh_batch', '50'::jsonb,
  '§4.1 — names per per-ticker earnings-calendar request in the nightly targeted refresh', 'yuna'),
 ('earnings_refresh_max_calls', '12'::jsonb,
  '§4.1 — ceiling on those requests per night; the weekly full-universe sweep is unchanged', 'yuna'),
 ('fundamentals_missing_cap', '300'::jsonb,
  '§4.1 / WO-8 — names with no fundamentals row filled per weekly sweep, after the staleness pass',
  'yuna'),
 ('api_quota_ceiling', '0.70'::jsonb,
  '§4.1 — "meter and stop at ~70% quota". The sweep truncates itself at this fraction of the '
  'daily budget rather than running the tank dry.', 'yuna')
) as v(key, value, note, set_by)
where not exists (select 1 from config c where c.key = v.key);

insert into observations (kind, ticker, body, detail)
select 'note', null,
       'Rulings became readable (migration 034): verdicts are canonicalised by yuna_verdict() and '
       'resolved latest-wins by v_rulings_latest. Every reader asked for lower-case pass/fail and '
       'the ledger holds PASS, FAIL, ESCALATE and QUARANTINE — 68 rulings were invisible, which is '
       'why 44 ruled names sat on the unruled docket and a quarantined name armed an entry.',
       '{"migration":"034_the_ledger_is_read","work_orders":["WO-1","WO-3","WO-7"]}'::jsonb
 where not exists (select 1 from observations where body like 'Rulings became readable%');
