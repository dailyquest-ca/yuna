-- 023_quarantine.sql — §4.1's quarantine, and the corporate-action log it leans on.
--
-- "Any print moving > 40% with no corporate action, or any print that would fire a sell-side
-- action, needs two sources to agree before anything acts on it. Quarantined rows are flagged in
-- the next brief, never silently used."
--
-- The bar itself is still stored — it is what the vendor said, and rewriting history to taste is
-- worse than flagging it. What quarantine buys is a gate: while a print is held, no sell-side
-- action may fire off it, and the brief names it.

create table if not exists corporate_actions (
  ticker text not null,
  d date not null,
  kind text not null,                    -- split | dividend
  detail jsonb,
  seen_at timestamptz not null default now(),
  primary key (ticker, d, kind)
);
create index if not exists corporate_actions_d_idx on corporate_actions(d desc);

create table if not exists quarantine (
  id bigint generated always as identity primary key,
  ticker text not null,
  d date not null,
  close double precision,
  prev_close double precision,
  move_pct double precision,
  reason text not null,                  -- move | sell_side
  status text not null default 'held',   -- held | cleared | confirmed
  second_source double precision,        -- the live quote we checked against
  checked_at timestamptz,
  resolved_at timestamptz,
  note text,
  detail jsonb,
  raised_at timestamptz not null default now()
);
create unique index if not exists quarantine_open_idx on quarantine(ticker, d)
  where status = 'held';
create index if not exists quarantine_status_idx on quarantine(status, raised_at desc);

comment on table quarantine is
  '§4.1: a suspicious print is held out of use until two sources agree. `held` blocks sell-side
   action on that name; `cleared` means the second source disagreed and the print is not to be
   trusted; `confirmed` means both sources agree and the move was real.';

alter table corporate_actions enable row level security;
alter table quarantine        enable row level security;

do $$
declare t text;
begin
  foreach t in array array['corporate_actions','quarantine']
  loop
    execute format('drop trigger if exists %I on %I', 'guard_'||t, t);
    execute format('create trigger %I before insert or update or delete on %I for each row execute function yuna_jobs_only()', 'guard_'||t, t);
  end loop;
end $$;

insert into config (key,value,note,set_by) values
 ('quarantine_move_threshold','0.40','§4.1 a print moving this far with no corporate action is held','yuna'),
 ('quarantine_source_tolerance','0.02','§4.1 how close two sources must be to count as agreeing','yuna');
