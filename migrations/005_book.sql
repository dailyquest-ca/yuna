-- 005_book.sql — Phase C: the money tables, the guards, the human views.
-- Plan §4.3. Append tables are ledgers (rows never edited); overwrite tables are current state.

-- ---------- accounts & balances (§2.0 NAV, §2.6 placement, §2.5 facilities) ----------
create table if not exists accounts (
  code text primary key,
  label text not null,
  kind text not null,                    -- registered | taxable | facility
  currency text not null default 'CAD',
  callable boolean not null default false,
  max_utilization double precision,      -- §2.5: 0.50 for callable, null = full
  funds text,                            -- etf_only | single_or_etf
  note text
);

create table if not exists balances (    -- append: Sunday reconciliation anchors truth (§2.0)
  id bigint generated always as identity primary key,
  account text not null references accounts(code),
  as_of date not null,
  cash double precision,                 -- accounts: settled cash
  drawn double precision,                -- facilities: borrowed
  credit_limit double precision,         -- facilities: total limit
  source text not null default 'zak',    -- zak | job
  recorded_at timestamptz not null default now()
);
create index if not exists balances_acct_idx on balances(account, as_of desc);

-- ---------- bench (L1-C, overwrite) ----------
create table if not exists bench (
  ticker text primary key references universe(ticker),
  rank integer,
  cohort text,                           -- small | large (§3.1 $10B boundary)
  ccn double precision,
  engine double precision,               -- L0 percentile
  cash_conv double precision,            -- L0 percentile
  size_score double precision,           -- L0 percentile (inverted log mcap)
  engine_raw double precision,           -- raw: ROIC x reinvestment
  cash_conv_raw double precision,        -- raw: 3y FCF / 3y NI
  roic double precision,
  reinvest_rate double precision,
  c1_pass boolean,
  c1_fail_reason text,
  c2_status text not null default 'pending',   -- pending | pass | fail
  c2_confidence text,
  c2_memo text,
  hurdle_price double precision,
  fcf_yield double precision,
  engine_growth double precision,
  derating_drag double precision,
  fair_multiple double precision,
  last_close double precision,
  gap_to_hurdle double precision,        -- (price - hurdle)/hurdle; <=0 means buyable
  approved boolean not null default false,
  approved_at timestamptz,
  months_outside_top60 integer not null default 0,
  data_confidence text,                  -- full | 2of3 | flagged
  serial_acquirer boolean not null default false,
  computed_at timestamptz not null default now()
);

-- ---------- book (L3, overwrite) ----------
create table if not exists book (
  id bigint generated always as identity primary key,
  ticker text not null references universe(ticker),
  account text not null references accounts(code),
  sleeve text not null,                  -- compounders | momentum | levered
  lot text not null default 'core',      -- core | tactical (§3.3 crash protocol)
  qty double precision not null,
  avg_cost double precision not null,    -- in the position's own currency
  currency text not null default 'USD',
  opened_at date,
  stop double precision,
  stop_limit double precision,
  highest_close double precision,        -- trail memory
  trail_mode text,                       -- initial | breakeven | trail10 | trail5
  pyramid_step integer not null default 0,   -- 0..3; 3 = full size
  pyramid_stalled_since date,
  target_qty double precision,
  thesis text,
  invalidators jsonb,                    -- §3.1: 3-4 named events
  entry_snapshot jsonb,                  -- raw component values at purchase (§3.1 absolute exits)
  status text not null default 'open',   -- open | closed
  closed_at date,
  updated_at timestamptz not null default now()
);
create index if not exists book_open_idx on book(status, ticker);

-- ---------- tickets (append) ----------
create table if not exists tickets (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  ticker text not null,
  account text references accounts(code),
  sleeve text,
  action text not null,                  -- buy | add | sell | stop_move | cancel
  reason text,                           -- trigger | hurdle | stop | trail | gap | blackout | phase0 | swap
  order_type text,                       -- stop_limit | market | limit
  trigger_price double precision,
  limit_price double precision,
  qty double precision,
  stop double precision,
  stop_limit_price double precision,
  state text not null default 'proposed',  -- proposed | approved | provisional | confirmed | cancelled | expired
  brief_id bigint,
  note text,
  updated_at timestamptz not null default now()
);
create index if not exists tickets_state_idx on tickets(state, created_at desc);

-- ---------- transactions (append) ----------
create table if not exists transactions (
  id bigint generated always as identity primary key,
  ticket_id bigint references tickets(id),
  ticker text not null,
  account text not null references accounts(code),
  side text not null,                    -- buy | sell
  qty double precision not null,
  price double precision not null,
  currency text not null,
  fx_rate double precision,              -- to CAD at trade date
  fees double precision not null default 0,
  trade_date date not null,
  confirmed boolean not null default false,   -- false = provisional (§4.5 fill loop)
  confirmed_at timestamptz,
  note text
);
create index if not exists transactions_ticker_idx on transactions(ticker, trade_date desc);

