"""A corporate-action re-pull is checked before it replaces anything, and replaces it all.

A14 and A31. Run 593 is the case. IESC.US's 2:1 split sent the name through the re-pull, the
vendor answered with a half-rebuilt history — every bar from 2016 to 2026 at twice the price, 25
frozen zero-volume sessions — and the job deleted ten years and wrote it, green. A split or
dividend never changes a past RAW close, so the reply is now checked against the raw closes the
store already holds: a reply that contradicts most of them is refused, the stored rows stay, the
run ambers naming the name, and the next night asks again — the bulk file will not name it twice.

And the re-pull used to rewrite only `today - 3650` onward while the store holds bars back to
2005, so every re-pulled split left the older bars on the old basis: a fake 33-50% step at the
seam (APH.US 2016-09-06, 14.26 -> 7.12).
"""
import datetime as dt

import ingest_night as night


def _spy(cur):
    night.name(cur, "SPY.US", kind="index")
    night.store(cur, "SPY.US", [night.bar(night.day(3), 599.0), night.bar(night.day(2), 600.0)])


def _split_world(db):
    """XYZ.US splits 2:1 on day(1); the store holds nine sessions before it at about $100."""
    with db.cursor() as cur:
        _spy(cur)
        night.name(cur, "XYZ.US")
        night.store(cur, "XYZ.US",
                    [night.bar(night.day(n), 100.0 + n / 2) for n in range(10, 1, -1)])
    held = night.closes(db, "XYZ.US")
    vendor = night.Vendor()
    vendor.tape = night.tape(1, SPY=601.0, XYZ=50.5)
    vendor.bulk["splits"] = [dict(code="XYZ", exchange="US", date=night.day(1),
                                  split="2.000000/1.000000")]
    return vendor, held


def test_a_reply_that_contradicts_the_stored_closes_is_refused_and_asked_for_again(db,
                                                                                   monkeypatch):
    vendor, held = _split_world(db)
    # run 593's reply: the raw history at twice the price, the "adjusted" one at the old raw
    vendor.history["XYZ.US"] = ([night.bar(d, 2 * c, adj=c) for d, (c, _, _) in held.items()]
                                + [night.bar(night.day(1), 50.5)])

    run, raised = night.night(db, monkeypatch, vendor)
    now = night.closes(db, "XYZ.US")
    assert {d: now[d] for d in held} == held, "the stored rows stay exactly as they were"
    assert now[night.day(1)][0] == 50.5, "tonight's bar still landed from the tape"
    assert raised is None and run["status"] == "amber"
    assert "XYZ.US" in run["detail"]["repull_refused"]
    assert run["detail"]["repull_deferred"] == {
        "XYZ.US": "the vendor's reply contradicted the store"}
    assert any("XYZ.US" in a and "re-queued" in a for a in run["detail"]["amber"])

    # The next night the bulk file says nothing about XYZ — it named the split once — and the
    # vendor has rebuilt the history properly. The owed re-pull goes ahead anyway.
    vendor.tape = night.tape(0, SPY=602.0, XYZ=51.0)
    vendor.bulk["splits"] = []
    vendor.history["XYZ.US"] = ([night.bar(d, c, adj=c / 2) for d, (c, _, _) in held.items()]
                                + [night.bar(night.day(1), 50.5), night.bar(night.day(0), 51.0)])
    run, raised = night.night(db, monkeypatch, vendor)
    now = night.closes(db, "XYZ.US")
    for d, (close, _, _) in held.items():
        assert now[d][0] == close and now[d][1] == close / 2, f"{d} is on the split's basis"
    assert raised is None and run["status"] == "green", run["detail"].get("amber")
    assert run["detail"]["repull_deferred"] == {}, "nothing is owed once it lands"
    assert "re-queued by run" in run["detail"]["repairs"]["XYZ.US"]


