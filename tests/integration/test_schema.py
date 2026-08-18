"""The harness must clear everything the jobs write, or tests leak into each other.

Twice now a table was added and not added to the clean-slate list: a config override governed every
later test *and every later run*, and a stale corporate action made an insert collide. This test
pins the list against the schema rather than against anyone's memory of it.
"""
import re
import pathlib

CONFTEST = pathlib.Path(__file__).resolve().parent / "conftest.py"


def test_every_job_written_table_is_cleared_between_tests(db):
    with db.cursor() as cur:
        # the tables carrying the "jobs only" guard are by definition the ones a job writes
        cur.execute("""select distinct c.relname from pg_trigger t
                       join pg_class c on c.oid = t.tgrelid
                       join pg_proc p on p.oid = t.tgfoid
                       where p.proname = 'yuna_jobs_only' and not t.tgisinternal""")
        guarded = {r[0] for r in cur.fetchall()}

    body = CONFTEST.read_text()
    truncated = set(re.findall(r"[a-z_]+", body.split("truncate")[1].split('"""')[0]))
    missing = guarded - truncated - {"universe"}          # universe is deleted, not truncated
    assert not missing, f"tables a job writes but the harness never clears: {sorted(missing)}"

    # The guard cannot be the whole answer, and 2026-08-07 proved it. §4.3's session write list is
    # deliberately UNGUARDED, so `rulings` and `learnings` — both append ledgers, both read
    # latest-wins, both now read by jobs — were invisible to the check above and leaked across
    # pytest runs. A ledger a job reads must be cleared whoever writes it.
    session_ledgers = {"rulings", "learnings", "observations", "briefs", "tickets"}
    leaking = session_ledgers - truncated
    assert not leaking, (
        f"session-written ledgers the jobs now read, left standing between tests: {sorted(leaking)}"
        f" — config is exempt because it is cleared by a targeted delete just below")


def test_the_session_writable_tables_are_not_guarded(db):
    """§4.3's other half: the session write list must actually be writable by a session.

    **`transactions` rejoined the list on 2026-08-18** and this assertion inverted with it. The
    2026-08-04 plan took it off — a fill travelled as ticket state and a job derived the ledger row
    — and migration 033 enforced that with `guard_transactions`. v1.0's §4.3 carries no write list
    at all, and Zak's instruction that day is explicit: *"I will upload those to the chat so the
    chat should be able to write them... And know how."* A guard that refuses the write is a guard
    enforcing a retired law, so migration 059 drops it.

    `book` stays guarded, and that is the point rather than an oversight: the session writes the
    HISTORY, and `yuna_book_from_ledger` moves the position. One surface, one direction.
    """
    with db.cursor() as cur:
        cur.execute("""select distinct c.relname from pg_trigger t
                       join pg_class c on c.oid = t.tgrelid
                       join pg_proc p on p.oid = t.tgfoid
                       where p.proname = 'yuna_jobs_only' and not t.tgisinternal""")
        guarded = {r[0] for r in cur.fetchall()}
    assert not guarded & {"briefs", "tickets", "observations", "rulings", "learnings", "config",
                          "transactions"}
    assert "book" in guarded, (
        "the book is derived, never written by hand — a session writes `transactions` and "
        "`yuna_book_from_ledger` moves the position (migration 059)")


def test_latest_view_exposes_every_fundamentals_column(db):
    """A view's projection is frozen at creation, so adding a column to `fundamentals` does not add
    it to `v_fundamentals_latest` — and every reader in the system goes through the view. That gap
    is silent: the column exists, the writes succeed, and the readers see nothing.

    It happened for real. Migration 026 added cap_as_of, cap_close, effective_shares and raw_doc;
    the view still carried its original hand-written list, so the hurdle's frozen share count was
    unreadable by `score` the moment it was written. This test is the reason it cannot recur.
    """
    with db.cursor() as cur:
        cur.execute("""select column_name from information_schema.columns
                       where table_schema='public' and table_name=%s""", ("fundamentals",))
        table = {r[0] for r in cur.fetchall()}
        cur.execute("""select column_name from information_schema.columns
                       where table_schema='public' and table_name=%s""", ("v_fundamentals_latest",))
        view = {r[0] for r in cur.fetchall()}
    assert table, "fundamentals has no columns — migrations did not run"
    missing = table - view
    assert not missing, (
        f"v_fundamentals_latest cannot see {sorted(missing)} — recreate the view when the table gains "
        f"columns, or readers get silent nulls")


def test_the_extractor_can_write_every_column_it_builds(db):
    """`fundamentals.COLS` is the insert's column list. Every name in it must exist on the table.

    This is the cheapest test in the suite and it earned its place expensively: three Durability
    columns were wired into the extractor without a migration, and the failure did not surface until
    a full 2,762-name production sweep wrote zero rows and burned its quota. A schema mismatch is
    not a formula question — it is a seam, and seams are what this harness is for.
    """
    import fundamentals as fu

    with db.cursor() as cur:
        cur.execute("""select column_name from information_schema.columns
                       where table_schema='public' and table_name='fundamentals'""")
        have = {r[0] for r in cur.fetchall()}
    missing = [c for c in fu.COLS if c not in have]
    assert not missing, f"the sweep writes columns `fundamentals` does not have: {missing}"


def test_the_bench_writer_can_write_every_column_it_builds(db):
    """The same seam on the scoring side: `score` inserts a fixed column list into `bench`."""
    import re
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2] / "src" / "score.py").read_text()
    block = re.search(r"insert into bench\((.*?)\)", src, re.S)
    assert block, "could not find the bench insert — has score.py been restructured?"
    written = {c.strip() for c in block.group(1).replace("\n", " ").split(",") if c.strip()}

    with db.cursor() as cur:
        cur.execute("""select column_name from information_schema.columns
                       where table_schema='public' and table_name='bench'""")
        have = {r[0] for r in cur.fetchall()}
    missing = sorted(written - have)
    assert not missing, f"score writes columns `bench` does not have: {missing}"
