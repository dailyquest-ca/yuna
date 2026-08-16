-- 040_a_way_back_in.sql — §3.2 knows one way into a name: a fresh valid base. Hypothesis X1 buys
-- back on a new N-session closing high instead, so a trade now has to say which door it came
-- through or the bucket cannot be judged on its own P&L. Defaults to 'base', which is every row
-- written before this migration and every row a law-v0 run will ever write.

alter table backtest_trades add column if not exists entry_kind text not null default 'base';
