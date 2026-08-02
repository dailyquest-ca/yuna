-- 031 — the plain-cash rulings (2026-08-02) and the company we keep.
--
-- FCF is now net of stock-based compensation everywhere (glossary), so the extraction stores the
-- reported figure and its two big non-owner components alongside — the §5.5 owner-FCF note becomes
-- three numbers on the row instead of a suspicion in prose. `sbc_missing` is the §3.3 stamp for
-- periods where the vendor reports no SBC and the figure fell back to reported.
--
-- Bench rows gain the disclosure shares, the §3.1 owner-cash quarantine flag (session-ruled at R5,
-- like c2_status), and `corroborated_by` — which reference investors hold the name, written weekly
-- by the rank from holder records already stored.

alter table fundamentals
  add column if not exists fcf_ttm_reported double precision,
  add column if not exists sbc_ttm          double precision,
  add column if not exists dwc_ttm          double precision,
  add column if not exists sbc_missing      boolean;

alter table bench
  add column if not exists fcf_ttm_reported double precision,
  add column if not exists sbc_share        double precision,
  add column if not exists dwc_share        double precision,
  add column if not exists owner_fcf_suspect boolean not null default false,
  add column if not exists corroborated_by  text[];

comment on column bench.owner_fcf_suspect is
  'S3.1 owner-cash quarantine - ruled at R5 when reported FCF is materially customer float; scored, never ticketed';
comment on column bench.corroborated_by is
  'S3.1 the company we keep - which reference investors appear among the stored top holders; written weekly';

-- the reference investors are config, so a change is a logged row, never code
insert into config(key, value, note, set_by)
select 'named_investors',
       '["Fundsmith","Akre","Polen","TCI Fund","Pershing","WCM Invest","Giverny"]'::jsonb,
       'S3.1 the company we keep - substring-matched against stored top-holder names', 'zak'
where not exists (select 1 from config where key = 'named_investors');

-- views are frozen at creation; both rebuilt so every reader sees the new columns
drop view if exists v_fundamentals_latest;
create view v_fundamentals_latest as
  select distinct on (f.ticker) f.*
    from fundamentals f
   order by f.ticker, f.filing_date desc;

drop view if exists v_bench;
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
         round((100::double precision * b.sbc_share)::numeric, 0)     as sbc_pct_of_fcf,
         round((100::double precision * b.dwc_share)::numeric, 0)     as float_pct_of_fcf,
         b.owner_fcf_suspect, b.corroborated_by,
         b.c1_pass, b.c2_status, b.approved, b.data_confidence, b.serial_acquirer
    from bench b
    join universe u on u.ticker = b.ticker
   order by b.rank;
