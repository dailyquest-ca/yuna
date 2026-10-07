"""Last-resort autopsy — the workflow's step that runs on a failure, and on a cancel that landed
before the job's work finished (2026-10-07: a cancel or a timeout is not a failure() to GitHub,
and the rows of the jobs it killed stayed `running` for ever).

Ships the captured output tail into `runs` as a red row when a job dies. Standalone on purpose: it
imports nothing from `db.py`, because a job that died on an import error is exactly the death this
has to record.

Three deaths, told apart by the Actions run id AND attempt `Heartbeat` stamps into `detail.actions`
when the row opens (2026-09-13). The attempt matters: "Re-run all jobs" keeps the run id, and a
second attempt that dies before its heartbeat must not rewrite the first attempt's green as red.
  * a row of this run still `running` — the job was killed mid-flight: close it red with the tail;
  * a row of this run already `red` — the heartbeat recorded the crash itself: append the tail to
    THAT row rather than writing a second red that claims the job "died pre-heartbeat" (every
    crash used to leave two rows, one of them lying — runs 799/800, 879/880, 807/808);
  * a row of this run closed `green` (or amber) — a later step failed, the 2026-09-05 backup shape:
    flip it red, because a workflow that failed is not a green run whatever the Python thought;
  * no row of this run at all — the job really did die before its heartbeat opened: a new row,
    a rehearsal's row when the dispatch was a DRY_RUN (2026-10-07).
Without a run id (a local run, an old row) it falls back to closing any `running` row of the job.

**A cancelled trigger** (2026-10-07, QC A48). `pipeline.yml`'s `slot` job calls this for the
scheduled ingest that triggered the chain when GitHub reports that run CANCELLED. A run cancelled
before it started — GitHub drops a pending run when a newer one joins its concurrency group —
writes no row and runs no autopsy of its own, and the chain behind it used to re-score yesterday's
tape under a green freshness line. That call names the run with AUTOPSY_RUN_ID/AUTOPSY_RUN_ATTEMPT
and sets AUTOPSY_CANCELLED, which changes two of the rules above: a row of that run already closed
green or amber is left alone (the work finished before the cancel reached it), and a run that left
no row at all is recorded red — unless it is `ingest-daily` and the night is already green by the
retry's own test, so a redundant firing cancelled after a good one cannot hold a good night's buys.
"""
import sys, os, json, psycopg

job = sys.argv[1]; path = sys.argv[2] if len(sys.argv) > 2 else None
tail = "(no output captured)"
if path and os.path.exists(path):
    tail = open(path, errors="replace").read()[-1400:]


def url():
    """`db.db_url()`, copied rather than imported (see the module docstring): a URI takes
    `?sslmode=`, a keyword/value DSN takes ` sslmode=`, and DB_SSLMODE overrides for a local
    database. The old one-liner turned a DSN's database name into `postgres?sslmode=require`."""
    u = os.environ["DATABASE_URL"]
    mode = os.environ.get("DB_SSLMODE", "require")
    if not mode or "sslmode" in u:
        return u
    if "://" in u:
        return u + ("&" if "?" in u else "?") + f"sslmode={mode}"
    return f"{u} sslmode={mode}"


# the run being autopsied: this job's own, or the cancelled trigger the `slot` job names
rid = os.environ.get("AUTOPSY_RUN_ID") or os.environ.get("GITHUB_RUN_ID")
att = os.environ.get("AUTOPSY_RUN_ATTEMPT") or os.environ.get("GITHUB_RUN_ATTEMPT")
cancelled = os.environ.get("AUTOPSY_CANCELLED", "false").lower() in ("1", "true", "yes")
# The retry's own test for "the night is already green" (`src/ingest.py`, SECOND_RUN): a green,
# non-dry ingest-daily run inside four hours that did more than find the vendor unpublished. Four
# hours is the operating constant of record (§5.6, 2026-09-13), and tests/test_retry_coupling.py
# keeps this copy equal to the retry's.
NIGHT_GREEN = """select id from runs where job = 'ingest-daily' and status = 'green'
                   and dry_run = false and started_at > now() - interval '4 hours'
                   and not (detail ? 'awaiting_vendor')
                 order by id desc limit 1"""
