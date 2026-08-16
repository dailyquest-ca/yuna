-- 045 · a test symbol is not a stock, and one series is one series
--
-- Found by the first capture audit (run 57, 2026-08-13), which is the audit doing its job: the
-- top "missed push" in the whole nine-year window was ZVZZT.US at +2,555% in one day. ZVZZT is
-- NASDAQ's test symbol — its prints are exchange plumbing, not a market. It sits in `universe`
-- as an active stock, so every backtest's census has been offering the engine a fake security
-- (never traded, by luck of the ranking).
--
-- The same audit surfaced two duplicate series, both verified against the tape before this file
-- was written (the numbers are measurements, not recollections):
--
--   * LAZR_old.US and LAZRQ.US share 1,660 identical (close, volume) bars — one series under
--     two symbols. LAZRQ is the longer line (1,769 bars, carries the tail); keep it.
--   * TRCH.US is the pre-merger line of MMAT.US — 1,213 of 1,229 overlapping daily returns are
--     identical to 1e-9; the adjusted levels differ by the merger's exchange ratio, which is why
--     a (close, volume) comparison finds nothing while the returns are the same returns. MMAT
--     carries the full 2,094-bar history; keep it.
--
-- A duplicated series counts the same momentum twice in the audit's denominator and lets the
-- engine hold the same move under two names at once (runs 43/49/50 traded the MMAT/TRCH pair
-- five times). Same remedy as 041: exclusion, not deletion — the bars stay, the reason is on
-- the record, and one deleted row readmits a name if the vendor data is re-verified.

insert into universe_excluded (ticker, reason, detail) values
  ('ZVZZT.US',    'not_a_security',    'NASDAQ test symbol; prints are exchange test traffic — a one-day +2,555% "push" on 2019-11-13'),
  ('LAZR_old.US', 'duplicate_listing', 'same series as LAZRQ.US (1,660 identical close+volume bars); LAZRQ is the longer line, keep it'),
  ('TRCH.US',     'duplicate_listing', 'pre-merger line of MMAT.US (1,213 of 1,229 overlapping daily returns identical); MMAT carries the full history, keep it')
on conflict (ticker) do nothing;
