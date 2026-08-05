"""The freshness line, and the two rules it got wrong (§4.7, §5.6 — both ruled 2026-08-05).

This is the file for the bug that gagged the desk. `Heartbeat` went amber at thirty minutes of
schedule drift, `freshness()` held tickets on any amber in a price-critical domain, and so an
`ingest-daily` that started 194 minutes late with the bars perfectly current produced a brief
carrying "tickets held" — on a night when nothing at all was wrong with the data. RS.US and CTS.US
sat armed and frozen behind a clock.

The law now: **stale means the bars, not the clock.** Tickets are held when the bars are old, when
a price-critical job failed, or when the chain ran out of order. Lateness alone holds nothing.
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import db as dbm                                                          # noqa: E402
import fixtures as world                                                  # noqa: E402


def bars_today(cur):
    """Current bars, so nothing in these tests is stale for the reason the plan means."""
    world.add_name(cur, "AAA.US")
    world.flat_then_base(cur, "AAA.US")


def run(cur, job, status="green", *, started="now()", finished="now()", detail="{}",
        dry_run=False):
    cur.execute(f"""insert into runs (job, status, started_at, finished_at, dry_run, detail)
                    values (%s, %s, {started}, {finished}, %s, %s::jsonb) returning id""",
                (job, status, dry_run, detail))
    return cur.fetchone()[0]


# --------------------------------------------------------------------- the producer (§4.7)

def test_a_late_start_is_recorded_and_never_ambers(db, monkeypatch):
    """§4.7: schedule drift is not a half-failure and never turns a job amber.

    The acceptance case from the work order, exactly: `ingest-daily` starts three hours after its
    02:00 slot and completes its work. The run is GREEN, and the lateness is a separate,
    non-blocking field."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    due = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3))
    with dbm.Heartbeat(db, "ingest-daily", scheduled_utc=due.strftime("%H:%M")) as hb:
        hb.rows = 44401
    with db.cursor() as cur:
        cur.execute("select status, detail from runs where job='ingest-daily' order by id desc")
        status, detail = cur.fetchone()
    assert status == "green", "a late job that did its work is green (§4.7)"
    assert detail.get("amber") is None, "lateness must not write an amber reason"
    assert 175 <= detail["late_minutes"] <= 185


def test_a_genuine_half_failure_still_ambers(db):
    """Amber remains for real partial failure — the point was never to disarm it."""
    with dbm.Heartbeat(db, "ingest-daily") as hb:
        hb.amber("bulk feed returned 0 rows for the NYSE tape")
    with db.cursor() as cur:
        cur.execute("select status from runs where job='ingest-daily' order by id desc")
        assert cur.fetchone()[0] == "amber"


# --------------------------------------------------------------------- the consumer (§5.6)

def test_lateness_prints_on_the_line_and_holds_nothing(db):
    """The whole acceptance test: `late: ingest-daily +180m` on the line, and no `tickets held`."""
    with db.cursor() as cur:
        bars_today(cur)
        run(cur, "ingest-daily", detail='{"late_minutes": 180.0}')
        run(cur, "score")
        run(cur, "check")
    db.commit()
    line, tickets = dbm.freshness(db)
    assert "late: ingest-daily +180m" in line
    assert "tickets held" not in line
    assert tickets is True


def test_a_trivial_drift_is_not_worth_the_ink(db):
    with db.cursor() as cur:
        bars_today(cur)
        run(cur, "ingest-daily", detail='{"late_minutes": 4.0}')
    db.commit()
    line, tickets = dbm.freshness(db)
    assert "late:" not in line and tickets is True


def test_older_rows_written_before_the_ruling_still_read(db):
    """`runs` keeps its history, and the drift used to live under `schedule.drift_minutes`."""
    with db.cursor() as cur:
        bars_today(cur)
        run(cur, "ingest-daily", detail='{"schedule": {"drift_minutes": 194.0}}')
    db.commit()
    line, tickets = dbm.freshness(db)
    assert "late: ingest-daily +194m" in line and tickets is True


def test_a_price_critical_failure_still_holds_tickets(db):
    """§5.6's second condition — the one lateness was being mistaken for."""
    with db.cursor() as cur:
        bars_today(cur)
        run(cur, "ingest-daily", "red")
    db.commit()
    line, tickets = dbm.freshness(db)
    assert "tickets held" in line and tickets is False


def test_a_score_older_than_the_ingest_beside_it_holds_tickets(db):
    """§5.6's third condition: the chain ran **out of order**, so `score` ranked yesterday's world.

    This is what the `needs:` chain (§4.2) makes impossible and this assertion makes visible — the
    old freshness had no concept of order at all, and caught it only by accident, through the amber
    that also fired on mere lateness."""
    with db.cursor() as cur:
        bars_today(cur)
        run(cur, "score", started="now() - interval '90 minutes'",
            finished="now() - interval '80 minutes'")
        run(cur, "ingest-daily", started="now() - interval '40 minutes'",
            finished="now() - interval '10 minutes'")
    db.commit()
    line, tickets = dbm.freshness(db)
    assert "out of order" in line and tickets is False


def test_the_ordinary_chain_reads_in_order(db):
    with db.cursor() as cur:
        bars_today(cur)
        run(cur, "ingest-daily", started="now() - interval '60 minutes'",
            finished="now() - interval '50 minutes'")
        run(cur, "score", started="now() - interval '45 minutes'",
            finished="now() - interval '40 minutes'")
        run(cur, "check")
    db.commit()
    line, tickets = dbm.freshness(db)
    assert tickets is True and "out of order" not in line


def test_a_dry_run_ingest_cannot_gag_the_desk(db):
    """A dry run writes nothing, so it cannot leave the derived numbers behind the source rows."""
    with db.cursor() as cur:
        bars_today(cur)
        run(cur, "score", started="now() - interval '90 minutes'",
            finished="now() - interval '80 minutes'")
        run(cur, "ingest-daily", started="now() - interval '20 minutes'", dry_run=True)
    db.commit()
    _, tickets = dbm.freshness(db)
    assert tickets is True
