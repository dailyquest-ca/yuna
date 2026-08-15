"""The duplicate-listing scan, run as a job rather than transcribed into a migration.

Three migrations have now attacked this defect — 045 by hand, 047 on sampled closes, 048 on
sampled daily returns — and each one ran, wrote a plausible number of rows, and left behind the
case its own header called out. That is the pattern worth fixing, not the individual misses:

  * **047** compared closes with `a.close = b.close`, exact float equality, at a 99% bar. Its own
    headline example, BBBY_old against BBBY, agrees on 2,245 of 2,274 shared closes — 98.72%. It
    missed by 0.28 points, on sub-cent vendor rounding, and the migration reported success.
  * **048** moved to daily returns, which is the right invariant, but kept `abs(ra - rb) < 1e-9`
    at a 99% bar. On the current tape that threshold splits the duplicate population down the
    middle: SPWR_old/SPWRQ scores 0.467 exact and 0.952 at 1e-4; BALL/BLL scores 0.0015 exact and
    0.994 at 1e-4. Both are one company. 048 recorded BBBY as unfixable residue — "plainly one
    listing, and plainly below any threshold this file could defend" — which was true of the tape
    it ran against and is not true of the tape after the backfill re-fetched those series.
  * **both** sampled 2018-2025 only. The delisted census now reaches 2005, so every pair that
    died before 2018 — ANR/ANRZ, WLT/WLTGQ, TBSI/TBSIQ — has no signature at all and cannot be
    caught by either file however good its threshold is.

So the scan lives here, where it can be re-run against whatever the tape currently is, and it
**reports the distribution before it proposes anything**. The threshold is read off the gap
between the two populations in that distribution; it is not a number chosen in advance. If the
gap is not there, the scan says so and proposes nothing — see `THRESHOLD_MIN_GAP`.

Dispatch-only. `SCAN_APPLY=true` writes the exclusions; the default reports and writes nothing.
"""
import os
import sys

from db import connect

# A session where neither line moved more than 5bps is not evidence: a flat day agrees with every
# other flat day. 048 established this and it holds.
MOVED = 0.0005
# Returns are compared at 1e-4 — one basis point. Two lines quoted in cents on a $30 stock differ
# in the fifth decimal of a daily return from rounding alone, which is what defeated 048's 1e-9.
# A genuinely different security does not agree to a basis point on 85% of its sessions.
TOL = 1e-4
MIN_SHARED = 250         # 048 used 500; the pre-2018 delisted lines are shorter than that
MIN_PROBE_HITS = 4
# The scan refuses to propose a threshold unless the two populations are separated by at least
# this ratio. Placing a cut inside a continuum is fitting; placing one inside a gap is reading.
THRESHOLD_MIN_GAP = 3.0
# ...and the gap must be the widest by DIFFERENCE, not by ratio. Agreement is a proportion in
# [0,1], and on that scale a ratio is dominated by the bottom: 0.0060 to 0.0513 is 8.6x, clears
# the bar above, and both numbers mean the two lines agree on essentially nothing. On 2026-08-14
# that produced a proposed cut of 0.0175 — two series are the same company if they agree on 1.75%
# of their moving sessions — and put GOLD_old.US (Randgold, 0.0516) up for deletion in favour of
# GOLD.US (Barrick). Proportions are compared by difference; ratios belong to quantities with a
# meaningful zero and an unbounded range.
#
# The difference metric alone is not enough, because it says nothing about WHERE the gap sits. A
# cut is a claim that the lines above it are THE SAME SERIES, and two lines that agree on less
# than half their moving sessions disagree more often than they agree. That is not a fitted
# threshold, it is the logical floor of the claim being made: the scan may not assert sameness of
# series that mostly differ. So the population above the gap must clear one half.
MIN_SAMENESS = 0.5


def probe_anchors(cur, every=120):
    """Session pairs spread across the benchmark's whole history, derived rather than listed.

    047 and 048 both hard-coded eight dates in 2018-2025 and both were silently blind outside it.
    Taking the anchors from SPY's own session list means the scan covers whatever the tape covers.
    """
    cur.execute("""with spy as (select d, row_number() over (order by d) rn
                                  from prices where ticker = 'SPY.US')
                   select (select max(d) from spy b where b.rn = a.rn - 1) as p, a.d as q
                     from spy a where a.rn %% %s = 0 and a.rn > 1
                    order by a.d""", (every,))
    return [r for r in cur.fetchall() if r[0] is not None]