def test_a_split_re_pull_cut_off_by_the_cap_is_owed_to_the_next_night(db, monkeypatch):
    vendor, held = _split_world(db)
    with db.cursor() as cur:
        night.name(cur, "ABC.US")
        night.store(cur, "ABC.US", [night.bar(night.day(n), 40.0) for n in range(10, 1, -1)])
    vendor.tape += night.tape(1, ABC=20.0)
    vendor.bulk["splits"].append(dict(code="ABC", exchange="US", date=night.day(1),
                                      split="2.000000/1.000000"))
    vendor.history["XYZ.US"] = ([night.bar(d, c, adj=c / 2) for d, (c, _, _) in held.items()]
                                + [night.bar(night.day(1), 50.5)])
    vendor.history["ABC.US"] = ([night.bar(night.day(n), 40.0, adj=20.0) for n in range(10, 1, -1)]
                                + [night.bar(night.day(1), 20.0)])
    monkeypatch.setattr(night.ingest, "REPAIR_CAP", 1)

    first, _ = night.night(db, monkeypatch, vendor)          # one split re-pull fits under the cap

    vendor.tape = night.tape(0, SPY=602.0, XYZ=51.0, ABC=20.5)
    vendor.bulk["splits"] = []                                # the file named each split once
    for tk, px in (("XYZ.US", 51.0), ("ABC.US", 20.5)):
        vendor.history[tk].append(night.bar(night.day(0), px))
    second, _ = night.night(db, monkeypatch, vendor)
    for tk in ("XYZ.US", "ABC.US"):
        close, adj, _ = night.closes(db, tk)[night.day(5)]
        assert adj == close / 2, f"{tk}'s history carries its split by the second night"
    owed = first["detail"]["repull_deferred"]
    assert first["status"] == "amber" and len(owed) == 1
    assert "cap of 1" in next(iter(owed.values()))
    assert second["detail"]["repull_deferred"] == {}


def test_a_re_pull_rewrites_the_whole_stored_history_and_takes_the_vendors_corrections(db,
                                                                                    monkeypatch):
    """A31, and the two benign differences A14's check must let through. PENNY.US holds bars from
    twelve years back; tonight's dividend re-pulls it. The vendor's history quotes its sub-dollar
    closes to three decimals where the bulk file wrote four (DCX.US's shape), and it has corrected
    one session the store holds as a frozen zero-volume copy of the day before (CTVA.US's)."""
    stored_days = (4500, 4000, 3700, 3000, 100, 3, 2, 1)
    stored = dict(zip(stored_days, (0.5123, 0.4211, 0.3333, 0.25, 0.1044, 0.0734, 0.0734, 0.0603)))
    served = dict(zip(stored_days, (0.512, 0.421, 0.333, 0.25, 0.104, 0.073, 0.068, 0.06)))
    served[0] = 0.049
    with db.cursor() as cur:
        _spy(cur)
        night.name(cur, "PENNY.US")
        night.store(cur, "PENNY.US", [night.bar(night.day(n), c, volume=0 if n == 2 else 10_000)
                                      for n, c in stored.items()])
    vendor = night.Vendor()
    vendor.tape = night.tape(0, SPY=601.0, PENNY=0.0494)
    vendor.bulk["dividends"] = [dict(code="PENNY", exchange="US", date=night.day(0),
                                     dividend=0.001)]
    vendor.history["PENNY.US"] = [night.bar(night.day(n), c, adj=round(c * 0.98, 4))
                                  for n, c in served.items()]

    run, raised = night.night(db, monkeypatch, vendor)
    now = night.closes(db, "PENNY.US")
    for n, c in served.items():
        assert now[night.day(n)][1] == round(c * 0.98, 4), (
            f"{night.day(n)} is on the dividend's basis — {now[night.day(n)]}")
    assert now[night.day(2)][0] == 0.068, "the frozen session takes the vendor's real print"
    assert raised is None and run["status"] == "green", run["detail"].get("amber")
    assert min(now) == night.day(4500), "nothing older than the store's own first bar is invented"
    assert dt.date.today() - dt.timedelta(days=3650) > dt.date.fromisoformat(min(now))
