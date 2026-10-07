"""Migration 070: §3.2's rename rule, applied to the one row that broke it (QC 2026-10-07, A17).

§3.2: duplicate listings are "ticker renames where the vendor carries both the dead line and the
live one; keep the line still printing". 041 excluded SGI.US — Somnigroup, printing every session —
and kept TPX.US, the Tempur Sealy line with no bar since 2025-02-14, so the live universe held
neither. Tested on the rule over a real database, with a hand-built tape in the production shape.
"""
import pathlib
import sys

import psycopg
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import desk                                                               # noqa: E402
import funnel                                                             # noqa: E402
import fixtures as world                                                  # noqa: E402

MIGRATION_070 = ROOT / "migrations" / "070_the_line_still_printing.sql"
ROW_041 = "same series as TPX.US (Tempur Sealy renamed); keep TPX"


def _line(cur, ticker, days, *, kind="stock"):
    """A line with a bar on exactly `days`."""
    cur.execute("""insert into universe (ticker,name,kind,exchange,currency,status)
                   values (%s,%s,%s,'US','USD','active') on conflict (ticker) do nothing""",
                (ticker, ticker.split(".")[0], kind))
    cur.executemany("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                       values (%s,%s,50,50,50,50,50,1000000) on conflict (ticker,d) do nothing""",
                    [(ticker, d) for d in days])


def _tempur(db, *, sgi, tpx):
    """041's row over a tape where `sgi` and `tpx` pick the sessions each line prints."""
    days = world.trading_days(30)
    with db.cursor() as cur:
        _line(cur, "SPY.US", days, kind="index")
        _line(cur, "SGI.US", sgi(days))
        _line(cur, "TPX.US", tpx(days))
        cur.execute("update universe set status = 'delisted' where ticker = 'TPX.US'")
        cur.execute("""insert into universe_excluded (ticker, reason, detail)
                       values ('SGI.US', 'duplicate_listing', %s)""", (ROW_041,))
    db.commit()
    return days


def _exclusions(db):
    with db.cursor() as cur:
        cur.execute("select ticker, reason, detail from universe_excluded order by ticker")
        return cur.fetchall()


def test_070_keeps_the_line_still_printing(db):
    """The production shape: SGI.US prints through the newest session, TPX.US stopped, and TPX's
    span lies inside SGI's. 070 must leave the desk's universe holding the company through the line
    that prints, and must exclude the dead line rather than simply release the live one — the
    backtests keep the delisted, so a bare delete would put one company in two slots again."""
    days = _tempur(db, sgi=lambda d: d, tpx=lambda d: d[5:12])
    with db.cursor() as cur:
        cur.execute(MIGRATION_070.read_text())
        cur.execute(MIGRATION_070.read_text())       # idempotent: a second pass changes nothing
    db.commit()

    rows = _exclusions(db)
    assert [(t, r) for t, r, _ in rows] == [("TPX.US", "duplicate_listing")]
    assert funnel.kept_line(rows[0][2]) == "SGI.US", "the row names the line it keeps"
    with db.cursor() as cur:
        cur.execute(desk.TAPE, (days[-1],))
        on_the_desk = {r[0] for r in cur.fetchall()}
        session, pairs, flags = funnel.reverify_exclusions(cur)
    assert "SGI.US" in on_the_desk and "TPX.US" not in on_the_desk
    assert (session, pairs, flags) == (days[-1], [("TPX.US", "SGI.US")], []), (
        "the Saturday re-check passes the corrected row")


def test_070_refuses_when_the_line_it_would_exclude_is_the_one_printing(db):
    """The premise is asserted, not assumed (learning 35). If TPX.US printed past SGI.US, §3.2
    would keep TPX, and applying 070 would be the opposite of the rule it cites."""
    _tempur(db, sgi=lambda d: d[:12], tpx=lambda d: d)
    with db.cursor() as cur:
        with pytest.raises(psycopg.errors.RaiseException, match="TPX.US prints later than SGI.US"):
            cur.execute(MIGRATION_070.read_text())
    db.rollback()
    assert [t for t, _, _ in _exclusions(db)] == ["SGI.US"], "nothing applied"