def candidates(cur, anchors):
    """Pairs agreeing on at least MIN_PROBE_HITS of the sampled returns.

    This is only a prefilter — it decides what is worth the full-overlap comparison, nothing else.
    Rounding to 5dp here is deliberately coarser than TOL so the prefilter cannot be the thing
    that rejects a real pair.
    """
    cur.execute("set local statement_timeout = '900s'")
    cur.execute("""
        with anchor(p, q) as (select unnest(%s::date[]), unnest(%s::date[])),
             px as (select ticker, d, coalesce(adj_close, close) c from prices
                     where coalesce(adj_close, close) > 0),
             pr as (select x.ticker, an.q, round((y.c / x.c - 1)::numeric, 5) r
                      from anchor an
                      join px x on x.d = an.p
                      join px y on y.ticker = x.ticker and y.d = an.q
                     where abs(y.c / x.c - 1) > %s),
             u as (select ticker from universe where kind = 'stock' and ticker like '%%.US')
        select a.ticker, b.ticker
          from pr a
          join pr b on b.q = a.q and b.r = a.r and b.ticker > a.ticker
          join u ua on ua.ticker = a.ticker
          join u ub on ub.ticker = b.ticker
         group by 1, 2 having count(*) >= %s""",
        ([a[0] for a in anchors], [a[1] for a in anchors], MOVED, MIN_PROBE_HITS))
    return cur.fetchall()


def score(cur, pairs):
    """The full-overlap agreement on daily returns, for every candidate pair."""
    cur.execute("set local statement_timeout = '900s'")
    cur.execute("""
        with pair(t1, t2) as (select unnest(%s::text[]), unnest(%s::text[])),
             px as (select ticker, d, coalesce(adj_close, close) c from prices
                     where coalesce(adj_close, close) > 0),
             j as (select p.t1, p.t2, a.d,
                          a.c / nullif(lag(a.c) over (partition by p.t1, p.t2 order by a.d), 0) - 1 ra,
                          b.c / nullif(lag(b.c) over (partition by p.t1, p.t2 order by a.d), 0) - 1 rb
                     from pair p
                     join px a on a.ticker = p.t1
                     join px b on b.ticker = p.t2 and b.d = a.d)
        select t1, t2,
               count(*) shared,
               count(*) filter (where greatest(abs(ra), abs(rb)) > %s) moving,
               count(*) filter (where greatest(abs(ra), abs(rb)) > %s and abs(ra - rb) < %s) agree
          from j
         where ra is not null and rb is not null
         group by t1, t2""",
        ([p[0] for p in pairs], [p[1] for p in pairs], MOVED, MOVED, TOL))
    out = []
    for t1, t2, shared, moving, agree in cur.fetchall():
        if shared < MIN_SHARED or not moving:
            continue
        out.append((t1, t2, shared, moving, agree / moving))
    return out


def widest_gap(fracs):
    """The largest gap between consecutive scores, and where it sits.

    Reported so the threshold is visibly read off the data. Returns (lo, hi, ratio) — lo is the
    best score BELOW the gap and hi the worst score above it, so any cut in (lo, hi] separates the
    same two populations. The ratio comes back for the caller's separation test and for the
    exclusion's stated reason, but it is NOT what selects the gap.

    Selection is by DIFFERENCE. See MIN_SAMENESS: on a [0,1] agreement scale the widest ratio sits
    wherever the smallest numbers are, and the smallest numbers are exactly where the score has
    stopped meaning anything.
    """
    xs = sorted(f for f in fracs if f > 0)
    if len(xs) < 2:
        return None
    best = None
    for lo, hi in zip(xs, xs[1:]):
        if best is None or (hi - lo) > (best[1] - best[0]):
            best = (lo, hi, hi / lo if lo > 0 else float("inf"))
    return best


