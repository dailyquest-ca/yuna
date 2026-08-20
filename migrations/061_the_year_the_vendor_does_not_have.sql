-- 061_the_year_the_vendor_does_not_have.sql — 2026-08-20. Two exclusions, with the evidence paid
-- for tonight rather than assumed.
--
-- The roadmap carried LDG and SGT as "each missing roughly a contiguous year (252 and 251
-- sessions). A re-fetch." — the assumption being that the hole was OURS, left by some earlier
-- ingest, and one dispatch would fill it. The dispatch ran (backfill 2026-08-20, `what=bars,
-- years=10, tickers=LDG.US,SGT.US, resweep=true`): the vendor returned 2,281 rows, the upsert
-- wrote them, and the bar counts did not move — 1,146 and 1,147, exactly what we already held.
-- The hole is the VENDOR's. Measured on the tape as it stands:
--
--   LDG.US   no prints 2020-12-11 -> 2021-12-14   (368 calendar days)
--   SGT.US   no prints 2018-12-14 -> 2019-12-16   (367 calendar days)
--
-- A year-long void inside a series is not a quiet year — it is a span where any position would be
-- unmarkable and any formation window a fiction. The discontinuity guard already quarantines both
-- names on every research run for exactly this; the exclusion makes that per-run re-discovery a
-- recorded fact instead, which is what §7's changelog sanctions: "Exclusions are data-hygiene
-- only." Both names are delisted, so the LIVE universe never sees them regardless (`status <>
-- 'delisted'`) — this touches the research tape alone.
--
-- Reversible like every 049-family row: if the vendor ever backfills the year, delete the row and
-- the census picks them back up. §0.6 note: this excludes, it deletes no bars.

insert into universe_excluded (ticker, reason, detail) values
  ('LDG.US', 'vendor_gap',
   'No prints 2020-12-11 -> 2021-12-14 (368 calendar days, ~252 sessions). Re-fetched 2026-08-20 '
   '(backfill: bars, 10y, resweep) — vendor returned 2,281 rows for the pair, bar count unchanged '
   'at 1,146. The hole is upstream and cannot be repaired from here.'),
  ('SGT.US', 'vendor_gap',
   'No prints 2018-12-14 -> 2019-12-16 (367 calendar days, ~251 sessions). Re-fetched 2026-08-20 '
   'alongside LDG.US — bar count unchanged at 1,147. Same upstream hole.')
on conflict (ticker) do nothing;
