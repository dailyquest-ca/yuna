"""A split the bulk file did not carry on its night is still found and applied (A4).

The nightly reads splits from one bulk file: the newest tape's. DCX.US's 1:160 (2026-09-28) and
CTVA.US's 6.665:1 (2026-10-01) were not in their nights' files, nothing ever asked again, and both
adjusted histories kept a fake 125x jump and a fake -84% crash. Every night the vendor's own
per-ticker split ledger is now read for each name a split can hurt — the book, and the pool the
engine last ranked — and any split it lists that the stored series does not carry joins that
night's corporate actions and goes through the checked re-pull.
"""
import ingest_night as night
import fixtures as world


def _spy(cur):
    night.name(cur, "SPY.US", kind="index")
    night.store(cur, "SPY.US", [night.bar(night.day(3), 599.0), night.bar(night.day(2), 600.0)])


def _actions(db, ticker):
    with db.cursor() as cur:
        cur.execute("select d::text, kind, detail from corporate_actions where ticker = %s", (ticker,))
        out = cur.fetchall()
    db.commit()
    return out


def test_a_held_names_split_the_bulk_file_never_carried_is_applied_the_same_night(db, monkeypatch):
    with db.cursor() as cur:
        _spy(cur)
        night.name(cur, "HELD.US")
        night.store(cur, "HELD.US", [night.bar(night.day(n), 100.0 + n / 2) for n in range(10, 0, -1)])
        world.position(cur, "HELD.US", qty=10, cost=100.0, stop=None)
    held = night.closes(db, "HELD.US")
    vendor = night.Vendor()
    vendor.tape = [night.bar(night.day(0), 602.0, code="SPY"), night.bar(night.day(0), 50.0, code="HELD")]
    vendor.ledger["HELD.US"] = [dict(date=night.day(0), split="2.000000/1.000000")]
    vendor.history["HELD.US"] = ([night.bar(d, c, adj=c / 2) for d, (c, _, _) in held.items()]
                                 + [night.bar(night.day(0), 50.0)])

    run, raised = night.night(db, monkeypatch, vendor)
    now = night.closes(db, "HELD.US")
    for d, (close, _, _) in held.items():
        assert now[d][:2] == (close, close / 2), f"{d} carries the split"
    assert raised is None and run["status"] == "green", run["detail"].get("amber")
    assert [(d, k) for d, k, _ in _actions(db, "HELD.US")] == [(night.day(0), "split")]
    assert run["detail"]["split_ledger"]["found"] == {"HELD.US": f"split 2:1 on {night.day(0)}"}
    assert run["detail"]["bulk_actions"] == {"splits": 0, "dividends": 0}


