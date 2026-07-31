-- 018_session_api.sql — the session write path: schema `api`, role `yuna_session`, eight verbs.
--
-- Until now the database has had exactly one writer: the jobs, holding DATABASE_URL, which is
-- god-mode (§4.8 — "the connection string is god-mode and exists nowhere else"). Scheduled
-- sessions need to record fills, balances, rulings, briefs, observations and proposed tickets
-- (§4.3: "Sessions may write only briefs, tickets, observations, and config"), and there is no
-- honest way to give a session a credential that can do that and nothing else at the table level.
--
-- So sessions get no table access at all. They get VERBS: SECURITY DEFINER functions in a
-- dedicated schema `api`, executable by a role `yuna_session` that holds zero privileges on
-- every table in the database. Reaching a table is not forbidden, it is impossible — there is no
-- grant to bypass. Transport is PostgREST RPC with `api` as the only exposed schema; `public` is
-- deliberately not exposed over HTTP. The session is handed a pre-minted, role-scoped, expiring
-- JWT; the signing secret stays with Zak, because the secret can mint `service_role`.
--
-- The whole surface is safe for one reason, and it is worth naming before the first line of code:
-- **Yuna never executes** (§4.5 — "Zak places every order"). Every verb below either proposes
-- something Zak reviews or records something Zak said. Nothing here moves money, and nothing here
-- can make anything else move money.
--
-- ---------------------------------------------------------------------------------------------
-- CLAUSE MARKERS DELIBERATELY WITHHELD — read this before adding one.
--
-- The clauses this file services are all recorded OPEN in src/yuna/rules.py today:
--   2.0/provisional-balances   — "needs the session write path (session_record_cash)" (built here)
--   2.2/jobs-arm-sessions-write — jobs arm, only sessions write tickets (the SQL half is here;
--                                 phase0.py still writes tickets directly, so the clause is not
--                                 satisfied yet)
--   2.0/ticket-names-account   — only the "names an account" half is enforced here; there is no
--                                 cash check (that needs NAV + T+1, clause 2.0/t1-reuse, OPEN)
-- tests/test_conformance.py::test_unbuilt_clauses_have_no_implementation fails the build when a
-- marker cites a clause the ledger calls OPEN — which is exactly right: the ledger, not this
-- file, decides when a clause is built. rules.py is the orchestrator's file. Flip those statuses
-- there and add the markers here in the same commit, not before.
-- ---------------------------------------------------------------------------------------------
--
-- Nothing in this file adds a rule the plan does not state. Where a value had to be chosen
-- (the ticket transition list, the quarantine thresholds, the protected config keys) the choice
-- is commented with its reasoning and is listed in docs/write-path.md for Zak to confirm.
-- Design, threat model and the revocation procedure: docs/write-path.md.

-- =============================================================================================
-- 1. Schemas
-- =============================================================================================
-- `api`      — the verbs, and nothing else. This is the only schema PostgREST exposes.
-- `yuna_priv`— the machinery the verbs share. Not exposed, not executable by anyone. Split out
--              so that "everything yuna_session may call" is literally "everything in api" — a
--              reviewer can audit the surface by listing one schema.
create schema if not exists api;
create schema if not exists yuna_priv;

comment on schema api is
  'Session write path (§4.3). SECURITY DEFINER verbs only — no tables, no views. The only schema '
  'exposed over PostgREST; `public` is deliberately not exposed. See docs/write-path.md.';
comment on schema yuna_priv is
  'Internals of the session write path. Never exposed, never granted — if anything here becomes '
  'callable by yuna_session, the audit surface has been broken.';

revoke all on schema api       from public;
revoke all on schema yuna_priv from public;

-- =============================================================================================
-- 2. The role
-- =============================================================================================
-- NOLOGIN: yuna_session is never connected to directly. PostgREST logs in as `authenticator` and
-- assumes this role from the JWT's `role` claim, so a leaked token is useless without also
-- reaching the PostgREST endpoint. NOINHERIT so that a future membership cannot leak privileges
-- into it silently. No CREATEDB / CREATEROLE / BYPASSRLS — a role that can create roles can mint
-- itself a better one.
do $$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'yuna_session') then
    execute 'create role yuna_session nologin noinherit nosuperuser nocreatedb nocreaterole '
            'noreplication nobypassrls';
  end if;
end $$;

-- Wrapped: COMMENT ON ROLE wants superuser (or CREATEROLE with admin on the role). It is
-- documentation, and documentation must never be the reason a migration fails.
do $$
begin
  execute 'comment on role yuna_session is '
          '''Yuna''''s scheduled sessions. Zero privileges on every table; may only execute the '
          'verbs in schema api. Kill switch: revoke usage on schema api from yuna_session;''';
exception when insufficient_privilege then
  raise notice 'skipped comment on role yuna_session — no privilege, harmless';
end $$;

-- A leaked token should not be able to hold a connection open forever. Role settings apply on
-- SET ROLE, which is exactly how PostgREST enters this role, so this binds the session path and
-- leaves the jobs alone.
alter role yuna_session set statement_timeout = '10s';
alter role yuna_session set idle_in_transaction_session_timeout = '10s';

-- PostgREST assumes the role; without this grant every request dies at `set role`. Guarded
-- because a bare Postgres (a local restore, CI) has no authenticator and must still migrate.
do $$
begin
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'authenticator') then
    execute 'grant yuna_session to authenticator';
    -- PostgREST builds its schema cache as the authenticator before assuming any role.
    -- Membership runs one way (authenticator inherits yuna_session, never the reverse), so this
    -- grant cannot hand privileges back to yuna_session.
    execute 'grant usage on schema api to authenticator';
  end if;
end $$;

grant usage on schema api to yuna_session;   -- schema visibility only; the function grants follow

-- Belt and braces, and a statement of intent that survives `git log`: this role holds nothing on
-- any table, now or by default, in any schema we own. RLS is already default-deny everywhere
-- (001, 004, 005, 006, 015) so even a stray grant would land on a table with no policies — but
-- "impossible" should not depend on a second mechanism being right.
revoke all privileges on all tables    in schema public from yuna_session;
revoke all privileges on all sequences in schema public from yuna_session;
revoke all privileges on all functions in schema public from yuna_session;
revoke create on schema public from yuna_session;
alter default privileges in schema public revoke all on tables    from yuna_session;
alter default privileges in schema public revoke all on sequences from yuna_session;

-- =============================================================================================
-- 3. Provenance and idempotency: the call ledger
-- =============================================================================================
-- Requirement one of this path is that a retry writes once. Scheduled sessions retry — a run
-- that times out mid-write and is re-fired must not book the fill twice or propose the ticket
-- twice. Requirement two is that a human reading any row can tell whether a job or a session
-- wrote it, which session, which verb, when, and under which key.
--
-- Both are the same table. Every write through this path claims a row here first; the row holds
-- the arguments, the result, and the row the call produced. Any table row a verb writes carries
-- `session_call_id` back to it.
create table if not exists session_calls (
  id bigint generated always as identity primary key,
  verb text not null,                       -- api.<verb>, without the schema
  idempotency_key text not null,            -- the caller's key; unique per verb
  session_id text not null,                 -- JWT `session` / `sid` / `sub` claim, or 'unknown'
  jwt_role text,                            -- the role claim the token carried
  login_role text,                          -- session_user — 'authenticator' under PostgREST
  identified boolean not null default false,-- false = no session claim; provenance is degraded
  called_at timestamptz not null default now(),
  finished_at timestamptz,
  args jsonb not null,                      -- what was asked for, verbatim after validation
  args_digest text not null,                -- md5 of the canonical args — catches key reuse
  result jsonb,                             -- the envelope returned, replayed on every retry
  target_table text,
  target_id bigint,
  unique (verb, idempotency_key)
);
create index if not exists session_calls_session_idx on session_calls(session_id, called_at desc);
create index if not exists session_calls_target_idx  on session_calls(target_table, target_id);

comment on table session_calls is
  'One row per write through the session path (§4.3). The idempotency ledger and the provenance '
  'ledger are the same object on purpose: a retry replays the stored result, and every row a '
  'session wrote points back here.';
comment on column session_calls.args_digest is
  'md5 of the canonical jsonb args. Same key + same args replays; same key + different args is a '
  'caller bug and is refused, because replaying someone else''s result is worse than an error.';
comment on column session_calls.identified is
  'false means the request carried no session claim. The write still happened and is still '
  'attributed to the login role, but "which session" is unanswerable — worth alarming on.';

