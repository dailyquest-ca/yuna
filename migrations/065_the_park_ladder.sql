-- 065_the_park_ladder.sql — 2026-09-03. Eight parks for WO-A29, research only.
--
-- Zak, 2026-09-03: "Run this comparison against the likeliest 5-10 other park options." A24 showed
-- the park decides the gated-off episodes and bills are the floor of the ladder: the park with no
-- market exposure. WO-A29 (docs/wo-a29-the-park-ladder.md) asks whether any instrument with SOME
-- exposure beats bills in the seasons the sleeve is off without giving the protection back in
-- another. The claim and the predictions are in the work order; this is its data prerequisite.
--
-- Same standing as 043's SPY and SPMO and 063's SHV: `kind='index'`, `in_l0=false` — reference
-- data, never candidates, unseen by §3.2's universe and by `desk.PARKED`. Every one has vendor
-- bars before the first decision session 2007-01-12 (TLT, IEF, LQD from 2002; AGG 2003; TIP 2003;
-- GLD 2004; XLU and XLP from 1998); coverage is verified in the store before any arm dispatches,
-- so A24's park-start confound cannot recur. UNRULED — §3.7's park is SPY.US until Zak promotes on
-- evidence, and the production vehicle is a separate ruling (A24, "What this is not").
insert into universe (ticker, name, kind, exchange, currency, status, in_l0, note) values
  ('TLT.US', 'iShares 20+ Year Treasury Bond ETF',           'index', 'US', 'USD', 'active', false, 'WO-A29 park ladder rung: long Treasuries. Research only, UNRULED.'),
  ('IEF.US', 'iShares 7-10 Year Treasury Bond ETF',          'index', 'US', 'USD', 'active', false, 'WO-A29 park ladder rung: intermediate Treasuries. Research only, UNRULED.'),
  ('AGG.US', 'iShares Core U.S. Aggregate Bond ETF',         'index', 'US', 'USD', 'active', false, 'WO-A29 park ladder rung: aggregate bonds. Research only, UNRULED.'),
  ('LQD.US', 'iShares iBoxx $ Investment Grade Corporate Bond ETF', 'index', 'US', 'USD', 'active', false, 'WO-A29 park ladder rung: investment-grade credit. Research only, UNRULED.'),
  ('TIP.US', 'iShares TIPS Bond ETF',                        'index', 'US', 'USD', 'active', false, 'WO-A29 park ladder rung: inflation-protected Treasuries. Research only, UNRULED.'),
  ('GLD.US', 'SPDR Gold Shares',                             'index', 'US', 'USD', 'active', false, 'WO-A29 park ladder rung: gold. Research only, UNRULED.'),
  ('XLU.US', 'Utilities Select Sector SPDR Fund',            'index', 'US', 'USD', 'active', false, 'WO-A29 park ladder rung: utilities. Research only, UNRULED.'),
  ('XLP.US', 'Consumer Staples Select Sector SPDR Fund',     'index', 'US', 'USD', 'active', false, 'WO-A29 park ladder rung: consumer staples. Research only, UNRULED.')
on conflict (ticker) do nothing;
