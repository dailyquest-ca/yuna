"""The pacing guard on bulk writers (added after the 2026-08-03 outage).

The database was under 1 GB when it went down. What filled the volume was `pg_wal` — a sustained
bulk upsert generated write-ahead log faster than checkpoints could recycle it, and the fatal
error named the WAL directory, not a table. `max_wal_size` is 4 GB on this instance, so Postgres
is *permitted* to let that happen. Nothing but the writer can pace itself, so the writer does.

No database here: the guard is a decision about when to stop, and that is testable on its own.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import db                                                                 # noqa: E402


class FakeCur:
    def __init__(self, readings):
        self.readings, self.calls = list(readings), 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=None):
        self._sql = sql

    def fetchone(self):
        if "pg_ls_waldir" in getattr(self, "_sql", ""):
            v = self.readings[min(self.calls, len(self.readings) - 1)]
            self.calls += 1
            if isinstance(v, Exception):
                raise v
            return (v,)
        return (None,)


class FakeConn:
    def __init__(self, readings):
        self.cur = FakeCur(readings)

    def cursor(self):
        return self.cur


GB = 1024 ** 3


def test_it_proceeds_when_the_wal_is_small(monkeypatch):
    monkeypatch.setattr(db.time, "sleep", lambda s: None)
    assert db.wait_for_wal(FakeConn([100 * 1024 * 1024]), ceiling_bytes=GB) is True


def test_it_waits_and_then_proceeds_once_checkpoints_catch_up(monkeypatch):
    """The normal case: pressure builds, the checkpointer drains it, the job carries on. Pausing
    costs minutes; not pausing cost a night."""
    slept = []
    monkeypatch.setattr(db.time, "sleep", slept.append)
    conn = FakeConn([2 * GB, 2 * GB, 100 * 1024 * 1024])
    assert db.wait_for_wal(conn, ceiling_bytes=GB, max_wait_s=120, poll_s=10) is True
    assert slept, "it should have waited rather than writing straight through"


def test_it_gives_up_rather_than_running_the_disk_to_zero(monkeypatch):
    """The case that matters. If the WAL will not drain, the answer is to STOP — a truncated
    backfill is resumable, a database that cannot finish crash recovery is not."""
    monkeypatch.setattr(db.time, "sleep", lambda s: None)
    conn = FakeConn([4 * GB])
    assert db.wait_for_wal(conn, ceiling_bytes=GB, max_wait_s=30, poll_s=10) is False


def test_a_role_that_cannot_read_the_wal_directory_never_blocks_the_job(monkeypatch):
    """The guard must not become a new way to fail. If the reading is unavailable, proceed —
    a diagnostic that can halt production is worse than the thing it diagnoses."""
    monkeypatch.setattr(db.time, "sleep", lambda s: None)
    conn = FakeConn([PermissionError("no pg_ls_waldir for you")])
    assert db.wal_bytes(conn.cursor()) is None
    assert db.wait_for_wal(FakeConn([PermissionError("nope")]), ceiling_bytes=GB) is True
