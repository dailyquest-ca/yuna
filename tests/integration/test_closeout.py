"""§6.2's system close-out, against a real database.

This job runs once, on the day the old engine stops, and it touches four tables. The failure that
matters is not a crash — it is a close-out that looks complete and leaves one thing behind: an
armed row that re-arms, a ticket that is still proposable, a learning that keeps brewing against
an engine that no longer exists. So every clause gets its own test, and one test asserts the thing
§6.2 must NOT do.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import closeout                                                           # noqa: E402


def _world(cur):
    """The seven positions §6.1 names, plus the old engine's leftovers."""
    for tk in list(closeout.LIQUIDATE) + ["SPY.US"]:
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values (%s,%s,'stock','USD','active') on conflict do nothing""", (tk, tk))
    for tk, qty in closeout.LIQUIDATE.items():
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values (%s,'TFSA','compounders',%s,100,'open')""", (tk, qty))
    cur.execute("""insert into tickets (ticker, account, action, state, order_type, qty)
                   values ('SPY.US','TFSA','buy','proposed','stop_limit',10),
                          ('SPY.US','TFSA','buy','approved','stop_limit',10)""")
    cur.execute("""insert into armed (ticker, kind, reason, trigger_price, stop)
                   values ('SPY.US','entry','trigger',100,90)""")
    cur.execute("""insert into learnings (key, status, lane, hypothesis, falsifier)
                   values ('brewing-one','learning','mechanics','h','f'),
                          ('brewing-two','proposal','strategy','h','f')""")


def test_a_sell_row_is_written_for_every_open_position(db, migrated):
    """§6.2 clause one. Every OPEN position, not §6.1's seven names — the book is what the system
    will still be reasoning from tomorrow."""
    with db.cursor() as cur:
        _world(cur)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('SPY.US','RRSP','compounders',5,400,'open')""")
        db.commit()
        positions = closeout.open_positions(cur)
        ids = closeout.sell_rows(cur, positions)
        db.commit()

        assert len(ids) == 8, "seven from §6.1 plus the one the plan did not anticipate"
        cur.execute("""select distinct action, state, clause, order_type from tickets
                        where id = any(%s)""", (ids,))
        assert cur.fetchall() == [("sell", "proposed", "phase0", "market")]
        cur.execute("select qty from tickets where ticker = 'NVDA.US' and clause = 'phase0'")
        assert cur.fetchone()[0] == 40.0437, "the DRIP'd fraction is a real share count"


def test_the_plan_and_the_book_are_compared_and_never_merged(db, migrated):
    """§6.1's list was written on a date and the book has been maintained since. Neither is
    automatically the truth, and the difference is the one thing a close-out must not decide."""
    with db.cursor() as cur:
        _world(cur)
        cur.execute("update book set qty = 39 where ticker = 'ANET.US'")
        cur.execute("delete from book where ticker = 'ISRG.US'")
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('SPY.US','TFSA','momentum',7,400,'open')""")
        db.commit()
        agreed, findings = closeout.reconcile_against_the_plan(closeout.open_positions(cur))

    assert agreed is False
    joined = " | ".join(findings)
    assert "ANET.US: §6.1 lists 40, the book holds 39 (-1)" in joined
    assert "ISRG.US: §6.1 lists 26 shares and the book holds no open position" in joined
    assert "SPY.US: the book holds 7 and §6.1 does not list it" in joined


def test_a_clean_book_agrees_with_the_plan(db, migrated):
    with db.cursor() as cur:
        _world(cur)
        db.commit()
        agreed, findings = closeout.reconcile_against_the_plan(closeout.open_positions(cur))
    assert (agreed, findings) == (True, [])


def test_open_tickets_are_voided_but_the_close_out_rows_survive(db, migrated):
    """§6.2 clause two. The close-out's own sells are open by definition and must survive their
    own clause — voiding them would leave a book with nothing proposing its liquidation."""
    with db.cursor() as cur:
        _world(cur)
        db.commit()
        ids = closeout.sell_rows(cur, closeout.open_positions(cur))
        voided = closeout.void_open_tickets(cur, ids)
        db.commit()

        assert len(voided) == 2
        cur.execute("select count(*) from tickets where state = 'proposed'")
        assert cur.fetchone()[0] == len(ids)
        cur.execute("""select count(*) from tickets where state = 'cancelled'
                        and note like '%voided by §6.2 close-out%'""")
        assert cur.fetchone()[0] == 2, "voided by state, never deleted"


