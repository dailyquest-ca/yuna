-- 011_statement_currency.sql — the currency detector, built on the field that tells the truth.
--
-- 009 trusted General.CurrencyCode. For TSM that field says USD, CountryISO says US, and the
-- statements are in TWD — the give-away being a P/FCF of 1.63x. The vendor makes the same
-- mistake we did: its own PriceSalesTTM divides a USD market cap by TWD revenue.
--
-- Two fields do not lie:
--   Financials.*.currency_symbol   — 'TWD' on every TSM statement
--   General.PrimaryTicker          — '2330.TW', i.e. this listing is a depositary receipt
--
-- A name failing either check gets no hurdle and no bench seat. Its ROIC and cash conversion
-- are currency-neutral ratios and stay in the percentile pool; only the price-based half of
-- the compounder pipeline is unavailable. FX pairs and ADR ratios would fix it properly —
-- deliberately deferred rather than approximated.

alter table fundamentals add column if not exists statement_currency text;
comment on column fundamentals.statement_currency is
  'currency_symbol off the statements — the reporting currency, unlike General.CurrencyCode';

-- unknown until the next sweep reads currency_symbol; null, not a guess
update fundamentals set quote_ok = null;

drop view if exists v_fundamentals_latest;
create view v_fundamentals_latest as
select distinct on (ticker) * from fundamentals order by ticker, filing_date desc;