# A rehearsal's death is a rehearsal's row (QC 2026-10-07, A24; learning 67). The new-row path
# below wrote `dry_run=false` whatever the dispatch said, so a DRY_RUN dispatch that died before
# its heartbeat opened left a live red under a price-critical name — and `freshness()` held the
# desk on it. The workflow hands the autopsy the same DRY_RUN its job got; read as `db.dry()`
# reads it, copied rather than imported for the reason at the top of this file.
dry = os.environ.get("DRY_RUN", "false").lower() in ("1", "true", "yes")
# this run's rows, or — with no run id to go on — any row of the job
MINE = """(%s::text is null or (detail->'actions'->>'run_id' = %s
           and coalesce(detail->'actions'->>'attempt', '') = coalesce(%s::text, '')))"""
# `clock_timestamp()` rather than `now()` (the transaction's start), as in `db.Heartbeat` (QC
# 2026-10-07, A37): here each write opens or shares one short transaction, so the two barely
# differ, but a finish time in `runs` means the clock in every writer or it means nothing.
with psycopg.connect(url()) as conn, conn.cursor() as cur:
    wrote = True
    killed = json.dumps({"fatal": "cancelled mid-run" if cancelled else "died mid-run",
                         "output_tail": tail})
    cur.execute(f"""update runs set finished_at=clock_timestamp(), status='red',
                      detail = coalesce(detail,'{{}}'::jsonb) || %s::jsonb
                    where job=%s and status='running' and {MINE}""", (killed, job, rid, rid, att))
    if cur.rowcount:
        how = f"closed {cur.rowcount} stuck run(s)"
    else:
        row = None
        if rid:
            cur.execute(f"""select id, status from runs where job=%s and {MINE}
                            order by id desc limit 1""", (job, rid, rid, att))
            row = cur.fetchone()
        if row and row[1] == "red":
            cur.execute("update runs set detail = coalesce(detail,'{}'::jsonb) || %s::jsonb where id=%s",
                        (json.dumps({"output_tail": tail}), row[0]))
            how = f"appended the output tail to the heartbeat's own red (run {row[0]})"
        elif row and cancelled:
            wrote = False
            how = f"run {row[0]} closed {row[1]} before the cancel reached it — left as it is"
        elif row:
            cur.execute("""update runs set status='red', finished_at=clock_timestamp(),
                             detail = coalesce(detail,'{}'::jsonb) || %s::jsonb where id=%s""",
                        (json.dumps({"fatal": f"died after the heartbeat closed {row[1]}",
                                     "output_tail": tail}), row[0]))
            how = f"the heartbeat had closed {row[1]} before the job died — run {row[0]} flipped to red"
        else:
            green = None
            if cancelled and job == "ingest-daily":
                cur.execute(NIGHT_GREEN)
                green = cur.fetchone()
            if green:
                wrote = False
                how = (f"nothing written: the night is already green (run {green[0]}), so the "
                       f"cancelled firing lost nothing the retry would not have skipped")
            else:
                # stamped like a heartbeat's row, so a re-run of this step finds it, not a twin
                stamp = {"actions": {"run_id": rid, "attempt": att}} if rid else {}
                fatal = ("cancelled before its heartbeat opened — its work never ran" if cancelled
                         else "job died pre-heartbeat")
                cur.execute("""insert into runs(job,finished_at,status,dry_run,detail)
                               values (%s,clock_timestamp(),'red',%s,%s)""",
                            (job, dry, json.dumps({**stamp, "fatal": fatal, "output_tail": tail})))
                how = ("new row: the run was cancelled before its heartbeat opened" if cancelled
                       else "new row: the job died before its heartbeat opened")
    conn.commit()
print(f"red autopsy written for {job} ({how})" if wrote else f"autopsy for {job}: {how}")
