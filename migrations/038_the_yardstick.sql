-- 038_the_yardstick.sql — the benchmark the backtest is measured against (ruled 2026-08-10).
--
-- Zak's ruling: "we are really asking, are we better than S&P 500 - VOO. That's the thing we are
-- versing over time." Three problems with what we had, all fixed by one row:
--
--   * `backtest_equity.benchmark` was NULL in all 5,988 rows across all 12 runs. The code read
--     SPY.US, which is not in `prices`, and the guard quietly wrote NULL every day. No stored run
--     could draw a side-by-side curve.
--   * `GSPC.INDX` is a PRICE index. Comparing our total-return NAV against it hands us 1.5-2%/yr
--     for free. VOO's `adj_close` is distribution-adjusted, so the yardstick includes dividends.
--   * `GSPC.INDX` only reaches back to 2023-08-01 — it, not the stock bars, is what capped every
--     backtest at two years. The bars go to 2016-08-05 for 2,050 names.
--
-- kind='index', deliberately: `backtest.load` and the L0 census both filter `kind='stock'`, so the
-- yardstick can never be ranked, entered or held. A benchmark that can enter the book is a bug.

insert into universe (ticker, name, kind, exchange, currency, is_holding, note) values
 ('VOO.US', 'Vanguard S&P 500 ETF', 'index', 'US', 'USD', false,
  'the benchmark (ruled 2026-08-10) — adj_close is total return; kind=index keeps it untradeable')
on conflict (ticker) do nothing;

insert into config (key, value, note, set_by)
select 'benchmark', '"VOO.US"'::jsonb,
       'Ruled 2026-08-10: the S&P 500 held as VOO is the comparison, measured on adjusted closes '
       'so dividends count. The named-investor comparison is dropped, not parked — no holdings '
       'history exists to reconstruct it from, and a 13F clone would answer a different question.',
       'zak'
 where not exists (select 1 from config where key = 'benchmark');

-- §3.2 caps the momentum sleeve at "3-4 names". The number was a literal in two codebases; it is
-- a config row now, so the backtest and the nightly cannot disagree about it by accident.
insert into config (key, value, note, set_by)
select 'momentum_max_names', '4'::jsonb,
       '§3.2 — the momentum sleeve holds 3-4 names. Read by the nightly and by the backtest.',
       'yuna'
 where not exists (select 1 from config where key = 'momentum_max_names');
