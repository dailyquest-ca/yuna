"""The nightly's split sweep and its re-pulls answer only for the bars a decision reads.

The first night the per-ticker split ledger was read (2026-10-09) it judged every split the vendor
lists back to 2005. It re-pulled the whole history of seven pool names for factors dated 2007-2023
— ASML.US's 0.888889:1 of 2007-10-01, LH.US's 1.164:1 spin-off of 2023-07-03 and the like — and
ambered twice on a price-critical job: three factors the vendor's own history does not carry, and
two re-pulls refused because the vendor has restated those names' older closes. Both refusals were
owed to the next night, and the next, for good.

A split scales the adjusted closes before its date, so one dated on or before the first session
the engine reads (`desk.first_read`) moves nothing any decision reads, tonight or later. The sweep
asks about nothing older, and an owed re-pull the vendor refuses only over closes older than that
session is recorded and owed no more. A split inside the window stays guarded either way: the sweep
finds it again every night as that night's own action.
"""
import desk
import ingest_night as night

DEEP = max(desk.reads().values())          # the first bar a decision reads is DEEP sessions back
LONG = DEEP + 400                          # stored history reaching well past it


def _spy(cur, oldest=LONG):
    """SPY on every calendar day, so `night.day(n)` is n sessions back on the engine's calendar."""
    night.name(cur, "SPY.US", kind="index")
    night.store(cur, "SPY.US", [night.bar(night.day(n), 600.0) for n in range(oldest, 1, -1)])


def _pool(cur, *tickers):
    """The pool the engine last ranked: the population the sweep reads ledgers for (§3.2)."""
    cur.executemany("""insert into engine_ranks (session_date, mode, ticker, rank, score)
                       values (%s, 'live', %s, %s, 1.0)""",
                    [(night.day(2), tk, rank) for rank, tk in enumerate(tickers, start=1)])


def _flat(cur, ticker, days, close=100.0):
    night.name(cur, ticker)
    night.store(cur, ticker, [night.bar(night.day(n), close) for n in days])


def test_a_split_older_than_every_bar_a_decision_reads_is_not_judged(db, monkeypatch):
    """Two pool names, each with a 2:1 split the store does not carry. OLDS.US's is dated before
    the first session tonight's decision reads: the night must not ask for its history. NEWS.US's
    is inside the window: it is found and applied as before."""
    with db.cursor() as cur:
        _spy(cur)
        for tk, at in (("OLDS.US", DEEP + 30), ("NEWS.US", 100)):
            night.name(cur, tk)
            night.store(cur, tk, [night.bar(night.day(n), 100.0 if n > at else 50.0)
                                  for n in range(LONG, 1, -1)])
        _pool(cur, "OLDS.US", "NEWS.US")
    vendor = night.Vendor()
    vendor.tape = night.tape(1, SPY=601.0, OLDS=50.0, NEWS=50.0)
    for tk, at in (("OLDS.US", DEEP + 30), ("NEWS.US", 100)):
        vendor.ledger[tk] = [dict(date=night.day(at), split="2.000000/1.000000")]
    vendor.history["NEWS.US"] = [night.bar(night.day(n), 100.0 if n > 100 else 50.0, adj=50.0)
                                 for n in range(LONG, 0, -1)]

    run, raised = night.night(db, monkeypatch, vendor)
    assert raised is None and run["status"] == "green", run["detail"].get("amber")
    assert run["detail"]["split_ledger"]["found"] == {
        "NEWS.US": f"split 2:1 on {night.day(100)}"}
    assert run["detail"]["split_ledger"]["after"] == night.day(DEEP + 1)
    assert "OLDS.US" not in vendor.pulled("eod/"), "a split no decision reads costs nothing"
    assert night.closes(db, "NEWS.US")[night.day(150)][1] == 50.0, "the split inside is applied"


