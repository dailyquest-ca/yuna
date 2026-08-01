-- 026 — the inputs the 2026-08-01 law needs, and the ledger it legislated.
--
-- §3.1 freezes the hurdle's share count at the filing: effective shares = vendor cap / the close on
-- the cap's `as_of` date. That is three facts about the filing (the cap, the date it was stamped,
-- the close on that date) and the count they imply, and none of them existed. Without them the
-- hurdle is a function of tonight's quote and decays every night — `verify`'s two-way mismatches
-- were exactly that signature.
--
-- §2.6 gives higher-yield US compounders the RRSP, and defines higher as a trailing-12-month
-- dividend yield >= 1% AT TICKET TIME. That is deliberately not a stored score: the numerator is a
-- rolling twelve months of payments and the denominator is the ticket's own price, so it belongs in
-- a view over the dividend ledger, evaluated when the ticket is written. The vendor serves a
-- *forward* annual rate, which is a different number and not the one the plan names.
--
-- §4.1 moves the raw filing document into the database. `raw` already holds the derived extract the
-- formulas read (quarterly FCF series, eight years of statement lines); `raw_doc` holds what the
-- vendor actually served, so the point-in-time archive is queryable rather than a blob in git.
--
-- §4.3 legislates `armed` as an append ledger stamped with run ids. It was truncated every night,
-- which is why the only way to notice that armed rows contradicted the queue was to look on the
-- right day.

-- ---------- fundamentals: the frozen share count, and the yield ----------
alter table fundamentals
  add column if not exists cap_as_of         date,
  add column if not exists cap_close         double precision,
  add column if not exists effective_shares  double precision,
  add column if not exists raw_doc           jsonb;

comment on column fundamentals.cap_as_of is
  '§3.1 — the date the vendor stamps the market cap; the fetch date when it gives none';
comment on column fundamentals.effective_shares is
  '§3.1 — vendor cap / close on cap_as_of, frozen with the filing. The hurdle moves on filings, never on quotes';
-- ---------- the trailing-12-month dividend, per share, from the ledger ----------
-- Two feeds write `corporate_actions`: the nightly bulk file keys the amount as `dividend`, the
-- per-ticker history used by the backfill keys it as `value`. Both are read here so the ledger has
-- one meaning regardless of which job wrote the row. Amounts are unadjusted cash per share as paid.
create or replace view v_dividend_ttm as
  select ticker,
         sum(coalesce((detail->>'dividend')::double precision,
                      (detail->>'value')::double precision))          as dps_ttm,
         count(*)                                                      as payments_ttm,
         max(d)                                                        as last_ex_date
  from corporate_actions
  where kind = 'dividend'
    and d > current_date - interval '12 months'
    and coalesce(detail->>'dividend', detail->>'value') is not null
  group by ticker;

-- ---------- armed: an append ledger, not a nightly overwrite ----------
create index if not exists armed_run_idx on armed(run_id desc, id);
create index if not exists armed_ticker_idx on armed(ticker, computed_at desc);

-- What every session should read: the most recent night's arming, and nothing older pretending
-- to be current. The table keeps the history; the view keeps the sessions honest.
create or replace view v_armed_latest as
  select a.* from armed a
  where a.run_id = (select max(run_id) from armed);

-- ---------- earnings: telling "already reported" apart from "no data" ----------
-- The calendar is pulled forward-only, so a July reporter simply vanishes and the system cannot say
-- whether it reported or whether the row is missing. The sync now also pulls a backward window, and
-- this view answers the question per ticker from the ledger itself — one source of truth, never a
-- denormalized column that can drift from the rows under it.
create or replace view v_earnings_state as
  select ticker,
         max(report_date) filter (where report_date <= current_date)  as last_reported_date,
         min(report_date) filter (where report_date >= current_date)  as next_report_date,
         max(report_when) filter (where report_date >= current_date)  as next_report_when
  from earnings
  group by ticker;
