-- 022_position_identity.sql — a position remembers its own pivot and its full-size target.
--
-- Found in review of the Phase I code, before either mistake reached a real order:
--
--   1. The pyramid and the unconfirmed-breakout hair-trigger were reading the pivot from `queue`.
--      That is the *current* base's pivot, which re-scans nightly and disappears entirely when the
--      name leaves the queue. A position must be judged against the pivot it was entered on —
--      §3.2's "a close back below the pivot" means *its* pivot, not tonight's.
--   2. `book.target_qty` existed and nothing ever set it, so every pyramid add ticket would have
--      carried a null quantity. The full-size target belongs on the ticket that arms the entry and
--      travels to the book row on the fill.
--
-- §3.2's first position is 50% of full size; without these two columns the machine could not have
-- pyramided at all, and would have had no honest way to know when a breakout had failed.

alter table book add column if not exists pivot double precision;
comment on column book.pivot is
  '§3.2 the pivot this position was entered on — the reference for the hair-trigger and the pyramid';

alter table tickets add column if not exists target_qty double precision;
comment on column tickets.target_qty is
  '§3.2 full-size quantity; the entry ticket itself buys 50% and steps 2-3 size off this';

comment on column book.adds_12m is
  'lifetime add counter, informational only — the authoritative 12-month count for §3.1''s two-add
   limit is computed from `transactions` inside a rolling window, because a counter that only ever
   increments becomes a permanent block after the second add';
