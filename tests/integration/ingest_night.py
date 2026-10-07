"""One night of `ingest-daily`, run for real against a vendor the test writes down.

`ingest.main` is the code that lands the tape, records the corporate actions and re-pulls the
histories they rewrite — and until these helpers no test ran it: every guard it carries was tested
as a function, never as the night it belongs to. The vendor below answers exactly the calls the
nightly makes and raises on any other, so a test also pins WHAT the night asks for.

Not a test module (no `test_` prefix): the tests import it, the way they import `fixtures`.
"""
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import ingest                                                             # noqa: E402

TODAY = dt.date.today()


def day(n):
    """`n` calendar days before today, as the vendor writes a date."""
    return (TODAY - dt.timedelta(days=n)).isoformat()


def bar(date, close, adj=None, volume=1_000_000, code=None):
    """A vendor bar. `adj` defaults to the close, which is what the newest day always carries."""
    b = dict(date=date, open=close, high=close, low=close, close=close,
             adjusted_close=close if adj is None else adj, volume=volume)
    if code:
        b["code"] = code
    return b


class Vendor:
    """Answers the nightly's calls from the world a test states, and remembers every question."""

    def __init__(self):
        self.tape = []                                    # the newest day, every name
        self.bulk = {"splits": [], "dividends": []}       # that day's corporate-action files
        self.history = {}                                 # ticker -> bars, served by eod/{ticker}
        self.ledger = {}                                  # ticker -> splits, served by splits/{ticker}
        self.asked = []

    def __call__(self, path, calls, **params):
        calls[0] += 1
        self.asked.append((path, params))
        if path == "eod-bulk-last-day/US":
            kind = params.get("type")
            return [dict(r) for r in (self.bulk[kind] if kind else self.tape)]
        if path.startswith("eod/"):
            frm = params.get("from") or ""
            return [dict(b) for b in self.history.get(path[len("eod/"):], []) if b["date"] >= frm]
        if path.startswith("splits/"):
            ledger = self.ledger.get(path[len("splits/"):], [])
            if not isinstance(ledger, list):
                return ledger
            return [dict(s) if isinstance(s, dict) else s for s in ledger]
        if path.startswith("real-time/"):
            code = path[len("real-time/"):].removesuffix(".US")
            return {"close": next((r["close"] for r in self.tape if r["code"] == code), None)}
        raise AssertionError(f"the nightly asked the vendor for something it never asks: {path}")

    def pulled(self, prefix):
        """The tickers the night asked `prefix` for, in order — e.g. pulled('eod/')."""
        return [p[len(prefix):] for p, _ in self.asked if p.startswith(prefix)]


def name(cur, ticker, kind="stock"):
    cur.execute("""insert into universe (ticker, name, kind, exchange, currency, status)
                   values (%s, %s, %s, 'US', 'USD', 'active')""",
                (ticker, ticker.split(".")[0], kind))


def store(cur, ticker, bars):
    """Bars as the store holds them (`bar` dicts), written straight to `prices`."""
    cur.executemany("""insert into prices (ticker, d, open, high, low, close, adj_close, volume)
                       values (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    [(ticker, b["date"], b["open"], b["high"], b["low"], b["close"],
                      b["adjusted_close"], b["volume"]) for b in bars])


def night(db, monkeypatch, vendor, *, scheduled=True, retry=False, tape_date=None, dry=False):
    """Run `ingest.main` once. Returns (runs row as a dict, the exception it raised or None)."""
    db.commit()
    monkeypatch.setattr(ingest, "get", vendor)
    monkeypatch.setattr(ingest, "SECOND_RUN", retry)
    monkeypatch.setattr(ingest, "TAPE_DATE", tape_date)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule" if scheduled else "workflow_dispatch")
    monkeypatch.setenv("DRY_RUN", "true" if dry else "false")
    raised = None
    try:
        ingest.main()
    except Exception as e:                              # the heartbeat has already written it red
        raised = e
    with db.cursor() as cur:
        cur.execute("""select id, status, rows_written, detail from runs
                        where job = 'ingest-daily' order by id desc limit 1""")
        rid, status, rows, detail = cur.fetchone()
    db.commit()
    detail = detail if isinstance(detail, dict) else json.loads(detail or "{}")
    return dict(id=rid, status=status, rows=rows, detail=detail), raised


def closes(db, ticker):
    """{date string: (close, adj_close, volume)} for one ticker, as the store now holds it."""
    with db.cursor() as cur:
        cur.execute("select d, close, adj_close, volume from prices where ticker = %s order by d",
                    (ticker,))
        out = {str(d): (c, a, v) for d, c, a, v in cur.fetchall()}
    db.commit()
    return out
