-- 008_balances.sql — Phase 0 capital anchor. Source: Zak's Wealthsimple screenshots,
-- 2026-07-31 11:58–11:59 PT. Balances are truth; prices are the extrapolation (§2.0).
--
-- RECONCILIATION FLAG, unresolved and deliberately not smoothed over:
--   TFSA total                              176,321.93 CAD
--   less available to trade (cash)           94,796.02 CAD
--   implied TFSA equities                    81,525.91 CAD
--   our book's six TFSA names at 07-30 close 58,314.68 CAD  (41,617.53 USD x 1.4012)
--   unexplained                              23,211.23 CAD
-- Either the TFSA holds a position the handoff's "seven rows, confirmed complete" missed,
-- or part of that cash is unsettled and the split is not what it looks like. Recorded, not
-- absorbed. NAV is computed from stated account totals, so the gap does not corrupt it —
-- only the per-position weights are affected until Zak resolves it.

alter table balances add column if not exists total_value double precision;
comment on column balances.total_value is
  'the account''s stated total at as_of — the reconciliation anchor NAV is built from';

insert into balances (account, as_of, cash, drawn, credit_limit, total_value, source) values
 ('TFSA',  date '2026-07-31', 94796.02, null,    null,     176321.93, 'zak'),
 ('RRSP',  date '2026-07-31', 22747.65, null,    null,      22747.65, 'zak'),
 ('NONREG',date '2026-07-31', null,     null,    null,      null,     'zak'),
 ('LOC',   date '2026-07-31', null,     7980.40, 75200.00,  null,     'zak');

insert into observations (kind, ticker, body, detail) values
 ('breach', null,
  'Phase 0 capital anchor: TFSA equities implied by the broker (81,525.91 CAD) exceed the '
  'six TFSA names in our book (58,314.68 CAD) by 23,211.23 CAD. Flagged, not absorbed.',
  '{"tfsa_total":176321.93,"tfsa_cash":94796.02,"tfsa_equities_implied":81525.91,'
  '"book_tfsa_equities_cad":58314.68,"gap_cad":23211.23,"usdcad":1.4012,'
  '"as_of":"2026-07-31","source":"wealthsimple screenshots"}'),
 ('note', null,
  'HELOC and callable margin were not captured — treated as zero drawn. Undrawn credit is '
  'capacity, not debt, so NAV is unaffected; §2.5 utilization headroom is unknown for both.',
  '{"facilities_missing":["HELOC","MARGIN"],"loc_utilization":0.1061}');
