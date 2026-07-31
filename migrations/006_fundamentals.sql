-- 006_fundamentals.sql — Phase D: the point-in-time fundamentals asset.
-- One row per (ticker, filing_date). Rows are never edited, so the table becomes the
-- honest backtest history the plan says we cannot buy (§4.8 backtest honesty).

create table if not exists fundamentals (
  ticker text not null references universe(ticker),
  filing_date date not null,             -- §3.3: as of filing, never fiscal period end
  period_end date,
  fetched_at timestamptz not null default now(),

  -- identity
  currency text,
  sector text,
  industry text,
  gic_sector text,
  gic_industry text,
  ipo_date date,
  is_financial boolean not null default false,   -- banks/insurers excluded in C1 v1
  market_cap double precision,
  shares_out double precision,
  fiscal_years integer,

  -- compounding engine (§3.1)
  ebit_3y double precision,
  tax_rate double precision,
  nopat_3y double precision,
  invested_capital double precision,
  invested_capital_ex_gw double precision,
  roic double precision,
  roic_ex_gw double precision,
  reinvest_rate double precision,
  engine double precision,                       -- ROIC x reinvestment
  revenue_cagr_3y double precision,              -- engine reliability cross-check
  engine_agrees boolean,                         -- |engine - revenue CAGR| within tolerance

  -- cash conversion
  fcf_3y double precision,
  ni_3y double precision,
  cash_conversion double precision,
  fcf_ttm double precision,

  -- Gate C1 inputs
  fcf_positive boolean,
  net_issuance_3y double precision,
  net_debt double precision,
  ebitda double precision,
  net_debt_ebitda double precision,
  debt_grows_faster boolean,
  goodwill double precision,
  goodwill_jump boolean,                         -- routes a serial-acquirer flag to the C2 memo
  c1_pass boolean,
  c1_fail_reason text,

  -- hurdle inputs (§3.1)
  pfcf_current double precision,
  pfcf_median double precision,
  pfcf_obs integer,

  -- M4 (§3.2)
  eps_yoy_latest double precision,
  eps_yoy_prev double precision,
  m4_pass boolean,

  data_confidence text,                          -- full | 2of3 | flagged
  raw jsonb,                                     -- the statement rows the numbers came from
  primary key (ticker, filing_date)
);
create index if not exists fundamentals_ticker_idx on fundamentals(ticker, filing_date desc);

alter table fundamentals enable row level security;

drop trigger if exists guard_fundamentals on fundamentals;
create trigger guard_fundamentals before insert or update or delete on fundamentals
  for each row execute function yuna_jobs_only();

-- latest filing per name — what every score reads
create or replace view v_fundamentals_latest as
select distinct on (ticker) * from fundamentals order by ticker, filing_date desc;
