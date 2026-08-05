"""Phase 0 Step 2a — assigning sleeves, which is a write to the book and not a paragraph.

§6 Step 2a: "Every current **sleeve** holding is scored by **both** pipelines … It joins whichever
sleeve it qualifies for." Joining is `book.sleeve`, and nothing but a job can write it (§4.3's
guard_book). This job computed the assignment, published it in a brief, and left every row reading
`unassigned` — so Step 2a never completed, Step 2b could not start behind it, and cutover (Phase F)
had nothing to stand on. An unassigned holding is also unprotected: the stop ladder, the pyramid,
both relative exits and both sleeve ceilings all select on the sleeve.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import phase0                                                             # noqa: E402
import fixtures as world                                                  # noqa: E402


def benched(cur, ticker, *, ccn=78.0, c1=True, hurdle=150.0, close=100.0):
    cur.execute("""insert into bench (ticker, rank, cohort, ccn, c1_pass, hurdle_price,
                                      last_close, gap_to_hurdle, data_confidence)
                   values (%s, 1, 'large', %s, %s, %s, %s, %s, 'full')
                   on conflict (ticker) do update set ccn=excluded.ccn, c1_pass=excluded.c1_pass""",
                (ticker, ccn, c1, hurdle, close, (close - hurdle) / hurdle))


def sleeves(conn):
    with conn.cursor() as cur:
        cur.execute("select ticker, sleeve from book order by ticker")
        return dict(cur.fetchall())


def report(conn):
    with conn.cursor() as cur:
        cur.execute("select status, detail from runs where job='phase0' order by id desc limit 1")
        return cur.fetchone()


def test_a_holding_that_qualifies_joins_its_sleeve_on_the_book(db, fx):
    """The whole of Step 2a: the verdict lands on the row, not only in the prose."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US", holding=True)
        world.flat_then_base(cur, "AAA.US", level=100.0, last_close=100.0)
        world.position(cur, "AAA.US", sleeve="unassigned", cost=90.0)
        benched(cur, "AAA.US", ccn=78.0)
        world.balances(cur)
    db.commit()
    assert phase0.main() == 0
    assert sleeves(db)["AAA.US"] == "compounders"
    status, detail = report(db)
    assert any("AAA.US" in line for line in detail["sleeves_assigned"])


def test_a_momentum_qualifier_joins_momentum(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "BBB.US", holding=True)
        world.flat_then_base(cur, "BBB.US", level=100.0, last_close=100.0)
        world.position(cur, "BBB.US", sleeve="unassigned", cost=90.0)
        world.candidate(cur, "BBB.US", mcn=81.0, m2=True, m4=True)
        benched(cur, "BBB.US", ccn=40.0, c1=False)       # fails the compounder gate
        world.balances(cur)
    db.commit()
    assert phase0.main() == 0
    assert sleeves(db)["BBB.US"] == "momentum"


def test_dual_qualification_goes_to_compounders(db, fx):
    """§3.3: longer horizon wins."""
    with db.cursor() as cur:
        world.add_name(cur, "CCC.US", holding=True)
        world.flat_then_base(cur, "CCC.US", level=100.0, last_close=100.0)
        world.position(cur, "CCC.US", sleeve="unassigned", cost=90.0)
        world.candidate(cur, "CCC.US", mcn=95.0, m2=True, m4=True)
        benched(cur, "CCC.US", ccn=88.0)
        world.balances(cur)
    db.commit()
    assert phase0.main() == 0
    assert sleeves(db)["CCC.US"] == "compounders"


def test_a_name_that_qualifies_for_neither_stays_unassigned_and_is_named(db, fx):
    """"Qualifies for neither sleeve → exit" (§6). The row is on its way out, so it joins nothing —
    and the run says so rather than reading as a completed Step 2a."""
    with db.cursor() as cur:
        world.add_name(cur, "DDD.US", holding=True)
        world.flat_then_base(cur, "DDD.US", level=100.0, last_close=100.0)
        world.position(cur, "DDD.US", sleeve="unassigned", cost=90.0)
        benched(cur, "DDD.US", ccn=41.0, c1=False)
        world.balances(cur)
    db.commit()
    assert phase0.main() == 0
    assert sleeves(db)["DDD.US"] == "unassigned"
    status, detail = report(db)
    assert status == "amber" and "Step 2a incomplete" in str(detail["amber"])


def test_the_levered_layer_is_left_where_it_is(db, fx):
    """§2.5 / §6 Step 5: the levered layer sits outside the sleeves and is judged separately."""
    with db.cursor() as cur:
        world.add_name(cur, "EEE.US", holding=True)
        world.flat_then_base(cur, "EEE.US", level=100.0, last_close=100.0)
        world.position(cur, "EEE.US", sleeve="levered", account="NONREG", cost=90.0)
        benched(cur, "EEE.US", ccn=95.0)
        world.balances(cur)
    db.commit()
    assert phase0.main() == 0
    assert sleeves(db)["EEE.US"] == "levered"


def test_a_dry_run_assigns_nothing(db, fx, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US", holding=True)
        world.flat_then_base(cur, "AAA.US", level=100.0, last_close=100.0)
        world.position(cur, "AAA.US", sleeve="unassigned", cost=90.0)
        benched(cur, "AAA.US", ccn=78.0)
        world.balances(cur)
    db.commit()
    assert phase0.main() == 0
    assert sleeves(db)["AAA.US"] == "unassigned"
