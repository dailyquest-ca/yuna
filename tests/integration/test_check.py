"""End-to-end tests for `check`, §4.2's third verb, over a real database.

Two properties matter more than any individual assertion, and both are here: `check` writes
nothing but its own report row, and a finding that says a published number cannot be rebuilt
blocks the dispatch rather than merely complaining.
"""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import check                                                              # noqa: E402
import fixtures as world                                                  # noqa: E402


@pytest.fixture(autouse=True)
def no_vendor(monkeypatch):
    """The quota reading is the job's only outside call; every test supplies it."""
    monkeypatch.setattr(check, "get",
                        lambda path, calls, **kw: {"apiRequests": 100, "dailyRateLimit": 100000})


def report(conn):
    with conn.cursor() as cur:
        cur.execute("select status, detail from runs where job='check' order by id desc limit 1")
        status, detail = cur.fetchone()
    return status, detail


def test_the_report_carries_the_api_quota_and_alarms_past_the_budget(db, monkeypatch):
    """§4.1: the brief alarms past ~70% of the daily budget. The reading moved here from the
    nightly job when §4.2 made `score` a pure function of the database."""
    monkeypatch.setattr(check, "get",
                        lambda path, calls, **kw: {"apiRequests": 85000, "dailyRateLimit": 100000})
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur)
        world.balances(cur)
    db.commit()
    assert check.main() == 0
    status, detail = report(db)
    assert detail["preflight"]["api_quota"]["fraction"] == pytest.approx(0.85)
    assert "quota at 85%" in str(detail["amber"])


def test_the_preflight_reports_what_a_session_needs_before_it_speaks(db):
    """§4.2's pre-flight: the gate, what is offerable, and how much of the book carries a share
    count anybody has confirmed (§4.5 step 5)."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur)
        world.position(cur, "AAA.US", confirmed=True)
        world.balances(cur)
    db.commit()
    assert check.main() == 0
    _, detail = report(db)
    flight = detail["preflight"]
    assert flight["gate"] == "ON"
    assert flight["positions"] == 1
    assert flight["confirmation_coverage"] is not None
    assert "ingest" in detail["freshness"] and "score" in detail["freshness"]


def test_check_writes_nothing_but_its_own_report_row(db):
    """The law that makes the answer worth having (§4.2): a checker that can edit what it checks
    is a participant, not a witness. Everything it could once touch is counted before and after."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur)
        world.position(cur, "AAA.US", confirmed=True)
        world.balances(cur)
    db.commit()

    watched = ["observations", "bench", "book", "armed", "queue", "candidates", "briefs",
               "tickets", "transactions", "nav_snapshots", "quarantine", "prices",
               "fundamentals", "universe", "gate_state", "group_strength"]

    def census():
        with db.cursor() as cur:
            out = {}
            for t in watched:
                cur.execute(f"select count(*) from {t}")
                out[t] = cur.fetchone()[0]
            return out

    before = census()
    assert check.main() == 0
    after = census()
    assert before == after, f"check wrote outside its report row: {before} -> {after}"


def test_a_number_that_cannot_be_rebuilt_blocks_the_dispatch(db):
    """§4.2: ambers print at the top of the brief, a red blocks it. A stored hurdle the solver
    will not reproduce is the case the rule was written for — every conclusion drawn from it is
    unsafe, so the desk does not open."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur)
        world.balances(cur)
        cur.execute("""insert into bench (ticker, rank, ccn, engine, cash_conv, durability,
                         engine_provenance, data_confidence, hurdle_price, last_close,
                         fcf_yield, engine_growth, fair_multiple, gap_to_hurdle)
                       values ('AAA.US', 1, 50, 50, 50, 50, 'growth-derived', 'flagged',
                               999.00, 100.0, 0.05, 0.05, 20.0, -0.8993)""")
    db.commit()
    assert check.main() == 0
    status, detail = report(db)
    assert status == "red"
    assert "hurdle_reproduces_floor" in detail["blocks_dispatch"]


def test_a_calibration_gauge_is_loud_but_never_a_gag(db):
    """A gauge past its alarm is a finding about the SCREEN, not about tonight's arithmetic. It
    must not silence the desk — a system that stops speaking whenever it doubts its own strategy
    would never speak again."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur)
        world.balances(cur)
    db.commit()
    assert check.main() == 0
    _, detail = report(db)
    gauges = [c["check"] for c in detail["checks"] if c["check"].endswith("_gauge")]
    assert gauges, "the calibration gauges should always be reported"
    assert not any(g in detail["blocks_dispatch"] for g in gauges)
