-- 032 — the QA batch's data-hygiene items (dev change set 3 and 4, 2026-08-02).
--
-- (3) 427 fundamentals rows carry NO stored filing and are superseded by a newer row that does.
--     They are not point-in-time history — the document that produced their fields is gone, so
--     nothing on them can be re-derived or audited. They are orphans, and they double every
--     ad-hoc join written against `fundamentals` instead of `v_fundamentals_latest`.
--
--     The change set also asked for a uniqueness constraint on `ticker`. **Not applied, and the
--     reason is law.** §4.3 keeps fundamentals forever as "one queryable point-in-time asset,
--     stamped with filing dates"; the table's key is already `(ticker, filing_date)` and the
--     sweep's upsert depends on it. A unique-on-ticker constraint would make each new filing
--     overwrite its predecessor and delete the asset §4.8 calls the honest backtest. The class
--     of bug the constraint was meant to kill is killed instead by the `check` assertion added
--     in this batch: every bench name must resolve to exactly one fundamentals row.
--
-- (4) `_baseline_20260802` was one day of prediction-check scaffolding with RLS disabled. Dropped.

delete from fundamentals f
 where f.raw_doc is null
   and exists (select 1 from fundamentals g
                where g.ticker = f.ticker and g.filing_date > f.filing_date);

drop table if exists public._baseline_20260802;

-- the sweep already relies on this key; stated here so the intended grain is in the record
-- rather than inferred from an upsert clause.
comment on table fundamentals is
  'S4.3 point-in-time asset: one row per (ticker, filing_date), kept forever. Readers use '
  'v_fundamentals_latest - a direct join to this table double-counts every name that has filed twice.';
