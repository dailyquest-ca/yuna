"""The autopsy step tells a heartbeat's own red from a death nobody recorded.

Until 2026-09-13 every crash left two red rows: the one `Heartbeat.__exit__` wrote with the
traceback, and a second from `report_fail.py` claiming the job "died pre-heartbeat" — runs 799/800
and 879/880 for ingest-universe, 807/808 for backup. The run id the heartbeat now stamps into
`detail.actions` is what lets the autopsy find its own run's row.
"""
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
from db import Heartbeat                                                   # noqa: E402

RID = "424242"


def autopsy(tmp_path, job="probe", rid=RID, tail="Traceback: boom"):
    out = tmp_path / "job.out"
    out.write_text(tail)
    env = {**os.environ}
    env.pop("GITHUB_RUN_ID", None)
    if rid:
        env["GITHUB_RUN_ID"] = rid
    res = subprocess.run([sys.executable, str(ROOT / "src" / "report_fail.py"), job, str(out)],
                         capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def rows(db, job="probe"):
    with db.cursor() as cur:
        cur.execute("select id, status, detail from runs where job=%s order by id", (job,))
        return cur.fetchall()


def seed(db, status, *, rid=RID, detail=None, job="probe"):
    d = {"actions": {"run_id": rid, "attempt": "1"}} if rid else {}
    d.update(detail or {})
    with db.cursor() as cur:
        cur.execute("""insert into runs (job, status, dry_run, started_at, finished_at, rows_written, detail)
                       values (%s, %s, false, now(), case when %s='running' then null else now() end,
                               %s, %s) returning id""",
                    (job, status, status, 0 if status != "running" else None, json.dumps(d)))
        rid_ = cur.fetchone()[0]
    db.commit()
    return rid_


def test_the_heartbeat_stamps_the_actions_run_id_when_the_row_opens(db, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", RID)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with Heartbeat(db, "probe", dry_run=False) as hb:
        with db.cursor() as cur:
            cur.execute("select detail->'actions' from runs where id=%s", (hb.id,))
            assert cur.fetchone()[0] == {"run_id": RID, "attempt": "2"}, "stamped while still running"
    (_, status, detail), = rows(db)
    assert status == "green" and detail["actions"]["run_id"] == RID


def test_a_crash_the_heartbeat_recorded_gets_one_red_row_not_two(db, tmp_path):
    seed(db, "red", detail={"fatal": "HTTPError: 403"})
    out = autopsy(tmp_path)
    assert "appended" in out
    (_, status, detail), = rows(db)
    assert status == "red" and detail["fatal"] == "HTTPError: 403"
    assert detail["output_tail"] == "Traceback: boom"


def test_a_job_killed_mid_run_has_its_own_row_closed(db, tmp_path):
    seed(db, "running")
    seed(db, "running", rid="other")          # someone else's stuck row is not this run's business
    autopsy(tmp_path)
    got = {d["actions"]["run_id"]: s for _, s, d in rows(db)}
    assert got == {RID: "red", "other": "running"}


def test_a_step_failing_after_a_green_heartbeat_flips_the_row_red(db, tmp_path):
    """The 2026-09-05 backup: the dump closed green, the push was refused, the ledger kept saying
    green for a week."""
    seed(db, "green")
    out = autopsy(tmp_path)
    assert "flipped to red" in out
    (_, status, detail), = rows(db)
    assert status == "red" and detail["fatal"].startswith("died after the heartbeat closed green")


def test_a_death_before_any_heartbeat_still_gets_its_row(db, tmp_path):
    out = autopsy(tmp_path)
    assert "died before its heartbeat opened" in out
    (_, status, detail), = rows(db)
    assert status == "red" and detail["fatal"] == "job died pre-heartbeat"


def test_without_a_run_id_it_closes_any_stuck_row_of_the_job(db, tmp_path):
    """Local runs and rows from before the stamp: the old behaviour, kept."""
    seed(db, "running", rid=None)
    autopsy(tmp_path, rid=None)
    (_, status, _), = rows(db)
    assert status == "red"
