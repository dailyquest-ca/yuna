-- 063_the_bill_park.sql — 2026-09-02. The T-bill park variant, §7's own research work order.
--
-- §7's changelog (v1.0, 2026-08-15): "Park is SPY per the cell of record; a T-bill park variant
-- is a research work order, promoted only on evidence." The roadmap files it under "Research,
-- parked but not dead" as one dispatch. This is the data prerequisite for that dispatch, and it
-- has the SAME standing 043 gave SPMO: reference data, inert until a ruling changes §3.7.
--
-- ---------------------------------------------------------------------------------------------
-- WHY AN ETF AND NOT `bill_rates`
--
-- 043 already holds 13-week bill rates, and stopped there on purpose: "the rule that reads it —
-- which tenor, accrual convention, and the holiday fill — is a plan gap for Zak, not a default to
-- be picked in code. Nothing reads this table yet." That gap is still open, and the rates only
-- reach 2016-01-04, so they cannot see 2008 — which is the whole question. §3.8 names it: "The
-- park is SPY: gated-off capital rides the index down (2008 modeled: −37.3% while gated)."
--
-- A bill ETF sidesteps both problems. Its adjusted close IS a total-return series with the accrual
-- convention, expense ratio and spread already inside it — nothing for code to assume — and the
-- vendor carries it from 2007-01-11, so 2008 is on the tape. Measured at the vendor, 2026-09-02:
-- first bar 2007-01-11, close 108.70 against adjusted 80.84, i.e. two decades of distributions
-- reinvested. BIL.US (1-3 month bills) is the purer instrument and starts 2007-05-30; SHV.US
-- (under one year) starts four months earlier and is what the backtest parks in.
--
-- ---------------------------------------------------------------------------------------------
-- WHAT THIS IS NOT
--
-- It is not the production park, and it is not a production recommendation. Two facts decide
-- that and both belong to Zak, not to this file:
--
--   * SHV is US-domiciled. `.claude/rules/investment-tax.md`: "US dividend withholding is
--     treaty-exempt in an RRSP and is not in a TFSA." The engine lives in the TFSA (§2.1). A
--     Canadian-listed USD cash fund (PSU-U.TO, live 2018-02-28; HISU-U.TO, 2022-08-30) is the
--     same accrual with no withholding and no FX, and none of them reaches 2008. So the SIM parks
--     in SHV to measure the mechanism; PRODUCTION, if the evidence promotes the mechanism, picks
--     the vehicle. That is a §3.7 / §8 change and a ruling.
--   * The pre-registered claim is DRAWDOWN. Bills underperform the index over nineteen years, so
--     a CAGR gain from this arm would be the window doing the work, not the park.
--
-- `kind='index'`, exactly as 038/043 classified VOO, SPY, SPMO: a measuring instrument, not a
-- candidate. §3.2's universe is `kind='stock'`, so it can never be ranked, and `desk.PARKED` does
-- not name it, so the live engine never sees it as capital either. The nightly bulk tape carries
-- every US listing, so once backfilled it stays current at no extra vendor cost.

insert into universe (ticker, name, kind, exchange, currency, status, in_l0, note) values
  ('SHV.US', 'iShares Short Treasury Bond ETF', 'index', 'US', 'USD', 'active', false,
   'WO-A24: the §7 T-bill park variant, research only. Live 2007-01-11 at the vendor. UNRULED — '
   '§3.7 park is SPY.US until Zak promotes on evidence; production vehicle is a separate ruling.')
on conflict (ticker) do nothing;
