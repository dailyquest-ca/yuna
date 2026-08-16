-- 053_the_screen_before_the_pool.sql — 2026-08-16. What §4.4's second gauge actually measures.
--
-- §4.4 gauges "screen survivor count within historical band". `engine_sessions.ranked_count` is
-- the wrong number for it: §3.2 caps the pool at the top 500 by ADDV, so on any ordinary session
-- the count is exactly 500 and stays exactly 500 while the tape rots underneath it. A gauge that
-- reads 500 every night whatever happens is not a gauge.
--
-- `screen_count` is the uncensored number — how many names passed §3.2's four tests before the cap
-- was applied. That one moves with the tape: a failed ingest, a currency defect, a delisting sweep
-- and a vendor restatement all change it, and none of them change `ranked_count` at all.

alter table engine_sessions
  add column if not exists screen_count integer;

comment on column engine_sessions.screen_count is
  'S3.2 survivors BEFORE the top-500 pool cap. S4.4 gauges this, not ranked_count, which is '
  'censored at 500 on any ordinary session and therefore cannot move when the tape breaks.';
