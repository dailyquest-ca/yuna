-- 025 — one row per day, one legislated state.
--
-- Two shapes the schema allowed and the plan does not.
--
-- nav_snapshots (§4.3, "Daily NAV, provisional until Sunday") is keyed only on its own id, so every
-- run of `duties` appended another row for the same date. Production carried EIGHT rows for
-- 2026-07-31 spanning C$1,017 of NAV — 199,936.88 to 200,954.12 — and nothing in the schema said
-- which one was the day's NAV. The grain is the date; the constraint now says so and the writer
-- upserts.
--
-- queue.state was unconstrained text, so `WATCH` — a state that appears nowhere in the plan — was
-- written by the weekly rank and read by nobody. §3.2 legislates BUY and WAIT for momentum; the
-- holdings seats carry HOLD. Three values, enforced by the database rather than by memory.

-- ---------- nav_snapshots: collapse the duplicates, then forbid them ----------
delete from nav_snapshots a
 using nav_snapshots b
 where a.d = b.d
   and (a.computed_at, a.id) < (b.computed_at, b.id);

alter table nav_snapshots
  add constraint nav_snapshots_d_key unique (d);

-- ---------- queue: the legislated states, and nothing else ----------
update queue set state = 'WAIT' where state = 'WATCH';

alter table queue
  add constraint queue_state_legislated
  check (state in ('BUY', 'WAIT', 'HOLD'));
