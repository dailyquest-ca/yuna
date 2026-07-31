-- 012_quote_ok.sql — resolve quote_ok from data already on disk, no second sweep.
--
-- The sweep's `%s is false` update never ran: the batch statement failed, flush fell back to
-- row-by-row, and the fallback path had no quote_ok step. The detector logic was right; the
-- plumbing dropped it. It now lives in Python, where a boolean is a boolean.
--
-- A name is priceable only if its statements are in the currency its shares quote in, and
-- only if this listing is the primary one. Null statement currency fails too — unknown is
-- not the same as fine.

update fundamentals f
   set quote_ok = (
         f.statement_currency is not null
         and u.currency is not null
         and f.statement_currency = u.currency
         and (f.primary_ticker is null
              or split_part(f.primary_ticker, '.', 1) = split_part(f.ticker, '.', 1))
       )
  from universe u
 where u.ticker = f.ticker;
