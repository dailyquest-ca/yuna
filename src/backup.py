"""monthly-backup — dump everything except daily bars, compressed, into the repo (plan §4.2).

Bars are a vendor-re-pullable cache; the decisions are not. The commit doubles as GitHub's
60-day schedule keep-alive, so the crons never fall asleep.
"""
import os, sys, gzip, json, datetime as dt
import psycopg
from db import connect, Heartbeat

SKIP = {"prices"}
OUT = "backups"


def main():
    stamp = dt.date.today().isoformat()
    with connect() as conn:
        with Heartbeat(conn, "monthly-backup") as hb:
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
