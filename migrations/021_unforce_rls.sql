-- 021_unforce_rls.sql — undo a mistake in 020 before it can bite.
--
-- 020 used `force row level security` on the four session-writable tables. FORCE applies RLS to
-- the table OWNER as well, and the only policies there name `yuna_session` — so on any Postgres
-- where the job role is not BYPASSRLS, the nightly job would stop being able to write its own
-- brief and its own observations. The heartbeat would go red on the last line of the night, after
-- every conclusion had already been computed. Exactly the kind of silent-until-it-matters trap the
-- plan's guard-trigger design was chosen to avoid.
--
-- The write boundary does not need FORCE. It is already enforced twice:
--   1. guard triggers reject any write to a computed table from a non-owner role;
--   2. `yuna_session` holds grants on four tables and nothing else.
-- Plain `enable row level security` keeps the default-deny posture for anon/public while leaving
-- the owner — the jobs — free to write. That is what §4.3 describes.

alter table briefs        no force row level security;
alter table tickets       no force row level security;
alter table observations  no force row level security;
alter table transactions  no force row level security;

insert into observations (kind, ticker, body, detail)
select 'note', null,
       'Migration 020 set FORCE row level security on briefs/tickets/observations/transactions, '
       'which would have applied RLS to the job role itself and broken the nightly brief write on '
       'any Postgres where that role lacks BYPASSRLS. Reverted in 021. The boundary still holds: '
       'guard triggers plus yuna_session grants.',
       '{"migration":"021","reverted":"force row level security","tables":["briefs","tickets","observations","transactions"]}'::jsonb
 where not exists (select 1 from observations where body like 'Migration 020 set FORCE row level security%');
