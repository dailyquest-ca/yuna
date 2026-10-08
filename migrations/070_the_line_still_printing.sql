-- 070_the_line_still_printing.sql — 2026-10-07. §3.2's rename rule, applied to the one row that
-- broke it: Tempur Sealy (TPX.US) became Somnigroup (SGI.US), and 041 kept the dead symbol.
--
-- §3.2: duplicate listings are "ticker renames where the vendor carries both the dead line and the
-- live one; keep the line still printing". 041 wrote this row the other way round —
--     ('SGI.US', 'duplicate_listing', 'same series as TPX.US (Tempur Sealy renamed); keep TPX')
-- — though its own header names the direction of the rename, "TPX -> SGI". 050 then carried it
-- under "permanent facts, re-checked and unchanged", and it is the one rename row in that file
-- decided against the successor: BLL, HFC and RFMD beside it each keep the line still printing.
-- Which line still prints is a fact about the tape, and the tape was not re-read.
--
-- Measured on production, read-only, 2026-10-07 (QC finding A17):
--   SGI.US   5,314 bars   2005-08-19 .. 2026-10-06   active; prints every session
--   TPX.US   2,140 bars   2016-08-12 .. 2025-02-14   delisted; no bar since
--   2,139 shared sessions, raw close identical on all 2,139. TPX's span lies inside SGI's. One TPX
--   bar has no SGI twin (2023-04-06), and that one session is all the swap gives up.
-- So since 2026-08-12 the live universe has held NEITHER line: SGI.US is excluded here and TPX.US
-- is filtered as delisted (`desk.TAPE`). Somnigroup — $62.74 at the 10-06 close, a 50-session
-- median of $198M a day — has never been ranked. §3.2: "Excluding a real, tradable common stock
-- for any editorial reason is a strategy change and requires a ruling"; no ruling names SGI, TPX,
-- Tempur or Somnigroup (107 rulings read). Tonight's sheet does not move: $198M is under the
-- pool's 500th name ($216M on 10-06), so the name passes the screen and misses the pool.
--
-- A swap, not a bare delete. The backtests keep the delisted on purpose, so deleting SGI.US's row
-- alone would put BOTH lines on the historical tape for 2016-08 .. 2025-02 — one company in two
-- slots, the double holding of runs 29, 32 and 34-36 that 041 was written to stop. Excluding
-- TPX.US is what `dedupe_scan.py` would have chosen: `keeper()` keeps the later last bar, and
-- `covered()` admits an exclusion only when the kept line's span covers the dropped one's.
--
-- Zak signs off before this is dispatched. It follows §3.2's own rule, and it ADMITS a tradable
-- common stock rather than excluding one, but it changes the universe the engine ranks, and
-- `migrate` applies every pending file at once. Signed off by Zak in chat on 2026-10-07, asked to
-- confirm that SGI.US is the line still printing and TPX.US the dead one: "Sounds good, I trust
-- you."
--
-- For whoever re-runs the cell of record on this tape: SGI.US's volume from 2016-08-23 to
-- 2020-11-23 is a quarter of TPX.US's on identical closes — a raw share count, where learning 34
-- relies on the vendor's volume being split-adjusted (Tempur split 4:1 on 2020-11-24). The live
-- desk reads the last 50 sessions and is untouched; a backtest's ADDV for the name reads 4x low
-- across those four years, so name that window, or re-pull the line, before differencing run 589.

-- The premise, asserted rather than assumed: evidence baked into a migration goes stale the moment
-- the data moves (learning 35). If TPX.US ever prints past SGI.US, §3.2 would keep TPX, this file's
-- reason is gone, and it refuses rather than applying the opposite of the rule it cites.
do $$
begin
  if (select max(d) from prices where ticker = 'TPX.US')
     > (select max(d) from prices where ticker = 'SGI.US') then
    raise exception '070: TPX.US prints later than SGI.US, so §3.2 keeps TPX — re-measure first';
  end if;
end $$;

delete from universe_excluded where ticker = 'SGI.US' and reason = 'duplicate_listing';

insert into universe_excluded (ticker, reason, detail) values
  ('TPX.US', 'duplicate_listing',
   'same series as SGI.US (2139 of 2139 shared closes identical, 2016-08-12..2025-02-14) — Tempur '
   'Sealy renamed Somnigroup, and SGI.US is the line still printing, which §3.2 keeps. Replaces '
   '041''s row, which kept TPX (QC 2026-10-07, A17)')
on conflict (ticker) do nothing;
