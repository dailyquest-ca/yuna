"""§4.1's `score` job under v1.1's §3.5 and Zak's ruling R1 of 2026-10-07, end to end — src/sheet.py
as CI invokes it, then the record it leaves and what §4.4's check makes of that record.

`test_desk_v11` pins the decisions; this pins that the job writes exactly what it decided, attests
the inputs the sheet gauge re-derives from, goes amber on a hold with words that name it, and
writes nothing at all when the gate cannot be evaluated on fresh data.
"""
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import gauges                                                             # noqa: E402
from test_desk import _park, _shadow_passed, _world                       # noqa: E402
from test_desk_v11 import _close, _ten_oh_five                            # noqa: E402


def _job(migrated, as_of, **env):
    """`score` exactly as CI invokes it."""
    return subprocess.run([sys.executable, str(ROOT / "src" / "sheet.py")],
                          capture_output=True, text=True,
                          env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                               "AS_OF": as_of.isoformat(), "PATH": "/usr/bin:/bin", **env})


def _last_score(cur):
    cur.execute("select status, detail from runs where job = 'score' order by id desc limit 1")
    return cur.fetchone()


def _written(cur, session):
    cur.execute("""select ticker, action from tickets
                    where session_date = %s and state not in ('cancelled', 'void')""", (session,))
    return set(cur.fetchall())


def _attested(cur, session):
    cur.execute("select detail from engine_sessions where session_date = %s and mode = 'live'",
                (session,))
    return cur.fetchone()[0]