def _restated(db, *, also_inside=False):
    """RST.US: a long stored history the vendor has since restated before the window — and, with
    `also_inside`, one close inside it too. A dividend on day(1) sends it through the re-pull."""
    with db.cursor() as cur:
        _spy(cur)
        _flat(cur, "RST.US", range(LONG, 1, -1))
    vendor = night.Vendor()
    vendor.tape = night.tape(1, SPY=601.0, RST=100.0)
    vendor.bulk["dividends"] = [dict(code="RST", exchange="US", date=night.day(1), dividend=0.5)]
    vendor.history["RST.US"] = [
        night.bar(night.day(n), 120.0 if n > DEEP + 1 or (also_inside and n == 5) else 100.0,
                  adj=99.5) for n in range(LONG, 0, -1)]
    return vendor


def test_an_owed_re_pull_the_vendor_refuses_only_over_its_restated_past_is_owed_no_more(
        db, monkeypatch):
    vendor = _restated(db)
    first, _ = night.night(db, monkeypatch, vendor)
    assert first["status"] == "amber", "tonight's own dividend is refused, and says so once"
    assert "RST.US" in first["detail"]["repull_refused"]
    assert "RST.US" in first["detail"]["repull_deferred"]

    vendor.tape = night.tape(0, SPY=602.0, RST=100.0)
    vendor.bulk["dividends"] = []
    vendor.history["RST.US"].append(night.bar(night.day(0), 100.0))
    second, raised = night.night(db, monkeypatch, vendor)
    assert raised is None and second["status"] == "green", second["detail"].get("amber")
    assert "RST.US" in second["detail"]["repull_restated"]
    assert second["detail"]["repull_refused"] == {}
    assert second["detail"]["repull_deferred"] == {}, "owed no more"
    assert "owed no more" in second["detail"]["repairs"]["RST.US"]


def test_an_owed_re_pull_refused_over_a_close_inside_the_window_is_still_owed(db, monkeypatch):
    vendor = _restated(db, also_inside=True)
    night.night(db, monkeypatch, vendor)

    vendor.tape = night.tape(0, SPY=602.0, RST=100.0)
    vendor.bulk["dividends"] = []
    vendor.history["RST.US"].append(night.bar(night.day(0), 100.0))
    second, raised = night.night(db, monkeypatch, vendor)
    assert raised is None and second["status"] == "amber"
    assert "RST.US" in second["detail"]["repull_refused"]
    assert "RST.US" in second["detail"]["repull_deferred"]
    assert second["detail"]["repull_restated"] == {}


def test_a_split_inside_the_window_whose_re_pull_is_refused_is_never_let_go(db, monkeypatch):
    """The guard the restated branch leans on. SPL.US splits 2:1 inside the window and its re-pull
    is refused over restated old closes, night after night. Each night the sweep finds the split
    again as that night's own action, so it is refused as tonight's and ambers — never recorded
    as a restated past and let go while the store still carries a fake crash."""
    with db.cursor() as cur:
        _spy(cur)
        night.name(cur, "SPL.US")
        night.store(cur, "SPL.US", [night.bar(night.day(n), 100.0 if n > 3 else 50.0)
                                    for n in range(LONG, 1, -1)])
        _pool(cur, "SPL.US")
    vendor = night.Vendor()
    vendor.tape = night.tape(1, SPY=601.0, SPL=50.0)
    vendor.ledger["SPL.US"] = [dict(date=night.day(3), split="2.000000/1.000000")]
    vendor.history["SPL.US"] = [
        night.bar(night.day(n), 120.0 if n > DEEP + 1 else (100.0 if n > 3 else 50.0), adj=50.0)
        for n in range(LONG, 0, -1)]
    for n in (1, 0):
        vendor.tape = night.tape(n, SPY=601.0, SPL=50.0)
        if n == 0:
            vendor.history["SPL.US"].append(night.bar(night.day(0), 50.0))
        run, raised = night.night(db, monkeypatch, vendor)
        assert raised is None and run["status"] == "amber", f"night {n}: {run['detail']}"
        assert "SPL.US" in run["detail"]["repull_refused"]
        assert run["detail"]["repull_restated"] == {}
        assert run["detail"]["split_ledger"]["found"] == {"SPL.US": f"split 2:1 on {night.day(3)}"}
