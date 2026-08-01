-- 030 — the two Durability facts the sweep derives, on the table that stores them.
--
-- §3.1's Durability needs two things per name that no other column carries: how many of the last
-- five years grew revenue, and the worst single reported year's ROIC. Both are name-level facts
-- derived once at extraction; `score` turns them into cross-sectional percentiles.
--
-- These were wired into the extractor in the same change set as the scoring, and the migration was
-- not. The full 2,762-name sweep therefore wrote **zero rows** — every batch insert failed on
-- `column "growth_consistency" of relation "fundamentals" does not exist`, fell back to row-by-row,
-- and failed there too. The heartbeat said amber and the reason was in the errors map, which is the
-- system working; the cost was a wasted sweep. `test_schema.py` now asserts the extractor's column
-- list against the table, so the next one fails in CI in a second instead of in production in an
-- hour.
--
-- `roic_worst_year` is double precision and may legitimately hold ±Infinity: §3.1 top-codes a year
-- with invested capital ≤ 0 when NOPAT > 0 (capital-free compounding) and bottom-codes it when not,
-- and infinities carry that ranking through the percentile step intact.

alter table fundamentals
  add column if not exists growth_consistency   double precision,
  add column if not exists roic_worst_year      double precision,
  add column if not exists roic_years_reported  integer;

comment on column fundamentals.growth_consistency is
  'S3.1 Durability - positive-YoY revenue years out of five, on 0-100. Five comparisons, six fiscal years';
comment on column fundamentals.roic_worst_year is
  'S3.1 Durability - the worst single reported years ROIC. +/-Infinity encodes the capital-free top/bottom coding';
comment on column fundamentals.roic_years_reported is
  'S3.1 - reported ROIC years; under three the name is not bench-eligible';

-- the latest-row view is `select f.*`, frozen at creation — rebuild it so readers can see the new
-- columns (the same trap 027 and 029 both had to close)
drop view if exists v_fundamentals_latest;
create view v_fundamentals_latest as
  select distinct on (f.ticker) f.*
    from fundamentals f
   order by f.ticker, f.filing_date desc;
