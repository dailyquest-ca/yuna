"""Apply migrations/*.sql in order, once each. Tracker: _migrations table.

DRY_RUN lists what would be applied and applies nothing (§4.2 — all jobs carry it).
"""
import os, sys, pathlib, psycopg
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from db import db_url, dry

def main():
    mig_dir = pathlib.Path(__file__).resolve().parent.parent / "migrations"
    files = sorted(p for p in mig_dir.glob("*.sql"))
    with psycopg.connect(db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("create table if not exists _migrations(name text primary key, applied_at timestamptz not null default now())")
            conn.commit()
            cur.execute("select name from _migrations")
            done = {r[0] for r in cur.fetchall()}
        pending = [p for p in files if p.name not in done]
        if dry():
            for p in pending:
                print(f"would apply {p.name}")
            print(f"migrate: dry run — {len(pending)} pending, nothing written")
            return
        for p in files:
            if p.name in done:
                print(f"skip   {p.name} (already applied)"); continue
            with conn.cursor() as cur:
                cur.execute(p.read_text())
                cur.execute("insert into _migrations(name) values (%s)", (p.name,))
            conn.commit()
            print(f"applied {p.name}")
    print("migrate: done")

if __name__ == "__main__":
    sys.exit(main())
