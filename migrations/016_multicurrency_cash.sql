-- 016_multicurrency_cash.sql — cash is held per currency, not as one CAD number.
--
-- I collapsed the TFSA to 117,323.27 CAD. It is actually 7,933.12 CAD *and* 78,085.62 USD,
-- and those move differently: the USD sleeve is repriced by FX every day. Storing the
-- broker's converted total froze that, so NAV would have been blind to the currency it is
-- mostly denominated in.
--
-- §2.0 says balances are truth and prices are the extrapolation. Cash per currency is now the
-- anchored truth, equities mark from prices, and `total_value` becomes the reconciliation
-- check it always should have been rather than the NAV input.
--
-- Leverage is CAD always — Zak, 2026-07-31 — so `drawn` and `credit_limit` need no currency.

alter table balances add column if not exists cash_cad double precision;
alter table balances add column if not exists cash_usd double precision;

comment on column balances.cash      is 'DEPRECATED — the broker''s converted total; use cash_cad + cash_usd';
comment on column balances.cash_cad  is 'settled CAD cash in the account';
comment on column balances.cash_usd  is 'settled USD cash in the account — repriced by FX daily';
comment on column balances.drawn     is 'facility balance drawn, always CAD';
comment on column balances.total_value is
  'the account''s stated total at as_of — a reconciliation check against cash + marked equities, not the NAV input';

-- transactions already carry currency and fx_rate; make the intent explicit
comment on column transactions.currency is 'the trade''s own currency — USD for US listings, CAD for TSX';
comment on column transactions.fx_rate  is 'to CAD at trade date; 1.0 for CAD trades';

insert into balances (account, as_of, cash_cad, cash_usd, cash, drawn, credit_limit, total_value, source) values
 ('TFSA',  date '2026-07-31',  7933.12, 78085.62, 117323.27, null,    null,     176583.89, 'zak'),
 ('RRSP',  date '2026-07-31',   616.76, 15791.99,  22747.65, null,    null,      22747.65, 'zak'),
 ('NONREG',date '2026-07-31',      0.00,     0.00,      0.00, null,    null,          null, 'zak'),
 ('LOC',   date '2026-07-31',      null,     null,      null, 7980.40, 75200.00,      null, 'zak');

-- D10 resolved (§6 Step 5, and the TODO's last open decision)
insert into config (key, value, note, set_by) values
 ('levered_etf', '"VXC.TO"',
  'Vanguard FTSE Global All Cap ex Canada — CAD-listed and unhedged per §2.5. Chosen over VFV '
  'on the §2.2 theme cap: 31.8% technology against VFV''s 39.1%, so it reaches 15.1% of NAV '
  'before the 35% entry cap binds where VFV stops at 12.3%. Also lower vol (10.63 vs 11.80) '
  'and higher 3y Sharpe (1.61 vs 1.50). Zak ruled 2026-07-31.', 'zak');

insert into observations (kind, ticker, body, detail) values
 ('note', 'VXC.TO',
  'D10 RESOLVED: VXC is the levered-layer ETF. VFV''s original objection was correlation with '
  'the AI-cluster book, which Phase 0 retires; the deciding argument is the §2.2 theme cap, '
  'which sees the levered layer and binds on VFV''s 39.1% technology weight sooner.',
  '{"chosen":"VXC.TO","rejected":["VFV.TO","VUN.TO"],"tech_weight":{"VXC":0.3176,"VFV":0.3913},'
  '"cap_binds_at_pct_nav":{"VXC":0.151,"VFV":0.123},"decided_by":"zak","date":"2026-07-31"}'),
 ('learning', null,
  'Cash must be stored per currency in a book that is mostly USD. Collapsing to the broker''s '
  'converted total hides FX movement between reconciliations, in the currency most of the '
  'money sits in.',
  '{"source":"zak","migration":"016"}');
