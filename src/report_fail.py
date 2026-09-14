"""Last-resort autopsy — the workflow's `if: failure()` step.

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
  * no row of this run at all — the job really did die before its heartbeat opened: a new row.
Without a run id (a local run, an old row) it falls back to closing any `running` row of the job.
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


rid = os.environ.get("GITHUB_RUN_ID")
att = os.environ.get("GITHUB_RUN_ATTEMPT")
# this run's rows, or — with no run id to go on — any row of the job
MINE = """(%s::text is null or (detail->'actions'->>'run_id' = %s
           and coalesce(detail->'actions'->>'attempt', '') = coalesce(%s::text, '')))"""
with psycopg.connect(url()) as conn, conn.cursor() as cur:
    killed = json.dumps({"fatal": "died mid-run", "output_tail": tail})
    cur.execute(f"""update runs set finished_at=now(), status='red',
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
        elif row:
            cur.execute("""update runs set status='red', finished_at=now(),
                             detail = coalesce(detail,'{}'::jsonb) || %s::jsonb where id=%s""",
                        (json.dumps({"fatal": f"died after the heartbeat closed {row[1]}",
                                     "output_tail": tail}), row[0]))
            how = f"the heartbeat had closed {row[1]} before the job died — run {row[0]} flipped to red"
        else:
            cur.execute("""insert into runs(job,finished_at,status,dry_run,detail)
                           values (%s,now(),'red',false,%s)""",
                        (job, json.dumps({"fatal": "job died pre-heartbeat", "output_tail": tail})))
            how = "new row: the job died before its heartbeat opened"
    conn.commit()
print(f"red autopsy written for {job} ({how})")
