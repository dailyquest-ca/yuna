-- 076_one_copy_of_the_law.sql — 2026-10-08. The law has one copy, and this is where every reader
-- gets it. Plan v1.2 §0.7; §0.4.
--
-- Zak promoted v1.1 on 2026-10-06 into the claude.ai project's copy of the plan. That copy was
-- stale: it predated five rulings the repo's plan carried and the code cites (the 2026-09-02
-- drawdown record, the 2026-09-13 operating constants and census floors, the 2026-09-14 §4.3
-- amendment and screen band), and the Routines read it as the law. Two writable copies with nothing
-- tying them together, and the one a chat can reach is the one that drifted. Zak, 2026-10-07: "we
-- need to synchronize them somehow and find a way to force them to stay synchronized."
--
-- So the law has one copy: `docs/yuna_plan.md` on `main`, and beside it `docs/routines-contract.md`,
-- which tells the Routines how to read the rest. A merge to `main` is a promotion (§0.3 still says
-- who promotes). The `law` job (.github/workflows/law.yml, src/law.py) publishes each changed
-- document here, and every session and Routine reads `v_law`. Nothing else is a copy.
--
--   law            append-only: the full text of every published version, its SHA-256, the plan's
--                  version and the commit. A published law is never edited or deleted (§0.6).
--   v_law          the newest row per document.
--   v_session_payload  gains `law` (its last column; every earlier column unchanged): the plan's
--                  version and hash, which the brief prints in its header. A Routine that quotes
--                  another version is visibly reading another copy.
--
-- Readers: `yuna_session` reads both through 020's default grant on new tables and views; the Data
-- API's public roles get nothing (066). No role but the owner can write, and the owner cannot edit.

create table if not exists law (
  id            bigint generated always as identity primary key,
  document      text not null check (document in ('plan', 'routines-contract')),
  version       text,                       -- the plan's header version (v1.2); null for the contract
  sha256        text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  git_commit    text not null,
  body          text not null,
  published_at  timestamptz not null default now()
);
alter table law enable row level security;

comment on table law is
  'S0.7: every published version of the law, append-only. Written by the law job on each merge to '
  'main that changes docs/yuna_plan.md or docs/routines-contract.md; read through v_law (076).';

create or replace function yuna_law_is_append_only() returns trigger
language plpgsql set search_path = public as $$
begin
  raise exception 'law is append-only — % refused', TG_OP
    using hint = 'a new version of the law is a new row, published by the law job from main (S0.7)';
end $$;

drop trigger if exists law_append_only on law;
create trigger law_append_only before update or delete on law
  for each row execute function yuna_law_is_append_only();
drop trigger if exists law_never_truncated on law;
create trigger law_never_truncated before truncate on law
  for each statement execute function yuna_law_is_append_only();

create or replace view v_law as
select distinct on (document) document, version, sha256, git_commit, body, published_at
  from law
 order by document, id desc;

comment on view v_law is
  'S0.4/S0.7: the law as it stands — the newest published row per document. Sessions and Routines '
  'read the plan and the routines contract here, never from a project file or a paste (076).';

do $$
declare r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke all on law, v_law from %I', r);
    end if;
  end loop;
  if exists (select 1 from pg_roles where rolname = 'yuna_session') then
    grant select on law, v_law to yuna_session;
  end if;
end $$;
revoke execute on function yuna_law_is_append_only() from public;

-- ---- the payload names the law ------------------------------------------------------------------
-- 068's view, unchanged, with `law` appended as its last column.
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

  -- 5. the exclusion table (§3.2 permits four categories and nothing else), each row with the
  --    excluded line's own last bar — §3.2 keeps "the line still printing" (068, A43)
  (select jsonb_agg(row_to_json(e) order by e.reason, e.ticker) from (
     select x.ticker, x.reason, x.detail, lb.d as last_bar
       from universe_excluded x
       left join lateral (select d from prices where ticker = x.ticker
                           order by d desc limit 1) lb on true) e)          as exclusions,

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
        and state not in ('proposed', 'approved')) w)                       as not_orders,

  -- 10. the law the night was read under (§0.4, §0.7; 076): the plan's published version and the
  --     first twelve hex digits of its SHA-256, so every brief names the law it obeyed
  (select row_to_json(l) from (
     select version, left(sha256, 12) as hash, git_commit, published_at
       from v_law where document = 'plan') l)                              as law;

comment on view v_session_payload is
  'S4.2: the single read of every session. The plan''s nine items in its own order, plus '
  'not_orders (068): tonight''s tickets that are not orders, and law (076): the plan version and '
  'hash the night was read under. order_sheet carries only proposed and approved tickets; '
  'check_report is the newest live, non-dry check of tonight''s session. A session reads this row '
  'and then judges; it never crawls tables.';
