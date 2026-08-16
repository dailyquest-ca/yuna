-- 056_two_rulings_on_the_exclusions.sql — 2026-08-16. Zak's rulings on 050's held-back rows.
--
-- Migration 050 left five rows unapplied and said each needed one measurement rather than a
-- judgement. The census ran those measurements against the current tape today. Zak ruled on both
-- questions, 2026-08-16:
--
--   1. *"If the defect is gone then we can allow them."*
--   2. *"You tell me. I don't really care."*
--
-- This is those two rulings, applied.

-- ---- 1. APPS.US and BDN.US are released -----------------------------------------------------
--
-- 041 quarantined them on an "identical 653-bar series" between two unrelated companies, and its
-- own text said *"pending a re-pull"*. The re-pull has happened. Today's census measured them over
-- **762 shared sessions and they are not the same series** — the vendor defect is gone.
--
-- They were not merely unapplied; 041 IS applied in production, so this exclusion has been live and
-- two tradable common stocks have been outside §3.2's universe on evidence that no longer holds.
-- §3.2 permits exactly four categories of exclusion and "a defect the vendor has since fixed" is
-- not one of them, so leaving them out would be a strategy change wearing a hygiene costume.
--
-- VGNT.US is deliberately NOT released. The same census measured it against its own warrant and
-- they ARE still one series over 96 shared sessions — the vendor is still serving one line's prices
-- for both, so VGNT.US's own prices remain unreliable. Zak's ruling was conditional on the defect
-- being gone; for this pair it is not.
delete from universe_excluded where ticker in ('APPS.US', 'BDN.US');

-- ---- 2. the bankruptcy-continuation pairs ----------------------------------------------------
--
-- §3.2 says "keep the line still printing". Neither of these lines is: TBSI.US and TBSIQ.US both
-- end 2012-04-16, and VVUS.US and VVUSQ.US both end 2020-12-14. The clause does not reach them and
-- the last-print does not break the tie, which is exactly why 050 held them back rather than
-- guessing. Zak: *"You tell me. I don't really care."*
--
-- **The `Q` line goes, in both cases, and the reason is what the suffix means.** A trailing `Q` is
-- appended by the exchange to a company in Chapter 11. It marks a status, not a security — the
-- company's own ticker is the unsuffixed one, and it is the line that carries the primary history.
-- Excluding the marker keeps the company.
--
-- The two pairs are not equally consequential and the difference is stated rather than smoothed:
--
--   TBSI / TBSIQ   one series (100.0% of 1,675 shared sessions). Either could be kept and no
--                  backtest could tell the difference. The rule above decides it on principle
--                  rather than on a coin.
--   VVUS / VVUSQ   NOT one series — 96.1% over 3,853 shared sessions, so ~4% of sessions differ.
--                  Something is genuinely dropped here. What it is: 3,853 shared sessions is far
--                  more history than a Chapter 11 window, which means the vendor back-filled the
--                  `Q` symbol with the base line's own past and then diverged on the tail. Keeping
--                  VVUS keeps the company's real series; the discarded tail belongs to a line that
--                  was already dead.
--
-- Both are delisted, so neither reaches today's ranking — `desk.py` filters `status = 'delisted'`.
-- This binds on the historical tape, which is where §3.2's one-company-one-line rule is enforced
-- and where `verify_run.py` B7 found concurrent holdings of one company in two of five slots.
insert into universe_excluded (ticker, reason, detail) values
  ('TBSIQ.US', 'duplicate_listing',
   'same series as TBSI.US (100.0% of 1675 shared sessions); Q marks Chapter 11 status, not a '
   'security — keep the company''s own ticker. Ruled by Zak 2026-08-16'),
  ('VVUSQ.US', 'duplicate_listing',
   'same company as VVUS.US (96.1% of 3853 shared sessions); Q marks Chapter 11 status, and the '
   'shared history far exceeds a bankruptcy window — the vendor back-filled this symbol with the '
   'base line''s past. Keep VVUS. Ruled by Zak 2026-08-16')
on conflict (ticker) do nothing;