-- ---------- observations (append) ----------
create table if not exists observations (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  kind text not null,                    -- pass | exit | gate_flip | c2 | breach | learning | note
  ticker text,
  score double precision,
  price double precision,
  body text,
  mark_30 double precision,
  mark_60 double precision,
  mark_90 double precision,
  marked_at timestamptz,
  promoted boolean not null default false,
  detail jsonb
);
create index if not exists observations_kind_idx on observations(kind, at desc);

-- ---------- briefs (append) ----------
create table if not exists briefs (
  id bigint generated always as identity primary key,
  kind text not null,                    -- preopen | stopsheet | deepdive | reconcile | monthly | phase0
  at timestamptz not null default now(),
  session_date date not null,
  freshness text,
  summary text,
  body text,
  detail jsonb
);
create index if not exists briefs_kind_idx on briefs(kind, at desc);

-- ---------- nav_snapshots (append) ----------
create table if not exists nav_snapshots (
  id bigint generated always as identity primary key,
  d date not null,
  nav_cad double precision not null,
  equities_cad double precision,
  cash_cad double precision,
  debt_cad double precision,
  usdcad double precision,
  provisional boolean not null default true,
  detail jsonb,
  computed_at timestamptz not null default now()
);
create index if not exists nav_d_idx on nav_snapshots(d desc);

-- ---------- earnings calendar (§3.3 blackout, §3.2 M4) ----------
create table if not exists earnings (
  ticker text not null,
  report_date date not null,
  report_when text,                      -- BeforeMarketOpen | AfterMarketClose
  eps_est double precision,
  eps_actual double precision,
  revenue_est double precision,
  revenue_actual double precision,
  updated_at timestamptz not null default now(),
  primary key (ticker, report_date)
);
create index if not exists earnings_date_idx on earnings(report_date);

-- ---------- RLS: default-deny everywhere (jobs connect as owner) ----------
alter table accounts        enable row level security;
alter table balances        enable row level security;
alter table bench           enable row level security;
alter table book            enable row level security;
alter table tickets         enable row level security;
alter table transactions    enable row level security;
alter table observations    enable row level security;
alter table briefs          enable row level security;
alter table nav_snapshots   enable row level security;
alter table earnings        enable row level security;
alter table _migrations     enable row level security;

-- ---------- guard: computed tables are written by jobs only (§4.3) ----------
-- implements: 4.3/guard-triggers — refuses writes to the computed tables from any role but the migrator
-- Jobs connect as the owner role through DATABASE_URL; every session connector (today the
-- read-only MCP, tomorrow a read-write one) arrives as some other role and is refused.
-- Role-based on purpose: it carries no session state, so a pooler cannot silently drop it.
create or replace function yuna_jobs_only() returns trigger
language plpgsql as $$
begin
  if current_user not in ('postgres','supabase_admin') then
    raise exception '% is job-written only — sessions may write briefs, tickets, observations, config', TG_TABLE_NAME
      using hint = 'the machine computes; Yuna judges (plan §4.3)';
  end if;
  return coalesce(NEW, OLD);
end $$;

do $$
declare t text;
begin
  -- the plan's list (universe, candidates, bench, queue, book) plus the other machine-computed stores.
  -- balances / transactions / tickets / observations / briefs / config stay session-writable by design.
  foreach t in array array['universe','prices','candidates','queue','bench','book','gate_state','nav_snapshots','earnings']
  loop
    execute format('drop trigger if exists %I on %I', 'guard_'||t, t);
    execute format('create trigger %I before insert or update or delete on %I for each row execute function yuna_jobs_only()', 'guard_'||t, t);
    execute format('drop trigger if exists %I on %I', 'guard_trunc_'||t, t);
    execute format('create trigger %I before truncate on %I execute function yuna_jobs_only()', 'guard_trunc_'||t, t);
  end loop;
end $$;

-- ---------- human views (§4.3) ----------
create or replace view v_book as
select b.ticker, u.name, b.account, b.sleeve, b.lot, b.qty, round(b.avg_cost::numeric,4) avg_cost,
       b.currency, p.close as last_close,
       round((b.qty * p.close)::numeric, 2) as market_value,
       round((100.0*(p.close - b.avg_cost)/nullif(b.avg_cost,0))::numeric, 1) as pnl_pct,
       b.stop, b.stop_limit, b.trail_mode, b.pyramid_step, b.highest_close,
       round((100.0*(p.close - b.stop)/nullif(p.close,0))::numeric, 1) as stop_distance_pct,
       b.opened_at, b.thesis, b.invalidators, b.status
