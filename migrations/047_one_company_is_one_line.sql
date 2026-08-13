-- 047 · one company is one line
--
-- 045 excluded two duplicate series found by hand (LAZR_old, TRCH). This is the same defect at
-- its real size, found by asking the ledger a question rather than reading a report: on
-- 2021-01-04 every concentrated cell held BBBY.US, BBBY_old.US, OSTK.US and BYON.US at once —
-- four slots of twelve, 33% of a "twelve-name" book, all of it Overstock, through the meme
-- window those slots returned +82.5% in. On 2022-01-03 the same books held MMC.US and MRSH.US,
-- which is Marsh McLennan twice.
--
-- The cause is a vendor convention, not bad data: when a listing changes its symbol, EODHD
-- back-fills the NEW symbol with the whole history and ALSO keeps the old symbol carrying that
-- same history up to the rename. Both lines are real, both are in `universe` as active stocks,
-- and their closes agree to the cent. A rank over the census therefore scores one company twice
-- and a concentrated book can buy it twice.
--
-- The shape is completely regular, which is what makes the rule derivable rather than chosen:
-- in every group the surviving line runs to the last stored session and the retired line stops
-- at the rename. Measured on the eight sampled dates below, before this file was written:
--
--   FISV.US  (2,518 bars, to 2026-08-12)  vs  FI.US        (2,325, to 2025-11-10)
--   MRSH.US  (2,518 bars, to 2026-08-12)  vs  MMC.US       (2,368, to 2026-01-13)
--   B.US     (2,518 bars, to 2026-08-12)  vs  GOLD_old.US  (2,345, to 2025-12-09)
--   BNY.US   (2,518 bars, to 2026-08-12)  vs  BK.US        (2,456, to 2026-05-20)
--   BBBY.US  (2,518 bars, to 2026-08-12)  vs  BBBY_old.US / BYON.US (2,274, to 2025-08-29)
--   ... and fifteen more groups above $20M median dollar volume, plus a tail below it.
--
-- So: keep the line with the LATEST last bar; ties go to the line with more bars, then to the
-- lower ticker. Exclude the rest. That rule is computed here rather than transcribed, because a
-- hand-list of thirty-odd symbols is a hand-list that rots — and the computation records what it
-- decided, ticker by ticker, in `detail`.
--
-- Two guards make the match strict enough to trust with an exclusion:
--
--   1. the eight sampled dates must agree on at least six (a coincidence across six specific
--      closes, to the cent, on two different companies does not happen), AND
--   2. over the FULL overlapping range the two lines must agree on at least 99% of their shared
--      sessions — the test that would fail if a sampled agreement were an accident.
--
-- Third check, run before this file was written, because it is the one way this could do harm:
-- no excluded line begins earlier than the line kept in its place. Zero of the 35 groups lose a
-- single session of history — the retired symbol is always a truncation of the survivor, never a
-- longer tail. (`select ... where m.first_bar < kp.first_bar` returns no rows.)
--
-- Same remedy as 041 and 045: exclusion, not deletion. The bars stay, the reason is on the
-- record with the numbers that produced it, and deleting one row readmits a name.
--
-- 35 lines are excluded here, of which one (LAZR_old.US) 045 already had — the `on conflict`
-- keeps 045's hand-written reason for that one rather than overwriting it.

with sig as (
  -- the signature: closes on eight sessions spread across the window
  select ticker, string_agg(close::text, '|' order by d) k, count(*) c
    from prices
   where d in ('2018-06-01','2019-06-03','2020-06-01','2021-06-01',
               '2022-06-01','2023-06-01','2024-06-03','2025-06-02')
     and close is not null
   group by ticker
  having count(*) >= 6                                            -- guard 1
),
grp as (select k from sig group by k having count(*) > 1),
member as (
  select s.k, s.ticker, count(*) bars, max(p.d) last_bar
    from sig s
    join grp g on g.k = s.k
    join prices p on p.ticker = s.ticker
   group by s.k, s.ticker
),
keeper as (
  select distinct on (k) k, ticker, bars, last_bar
    from member
   order by k, last_bar desc, bars desc, ticker
),
-- guard 2: the full-overlap agreement, computed only for the candidates
verified as (
  select m.k, m.ticker, m.bars, m.last_bar, kp.ticker keep_ticker, kp.bars keep_bars,
         kp.last_bar keep_last,
         count(*) shared,
         count(*) filter (where a.close = b.close) agree
    from member m
    join keeper kp on kp.k = m.k and kp.ticker <> m.ticker
    join prices a on a.ticker = m.ticker
    join prices b on b.ticker = kp.ticker and b.d = a.d
   group by m.k, m.ticker, m.bars, m.last_bar, kp.ticker, kp.bars, kp.last_bar
  having count(*) > 0 and count(*) filter (where a.close = b.close)::numeric / count(*) >= 0.99
)
insert into universe_excluded (ticker, reason, detail)
select ticker, 'duplicate_listing',
       format('same series as %s (%s of %s overlapping closes identical); %s runs to %s with %s bars against this line''s %s to %s — keep the line that is still printing',
              keep_ticker, agree, shared, keep_ticker, keep_last, keep_bars, bars, last_bar)
  from verified
on conflict (ticker) do nothing;
