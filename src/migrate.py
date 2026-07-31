"""Apply migrations/*.sql in order, once each. Tracker: _migrations table."""
import os, sys, pathlib, psycopg

def db_url():
    url = os.environ["DATABASE_URL"]
    if "sslmode" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url

def main():
    mig_dir = pathlib.Path(__file__).resolve().parent.parent / "migrations"
    files = sorted(p for p in mig_dir.glob("*.sql"))
    with psycopg.connect(db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("create table if not exists _migrations(name text primary key, applied_at timestamptz not null default now())")
            conn.commit()
            cur.execute("select name from _migrations")
            done = {r[0] for r in cur.fetchall()}
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
