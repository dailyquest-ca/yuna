-- 068_the_payload_answers_for_tonight.sql — 2026-10-07. Two payload items that answered for
-- something other than tonight's sheet, and the drawdown series that measured the wrong number.
--
-- QC review 2026-10-07, findings A10, A9/A20 and A28. All three are §4.2's payload ("the single
-- read of every session"), so every reader inherits them: the brief Zak executes from and every
-- chat session that judges from the one read (§0.4).
--
-- ---------------------------------------------------------------------------------------------
-- 1. THE ORDER SHEET CARRIES ORDERS (A10)
--
-- §4.3: "The nightly sheet is the only source of engine orders." 054 rebuilt the payload and took
-- EVERY ticket of the newest live session into `order_sheet`, where 033-036 had filtered to the
-- live states. So a proposal the re-score withdrew (`sheet.write_tickets` cancels, never deletes),
-- one Zak cancelled in chat, or one already executed printed as a SELL or BUY line under "Order
-- sheet (§4.3)" — tagged with its state, and counted in the "N order(s)" that notify sends him.
-- Production, 2026-08-17: "6 order(s)" with 3 live, one of them "SELL NUE.US qty 32 [cancelled]"
-- whose own note reads "already executed ... do not execute". Learning 57 swept `cancelled` out of
-- the gauges and not out of the payload.
--
-- `order_sheet` now carries the two states a ticket can be acted on in — proposed, approved
-- (§4.3's states before Zak's execution is the event) — and the rest of the session's tickets ride
-- beside it as `not_orders`, so a withdrawal is still legible ("the engine proposed this and then
-- withdrew it" is a fact, sheet.py) without ever being one.
--
-- ---------------------------------------------------------------------------------------------
-- 2. THE CHECK IS TONIGHT'S CHECK (A9, A20)
--
-- `check_report` was the newest `check` row of any session, mode or dry run. Learning 66 named
-- the hazard ("the brief — which reads the newest `check` — would have dropped 'buys held' for a
-- night") and learning 67 the doctrine (a row that is not a fact must not decide); neither reached
-- this read. Now it is the newest LIVE, non-dry check that began after tonight's live session row
-- was written, and that either names that session or never lived to name one:
--
--   * `started_at >= created_at` of the gate's session. `sheet.write_session` restamps
--     `created_at` on every re-score, so a check that began before the sheet it would prove was
--     (re)written has proved a different sheet — including the retry chain's, whose re-score lands
--     between the first chain's check and the second's.
--   * `detail->>'session'` equal to that session, or absent. `gauges.main` writes the session and
--     the verdict together, after the six gauges have run; a row without a session is a check
--     that crashed (Heartbeat's red), died before its heartbeat (report_fail's row) or is still
--     `running`. Those are exactly the rows §4.4 needs the brief to see, because a check that did
--     not finish proved nothing and holds the buys (A20) — so they are kept, bounded by the same
--     timestamp, rather than filtered out with the stale ones.
--   * `coalesce(mode, 'live') = 'live'` and `not dry_run`: a shadow-mode or dry pass is not the
--     live desk's verdict. A row with no mode at all is a crash, and a crash counts.
--
-- None of this is a window: the anchors are the session row and its own write time. The keys the
-- payload carried are kept; `id`, `started_at`, `session`, `mode` and `fatal` are added so a
-- reader can say which run it is and why it has no verdict.
--
-- ---------------------------------------------------------------------------------------------
-- 3. DRAWDOWN IS MEASURED ON ENGINE NAV (A28)
--
-- §5.2: "Pager at −10% engine DD". 054 measured it on `marked_equity`, the positions alone, on the
-- argument that "the sleeve is always in positions" — §2.4 and §3.4 leave no cash. That premise
-- was false the day it was written: §2.4 itself exempts cash "awaiting a same-week engine order",
-- §3.5 says "residue returns to park", and no sheet ever proposes the park buy. Production since
-- 2026-08-28: US$1,458.90 + C$47.33 of TFSA cash sat outside the series, and on 2026-09-16 the brief
-- printed "drawdown −10.0% … ** −10% pager reached **" against an engine-NAV drawdown of −9.89%.
-- An exit whose buy is held (a red check, a freeze) reads about −18% for a night; a gate-off whose
-- proceeds sit in cash reads −100% with every milestone passed.
--
-- `engine_sessions.nav` is engine NAV by the engine's own definition (`sheet.engine_nav` /
-- `desk.derived_engine_nav`: TFSA positions, park included, at the decision close + TFSA cash at
-- the session's USDCAD, in USD) and it is already on every row since 2026-08-19. The peak and the
-- drawdown are now taken over it, with no constant and no window. Sessions sized with no NAV
-- carry no drawdown — "not measurable" is truer than a number off the wrong series — and the
-- three sessions before the derivation (08-14..08-18, including the 08-17 transitional
-- 129,622.50 peak taken mid-liquidation) drop out of the peak with it.
--
-- Known and stated, not fixed here: the ledger records no deposit or withdrawal (A29), so a TFSA
-- contribution would read as a new high and a withdrawal as a fall, at the first anchor after it.
--
-- ---------------------------------------------------------------------------------------------
-- `create or replace` throughout: same columns, same order, same types, so grants and every
-- reader survive; new columns only at the end, new keys only inside the JSON items.

-- ---------- §5.2's series, on engine NAV --------------------------------------------------------
create or replace view v_engine_drawdown as
select session_date,
       marked_equity,
       max(nav) over w                                                   as peak,
       case when nav is not null and max(nav) over w > 0
            then nav / max(nav) over w - 1.0 end                         as drawdown,
       nav
  from engine_sessions
 where mode = 'live' and (nav is not null or marked_equity is not null)
window w as (order by session_date rows between unbounded preceding and current row);

comment on view v_engine_drawdown is
  'S5.2 drawdown milestones are INFORMATION, never action. No mechanical intervention exists at '
  'any level; any intervention is Zak''s explicit ruling in chat. Measured on engine NAV '
  '(engine_sessions.nav: positions + TFSA cash, USD) since migration 068; a session sized with no '
  'NAV has no drawdown.';

comment on column engine_sessions.marked_equity is
  'The engine''s positions, park included, marked at the decision close: sum(qty x close), USD. '
  'NOT engine NAV - TFSA cash is outside it (S3.5 residue, an exit whose buy is held, a gate-off '
  'before the park is bought). Engine NAV is the nav column, and S5.2''s drawdown is measured on it '
  '(migration 068).';

-- ---------- the payload -----------------------------------------------------------------------
create or replace view v_session_payload as
select
  -- 1. gate state & latch (§3.4)
  (select row_to_json(g) from (
     select session_date, gate_on, gate_green, index_close, index_sma, param_digest, mode
       from engine_sessions where mode = 'live'
      order by session_date desc limit 1) g)                                as gate,

  -- 2. current book with ranks (§4.2)
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

  -- 3. the nightly order sheet (§4.3) — sells first, then buys — and ONLY what can be acted on.
  --    proposed and approved are the states before Zak's execution; everything else on the
  --    session is in `not_orders` at the end of this row (068, A10).
  (select jsonb_agg(row_to_json(s)) from (
     select * from v_engine_sheet
      where session_date = (select max(session_date) from engine_sessions where mode = 'live')
        and state in ('proposed', 'approved')) s)                           as order_sheet,

  -- 4. top-12 with scores (§4.2)
  (select jsonb_agg(row_to_json(t) order by t.rank) from (
     select ticker, rank, score, mark, addv from engine_ranks
      where mode = 'live'
        and session_date = (select max(session_date) from engine_sessions where mode = 'live')
        and rank <= 12) t)                                                  as top12,

  -- 5. the exclusion table (§3.2 permits four categories and nothing else)
  (select jsonb_agg(row_to_json(e) order by e.reason, e.ticker) from (
     select ticker, reason, detail from universe_excluded) e)               as exclusions,

  -- 6. NAV & DD status (§5.2 — information, never action). The drawdown is on engine NAV (068,
  --    A28); `nav_source` says where tonight's NAV came from (derived, or an override), USD.
  (select row_to_json(n) from (
     select s.session_date, s.nav as engine_nav, d.marked_equity, d.peak, d.drawdown,
            (select row_to_json(h) from (select d as as_of, nav_cad, usdcad, provisional
                                           from nav_snapshots order by d desc, id desc limit 1) h)
              as household,
            s.detail->'nav_source' as nav_source
       from engine_sessions s
       left join v_engine_drawdown d on d.session_date = s.session_date
      where s.mode = 'live' order by s.session_date desc limit 1) n)        as nav,

  -- 7. levered facilities & tranche schedule (§2.3)
  (select jsonb_agg(row_to_json(f)) from v_levered_facility f)              as facilities,
  (select jsonb_agg(row_to_json(t) order by t.seq) from (
     select seq, amount_cad, planned_on, approximate, status, drawn_on, note
       from levered_tranches) t)                                            as tranches,

  -- 8. pipeline freshness — the check of TONIGHT's live sheet, gauge by gauge (068, A9/A20): the
  --    newest live, non-dry check that began after the session row was (re)written and either
  --    names that session or died before it could name one. A row with no verdict is a check
  --    that did not finish, and the brief holds the buys on it.
  (select row_to_json(c) from (
     select r.status, r.finished_at, r.detail->'verdict' as verdict, r.detail->'gauges' as gauges,
            r.detail->'blocks_buys' as blocks_buys, r.detail->'amber' as amber,
            r.detail->'red' as red,
            r.id, r.started_at, r.detail->>'session' as session,
            coalesce(r.detail->>'mode', 'live') as mode, r.detail->>'fatal' as fatal
       from runs r
       join (select session_date, created_at from engine_sessions where mode = 'live'
              order by session_date desc limit 1) s on r.started_at >= s.created_at
      where r.job = 'check' and not r.dry_run
        and coalesce(r.detail->>'mode', 'live') = 'live'
        and (r.detail->>'session' is null
             or r.detail->>'session' = to_char(s.session_date, 'YYYY-MM-DD'))
      order by r.id desc limit 1) c)                                        as check_report,
  (select jsonb_agg(row_to_json(r) order by r.job) from (
     select distinct on (job) job, status, started_at, finished_at, rows_written
       from runs where started_at > now() - interval '36 hours'
      order by job, id desc) r)                                             as pipeline,
  (select row_to_json(a) from v_reconciliation_age a)                       as reconciliation,

  -- 9. learnings (§5.3)
  (select jsonb_agg(row_to_json(l)) from (
     select key, status, lane, hypothesis, falsifier, occurrences, loosens_risk
       from v_learnings_current
      where status in ('learning', 'proposal') order by at desc limit 12) l) as learnings,

  -- 3b. the rest of tonight's tickets: withdrawn (cancelled, expired) or already done (executed,
  --     reconciled). On the record, never on the sheet (068, A10).
  (select jsonb_agg(row_to_json(w)) from (
     select * from v_engine_sheet
      where session_date = (select max(session_date) from engine_sessions where mode = 'live')
        and state not in ('proposed', 'approved')) w)                       as not_orders;

comment on view v_session_payload is
  'S4.2: the single read of every session. The plan''s nine items in its own order, plus '
  'not_orders (068): tonight''s tickets that are not orders. order_sheet carries only proposed and '
  'approved tickets; check_report is the newest live, non-dry check of tonight''s session. A session '
  'reads this row and then judges; it never crawls tables.';
