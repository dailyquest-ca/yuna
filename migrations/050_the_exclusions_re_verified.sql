-- 050_the_exclusions_re_verified.sql — 2026-08-16.
--
-- Zak ruled 2026-08-16: "re-verify and apply what survives." This is what survives, plus what the
-- WO-A22 audit found afterwards. **041 is never dispatched** — its DDL already landed as 049, and
-- its rows are superseded by this file.
--
-- The sorting principle is whether a row's evidence can GO STALE. A preferred share stays a
-- preferred share and a share-class spelling stays a spelling, so those rows are as true today as
-- when they were written. A quarantine that says "pending a re-pull" is a claim about the tape on
-- one particular day, and the tape has been re-fetched since.
--
-- §3.2 permits exactly four categories and every row below is one of them: duplicate listings,
-- non-common equity, quarantined vendor defects, and exchange test symbols. Excluding a real,
-- tradable common stock for any editorial reason would be a strategy change needing a ruling, and
-- nothing here is that.

-- ---- carried from 041: permanent facts, re-checked and unchanged -------------------------------
insert into universe_excluded (ticker, reason, detail) values
  ('SGI.US',      'duplicate_listing', 'same series as TPX.US (Tempur Sealy renamed); keep TPX'),
  ('PENG_old.US', 'duplicate_listing', 'same series as SGH.US; keep SGH'),
  ('GEFB.US',     'duplicate_listing', 'share-class spelling of GEF-B.US'),
  ('HPE-PC.US',   'duplicate_listing', 'share-class spelling of HPE-P-C.US'),
  ('FOUR-PA.US',  'duplicate_listing', 'share-class spelling of FOUR-P-A.US'),
  ('HPE-P-C.US',  'not_common_equity', 'preferred share'),
  ('FOUR-P-A.US', 'not_common_equity', 'preferred share'),
  ('GEF-B.US',    'not_common_equity', 'class B share line, thin secondary listing'),
  ('VGNT-W.US',   'not_common_equity', 'warrant')
on conflict (ticker) do nothing;

-- ---- new: the foreign listings, WO-A22 §8 ------------------------------------------------------
--
-- Not US securities at all. They carry `.US` tickers and `currency = USD` in the vendor's
-- metadata while trading in Moscow, Istanbul and Bangkok, so their price x volume is computed in
-- the foreign currency and compared against a $10M threshold — Polyus showed $426m of median
-- "dollar volume" and cleared the liquidity gate on an FX rate. The book traded them.
--
-- Zak, 2026-08-16: *"We can only trade on the US stock market, don't care what name someone has or
-- currency if it seems like it's US."*
--
-- Excluded BY NAME rather than by a rule, deliberately. The exchange filter cannot be built —
-- `universe.exchange` holds 'US' for all 6,332 stocks, because it is EODHD's bulk-feed bucket and
-- not a listing venue (§8.1). And the calendar-participation rule that FOUND them needs a
-- threshold nobody has ruled, and over-fires on ordinary US names with patchy history (§8.2).
-- Four names on stated evidence beats a threshold on none.
insert into universe_excluded (ticker, reason, detail) values
  ('PLZL.US',  'not_common_equity', 'Polyus — trades on MOEX in roubles; not a US listing'),
  ('NVTK.US',  'not_common_equity', 'Novatek — trades on MOEX in roubles; not a US listing'),
  ('MGROS.US', 'not_common_equity', 'Migros Ticaret — trades in Istanbul in lira; not a US listing'),
  ('IVL.US',   'not_common_equity', 'Indorama Ventures — trades on the SET in baht; not a US listing')
on conflict (ticker) do nothing;

-- ---- new: duplicate pairs the audit measured on the CURRENT tape -------------------------------
--
-- `verify_run.py` B7 found these held CONCURRENTLY in run 589 — one company in two of five slots,
-- at 1.25x the intended weight, with every cap counting it twice. Agreement is on daily RETURNS
-- over shared sessions, which is the invariant migrations 047 and 048 got wrong in opposite
-- directions (047 exact-equality on closes missed BBBY at 98.72%; 048 kept a 1e-9 tolerance that
-- measures vendor rounding rather than securities — learnings 35).
--
-- §3.2's rule for which line goes: "keep the line still printing". Each of these is a rename or a
-- merger where the surviving symbol is unambiguous.
insert into universe_excluded (ticker, reason, detail) values
  ('BLL.US',      'duplicate_listing',
   'same daily returns as BALL.US (99.4% of 1445 shared sessions) — Ball Corp renamed; keep BALL'),
  ('HFC.US',      'duplicate_listing',
   'same daily returns as DINO.US (100.0% of 1405) — HollyFrontier became HF Sinclair; keep DINO'),
  ('BBBY_old.US', 'duplicate_listing',
   'same daily returns as BBBY.US (97.7% of 2273) — vendor carries the dead line; keep BBBY'),
  ('RFMD.US',     'duplicate_listing',
   'same daily returns as QRVO.US (95.3% of 2377) — RF Micro Devices merged into Qorvo; keep QRVO')
on conflict (ticker) do nothing;

-- ---- NOT carried, and why ---------------------------------------------------------------------
--
-- Five rows are deliberately absent, because applying them would mean asserting something this
-- file cannot currently show. Each needs one measurement, not a judgement:
--
--   VGNT.US, APPS.US, BDN.US  — 041's three `quarantine` rows. Its own APPS/BDN entry says
--     "pending a re-pull", and the re-pull has since happened. If the vendor corruption is gone,
--     applying these would permanently exclude two live, tradable common stocks for a defect that
--     no longer exists — which §3.2 calls a strategy change, not hygiene. **Re-run the identical-
--     series test against the current tape before restoring them.**
--
--   TBSI.US/TBSIQ.US, VVUS.US/VVUSQ.US — real duplicate pairs (100.0% of 1675 and 96.1% of 3853),
--     but the `Q` suffix marks a bankruptcy continuation and BOTH lines are dead. §3.2 says keep
--     the line still printing; when neither is, the rule does not decide, and guessing which
--     symbol to drop would be inventing the answer. **Determine which line prints later and
--     exclude the other.**
--
-- Both are one query each. They are held back rather than approximated because an exclusion is
-- permanent in effect: a name that is wrongly excluded never gets ranked, never gets traded, and
-- leaves no trace of what it would have done.
