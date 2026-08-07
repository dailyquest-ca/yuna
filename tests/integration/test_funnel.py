"""The census, over a real database — specifically the part that decides who counts as dead.

§3.0 and §3.3 both say delisted names are retained. Until this test existed, a name that stopped
trading simply went quiet: `status` stayed `active`, nothing recorded that it had gone, and every
backtest ran on today's survivors. That is the survivorship bias §4.8 calls one of the two classic
sins, and it flatters every number in `docs/backtest-findings`.

The vendor calls are stubbed. What is under test is the bookkeeping, not the tape.
"""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import funnel                                                             # noqa: E402
import fixtures as world                                                  # noqa: E402


def stub_vendor(monkeypatch, listed, priced):
    """`listed` is what the exchange still lists; `priced` is the bulk tape."""
    def fake_get(url, calls, tries=3):
        calls[0] += 1
        if "exchange-symbol-list" in url:
            return [{"Code": c, "Type": "Common Stock", "Exchange": "NASDAQ"} for c in listed]
        if "eod-bulk-last-day" in url:
            return [{"code": c, "close": 50.0, "volume": 2_000_000} for c in priced]
        return {"data": []}                     # the screener decorates; it is not the census
    monkeypatch.setattr(funnel, "get", fake_get)
    monkeypatch.setattr(funnel, "FORCE", True)  # rebuild whatever the month guard thinks
    monkeypatch.setattr(funnel, "K", "test-key", raising=False)


def universe_row(conn, ticker):
    with conn.cursor() as cur:
        cur.execute("""select status, in_l0, delisted_at, note from universe where ticker=%s""",
                    (ticker,))
        row = cur.fetchone()
    return dict(zip(["status", "in_l0", "delisted_at", "note"], row)) if row else None


def test_a_name_absent_from_the_listing_is_marked_delisted_and_kept(db, monkeypatch):
    with db.cursor() as cur:
        world.add_name(cur, "GONE.US")
        world.flat_then_base(cur, "GONE.US")       # it has history, and the history stays
        world.add_name(cur, "ALIVE.US")
    db.commit()
    stub_vendor(monkeypatch, listed=["ALIVE"], priced=["ALIVE"])
    assert funnel.main() == 0

    gone = universe_row(db, "GONE.US")
    assert gone["status"] == "delisted" and gone["delisted_at"] is not None
    assert "exchange listing" in gone["note"]
    assert universe_row(db, "ALIVE.US")["status"] == "active"

    with db.cursor() as cur:                       # the bars are the whole point of retaining it
        cur.execute("select count(*) from prices where ticker='GONE.US'")
        assert cur.fetchone()[0] > 200


def test_a_holding_is_never_marked_delisted_by_a_census(db, monkeypatch):
    """A name we own dropping out of the listing is a question for Zak, not a bookkeeping event —
    and §3.0 says membership lists never drop a name the book owns."""
    with db.cursor() as cur:
        world.add_name(cur, "HELD.US", holding=True)
        world.flat_then_base(cur, "HELD.US")
    db.commit()
    stub_vendor(monkeypatch, listed=["OTHER"], priced=["OTHER"])
    assert funnel.main() == 0
    assert universe_row(db, "HELD.US")["status"] == "active"


def test_a_delisted_name_that_returns_is_active_again(db, monkeypatch):
    """Re-listings and ticker changes happen. The row should recover rather than stay a fossil."""
    with db.cursor() as cur:
        world.add_name(cur, "BACK.US")
    db.commit()
    stub_vendor(monkeypatch, listed=["OTHER"], priced=["OTHER"])
    assert funnel.main() == 0
    assert universe_row(db, "BACK.US")["status"] == "delisted"

    stub_vendor(monkeypatch, listed=["BACK", "OTHER"], priced=["BACK", "OTHER"])
    assert funnel.main() == 0
    row = universe_row(db, "BACK.US")
    assert row["status"] == "active" and row["in_l0"] is True


def test_the_census_records_what_it_did(db, monkeypatch):
    stub_vendor(monkeypatch, listed=["ALIVE"], priced=["ALIVE"])
    assert funnel.main() == 0
    with db.cursor() as cur:
        cur.execute("""select status, detail from runs where job='ingest-universe'
                       order by id desc limit 1""")
        status, detail = cur.fetchone()
    assert status == "green" and detail["stage"] == "census"


