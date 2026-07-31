-- 009_quote_currency.sql — the hurdle can only be computed in one currency.
--
-- EODHD reports statements in the issuer's reporting currency but market cap in USD. TSM
-- files in TWD, Karooooo in ZAR, Wise in GBP — divide one by the other and P/FCF comes out
-- at 1.4x, the name looks absurdly cheap, and the hurdle lands three times above the price.
-- KARO, TSM and WSE all appeared on the "at or below hurdle" list for exactly this reason.
--
-- v1 fix: a name whose reporting currency differs from its quote currency gets no hurdle and
-- is flagged, rather than a confident wrong one. primary_ticker is captured now so the next
-- sweep can also catch ADRs, where shares outstanding are ordinary shares but the price is
-- per depositary receipt. Both are solvable with FX pairs and ADR ratios — later, deliberately.

alter table fundamentals add column if not exists primary_ticker text;
alter table fundamentals add column if not exists quote_ok boolean;

comment on column fundamentals.quote_ok is
  'reporting currency matches the listing''s quote currency — false means no honest P/FCF';

-- backfill from what we already hold, so this needs no second API sweep
update fundamentals f
   set quote_ok = (f.currency is not null and u.currency is not null and f.currency = u.currency)
  from universe u
 where u.ticker = f.ticker;

insert into config (key,value,note,set_by) values
 ('engine_agreement_tolerance','0.05',
  'absolute floor on |engine - revenue CAGR| before the engine is distrusted; 10pp let a 7% '
  'grower underwrite at 16%','yuna');
