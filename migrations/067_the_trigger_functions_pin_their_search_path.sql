-- 067_the_trigger_functions_pin_their_search_path.sql — 2026-09-15. Three functions, one setting.
--
-- Supabase's linter (function_search_path_mutable): a function without its own search_path
-- resolves every unqualified name against the CALLER's search_path, so a role that can set its
-- search_path can put a table or function of its own in front of the real one. 059 already pinned
-- yuna_book_from_ledger to `public`; the two guard triggers and the verdict function never were.
-- The exposure is small — the public roles lost every grant in 066 and these run as the owner or
-- yuna_session — and the fix is one line each, the same line 059 used.
alter function yuna_jobs_only()               set search_path = public;
alter function yuna_ledger_moves_the_book()   set search_path = public;
alter function yuna_verdict(text)             set search_path = public;
