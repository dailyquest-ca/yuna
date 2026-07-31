-- 024_split_adjust.sql — a split rewrites the bars; it must also rewrite the position.
--
-- Found by an integration test that was asserting something else. §4.1 says a split triggers a
-- re-pull of the name's adjusted history, and it does — but `book` stores avg_cost, stop,
-- stop_limit, highest_close and pivot in nominal dollars, and §3.2 says stops ratchet UP and never
-- down. So after a 4:1 split a stop of 90 sits against a price of 25, cannot be lowered by the
-- ratchet, and the position reads as permanently stopped out. Every night. Forever.
--
-- The marker below lets the nightly job apply each action to the book exactly once.

alter table corporate_actions add column if not exists applied_to_book_at timestamptz;
comment on column corporate_actions.applied_to_book_at is
  'when the nightly job re-based the affected position''s stored prices — null means not yet';
