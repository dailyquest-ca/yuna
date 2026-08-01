-- 029 — what a ticket must say, and the price the add bands measure from.
--
-- §5.1, new law: "every entry ticket names its **account, currency (FX estimate printed), theme,
-- and risk in C$ and % of NAV**". Risk is CAD-converted BEFORE the percentage. The trial printed
-- DELL's risk as 0.16% of NAV; the truth was 0.24%, because 9 shares x $37.56 of stop distance is
-- US$338 and it was divided by a CAD NAV. A unit mix, in the one number that says how much a bad
-- trade costs.
--
-- §3.1, new law: averaging-down bands measure from the ENTRY FILL, not the hurdle. `avg_cost`
-- cannot stand in — it moves with every add, so the second add would measure from a base the first
-- add shifted. The fill price is written once, at entry, and never again.

alter table book
  add column if not exists entry_fill double precision;

comment on column book.entry_fill is
  'S3.1 - the fill price of the ENTRY order. Add bands measure from this, never from avg_cost, which moves with each add';

alter table tickets
  add column if not exists currency      text,
  add column if not exists fx_estimate   double precision,
  add column if not exists risk_cad      double precision,
  add column if not exists risk_pct_nav  double precision;

alter table armed
  add column if not exists currency      text,
  add column if not exists fx_estimate   double precision,
  add column if not exists risk_cad      double precision,
  add column if not exists risk_pct_nav  double precision;

comment on column tickets.risk_pct_nav is
  'S5.1 - risk_cad / NAV. Converted to CAD first: a USD risk over a CAD NAV understates by the FX rate';

-- Backfill the fill price for positions that predate the column, from the entry transaction where
-- there is one and the opening average cost otherwise. Stated rather than silent: for a position
-- with adds already taken, avg_cost is an approximation of the fill, and the row says so.
update book b
   set entry_fill = coalesce(
         (select t.price from transactions t
           where t.ticker = b.ticker and t.side = 'buy'
           order by t.trade_date, t.id limit 1),
         b.avg_cost)
 where b.entry_fill is null and b.status = 'open';
