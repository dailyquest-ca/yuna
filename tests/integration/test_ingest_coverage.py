"""What `ingest-daily` must write down before anything derives from it (WO-2, WO-4).

Two source-of-truth gaps the 2026-08-07 orders name. Neither is a formula and both are invisible
from the code alone — they only show up when the job runs over data and you look at what came out.

  * §4.1's FX row says "USDCAD for CAD NAV **+ statement currencies for foreign filers**". Only
    USDCAD was ever on the feed, so §3.0's conversion had no rates and ~185 names were excluded
    from the compounder funnel instead of converted.
  * obs 114 — the bulk calendar is broad and it is not complete. Arcosa's 2026-08-05 report was
    absent, so the blackout wall showed nothing and the nightly armed through the print twice.
"""
import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import ingest                                                             # noqa: E402
import fixtures as world                                                  # noqa: E402


class Beat:
    def __init__(self):
        self.detail, self.calls, self.rows, self.id = {}, [0], 0, None

    def amber(self, why):
        self.detail.setdefault("amber", []).append(why)


def with_statements_in(cur, ticker, currency):
    world.add_name(cur, ticker)
    cur.execute("""insert into fundamentals (ticker, filing_date, period_end, statement_currency,
                                             quote_ok, data_confidence, fiscal_years)
                   values (%s,'2026-05-01','2025-12-31',%s,false,'flagged',6)""",
                (ticker, currency))


# --------------------------------------------------------------- WO-2 · the pairs join the feed

def test_every_statement_currency_gets_a_pair_on_the_nightly_feed(db):
    """Registration only — the per-ticker pass pulls the bars, so a new currency backfills its full
    history on the first night it appears and costs one incremental call every night after."""
    with db.cursor() as cur:
        with_statements_in(cur, "TSM.US", "TWD")
        with_statements_in(cur, "ASML.US", "EUR")
        with_statements_in(cur, "MSFT.US", "USD")           # nothing to convert, nothing to add
    db.commit()

    hb = Beat()
    pairs = ingest.register_fx_pairs(db, hb)
    assert pairs == ["EURUSD.FOREX", "USDTWD.FOREX"], "majors quote XXXUSD, the rest USDXXX"
    with db.cursor() as cur:
        cur.execute("select ticker, kind from universe where kind='fx' order by ticker")
        assert cur.fetchall() == [("EURUSD.FOREX", "fx"), ("USDTWD.FOREX", "fx")]

    assert ingest.register_fx_pairs(db, Beat()) == pairs, "registering twice adds nothing"


def test_a_new_pair_is_repaired_before_the_equities_queue_for_it(db):
    """§4.1 caps per-ticker pulls per night. The index and the FX pairs carry the rest of the
    night's arithmetic, so they must not queue behind two hundred equity backfills and fall past
    the cap — which is what the old sort did to a currency's cold start."""
    repairs = [("ZZZ.US", "cold start", None), ("USDTWD.FOREX", "cold start", None),
               ("AAA.US", "corporate action (split 4:1)", None), ("GSPC.INDX", "non-US listing", None)]
    repairs.sort(key=lambda r: (not r[1].startswith("corporate action"),
                                r[0].endswith(".US"),
                                r[1] != "non-US listing"))
    assert [r[0] for r in repairs][:3] == ["AAA.US", "GSPC.INDX", "USDTWD.FOREX"]


# --------------------------------------------------------------- WO-4 · the calendar, by name

def test_the_watched_names_get_their_calendar_asked_for_by_name(db, monkeypatch):
    """The population is the one the arming stage reaches for: holdings, the queue, BUY-state
    candidates, and every bench name at or within 10% of its hurdle."""
    asked = {}

    def fake_get(path, calls, **params):
        calls[0] += 1
        asked["path"], asked["symbols"] = path, params.get("symbols", "")
        return {"earnings": [
            {"code": "ACA.US", "report_date": "2026-08-05", "before_after_market": "BeforeMarket"},
            {"code": "NOTOURS.US", "report_date": "2026-08-05"},          # the vendor's filter lies
        ]}

    monkeypatch.setattr(ingest, "get", fake_get)
    with db.cursor() as cur:
        world.add_name(cur, "ACA.US", last_reported_days_ago=None)
        world.add_name(cur, "IDLE.US", last_reported_days_ago=None)       # in neither list
        world.queued(cur, "ACA.US", trigger=110.0)
        cur.execute("delete from earnings")
    db.commit()

    hb = Beat()
    ingest.refresh_earnings_for_watched(db, hb, batch_size=50, max_calls=12)

    assert asked["path"] == "calendar/earnings"
    assert asked["symbols"] == "ACA.US" and "IDLE.US" not in asked["symbols"]
    with db.cursor() as cur:
        cur.execute("select ticker, report_date from earnings")
        assert cur.fetchall() == [("ACA.US", dt.date(2026, 8, 5))], "and only names we asked about"


def test_a_watched_name_the_calendar_still_cannot_see_is_named(db, monkeypatch):
    """§4.1: never a silent gap. A name we meant to verify and could not is the ACA case again, so
    it goes on the heartbeat by name rather than into a count."""
    monkeypatch.setattr(ingest, "get", lambda path, calls, **p: {"earnings": []})
    with db.cursor() as cur:
        world.add_name(cur, "DARK.US", last_reported_days_ago=None)
        world.queued(cur, "DARK.US", trigger=110.0)
        cur.execute("delete from earnings")
    db.commit()

    hb = Beat()
    ingest.refresh_earnings_for_watched(db, hb, batch_size=50, max_calls=12)
    assert hb.detail["earnings_blind_spots"] == ["DARK.US"]
    assert any("no report date inside 110 days" in a for a in hb.detail["amber"])


def test_the_refresh_cap_is_real_and_never_silent(db, monkeypatch):
    """§4.1's budget is real. A truncation the brief never hears about reads as full coverage."""
    monkeypatch.setattr(ingest, "get", lambda path, calls, **p: {"earnings": []})
    with db.cursor() as cur:
        for i in range(6):
            tk = f"N{i}.US"
            world.add_name(cur, tk, last_reported_days_ago=10)
            world.queued(cur, tk, trigger=110.0, rank=i + 1)
    db.commit()

    hb = Beat()
    ingest.refresh_earnings_for_watched(db, hb, batch_size=2, max_calls=2)
    assert hb.detail["earnings_watched"]["calls"] == 2
    assert hb.detail["earnings_watched"]["dropped_past_cap"] == ["N4.US", "N5.US"]
    assert any("past tonight's earnings-refresh cap" in a for a in hb.detail["amber"])


def test_a_failed_batch_costs_that_batch_and_says_so(db, monkeypatch):
    """One rejected symbol must not look like a clean night for the other forty-nine."""
    def boom(path, calls, **p):
        calls[0] += 1
        raise RuntimeError("422 unknown symbol")

    monkeypatch.setattr(ingest, "get", boom)
    with db.cursor() as cur:
        world.add_name(cur, "ODD.XX", last_reported_days_ago=10)
        world.queued(cur, "ODD.XX", trigger=110.0)
    db.commit()

    hb = Beat()
    ingest.refresh_earnings_for_watched(db, hb, batch_size=50, max_calls=12)
    assert hb.detail["earnings_watched"]["errors"]
    assert any("targeted earnings request(s) failed" in a for a in hb.detail["amber"])