-- =============================================================================================
-- 4. Quarantine (§4.1 in spirit: a suspicious number is held, never silently used)
-- =============================================================================================
-- §4.1 quarantines prices; balances need the same reflex for a different reason. Zak states a
-- balance in chat, a session records it, and it becomes NAV — the compounding number and the
-- only scorecard (§2.0). One extra zero in a chat message must not become NAV.
--
-- A quarantined statement writes NO balance row. It writes here plus an observation, so it
-- surfaces in the next brief (§4.1 — "Quarantined rows are flagged in the next brief, never
-- silently used"), and a human resolves it with DATABASE_URL. Sessions cannot release a
-- quarantine: there is no verb for it, deliberately. The whole point is a second pair of eyes.
create table if not exists balance_quarantine (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  session_call_id bigint references session_calls(id),
  verb text not null,
  account text not null references accounts(code),
  currency text not null,
  stated_as text not null,                  -- anchor | movement
  amount double precision not null,         -- what was stated
  as_of date not null,
  last_amount double precision,             -- what we held before it
  last_as_of date,
  ratio double precision,                   -- amount / last_amount, when both are usable
  reason text not null,
  resolution text not null default 'pending',   -- pending | accepted | rejected
  resolved_at timestamptz,
  resolved_by text,
  note text
);
create index if not exists balance_quarantine_open_idx
  on balance_quarantine(resolution, at desc);

comment on table balance_quarantine is
  'Balance and cash statements too far from the last known value to accept unreviewed. Resolved '
  'by a human holding DATABASE_URL — no verb releases one.';

alter table session_calls      enable row level security;
alter table balance_quarantine enable row level security;

-- =============================================================================================
-- 5. Provenance columns on the tables sessions write
-- =============================================================================================
-- §4.3 lets sessions write briefs, tickets, observations and config; §2.0 and §5.4 add balances.
-- Those five tables gain the same two columns so any row answers "job or session?" on sight.
-- Existing rows default to 'job', which is the truth — everything written before this migration
-- came from a job or a migration.
--
-- VIEW CHECK (010's lesson: a `select *` view freezes its column list at creation). The only
-- `select *` view in this repo is v_fundamentals_latest, over `fundamentals`, and no table
-- altered below is `fundamentals`. v_book, v_queue and v_bench name their columns and are
-- unaffected. Nothing needs recreating here — verified, not assumed.
do $$
declare t text;
begin
  foreach t in array array['tickets','briefs','observations','balances','config'] loop
    execute format('alter table %I add column if not exists written_by text not null default ''job''', t);
    execute format('alter table %I add column if not exists session_call_id bigint references session_calls(id)', t);
    if not exists (select 1 from pg_catalog.pg_constraint where conname = t || '_written_by_ck') then
      execute format('alter table %I add constraint %I check (written_by in (''job'',''session''))',
                     t, t || '_written_by_ck');
    end if;
    execute format('comment on column %I.written_by is %L', t,
                   'job | session — who wrote this row. session rows carry session_call_id.');
    execute format('comment on column %I.session_call_id is %L', t,
                   'the session_calls row that produced this: which session, which verb, when, '
                   'and under which idempotency key.');
  end loop;
end $$;

-- observations gains a subject line. `kind` is the vocabulary (pass | exit | gate_flip | c2 |
-- breach | learning | note, plus `ruling` below); `topic` is what the observation is about when
-- it is not about a ticker — "TFSA cash", "sizing", "D10".
alter table observations add column if not exists topic text;
comment on column observations.topic is
  'free-text subject when the observation is not about a ticker; `kind` stays the vocabulary';

-- balances gains the §2.0 provisional apparatus.
alter table balances add column if not exists provisional boolean not null default false;
alter table balances add column if not exists stated_as text;              -- anchor | movement
alter table balances add column if not exists movement_amount double precision;
alter table balances add column if not exists movement_currency text;

comment on column balances.provisional is
  '§2.0 — a balance stated mid-week is provisional and is trued up at Sunday reconciliation. '
  'Rows written before 018, and rows written by session_record_balance (the reconciliation verb), '
  'are anchors and read false.';
comment on column balances.stated_as is
  'anchor = "the balance is now X" · movement = "I deposited X". null on job and reconciliation '
  'rows, which are anchors by construction.';
comment on column balances.movement_amount is
  'the movement itself, signed, so "last anchor + movements since" is auditable arithmetic '
  'rather than a number that appeared. Null on anchor rows.';
comment on column balances.movement_currency is
  'the currency the movement was stated in — CAD or USD; facilities are CAD always (016).';

-- =============================================================================================
-- 6. Internals — yuna_priv
-- =============================================================================================
-- Every function below is SECURITY DEFINER with a pinned search_path. The pin is not decoration:
-- a definer function running as the migration owner with a caller-controlled search_path is a
-- straight privilege escalation, because the caller chooses which `balances` you insert into.
-- pg_temp is pinned LAST — the CREATE privilege on a temp schema is granted to PUBLIC by default,
-- so pg_temp first would let a caller shadow a table or an operator.

-- Who is calling. PostgREST publishes the verified JWT claims in a GUC; we take the session
-- identity from there. Malformed or absent claims degrade provenance to 'unknown' rather than
-- refusing the write: refusing would be a rule the plan does not state, and a write we can only
-- half-attribute is still better than a write we lost. `identified` records which happened.
create or replace function yuna_priv.caller() returns jsonb
language plpgsql stable security definer set search_path = pg_catalog, public, pg_temp as $$
declare c jsonb;
begin
  begin
    c := nullif(current_setting('request.jwt.claims', true), '')::jsonb;
  exception when others then
    c := null;
  end;
  return jsonb_build_object(
    'session', coalesce(c ->> 'session', c ->> 'sid', c ->> 'sub', 'unknown'),
    'role',    c ->> 'role',
    'expires', c ->> 'exp',
    'login',   session_user::text);
end $$;

-- The uniform result envelope. Every verb returns this shape, so a session can branch on
-- `action` without knowing which verb it called: written | quarantined | would_write |
-- would_quarantine | validated.
create or replace function yuna_priv.envelope(p_verb text, p_key text, p_dry boolean,
                                              p_replayed boolean, p_action text,
                                              p_table text, p_id bigint,
                                              p_extra jsonb default '{}'::jsonb)
returns jsonb
language sql stable security definer set search_path = pg_catalog, public, pg_temp as $$
  select jsonb_build_object('ok', true, 'verb', p_verb, 'idempotency_key', p_key,
                            'dry_run', p_dry, 'replayed', p_replayed, 'action', p_action,
                            'table', p_table, 'id', p_id, 'at', now())
         || coalesce(p_extra, '{}'::jsonb);
$$;

-- Claim the idempotency key, or replay.
--
-- Returns {call_id, replayed, result}. The insert races cleanly: two identical concurrent calls
-- both attempt the insert, one wins, the loser blocks on the unique index until the winner
-- commits and then reads the winner's row. The retry loop exists for the case where the winner
-- ROLLED BACK — then the row is gone and the key is genuinely free again.
--
-- A key reused with different arguments is refused, not replayed. Replaying would hand back a
-- result for something the caller did not ask for; writing again would defeat the whole table.
create or replace function yuna_priv.claim(p_verb text, p_key text, p_args jsonb)
returns jsonb
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
  v_who    jsonb := yuna_priv.caller();
  v_digest text  := md5(p_args::text);   -- jsonb::text is canonical, so equal args hash equal
  v_id     bigint;
  v_prior  session_calls%rowtype;
begin
  if p_key is null or btrim(p_key) = '' then
    raise exception 'idempotency_key is required'
      using errcode = 'PT400',
            hint = 'scheduled sessions retry; the key is the only thing that stops a retry '
                   'writing twice. Derive it from the thing itself, not from the clock.';
  end if;

  for _attempt in 1..3 loop
    insert into session_calls (verb, idempotency_key, session_id, jwt_role, login_role,
                               identified, args, args_digest)
    values (p_verb, p_key, v_who ->> 'session', v_who ->> 'role', v_who ->> 'login',
            (v_who ->> 'session') is distinct from 'unknown', p_args, v_digest)
    on conflict (verb, idempotency_key) do nothing
    returning id into v_id;

    if v_id is not null then
      return jsonb_build_object('call_id', v_id, 'replayed', false);
    end if;

    select * into v_prior from session_calls c
     where c.verb = p_verb and c.idempotency_key = p_key;

    if found then
      if v_prior.args_digest is distinct from v_digest then
        raise exception 'idempotency key % was already used by % with different arguments',
                        p_key, p_verb
          using errcode = 'PT409',
                hint = 'use a new key, or send the original arguments. Replaying a stored result '
                       'for a different request would be a silent lie.';
      end if;
      if v_prior.result is null then
        raise exception 'idempotency key % for % is still in flight', p_key, p_verb
          using errcode = 'PT409', hint = 'retry in a moment; the first call has not finished';
      end if;
      -- Same write, same result. `replayed` flips so the caller can tell it retried; every
      -- other field — table, id, action — is byte-identical to the first call's answer.
      return jsonb_build_object('call_id', v_prior.id, 'replayed', true,
                                'result', v_prior.result || '{"replayed": true}'::jsonb);
    end if;
  end loop;

  raise exception 'could not claim idempotency key % for %', p_key, p_verb
    using errcode = 'PT409', hint = 'three attempts lost the race; this should not happen';
end $$;

-- Close the ledger row and hand the envelope back.
create or replace function yuna_priv.finish(p_call_id bigint, p_result jsonb,
                                            p_table text default null, p_id bigint default null)
returns jsonb
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
begin
  update session_calls c
     set result = p_result, target_table = p_table, target_id = p_id, finished_at = now()
   where c.id = p_call_id;
  return p_result;
end $$;

-- --- the ticket state machine ---------------------------------------------------------------
-- The states are the six in 005's `tickets.state` comment, and no others. The transitions are
-- read off §4.3 ("proposed -> approved -> filled (provisional/confirmed) -> cancelled") and the
-- §4.5 fill loop ("chat or flip -> tickets row provisional -> book updates that night -> Sunday
-- confirms against the broker's settled record"). The plan never enumerates them, so this list
-- is a decision, recorded as Q4 in docs/open-questions.md and listed in docs/write-path.md for
-- Zak to confirm. Everything not on the list is refused — including a self-transition, which is
-- either a bug or a retry that should have carried its original idempotency key.
create or replace function yuna_priv.ticket_states() returns text[]
language sql immutable security definer set search_path = pg_catalog, public, pg_temp as $$
  select array['proposed','approved','provisional','confirmed','cancelled','expired'];
$$;

create or replace function yuna_priv.ticket_transitions()
returns table (from_state text, to_state text, why text)
language sql immutable security definer set search_path = pg_catalog, public, pg_temp as $$
  select * from (values
    -- Zak reviews and decides (§4.5 item 1)
    ('proposed',   'approved',    'Zak approved the ticket; it goes to the broker'),
    ('proposed',   'cancelled',   'Zak declined it, or the setup died before he acted'),
    ('proposed',   'expired',     'the trigger aged out — the base broke, the gate flipped'),
    -- the order is live at the broker
    ('approved',   'provisional', 'fill reported in chat or by flipping the ticket (§4.5)'),
    ('approved',   'cancelled',   'order pulled — blackout cancels live entries and adds (§3.3)'),
    ('approved',   'expired',     'GTC lapsed unfilled (90 days at Wealthsimple, §4.6)'),
    -- Sunday reconciliation (§5.4)
    ('provisional','confirmed',   'matched against the broker''s settled record on Sunday'),
    ('provisional','cancelled',   'the broker record contradicts the reported fill — §5.4 says '
                                  'discrepancies are flagged, never silently absorbed. Requires a note.')
  ) as t(from_state, to_state, why);
$$;
-- confirmed / cancelled / expired are terminal. `confirmed` means it was matched against the
-- broker's settled record; nothing a session can say outranks that.

create or replace function yuna_priv.ticket_transition_ok(p_from text, p_to text) returns boolean
language sql stable security definer set search_path = pg_catalog, public, pg_temp as $$
  select exists (select 1 from yuna_priv.ticket_transitions() t
                  where t.from_state = p_from and t.to_state = p_to);
$$;

-- --- protected config ------------------------------------------------------------------------
-- §4.3: "The plan is law; config is its runtime copy. Any config change that moves a plan-stated
-- number requires the announced plan edit first — a config row never quietly overrules this
-- document." A session that could widen a stop or raise a size cap by writing a config row would
-- be able to change what the machine does to money without anyone announcing an edit.
--
-- Five gates, any one of which refuses. Deliberately over-broad: a wrongly-refused key costs one
-- migration, a wrongly-allowed key costs real money.
--   1. the exact list of every key seeded to date (002, 005, 009, 016)
--   2. a substring deny-list, so a key invented next month is refused by default
--   3. any existing key Zak himself set — his settings are not a session's to overwrite
--   4. any existing key whose note cites a plan section — that is §4.3's "runtime copy of law"
--   5. any key a JOB or a migration has ever written. This is the gate that matters most,
--      because it does not depend on anyone naming the key well: whatever the machine set, a
--      session cannot move. Gates 1-4 are the backstop for keys that do not exist yet.
-- What is left, in practice, is a key a session invented and maintains itself. That is a very
-- small door, and it is meant to be.
-- Returns null when the key may be set, or the reason it may not.
create or replace function yuna_priv.config_protection(p_key text) returns text
language plpgsql stable security definer set search_path = pg_catalog, public, pg_temp as $$
declare
  -- Every config key that exists today. All of them govern money, risk, or the shape of the
  -- funnel that leads to money; none of them is a session's to move.
  k_locked constant text[] := array[
    -- 002_seed.sql
    'stop_limit_buffer','entry_limit_over_pivot','gap_threshold','blackout_trading_days',
    'bars_retention_years','small_large_boundary_usd','queue_cap','new_entry_tickets_per_brief',
    'api_alarm_fraction','position_floor_nav','mcn_risk_budget','mcn_risk_budget_validation',
    'base_currency',
    -- 005_book.sql
    'hurdle_min_return','hurdle_growth_cap','hurdle_fair_multiple_cap',
    'hurdle_fair_multiple_cap_short','c1_max_net_debt_ebitda','c1_max_net_issuance',
    'ccn_size_band','ccn_flat_size','sleeve_ceiling','single_name_entry_cap','theme_entry_cap',
    'max_names_per_group','score_thresholds','momentum_max_stop','momentum_trail','bench_size',
    'bench_cohort_take','c2_memo_top_n',
    -- 009_quote_currency.sql / 016_multicurrency_cash.sql
    'engine_agreement_tolerance','levered_etf'];
  -- Substrings. If a future key contains any of these it touches sizing, stops, hurdles, risk
  -- budgets, sleeve weights or caps, and it is refused until a human says otherwise.
  k_patterns constant text[] := array[
    'size','cap','stop','trail','risk','budget','hurdle','sleeve','weight','threshold','floor',
    'ceiling','limit','margin','leverage','utilization','facility','nav','currency','fx','ccn',
    'mcn','score','theme','group','blackout','pivot','volume','tranche','quarantine','position',
    'entry','exit','drawdown','allocation','percent','pct','ratio','rate','buffer','gate',
    'drawn','credit','cash','order','qty','share','tier','band','bar','target','idempot'];
  v_key text := lower(btrim(coalesce(p_key, '')));
  p    text;
  v_by text;
  v_note text;
begin
  if v_key = '' then
    return 'a config key is required';
  end if;
  if v_key = any (k_locked) then
    return format('%s is a plan-stated value (§4.3: the plan is law, config is its runtime copy). '
                  'Changing it requires the announced plan edit first, then a migration.', v_key);
  end if;
  foreach p in array k_patterns loop
    if position(p in v_key) > 0 then
      return format('%s contains "%s", so it governs sizing, risk or the caps. The session path '
                    'refuses those by pattern (§4.3); set it by migration.', v_key, p);
    end if;
  end loop;
  if exists (select 1 from config c where lower(c.key) = v_key and c.written_by = 'job') then
    return format('%s is maintained by the machine — a job or a migration set it, so a session '
                  'does not move it (§4.3).', v_key);
  end if;
  select c.set_by, c.note into v_by, v_note
    from config c where lower(c.key) = v_key order by c.set_at desc, c.id desc limit 1;
  if v_by = 'zak' then
    return format('%s was set by Zak; a session does not overwrite his settings.', v_key);
  end if;
  if v_note is not null and position('§' in v_note) > 0 then
    return format('%s cites a plan section in its note, so it is a runtime copy of law (§4.3).', v_key);
  end if;
  return null;
end $$;

-- --- balance outliers ------------------------------------------------------------------------
-- §4.1 holds a suspicious PRICE out of use until two sources agree. A balance has no second
-- source until Sunday, so the test is against our own last known value, and the failure mode we
-- are actually defending against is a typo in a chat message becoming NAV.
--
-- THRESHOLDS, and why (all chosen here, all listed in docs/write-path.md as Q5 for Zak):
--   MATERIALITY   10,000 — in the stated currency, no FX conversion. NAV is ~200K CAD, so a
--                 change under 10K cannot meaningfully move the scorecard, and cash sloshes by
--                 that much in normal trading. Below it, nothing is quarantined.
--   ANCHOR ratio  >= 10x or <= 0.1x. This is the extra-zero signature, exactly. 7,933 -> 79,331
--                 trips it; 78,085 -> 178,085 (a real 100K deposit) does not, and should not.
--   MOVEMENT      >= 50,000 in the stated currency, or >= 10x the last known balance. 50K is a
--                 quarter of NAV — a transfer that size is rare enough that one confirmation is
--                 cheap, and it catches the extra zero on the plan's own worked example
--                 ("I deposited $5,000 CAD" -> 50,000).
--
-- Honest residue, named rather than hidden: a typo INSIDE one order of magnitude (78,085 ->
-- 87,085) is not caught here. Nothing available to a single SQL function catches it. It is caught
-- Sunday, against the broker's settled record (§2.0, §5.4) — which is the real control; this
-- function only stops the damage that would be done before Sunday arrives.
--
-- The thresholds are constants in the function body, NOT config rows, on purpose: a session that
-- could widen its own quarantine could defeat it. Changing them takes a migration.
create or replace function yuna_priv.balance_outlier(p_account text, p_currency text,
                                                     p_field text, p_stated_as text,
                                                     p_amount double precision)
returns jsonb
language plpgsql stable security definer set search_path = pg_catalog, public, pg_temp as $$
declare
  c_materiality  constant double precision := 10000;
  c_anchor_hi    constant double precision := 10;
  c_anchor_lo    constant double precision := 0.1;
  c_movement_max constant double precision := 50000;
  v_last    double precision;
  v_last_at date;
  v_ratio   double precision;
begin
  -- last known value of this exact field for this account, provisional or not
  select case p_field when 'cash_cad' then b.cash_cad
                      when 'cash_usd' then b.cash_usd
                      else b.drawn end,
         b.as_of
    into v_last, v_last_at
    from balances b
   where b.account = p_account
     and (case p_field when 'cash_cad' then b.cash_cad
                       when 'cash_usd' then b.cash_usd
                       else b.drawn end) is not null
   order by b.as_of desc, b.id desc
   limit 1;

  if p_stated_as = 'movement' then
    if abs(p_amount) >= c_movement_max then
      return jsonb_build_object('quarantine', true, 'last', v_last, 'last_as_of', v_last_at,
        'ratio', null, 'reason', format(
          'movement of %s %s is at or above the %s review threshold', abs(p_amount), p_currency,
          c_movement_max));
    end if;
    if v_last is not null and v_last > 0 and abs(p_amount) > c_materiality
       and abs(p_amount) >= c_anchor_hi * v_last then
      return jsonb_build_object('quarantine', true, 'last', v_last, 'last_as_of', v_last_at,
        'ratio', abs(p_amount) / v_last, 'reason', format(
          'movement of %s %s is %sx the last known balance of %s', abs(p_amount), p_currency,
          round((abs(p_amount) / v_last)::numeric, 1), v_last));
    end if;
    return jsonb_build_object('quarantine', false, 'last', v_last, 'last_as_of', v_last_at);
  end if;

  -- anchor
  if p_amount < 0 then
    return jsonb_build_object('quarantine', true, 'last', v_last, 'last_as_of', v_last_at,
      'ratio', null, 'reason', 'a stated balance below zero needs a human');
  end if;
  if v_last is null then
    -- nothing to compare against. Not an outlier — there is no baseline, and inventing one
    -- would be worse than accepting the first statement and labelling it.
    return jsonb_build_object('quarantine', false, 'last', null, 'last_as_of', null,
                              'baseline', false);
  end if;
  if abs(p_amount - v_last) <= c_materiality then
    return jsonb_build_object('quarantine', false, 'last', v_last, 'last_as_of', v_last_at);
  end if;
  if v_last = 0 then
    return jsonb_build_object('quarantine', true, 'last', 0, 'last_as_of', v_last_at,
      'ratio', null, 'reason', format(
        'account last read zero %s and is now stated at %s — no ratio can test that',
        p_currency, p_amount));
  end if;
  v_ratio := p_amount / v_last;
  if v_ratio >= c_anchor_hi or v_ratio <= c_anchor_lo then
    return jsonb_build_object('quarantine', true, 'last', v_last, 'last_as_of', v_last_at,
      'ratio', v_ratio, 'reason', format(
        'stated %s %s against a last known %s (%sx) — an order of magnitude is the fat-finger '
        'signature', p_amount, p_currency, v_last, round(v_ratio::numeric, 2)));
  end if;
  return jsonb_build_object('quarantine', false, 'last', v_last, 'last_as_of', v_last_at,
                            'ratio', v_ratio);
end $$;

-- Write the quarantine row + the observation that puts it in the next brief (§4.1).
create or replace function yuna_priv.quarantine(p_call_id bigint, p_verb text, p_account text,
                                                p_currency text, p_stated_as text,
                                                p_amount double precision, p_as_of date,
                                                p_check jsonb, p_note text)
returns bigint
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare v_id bigint;
begin
  insert into balance_quarantine (session_call_id, verb, account, currency, stated_as, amount,
                                  as_of, last_amount, last_as_of, ratio, reason, note)
  values (p_call_id, p_verb, p_account, p_currency, p_stated_as, p_amount, p_as_of,
          (p_check ->> 'last')::double precision, (p_check ->> 'last_as_of')::date,
          (p_check ->> 'ratio')::double precision, p_check ->> 'reason', p_note)
  returning id into v_id;

  insert into observations (kind, topic, body, detail, written_by, session_call_id)
  values ('breach', format('%s %s balance', p_account, p_currency),
          format('QUARANTINED: %s. Stated %s %s as of %s. Not written to balances — NAV still '
                 'reads the last accepted value. Needs Zak.',
                 p_check ->> 'reason', p_amount, p_currency, p_as_of),
          jsonb_build_object('quarantine_id', v_id, 'verb', p_verb, 'account', p_account,
                             'currency', p_currency, 'stated_as', p_stated_as,
                             'amount', p_amount, 'as_of', p_as_of) || p_check,
          'session', p_call_id);
  return v_id;
end $$;

-- Resolve (account, currency) to the balances column being stated, and validate the pair.
-- Facilities carry `drawn`, and 016 records Zak's ruling that leverage is CAD always.
create or replace function yuna_priv.balance_field(p_account text, p_currency text) returns text
language plpgsql stable security definer set search_path = pg_catalog, public, pg_temp as $$
declare v_kind text; v_ccy text := upper(btrim(coalesce(p_currency, '')));
begin
  select a.kind into v_kind from accounts a where a.code = p_account;
  if v_kind is null then
    raise exception 'unknown account %', p_account
      using errcode = 'PT400',
            hint = 'accounts are seeded in 005: TFSA, RRSP, NONREG, LOC, HELOC, MARGIN';
  end if;
  if v_ccy not in ('CAD','USD') then
    raise exception 'currency % is not held — balances carry CAD and USD only', p_currency
      using errcode = 'PT400';
  end if;
  if v_kind = 'facility' then
    if v_ccy <> 'CAD' then
      raise exception 'facility % is drawn in CAD always (016, Zak 2026-07-31)', p_account
        using errcode = 'PT400';
    end if;
    return 'drawn';
  end if;
  return case v_ccy when 'CAD' then 'cash_cad' else 'cash_usd' end;
end $$;

-- The last row for an account, so a new row can carry forward everything it does not restate.
--
-- THIS IS LOAD-BEARING. db.nav_cad reads `select distinct on (account) ... order by as_of desc,
-- id desc` — the newest row per account wins outright. A row stating only CAD cash, written
-- naively, would leave cash_usd null and NAV would silently lose the 78,085 USD sitting in the
-- TFSA. So every session-written balance row copies the previous row's other fields forward and
-- overwrites exactly the one field being stated.
--
-- total_value is the one thing NOT carried forward: it is the broker's stated account total, a
-- reconciliation check (016), and carrying a stale one forward would fake a variance of zero.
-- A session row leaves it null, and nav_cad already reports stated_total as null cleanly.
create or replace function yuna_priv.prior_balance(p_account text) returns balances
language sql stable security definer set search_path = pg_catalog, public, pg_temp as $$
  select b.* from balances b where b.account = p_account
   order by b.as_of desc, b.id desc limit 1;
$$;

-- Insert one balances row, carrying the prior row forward. Returns the new row's id.
create or replace function yuna_priv.write_balance(p_call_id bigint, p_account text,
                                                   p_field text, p_currency text,
                                                   p_value double precision, p_as_of date,
                                                   p_provisional boolean, p_stated_as text,
                                                   p_movement double precision)
returns bigint
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare p balances; v_id bigint;
begin
  if p_value is null then
    -- Callers must not write a row that blanks a field NAV reads. Belt and braces: the one path
    -- that can produce a null figure (a movement with no anchor) returns before reaching here.
    raise exception 'refusing to write a balance row with no figure for % on %', p_field, p_account
      using errcode = 'PT400';
  end if;
  p := yuna_priv.prior_balance(p_account);
  insert into balances (account, as_of, cash_cad, cash_usd, drawn, credit_limit, source,
                        provisional, stated_as, movement_amount, movement_currency,
                        written_by, session_call_id)
  values (p_account, p_as_of,
          case when p_field = 'cash_cad' then p_value else p.cash_cad end,
          case when p_field = 'cash_usd' then p_value else p.cash_usd end,
          case when p_field = 'drawn'    then p_value else p.drawn    end,
          p.credit_limit,                        -- capacity, not a liability (§2.0) — unchanged
          'zak',                                 -- the number came from Zak, via a session
          p_provisional, p_stated_as, p_movement,
          case when p_movement is null then null else p_currency end,
          'session', p_call_id)
  returning id into v_id;
  return v_id;
end $$;

-- =============================================================================================
-- 7. The verbs
-- =============================================================================================
-- Shape, identical in all eight:
--   1. validate everything, raising with a clear message. Each verb does its OWN validation and
--      leans on no trigger — see §8 of docs/write-path.md for why that matters here.
--   2. if dry_run, return what WOULD happen and write nothing at all — not even the idempotency
--      row, so a dry run cannot burn the key the real call needs.
--   3. claim the idempotency key; replay verbatim if it has been used.
--   4. write, stamping written_by='session' and session_call_id.
--   5. close the ledger row with the envelope, and return it.
--
-- Parameters are referenced as <function>.<param> throughout. It is verbose and it is deliberate:
-- `where key = key` in plpgsql is ambiguous, and the failure mode of getting it wrong here is
-- writing to the wrong row.

-- --- 7.1 briefs -------------------------------------------------------------------------------
-- §4.4 / §5.6: "Every session writes its output to briefs — a session that produced nothing
-- durable didn't happen." The kinds are 005's vocabulary, one per runbook, plus phase0.
create or replace function api.session_write_brief(
  idempotency_key text,
  kind text,
  summary text,
  detail jsonb default null,
  body text default null,
  freshness text default null,
  session_date date default null,
  dry_run boolean default false)
returns jsonb
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
  v_day   date := coalesce(session_date, current_date);
  v_args  jsonb;
  v_claim jsonb;
  v_id    bigint;
begin
  if kind is null or kind not in ('preopen','stopsheet','deepdive','reconcile','monthly','phase0') then
    raise exception 'brief kind % is not a session output', coalesce(kind, '<null>')
      using errcode = 'PT400',
            hint = 'preopen (R1) · stopsheet (R2) · deepdive (R3) · reconcile (R4) · '
                   'monthly (R5) · phase0';
  end if;
  if summary is null or btrim(summary) = '' then
    raise exception 'a brief needs a summary — §5.6 puts the summary first, context second'
      using errcode = 'PT400';
  end if;
  if v_day > current_date then
    raise exception 'session_date % is in the future', v_day using errcode = 'PT400';
  end if;

  v_args := jsonb_build_object('kind', kind, 'summary', summary, 'body', body,
                               'detail', detail, 'freshness', freshness, 'session_date', v_day);
  if dry_run then
    return yuna_priv.envelope('session_write_brief', idempotency_key, true, false,
                              'would_write', 'briefs', null, jsonb_build_object('args', v_args));
  end if;

  v_claim := yuna_priv.claim('session_write_brief', idempotency_key, v_args);
  if (v_claim ->> 'replayed')::boolean then return v_claim -> 'result'; end if;

  insert into briefs (kind, session_date, freshness, summary, body, detail,
                      written_by, session_call_id)
  values (session_write_brief.kind, v_day, session_write_brief.freshness,
          session_write_brief.summary, session_write_brief.body, session_write_brief.detail,
          'session', (v_claim ->> 'call_id')::bigint)
  returning id into v_id;

  return yuna_priv.finish((v_claim ->> 'call_id')::bigint,
                          yuna_priv.envelope('session_write_brief', idempotency_key, false, false,
                                             'written', 'briefs', v_id,
                                             jsonb_build_object('kind', kind, 'session_date', v_day)),
                          'briefs', v_id);
end $$;

-- --- 7.2 propose a ticket ---------------------------------------------------------------------
-- §4.3: "jobs arm candidates; only sessions write tickets" — this is the session's half of that.
-- The verb has NO state parameter. It cannot create anything but a 'proposed' ticket, which is
-- why the whole surface stays safe: a proposed ticket is a suggestion on a page until Zak places
-- the order himself (§4.5).
--
-- NOT enforced here, deliberately: §2.0's "only written if that account holds the cash". That
-- needs NAV, open positions and the T+1 rule (clause 2.0/t1-reuse, still OPEN), which is a
-- calculation that belongs in policy.py, not in a definer function. The account is required; the
-- cash test is not made. Recorded in docs/write-path.md as a known gap.
create or replace function api.session_propose_ticket(
  idempotency_key text,
  ticker text,
  account text,
  action text,
  reason text default null,
  sleeve text default null,
  order_type text default null,
  trigger_price double precision default null,
  limit_price double precision default null,
  qty double precision default null,
  stop double precision default null,
  stop_limit_price double precision default null,
  brief_id bigint default null,
  note text default null,
  dry_run boolean default false)
returns jsonb
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
  v_args  jsonb;
  v_claim jsonb;
  v_id    bigint;
begin
  if ticker is null or btrim(ticker) = '' then
    raise exception 'a ticket names a ticker' using errcode = 'PT400';
  end if;
  -- §2.0: "Every ticket names an account". tickets.account also carries an FK to accounts(code);
  -- this check exists to produce a sentence instead of a constraint violation.
  if account is null or not exists (select 1 from accounts a where a.code = session_propose_ticket.account) then
    raise exception 'ticket names no known account (§2.0 — every ticket names an account)'
      using errcode = 'PT400', hint = 'TFSA · RRSP · NONREG · LOC · HELOC · MARGIN';
  end if;
  if action is null or action not in ('buy','add','sell','stop_move','cancel') then
    raise exception 'ticket action % is not one of buy · add · sell · stop_move · cancel',
                    coalesce(action, '<null>') using errcode = 'PT400';
  end if;
  if reason is not null and reason not in
     ('trigger','hurdle','stop','trail','gap','blackout','phase0','swap') then
    raise exception 'ticket reason % is not one of trigger · hurdle · stop · trail · gap · '
                    'blackout · phase0 · swap', reason using errcode = 'PT400';
  end if;
  if sleeve is not null and sleeve not in ('compounders','momentum','levered') then
    raise exception 'sleeve % is not one of compounders · momentum · levered (§2.1, §2.0)', sleeve
      using errcode = 'PT400';
  end if;
  if order_type is not null and order_type not in ('stop_limit','market','limit') then
    raise exception 'order_type % is not one of stop_limit · market · limit', order_type
      using errcode = 'PT400';
  end if;
  if action in ('buy','add','sell') and (qty is null or qty <= 0) then
    raise exception 'a % ticket needs a positive qty', action using errcode = 'PT400';
  end if;
  if coalesce(trigger_price, 1) <= 0 or coalesce(limit_price, 1) <= 0
     or coalesce(stop, 1) <= 0 or coalesce(stop_limit_price, 1) <= 0 then
    raise exception 'prices on a ticket are positive or absent' using errcode = 'PT400';
  end if;
  if brief_id is not null and not exists (select 1 from briefs b where b.id = session_propose_ticket.brief_id) then
    raise exception 'brief % does not exist', brief_id using errcode = 'PT400';
  end if;

  v_args := jsonb_build_object('ticker', ticker, 'account', account, 'action', action,
                               'reason', reason, 'sleeve', sleeve, 'order_type', order_type,
                               'trigger_price', trigger_price, 'limit_price', limit_price,
                               'qty', qty, 'stop', stop, 'stop_limit_price', stop_limit_price,
                               'brief_id', brief_id, 'note', note);
  if dry_run then
    return yuna_priv.envelope('session_propose_ticket', idempotency_key, true, false,
                              'would_write', 'tickets', null,
                              jsonb_build_object('state', 'proposed', 'args', v_args));
  end if;

  v_claim := yuna_priv.claim('session_propose_ticket', idempotency_key, v_args);
  if (v_claim ->> 'replayed')::boolean then return v_claim -> 'result'; end if;

  insert into tickets (ticker, account, sleeve, action, reason, order_type, trigger_price,
                       limit_price, qty, stop, stop_limit_price, state, brief_id, note,
                       written_by, session_call_id)
  values (session_propose_ticket.ticker, session_propose_ticket.account,
          session_propose_ticket.sleeve, session_propose_ticket.action,
          session_propose_ticket.reason, session_propose_ticket.order_type,
          session_propose_ticket.trigger_price, session_propose_ticket.limit_price,
          session_propose_ticket.qty, session_propose_ticket.stop,
          session_propose_ticket.stop_limit_price,
          'proposed',                       -- the only state this verb can ever produce
          session_propose_ticket.brief_id, session_propose_ticket.note,
          'session', (v_claim ->> 'call_id')::bigint)
  returning id into v_id;

  return yuna_priv.finish((v_claim ->> 'call_id')::bigint,
                          yuna_priv.envelope('session_propose_ticket', idempotency_key, false,
                                             false, 'written', 'tickets', v_id,
                                             jsonb_build_object('state', 'proposed',
                                                                'ticker', ticker,
                                                                'account', account)),
                          'tickets', v_id);
end $$;

-- --- 7.3 move a ticket through its states -----------------------------------------------------
-- The fill loop lives here: §4.5 "chat or flip → tickets row provisional → book updates that
-- night → Sunday confirms against the broker's settled record". Recording a fill IS
-- session_set_ticket_state(ticket, 'provisional', 'filled at 176.20') — there is no separate
-- fill verb, because a fill that does not correspond to a ticket is not a thing this system has.
create or replace function api.session_set_ticket_state(
  idempotency_key text,
  ticket_id bigint,
  new_state text,
  note text default null,
  dry_run boolean default false)
returns jsonb
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
  v_from  text;
  v_legal text;
  v_args  jsonb;
  v_claim jsonb;
begin
  select t.state into v_from from tickets t where t.id = session_set_ticket_state.ticket_id;
  if v_from is null then
    raise exception 'ticket % does not exist', ticket_id using errcode = 'PT404';
  end if;
  if new_state is null or not (new_state = any (yuna_priv.ticket_states())) then
    raise exception 'ticket state % does not exist', coalesce(new_state, '<null>')
      using errcode = 'PT400',
            hint = 'proposed · approved · provisional · confirmed · cancelled · expired';
  end if;
  if not yuna_priv.ticket_transition_ok(v_from, new_state) then
    select coalesce(string_agg(t.to_state, ' · ' order by t.to_state), '(none — terminal)')
      into v_legal from yuna_priv.ticket_transitions() t where t.from_state = v_from;
    raise exception 'ticket % is %; % -> % is not a legal transition. Legal from %: %',
                    ticket_id, v_from, v_from, new_state, v_from, v_legal
      using errcode = 'PT403',
            hint = 'the transition list is in yuna_priv.ticket_transitions() and '
                   'docs/write-path.md. It is refused, not bent.';
  end if;
  -- §5.4: discrepancies are flagged, never silently absorbed. Undoing a reported fill is exactly
  -- such a discrepancy, so it must arrive with its reason attached.
  if v_from = 'provisional' and new_state = 'cancelled' and (note is null or btrim(note) = '') then
    raise exception 'cancelling a provisional fill needs a note — §5.4 flags discrepancies, '
                    'never absorbs them' using errcode = 'PT400';
  end if;

  v_args := jsonb_build_object('ticket_id', ticket_id, 'new_state', new_state, 'note', note);
  if dry_run then
    return yuna_priv.envelope('session_set_ticket_state', idempotency_key, true, false,
                              'would_write', 'tickets', ticket_id,
                              jsonb_build_object('from', v_from, 'to', new_state));
  end if;

  v_claim := yuna_priv.claim('session_set_ticket_state', idempotency_key, v_args);
  if (v_claim ->> 'replayed')::boolean then return v_claim -> 'result'; end if;

  -- The note is APPENDED. tickets.note carries why the ticket was written ("MCN 78.2 · base
  -- 2026-05-04") and overwriting it would destroy the reason for the trade to record the fill.
  update tickets t
     set state = session_set_ticket_state.new_state,
         note = case when session_set_ticket_state.note is null
                       or btrim(session_set_ticket_state.note) = '' then t.note
                     else coalesce(t.note || E'\n', '')
                          || to_char(now(), 'YYYY-MM-DD') || ' → '
                          || session_set_ticket_state.new_state || ': '
                          || session_set_ticket_state.note end,
         updated_at = now(),
         written_by = 'session',
         session_call_id = (v_claim ->> 'call_id')::bigint
   where t.id = session_set_ticket_state.ticket_id;

  return yuna_priv.finish((v_claim ->> 'call_id')::bigint,
                          yuna_priv.envelope('session_set_ticket_state', idempotency_key, false,
                                             false, 'written', 'tickets', ticket_id,
                                             jsonb_build_object('from', v_from, 'to', new_state)),
                          'tickets', ticket_id);
end $$;

-- --- 7.4 record a balance (the reconciliation anchor) -----------------------------------------
-- §2.0: "Balances are truth, prices are the extrapolation. Sunday reconciliation captures
-- per-account cash and positions plus available credit on each facility (Zak reads them off
-- Wealthsimple, or tells Yuna in chat)." This is that verb — a stated balance, read off the
-- broker, which becomes the anchor everything else extrapolates from. It is NOT provisional;
-- session_record_cash is the mid-week provisional path.
--
-- For a facility the amount is the DRAWN balance, CAD always (016). Credit limits are capacity,
-- not debt (§2.0), and are not restated here.
create or replace function api.session_record_balance(
  idempotency_key text,
  account text,
  currency text,
  amount double precision,
  as_of date default null,
  note text default null,
  dry_run boolean default false)
returns jsonb
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
  v_day   date := coalesce(as_of, current_date);
  v_field text := yuna_priv.balance_field(account, currency);
  v_ccy   text := upper(btrim(currency));
  v_check jsonb;
  v_args  jsonb;
  v_claim jsonb;
  v_id    bigint;
  v_call  bigint;
begin
  if amount is null then
    raise exception 'a balance needs an amount' using errcode = 'PT400';
  end if;
  -- A future-dated row would outrank the Sunday anchor forever: db.nav_cad orders by as_of desc.
  if v_day > current_date then
    raise exception 'as_of % is in the future', v_day using errcode = 'PT400';
  end if;

  v_check := yuna_priv.balance_outlier(account, v_ccy, v_field, 'anchor', amount);
  v_args  := jsonb_build_object('account', account, 'currency', v_ccy, 'amount', amount,
                                'as_of', v_day, 'note', note, 'field', v_field);

  if dry_run then
    return yuna_priv.envelope('session_record_balance', idempotency_key, true, false,
      case when (v_check ->> 'quarantine')::boolean then 'would_quarantine' else 'would_write' end,
      'balances', null, jsonb_build_object('args', v_args, 'check', v_check));
  end if;

  v_claim := yuna_priv.claim('session_record_balance', idempotency_key, v_args);
  if (v_claim ->> 'replayed')::boolean then return v_claim -> 'result'; end if;
  v_call := (v_claim ->> 'call_id')::bigint;

  if (v_check ->> 'quarantine')::boolean then
    v_id := yuna_priv.quarantine(v_call, 'session_record_balance', account, v_ccy, 'anchor',
                                 amount, v_day, v_check, note);
    return yuna_priv.finish(v_call,
                            yuna_priv.envelope('session_record_balance', idempotency_key, false,
                                               false, 'quarantined', 'balance_quarantine', v_id,
                                               jsonb_build_object('written', false, 'check', v_check)),
                            'balance_quarantine', v_id);
  end if;

  v_id := yuna_priv.write_balance(v_call, account, v_field, v_ccy, amount, v_day,
                                  false, 'anchor', null);
  return yuna_priv.finish(v_call,
                          yuna_priv.envelope('session_record_balance', idempotency_key, false,
                                             false, 'written', 'balances', v_id,
                                             jsonb_build_object('account', account,
                                                                'currency', v_ccy,
                                                                'field', v_field,
                                                                'amount', amount,
                                                                'as_of', v_day,
                                                                'provisional', false,
                                                                'check', v_check)),
                          'balances', v_id);
end $$;

-- --- 7.5 record cash: the mid-week provisional path -------------------------------------------
-- §2.0: "Weekday NAV extrapolates from the last confirmed balances using price moves —
-- provisional, labeled, trued up Sunday." and "Deposits, dividends, and interest are absorbed
-- automatically without modeling them individually."
--
-- Two things Zak can say, and they are not the same statement:
--   ANCHOR    "TFSA cash is now 94,796.02"  → the balance IS that
--   MOVEMENT  "I deposited $5,000 CAD"      → the balance is last anchor + movements since
--
-- Both write TWO rows: an observation of what he actually said (the words are the primary
-- record — the derived number can always be recomputed from them, and Sunday will), and a
-- provisional balances row carrying the arithmetic. A movement with no anchor to build on writes
-- the observation and a movement row with no balance, because there is no honest number to put
-- there and zero is not a safe guess.
create or replace function api.session_record_cash(
  idempotency_key text,
  account text,
  currency text,
  amount double precision,
  kind text,
  as_of date default null,
  note text default null,
  dry_run boolean default false)
returns jsonb
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
  v_day    date := coalesce(as_of, current_date);
  v_kind   text := lower(btrim(coalesce(kind, '')));
  v_field  text := yuna_priv.balance_field(account, currency);
  v_ccy    text := upper(btrim(currency));
  -- scalars, not a record: for kind='anchor' the lookup below never runs, and reading a field
  -- off an unassigned record variable is an error, not a null
  v_anchor_id   bigint;
  v_anchor_at   date;
  v_anchor_base double precision;
  v_moves  double precision := 0;
  v_new    double precision;
  v_check  jsonb;
  v_args   jsonb;
  v_claim  jsonb;
  v_call   bigint;
  v_id     bigint;
  v_obs    bigint;
  v_said   text;
begin
  if v_kind not in ('anchor','movement') then
    raise exception 'cash kind % is not anchor or movement', coalesce(kind, '<null>')
      using errcode = 'PT400',
            hint = 'anchor = "TFSA cash is now X" · movement = "I deposited X" (§2.0)';
  end if;
  if amount is null then
    raise exception 'a cash statement needs an amount' using errcode = 'PT400';
  end if;
  if v_kind = 'movement' and amount = 0 then
    raise exception 'a movement of zero is not a movement' using errcode = 'PT400';
  end if;
  if v_day > current_date then
    raise exception 'as_of % is in the future', v_day using errcode = 'PT400';
  end if;

  -- The provisional balance this statement implies. For an anchor it is the amount. For a
  -- movement it is the last anchor plus every movement recorded since it, this one included —
  -- §2.0's arithmetic, done in one place and stored so it can be checked.
  if v_kind = 'anchor' then
    v_new := amount;
  else
    select b.id, b.as_of,
           case p.f when 'cash_cad' then b.cash_cad when 'cash_usd' then b.cash_usd
                    else b.drawn end
      into v_anchor_id, v_anchor_at, v_anchor_base
      from balances b, (select v_field as f) p
     where b.account = session_record_cash.account
       and coalesce(b.stated_as, 'anchor') = 'anchor'
       and (case p.f when 'cash_cad' then b.cash_cad when 'cash_usd' then b.cash_usd
                     else b.drawn end) is not null
     order by b.as_of desc, b.id desc
     limit 1;
    if v_anchor_id is not null then
      select coalesce(sum(b.movement_amount), 0) into v_moves
        from balances b
       where b.account = session_record_cash.account
         and b.stated_as = 'movement' and b.movement_currency = v_ccy
         and (b.as_of, b.id) > (v_anchor_at, v_anchor_id);
      v_new := v_anchor_base + v_moves + amount;
    else
      -- No anchor to build on. §2.0's arithmetic is "last anchor + movements since"; with no
      -- last anchor there is no honest number, and zero is not a safe guess. The statement is
      -- still recorded as an observation below — a balance row is not written.
      v_new := null;
    end if;
  end if;

  v_check := yuna_priv.balance_outlier(account, v_ccy, v_field, v_kind, amount);
  v_said  := case when v_kind = 'anchor'
                  then format('%s %s cash is now %s', account, v_ccy, amount)
                  else format('%s %s %s %s', account,
                              case when amount >= 0 then 'deposit of' else 'withdrawal of' end,
                              abs(amount), v_ccy) end;
  v_args  := jsonb_build_object('account', account, 'currency', v_ccy, 'amount', amount,
                                'kind', v_kind, 'as_of', v_day, 'note', note, 'field', v_field);

  if dry_run then
    return yuna_priv.envelope('session_record_cash', idempotency_key, true, false,
      case when (v_check ->> 'quarantine')::boolean then 'would_quarantine' else 'would_write' end,
      'balances', null,
      jsonb_build_object('args', v_args, 'check', v_check, 'said', v_said,
                         'balance', v_new, 'movements_since', v_moves, 'provisional', true,
                         'needs_anchor', v_kind = 'movement' and v_new is null,
                         'anchor', jsonb_build_object('id', v_anchor_id, 'as_of', v_anchor_at,
                                                      'base', v_anchor_base)));
  end if;

  v_claim := yuna_priv.claim('session_record_cash', idempotency_key, v_args);
  if (v_claim ->> 'replayed')::boolean then return v_claim -> 'result'; end if;
  v_call := (v_claim ->> 'call_id')::bigint;

  -- What Zak said, recorded whether or not the number survives the outlier test. §2.0 absorbs
  -- deposits without modeling them individually — but it cannot absorb what was never written
  -- down, and Sunday's reconciliation reads these.
  insert into observations (kind, topic, body, detail, written_by, session_call_id)
  values ('note', format('%s %s cash', account, v_ccy),
          v_said || coalesce(' — ' || note, ''),
          jsonb_build_object('stated_as', v_kind, 'account', account, 'currency', v_ccy,
                             'amount', amount, 'as_of', v_day, 'implies_balance', v_new,
                             'anchor_base', v_anchor_base, 'anchor_as_of', v_anchor_at,
                             'movements_since', v_moves, 'provisional', true) || v_check,
          'session', v_call)
  returning id into v_obs;

  if (v_check ->> 'quarantine')::boolean then
    v_id := yuna_priv.quarantine(v_call, 'session_record_cash', account, v_ccy, v_kind,
                                 amount, v_day, v_check, note);
    return yuna_priv.finish(v_call,
                            yuna_priv.envelope('session_record_cash', idempotency_key, false,
                                               false, 'quarantined', 'balance_quarantine', v_id,
                                               jsonb_build_object('observation_id', v_obs,
                                                                  'written', false,
                                                                  'said', v_said,
                                                                  'check', v_check)),
                            'balance_quarantine', v_id);
  end if;

  -- A movement with no anchor behind it gets the observation and nothing else. Writing a row
  -- with a null cash figure would be worse than writing none: db.nav_cad takes the NEWEST row
  -- per account outright, so a row stating "cash is unknown" would blank the account's cash in
  -- NAV. The observation preserves what Zak said; the next anchor supersedes it anyway, because
  -- "movements since" only counts movements recorded after the anchor.
  if v_new is null then
    return yuna_priv.finish(v_call,
                            yuna_priv.envelope('session_record_cash', idempotency_key, false,
                                               false, 'observed', 'observations', v_obs,
                                               jsonb_build_object('said', v_said,
                                                                  'stated_as', v_kind,
                                                                  'account', account,
                                                                  'currency', v_ccy,
                                                                  'balance', null,
                                                                  'needs_anchor', true,
                                                                  'why', 'no anchor to build on — '
                                                                    'record a balance first '
                                                                    '(session_record_balance)')),
                            'observations', v_obs);
  end if;

  -- The provisional balance row (§2.0 — stated mid-week, labeled, trued up Sunday).
  v_id := yuna_priv.write_balance(v_call, account, v_field, v_ccy, v_new, v_day, true, v_kind,
                                  case when v_kind = 'movement' then amount else null end);

  return yuna_priv.finish(v_call,
                          yuna_priv.envelope('session_record_cash', idempotency_key, false, false,
                                             'written', 'balances', v_id,
                                             jsonb_build_object('observation_id', v_obs,
                                                                'said', v_said,
                                                                'stated_as', v_kind,
                                                                'account', account,
                                                                'currency', v_ccy,
                                                                'balance', v_new,
                                                                'movements_since', v_moves,
                                                                'needs_anchor', false,
                                                                'provisional', true,
                                                                'as_of', v_day)),
                          'balances', v_id);
end $$;

-- --- 7.6 observations -------------------------------------------------------------------------
-- §1: "Every pass and every exit is recorded as a plain observation." §3.1: "Every memo and every
-- decision logged as an observation." §3.2: "every flip is logged as an observation."
create or replace function api.session_record_observation(
  idempotency_key text,
  topic text,
  body text,
  detail jsonb default null,
  kind text default 'note',
  ticker text default null,
  score double precision default null,
  price double precision default null,
  dry_run boolean default false)
returns jsonb
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare v_args jsonb; v_claim jsonb; v_id bigint; v_kind text := lower(btrim(coalesce(kind,'note')));
begin
  if v_kind not in ('pass','exit','gate_flip','c2','breach','learning','note','ruling') then
    raise exception 'observation kind % is not in the vocabulary', kind
      using errcode = 'PT400',
            hint = 'pass · exit · gate_flip · c2 · breach · learning · note · ruling';
  end if;
  if body is null or btrim(body) = '' then
    raise exception 'an observation needs a body — the whole point is the sentence'
      using errcode = 'PT400';
  end if;
  if (topic is null or btrim(topic) = '') and (ticker is null or btrim(ticker) = '') then
    raise exception 'an observation needs a topic or a ticker to be about' using errcode = 'PT400';
  end if;

  v_args := jsonb_build_object('topic', topic, 'body', body, 'detail', detail, 'kind', v_kind,
                               'ticker', ticker, 'score', score, 'price', price);
  if dry_run then
    return yuna_priv.envelope('session_record_observation', idempotency_key, true, false,
                              'would_write', 'observations', null,
                              jsonb_build_object('args', v_args));
  end if;

  v_claim := yuna_priv.claim('session_record_observation', idempotency_key, v_args);
  if (v_claim ->> 'replayed')::boolean then return v_claim -> 'result'; end if;

  insert into observations (kind, topic, ticker, score, price, body, detail,
                            written_by, session_call_id)
  values (v_kind, session_record_observation.topic, session_record_observation.ticker,
          session_record_observation.score, session_record_observation.price,
          session_record_observation.body, session_record_observation.detail,
          'session', (v_claim ->> 'call_id')::bigint)
  returning id into v_id;

  return yuna_priv.finish((v_claim ->> 'call_id')::bigint,
                          yuna_priv.envelope('session_record_observation', idempotency_key, false,
                                             false, 'written', 'observations', v_id,
                                             jsonb_build_object('kind', v_kind, 'topic', topic)),
                          'observations', v_id);
end $$;

-- --- 7.7 record a ruling ----------------------------------------------------------------------
-- A ruling is a decision Zak made, written down so it survives the session (§4.0 — "No number
-- lives in anyone's head between sessions"). §3.1 already says every decision is logged as an
-- observation, so that is where it goes, under kind='ruling'.
--
-- IT HAS NO MECHANICAL EFFECT, and that is a security property, not a limitation. A row saying
-- "Zak ruled that 15% sizing is unlocked" unlocks nothing: §3.1's tier is read from config, and
-- config is protected. Nothing in this codebase reads a ruling row and changes behaviour. The
-- row is attributed to the session that wrote it, never to Zak — see the threat model in
-- docs/write-path.md, where a forged ruling is the most interesting thing a leaked token can do.
create or replace function api.session_rule(
  idempotency_key text,
  topic text,
  ruling text,
  note text default null,
  dry_run boolean default false)
returns jsonb
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare v_args jsonb; v_claim jsonb; v_id bigint;
begin
  if topic is null or btrim(topic) = '' then
    raise exception 'a ruling needs a topic — what was ruled on' using errcode = 'PT400';
  end if;
  if ruling is null or btrim(ruling) = '' then
    raise exception 'a ruling needs the ruling' using errcode = 'PT400';
  end if;

  v_args := jsonb_build_object('topic', topic, 'ruling', ruling, 'note', note);
  if dry_run then
    return yuna_priv.envelope('session_rule', idempotency_key, true, false, 'would_write',
                              'observations', null, jsonb_build_object('args', v_args));
  end if;

  v_claim := yuna_priv.claim('session_rule', idempotency_key, v_args);
  if (v_claim ->> 'replayed')::boolean then return v_claim -> 'result'; end if;

  insert into observations (kind, topic, body, detail, written_by, session_call_id)
  values ('ruling', session_rule.topic, session_rule.ruling,
          jsonb_build_object('note', session_rule.note,
                             'recorded_by', 'session',
                             'attribution', 'reported by a session, not signed by Zak',
                             'effect', 'none — rulings are records; nothing reads them'),
          'session', (v_claim ->> 'call_id')::bigint)
  returning id into v_id;

  return yuna_priv.finish((v_claim ->> 'call_id')::bigint,
                          yuna_priv.envelope('session_rule', idempotency_key, false, false,
                                             'written', 'observations', v_id,
                                             jsonb_build_object('kind', 'ruling', 'topic', topic)),
                          'observations', v_id);
end $$;

-- --- 7.8 config -------------------------------------------------------------------------------
-- config is append-only: a change is a new row (§4.3 — "Weights and thresholds live in the config
-- table — every change is a logged row, not code archaeology"). What a session may set is
-- narrow to the point of being nearly empty, and that is the design: see
-- yuna_priv.config_protection() above for the four gates and their reasoning.
create or replace function api.session_set_config(
  idempotency_key text,
  key text,
  value jsonb,
  note text default null,
  dry_run boolean default false)
returns jsonb
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare v_why text; v_args jsonb; v_claim jsonb; v_id bigint;
begin
  v_why := yuna_priv.config_protection(key);
  if v_why is not null then
    raise exception 'refused: %', v_why
      using errcode = 'PT403',
            hint = 'the plan is law and config is its runtime copy (§4.3). Announce the plan '
                   'edit, then move the number by migration.';
  end if;
  if value is null then
    raise exception 'a config row needs a value' using errcode = 'PT400';
  end if;

  v_args := jsonb_build_object('key', key, 'value', value, 'note', note);
  if dry_run then
    return yuna_priv.envelope('session_set_config', idempotency_key, true, false, 'would_write',
                              'config', null, jsonb_build_object('args', v_args));
  end if;

  v_claim := yuna_priv.claim('session_set_config', idempotency_key, v_args);
  if (v_claim ->> 'replayed')::boolean then return v_claim -> 'result'; end if;

  insert into config (key, value, note, set_by, written_by, session_call_id)
  values (session_set_config.key, session_set_config.value, session_set_config.note,
          'yuna', 'session', (v_claim ->> 'call_id')::bigint)
  returning id into v_id;

  return yuna_priv.finish((v_claim ->> 'call_id')::bigint,
                          yuna_priv.envelope('session_set_config', idempotency_key, false, false,
                                             'written', 'config', v_id,
                                             jsonb_build_object('key', key)),
                          'config', v_id);
end $$;

-- =============================================================================================
-- 8. Human views (§4.3 — what Zak browses in Studio)
-- =============================================================================================
create or replace view v_session_writes as
select c.id, c.called_at, c.session_id, c.verb, c.idempotency_key, c.identified,
       c.target_table, c.target_id, c.result ->> 'action' as action,
       c.args, c.finished_at is null as unfinished
from session_calls c
order by c.called_at desc;

create or replace view v_quarantine as
select q.id, q.at, q.account, q.currency, q.stated_as, q.amount, q.last_amount,
       round(q.ratio::numeric, 2) as ratio, q.as_of, q.reason, q.note, q.resolution,
       c.session_id, c.verb, c.idempotency_key
from balance_quarantine q
left join session_calls c on c.id = q.session_call_id
order by (q.resolution = 'pending') desc, q.at desc;

comment on view v_quarantine is
  'Statements held for review. Anything with resolution=pending belongs in the next brief (§4.1).';

-- =============================================================================================
-- 9. Grants — the surface, stated once, precisely
-- =============================================================================================
-- CREATE FUNCTION grants EXECUTE to PUBLIC by default. On a Supabase project PUBLIC includes
-- `anon`, which is reachable with the publishable key and no login at all. Leaving that default
-- in place would make every verb below callable by the internet. So: revoke from PUBLIC first,
-- then grant to yuna_session only, and set the default privilege so a function added later is
-- not accidentally world-callable while someone forgets this block exists.
do $$
declare f record;
begin
  for f in select p.oid::regprocedure as sig
             from pg_catalog.pg_proc p
             join pg_catalog.pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'api'
  loop
    execute format('revoke all on function %s from public', f.sig);
    execute format('grant execute on function %s to yuna_session', f.sig);
  end loop;
  -- yuna_priv is granted to nobody. The verbs reach it because SECURITY DEFINER runs them as
  -- the owner; a caller cannot reach it at all.
  for f in select p.oid::regprocedure as sig
             from pg_catalog.pg_proc p
             join pg_catalog.pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'yuna_priv'
  loop
    execute format('revoke all on function %s from public', f.sig);
  end loop;
end $$;

alter default privileges in schema api       revoke execute on functions from public;
alter default privileges in schema yuna_priv revoke execute on functions from public;

-- REVOCATION (docs/write-path.md §Revocation). One statement kills the entire path:
--     revoke usage on schema api from yuna_session;
-- EXECUTE on a function is unusable without USAGE on its schema, so every verb dies at once,
-- instantly, for every token already minted, with no restart and nothing to redeploy. The
-- reverse is `grant usage on schema api to yuna_session;`.

-- =============================================================================================
-- 10. Record the decisions this migration had to make
-- =============================================================================================
-- Q4 and Q5 in docs/open-questions.md asked for exactly these two lists. They are implemented as
-- chosen here so the path can be built; they are Zak's to confirm or change, and the observations
-- below are how they stay visible until he does.
insert into observations (kind, topic, body, detail, written_by) values
 ('note', 'session write path — ticket state machine',
  'Q4 answered as built, awaiting Zak. States are 005''s six. Legal transitions: proposed→'
  'approved · proposed→cancelled · proposed→expired · approved→provisional · approved→cancelled · '
  'approved→expired · provisional→confirmed · provisional→cancelled (note required). confirmed, '
  'cancelled and expired are terminal. Everything else is refused. The one likely to bite: '
  'proposed→provisional is NOT legal — a fill on an unapproved ticket takes two calls.',
  '{"question":"Q4","source":"migration 018","authority":"chosen, not ruled",'
  '"terminal":["confirmed","cancelled","expired"]}', 'job'),
 ('note', 'session write path — quarantine thresholds',
  'Q5 answered as built, awaiting Zak. An anchor is quarantined when it moves more than 10,000 '
  'of the stated currency AND lands at 10x or more, or 0.1x or less, of the last known value — '
  'the extra-zero signature. A movement is quarantined at 50,000 or more, or at 10x the last '
  'known balance. Thresholds are constants in the function, not config, because a session that '
  'could widen its own quarantine could defeat it. A typo inside one order of magnitude is not '
  'caught here; Sunday catches it.',
  '{"question":"Q5","source":"migration 018","authority":"chosen, not ruled",'
  '"materiality":10000,"anchor_ratio_hi":10,"anchor_ratio_lo":0.1,"movement_max":50000}', 'job'),
 ('learning', 'session write path — guard triggers do not cover this path',
  'The 005 guard triggers refuse writes when current_user is not the migrator. A SECURITY '
  'DEFINER function runs as its owner, so current_user IS the migrator inside every verb and '
  'the guards pass without comment. They are not a control on this path. Every verb therefore '
  'validates for itself, and no verb touches a guarded table.',
  '{"source":"migration 018","guarded_tables":["universe","prices","candidates","queue","bench",'
  '"book","gate_state","nav_snapshots","earnings","fundamentals","backtest_runs",'
  '"backtest_trades","backtest_equity"],"written_by_this_path":["briefs","tickets",'
  '"observations","balances","config","session_calls","balance_quarantine"]}', 'job');