def reused_ticker_pairs(cur):
    """`X_old.US` against `X.US` — the vendor's OWN marker that a symbol was reused.

    This pass exists because the general scan cannot cut and is right not to: across all 471
    candidate pairs the distribution is continuous, the widest gap is 1.6x, and a threshold read
    off that would be fitted. But the tape carries 178 `_old` tickers, and the suffix is not a
    score — it is EODHD stating that this symbol carried a different company before. That is
    categorical evidence, and it makes a much narrower population worth scoring on its own.

    The suffix alone is not enough to exclude, which is the whole reason the agreement test still
    runs. `WTW_old` is Weight Watchers and `WTW` is Willis Towers Watson: two genuinely different
    companies, agreeing on 0.15% of their moving sessions, and dropping either would delete real
    history. Within this population the two cases separate cleanly, so the cut is read from this
    subpopulation's own widest gap by exactly the same rule the general scan uses.

    Measured 2026-08-14: runs 484 and 491 both held BBBY_old.US and BBBY.US AT THE SAME TIME in
    February 2018 — one company, two of five slots, and every cap counting it as two names.
    """
    # Only pairs where the surviving line COVERS the `_old` one end to end. 047's guard refuses any
    # exclusion that would drop a line starting before the one kept in its place, and it is right
    # to — so a pass that proposes such a pair is proposing something it cannot defend, and one
    # undefendable pair kills the whole run. `CBIO_old.US` is exactly that: it starts before
    # `CBIO.US`, and it reached the proposal list because the gap-finder's cut swept up the middle
    # of this distribution along with the clean duplicates.
    #
    # Coverage is the right filter rather than a tighter score, because it is the guard's own
    # question asked in advance. It is also why the clean cases pass: the `_old` series all begin
    # at 2016-08-12, the backfill boundary, while several bases reach back to 2005.
    cur.execute("""
        with pair as (select u.ticker as old_t, replace(u.ticker, '_old', '') as base_t
                        from universe u
                       where u.ticker like '%%!_old.US' escape '!'
                         and exists (select 1 from universe b
                                      where b.ticker = replace(u.ticker, '_old', ''))),
             span as (select ticker, min(d) a, max(d) b from prices group by ticker)
        select p.old_t, p.base_t
          from pair p join span o on o.ticker = p.old_t
                      join span s on s.ticker = p.base_t
         where s.a <= o.a and s.b >= o.b
           and exists (select 1 from prices x join prices y on y.ticker = p.base_t and y.d = x.d
                        where x.ticker = p.old_t)""")
    # ordered as the scorer expects (t1 < t2) so the returned rows line up with `score`
    return [tuple(sorted(r)) for r in cur.fetchall()]


def keeper(cur, tickers, already=frozenset()):
    """047's rule, unchanged and still the right one: keep the line that is still printing.

    Later last bar, then more bars, then the lower ticker. A total order, so a group always has
    exactly one winner.

    `already` is the set of lines a previous pass has EXCLUDED, and they are not eligible to be
    kept. Its comment claimed a winner "is never itself excluded", which was true only while the
    scan ran once against a clean list: on 2026-08-14 the reused-symbol pass proposed dropping
    `GCI_old.US` in favour of `GCI.US`, which an earlier pass had already excluded, and 048's guard
    correctly halted the whole run rather than let the group vanish. Nominating a dead line is the
    defect; the guard behind it stays exactly as it is, and still fires if a group has no live
    line left at all.
    """
    live = [t for t in tickers if t not in already] or list(tickers)
    cur.execute("""select ticker, count(*) bars, max(d) last_bar
                     from prices where ticker = any(%s) group by ticker""", (live,))
    rows = {t: (bars, last) for t, bars, last in cur.fetchall()}
    return max(live, key=lambda t: (rows[t][1], rows[t][0], [-ord(c) for c in t]))


