"""restore — land a `backup` dump in a freshly migrated database. Dispatch-only tooling, and no
workflow runs it: this is what a person does if the Supabase project is lost together with
Supabase's own daily backups, the two fallbacks docs/incident-2026-08-03.md names.

    DATABASE_URL=<the NEW database> python src/restore.py backups/yuna-2026-10-03.json.gz
    DRY_RUN=true ...    # every step, inside one transaction, then rolled back

QC 2026-10-07 (A68) found no restore had ever been written or tried, and that the obvious one
fails: a plain insert is refused on 17 of the dump's 30 tables, and once forced in, every identity
sequence still stands at 1, so the first heartbeat collides on `runs_pkey` and every job dies
red at start-up. What it takes, all of it in ONE transaction — the restore lands whole or not at
all:

  1. **A target fit to receive it.** `runs` must be empty (every job writes a row on every firing,
     so a database any job has touched — production above all — is refused), and its migrations
     must be the dump's exactly. A column the dump does not carry would load as NULL, and a data
     migration newer than the dump would never touch the restored rows. A dump older than the
     code is restored at its own level, then migrated forward:
         git worktree add /tmp/at-dump <a commit whose migrations/ match the dump's _migrations>
         DATABASE_URL=... python /tmp/at-dump/src/migrate.py       # the dump's schema
         DATABASE_URL=... python src/restore.py <dump>             # this file, from today's code
         DATABASE_URL=... python src/migrate.py                    # every migration since
  2. **The migrations' seed rows out of the way.** They seed accounts, config, the book and more,
     and collide with the dump's own. Every table the dump carries is emptied and refilled;
     `_migrations` is the target's, and the guard above has made it the dump's.
  3. **Every row exactly as dumped.** Triggers are off for the load (`session_replication_role`
     = replica): the ledger trigger would recompute `book` from `transactions` and "repair" the
     very rows the dump recorded. Identity columns take the dumped ids (OVERRIDING SYSTEM VALUE).
  4. **Foreign keys checked after the load**, not during it, so the order tables load in cannot
     matter and a self-reference (a superseded transaction, a reversed ruling) needs no second
     pass. A reference that dangles stops the restore.
  5. **Every sequence past its table's highest id**, identity and serial alike.

Then, committed, the restored database records its own `restore` run — the first new row, and
the proof that the sequences moved. The dump carries no bars (`prices` is a re-pullable cache,
learning 9) and no research grid; re-pull the bars with the dispatch-only `backfill` afterwards.
Writes nothing to any database but the one DATABASE_URL names.
"""
import gzip
import json
import pathlib
import sys

from psycopg import sql

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from db import connect, dry, Heartbeat                                     # noqa: E402

# Rows per INSERT. Engineering, not a decision: the largest table runs to ~10^5 rows, and one
# statement per table would send it as a single parameter of tens of megabytes.
BATCH = 5000