def test_the_job_sizes_a_fill_to_deployable_cash_and_attests_it(db, migrated):
    """Item 1 end to end: the 10-05 shape through src/sheet.py, NAV from the environment. The fill
    is v1.1's size — re-derived by hand here — and its ticket says it is below weight; the session
    attests the inputs; the run stays green, because a fill below weight is still a fill; and the
    check reads the sheet green, then red the moment the ticket is put back to NAV ÷ 5 — the
    580-against-512 sheet of 2026-10-05."""
    with db.cursor() as cur:
        days, deployable = _ten_oh_five(cur)
        in_px = _close(cur, "N04.US", days[-1])
    db.commit()
    out = _job(migrated, days[-1], ENGINE_NAV="200000")
    assert out.returncode == 0, out.stdout + out.stderr
    slot_qty = int(200_000.0 / 5 // in_px)
    expect = min(slot_qty, int(deployable // in_px))

    with db.cursor() as cur:
        cur.execute("""select ticker, action, clause, qty, note from tickets
                        where session_date = %s order by action, ticker""", (days[-1],))
        rows = cur.fetchall()
        assert [r[:3] for r in rows] == [("N04.US", "buy", "fill"), ("N15.US", "sell", "rank_exit")]
        assert rows[0][3] == expect < slot_qty, f"v1.1 gives {expect}; NAV ÷ 5 alone {slot_qty}"
        assert f"{expect:,} of {slot_qty:,} shares" in rows[0][4], "the ticket carries the reason"
        assert "below §3.5 weight" in out.stdout, "and so does the sheet"
        assert _last_score(cur)[0] == "green", "a fill below weight is a fill, reported — no amber"
        sz = _attested(cur, days[-1])["sizing"]
        assert sz["buys"] == 1 and [x["ticker"] for x in sz["sold"]] == ["N15.US"]
        assert sz["deployable"] == pytest.approx(deployable)
        assert sz["alloc"] == pytest.approx(deployable)
        assert (sz["cash"]["usd"], sz["cash"]["cad"], sz["cash"]["usdcad"]) == \
            (1458.90, 47.33, 1.40)
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
        assert g["status"] == "green", g
        cur.execute("update tickets set qty = %s where ticker = 'N04.US' and session_date = %s",
                    (slot_qty, days[-1]))
        db.commit()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "red", "NAV ÷ 5 against cash that cannot fund it holds the buys"
    assert any(f.startswith("N04.US: qty") for f in g["failures"])


def test_the_job_writes_unsized_buys_when_the_store_cannot_state_the_cash(db, migrated):
    """Fail closed, end to end: NAV from the environment and no TFSA anchor. Every buy is written
    with no quantity and `score` goes amber naming the gap — a price-critical amber, which holds
    the buys (§4.3) — rather than sizing them off NAV ÷ 5 alone."""
    with db.cursor() as cur:
        days = _world(cur)
    db.commit()
    out = _job(migrated, days[-1], ENGINE_NAV="200000")
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        status, detail = _last_score(cur)
        assert status == "amber"
        assert any("deployable TFSA cash unknown" in a and "no balances anchor for TFSA" in a
                   for a in detail["amber"])
        cur.execute("""select count(*) from tickets
                        where session_date = %s and action = 'buy' and qty is null""", (days[-1],))
        assert cur.fetchone()[0] == 5


def test_the_attestation_matches_the_tickets_on_a_park_draw(db, migrated):
    """Item 7 on the park path: the sheet gauge compares the attested (ticker, action) pairs with
    the tickets, so the `fund` sell v1.1 sizes to the shortfall is attested and written alike —
    644 of 810 SPMO for a 100,000 shortfall at 155.5 — and the gauge re-derives it green."""
    with db.cursor() as cur:
        days = _world(cur, cash=100_000.0)
        _park(cur, days)
        _shadow_passed(cur, days)
    db.commit()
    out = _job(migrated, days[-1], ENGINE_NAV="200000")
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        cur.execute("select qty from tickets where clause = 'fund' and session_date = %s",
                    (days[-1],))
        assert cur.fetchone()[0] == 644, "the shortfall in whole shares, never the lot"
        att = _attested(cur, days[-1])
        assert _written(cur, days[-1]) == ({(t, "sell") for t in att["sells"]}
                                           | {(t, "buy") for t in att["buys"]})
        assert att["sizing"]["park"][0]["qty"] == 644 and att["sizing"]["shortfall"] == 100_000.0
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "green", g


def test_a_night_whose_buys_the_cash_cannot_reach_names_them_in_the_check(db, migrated):
    """Item 7 on the held-below path, and the reporting it owes. A buy whose share of cash buys no
    share is no ticket, so it is attested nowhere among the orders — and the check names it, since
    the brief prints the check's reasons and v1.1 says a shortfall "is reported"."""
    with db.cursor() as cur:
        days = _world(cur, cash=10.0)
    db.commit()
    out = _job(migrated, days[-1], ENGINE_NAV="200000")
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        att = _attested(cur, days[-1])
        assert att["orders"] == 0 and att["buys"] == [] and _written(cur, days[-1]) == set()
        assert [h["ticker"] for h in att["held_below"]] == ["N00.US", "N01.US", "N02.US",
                                                            "N03.US", "N04.US"]
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "amber" and "held below weight, no ticket" in g["why"]
    assert all(t in g["why"] for t in ("N00.US", "N04.US"))


def test_a_gate_that_cannot_be_evaluated_writes_nothing_and_says_why(db, migrated):
    """Item 5 end to end (R1). Last night's chain scored the session before, cleanly. Tonight the
    names print a new session and SPY does not. The job used to re-score last night's close, green,
    and hand the same sheet back as tonight's (QC A39). Now it writes nothing — last night's sheet
    stays the sheet in force, untouched — goes amber naming SPY's bar and the tape's, and the check
    carries those words to the brief beside a red verdict that holds the buys."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",), cash=200_000.0)
        cur.execute("delete from prices where ticker = 'SPY.US' and d = %s", (days[-1],))
    db.commit()
    first = _job(migrated, days[-2], ENGINE_NAV="200000")             # last night: fresh
    assert first.returncode == 0, first.stdout + first.stderr
    with db.cursor() as cur:
        assert _last_score(cur)[0] == "green"
        cur.execute("select id, session_date, created_at, detail from engine_sessions")
        sessions_before = cur.fetchall()
        cur.execute("select id, state, qty, note, updated_at from tickets order by id")
        tickets_before = cur.fetchall()
    assert tickets_before, "last night proposed a sheet"

    tonight = _job(migrated, days[-1], ENGINE_NAV="200000")
    assert tonight.returncode == 0, tonight.stdout + tonight.stderr
    with db.cursor() as cur:
        status, detail = _last_score(cur)
        assert status == "amber", "an unevaluated gate is score's amber, which holds the buys"
        assert "unevaluated on fresh data" in tonight.stdout
        said = " ".join(detail["amber"])
        assert f"newest bar is {days[-2]}" in said and f"printed {days[-1]}" in said
        assert "never sells the book" in said
        cur.execute("select id, session_date, created_at, detail from engine_sessions")
        assert cur.fetchall() == sessions_before, "no session re-written"
        cur.execute("select id, state, qty, note, updated_at from tickets order by id")
        assert cur.fetchall() == tickets_before, "last night's sheet stands, untouched"
    verdict, got = gauges.run(db)
    sheet_gauge = next(g for g in got if g["gauge"] == "sheet")
    assert sheet_gauge["status"] == "amber" and f"printed {days[-1]}" in sheet_gauge["why"]
    assert verdict == "red"
