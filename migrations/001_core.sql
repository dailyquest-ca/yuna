-- Yuna core schema (Phase A): runs · config · universe · prices
create table if not exists runs (
  id bigint generated always as identity primary key,
  job text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running',   -- running | green | amber | red
  dry_run boolean not null default false,
  calls_used integer,
  rows_written integer,
  detail jsonb
);
create index if not exists runs_job_started_idx on runs(job, started_at desc);

create table if not exists config (
  id bigint generated always as identity primary key,
  key text not null,
  value jsonb not null,
  note text,
  set_by text not null default 'yuna',      -- yuna | zak
  set_at timestamptz not null default now()
);
create index if not exists config_key_idx on config(key, set_at desc);

create table if not exists universe (
  ticker text primary key,                  -- EODHD format: AAPL.US, CNQ.TO, GSPC.INDX
  name text,
  kind text not null default 'stock',       -- stock | index | fx
  exchange text,
  currency text,
  status text not null default 'active',    -- active | delisted
  in_l0 boolean not null default false,
  is_holding boolean not null default false,
  added_at timestamptz not null default now(),
  delisted_at date,
  note text
);

create table if not exists prices (
  ticker text not null references universe(ticker),
  d date not null,
  open double precision, high double precision, low double precision,
  close double precision, adj_close double precision,
  volume bigint,
  ingested_at timestamptz not null default now(),
  primary key (ticker, d)
);
create index if not exists prices_d_idx on prices(d);

-- default-deny: RLS on, no policies; jobs connect as postgres via DATABASE_URL
alter table runs enable row level security;
alter table config enable row level security;
alter table universe enable row level security;
alter table prices enable row level security;
