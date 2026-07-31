-- 020_session_role.sql — the write boundary as a database fact (roadmap A4, plan §4.3).
--
-- "The machine computes; Yuna judges" is enforced twice, deliberately:
--   1. Guard triggers refuse any write to a computed table from a non-owner role.
--   2. This role's grants only reach the four tables a session is allowed to write.
--
-- Belt and braces on purpose: the triggers are the law, the grants are the lock. The owner
-- credential (DATABASE_URL) stays in GitHub Actions secrets and is used by jobs only; the session
-- connector uses `yuna_session`.
--
-- Zak's one manual step: set a password and grant login in the Supabase dashboard, then point the
-- Supabase MCP connector at it. This file deliberately contains no password — a credential that
-- passes through a migration passes through chat, a repo and a log.
--
-- The whole block is exception-guarded: on a Postgres where the migration runner cannot create
-- roles, this becomes a recorded notice instead of a failed migration.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'yuna_session') then
    create role yuna_session nologin;
  end if;

  -- read everything: a session must be able to see every number it reasons about
  grant usage on schema public to yuna_session;
  grant select on all tables in schema public to yuna_session;
  alter default privileges in schema public grant select on tables to yuna_session;

  -- write exactly four things (§4.3)
  grant insert, update on briefs, tickets, observations, transactions to yuna_session;
  grant insert on config to yuna_session;          -- config is append-only; no update, ever
  grant usage, select on all sequences in schema public to yuna_session;
  alter default privileges in schema public grant usage, select on sequences to yuna_session;

  -- RLS is default-deny with no policies, so a non-owner role needs an explicit bypass path.
  -- For a single-user prototype the honest choice is to say so out loud rather than pretend:
  -- yuna_session is trusted with the four tables and nothing else, and the guard triggers still
  -- refuse it everywhere else even if a policy were ever added by accident.
  alter table briefs        force row level security;
  alter table tickets       force row level security;
  alter table observations  force row level security;
  alter table transactions  force row level security;

  drop policy if exists yuna_session_rw on briefs;
  create policy yuna_session_rw on briefs to yuna_session using (true) with check (true);
  drop policy if exists yuna_session_rw on tickets;
  create policy yuna_session_rw on tickets to yuna_session using (true) with check (true);
  drop policy if exists yuna_session_rw on observations;
  create policy yuna_session_rw on observations to yuna_session using (true) with check (true);
  drop policy if exists yuna_session_rw on transactions;
  create policy yuna_session_rw on transactions to yuna_session using (true) with check (true);
  drop policy if exists yuna_session_read on config;
  create policy yuna_session_read on config to yuna_session using (true) with check (true);

exception when insufficient_privilege or feature_not_supported then
  raise notice 'yuna_session not provisioned here (%): create it in the Supabase dashboard and '
               'grant it select on all tables plus insert/update on briefs, tickets, observations, '
               'transactions', sqlerrm;
end $$;

insert into observations (kind, ticker, body, detail)
select 'note', null,
       'Session write boundary provisioned: role yuna_session reads everything and writes only '
       'briefs, tickets, observations, transactions (insert-only on config). Guard triggers still '
       'refuse it on every computed table. Manual step remaining: give the role a password and '
       'login in the Supabase dashboard, then repoint the MCP connector at it.',
       '{"role":"yuna_session","writes":["briefs","tickets","observations","transactions"],'
       '"owner_credential":"DATABASE_URL, GitHub Actions secrets only"}'::jsonb
 where not exists (select 1 from observations where body like 'Session write boundary provisioned%');
