"""The harness must clear everything the jobs write, or tests leak into each other.

Twice now a table was added and not added to the clean-slate list: a config override governed every
later test *and every later run*, and a stale corporate action made an insert collide. This test
pins the list against the schema rather than against anyone's memory of it.
"""
import re
import pathlib

CONFTEST = pathlib.Path(__file__).resolve().parent / "conftest.py"


def test_every_job_written_table_is_cleared_between_tests(db):
    with db.cursor() as cur:
        # the tables carrying the "jobs only" guard are by definition the ones a job writes
        cur.execute("""select distinct c.relname from pg_trigger t
                       join pg_class c on c.oid = t.tgrelid
                       join pg_proc p on p.oid = t.tgfoid
                       where p.proname = 'yuna_jobs_only' and not t.tgisinternal""")
        guarded = {r[0] for r in cur.fetchall()}

    body = CONFTEST.read_text()
    truncated = set(re.findall(r"[a-z_]+", body.split("truncate")[1].split('"""')[0]))
    missing = guarded - truncated - {"universe"}          # universe is deleted, not truncated
    assert not missing, f"tables a job writes but the harness never clears: {sorted(missing)}"


def test_the_session_writable_tables_are_not_guarded(db):
    """§4.3's other half: a session must be able to write briefs, tickets, observations and
    transactions. A guard trigger on any of them would silently break every runbook."""
    with db.cursor() as cur:
        cur.execute("""select distinct c.relname from pg_trigger t
                       join pg_class c on c.oid = t.tgrelid
                       join pg_proc p on p.oid = t.tgfoid
                       where p.proname = 'yuna_jobs_only' and not t.tgisinternal""")
        guarded = {r[0] for r in cur.fetchall()}
    assert not guarded & {"briefs", "tickets", "observations", "transactions", "config"}
