-- 019_operate.sql — the schema the operating layer needs (roadmap Phases G-I).
--
-- Three things: tickets get an identity so arming can supersede instead of duplicate; the book
-- and tickets carry the theme a session assigns; group strength gets a home so the Saturday
-- deep-dive can quote week-over-week deltas instead of recomputing them.
--
-- Config keys are seeded here ONLY for rules whose reading code ships in the same commit
-- (learnings #21 — a rule stored is not a rule enforced).

-- ---------- ticket identity (roadmap A3) ----------
-- Arming recomputes the same conclusions every night. Without a key, three phase0 runs wrote 45
-- rows encoding 15 decisions. The key is deliberately coarse: a re-armed trigger at the same
-- price is the same ticket, a trigger at a new price is a new one.
alter table tickets add column if not exists arm_key text;
alter table tickets add column if not exists theme text;
alter table tickets add column if not exists armed_run_id bigint;
alter table tickets add column if not exists effective_bets double precision;
alter table tickets add column if not exists superseded_reason text;

comment on column tickets.arm_key is
  'ticker|action|reason|price — identity for supersession; null on session-written tickets';
comment on column tickets.theme is
  '§2.2 theme, assigned by judgment in the session that writes the ticket — never a data field';
comment on column tickets.effective_bets is
  '§2.2 count printed on every draft ticket; below 4 carries a concentration warning';

-- one live ticket per armed conclusion; cancelled and confirmed rows stay in the ledger
create unique index if not exists tickets_arm_live_idx on tickets(arm_key)
  where arm_key is not null and state in ('proposed','approved');

-- ---------- the book carries its theme (§4.3) ----------
alter table book add column if not exists theme text;
alter table book add column if not exists confirmed boolean;          -- §3.2 breakout confirmation
alter table book add column if not exists confirm_deadline date;      -- late-confirm window
alter table book add column if not exists adds_12m integer not null default 0;
alter table book add column if not exists last_add_at date;
comment on column book.confirmed is
  '§3.2: null until the breakout session closes, then true/false. False freezes the pyramid at 50%';

-- ---------- armed actions: what the nightly job concluded (§2.2, §4.3) ----------
-- The law is explicit twice over: "jobs arm candidates; only sessions write tickets", because a
-- ticket carries a theme and a theme is judgment. So the nightly job writes its conclusions here,
-- fully priced and cap-checked, and R1/R2 turn them into tickets with the theme attached.
-- Overwrite table: every nightly run truncates and rewrites, so a conclusion cannot duplicate.
create table if not exists armed (
  id bigint generated always as identity primary key,
  run_id bigint,
  kind text not null,               -- entry | add | exit | stop_move | cancel | check
  ticker text not null,
  sleeve text,
  account text,
  reason text not null,             -- trigger | hurdle | stop | trail | gap | blackout | gate_off
                                    -- | template | score | unconfirmed | stall | earnings | invalidator
  urgency text not null default 'normal',   -- protective | normal
  order_type text,
  trigger_price double precision,
  limit_price double precision,
  stop double precision,
  stop_limit_price double precision,
  qty double precision,
  size_pct double precision,
  score double precision,
  blocked_by text,                  -- non-null = armed but not offerable (blackout, no room, cap)
  note text,
  detail jsonb,
  computed_at timestamptz not null default now()
);
create index if not exists armed_kind_idx on armed(kind, ticker);
alter table armed enable row level security;
drop trigger if exists guard_armed on armed;
create trigger guard_armed before insert or update or delete on armed
  for each row execute function yuna_jobs_only();
drop trigger if exists guard_trunc_armed on armed;
create trigger guard_trunc_armed before truncate on armed
  execute function yuna_jobs_only();

-- ---------- fills apply to the book exactly once (§4.5) ----------
alter table transactions add column if not exists applied_at timestamptz;
alter table transactions add column if not exists pyramid_step integer;
comment on column transactions.applied_at is
  'set by the nightly job when this fill has been folded into book — keeps application idempotent';

-- ---------- group strength (§5.3 R3 wants week-over-week deltas) ----------
create table if not exists group_strength (
  week_end date not null,
  industry text not null,
  ret_6m double precision,
  percentile double precision,
  members integer,
  computed_at timestamptz not null default now(),
  primary key (week_end, industry)
);
alter table group_strength enable row level security;
drop trigger if exists guard_group_strength on group_strength;
create trigger guard_group_strength before insert or update or delete on group_strength
  for each row execute function yuna_jobs_only();

-- ---------- C1's industry gap, for the C2 memo (§3.1 B4) ----------
-- A name with no vendor industry is not excludable by the bank/insurer test, so the gap has to be
-- visible to whoever writes its memo. Adding a fundamentals column means recreating the view in
-- the same file — a view defined `select *` freezes its column list at creation (learnings #7).
alter table fundamentals add column if not exists industry_missing boolean not null default false;
comment on column fundamentals.industry_missing is
  '§3.1: no vendor industry, so C1 could not test the bank/insurer exclusion — named on the C2 memo';

create or replace view v_fundamentals_latest as
select distinct on (ticker) * from fundamentals order by ticker, filing_date desc;

-- ---------- config the new code reads ----------
insert into config (key,value,note,set_by) values
 ('l2_hurdle_proximity','0.10','§3.0 L2 admits bench names within 10% of hurdle','yuna'),
 ('pyramid_ceiling','1.05','§3.2 both add limits sit at pivot x 1.05','yuna'),
 ('confirmation_volume','1.4','§3.2 breakout confirmation, per session vs its own 50-day','yuna'),
 ('confirmation_sessions','3','§3.2 late-confirm window, breakout day included','yuna'),
 ('holdthrough_cushion','1.08','§3.3 momentum holds through a print only above this x avg cost','yuna'),
 ('effective_bets_warn','4','§2.2 draft tickets below this carry a concentration line','yuna'),
 ('max_adds_per_year','2','§3.1 adds per name per 12 months; tactical adds exempt','yuna'),
 ('max_positions','{"min":7,"max":9}','§2.1 total names across both sleeves','yuna'),
 ('pyramid_stall_weeks','4','§3.2 a pyramid stalled below full size for 4 weeks resolves','yuna');
