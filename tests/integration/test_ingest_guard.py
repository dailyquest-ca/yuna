"""The retry's red is for a night with NO tape (2026-09-02, the 22:23 schedule).

The two firings drift independently (learning 58), so the retry can arrive hours after the first
firing — or a hand dispatch — has already landed today's session. Then the vendor's newest tape
equals the store's date because the store HAS it, and a red there would be a false alarm on the
first night of the new slot. The tell is a run that landed rows for exactly that tape date inside
the night; the previous night's landing must not count, because that is the late-vendor case.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import ingest  # noqa: E402


def _run(cur, *, started, as_of, rows=44_401, dry_run=False, job="ingest-daily"):
    cur.execute(f"""insert into runs (job, status, started_at, finished_at, dry_run, rows_written,
                                      detail)
                    values (%s, 'green', now() - interval '{started}', now() - interval '{started}',
                            %s, %s, %s::jsonb) returning id""",
                (job, dry_run, rows, '{"tape": {"as_of": "%s", "rows": 11000}}' % as_of))
    return cur.fetchone()[0]


def test_a_tape_landed_this_night_is_recognised_and_last_nights_is_not(db):
    with db.cursor() as cur:
        assert ingest.tape_already_landed(cur, "2026-09-02") is None, "an empty night has no tape"
        old = _run(cur, started="20 hours", as_of="2026-09-01")
        assert ingest.tape_already_landed(cur, "2026-09-01") is None, (
            "the previous night's landing is the late-vendor case and must stay red")
        assert ingest.tape_already_landed(cur, "2026-09-02") is None
        this = _run(cur, started="5 hours", as_of="2026-09-02")
        assert ingest.tape_already_landed(cur, "2026-09-02") == this
        assert ingest.tape_already_landed(cur, "2026-09-01") is None, "the date must match exactly"
        db.commit()
        assert old != this


def test_rows_that_landed_nothing_do_not_count(db):
    with db.cursor() as cur:
        _run(cur, started="2 hours", as_of="2026-09-02", rows=0)
        assert ingest.tape_already_landed(cur, "2026-09-02") is None, "a green skip landed no tape"
        _run(cur, started="2 hours", as_of="2026-09-02", dry_run=True)
        assert ingest.tape_already_landed(cur, "2026-09-02") is None, "a dry run wrote nothing"
        _run(cur, started="2 hours", as_of="2026-09-02", job="ingest-universe")
        assert ingest.tape_already_landed(cur, "2026-09-02") is None, "another job is not this tape"
        db.commit()


# ------------------------------------------------------------------ the retry, run for real (A53)
#
# The retry's green test used to count any green run in the window that had not waited on the
# vendor. A hand dispatch never waits, so a named-date repair of an OLDER session — learning 59's
# own tool — or a blank-date press before the vendor posted satisfied it, and the retry exited
# without fetching: neither firing landed tonight's session, nothing went red, and the next night's
# tape sealed the hole for good.

import json                                                               # noqa: E402

import ingest_night as night                                              # noqa: E402


def _ledger(cur, *, started, as_of, scheduled, rows=44_401, requested=None, awaiting=False):
    detail = {"tape": {"as_of": as_of, "rows": 36_000, "requested": requested}}
    if scheduled:
        detail["schedule"] = {"due_utc": "earlier", "drift_minutes": 12.0}
    if awaiting:
        detail["awaiting_vendor"] = "today's session is not published yet — nothing written"
    cur.execute(f"""insert into runs (job, status, started_at, finished_at, dry_run, rows_written,
                                      detail)
                    values ('ingest-daily', 'green', now() - interval '{started}',
                            now() - interval '{started}', false, %s, %s::jsonb) returning id""",
                (rows, json.dumps(detail)))
    return cur.fetchone()[0]


def _held_back_world(db):
    """The store holds yesterday; the vendor has not posted today, so its newest is yesterday."""
    with db.cursor() as cur:
        night.name(cur, "SPY.US", kind="index")
        night.name(cur, "AAA.US")
        for tk, px in (("SPY.US", 600.0), ("AAA.US", 50.0)):
            night.store(cur, tk, [night.bar(night.day(2), px), night.bar(night.day(1), px + 1)])
    v = night.Vendor()
    v.tape = [night.bar(night.day(1), 601.0, code="SPY"), night.bar(night.day(1), 51.0, code="AAA")]
    return v


def test_a_named_date_repair_does_not_stand_in_for_tonights_tape(db, monkeypatch):
    vendor = _held_back_world(db)
    with db.cursor() as cur:
        _ledger(cur, started="3 hours", as_of=night.day(1), scheduled=True, rows=0, awaiting=True)
        _ledger(cur, started="2 hours", as_of=night.day(9), scheduled=False,
                requested=night.day(9))                    # Zak repairs an older missed session
        _ledger(cur, started="30 hours", as_of=night.day(1), scheduled=True)   # yesterday's landing
    run, raised = night.night(db, monkeypatch, vendor, retry=True)
    assert run["status"] == "red" and raised is not None, (
        "the retry must fetch, find the vendor unpublished, and say the night has no tape")
    assert "no tape" in str(raised)
    assert ("eod-bulk-last-day/US", {}) in vendor.asked, "it fetched instead of exiting"


def test_a_blank_hand_dispatch_that_re_landed_yesterday_does_not_either(db, monkeypatch):
    """The variant: pressed before the vendor posts, a blank-date dispatch re-upserts yesterday's
    tape green inside the night. It used to satisfy the green test — and, failing that, the
    landed-this-night test — though yesterday's tape was first landed last night."""
    vendor = _held_back_world(db)
    with db.cursor() as cur:
        _ledger(cur, started="30 hours", as_of=night.day(1), scheduled=True)   # first landed then
        _ledger(cur, started="3 hours", as_of=night.day(1), scheduled=True, rows=0, awaiting=True)
        _ledger(cur, started="2 hours", as_of=night.day(1), scheduled=False)   # the blank press
        assert ingest.tape_already_landed(cur, night.day(1)) is None
    run, raised = night.night(db, monkeypatch, vendor, retry=True)
    assert run["status"] == "red" and raised is not None