def main():
    apply = os.environ.get("SCAN_APPLY", "").strip().lower() == "true"
    with connect() as conn:
        with conn.cursor() as cur:
            anchors = probe_anchors(cur)
            print(f"probe anchors: {len(anchors)} session pairs, "
                  f"{anchors[0][1]} .. {anchors[-1][1]}")
            pairs = candidates(cur, anchors)
            print(f"candidate pairs: {len(pairs)}")
            scored = score(cur, pairs)
            print(f"scored pairs (>= {MIN_SHARED} shared sessions): {len(scored)}")

            # the distribution, before any threshold is applied to it
            buckets = [0.0, 0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.85, 0.90, 0.95, 0.99, 1.01]
            print("\nagreement on daily returns to 1e-4, over moving sessions:")
            for lo, hi in zip(buckets, buckets[1:]):
                n = sum(1 for s in scored if lo <= s[4] < hi)
                if n:
                    print(f"  [{lo:.2f}, {hi:.2f})  {n:5d}  {'#' * min(n, 60)}")

            # The reused-symbol pass, scored and thresholded on its own population. It runs whether
            # or not the general scan can cut, because its candidates are named by the vendor
            # rather than found by correlation.
            # Each pass carries its OWN cut and says so in the exclusion it writes. A single global
            # threshold would have made the reused-symbol proposals cite the census gap that did
            # not produce them, and an exclusion whose stated reason is not its actual reason is
            # how the last three attempts at this defect went stale.
            def cut_from(population, label):
                g = widest_gap([s[4] for s in population])
                if not g:
                    print(f"  {label}: nothing to threshold")
                    return None, None
                lo, hi, ratio = g
                print(f"  {label}: widest gap {lo:.4f} -> {hi:.4f} "
                      f"({hi - lo:.4f} wide, {ratio:.1f}x)")
                if ratio < THRESHOLD_MIN_GAP:
                    print(f"    not separated by {THRESHOLD_MIN_GAP}x — a cut here would be "
                          f"fitted, not read. Proposing nothing from this pass.")
                    return None, None
                if hi < MIN_SAMENESS:
                    print(f"    the population above the gap agrees on only {hi:.1%} of its "
                          f"moving sessions, under {MIN_SAMENESS:.0%}. Calling those lines the "
                          f"same series would assert sameness of series that mostly differ. "
                          f"Proposing nothing from this pass.")
                    return None, None
                c = (lo * hi) ** 0.5                     # geometric midpoint of the gap
                print(f"    threshold {c:.4f} (geometric midpoint)")
                return c, ratio

            dups, why = [], {}
            reused = score(cur, reused_ticker_pairs(cur))
            print(f"\nreused symbols (`_old`, the vendor's own marker): {len(reused)} pairs scored")
            rcut, rratio = cut_from(reused, "reused") if reused else (None, None)
            if rcut is not None:
                hit = [s for s in reused if s[4] >= rcut]
                dups += hit
                for s in hit:
                    why[(s[0], s[1])] = f"threshold {rcut:.4f} read from a {rratio:.1f}x gap in " \
                                        f"the reused-symbol population"
                print(f"    {len(hit)} pairs are one company under two symbols")

            print("\nthe whole census:")
            cut, ratio = cut_from(scored, "census")
            if cut is not None:
                hit = [s for s in scored if s[4] >= cut and (s[0], s[1]) not in why]
                dups += hit
                for s in hit:
                    why[(s[0], s[1])] = f"threshold {cut:.4f} read from a {ratio:.1f}x gap in " \
                                        f"the census distribution"

            if not dups:
                print("\nno proposals from either pass")
                return 0
            groups = {}
            for t1, t2, *_ in dups:
                g = groups.setdefault(t1, {t1})
                g.add(t2)
                groups[t2] = g
            # Read BEFORE choosing keepers, not after: a line an earlier pass already excluded is
            # not a candidate to keep, and nominating one is what killed run 31855520505.
            cur.execute("select ticker from universe_excluded")
            already = {r[0] for r in cur.fetchall()}

            seen, proposals = set(), []
            for g in groups.values():
                key = tuple(sorted(g))
                if key in seen:
                    continue
                seen.add(key)
                keep = keeper(cur, g, already)
                for t in sorted(g - {keep}):
                    proposals.append((t, keep))

            fresh = [(t, k) for t, k in proposals if t not in already]
            print(f"\n{len(proposals)} lines in {len(seen)} groups; {len(fresh)} not already excluded")

            # The guard 048 added after 047 came one row from deleting a company: never exclude a
            # line in favour of one that is itself excluded.
            bad = [(t, k) for t, k in fresh if k in already]
            if bad:
                raise RuntimeError(f"keeper is itself excluded for {bad} — the group would vanish")

            # And 047's third check, which it ran by hand and did not encode: no excluded line may
            # start earlier than the line kept in its place, or history is lost rather than deduped.
            cur.execute("""select ticker, min(d) from prices
                            where ticker = any(%s) group by ticker""",
                        (list({t for t, _ in fresh} | {k for _, k in fresh}),))
            first = dict(cur.fetchall())
            loses = [(t, k) for t, k in fresh if first.get(t) and first.get(k) and first[t] < first[k]]
            if loses:
                raise RuntimeError(f"these lines start before the line kept in their place, so "
                                   f"excluding them would lose history: {loses}")

            for t, k in fresh:
                print(f"  {t:16s} -> keep {k}")

            if not apply:
                print("\nSCAN_APPLY is not true — nothing written")
                return 0
            score_by = {(t1, t2): (sh, mv, f) for t1, t2, sh, mv, f in dups}
            for t, k in fresh:
                sh, mv, f = score_by.get((t, k)) or score_by.get((k, t)) or (0, 0, 0.0)
                prov = why.get((t, k)) or why.get((k, t)) or "no threshold recorded"
                cur.execute("""insert into universe_excluded (ticker, reason, detail)
                               values (%s, 'duplicate_listing', %s)
                               on conflict (ticker) do nothing""",
                            (t, f"same daily returns as {k} ({f:.4f} of {mv} moving sessions agree "
                                 f"to {TOL:g}, over {sh} shared); {prov}"))
            conn.commit()
            print(f"\nwrote {len(fresh)} exclusions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
