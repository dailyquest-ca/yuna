-- 027 — the view has to see the columns 026 added.
--
-- `v_fundamentals_latest` was written with an explicit column list, and Postgres freezes a view's
-- projection at creation. So `cap_as_of`, `cap_close`, `effective_shares` and `raw_doc` existed on
-- the table and were invisible to every reader — score, verify, rank, the sessions, all of which go
-- through the view rather than the table. A column nothing can read is a column that does not exist.
--
-- Rebuilt as `f.*` so the projection is the table's, and `tests/integration/test_schema.py` now
-- asserts the view exposes every base column — this class of drift is silent, survives green runs,
-- and is exactly what the integration harness is for.

drop view if exists v_fundamentals_latest;

create view v_fundamentals_latest as
  select distinct on (f.ticker) f.*
    from fundamentals f
   order by f.ticker, f.filing_date desc;
