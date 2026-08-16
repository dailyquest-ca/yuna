"""§4.1's `compose` and §4.2's payload, against a real database.

The brief is where Zak reads the sheet, so its failures are the ones that reach a human. Two kinds
matter and they are opposite: a brief that omits something the plan requires (§5.1 lists six
sections and every one of them is a decision input), and a brief that states something no job
computed. "Judgment happens in chat; arithmetic happens in the pipeline" — this file is the arith-
metic arriving, and a number that appears here without a writer behind it is the arithmetic
happening in the wrong place.
"""
import datetime as dt
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import brief                                                              # noqa: E402
import desk                                                               # noqa: E402
import engine                                                             # noqa: E402
import sheet                                                              # noqa: E402
from test_desk import _world                                              # noqa: E402


def _score(cur, days, nav=200_000.0):
    s = desk.sheet(cur, days[-1], nav)
    sheet.write_session(cur, s, "live", engine.digest())
    sheet.write_ranks(cur, s, "live")
    sheet.write_tickets(cur, s)
    return s


def test_the_payload_carries_every_item_ss4_2_names(db, migrated):
    """"gate state & latch, current book with ranks, the nightly order sheet, top-12 with scores,
    the exclusion table, NAV & DD status, levered facilities & tranche schedule, pipeline
    freshness, learnings." Nine items. A payload missing one is a session reading around it."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))
        _score(cur, days)
        db.commit()
        p = brief.payload(cur)

    for key in ("gate", "book", "order_sheet", "top12", "exclusions", "nav",
                "facilities", "tranches", "check_report", "pipeline", "reconciliation",
                "learnings"):
        assert key in p, f"§4.2 names {key} and the payload does not carry it"

    assert p["gate"]["gate_on"] is True
    assert len(p["top12"]) == 12
    assert all(t["score"] is not None for t in p["top12"]), "top-12 WITH SCORES"
    assert [b["ticker"] for b in p["book"]] == ["N15.US"]
    assert p["book"][0]["rank"] == 16
    assert len(p["tranches"]) == 3


def test_the_tranche_schedule_is_the_plans_own_ramp(db, migrated):
    """§2.3, verbatim: "$12.5K immediately · $12.5K ~Sep 15 · $12.6K ~Oct 15". The amounts are the
    plan's; the years come from a v1.0 promoted 2026-08-15 and targeting mid-September 2026; and
    the tildes are carried into `approximate` rather than dropped."""
    with db.cursor() as cur:
        cur.execute("""select seq, amount_cad, planned_on::text, approximate, status
                         from levered_tranches order by seq""")
        assert cur.fetchall() == [
            (1, 12500.0, "2026-08-15", False, "planned"),
            (2, 12500.0, "2026-09-15", True, "planned"),
            (3, 12600.0, "2026-10-15", True, "planned")]


def test_headroom_is_measured_to_the_cap_and_never_to_the_limit(db, migrated):
    """§2.3: "Hard cap: drawn balance ≤ 50% of the facility limit". Reporting headroom against the
    LIMIT would say $67,220 was available where the plan permits $29,620 — a number that is both
    plausible and 2.3x the truth."""
    with db.cursor() as cur:
        cur.execute("""insert into balances (account, as_of, drawn, credit_limit, source)
                       values ('LOC', current_date, 7980, 75200, 'zak')""")
        db.commit()
        cur.execute("""select cap, headroom_to_cap, utilization from v_levered_facility
                        where account = 'LOC'""")
        cap, headroom, util = cur.fetchone()
    assert cap == 37600.0
    assert headroom == 29620.0
    assert round(util, 6) == round(7980 / 75200, 6)


def test_the_brief_renders_every_section_ss5_1_requires(db, migrated):
    """"freshness · gate & latch · the order sheet · book with ranks & P/L · DD status vs
    milestones · tranche schedule status." """
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))
        _score(cur, days)
        db.commit()
        text = brief.render(brief.payload(cur))

    for section in ("check", "gate **ON**", "## Order sheet", "## Book",
                    "## NAV & drawdown", "## Levered layer", "## Top 12"):
        assert section in text, f"§5.1 requires {section!r}"
    assert "latch:" in text
    assert "Nothing in this brief has been ordered" in text
    assert "sells first, then buys" in text
    assert "no GTC orders exist anywhere in this system" in text


