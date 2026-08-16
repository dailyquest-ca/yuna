-- 049_the_exclusion_table.sql — 2026-08-15.
--
-- The TABLE only. None of the rows.
--
-- `041_the_universe_is_deduplicated.sql` creates `universe_excluded` and immediately fills it with
-- twelve hand-curated exclusions. Three tools read the table — `verify_run.py` (check B2: no trade
-- may name an excluded ticker), `dedupe_scan.py` (read the excluded set BEFORE nominating keepers,
-- which is the bug that killed run 31855520505) and `capture_audit.py` — and none of them can run
-- against a database that does not have it. The tools are ready to merge; the twelve rows are not.
--
-- They are not ready because **evidence baked into a migration goes stale the moment the data
-- moves** (learning 35), and the tape has been re-fetched since 041 was written. Its APPS/BDN
-- quarantine says "pending a re-pull" in as many words. Each row needs re-checking against the
-- current census before it is applied, and that is a separate, deliberate act.
--
-- So the DDL lands here and the data waits. 041 stays exactly as written: its `create table if not
-- exists` becomes a no-op once this has run, its inserts are `on conflict do nothing`, and its RLS
-- and trigger statements are already idempotent. Applying it later is still correct and still
-- applies precisely the twelve rows it always did.
--
-- An empty exclusion table is the honest default. It means "nothing has been ruled out yet", which
-- is true, rather than "these twelve were ruled out on evidence someone last checked in August".

create table if not exists universe_excluded (
  ticker text primary key,
  reason text not null,
  detail text,
  excluded_at timestamptz not null default now()
);

alter table universe_excluded enable row level security;
drop trigger if exists guard_universe_excluded on universe_excluded;
create trigger guard_universe_excluded before insert or update or delete on universe_excluded
  for each row execute function yuna_jobs_only();
