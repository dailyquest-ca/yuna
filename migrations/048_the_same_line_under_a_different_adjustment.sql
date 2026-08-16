-- 048 · the same line under a different adjustment
--
-- 047 caught 35 duplicate listings and missed the ones that mattered most, for two reasons that
-- are worth writing down because both are easy to repeat:
--
--   1. **The signature was built from the dates a ticker HAS.** It concatenated closes over
--      whichever of eight sampled sessions the line printed on. Two lines with different coverage
--      therefore produce different-length strings and never group, however identical they are.
--      SQ.US ends 2025-01-21 and XYZ.US runs to 2026-08-12, so SQ had seven sampled closes
--      against XYZ's eight — and the pair sailed through, despite 2,122 shared sessions with
--      2,122 identical closes. The concentrated book then held Block twice: `lg8_semi_trail`
--      bought SQ.US *and* XYZ.US on 2017-08-15, two slots of eight, +71.4% each.
--
--   2. **It compared closes.** 045 had already recorded why that is the weaker test — a merger or
--      a re-listing changes the adjustment base, so the levels differ while the RETURNS are the
--      same returns. The bankruptcy lines are the bulk of this shape: RAD/RADCQ, CONN/CONNQ,
--      IRBT/IRBTQ, LL/LLFLQ, VTNR/VTNRQ, CUTR/CUTRQ, GRTS/GRTSQ, PRET/PRETQ, FSRN/FSRNQ.
--
-- So this file signs on DAILY RETURNS over a FIXED date vector, padding a missing session rather
-- than dropping it. Returns are scale-invariant, which fixes (2); the padding fixes (1).
--
-- Same three guards as 047, one tightened and one added:
--   * six of the eight sampled returns must match, and a session where both lines moved less than
--     5 bps does not count as evidence (a flat day agrees with every other flat day)
--   * over the FULL overlap the two must share at least 500 sessions and agree on 99% of their
--     daily returns to 1e-9
--   * no excluded line may begin earlier than the line kept in its place
--   * NEW: a group whose keeper is ALREADY excluded is skipped entirely. 047 had no such guard
--     and came within one row of deleting a company from the census — it excluded SGH.US as a
--     duplicate of PENG_old.US, which a previous migration had itself excluded in favour of
--     SGH.US. That group survived only because the live line, PENG.US, sits outside it.
--
-- Recorded residue, not fixed here: BBBY_old.US and BBBY.US share 2,274 sessions and agree on
-- 1,972 closes — 86.7%, plainly one listing, and plainly below any threshold this file could
-- defend as a rule. Forcing the threshold down to catch it would start excluding genuinely
-- different companies. It needs a corporate-actions source rather than a similarity test, and
-- until there is one the concentrated book can still hold Bed Bath & Beyond twice. That is a
-- known, bounded overstatement in every A4 cell that held it (2021-01-04 to 2021-01-29).

with pairs(p, q) as (
  values ('2018-05-31'::date,'2018-06-01'::date), ('2019-05-31','2019-06-03'),
         ('2020-05-29','2020-06-01'), ('2021-05-28','2021-06-01'),
         ('2022-05-31','2022-06-01'), ('2023-05-31','2023-06-01'),
         ('2024-05-31','2024-06-03'), ('2025-05-30','2025-06-02')
),
px as (
  select ticker, d, coalesce(adj_close, close) c
    from prices
   where coalesce(adj_close, close) > 0
     and d in (select p from pairs union select q from pairs)
),
tick as (select distinct ticker from px),
-- the fixed vector: one slot per sampled pair, 'x' where the line did not print or did not move
sig as (
  select t.ticker,
         string_agg(coalesce(case when abs(b.c / a.c - 1) > 0.0005
                                  then round((b.c / a.c - 1)::numeric, 6)::text end, 'x'),
                    '|' order by pr.q) k,
         count(*) filter (where a.c is not null and b.c is not null
                            and abs(b.c / a.c - 1) > 0.0005) moved
    from tick t
   cross join pairs pr
    left join px a on a.ticker = t.ticker and a.d = pr.p
    left join px b on b.ticker = t.ticker and b.d = pr.q
   group by t.ticker
  having count(*) filter (where a.c is not null and b.c is not null
                            and abs(b.c / a.c - 1) > 0.0005) >= 6
),
grp as (select k from sig group by k having count(*) > 1),
member as (
  select s.k, s.ticker, count(*) bars, min(p.d) first_bar, max(p.d) last_bar
    from sig s join grp g on g.k = s.k join prices p on p.ticker = s.ticker
   group by s.k, s.ticker
),
-- the keeper is chosen only from lines that are not ALREADY excluded, so a group can never be
-- emptied; a group with no eligible keeper is skipped rather than half-excluded
keeper as (
  select distinct on (k) k, ticker, bars, first_bar, last_bar
    from member
   where ticker not in (select ticker from universe_excluded)
   order by k, last_bar desc, bars desc, ticker
),
ret as (
  select ticker, d,
         coalesce(adj_close, close)
           / nullif(lag(coalesce(adj_close, close)) over (partition by ticker order by d), 0)
           - 1 r
    from prices
   where coalesce(adj_close, close) > 0
     and ticker in (select ticker from member)
),
verified as (
  select m.ticker, m.bars, m.last_bar, kp.ticker keep_ticker, kp.bars keep_bars,
         kp.last_bar keep_last,
         count(*) shared, count(*) filter (where abs(a.r - b.r) < 1e-9) agree
    from member m
    join keeper kp on kp.k = m.k and kp.ticker <> m.ticker
    join ret a on a.ticker = m.ticker and a.r is not null
    join ret b on b.ticker = kp.ticker and b.d = a.d and b.r is not null
   where m.ticker not in (select ticker from universe_excluded)
     and m.first_bar >= kp.first_bar                       -- never drop the longer tail
   group by m.ticker, m.bars, m.last_bar, kp.ticker, kp.bars, kp.last_bar
  having count(*) >= 500
     and count(*) filter (where abs(a.r - b.r) < 1e-9)::numeric / count(*) >= 0.99
)
insert into universe_excluded (ticker, reason, detail)
select ticker, 'duplicate_listing',
       format('same daily returns as %s (%s of %s overlapping sessions identical to 1e-9); %s runs to %s with %s bars against this line''s %s to %s — keep the line that is still printing',
              keep_ticker, agree, shared, keep_ticker, keep_last, keep_bars, bars, last_bar)
  from verified
on conflict (ticker) do nothing;
