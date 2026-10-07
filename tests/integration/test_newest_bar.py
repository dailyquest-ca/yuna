"""The newest stock bar, answered by an index probe (QC 2026-10-07, A35).

`data_date()` and `freshness()` ask one question — the date of the newest bar of any stock — and
both asked it as `max(p.d)` over a join with `universe`. Postgres turns a bare max() into an index
probe, but not across a join, so the question read the whole price table: 13M rows on production,
9.3 s on average and 30.7 s at worst against a 120-second statement timeout, in ingest before the
tape is fetched and in check on compose's critical path.

The answer must not move, so every world below is asked the old way too and the two must agree —
including the worlds that made the stock filter necessary (FX and the index printing past the last
equity bar, as production's FX does over weekends). And the readers' own SQL must plan as the probe,
or the cost comes back the first time somebody tidies the statement.
"""
import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import db as dbm                                                          # noqa: E402

# the old statement, kept here as the reference answer
AGGREGATE = """select max(p.d) from prices p join universe u on u.ticker = p.ticker
               where u.kind = 'stock'"""

FRI = dt.date(2026, 10, 2)


def _name(cur, ticker, kind="stock", status="active"):
    cur.execute("""insert into universe (ticker, name, kind, currency, status)
                   values (%s, %s, %s, 'USD', %s)""", (ticker, ticker, kind, status))


def _bars(cur, ticker, *days):
    for d in days:
        cur.execute("insert into prices (ticker, d, close) values (%s, %s, 10)", (ticker, d))


def _fx_and_index_print_past_the_stocks(cur):
    _name(cur, "AAA.US")
    _bars(cur, "AAA.US", FRI - dt.timedelta(days=1), FRI)
    _name(cur, "BBB.US")
    _bars(cur, "BBB.US", FRI - dt.timedelta(days=2), FRI - dt.timedelta(days=1))
    _name(cur, "USDCAD.FOREX", kind="fx")
    _bars(cur, "USDCAD.FOREX", *(FRI + dt.timedelta(days=k) for k in (0, 1, 2, 3)))
    _name(cur, "GSPC.INDX", kind="index")
    _bars(cur, "GSPC.INDX", FRI + dt.timedelta(days=3))
    return FRI


def _a_delisted_stock_is_still_a_stock(cur):
    _name(cur, "AAA.US")
    _bars(cur, "AAA.US", FRI)
    _name(cur, "GONE.US", status="delisted")         # the old form filtered on kind, never status
    _bars(cur, "GONE.US", FRI + dt.timedelta(days=3))
    return FRI + dt.timedelta(days=3)


def _no_stock_has_a_bar(cur):
    _name(cur, "AAA.US")
    _name(cur, "USDCAD.FOREX", kind="fx")
    _bars(cur, "USDCAD.FOREX", FRI)
    return None


def _an_empty_store(cur):
    return None


WORLDS = [_fx_and_index_print_past_the_stocks, _a_delisted_stock_is_still_a_stock,
          _no_stock_has_a_bar, _an_empty_store]


class _Sent:
    """A connection (or cursor) that remembers every statement sent through it, so the test can ask
    the planner about the exact SQL the reader chose."""

    def __init__(self, target, log=None):
        self._target, self.log = target, [] if log is None else log

    def cursor(self):
        return _Sent(self._target.cursor(), self.log)

    def __enter__(self):
        self._target.__enter__()
        return self

    def __exit__(self, *exc):
        return self._target.__exit__(*exc)

    def execute(self, sql, *args):
        self.log.append(sql)
        return self._target.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._target, name)


def _plan(db, sql):
    """The plan, with sequential scans priced out — so a probe is chosen wherever one exists, on
    a test table far too small for the planner to prefer it on its own."""
    with db.cursor() as cur:
        cur.execute("set local enable_seqscan = off")
        cur.execute("explain (costs off) " + sql)
        plan = "\n".join(r[0] for r in cur.fetchall())
    db.rollback()
    return plan


def _is_a_probe(plan):
    return ("Limit" in plan and "Backward" in plan and "prices_d_idx" in plan
            and "Aggregate" not in plan)


@pytest.mark.parametrize("world", WORLDS, ids=lambda w: w.__name__.strip("_"))
def test_data_date_answers_as_the_aggregate_did_from_an_index_probe(db, world):
    with db.cursor() as cur:
        want = world(cur)
    db.commit()
    with db.cursor() as cur:
        cur.execute(AGGREGATE)
        assert cur.fetchone()[0] == want, "the reference answer, the old way"
        sent = _Sent(cur)
        assert dbm.data_date(sent) == want, "the same answer, the new way"
    asked, = sent.log
    assert _is_a_probe(_plan(db, asked)), f"data_date must probe the index:\n{_plan(db, asked)}"


@pytest.mark.parametrize("world", WORLDS, ids=lambda w: w.__name__.strip("_"))
def test_freshness_reads_the_same_bar_from_an_index_probe(db, world):
    with db.cursor() as cur:
        want = world(cur)
    db.commit()
    sent = _Sent(db)
    line, _ = dbm.freshness(sent)
    # the bar's date, in whichever of the two shapes its age puts it
    assert f"last close {want} " in line or f"data {want} close" in line, line
    asked = sent.log[0]
    assert _is_a_probe(_plan(db, asked)), f"freshness must probe the index:\n{_plan(db, asked)}"
