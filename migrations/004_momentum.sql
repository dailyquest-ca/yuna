-- Phase B: momentum stack. universe gains census fields; candidates/queue/gate_state arrive.
alter table universe add column if not exists sector text;
alter table universe add column if not exists industry text;
alter table universe add column if not exists market_cap_usd double precision;

create table if not exists candidates (
  ticker text primary key references universe(ticker),
  rank integer,
  mcn double precision,
  mq double precision,          -- momentum quality percentile
  setup double precision,       -- setup proximity percentile
  grp double precision,         -- industry group strength percentile
  m2 boolean,
  m4 boolean,                   -- null until Phase D
  state text,                   -- BUY | WAIT
  pivot double precision,
  base_len integer,
  base_depth double precision,
  base_low double precision,    -- final-contraction low
  stop_suggest double precision,
  last_close double precision,
  computed_at timestamptz not null default now()
);

create table if not exists queue (
  ticker text primary key,
  rank integer,
  source text,                  -- holding | momentum
  state text,
  trigger_price double precision,
  limit_price double precision,
  stop_suggest double precision,
  proximity double precision,   -- |price-trigger|/price
  mcn double precision,
  note text,
  computed_at timestamptz not null default now()
);

create table if not exists gate_state (
  id bigint generated always as identity primary key,
  week_end date not null,
  state text not null,          -- ON | OFF
  spx_close double precision,
  sma30 double precision,
  sma30_4w_ago double precision,
  flipped boolean not null default false,
  computed_at timestamptz not null default now()
);

alter table candidates enable row level security;
alter table queue enable row level security;
alter table gate_state enable row level security;
