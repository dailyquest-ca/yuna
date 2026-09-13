-- 066_the_public_key_is_locked_out.sql — 2026-09-13. The Data API's public roles lose every grant.
--
-- Supabase exposes the `public` schema over its REST API to two roles anyone holding the project's
-- publishable key can assume: `anon` and `authenticated`. By default both hold every privilege on
-- every table and view the owner creates. Row level security is what stands between them and the
-- rows — RLS with no policy is a locked door, and every migration since 001 has enabled it on the
-- tables it created — but three things had slipped past (Supabase linter, 2026-09-13):
--   * seven tables created since 051 never enabled RLS: engine_sessions, engine_ranks,
--     levered_tranches, shadow_attestations, research_eps, research_monthly_adj,
--     research_monthly_raw_contaminated. The public key could read AND write the engine's own
--     sessions and ranks — the rows the morning brief renders.
--   * every view runs with its owner's rights (a Postgres view bypasses the reader's RLS), so the
--     public key could read v_session_payload, v_book, v_ledger_positions and the rest: the desk.
--   * yuna_book_from_ledger is SECURITY DEFINER and, like every function, executable by PUBLIC.
--
-- Nothing of Zak's uses the public key (ruled 2026-09-13): the chat and the Routines reach the
-- database through the Supabase connector, which arrives as the owner or as `yuna_session`; the
-- jobs use DATABASE_URL. So the key gets nothing. RLS is enabled where it was missing, the two
-- public roles lose every table, view, sequence and function grant they hold and the default
-- privileges that would hand them the next table, and the ledger function is callable only by the
-- roles with a reason to call it: the owner, and `yuna_session` whose ledger insert fires it.
--
-- Guarded: `anon` and `authenticated` are Supabase roles. On a plain Postgres they exist only if
-- the harness creates them (tests/integration/conftest.py does, so CI exercises this path); the
-- RLS half applies everywhere.

-- `if exists`: the three research tables were created by the research tooling in production and
-- never by a migration, so a throwaway database (CI, local_pg.sh) does not have them.
alter table if exists engine_sessions                   enable row level security;
alter table if exists engine_ranks                      enable row level security;
alter table if exists levered_tranches                  enable row level security;
alter table if exists shadow_attestations               enable row level security;
alter table if exists research_eps                      enable row level security;
alter table if exists research_monthly_adj              enable row level security;
alter table if exists research_monthly_raw_contaminated enable row level security;

do $$
declare r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke all privileges on all tables    in schema public from %I', r);
      execute format('revoke all privileges on all sequences in schema public from %I', r);
      execute format('revoke all privileges on all functions in schema public from %I', r);
      -- the defaults are what granted every past table to these roles the moment it was created;
      -- without this line the next migration's table is public again
      execute format('alter default privileges for role %I in schema public revoke all on tables    from %I', current_user, r);
      execute format('alter default privileges for role %I in schema public revoke all on sequences from %I', current_user, r);
      execute format('alter default privileges for role %I in schema public revoke all on functions from %I', current_user, r);
    end if;
  end loop;
end $$;

-- A function is executable by PUBLIC by default, and PUBLIC includes the two roles above, so a
-- revoke from them alone changes nothing. 059 made this one SECURITY DEFINER so a session's
-- ledger insert can move the book it may not write; the trigger runs as the inserting role, so
-- that role — and only that role, beside the owner — keeps EXECUTE.
revoke execute on function yuna_book_from_ledger(text, text) from public;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'yuna_session') then
    grant execute on function yuna_book_from_ledger(text, text) to yuna_session;
  end if;
end $$;

insert into observations (kind, ticker, body, detail)
select 'note', null,
       'Migration 066 locked the Data API''s public roles (anon, authenticated) out of every table, '
       'view, sequence and function in public, enabled row level security on the seven tables that '
       'had shipped without it since 051, and made yuna_book_from_ledger executable only by the '
       'owner and yuna_session. Nothing of Zak''s used the public key (ruled 2026-09-13).',
       '{"migration":"066","rls_enabled":["engine_sessions","engine_ranks","levered_tranches","shadow_attestations","research_eps","research_monthly_adj","research_monthly_raw_contaminated"],"revoked_from":["anon","authenticated"]}'::jsonb
 where not exists (select 1 from observations where body like 'Migration 066 locked the Data API%');
