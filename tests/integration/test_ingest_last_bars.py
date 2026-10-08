"""The per-ticker pass's last-bar map, read by index probe instead of a whole-table aggregate (A35).

`select ticker, max(d) from prices group by ticker` read all 13M rows of `prices` every night
(~10.5 s in production) to answer a question the job only ever asks of the ACTIVE names. The probe
form walks each active name's primary key backwards to its first row. These pin the two forms to
the same answer on the shapes production actually holds: names whose newest bars differ, a
delisted name, an FX pair with weekend bars newer than any stock bar, and an active name with no
bars at all.
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import ingest                                                             # noqa: E402

TODAY = dt.date.today()


def _name(cur, ticker, kind="stock", status="active"):
    cur.execute("""insert into universe (ticker, name, kind, currency, status)
                   values (%s, %s, %s, 'USD', %s)""", (ticker, ticker.split(".")[0], kind, status))


def _bars(cur, ticker, newest, n=5):
    cur.executemany("insert into prices (ticker, d, close, adj_close) values (%s, %s, 10, 10)",
                    [(ticker, newest - dt.timedelta(days=i)) for i in range(n)])


def test_the_probe_returns_what_the_aggregate_returned_for_every_active_name(db):
    with db.cursor() as cur:
        for tk in ("AAA.US", "BBB.US", "NOBARS.US"):
            _name(cur, tk)
        _name(cur, "GONE.US", status="delisted")
        _name(cur, "USDCAD.FOREX", kind="fx")
        _bars(cur, "AAA.US", TODAY - dt.timedelta(days=1))
        _bars(cur, "BBB.US", TODAY - dt.timedelta(days=4), n=300)
        _bars(cur, "GONE.US", TODAY - dt.timedelta(days=1))
        _bars(cur, "USDCAD.FOREX", TODAY)          # the FX feed prints weekends; stocks do not
        db.commit()

        cur.execute("select ticker, max(d) from prices group by ticker")
        aggregate = dict(cur.fetchall())
        cur.execute("select ticker from universe where status = 'active'")
        active = {r[0] for r in cur.fetchall()}

        probed = ingest.last_bars(cur)

    assert probed == {t: d for t, d in aggregate.items() if t in active}
    assert probed["USDCAD.FOREX"] == TODAY and probed["BBB.US"] == TODAY - dt.timedelta(days=4)
    assert "NOBARS.US" not in probed, "a name with no bars is a cold start, exactly as before"
    assert "GONE.US" not in probed, "the pass never reads a name outside the active universe"
