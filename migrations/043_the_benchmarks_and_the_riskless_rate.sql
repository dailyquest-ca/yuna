-- 043_the_benchmarks_and_the_riskless_rate.sql — 2026-08-12. WO-P.
--
-- Two data prerequisites the backtest programme needs and the database does not hold. They have
-- **different standing**, and the difference is the point of this comment.
--
-- ---------------------------------------------------------------------------------------------
-- 1. THE RISKLESS RATE — a measured distortion, no ruling yet
--
-- `backtest.py` holds the sleeve ~90% in cash (see the note at src/backtest.py:225 — "the sleeve
-- is ~90% in cash"), and models that cash at **zero**. Over 2016-2026 the 13-week bill paid
-- between -0.05% and 5.52%, so a decade of runs compared against VOO has been charging the
-- strategy the full opportunity cost of idle capital and crediting it nothing. That is not a
-- small correction and it moves every number the programme reports.
--
-- **The plan does not name a riskless rate.** `docs/yuna_plan.md` contains no T-bill, no
-- coupon-equivalent, no cash-accrual rule, and `config` has no rate key. So the *series* is
-- ingested here as fact, and the *rule that reads it* — which tenor, accrual convention, and the
-- holiday fill below — is a plan gap for Zak, not a default to be picked in code. Nothing reads
-- this table yet.
--
-- Coverage, measured: 2,651 rows of 13WK across 2016-01-04..2026-08-10. Against VOO's 2,512
-- trading days from 2016-08-12 there are **19 days with no bill rate** — bond-market holidays
-- when equities traded (Columbus Day 2016-10-10 is the first) plus 2026-08-11, where the bill
-- series lags the tape by a session. Carrying the previous rate forward is the obvious treatment
-- and it is still a rule; it belongs in the plan before a job depends on it.
--
-- ---------------------------------------------------------------------------------------------
-- 2. THE BENCHMARK INSTRUMENTS — SPY is settled, SPMO and MTUM are not
--
-- `docs/backtest-plan-2026-08-10.md` ruling #2 is explicit: "The benchmark is the S&P 500, held
-- as VOO. That is the thing we are versing over time — One yardstick. Everything reports against
-- it." `config.benchmark` is `VOO.US`, singular. Read against that:
--
--   * **SPY conforms.** The ruling names the *index* as the benchmark and VOO as the vehicle.
--     VOO's history starts 2010-09; SPY's starts 1993. For the WO-P2 window SPY is the same
--     yardstick carried by a vehicle that existed — not a second opinion.
--
--   * **SPMO and MTUM do not, yet.** A momentum ETF as a "could we just buy this instead"
--     reference is a genuinely useful question, and it is *a second yardstick* — which is the
--     thing ruling #2 closed. They are ingested here because the price history is inert and
--     costs nothing to hold, **but no report may cite them until Zak rules.** If he declines,
--     the rows stay as unused reference data and nothing else has to change.
--
-- All three are `kind='index'` because that is how VOO is already classified: measuring
-- instruments, not candidates. §3.2's universe is `kind='stock'`, so none of them can leak into
-- the tradeable set, and `universe_excluded` is not needed for them.

insert into universe (ticker, name, kind, exchange, currency, status, in_l0, note) values
  ('SPY.US',  'SPDR S&P 500 ETF Trust',          'index', 'US', 'USD', 'active', false,
   'WO-P: the ruling-#2 yardstick carried pre-2010, where VOO did not exist. Live 1993-01.'),
  ('SPMO.US', 'Invesco S&P 500 Momentum ETF',   'index', 'US', 'USD', 'active', false,
   'WO-P: proposed buy-vs-build reference. UNRULED — a second yardstick against ruling #2.'),
  ('MTUM.US', 'iShares MSCI USA Momentum Factor ETF', 'index', 'US', 'USD', 'active', false,
   'WO-P: proposed diagnostic column. UNRULED, and cuttable. Live 2013-04.')
on conflict (ticker) do nothing;

-- One row per (date, tenor) so the 4WK/8WK/17WK/26WK/52WK tenors can land later without a
-- migration; only 13WK is loaded. `coupon_equivalent` is the investment-rate basis and
-- `discount_rate` is the discount basis — they are not the same number and they diverge as
-- rates rise (2026-08-10: 3.74 discount, 3.83 coupon-equivalent). Both are stored so that a
-- reader who grabs the wrong one is wrong loudly rather than quietly off by the basis.
create table if not exists bill_rates (
  d                  date not null,
  tenor              text not null,
  discount_rate      double precision,
  coupon_equivalent  double precision,
  ingested_at        timestamptz not null default now(),
  primary key (d, tenor)
);

comment on table bill_rates is
  'US Treasury bill rates by tenor, as published (vendor: EODHD UST bill rates). Reference data: '
  'no job reads it yet. The cash-accrual rule that will read it is a plan gap — see 043.';

-- Units are the trap here. The vendor publishes percent per annum and the values are stored
-- verbatim, unconverted: 3.83 means 3.83%, not 383% and not 0.0383. A consumer compounding
-- `rate/252` without dividing by 100 is off by a factor of 100 and will not throw.
comment on column bill_rates.discount_rate is
  'Discount basis, PERCENT per annum as published (3.74 = 3.74%). Not the investment rate.';
comment on column bill_rates.coupon_equivalent is
  'Coupon-equivalent / investment basis, PERCENT per annum as published (3.83 = 3.83%).';

create index if not exists bill_rates_tenor_d on bill_rates (tenor, d);

alter table bill_rates enable row level security;
drop trigger if exists guard_bill_rates on bill_rates;
create trigger guard_bill_rates before insert or update or delete on bill_rates
  for each row execute function yuna_jobs_only();
