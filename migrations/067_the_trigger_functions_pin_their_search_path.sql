-- 067_the_trigger_functions_pin_their_search_path.sql — 2026-09-15. Three functions, one setting.
--
-- Supabase's linter (function_search_path_mutable): a function without its own search_path
-- resolves every unqualified name against the CALLER's search_path, so a role that can set its
-- search_path can put a table or function of its own in front of the real one. 059 already pinned
-- yuna_book_from_ledger to `public`; the two guard triggers and the verdict function never were.
-- The exposure is small — the public roles lost every grant in 066 and these run as the owner or
-- yuna_session — and the fix is one line each, the same line 059 used.
--
-- Two things a later migration must know. `create or replace function` REPLACES the setting, so
-- a redefinition of any of these (yuna_jobs_only has been restated three times to grow its write
-- list) must carry `set search_path = public` in the definition, the way 059 wrote
-- yuna_book_from_ledger; `test_public_key_locked_out.py` fails the suite if any function in
-- public is left unpinned, so the omission cannot ship in silence. And a SET clause stops Postgres
-- inlining yuna_verdict (a `language sql immutable` function) into the rulings views that call
-- it: each call becomes a real call. The rulings table is a hundred rows; accepted.
alter function yuna_jobs_only()               set search_path = public;
alter function yuna_ledger_moves_the_book()   set search_path = public;
alter function yuna_verdict(text)             set search_path = public;
