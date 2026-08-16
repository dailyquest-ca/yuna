-- 044_a_warrant_is_not_a_stock.sql — 2026-08-12. WO-0.
--
-- Found by the tape guard halting run WO-0, then by asking what it had actually caught.
--
-- `kind='stock'` is the gate on the tradeable universe — §3.2's candidate set — and it is read in
-- five places including `arming.py:1324`, which is the LIVE path. Anything sitting in `kind='stock'`
-- with `in_l0` can be proposed to Zak as a momentum candidate. 123 instruments in that set are not
-- common stock: warrants, when-issued lines, rights, SPAC units and preferred series. **25 of them
-- carried `in_l0 = true`**, so they were armable today.
--
-- The tape guard found five of them the hard way: ACHR-WS, IONQ-WS, JOBY-WS, MPTI-WS and NUVB-WS
-- each serve a price series byte-identical to their own common — 0 differing bars out of 176. The
-- book could hold the warrant and the common as two names, doubling one position while max_names,
-- the sleeve cap and the heat cap each counted two. That is the TPX/SGI failure of runs 29-36,
-- arriving through a different door.
--
-- A warrant is not a stock. It is a leveraged, expiring claim on one — different economics,
-- different risk, and nothing §3.2's trend template or MCN was written to score. The same goes for
-- rights, units and preferreds: a preferred share is a bond wearing equity's clothing and does not
-- trend. None of these belong in a momentum candidate set.
--
-- **Dual-class common is deliberately untouched.** BRK-A, BRK-B, BF-B, GEF-B, BH-A and their kind
-- are ordinary common stock and stay exactly where they are. The filter was checked against them
-- before it was run: of the 11 matches that end in -A/-B/-C/-K, every one is a `-P-` preferred
-- series or a `-WS-` warrant (KODK-WS-A names itself "Wt Exp 135%"), and no true share class is
-- caught. That check is the whole reason this is a regex on the security-type segment rather than
-- on "has a hyphen".

update universe set kind = case
    when ticker ~ '-P[A-Z]?(-|\.US$)'   then 'preferred'
    when ticker ~ '-(WS|WT)(-|\.US$)'   then 'warrant'
    when ticker ~ '-WI(-|\.US$)'        then 'when_issued'
    when ticker ~ '-W(-|\.US$)'         then 'warrant'
    when ticker ~ '-R(-|\.US$)'         then 'right'
    when ticker ~ '-(UN|U)(-|\.US$)'    then 'unit'
  end
where kind = 'stock'
  and ticker ~ '-(WS|WT|WI|W|R|UN|U|P[A-Z]?)(-|\.US$)';

-- No row may be left with a null kind by the CASE above — if the WHERE clause and the CASE ever
-- drift apart, that is a silent hole in the universe gate rather than an error, so assert it.
do $$
declare orphans int;
begin
  select count(*) into orphans from universe where kind is null;
  if orphans > 0 then
    raise exception '044 left % universe rows with a null kind — the CASE and the WHERE disagree',
      orphans;
  end if;
end $$;

comment on column universe.kind is
  'Security type. ''stock'' is the §3.2 tradeable gate (see arming.py) and means COMMON stock only. '
  'Dual-class common (BRK-A, BF-B) is stock; warrant / when_issued / right / unit / preferred are '
  'not, and are held here only so their prices stay available as reference. See 044.';