def read(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _columns(cur, table):
    cur.execute("""select column_name from information_schema.columns
                    where table_schema = 'public' and table_name = %s
                    order by ordinal_position""", (table,))
    return [r[0] for r in cur.fetchall()]


def _refuse(why):
    raise SystemExit(f"restore refused: {why}")


def check_target(cur, content):
    """Raise unless this database can take this dump. Returns the tables to load."""
    tables = sorted(t for t in content if t != "_meta")
    cur.execute("select count(*) from runs")
    if cur.fetchone()[0]:
        _refuse("the target's `runs` is not empty — a restore goes into a freshly migrated "
                "database, never one any job has written to (production least of all)")
    cur.execute("select name from _migrations")
    here = {r[0] for r in cur.fetchall()}
    there = {r["name"] for r in content.get("_migrations") or []}
    if here != there:
        _refuse(f"the target's migrations are not the dump's — the target lacks "
                f"{sorted(there - here)} and adds {sorted(here - there)}. Migrate a fresh "
                f"database to the dump's level, restore, then migrate forward (see the docstring)")
    cur.execute("""select table_name from information_schema.tables
                    where table_schema = 'public' and table_type = 'BASE TABLE'""")
    present = {r[0] for r in cur.fetchall()}
    if missing := sorted(set(tables) - present):
        _refuse(f"the dump carries tables the target does not have: {missing}")
    for t in tables:
        rows = content[t]
        if not rows:
            continue
        dumped = set().union(*(r.keys() for r in rows))
        if dumped != set(_columns(cur, t)):
            _refuse(f"{t}: the dump's columns and the target's differ by "
                    f"{sorted(dumped ^ set(_columns(cur, t)))}")
    return [t for t in tables if t != "_migrations"]


def dangling(cur, tables):
    """Every foreign key out of a loaded table that points at nothing: [(constraint, count)]."""
    cur.execute("""select c.conname, cl.relname, pl.relname,
                          array(select a.attname from unnest(c.conkey) with ordinality k(n, i)
                                  join pg_attribute a on a.attrelid = c.conrelid
                                                     and a.attnum = k.n order by k.i),
                          array(select a.attname from unnest(c.confkey) with ordinality k(n, i)
                                  join pg_attribute a on a.attrelid = c.confrelid
                                                     and a.attnum = k.n order by k.i)
                     from pg_constraint c
                     join pg_class cl on cl.oid = c.conrelid
                     join pg_class pl on pl.oid = c.confrelid
                    where c.contype = 'f' and c.connamespace = 'public'::regnamespace""")
    out = []
    for name, child, parent, ccols, pcols in cur.fetchall():
        if child not in tables:
            continue
        cur.execute(sql.SQL("""select count(*) from {c} x where {set} and not exists
                                 (select 1 from {p} y where {match})""").format(
            c=sql.Identifier(child), p=sql.Identifier(parent),
            set=sql.SQL(" and ").join(sql.SQL("x.{} is not null").format(sql.Identifier(a))
                                      for a in ccols),
            match=sql.SQL(" and ").join(sql.SQL("y.{} = x.{}").format(sql.Identifier(b),
                                                                       sql.Identifier(a))
                                        for a, b in zip(ccols, pcols))))
        n = cur.fetchone()[0]
        if n:
            out.append((name, n))
    return out


def restore(conn, content):
    """Steps 1-5 of the module docstring, on `conn`'s open transaction. Returns {table: rows}.
    The caller commits — or, for a rehearsal, rolls back."""
    with conn.cursor() as cur:
        tables = check_target(cur, content)
        cur.execute("set local session_replication_role = replica")
        for t in tables:
            cur.execute(sql.SQL("delete from {}").format(sql.Identifier(t)))
        for t in tables:
            rows = content[t]
            for i in range(0, len(rows), BATCH):
                cur.execute(sql.SQL("insert into {t} overriding system value select * from "
                                    "json_populate_recordset(null::{t}, %s::json)").format(
                                        t=sql.Identifier(t)),
                            (json.dumps(rows[i:i + BATCH]),))
        if broken := dangling(cur, tables):
            _refuse(f"references that point at nothing after the load: {broken}")
        for t in tables:
            for col in _columns(cur, t):
                cur.execute("select pg_get_serial_sequence(%s, %s)", (f"public.{t}", col))
                seq = cur.fetchone()[0]
                if seq:
                    cur.execute(sql.SQL("select setval(%s::regclass, coalesce((select max({c}) "
                                        "from {t}), 0) + 1, false)").format(c=sql.Identifier(col),
                                                                           t=sql.Identifier(t)),
                                (seq,))
    return {t: len(content[t]) for t in tables}


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: DATABASE_URL=<the new database> python src/restore.py <dump>")
    path = sys.argv[1]
    content = read(path)
    meta = content.get("_meta") or {}
    with connect() as conn:
        loaded = restore(conn, content)
        total = sum(loaded.values())
        for t, n in loaded.items():
            print(f"  {t:<22} {n:>8} rows")
        if dry():
            conn.rollback()
            print(f"restore: dry run — {total} rows across {len(loaded)} tables would land from "
                  f"{path} (taken {meta.get('taken')}); nothing was written")
            return 0
        conn.commit()
        with Heartbeat(conn, "restore") as hb:
            hb.rows = total
            hb.detail.update(file=str(path), taken=meta.get("taken"), tables=loaded,
                             excluded=meta.get("excluded"))
    print(f"restore: {total} rows across {len(loaded)} tables from {path} (taken "
          f"{meta.get('taken')}); re-pull the bars with `backfill` before the first nightly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
