-- 028 — Durability replaces Size on the bench row, and the engine says where it came from.
--
-- §3.1, 2026-08-01: the CCN's third component is Durability — growth consistency and the worst
-- reported year's ROIC floor, equal weight, the blend percentiled across L0. Size is repealed: the
-- tilt was double-counted (the funnel's cohort split already carries the small-cap hunt) and a
-- component that rewards smallness hardest turned the bench into a small-cap cyclical screen.
--
-- `engine_provenance` is not decoration. §3.1 requires growth-derived engines to be "marked on the
-- bench row and every memo that cites it", and the trial's C2 memos said "engine measured,
-- cross-check agrees" about names whose engines were growth-derived. A template that reads a flag
-- cannot make that mistake; free text can and did.

alter table bench
  add column if not exists durability          double precision,
  add column if not exists engine_provenance   text,
  add column if not exists growth_consistency  double precision,
  add column if not exists roic_floor_pct      double precision,
  add column if not exists roic_years          integer,
  add column if not exists engine_used         double precision;

comment on column bench.durability is
  'S3.1 - equal blend of growth consistency and the ROIC floor, percentiled across L0';
comment on column bench.engine_provenance is
  'S3.1 - measured | growth-derived. Growth-derived carries S3.3 guardrails and must be named on every memo';
comment on column bench.engine_used is
  'S3.1 - the engine value actually scored and underwritten, whichever side of the identity it came from';

-- Size is gone from the law, so it goes from the row. Nothing reads it, and §4.3's bloat rule is
-- explicit: if no decision reads a field, we do not store it. `v_bench` is what Zak browses in
-- Studio, so it is rebuilt in the same breath — dropping the column without it would either fail or
-- leave the human view showing a repealed component.
drop view if exists v_bench;
alter table bench drop column if exists size_score;

create view v_bench as
  select b.rank, b.ticker, u.name, b.cohort,
         round(b.ccn::numeric, 1)                      as ccn,
         round(b.engine::numeric, 0)                   as engine,
         b.engine_provenance,
         round(b.cash_conv::numeric, 0)                as cash_conv,
         round(b.durability::numeric, 0)               as durability,
         round(b.growth_consistency::numeric, 0)       as growth_years_pct,
         round(b.roic_floor_pct::numeric, 0)           as roic_floor,
         round(b.hurdle_price::numeric, 2)             as hurdle,
         round(b.last_close::numeric, 2)               as last_close,
         round((100::double precision * b.gap_to_hurdle)::numeric, 1) as above_hurdle_pct,
         b.gap_to_hurdle <= 0::double precision        as buyable,
         b.c1_pass, b.c2_status, b.approved, b.data_confidence, b.serial_acquirer
    from bench b
    join universe u on u.ticker = b.ticker
   order by b.rank;

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'bench_engine_provenance_legislated') then
    alter table bench add constraint bench_engine_provenance_legislated
      check (engine_provenance is null or engine_provenance in ('measured', 'growth-derived'));
  end if;
end $$;