def test_a_pool_names_split_posted_late_is_applied_the_first_night_the_ledger_lists_it(db,
                                                                                    monkeypatch):
    """CTVA.US's shape, a night late. Beside it, a pool name whose old split the store already
    carries (it must not be re-pulled for it), and a name outside the pool and the book (it must
    never be asked about at all: the population is bounded by the plan's own pool, §3.2)."""
    with db.cursor() as cur:
        _spy(cur)
        for tk in ("POOL.US", "OLD.US", "OUT.US"):
            night.name(cur, tk)
        night.store(cur, "POOL.US", [night.bar(night.day(n), 77.65) for n in range(10, 1, -1)])
        night.store(cur, "OUT.US", [night.bar(night.day(n), 10.0) for n in range(10, 1, -1)])
        night.store(cur, "OLD.US", [night.bar(night.day(n), 100.0, adj=50.0) for n in (10, 9)]
                    + [night.bar(night.day(n), 50.0) for n in range(8, 1, -1)])
        cur.executemany("""insert into engine_ranks (session_date, mode, ticker, rank, score)
                           values (%s, 'live', %s, %s, 1.0)""",
                        [(night.day(2), "POOL.US", 161), (night.day(2), "OLD.US", 5)])
    vendor = night.Vendor()
    vendor.tape = [night.bar(night.day(1), 601.0, code="SPY"), night.bar(night.day(1), 12.57, code="POOL"),
                   night.bar(night.day(1), 50.5, code="OLD"), night.bar(night.day(1), 10.1, code="OUT")]
    vendor.ledger["OLD.US"] = [dict(date=night.day(8), split="2.000000/1.000000")]
    vendor.ledger["OUT.US"] = [dict(date=night.day(1), split="1.000000/10.000000")]

    first, raised = night.night(db, monkeypatch, vendor)            # the vendor has not posted it
    assert raised is None
    assert night.closes(db, "POOL.US")[night.day(5)][1] == 77.65, "nothing to apply yet"

    vendor.tape = [night.bar(night.day(0), 602.0, code="SPY"), night.bar(night.day(0), 13.0, code="POOL"),
                   night.bar(night.day(0), 51.0, code="OLD"), night.bar(night.day(0), 10.2, code="OUT")]
    vendor.ledger["POOL.US"] = [dict(date=night.day(1), split="6665.000000/1000.000000")]
    vendor.history["POOL.US"] = ([night.bar(night.day(n), 77.65, adj=round(77.65 / 6.665, 4))
                                  for n in range(10, 1, -1)]
                                 + [night.bar(night.day(1), 12.57), night.bar(night.day(0), 13.0)])
    run, raised = night.night(db, monkeypatch, vendor)
    assert night.closes(db, "POOL.US")[night.day(5)][1] == round(77.65 / 6.665, 4), (
        "the first night the vendor lists it, the split is applied — though no bulk file named it")
    assert raised is None and run["status"] == "green", run["detail"].get("amber")
    assert run["detail"]["split_ledger"]["found"] == {"POOL.US": f"split 6.665:1 on {night.day(1)}"}
    assert first["detail"]["split_ledger"] == dict(asked=2, errors={}, found={})
    assert "OUT.US" not in vendor.pulled("splits/"), "outside the pool and the book: never asked"
    assert "OLD.US" not in vendor.pulled("eod/"), "a split the store already carries costs nothing"


def test_a_ledger_the_store_cannot_read_or_a_split_the_vendor_never_applied_is_named(db,
                                                                                  monkeypatch):
    """The two ways the check can come back without an answer, both on held names, both amber."""
    with db.cursor() as cur:
        _spy(cur)
        for tk in ("ODD.US", "DARK.US", "GARBLED.US"):
            night.name(cur, tk)
            night.store(cur, tk, [night.bar(night.day(n), 40.0) for n in range(10, 0, -1)])
            world.position(cur, tk, qty=10, cost=40.0, stop=None)
    vendor = night.Vendor()
    vendor.tape = [night.bar(night.day(0), 602.0, code="SPY"), night.bar(night.day(0), 20.0, code="ODD"),
                   night.bar(night.day(0), 41.0, code="DARK"), night.bar(night.day(0), 40.5, code="GARBLED")]
    vendor.ledger["GARBLED.US"] = ["2.000000/1.000000"]           # an entry with no date to read
    # ODD.US: the ledger says 2:1 tonight, but the vendor's own history is still unadjusted
    vendor.ledger["ODD.US"] = [dict(date=night.day(0), split="2.000000/1.000000")]
    vendor.history["ODD.US"] = ([night.bar(night.day(n), 40.0) for n in range(10, 0, -1)]
                                + [night.bar(night.day(0), 20.0)])
    vendor.ledger["DARK.US"] = {"error": "not a list"}            # a ledger nobody can read

    run, raised = night.night(db, monkeypatch, vendor)
    assert raised is None and run["status"] == "amber"
    ambers = " | ".join(run["detail"]["amber"])
    assert "ODD.US on" in ambers and "does not carry" in ambers
    assert "DARK.US" in ambers and "GARBLED.US" in ambers and "cannot be ruled out" in ambers
    assert {"DARK.US", "GARBLED.US"} <= set(run["detail"]["split_ledger"]["errors"])
