"""Last-resort autopsy: when a job dies before (or without) writing its heartbeat,
the workflow's failure step ships the captured output tail into runs as a red row."""
import json
import os
import sys

import psycopg


def main() -> int:
    job = sys.argv[1]; path = sys.argv[2] if len(sys.argv) > 2 else None
    tail = "(no output captured)"
    if path and os.path.exists(path):
        with open(path, errors="replace") as fh:
            tail = fh.read()[-1400:]
    u = os.environ["DATABASE_URL"]
    u += "" if "sslmode" in u else ("&" if "?" in u else "?") + "sslmode=require"
    with psycopg.connect(u) as conn, conn.cursor() as cur:
        # a job that opened a heartbeat and then died outside the context manager leaves a row
        # stuck on 'running' forever, which reads as "still working" to every freshness check
        cur.execute("""update runs set finished_at=now(), status='red',
                         detail = coalesce(detail,'{}'::jsonb) || %s::jsonb
                       where job=%s and status='running'""",
                    (json.dumps({"fatal": "died mid-run", "output_tail": tail}), job))
        orphans = cur.rowcount
        if not orphans:
            cur.execute(
                "insert into runs(job,finished_at,status,dry_run,detail)"
                " values (%s,now(),'red',false,%s)",
                (job, json.dumps({"fatal": "job died pre-heartbeat", "output_tail": tail})))
        conn.commit()
    print(f"red autopsy written for {job} ({'closed a stuck run' if orphans else 'new row'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
