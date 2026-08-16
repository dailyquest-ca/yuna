-- 039_the_calendar_reaches_back.sql — ten years of report dates, from a document we already hold.
--
-- §3.3's blackout is "no new entries and no adds within 5 trading days of a scheduled report."
-- The `earnings` ledger is fed by the nightly calendar sweep, which reaches CAL_BACK = 400 days,
-- so its earliest row is 2025-06-27. Over the ten-year backtest window the blackout was therefore
-- unenforceable for roughly eight of ten years — and the conformance table said 99.9% covered,
-- because it was finding *a* date (one years in the future) rather than the next print.
--
-- The dates were already in the database. `fundamentals.raw_doc->'Earnings'->'History'` carries a
-- reportDate per quarter for 2,949 tickers, averaging 98.8 quarters each — the same field M4's
-- point-in-time EPS reads. This lifts them into `earnings` so the blackout can see what M4 sees.
-- No vendor call.
--
-- Idempotent: `on conflict do nothing` leaves every swept row exactly as the calendar wrote it.
-- The vendor's own calendar stays authoritative for anything it has covered; this only fills the
-- years behind it.

insert into earnings (ticker, report_date, report_when, eps_est, eps_actual)
select f.ticker,
       (h.value->>'reportDate')::date,
       nullif(h.value->>'beforeAfterMarket', ''),
       (h.value->>'epsEstimate')::double precision,
       (h.value->>'epsActual')::double precision
  from v_fundamentals_latest f
  cross join lateral jsonb_each(coalesce(f.raw_doc->'Earnings'->'History', '{}'::jsonb)) h
 where h.value->>'reportDate' is not null
   and (h.value->>'reportDate')::date between '2015-01-01' and current_date + 400
   and exists (select 1 from universe u where u.ticker = f.ticker)
on conflict (ticker, report_date) do nothing;