def test_the_drawdown_section_always_says_that_nothing_happens_at_a_milestone(db, migrated):
    """§5.2 is the plan's most load-bearing negative: "**No mechanical intervention exists at any
    level.** Any intervention is Zak's explicit ruling in chat. This is the design, chosen with the
    three numbers in view." A brief that printed a milestone without it invites the reading that
    the system is about to do something."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))
        _score(cur, days)
        db.commit()
        # a peak, then a 35% fall
        cur.execute("""update engine_sessions set marked_equity = 100000
                        where session_date = %s""", (days[-1],))
        cur.execute("""insert into engine_sessions
                         (session_date, gate_on, gate_green, universe_count, ranked_count,
                          marked_equity, param_digest, mode)
                       values (%s, true, true, 20, 20, 65000, 'x', 'live')""",
                    (days[-1] + dt.timedelta(days=1),))
        db.commit()
        text = brief.render(brief.payload(cur))

    assert "-35.0%" in text
    assert "−10% pager reached" in text
    assert "milestones passed: -20%, -30%" in text
    assert "No mechanical intervention exists at any level" in text


def test_a_holding_with_no_rank_is_flagged_rather_than_shown_blank(db, migrated):
    """§3.5 queues anything below rank 12, and "not ranked at all" is below it. A blank cell in the
    rank column reads as missing data; it is in fact a queued exit."""
    with db.cursor() as cur:
        days = _world(cur, held=("N00.US",), excluded=("N00.US",))
        _score(cur, days)
        db.commit()
        text = brief.render(brief.payload(cur))
    assert "outside §3.2's universe" in text
    assert "SELL N00.US" in text


def test_a_red_check_ships_the_sheet_with_its_buys_held(db, migrated):
    """§5.4: exits are protective-direction and never blocked. §4.4: any red holds buys. The brief
    must therefore still print the sells — silence is the one outcome with no reader (§4.7)."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))
        _score(cur, days)
        cur.execute("""insert into runs (job, status, finished_at, detail)
                       values ('check','red', now(), %s)""",
                    (json.dumps({"verdict": "red", "blocks_buys": True,
                                 "red": ["sheet: qty does not follow from §3.5"]}),))
        db.commit()
        text = brief.render(brief.payload(cur))

    assert "buys held; exits stand" in text
    assert "SELL N15.US" in text, "the protective half always ships"
    assert "BUY  N00.US" in text, "and the held buys are still shown, marked by their state"


def test_the_tranche_line_holds_when_the_gate_is_off(db, migrated):
    """§2.3: "Each tranche requires the gate (§3.4) ON that week." """
    with db.cursor() as cur:
        days = _world(cur, rising=False)
        _score(cur, days)
        db.commit()
        text = brief.render(brief.payload(cur))
    assert "gate **OFF**" in text
    assert "held: §2.3 requires the gate ON that week" in text


def test_the_job_writes_one_brief_per_session_and_no_second(db, migrated):
    """§4.2: `compose` refuses to publish a kind twice for one session date, so the retry chain
    costs a few minutes and buys a second chance rather than a duplicate."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
    db.commit()
    env = {"DATABASE_URL": migrated, "DB_SSLMODE": "disable", "PATH": "/usr/bin:/bin"}
    for _ in range(2):
        out = subprocess.run([sys.executable, str(ROOT / "src" / "brief.py")],
                             capture_output=True, text=True, env=env)
        assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        cur.execute("select count(*) from briefs where kind = 'nightly'")
        assert cur.fetchone()[0] == 1


def test_the_job_stores_nothing_when_no_session_has_been_scored(db, migrated):
    """A brief dated today about a session that was never scored is a record of a night that did
    not happen."""
    out = subprocess.run([sys.executable, str(ROOT / "src" / "brief.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        cur.execute("select count(*) from briefs")
        assert cur.fetchone()[0] == 0
        cur.execute("select status, detail from runs where job='compose' order by id desc limit 1")
        status, detail = cur.fetchone()
        assert status == "amber"
        assert any("never" in a or "not stored" in a for a in detail["amber"])


def test_dry_run_renders_and_writes_nothing(db, migrated):
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
    db.commit()
    out = subprocess.run([sys.executable, str(ROOT / "src" / "brief.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "DRY_RUN": "true", "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    assert "# Yuna ·" in out.stdout
    with db.cursor() as cur:
        cur.execute("select count(*) from briefs")
        assert cur.fetchone()[0] == 0


def test_the_saturday_letter_carries_ss4_1s_six_items(db, migrated):
    """§4.1: "Weekly: the Saturday letter (clinical: gate, rank stability, DD status, divergences,
    learnings, NAV vs the §1 destination)." """
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        # a shadow that disagreed on the gate — §6.4's whole product is naming these
        cur.execute("""insert into engine_sessions (session_date, gate_on, gate_green,
                         universe_count, ranked_count, param_digest, mode)
                       values (%s, false, false, 20, 20, 'x', 'shadow')""", (days[-1],))
        cur.execute("""insert into nav_snapshots (d, nav_cad, provisional)
                       values (current_date, 250000, false)""")
        db.commit()
        p = brief.payload(cur)
        text = "\n".join(brief.saturday_lines(cur, p))

    assert "gate ON" in text and "flip(s) on record" in text
    assert "rank stability" in text
    assert "drawdown" in text
    assert "gate True/False" in text, "the live/shadow divergence is named, not summarised away"
    assert "250,000 of 5,000,000 CAD (5.0%)" in text
    assert "§1 names the number and not the currency" in text


def test_the_saturday_slot_writes_its_own_kind(db, migrated):
    """A Saturday letter that overwrote the nightly, or was suppressed by it, would leave §4.1's
    weekly obligation silently unmet on the one day it exists for."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
    db.commit()
    env = {"DATABASE_URL": migrated, "DB_SSLMODE": "disable", "PATH": "/usr/bin:/bin"}
    for slot in ("nightly", "saturday"):
        out = subprocess.run([sys.executable, str(ROOT / "src" / "brief.py")],
                             capture_output=True, text=True, env={**env, "COMPOSE_SLOT": slot})
        assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        cur.execute("select kind from briefs order by kind")
        assert [r[0] for r in cur.fetchall()] == ["nightly", "saturday"]
