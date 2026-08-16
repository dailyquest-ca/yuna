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
    print("\ncensus: read-only, nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
