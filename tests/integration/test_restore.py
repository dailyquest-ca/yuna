"""A backup is only what a restore can make of it (QC 2026-10-07, A68).

No restore had ever been written or run. A plain one fails on 17 of the dump's 30 tables (their
ids are GENERATED ALWAYS), collides with the rows the migrations seed, and — once forced in — leaves
every identity sequence at 1, so the first heartbeat dies on `runs_pkey` and every job is red at
start-up. These tests take a dump the way the Saturday job takes it, land it in a database that
has only ever been migrated, and check that what comes back IS the dump: every row, every id, and
sequences that hand out the next id rather than the first.
"""
import gzip
import json
import os
import pathlib
import subprocess
import sys

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import backup                                                             # noqa: E402
import db as dbm                                                          # noqa: E402
import engine                                                             # noqa: E402
import fixtures as world                                                  # noqa: E402
import sheet                                                              # noqa: E402
from test_desk import _world                                              # noqa: E402


def _a_little_of_everything(db):
    """The shapes a restore can get wrong, through the real writers where there is one: the
    engine's session, ranks and tickets; a position with its ledger row behind it; a statement
    superseded by the broker's row (a self-reference); a ruling reversed and a learning superseded
    (two more); identity ids with a gap in them; and the migration-seeded tables the dump must
    replace rather than collide with."""
    with db.cursor() as cur:
        days = _world(cur)
        import desk
        s = desk.sheet(cur, days[-1], 200_000.0)
        sheet.write_session(cur, s, "live", engine.digest())
        sheet.write_ranks(cur, s, "live")
        sheet.write_tickets(cur, s, "live")
        world.position(cur, "N05.US", qty=40, cost=61.5)
        world.balances(cur, tfsa_cash=12_345.67, total=210_000.0)
        cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                                 trade_date, confirmed, grade, source)
                       values ('N05.US','TFSA','buy',10,62.0,'USD',%s,true,'stated','chat')
                       returning id""", (days[-1],))
        stated = cur.fetchone()[0]
        ticket = world.ticket(cur, "N05.US", state="executed", qty=10)
        cur.execute("""insert into transactions (ticket_id, ticker, account, side, qty, price,
                                                 currency, trade_date, confirmed, grade, source)
                       values (%s,'N05.US','TFSA','buy',10,61.9876,'USD',%s,true,'broker','export')
                       returning id""", (ticket, days[-1]))
        cur.execute("update transactions set superseded_by = %s where id = %s",
                    (cur.fetchone()[0], stated))
        cur.execute("""insert into briefs (kind, session_date, freshness, summary, body, detail)
                       values ('nightly', %s, 'data ✓', 'gate ON', 'the words Zak read',
                               '{"composed": true, "engine": "v1"}')""", (days[-1],))
        cur.execute("insert into observations (kind, detail) values ('note', '{\"n\": 1}')")
        cur.execute("insert into nav_snapshots (d, nav_cad) values (%s, 281234.56)", (days[-1],))
        cur.execute("insert into gate_state (week_end, state) values (%s, 'ON')", (days[-1],))
        cur.execute("""insert into shadow_attestations (session_date, compared, matched)
                       values (%s, 'rank', true)""", (days[-1],))
        cur.execute("""insert into universe_excluded (ticker, reason, detail)
                       values ('N19.US', 'duplicate_listing', 'planted')""")
        cur.execute("""insert into rulings (kind, ticker, verdict, memo)
                       values ('exclusion','N07.US','pass','first word') returning id""")
        cur.execute("""insert into rulings (kind, ticker, verdict, memo, reverses)
                       values ('exclusion','N07.US','fail','second thoughts', %s)""",
                    (cur.fetchone()[0],))
        cur.execute("insert into learnings (key, hypothesis) values ('a.first', 'x') returning id")
        cur.execute("""insert into learnings (key, hypothesis, supersedes, observation_ids)
                       values ('a.second', 'y', %s, %s)""", (cur.fetchone()[0], [1, 2]))
        cur.execute("""insert into config (key, value, set_by)
                       values ('restore_probe', '{"nested": [1, 2.5, "three"]}', 'test')""")
        cur.execute("""insert into corporate_actions (ticker, d, kind, detail)
                       values ('N03.US', %s, 'split', '{"split": "2/1"}')""", (days[-2],))
    db.commit()
    for job in ("probe-a", "probe-b", "probe-c"):
        with dbm.Heartbeat(db, job, dry_run=False) as hb:
            hb.detail["note"] = f"{job} — détail, with a non-ASCII byte"
    with db.cursor() as cur:
        cur.execute("delete from runs where job = 'probe-b'")    # an id gap: max(id) > count(*)
    db.commit()


@pytest.fixture
def fresh(migrated):
    """A second database that has only ever been migrated — what a restore lands in."""
    name = conninfo_to_dict(migrated)["dbname"] + "_restore"
    url = make_conninfo(migrated, dbname=name)
    with psycopg.connect(migrated, autocommit=True) as admin:
        admin.execute(f'drop database if exists "{name}" with (force)')
        admin.execute(f'create database "{name}"')
    out = subprocess.run([sys.executable, str(ROOT / "src" / "migrate.py")],
                         capture_output=True, text=True, env={**os.environ, "DATABASE_URL": url})
    assert out.returncode == 0, out.stdout + out.stderr
    yield url
    with psycopg.connect(migrated, autocommit=True) as admin:
        admin.execute(f'drop database if exists "{name}" with (force)')


@pytest.fixture
def taken(db, monkeypatch, tmp_path):
    """The Saturday job's own dump of the fixture world, written where a test can read it."""
    _a_little_of_everything(db)
    monkeypatch.setattr(backup, "OUT", str(tmp_path / "backups"))
    monkeypatch.setattr(backup, "FORCE", False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    assert backup.main() == 0
    path = backup.month_file()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return path, json.load(f)


def _restore(path, url, **env):
    return subprocess.run([sys.executable, str(ROOT / "src" / "restore.py"), str(path)],
                          capture_output=True, text=True,
                          env={**os.environ, "DATABASE_URL": url, **env})


def _canon(rows):
    return sorted(json.dumps(r, sort_keys=True) for r in rows)


def _next_ids(url):
    """{table: (max id, the id its sequence hands out next)} for every sequence-backed column."""
    out = {}
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("""select c.relname, a.attname, pg_get_serial_sequence(c.oid::regclass::text,
                                                                           a.attname)
                         from pg_class c join pg_attribute a on a.attrelid = c.oid
                        where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
                          and a.attnum > 0 and not a.attisdropped""")
        for table, col, seq in cur.fetchall():
            if not seq:
                continue
            cur.execute(f'select max("{col}") from "{table}"')
            top = cur.fetchone()[0]
            cur.execute(f"select last_value, is_called from {seq}")
            last, called = cur.fetchone()
            out[table] = (top, last + 1 if called else last)
    return out


def test_a_dump_lands_whole_in_a_freshly_migrated_database(taken, fresh):
    path, dumped = taken
    out = _restore(path, fresh)
    assert out.returncode == 0, out.stdout + out.stderr

    with psycopg.connect(fresh) as conn:
        landed, _ = backup.dump(conn, "after the restore")
    assert dumped["_meta"]["tables"] == landed["_meta"]["tables"]
    for table, rows in dumped.items():
        if table == "_meta":
            continue
        got = landed[table]
        if table == "_migrations":                      # the target's own, guarded equal by name
            assert sorted(r["name"] for r in got) == sorted(r["name"] for r in rows)
            continue
        if table == "runs":                             # plus the restore's own run, below
            got = [r for r in got if r["job"] != "restore"]
        assert _canon(got) == _canon(rows), f"{table} did not come back as it was dumped"

    for table in ("runs", "tickets", "transactions", "book", "engine_ranks", "rulings",
                  "learnings", "briefs", "observations", "nav_snapshots", "gate_state",
                  "shadow_attestations", "universe_excluded"):
        assert dumped[table], f"the fixture world never reached {table}, so it proved nothing"
    for table, (top, nxt) in _next_ids(fresh).items():
        assert top is None or nxt > top, f"{table}'s next id {nxt} collides with its rows ({top})"
    with psycopg.connect(fresh) as conn, conn.cursor() as cur:
        cur.execute("select id, status from runs where job = 'restore'")
        (rid, status), = cur.fetchall()
    assert status == "green"
    assert rid == max(r["id"] for r in dumped["runs"]) + 1, \
        "the first heartbeat after a restore takes the next id, not runs_pkey's first"


def test_a_rehearsal_restores_everything_and_keeps_nothing(taken, fresh):
    path, _ = taken
    out = _restore(path, fresh, DRY_RUN="true")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "nothing was written" in out.stdout
    with psycopg.connect(fresh) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from runs")
        assert cur.fetchone()[0] == 0, "the target is still only migrated"


def test_a_database_any_job_has_written_to_is_refused_untouched(taken, migrated):
    """The guard that keeps this tool off production: every job writes a runs row on every
    firing, so a target with any is not a fresh database."""
    path, _ = taken
    with psycopg.connect(migrated) as conn, conn.cursor() as cur:
        cur.execute("select count(*), max(id) from runs")
        before = cur.fetchone()
    out = _restore(path, migrated)
    assert out.returncode != 0 and "`runs` is not empty" in out.stderr
    with psycopg.connect(migrated) as conn, conn.cursor() as cur:
        cur.execute("select count(*), max(id) from runs")
        assert cur.fetchone() == before


def test_a_dump_at_another_migration_level_is_refused(taken, fresh):
    """A column the dump does not carry would load as NULL, and a data migration newer than the
    dump would never touch its rows: restore at the dump's own level, then migrate forward."""
    path, dumped = taken
    dumped["_migrations"].append({"name": "999_from_the_future.sql", "applied_at": None})
    tampered = pathlib.Path(path).with_name("tampered.json.gz")
    backup.write(dumped, tampered)
    out = _restore(tampered, fresh)
    assert out.returncode != 0 and "999_from_the_future.sql" in out.stderr


def test_a_reference_that_points_at_nothing_stops_the_restore(taken, fresh):
    """Foreign keys are off while rows load (so the order cannot matter) and checked after — a
    transaction naming a ticket the dump does not hold must stop the restore, not land."""
    path, dumped = taken
    dumped["transactions"][0]["ticket_id"] = 10 ** 9
    tampered = pathlib.Path(path).with_name("tampered.json.gz")
    backup.write(dumped, tampered)
    out = _restore(tampered, fresh)
    assert out.returncode != 0 and "transactions_ticket_id_fkey" in out.stderr
    with psycopg.connect(fresh) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from transactions where source = 'export'")
        assert cur.fetchone()[0] == 0, "nothing of the refused dump landed"
