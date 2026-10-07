"""The heartbeat's closing write, on the paths where the job did not finish.

QC 2026-10-07 found the red written the wrong way twice over (A49, A75). It rode the job's own
transaction: a Python exception committed whatever the job had half-written along with the red, and
a database error left the transaction aborted, so the red UPDATE failed, `except: pass` hid it, and
the run stayed `running` with its traceback lost. The rule now: roll back, then write the red; and
if even that cannot be written, say so on stderr without ever replacing the job's own error.
"""
import pathlib
import sys
import time

import psycopg
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import db as dbm                                                          # noqa: E402


def _half_write(cur):
    """A write the job will not live to finish."""
    cur.execute("""insert into universe (ticker, name, kind, currency, status)
                   values ('HALF.US', 'Half', 'stock', 'USD', 'active')""")


def _after(migrated, run_id):
    """Read back on a fresh connection, so the answer never depends on the job's own one."""
    with psycopg.connect(migrated) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from universe where ticker = 'HALF.US'")
        half = cur.fetchone()[0]
        cur.execute("select status, finished_at is not null, detail from runs where id = %s",
                    (run_id,))
        return (half, *cur.fetchone())


@pytest.mark.parametrize("death", [KeyError("a bug"),
                                   SystemExit("refusing to fold a receipt"),
                                   KeyboardInterrupt()],
                         ids=["bug", "refusal", "interrupt"])
def test_a_job_that_raises_leaves_nothing_behind_but_its_red(db, migrated, death):
    """A49. The three ways a Python-level death reaches the heartbeat: a bug, a deliberate refusal
    (reconcile's `fold_fill`), and the SIGINT a cancelled Actions job receives. None of them may
    commit the half the job reached — a partial sheet or a half-folded manifest reads as a result."""
    with pytest.raises(type(death)):
        with dbm.Heartbeat(db, "probe", dry_run=False) as hb:
            with db.cursor() as cur:
                _half_write(cur)
            raise death
    half, status, finished, detail = _after(migrated, hb.id)
    assert half == 0, "the half-done write was rolled back, not committed with the red"
    assert status == "red" and finished
    assert detail["fatal"].startswith(type(death).__name__)
    assert type(death).__name__ in detail["trace"], "the traceback is in the row"


def test_a_database_error_closes_the_run_red_with_its_finish(db, migrated):
    """A75. The statement error aborts the transaction; the red is written after the rollback, so
    the row says red, says when, and keeps the heartbeat's own traceback — instead of `running`
    until an autopsy step, when one runs at all, overwrites it with "died mid-run"."""
    with pytest.raises(psycopg.errors.DivisionByZero):
        with dbm.Heartbeat(db, "probe", dry_run=False) as hb:
            with db.cursor() as cur:
                _half_write(cur)
                cur.execute("select 1/0")
    half, status, finished, detail = _after(migrated, hb.id)
    assert (half, status, finished) == (0, "red", True)
    assert detail["fatal"].startswith("DivisionByZero")


def test_a_red_that_cannot_be_written_is_said_and_never_masks_the_jobs_error(db, migrated, capsys):
    """A connection the server has killed cannot roll back or write anything. The heartbeat must
    say so — that line reaches the output tail the autopsy step writes into the row — and the
    exception that surfaces must still be the job's own."""
    conn = psycopg.connect(migrated)
    try:
        with pytest.raises(psycopg.OperationalError, match="terminating connection"):
            with dbm.Heartbeat(conn, "probe", dry_run=False) as hb:
                with conn.cursor() as cur:
                    cur.execute("select pg_terminate_backend(pg_backend_pid())")
    finally:
        conn.close()
    assert f"probe: could not record the red on run {hb.id}" in capsys.readouterr().err
    _, status, finished, _ = _after(migrated, hb.id)
    assert (status, finished) == ("running", False), "the row is the autopsy's to close"


# ---- how long a run took (A37) -----------------------------------------------------------------

PAUSE = 0.5          # seconds of work inside the body: measurable, and nothing more than that


def _seconds(migrated, run_id):
    with psycopg.connect(migrated) as conn, conn.cursor() as cur:
        cur.execute("select extract(epoch from finished_at - started_at) from runs where id = %s",
                    (run_id,))
        return float(cur.fetchone()[0])


def test_a_run_that_reads_and_never_commits_records_how_long_it_took(db, migrated):
    """A37. `check` reads the store, commits nothing, and closes its row — so `finished_at=now()`
    stamped the start of the transaction its first query opened. Production recorded check's
    115-second run as 0.015 seconds, and every job shaped like it as roughly nothing."""
    with dbm.Heartbeat(db, "probe", dry_run=False) as hb:
        with db.cursor() as cur:
            cur.execute("select 1")                 # the job's first read opens the transaction
        time.sleep(PAUSE)                           # ...and the work takes time inside it
    assert _seconds(migrated, hb.id) >= PAUSE


def test_a_run_that_dies_records_when_it_died(db, migrated):
    with pytest.raises(KeyError):
        with dbm.Heartbeat(db, "probe", dry_run=False) as hb:
            with db.cursor() as cur:
                cur.execute("select 1")
            time.sleep(PAUSE)
            raise KeyError("late in the run")
    assert _seconds(migrated, hb.id) >= PAUSE
