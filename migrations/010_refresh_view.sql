-- 010_refresh_view.sql — a view defined with `select *` freezes its column list at creation.
-- 009 added primary_ticker and quote_ok to `fundamentals`; v_fundamentals_latest never saw
-- them, so score.py died on "column f.quote_ok does not exist". Any migration that adds a
-- column to `fundamentals` must recreate this view in the same file.

drop view if exists v_fundamentals_latest;
create view v_fundamentals_latest as
select distinct on (ticker) * from fundamentals order by ticker, filing_date desc;
