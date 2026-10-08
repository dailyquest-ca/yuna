"""The research census's quarantine question, asked of the right line (QC 2026-10-07, A73).

`exchange_census.held_back` re-asks the questions migration 050 held back. Its quarantine question —
are these two lines one series? — accused both lines of a defect that lives in one of them, so a
common stock whose warrant line copies it could never be cleared. Tested over a real database with
hand-built tapes; the census writes nothing, so what is under test is the verdict it prints.
"""
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import exchange_census                                                    # noqa: E402
import fixtures as world                                                  # noqa: E402


def _line(cur, ticker, days, closes, *, kind="stock"):
    """A line with a bar, and a real trade, on exactly `days`."""
    cur.execute("""insert into universe (ticker,name,kind,exchange,currency,status)
                   values (%s,%s,%s,'US','USD','active') on conflict (ticker) do nothing""",
                (ticker, ticker.split(".")[0], kind))
    cur.executemany("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                       values (%s,%s,%s,%s,%s,%s,%s,1000000) on conflict (ticker,d) do nothing""",
                    [(ticker, d, closes[d], closes[d], closes[d], closes[d], closes[d])
                     for d in days])


def _pair(db, line, twin, *, line_days, twin_days, twin_reason, line_reason="quarantine"):
    """Two lines carrying ONE series — identical closes wherever both print — that moves enough
    for the twin test to mean something (a flat series agrees with everything)."""
    days = sorted(set(line_days) | set(twin_days))
    walk = np.exp(np.cumsum(np.random.default_rng(7).normal(0.0, 0.02, len(days))))
    closes = {d: round(30.0 * float(w), 2) for d, w in zip(days, walk)}
    with db.cursor() as cur:
        _line(cur, line, line_days, closes)
        _line(cur, twin, twin_days, closes, kind="warrant")
        cur.execute("insert into universe_excluded (ticker, reason, detail) values (%s, %s, %s)",
                    (line, line_reason, "planted by the test"))
        if twin_reason:
            cur.execute("insert into universe_excluded (ticker, reason, detail) values (%s,%s,%s)",
                        (twin, twin_reason, "planted by the test"))
    db.commit()


def test_the_copy_is_the_line_that_never_prints_alone(db, capsys):
    """VGNT.US's quarantine: "warrant/common pair share an identical series — re-pull". They do —
    and the -W line never prints on a session the common does not, while the common prints eight
    sessions alone, each a real trade. A copy cannot print without its source, so the defect is the
    warrant line's, and that line is already out as `not_common_equity`. Asked "same series?", the
    census answered STILL CORRUPT for as long as the vendor kept copying, so Zak's ruling — "if
    the defect is gone then we can allow them" — could never be met for a real common stock.

    The direction decides, and it decides nothing else: a common that is itself the copy stays
    out, and so does a pair of unrelated companies on one series (APPS/BDN), because which way a
    copy runs cannot say whose prices they are.
    """
    days = world.trading_days(60)
    gaps = set(days[10:60:7])                       # sessions only the common prints
    alone = [d for d in days if d not in gaps]
    _pair(db, "VGNT.US", "VGNT-W.US", line_days=days, twin_days=alone,
          twin_reason="not_common_equity")

    with db.cursor() as cur:
        exchange_census.held_back(cur)
    out = capsys.readouterr().out
    vgnt = out.split("VGNT.US / VGNT-W.US:", 1)[1].split("===", 1)[0]
    assert "VGNT-W.US IS THE COPY" in vgnt and "propose RELEASING it" in vgnt, vgnt
    assert "Zak's word" in vgnt, "the census proposes; whether to release is put back to Zak"
    assert "STILL CORRUPT" not in vgnt

    with db.cursor() as cur:
        verdict, _, why = exchange_census.quarantine_verdict(cur, "VGNT.US", "VGNT-W.US")
    assert verdict == "twin-is-the-copy" and f"prints {len(gaps)} session(s) alone" in why

    # the common is the copy: it never prints alone, its twin does — the quarantine stands
    _pair(db, "CMN.US", "CMN-W.US", line_days=alone, twin_days=days,
          twin_reason="not_common_equity")
    # two unrelated companies on one series, both quarantined — direction cannot clear either
    _pair(db, "AAA.US", "BBB.US", line_days=days, twin_days=alone, twin_reason="quarantine")
    # the copy is not excluded on its own account — releasing the source would re-admit a twin
    _pair(db, "SRC.US", "CPY.US", line_days=days, twin_days=alone, twin_reason=None)
    with db.cursor() as cur:
        for line, twin in (("CMN.US", "CMN-W.US"), ("AAA.US", "BBB.US"), ("SRC.US", "CPY.US")):
            verdict, _, why = exchange_census.quarantine_verdict(cur, line, twin)
            assert verdict == "corrupt" and "STILL CORRUPT" in why, (line, verdict, why)

    # and 056's answer for APPS/BDN keeps its shape: two lines no longer one series are clean
    _pair(db, "APPS.US", "BDN.US", line_days=days, twin_days=days, twin_reason="quarantine")
    with db.cursor() as cur:
        cur.executemany("""update prices set close = %s, adj_close = %s
                            where ticker = 'BDN.US' and d = %s""",
                        [(20.0 + i % 5, 20.0 + i % 5, d) for i, d in enumerate(days)])
        verdict, _, why = exchange_census.quarantine_verdict(cur, "APPS.US", "BDN.US")
    assert verdict == "clean" and "Propose RELEASING it" in why
