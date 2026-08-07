"""backup — dump everything except daily bars, compressed, into the repo (plan §4.2).

Bars are a vendor-re-pullable cache; the decisions are not. The commit doubles as GitHub's
60-day schedule keep-alive, so the crons never fall asleep.
"""
import os, sys, gzip, json, datetime as dt
import psycopg
from db import connect, scheduled_run, Heartbeat

SKIP = {"prices"}
OUT = "backups"


FORCE = os.environ.get("FORCE", "false").lower() in ("1", "true", "yes")


def month_backed_up(cur):
    """§4.2's work key: when this calendar month's backup was taken, or None if it has not been.

    The ledger is the key. A backup is a run that finished green and actually wrote rows, so a dry
    run, a crash and this job's own skip rows all leave the month unbacked — which is the point:
    the guard asks whether the WORK happened, not whether a job ran on a particular date.
    """
    cur.execute("""select started_at from runs
                    where job in ('backup', 'monthly-backup') and status = 'green'
                      and not dry_run and coalesce(rows_written, 0) > 0
                      and date_trunc('month', started_at at time zone 'utc')
                          = date_trunc('month', now() at time zone 'utc')
                    order by id desc limit 1""")
    row = cur.fetchone()
    return row[0] if row else None


def main():
    stamp = dt.date.today().isoformat()
    with connect() as conn:
        with Heartbeat(conn, "backup", scheduled_utc="14:00") as hb:
            # §4.2, ruled 2026-08-05: **monthly work is guarded by whether it has run, never by
            # the date.** This job's guard was a shell step that ran BEFORE the heartbeat opened,
            # so a firing outside the first seven days left no trace at all — the identical shape
            # that hid `ingest-universe`'s absence for a month. Now every firing writes a row and
            # asks one question: has this month been backed up? Unbacked → back it up. Backed →
            # exit green, saying which run did it. A missed Saturday is picked up the following
            # week instead of skipping the month in silence.
            with conn.cursor() as cur:
                # a hand dispatch is never guarded — see db.scheduled_run()
                done = month_backed_up(cur) if scheduled_run() and not FORCE else None
            if done:
                hb.detail.update(stage="guard", backed_up=False, month_backed_up_at=str(done))
                print(f"backup: green — this month was backed up {done}; nothing to do")
                return 0
            hb.detail["stage"] = "dump"
            with conn.cursor() as cur:
                cur.execute("""select table_name from information_schema.tables
                               where table_schema='public' and table_type='BASE TABLE'
                               order by table_name""")
                tables = [r[0] for r in cur.fetchall() if r[0] not in SKIP]
            dump, total = {}, 0
            with conn.cursor() as cur:
                for t in tables:
                    cur.execute(f'select row_to_json(x) from "{t}" x')
                    rows = [r[0] for r in cur.fetchall()]
                    dump[t] = rows
                    total += len(rows)
                cur.execute("select count(*), max(d) from prices")
                n_bars, last_bar = cur.fetchone()
            dump["_meta"] = {"taken": stamp, "tables": len(tables), "rows": total,
                             "prices_excluded": {"rows": n_bars, "last_bar": str(last_bar)}}
            os.makedirs(OUT, exist_ok=True)
            path = f"{OUT}/yuna-{stamp}.json.gz"
            with gzip.open(path, "wt", encoding="utf-8") as f:
                json.dump(dump, f, default=str)
            size = os.path.getsize(path)
            hb.rows = total
            hb.detail.update(path=path, bytes=size, tables=len(tables),
                             prices_rows=n_bars, prices_excluded=True)
            print(f"backup: {path} — {total} rows across {len(tables)} tables, {size/1024:.0f} KB")
            print(f"  (prices excluded: {n_bars} bars through {last_bar})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
