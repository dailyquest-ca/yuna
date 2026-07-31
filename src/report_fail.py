"""Last-resort autopsy: when a job dies before (or without) writing its heartbeat,
the workflow's failure step ships the captured output tail into runs as a red row."""
import sys, os, json, psycopg
job = sys.argv[1]; path = sys.argv[2] if len(sys.argv) > 2 else None
tail = "(no output captured)"
if path and os.path.exists(path):
    tail = open(path, errors="replace").read()[-1400:]
u = os.environ["DATABASE_URL"]
u += "" if "sslmode" in u else ("&" if "?" in u else "?") + "sslmode=require"
with psycopg.connect(u) as conn, conn.cursor() as cur:
    cur.execute("insert into runs(job,finished_at,status,dry_run,detail) values (%s,now(),'red',false,%s)",
                (job, json.dumps({"fatal": "job died pre-heartbeat", "output_tail": tail})))
    conn.commit()
print("red autopsy row written for", job)
