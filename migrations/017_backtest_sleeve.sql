-- 017_backtest_sleeve.sql — the backtest tables now carry two sleeves.

alter table backtest_runs add column if not exists sleeve text not null default 'momentum';
comment on column backtest_runs.sleeve is 'momentum | compounders';

create index if not exists backtest_runs_sleeve_idx on backtest_runs(sleeve, id desc);
