-- 015_backtest.sql — Phase E. Where the formulas stop being a reasoned prior.

create table if not exists backtest_runs (
  id bigint generated always as identity primary key,
  ran_at timestamptz not null default now(),
  label text,
  params jsonb,
  start_date date, end_date date, trading_days integer,
  start_nav double precision, end_nav double precision,
  total_return double precision, cagr double precision,
  max_drawdown double precision, max_dd_date date,
  trades integer, wins integer, win_rate double precision,
  avg_win double precision, avg_loss double precision, expectancy double precision,
  avg_exposure double precision, avg_hold_days double precision,
  benchmark_return double precision, benchmark_cagr double precision,
  stats jsonb
);

create table if not exists backtest_trades (
  id bigint generated always as identity primary key,
  run_id bigint not null references backtest_runs(id) on delete cascade,
  ticker text not null,
  entry_date date, entry_price double precision, qty double precision,
  exit_date date, exit_price double precision,
  mcn double precision, pivot double precision, initial_stop double precision,
  size_pct double precision, pyramid_steps integer,
  pnl_cad double precision, pnl_pct double precision, bars_held integer,
  max_favorable double precision, max_adverse double precision,
  exit_reason text
);
create index if not exists backtest_trades_run_idx on backtest_trades(run_id, entry_date);

create table if not exists backtest_equity (
  run_id bigint not null references backtest_runs(id) on delete cascade,
  d date not null,
  nav double precision, exposure double precision,
  positions integer, gate text, benchmark double precision,
  primary key (run_id, d)
);

alter table backtest_runs   enable row level security;
alter table backtest_trades enable row level security;
alter table backtest_equity enable row level security;

do $$
declare t text;
begin
  foreach t in array array['backtest_runs','backtest_trades','backtest_equity'] loop
    execute format('drop trigger if exists %I on %I', 'guard_'||t, t);
    execute format('create trigger %I before insert or update or delete on %I for each row execute function yuna_jobs_only()', 'guard_'||t, t);
  end loop;
end $$;