def test_a_firing_or_dispatch_that_first_landed_tonights_tape_still_lets_the_retry_go(db,
                                                                                    monkeypatch):
    """The other half, both shapes of it: a scheduled first firing inside the window, and a hand
    dispatch that was the FIRST run to land tonight's tape. Neither may cost a red."""
    vendor = _held_back_world(db)
    with db.cursor() as cur:
        _ledger(cur, started="2 hours", as_of=night.day(9), scheduled=False,
                requested=night.day(9))
        first = _ledger(cur, started="1 hour", as_of=night.day(1), scheduled=True)
        assert ingest.night_already_green(cur, run_id=-1) == first
    run, raised = night.night(db, monkeypatch, vendor, retry=True)
    assert raised is None and run["status"] == "green" and "already green" in run["detail"]["skipped"]
    assert vendor.asked == [], "an exit fetches nothing"

    with db.cursor() as cur:
        cur.execute("delete from runs")
        _ledger(cur, started="27 hours", as_of=night.day(2), scheduled=True)   # last night's
        by_hand = _ledger(cur, started="2 hours", as_of=night.day(1), scheduled=False)
        _ledger(cur, started="1 hour", as_of=night.day(1), scheduled=True, rows=0, awaiting=True)
    run, raised = night.night(db, monkeypatch, vendor, retry=True)
    assert raised is None and run["status"] == "green"
    assert f"run {by_hand} landed it" in run["detail"]["skipped"]


# ------------------------------------------------------------------ a session needs SPY.US (A47)
#
# The 2026-09-07 Labor Day file — 311 rows, a newer date, no SPY — went green and set `data_date`
# to a day no market printed. The engine's calendar is SPY.US's own bars, so a file without one is
# not a session: a first firing waits on it, the retry fails red, a hand dispatch refuses it.

def _labor_day(vendor):
    vendor.tape = [night.bar(night.day(0), 3.10, code="JUNK"),
                   night.bar(night.day(0), 52.0, code="AAA")]
    return vendor


def test_a_first_firing_waits_on_a_file_with_no_spy_and_the_retry_lands_the_real_one(db,
                                                                                   monkeypatch):
    vendor = _labor_day(_held_back_world(db))
    run, raised = night.night(db, monkeypatch, vendor)
    assert raised is None and run["status"] == "green"
    assert "carries no SPY.US bar" in run["detail"]["awaiting_vendor"]
    assert night.day(0) not in night.closes(db, "AAA.US"), "a file that is not a session lands nothing"

    vendor.tape.append(night.bar(night.day(0), 603.0, code="SPY"))   # the vendor posts the session
    run, raised = night.night(db, monkeypatch, vendor, retry=True)
    assert raised is None and run["status"] == "green"
    assert night.closes(db, "AAA.US")[night.day(0)][0] == 52.0
    assert night.closes(db, "SPY.US")[night.day(0)][0] == 603.0


def test_the_retry_fails_red_on_a_file_with_no_spy(db, monkeypatch):
    vendor = _labor_day(_held_back_world(db))
    with db.cursor() as cur:
        _ledger(cur, started="1 hour", as_of=night.day(0), scheduled=True, rows=0, awaiting=True)
    run, raised = night.night(db, monkeypatch, vendor, retry=True)
    assert run["status"] == "red" and "carries no SPY.US bar" in str(raised)
    assert night.day(0) not in night.closes(db, "AAA.US")


def test_a_hand_dispatch_refuses_to_land_a_file_with_no_spy(db, monkeypatch):
    vendor = _labor_day(_held_back_world(db))
    run, raised = night.night(db, monkeypatch, vendor, scheduled=False)
    assert run["status"] == "red" and "refusing to land it" in str(raised)
    assert night.day(0) not in night.closes(db, "AAA.US")
