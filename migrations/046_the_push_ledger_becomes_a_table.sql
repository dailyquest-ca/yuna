-- 046 · the push ledger becomes a table (WO-A3 §2)
--
-- The capture audit walks every episode on the census — completed pushes, failed breakouts,
-- unresolved races — and until now kept only aggregates. The push study writes the whole ledger
-- down, one row per episode, with every candidate gate's value AT the breakout (bars <= b only,
-- look-ahead-safe by construction) and the outcome labels that answer the exit question without
-- running an engine backtest: what trail width did each push actually need, and which of the
-- candidate exits (3xATR trail, 10/20-session MA, own 100-session MA) would have survived to
-- the +50% mark. Gates are then measured with SQL against this table, and a gate that shows no
-- lift dies at the cost of zero trials — §2.5(d)'s burden is the row of feature columns below,
-- logged in the work order.

create table if not exists push_study (
  id bigserial primary key,
  studied_at timestamptz not null default now(),
  window_start date not null,
  window_end date not null,
  ticker text not null,
  b date not null,                      -- the breakout session (the signal day)
  outcome text not null check (outcome in ('push', 'failed', 'unresolved')),
  e date,                               -- resolution session; null while unresolved
  level double precision not null,      -- the breakout close the race measures from
  gain double precision,                -- push: gain at completion; failed: best tease reached
  sessions_to_resolve integer,

  -- candidate gates, all computed on bars at or before b
  slope_ann_90 double precision,        -- annualized exponential regression slope (Clenow)
  r2_90 double precision,               -- the fit's R² — how clean the trend is
  slope_r2_90 double precision,         -- the product: how fast times how clean
  up_share_126 double precision,        -- share of up days (frog-in-the-pan smoothness)
  ret_vol_90 double precision,          -- daily return stdev (unannualized)
  max_move_90 double precision,         -- largest |daily move| (MAX/lottery proxy)
  atr_frac_20 double precision,         -- ATR(20)/price — the trend_vol arm's key
  addv_50 double precision,             -- 50-session median dollar volume
  raw_close double precision,
  prior_gain_126 double precision,
  prior_gain_252 double precision,
  dist_50dma double precision,
  sessions_since_push integer,          -- own bars since this name's prior completed push
  regime_on boolean,                    -- S&P close above its 200-session SMA at b (Clenow gate)

  -- outcome-conditional exit labels, pushes only: null on failed/unresolved rows
  needed_trail_frac double precision,   -- deepest pullback from the running high, as a fraction
  needed_trail_atr double precision,    -- the same pullback in multiples of ATR(20) at b
  survives_trail_3atr boolean,          -- reached +50% before closing 3xATR(b) under the high
  survives_ma10 boolean,                -- ... before closing under the 10-session MA
  survives_ma20 boolean,
  survives_ma100 boolean,
  unique (window_start, window_end, ticker, b)
);

alter table push_study enable row level security;
drop trigger if exists guard_push_study on push_study;
create trigger guard_push_study before insert or update or delete on push_study
  for each row execute function yuna_jobs_only();