from book b
join universe u on u.ticker = b.ticker
left join lateral (select close from prices where ticker=b.ticker order by d desc limit 1) p on true
where b.status = 'open'
order by b.sleeve, b.ticker;

create or replace view v_queue as
select q.rank, q.ticker, u.name, q.source, q.state,
       round(q.trigger_price::numeric,2) trigger_price,
       round(q.limit_price::numeric,2)   limit_price,
       round(q.stop_suggest::numeric,2)  stop_suggest,
       round((100*q.proximity)::numeric,1) as away_pct,
       round(q.mcn::numeric,1) mcn, q.note,
       e.report_date as next_earnings,
       (e.report_date is not null and e.report_date <= current_date + 7) as blackout_risk
from queue q
join universe u on u.ticker = q.ticker
left join lateral (select report_date from earnings
                   where ticker=q.ticker and report_date >= current_date
                   order by report_date limit 1) e on true
order by q.rank;

create or replace view v_bench as
select b.rank, b.ticker, u.name, b.cohort,
       round(b.ccn::numeric,1) ccn,
       round(b.engine::numeric,0) engine, round(b.cash_conv::numeric,0) cash_conv, round(b.size_score::numeric,0) size_score,
       round(b.hurdle_price::numeric,2) hurdle, round(b.last_close::numeric,2) last_close,
       round((100*b.gap_to_hurdle)::numeric,1) as above_hurdle_pct,
       (b.gap_to_hurdle <= 0) as buyable,
       b.c1_pass, b.c2_status, b.approved, b.data_confidence, b.serial_acquirer
from bench b
join universe u on u.ticker = b.ticker
order by b.rank;

-- ---------- seed: accounts (§2.5 / §2.6) ----------
insert into accounts (code,label,kind,currency,callable,max_utilization,funds,note) values
 ('TFSA',  'Wealthsimple TFSA',           'registered','CAD',false,null,null,'all of Momentum + Compounders primary home'),
 ('RRSP',  'Wealthsimple RRSP',           'registered','CAD',false,null,null,'compounder satellite; idle cash deploys here'),
 ('NONREG','Wealthsimple LOC-Investing',  'taxable',   'CAD',false,null,null,'the levered layer only'),
 ('LOC',   'TFSA-secured line of credit', 'facility',  'CAD',true, 0.50,'single_or_etf','single names at CCN >= 85, or ETFs'),
 ('HELOC', 'Home equity line of credit',  'facility',  'CAD',false,null, 'single_or_etf','readvanceable — exempt from never-increase-into-strength'),
 ('MARGIN','Callable margin',             'facility',  'CAD',true, 0.50,'etf_only','ETFs only')
on conflict (code) do nothing;

-- ---------- config additions (append-only versions) ----------
insert into config (key,value,note,set_by) values
 ('hurdle_min_return','0.15','§3.1 expected return floor','yuna'),
 ('hurdle_growth_cap','0.25','§3.1 engine growth cap','yuna'),
 ('hurdle_fair_multiple_cap','30','§3.1 fair P/FCF ceiling','yuna'),
 ('hurdle_fair_multiple_cap_short','25','§3.1 <3yr history','yuna'),
 ('c1_max_net_debt_ebitda','2.5','§3.1 Gate C1 leverage','yuna'),
 ('c1_max_net_issuance','0.02','§3.1 Gate C1 3-yr avg share issuance','yuna'),
 ('ccn_size_band','{"70":0.12,"85":0.15}','§3.1 compounder entry sizing','yuna'),
 ('ccn_flat_size','0.12','§3.1 flat until shadow book validates','yuna'),
 ('sleeve_ceiling','{"compounders":0.60,"momentum":0.40}','§2.1','yuna'),
 ('single_name_entry_cap','0.25','§2.3 entry-only','yuna'),
 ('theme_entry_cap','0.35','§2.2 entry-only','yuna'),
 ('max_names_per_group','2','§2.2 independence','yuna'),
 ('score_thresholds','{"full":85,"enter":70,"hold":55,"displace_margin":10}','§3.3','yuna'),
 ('momentum_max_stop','0.08','§3.2 never wider than 8%','yuna'),
 ('momentum_trail','{"breakeven_at":"full","trail10_from":0.15,"euphoria":0.05}','§3.2','yuna'),
 ('bench_size','60','§3.0 L1-C','yuna'),
 ('bench_cohort_take','30','§3.1 top-30 per size cohort','yuna'),
 ('c2_memo_top_n','100','§3.1 funnel step 4','yuna');
