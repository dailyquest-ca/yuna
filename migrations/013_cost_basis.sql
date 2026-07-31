-- 013_cost_basis.sql — cost basis, theses and invalidators from Zak's trade journal
-- (Trade_Journal.xlsx, Holdings sheet, as of 2026-07-28 close), plus the 2026-07-31 balances.
--
-- The journal's own NAV at 2026-07-28 is 200,503.20 CAD against the machine's 200,754.38 at
-- 2026-07-31 — 0.13% apart, two independent constructions. That is the three-eyes check.
--
-- RECONCILIATION GAP RESOLVED. The 23,211.23 CAD flagged in 008 was an artifact of the
-- 11:58 screenshot: available-to-trade was depressed by the portfolio-line-of-credit
-- collateral hold ("some of your trading balance may be held to secure your portfolio line
-- of credit"). The 14:15 screenshot gives TFSA 176,583.89 with 117,323.27 available, so
-- implied equities are 59,260.62 against our six names at 58,347.78 — a 912.84 gap, which is
-- one trading day of drift (our bars are the 07-30 close). The book is complete at seven rows.
--
-- ISRG IS THE ONE OPEN ITEM. The journal has 11 shares at 345.00 opened 2026-07-21; the
-- broker shows 26 on 2026-07-30. Fifteen shares were bought after the journal's last entry
-- and their fill price is unknown, so avg_cost stays null rather than carry a blended number
-- built on a guess.

alter table book add column if not exists note text;

update book set avg_cost = 146.530, opened_at = date '2026-05-07',
  thesis = 'Leading AI data-centre networking for hyperscalers; Ethernet displacing InfiniBand in AI clusters.',
  invalidators = '["Two consecutive earnings prints below modeled trajectory","Hyperscaler shift away from Ethernet"]'::jsonb
  where ticker = 'ANET.US' and status = 'open';

update book set avg_cost = 342.585, opened_at = date '2026-01-16',
  thesis = 'Mega-cap AI/cloud diversifier; custom silicon (XPUs) + networking + VMware software cash machine.',
  invalidators = '["Hyperscaler AI capex cuts","Share loss to NVDA or custom internal silicon"]'::jsonb
  where ticker = 'AVGO.US' and status = 'open';

update book set opened_at = date '2026-07-21',
  thesis = 'Robotic-surgery monopoly at 31x forward after a 43% de-rate; procedures +16%, Ion +36%, dV5 cycle.',
  invalidators = '["Procedure guidance CUT rather than maintained","ACA-subsidy expiry visibly hitting volumes","Share loss to Hugo or Ottava"]'::jsonb,
  note = 'journal has 11 sh @ 345.00; broker shows 26 on 2026-07-30 — 15 sh acquired after the journal cutoff, fill price unknown'
  where ticker = 'ISRG.US' and status = 'open';

update book set avg_cost = 203.240, opened_at = date '2026-05-04',
  thesis = 'Data-centre AI infrastructure leader; CUDA moat; Rubin cycle.',
  invalidators = '["Hyperscaler capex revisions down more than 15%","Custom-silicon share shift accelerating"]'::jsonb
  where ticker = 'NVDA.US' and status = 'open';

update book set avg_cost = 183.090, opened_at = date '2024-05-01',
  thesis = 'Dominant advanced-node foundry; every AI chip runs through it; pricing power.',
  invalidators = '["Taiwan geopolitical strike (accepted, unhedgeable)","N2 execution failure"]'::jsonb
  where ticker = 'TSM.US' and status = 'open';

update book set avg_cost = 332.500, opened_at = date '2026-06-03',
  thesis = 'Data-centre power and cooling pure-play; AI thermal-density tailwind. Dust tail only.',
  invalidators = '["Hyperscaler capex pause","Liquid-cooling share loss"]'::jsonb
  where ticker = 'VRT.US' and status = 'open';

update book set avg_cost = 56.200, opened_at = date '2026-07-07',
  thesis = '26-year dividend-growth streak (~20% CAGR), ~4.4% yield, long-life low-decline assets, ~30% AFF payout, breakevens US$40-45. ITA 20(1)(c)-clean CAD common shares for the leverage sleeve.',
  invalidators = '["Dividend growth streak breaks","Sustained WTI below US$45 uncovered by downstream/gas"]'::jsonb
  where ticker = 'CNQ.TO' and status = 'open';

-- 2026-07-31 balances. The LOC is the only facility carrying a balance; HELOC and callable
-- margin do not exist today, so §2.5 headroom is the LOC's alone.
insert into balances (account, as_of, cash, drawn, credit_limit, total_value, source) values
 ('TFSA',  date '2026-07-31', 117323.27, null,    null,     176583.89, 'zak'),
 ('HELOC', date '2026-07-31', null,      0,       0,        null,      'zak'),
 ('MARGIN',date '2026-07-31', null,      0,       0,        null,      'zak');

insert into observations (kind, ticker, body, detail) values
 ('note', null,
  'Reconciliation gap from 008 RESOLVED: available-to-trade was depressed by the LOC collateral '
  'hold at 11:58. At 14:15 the TFSA implies 59,260.62 of equities against 58,347.78 in the book — '
  '912.84 apart, one trading day of drift. Seven rows confirmed complete.',
  '{"gap_cad":912.84,"was":23211.23,"cause":"portfolio LOC collateral hold on available-to-trade"}'),
 ('note', 'ISRG.US',
  'Cost basis incomplete: 11 sh @ 345.00 from the journal, 26 held per the broker. The 15-share '
  'difference was bought after the journal cutoff and needs its fill price from Zak.',
  '{"known_qty":11,"known_cost":345.00,"held_qty":26,"missing_qty":15}');