def test_the_month_guard_is_keyed_to_the_work_and_not_to_the_date(db, monkeypatch):
    """§4.2, ruled 2026-08-05: monthly work is guarded by whether it has run, never by the date.

    The old guard read `weekday==5 and day<=7` **before** opening the runs row, so a firing outside
    that window vanished without trace — this job had never produced a single runs row and L0 had
    never been rebuilt. Every firing now leaves a heartbeat, and the second firing of a month
    rebuilds nothing.
    """
    stub_vendor(monkeypatch, listed=["ALIVE"], priced=["ALIVE"])
    monkeypatch.setattr(funnel, "FORCE", False)          # the guard is what is under test
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")  # …and a guard only guards the clock
    assert funnel.main() == 0                            # month unbuilt -> rebuild
    assert funnel.main() == 0                            # same month -> exit clean

    with db.cursor() as cur:
        cur.execute("""select status, detail, rows_written from runs where job='ingest-universe'
                       order by id""")
        rows = cur.fetchall()
    assert len(rows) == 2, "every firing writes a heartbeat, including the one that does nothing"
    assert rows[0][0] == "green" and rows[0][1]["rebuilt"] is True and rows[0][2] > 0
    assert rows[1][0] == "green" and rows[1][1]["rebuilt"] is False
    assert rows[1][1]["month_built_at"], "the skip says which run did the month's work"


def test_a_hand_dispatch_is_never_thwarted_by_the_guard(db, monkeypatch):
    """Ruled by Zak, 2026-08-07: "I want to be able to manually run everything, and allow it to
    work OK. I don't want a manual run to be thwarted by the day."

    Every work-guard in the system exists to stop a duplicate SCHEDULED firing. None of them exists
    to argue with a person, and a `force` checkbox you have to remember is the guard defeating the
    human it was built for. So the guard reads the clock only when the clock started the run.
    """
    stub_vendor(monkeypatch, listed=["ALIVE"], priced=["ALIVE"])
    monkeypatch.setattr(funnel, "FORCE", False)          # no checkbox ticked, deliberately
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    assert funnel.main() == 0                            # the month's work is now done

    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    assert funnel.main() == 0                            # a person pressed the button
    with db.cursor() as cur:
        cur.execute("""select detail->>'rebuilt' from runs where job='ingest-universe'
                       order by id desc limit 1""")
        assert cur.fetchone()[0] == "true", "a hand run does the work, checkbox or not"


def test_a_missed_firing_is_picked_up_the_following_week(db, monkeypatch):
    """The failure the date key produced: a skipped firing lost the month. Here last month's
    rebuild is the only one on the ledger, so this week's firing does the work."""
    with db.cursor() as cur:
        cur.execute("""insert into runs (job, status, started_at, finished_at, rows_written, detail)
                       values ('ingest-universe','green', now() - interval '40 days',
                               now() - interval '40 days', 2700, '{"rebuilt": true}'::jsonb)""")
    db.commit()
    stub_vendor(monkeypatch, listed=["ALIVE"], priced=["ALIVE"])
    monkeypatch.setattr(funnel, "FORCE", False)
    assert funnel.main() == 0
    with db.cursor() as cur:
        cur.execute("""select detail from runs where job='ingest-universe' order by id desc limit 1""")
        assert cur.fetchone()[0]["rebuilt"] is True


def test_a_dry_run_leaves_the_month_unbuilt(db, monkeypatch):
    """A rehearsal is not the work — otherwise a DRY_RUN dispatch would skip the month for real."""
    stub_vendor(monkeypatch, listed=["ALIVE"], priced=["ALIVE"])
    monkeypatch.setattr(funnel, "FORCE", False)
    monkeypatch.setattr(funnel, "DRY", True)
    assert funnel.main() == 0
    monkeypatch.setattr(funnel, "DRY", False)
    assert funnel.main() == 0
    with db.cursor() as cur:
        cur.execute("""select detail from runs where job='ingest-universe' order by id desc limit 1""")
        assert cur.fetchone()[0]["rebuilt"] is True


def test_a_non_us_listing_survives_a_us_census(db, monkeypatch):
    """The census reads the US exchange listing and nothing else, so it has no opinion about a
    Toronto listing. Without the guard, `VXC.TO` — the levered sleeve's own ETF — would be marked
    delisted on the first Saturday of every month.
    """
    with db.cursor() as cur:
        cur.execute("""insert into universe (ticker,name,kind,exchange,currency,status,in_l0)
                       values ('VXC.TO','Vanguard ex-Canada','stock','TO','CAD','active',false)
                       on conflict (ticker) do nothing""")
    db.commit()
    stub_vendor(monkeypatch, listed=["ALIVE"], priced=["ALIVE"])
    assert funnel.main() == 0
    assert universe_row(db, "VXC.TO")["status"] == "active"
