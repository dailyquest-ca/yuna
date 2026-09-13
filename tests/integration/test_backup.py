"""The backup, over a real database — the guard, the exclusions, and the commit as the work.

Written after 2026-09-05. The dump ran, the heartbeat closed green with 3,753,011 rows, and the
workflow's separate commit step was refused by GitHub a minute later (385 MB against a 100 MB file
limit). The following Saturday read that green row, wrote "backed up 2026-09-05", and exited —
September had no backup anywhere. Every test here is a shape of that day.

Git is never run from a test: the commit is stubbed, and outside Actions the job does not commit.
"""
import gzip
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import backup                                                             # noqa: E402


@pytest.fixture
def out(monkeypatch, tmp_path):
    """A throwaway `backups/` and no Actions, so nothing is ever pushed from a test."""
    d = tmp_path / "backups"
    monkeypatch.setattr(backup, "OUT", str(d))
    monkeypatch.setattr(backup, "FORCE", False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    return d


def ledger_row(db, rows=3_753_011):
    """What 2026-09-05 left behind: a green backup row with rows written, this month."""
    with db.cursor() as cur:
        cur.execute("""insert into runs (job, status, started_at, finished_at, rows_written, detail)
                       values ('backup', 'green', now(), now(), %s, '{"stage": "dump"}'::jsonb)""",
                    (rows,))
    db.commit()


def newest(db):
    with db.cursor() as cur:
        cur.execute("""select status, rows_written, detail from runs where job='backup'
                       order by id desc limit 1""")
        return cur.fetchone()


def test_the_dump_leaves_out_what_it_says_it_leaves_out(db, out):
    with db.cursor() as cur:
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values ('KEEP.US','Keep','stock','USD','active')""")
        cur.execute("insert into prices (ticker,d,close) values ('KEEP.US',current_date,10)")
    db.commit()
    assert backup.main() == 0

    path = backup.month_file()
    assert path and path.startswith(str(out)), "the dump lands in this month's file"
    dump = json.load(gzip.open(path, "rt"))
    assert "universe" in dump and "runs" in dump, "the decisions are in"
    for table in backup.SKIP:
        assert table not in dump, f"{table} is excluded by name"
    assert dump["_meta"]["excluded"] == sorted(backup.SKIP), "and the file says so itself"
    assert dump["_meta"]["prices_excluded"]["rows"] == 1

    status, rows, detail = newest(db)
    assert status == "green" and rows > 0
    assert detail["excluded"] == sorted(backup.SKIP)
    assert detail["committed"] is False, "outside Actions the dump is written and not pushed"


def test_a_green_ledger_row_with_no_file_does_not_skip_the_month(db, out, monkeypatch):
    """2026-09-12: the ledger said 09-05 had backed the month up; the checkout had no such file."""
    ledger_row(db)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    assert backup.main() == 0
    status, rows, detail = newest(db)
    assert detail["stage"] == "dump" and detail["file_missing"] is True
    assert detail["ledger_said"], "the row says which ledger entry it refused to believe"
    assert rows > 0 and backup.month_file() is not None


def test_a_ledger_row_and_a_file_together_skip_the_month(db, out, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    assert backup.main() == 0                            # month unbacked -> dump
    assert backup.main() == 0                            # same month -> exit clean
    status, rows, detail = newest(db)
    assert status == "green" and rows == 0
    assert detail["stage"] == "guard" and detail["backed_up"] is False
    assert detail["month_backed_up_at"] and detail["file"], "the skip names the run and the file"
    with db.cursor() as cur:
        cur.execute("select count(*) from runs where job='backup'")
        assert cur.fetchone()[0] == 2, "every firing writes a heartbeat, the skip included"


def test_a_hand_dispatch_is_never_thwarted_by_the_guard(db, out, monkeypatch):
    """Ruled by Zak, 2026-08-07: a manual run is never thwarted by the day. The guard reads the
    clock only when the clock started the run."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    assert backup.main() == 0
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    assert backup.main() == 0
    assert newest(db)[2]["stage"] == "dump", "a person pressed the button, so it dumped"


def test_a_dump_over_githubs_limit_is_red_before_anything_is_committed(db, out, monkeypatch):
    """09-05 found the limit at the pre-receive hook, eight minutes in. The job finds it itself."""
    monkeypatch.setattr(backup, "GITHUB_FILE_LIMIT", 10)             # bytes: anything is too big
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    pushed = []
    monkeypatch.setattr(backup, "commit", lambda *a: pushed.append(a))
    with pytest.raises(RuntimeError, match="refuses files over"):
        backup.main()
    status, rows, detail = newest(db)
    assert status == "red" and "nothing was committed" in detail["fatal"]
    assert not pushed
    assert backup.month_file() is None, "an oversized dump is not left in the checkout"
    assert rows is None, "and the month stays unbacked on the ledger"


def test_a_refused_push_is_the_jobs_own_red(db, out, monkeypatch):
    """The 09-05 shape, with the commit inside the heartbeat: the ledger cannot say green."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")

    def refuse(*args):
        if args[0] == "push":
            raise RuntimeError("git push failed: remote: error: File backups/x.json.gz is 385.13 MB; "
                               "this exceeds GitHub's file size limit of 100.00 MB")
        return ""
    monkeypatch.setattr(backup, "git", refuse)
    with pytest.raises(RuntimeError, match="exceeds GitHub"):
        backup.main()
    status, rows, detail = newest(db)
    assert status == "red" and detail["stage"] == "commit"
    assert "100.00 MB" in detail["fatal"], "the server's words are in the runs row"
    assert rows is None, "a red run leaves the month unbacked"

    # …so the following week does the work again instead of reading a green row
    monkeypatch.setattr(backup, "git", lambda *args: "")
    assert backup.main() == 0
    status, rows, detail = newest(db)
    assert status == "green" and rows > 0 and detail["committed"] is True


def test_a_dry_run_leaves_the_month_unbacked(db, out, monkeypatch):
    """A rehearsal is not the work — otherwise a DRY_RUN dispatch would skip the month for real."""
    monkeypatch.setenv("DRY_RUN", "true")
    assert backup.main() == 0
    status, rows, detail = newest(db)
    assert rows == 0 and detail["committed"] is False

    monkeypatch.delenv("DRY_RUN")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    assert backup.main() == 0
    assert newest(db)[2]["stage"] == "dump"
