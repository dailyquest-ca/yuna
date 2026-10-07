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
import db as dbm                                                           # noqa: E402
import fixtures as world                                                   # noqa: E402
from db import Heartbeat                                                   # noqa: E402

RID = "424242"


def autopsy(tmp_path, job="probe", rid=RID, attempt="1", tail="Traceback: boom", **extra):
    """Run the autopsy as the workflow step does. `extra` is the step's own env (DRY_RUN)."""
    out = tmp_path / "job.out"
    out.write_text(tail)
    env = {**os.environ}
    for k in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "DRY_RUN"):
        env.pop(k, None)
    env.update(extra)
    if rid:
        env["GITHUB_RUN_ID"] = rid
        env["GITHUB_RUN_ATTEMPT"] = attempt
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


def test_a_rerun_attempt_that_dies_early_leaves_the_first_attempts_green_alone(db, tmp_path):
    """"Re-run all jobs" keeps the run id and bumps the attempt. Attempt 1 composed the brief and
    closed green; attempt 2 dies at pip install. That green is a fact about a brief Zak received —
    the second attempt gets its own pre-heartbeat row instead."""
    seed(db, "green")                                   # attempt "1"
    out = autopsy(tmp_path, attempt="2")
    assert "died before its heartbeat opened" in out
    (_, first, _), (_, second, d2) = rows(db)
    assert first == "green" and second == "red" and d2["fatal"] == "job died pre-heartbeat"


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


def test_a_rehearsal_that_dies_before_its_heartbeat_leaves_a_rehearsals_row(db, tmp_path):
    """QC 2026-10-07 (A24) — learning 67's class, on the path that fix did not reach.

    A DRY_RUN dispatch of the chain whose `score` dies before its heartbeat (an import error on the
    branch being tried, a mistyped engine_mode) used to get a red row with `dry_run=false`. `score`
    is price-critical, so `freshness()` read that rehearsal as the live desk's state and held the
    buys for a day and a half. The workflow now hands the autopsy its job's DRY_RUN."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")                # the bars themselves are current
    db.commit()
    out = autopsy(tmp_path, job="score", DRY_RUN="true")
    assert "died before its heartbeat opened" in out
    with db.cursor() as cur:
        cur.execute("select status, dry_run from runs where job = 'score'")
        assert cur.fetchall() == [("red", True)], "red, and marked as the rehearsal it was"
    line, tickets = dbm.freshness(db)
    assert tickets is True and "score red" not in line, line


# ---- a cancelled trigger (QC 2026-10-07, A48) ---------------------------------------------------
#
# `pipeline.yml`'s slot job, when the scheduled ingest that triggered the chain ended CANCELLED.
# The run being autopsied is not the one executing the step, so it is named by AUTOPSY_RUN_ID —
# and the step's own GITHUB_RUN_ID (here "999") must not be mistaken for it.

CANCELLED = "31337"


def trigger(tmp_path, job="ingest-daily"):
    return autopsy(tmp_path, job=job, rid="999", attempt="1",
                   tail="the scheduled ingest-daily run ended cancelled",
                   AUTOPSY_RUN_ID=CANCELLED, AUTOPSY_RUN_ATTEMPT="1", AUTOPSY_CANCELLED="true")


def bars_today(db):
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
    db.commit()


def ingest_row(db, *, ago, detail=None, status="green", rows=40_000):
    with db.cursor() as cur:
        cur.execute("""insert into runs (job, status, dry_run, started_at, finished_at,
                                         rows_written, detail)
                       values ('ingest-daily', %s, false, now() - %s * interval '1 minute',
                               now() - %s * interval '1 minute', %s, %s) returning id""",
                    (status, ago, ago - 5, rows, json.dumps(detail or {})))
        rid_ = cur.fetchone()[0]
    db.commit()
    return rid_


def test_a_scheduled_ingest_cancelled_before_it_started_is_recorded_red(db, tmp_path):
    """A48. Both firings cancelled while pending behind a long dispatch: no row, no autopsy, and the
    previous night's green ingest still inside the 36-hour window — so the chain re-scored
    yesterday's tape and the freshness line released the buys. Now the night carries a red."""
    bars_today(db)
    ingest_row(db, ago=24 * 60)                              # last night's landing
    out = trigger(tmp_path)
    assert "cancelled before its heartbeat opened" in out
    with db.cursor() as cur:
        cur.execute("""select status, detail from runs where job = 'ingest-daily'
                        order by id desc limit 1""")
        status, detail = cur.fetchone()
    assert status == "red" and detail["fatal"].startswith("cancelled before its heartbeat opened")
    assert detail["actions"] == {"run_id": CANCELLED, "attempt": "1"}, "the cancelled run, named"
    line, tickets = dbm.freshness(db)
    assert tickets is False and "ingest-daily red" in line, line


def test_a_firing_cancelled_on_a_night_already_green_records_nothing(db, tmp_path):
    """The retry cancelled after the first firing landed the tape lost nothing: the retry would
    have exited "already green" by its own test (§5.6's four hours). A red here would hold a good
    night's buys on a cancellation that changed nothing."""
    bars_today(db)
    green = ingest_row(db, ago=50, detail={"tape": {"as_of": "2026-10-06", "rows": 11000}})
    out = trigger(tmp_path)
    assert f"the night is already green (run {green})" in out
    with db.cursor() as cur:
        cur.execute("select count(*) from runs where job = 'ingest-daily'")
        assert cur.fetchone()[0] == 1, "nothing written"
    _, tickets = dbm.freshness(db)
    assert tickets is True


def test_a_first_firing_that_found_the_vendor_unpublished_is_not_a_green_night(db, tmp_path):
    """The retry's own exclusion: a first firing that beat the vendor writes a green row that
    landed nothing. If the retry that should have fetched the tape is cancelled, the night has no
    tape — red, exactly as the retry itself would have gone red."""
    bars_today(db)
    ingest_row(db, ago=50, rows=0, detail={"awaiting_vendor": "the vendor's newest tape is old"})
    trigger(tmp_path)
    with db.cursor() as cur:
        cur.execute("""select status, detail->>'fatal' from runs where job = 'ingest-daily'
                        order by id desc limit 1""")
        status, fatal = cur.fetchone()
    assert status == "red" and fatal.startswith("cancelled before its heartbeat opened")


def test_a_cancel_that_landed_after_the_work_finished_leaves_the_green_alone(db, tmp_path):
    """A run cancelled after its heartbeat closed green did its work. The autopsy's ordinary rule
    — a later step failed, so flip it red — must not hold the buys on a cancel that changed
    nothing."""
    seed(db, "green", rid=CANCELLED, job="ingest-daily")
    out = trigger(tmp_path)
    assert "left as it is" in out
    assert [s for _, s, _ in rows(db, "ingest-daily")] == ["green"]


def test_a_cancelled_run_whose_row_still_reads_running_is_closed_red(db, tmp_path):
    """A runner GitHub lost runs no step at all, the autopsy included, so the row is still open
    when the chain behind the cancel starts. The chain closes it."""
    seed(db, "running", rid=CANCELLED, job="ingest-daily")
    trigger(tmp_path)
    (_, status, detail), = rows(db, "ingest-daily")
    assert status == "red" and detail["fatal"] == "cancelled mid-run"
