"""What exchange is each name actually listed on — and can we trust the answer?

Zak, 2026-08-16: *"Can't we just use like... NYSE and NASDAQ as a filter?"*

Yes, and it beats the participation gate, which infers "not a US listing" from a name missing too
much of SPY's calendar. That is a statistical proxy needing a threshold nobody has ruled, and it
can fire on a real US stock that halted for a stretch. The exchange is a fact, already stored since
`001_core.sql`, and a filter on it needs no threshold at all.

**But the vendor got `currency` wrong on exactly the names at issue** — it labelled roubles as USD,
which is how Polyus cleared a $10M liquidity gate on an FX rate. So `exchange` is a claim from the
same source and gets checked rather than trusted. This prints the census so the allow-list is
written against what the column HOLDS, not against what it ought to hold.

READ-ONLY. No INSERT, UPDATE, DELETE or COMMIT — it reports, and the exclusion decision stays a
ruling.

    DATABASE_URL=... python src/exchange_census.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from db import connect                                                    # noqa: E402

# The names `verify_run.py` B4 flagged on run 589 — the ones this census has to explain. If the
# exchange column separates these from the rest, the filter works; if it calls them NYSE, it does
# not, and the participation gate stays load-bearing.
SUSPECTS = ("RXDX.US", "LDG.US", "SGT.US", "NBIS.US", "AOI.US", "MGROS.US",
            "PLZL.US", "IVL.US", "NVTK.US", "SUG.US")


def main():
    with connect() as conn:
        with conn.cursor() as cur:
            print("=== every exchange value in the stock universe ===")
            cur.execute("""select coalesce(exchange, '(null)'), count(*),
                                  count(*) filter (where status = 'active')
                             from universe where kind = 'stock'
                            group by 1 order by 2 desc""")
            rows = cur.fetchall()
            total = sum(r[1] for r in rows)
            for ex, n, live in rows:
                print(f"  {ex:<24} {n:>6}  ({live} active)  {n / total:6.2%}")
            print(f"  {'TOTAL':<24} {total:>6}")

            print("\n=== the names B4 flagged, and what the column says about them ===")
            cur.execute("""select ticker, coalesce(exchange,'(null)'), coalesce(currency,'(null)'),
                                  status, name
                             from universe where ticker = any(%s) order by ticker""",
                        (list(SUSPECTS),))
            found = cur.fetchall()
            for tk, ex, ccy, st, nm in found:
                print(f"  {tk:<12} exchange={ex:<16} currency={ccy:<6} {st:<10} {nm[:38]}")
            missing = set(SUSPECTS) - {r[0] for r in found}
            if missing:
                print(f"  not in universe at all: {', '.join(sorted(missing))}")

            # The question the census exists to answer. If every flagged name sits outside NYSE and
            # NASDAQ, an allow-list is sufficient and no threshold is needed. If any sits INSIDE
            # them, the vendor's exchange is as unreliable as its currency was and the participation
            # gate has to stay.
            print("\n=== would an NYSE/NASDAQ allow-list have caught them? ===")
            cur.execute("""select coalesce(exchange,'(null)'), count(*)
                             from universe where ticker = any(%s) group by 1 order by 2 desc""",
                        (list(SUSPECTS),))
            for ex, n in cur.fetchall():
                verdict = "CAUGHT" if ex.upper() not in ("NYSE", "NASDAQ") else "**LET THROUGH**"
                print(f"  {ex:<24} {n:>3}  {verdict}")

            # And the cost of the filter on the other side: how much of the tradeable universe an
            # allow-list would remove. A filter that drops a third of the pool is a strategy change
            # wearing a hygiene costume, and §3.2 says so.
            print("\n=== what an NYSE/NASDAQ-only universe would cost ===")
            cur.execute("""select count(*) filter (where upper(coalesce(exchange,'')) in
                                                         ('NYSE','NASDAQ')),
                                  count(*)
                             from universe where kind = 'stock' and status = 'active'""")
            keep, live = cur.fetchone()
            print(f"  active stocks {live}, kept by NYSE/NASDAQ only: {keep} "
                  f"({keep / live:.1%}) — dropped: {live - keep}")
            # ---- reused tickers -------------------------------------------------------------
            #
            # RXDX was Ignyta until Roche bought it in 2018, then the symbol was reissued to
            # Prometheus Biosciences in 2021 — one ticker, two companies, 777 missing sessions in
            # between. It was found by accident while explaining a B4 flag, and nothing in this
            # repo looks for the class.
            #
            # It is the worst tape defect available, worse than a mis-stated split: a 252-session
            # formation window spanning the gap computes (adj[i-21] / adj[i-252] - 1) across TWO
            # UNRELATED COMPANIES, and §3.3 makes that number the entire opinion. The engine cannot
            # tell; the score is arithmetically valid and economically meaningless.
            #
            # A quarter of dead sessions is far past any halt or suspension, so the gap threshold
            # needs no calibration — it is not a tuned parameter, it is "obviously not trading".
            print("\n=== one ticker, two companies: dead runs longer than a quarter ===")
            cur.execute("""
                with span as (select p.ticker, min(p.d) a, max(p.d) b
                                from prices p join universe u on u.ticker = p.ticker
                               where u.kind = 'stock' group by p.ticker),
                miss as (select s.ticker, bm.d,
                                row_number() over (partition by s.ticker order by bm.d) rn
                           from span s
                           join prices bm on bm.ticker = 'SPY.US' and bm.d between s.a and s.b
                          where not exists (select 1 from prices p
                                             where p.ticker = s.ticker and p.d = bm.d)),
                runs as (select ticker, count(*) len, min(d) from_d, max(d) to_d
                           from (select ticker, d, rn, d - (rn * interval '1 day') grp
                                   from miss) g
                          group by ticker, grp)
                select r.ticker, r.len, r.from_d, r.to_d,
                       (select coalesce(p.adj_close,p.close) from prices p
                         where p.ticker = r.ticker and p.d < r.from_d
                         order by p.d desc limit 1) as before_px,
                       (select coalesce(p.adj_close,p.close) from prices p
                         where p.ticker = r.ticker and p.d > r.to_d
                         order by p.d limit 1) as after_px
                  from runs r where r.len >= 63
                 order by r.len desc limit 40""")
            gaps = cur.fetchall()
            if not gaps:
                print("  none — no stock ticker goes dark for a quarter inside its own span")
            for tk, ln, a, b, before, after in gaps:
                # A price that resumes at a wildly different level across a long dead period is the
                # tell for a REISSUE rather than a suspension: the same company coming back from a
                # halt resumes near where it stopped.
                jump = ""
                if before and after and float(before) > 0:
                    r = float(after) / float(before)
                    jump = f"  {float(before):.2f} -> {float(after):.2f} ({r:.2f}x)"
                    if r > 3 or r < 0.33:
                        jump += "  ** LIKELY REISSUE **"
                print(f"  {tk:<12} {ln:>4} sessions dark  {a} .. {b}{jump}")

            held_back(cur)

    print("\ncensus: read-only, nothing written")
    return 0


# ---- the three questions migration 050 held back --------------------------------------------
#
# 050 applied what survived re-verification and deliberately left five rows unapplied, each needing
# one measurement rather than a judgement. They are asked here rather than in a new job because
# this is already the read-only universe-hygiene report, and because an exclusion is permanent in
# effect: a name wrongly excluded is never ranked, never traded, and leaves no trace of what it
# would have done.
#
# The first question is live and costing something right now. 041 IS applied in production, so
# APPS.US and BDN.US are excluded today under a row whose own text says "pending a re-pull" — and
# the re-pull has since happened. Two live, tradable common stocks are being kept out of §3.3's
# ranking on evidence nobody has re-checked.
QUARANTINED = (("APPS.US", "BDN.US"), ("VGNT.US", "VGNT-W.US"))
DEAD_PAIRS = (("TBSI.US", "TBSIQ.US"), ("VVUS.US", "VVUSQ.US"))


def _returns(cur, a, b):
    """Aligned daily returns for two tickers over the sessions they share. NaN where either is out."""
    cur.execute("""select d, ticker, coalesce(adj_close, close) from prices
                    where ticker in (%s, %s) order by d""", (a, b))
    series = {}
    for d, tk, px in cur.fetchall():
        series.setdefault(d, {})[tk] = float(px) if px is not None else float("nan")
    days = sorted(series)
    import numpy as np
    cols = {}
    for tk in (a, b):
        px = np.array([series[d].get(tk, np.nan) for d in days], dtype=float)
        with np.errstate(invalid="ignore", divide="ignore"):
            cols[tk] = np.diff(px) / px[:-1]
    return cols[a], cols[b], len(days)


def held_back(cur):
    import bars

    print("\n=== 050's quarantine rows: does the identical series survive the re-pull? ===")
    for a, b in QUARANTINED:
        ra, rb, n = _returns(cur, a, b)
        if n < 2:
            print(f"  {a} / {b}: fewer than two shared sessions — no bars to compare")
            continue
        twins = bars.same_security(ra, rb)
        shared = int((~(ra != ra) & ~(rb != rb)).sum())
        print(f"  {a} / {b}: {shared} shared sessions · same series = {twins}")
        verdict = ("STILL CORRUPT — the exclusion stands" if twins else
                   "CLEAN — the defect is gone, and §3.2 calls a standing exclusion of a live "
                   "tradable common stock a strategy change. Propose RELEASING it.")
        print(f"      {verdict}")

    print("\n=== 050's dead pairs: does §3.2's rule decide? ===")
    for a, b in DEAD_PAIRS:
        cur.execute("""select ticker, min(d), max(d), count(*) from prices
                        where ticker in (%s, %s) group by ticker order by 1""", (a, b))
        rows = cur.fetchall()
        if len(rows) < 2:
            print(f"  {a} / {b}: only {len(rows)} of the two has bars at all")
            for tk, first, last, n in rows:
                print(f"      {tk}: {n} bars, {first} .. {last}")
            continue
        for tk, first, last, n in rows:
            print(f"  {tk:<10} {n:>5} bars   {first} .. {last}")

        ra, rb, _ = _returns(cur, a, b)
        shared = int((~(ra != ra) & ~(rb != rb)).sum())
        agree = bars.same_security(ra, rb)
        lasts = {tk: last for tk, _, last, _ in rows}
        # §3.2: "keep the line still printing." Neither of these is, so the clause does not reach
        # them, and the last-print does not break the tie either — both die on the same session.
        #
        # This is where the first draft of this report was WRONG. It said "the later last-print
        # decides" and then printed a confident keep/exclude off a tie that Postgres broke by row
        # order. That is precisely the invention migration 050 held these rows back to avoid: an
        # exclusion is permanent in effect, and a name wrongly excluded is never ranked, never
        # traded, and leaves no trace of what it would have done. The report states the facts and
        # says plainly when the rule does not decide.
        if lasts[a] != lasts[b]:
            keep = a if lasts[a] > lasts[b] else b
            print(f"      §3.2 DECIDES: keep {keep} — it is the line the vendor carried furthest")
        elif agree:
            print(f"      §3.2 does not decide: both lines end {lasts[a]}, and neither is still "
                  f"printing. They ARE one series ({shared} shared sessions), so either may be "
                  f"kept and exactly one must go — the choice does not change a backtest. "
                  f"**Zak's ruling, on a coin that genuinely has two identical faces.**")
        else:
            print(f"      §3.2 does not decide, and the choice MATTERS: both lines end "
                  f"{lasts[a]}, and over {shared} shared sessions they are not the same series. "
                  f"Excluding the wrong one drops real history. **Needs a ruling, not a default.**")


if __name__ == "__main__":
    sys.exit(main())