def test_every_armed_row_is_retired(db, migrated):
    """§6.2 clause three. §3.3 has no arming stage; a row left armed is a trigger with no engine
    behind it."""
    with db.cursor() as cur:
        _world(cur)
        db.commit()
        assert closeout.retire_armed(cur) == 1
        db.commit()
        cur.execute("select count(*) from armed")
        assert cur.fetchone()[0] == 0


def test_brewing_learnings_close_into_the_ledgers_own_vocabulary(db, migrated):
    """§6.2 clause four. §5.3's ladder ends in "promotion or expiry", so "retired with engine" is
    the REASON and `expired` is the status — inventing a sixth state would extend a documented
    vocabulary without a ruling. And the closure is APPENDED: editing the row that raised the
    learning would erase the observation behind it, which §5.3 makes step one of the loop."""
    with db.cursor() as cur:
        _world(cur)
        db.commit()
        closed = closeout.close_learnings(cur)
        db.commit()

        assert closed == ["brewing-one", "brewing-two"]
        cur.execute("""select status, detail->>'verdict' from v_learnings_current
                        order by key""")
        assert cur.fetchall() == [("expired", closeout.RETIRED_WITH_ENGINE)] * 2
        cur.execute("select count(*) from learnings")
        assert cur.fetchone()[0] == 4, "two raised, two closures appended beside them"


def test_the_book_is_not_zeroed_ahead_of_zak(db, migrated):
    """The clause that does not mean what it first reads as. §0.2 makes Zak the executor: until he
    sells, the broker still holds those shares, and a book zeroed ahead of him would put
    `reconcile` in exactly the state it exists to detect."""
    with db.cursor() as cur:
        _world(cur)
    db.commit()
    out = subprocess.run([sys.executable, str(ROOT / "src" / "closeout.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "CLOSEOUT_APPLY": "true", "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        cur.execute("select count(*) from book where status = 'open'")
        assert cur.fetchone()[0] == 7, "the positions stand until the receipts land"
    assert "Nothing here has been ordered" in out.stdout
    assert "reaches zero through `reconcile`" in out.stdout


def test_it_writes_nothing_without_the_apply_flag(db, migrated):
    with db.cursor() as cur:
        _world(cur)
    db.commit()
    out = subprocess.run([sys.executable, str(ROOT / "src" / "closeout.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    assert "set CLOSEOUT_APPLY=true to write" in out.stdout
    with db.cursor() as cur:
        cur.execute("select count(*) from tickets where clause = 'phase0'")
        assert cur.fetchone()[0] == 0
        cur.execute("select count(*) from armed")
        assert cur.fetchone()[0] == 1


def test_running_it_twice_does_not_propose_a_second_liquidation(db, migrated):
    """It runs once. A second pass over an already-sold book would propose sells for positions
    that are gone, and §4.4's sheet gauge would read each one as a completeness failure."""
    with db.cursor() as cur:
        _world(cur)
    db.commit()
    env = {"DATABASE_URL": migrated, "DB_SSLMODE": "disable", "CLOSEOUT_APPLY": "true",
           "PATH": "/usr/bin:/bin"}
    first = subprocess.run([sys.executable, str(ROOT / "src" / "closeout.py")],
                           capture_output=True, text=True, env=env)
    second = subprocess.run([sys.executable, str(ROOT / "src" / "closeout.py")],
                            capture_output=True, text=True, env=env)
    assert first.returncode == second.returncode == 0
    assert "already run" in second.stdout
    with db.cursor() as cur:
        cur.execute("select count(*) from tickets where clause = 'phase0'")
        assert cur.fetchone()[0] == 7


def test_the_sheet_gauge_accepts_the_close_out_clause(db, migrated):
    """§4.4's sheet gauge rejects any clause §3.5 does not name, and `phase0` is on its list for
    exactly this job. A close-out that tripped the gauge would hold the buys on the morning the
    engine seeds."""
    import gauges
    with db.cursor() as cur:
        _world(cur)
        db.commit()
        ids = closeout.sell_rows(cur, closeout.open_positions(cur))
        cur.execute("update tickets set session_date = current_date where id = any(%s)", (ids,))
        cur.execute("""insert into engine_sessions (session_date, gate_on, gate_green,
                         universe_count, ranked_count, nav, param_digest, mode)
                       values (current_date, true, true, 10, 10, 200000, 'x', 'live')""")
        db.commit()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "green", g
