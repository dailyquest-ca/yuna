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
import pytest


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


def _check(conn, session, verdict, *, mode="live", dry_run=False, why="planted by the test"):
    """A finished `check` row, keyed as `gauges.main` writes one: verdict, mode and session in the
    same update, `blocks_buys` true exactly when the verdict is red. Committed on its own, so it
    begins after the session row it checks — as the job does, which runs after `score`."""
    detail = {"gauges": [], "verdict": verdict, "mode": mode, "session": str(session),
              "blocks_buys": verdict == "red"}
    if verdict != "green":
        detail[verdict] = [why]
    with conn.cursor() as cur:
        cur.execute("""insert into runs (job, status, dry_run, finished_at, detail)
                       values ('check', %s, %s, now(), %s) returning id""",
                    (verdict, dry_run, json.dumps(detail)))
        rid = cur.fetchone()[0]
    conn.commit()
    return rid


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
    the system is about to do something.

    The fall is in engine NAV, the number §5.2's "engine DD" is measured on since migration 068
    (A28); this fixture moved `marked_equity`, the positions alone, until then."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))
        _score(cur, days)
        db.commit()
        # a peak, then a 35% fall
        cur.execute("""update engine_sessions set nav = 100000, marked_equity = 100000
                        where session_date = %s""", (days[-1],))
        cur.execute("""insert into engine_sessions
                         (session_date, gate_on, gate_green, universe_count, ranked_count,
                          marked_equity, nav, param_digest, mode)
                       values (%s, true, true, 20, 20, 65000, 65000, 'x', 'live')""",
                    (days[-1] + dt.timedelta(days=1),))
        db.commit()
        text = brief.render(brief.payload(cur))

    assert "-35.0%" in text
    assert "−10% pager reached" in text
    assert "milestones passed: -20%, -30%" in text
    assert "No mechanical intervention exists at any level" in text


def test_the_drawdown_section_carries_the_record_beside_the_number(db, migrated):
    """§5.2 (2026-09-02): the drawdown record rides with the milestones. Zak: "the most important
    piece is having something to tell me and remind me." At −35% the brief quotes the share of the
    cell of record's sessions that sat at least 30% below their high, both recoveries, and the
    sentence that says what the record does and does not promise. At −2% it quotes the −10% share
    and says today is one of the other sessions. Every number is the plan's, none is the store's —
    `test_brief_record.py` holds the plan and the code to the same figures. (The depth is engine
    NAV's since migration 068, A28 — the fixture moved `marked_equity` until then.)"""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))
        _score(cur, days)
        db.commit()
        cur.execute("""update engine_sessions set nav = 100000, marked_equity = 100000
                        where session_date = %s""", (days[-1],))
        cur.execute("""insert into engine_sessions
                         (session_date, gate_on, gate_green, universe_count, ranked_count,
                          marked_equity, nav, param_digest, mode)
                       values (%s, true, true, 20, 20, 65000, 65000, 'x', 'live')""",
                    (days[-1] + dt.timedelta(days=1),))
        db.commit()
        deep = brief.render(brief.payload(cur))
        cur.execute("""update engine_sessions set nav = 98000, marked_equity = 98000
                        where session_date = %s""", (days[-1] + dt.timedelta(days=1),))
        db.commit()
        shallow = brief.render(brief.payload(cur))

    assert "a book at least 30% below its high is 26.2% of the cell of record's 4,940 sessions" in deep
    assert "at least 10% below is 68.4%" in deep
    for both in (deep, shallow):
        assert "-60.3% on 2009-03-09, made a new high on 2013-09-10, four and a half years later" in both
        assert "-45.9% on 2025-11-21, made one on 2026-04-30, five months later" in both
        assert "the bet is the rotation, not the name" in both
    assert "sat at least 10% below its high in 68.4% of its 4,940 sessions; today is one of the other 31.6%" in shallow


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
    """§2.3: "Each tranche requires the gate (§3.4) ON that week."

    THAT week — the tranche's own. The fixture puts tranche three's planned date on the session,
    because the rule is about the gate in the tranche's week; until 2026-10-07 (A71) this asserted
    a 2026 tranche held by a 2024 session's gate."""
    with db.cursor() as cur:
        days = _world(cur, rising=False)
        _score(cur, days)
        cur.execute("update levered_tranches set planned_on = %s where seq = 3", (days[-1],))
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
    learnings, NAV vs the §1 destination)."

    The household here is the store's own: one CAD cash anchor and nothing held. Until 2026-10-07
    the letter printed the newest `nav_snapshots` row instead, which nothing scheduled writes (A50),
    so this fixture planted the figure there."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        # a shadow that disagreed on the gate — §6.4's whole product is naming these
        cur.execute("""insert into engine_sessions (session_date, gate_on, gate_green,
                         universe_count, ranked_count, param_digest, mode)
                       values (%s, false, false, 20, 20, 'x', 'shadow')""", (days[-1],))
        cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source)
                       values ('TFSA', %s, 250000, 0, 'test')""", (days[-1],))
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


def test_a_rescored_night_refreshes_the_brief_rather_than_serving_the_first_render(db, migrated):
    """`check` runs before `compose`, so a re-scored night legitimately produces a different
    verdict, sheet and banner — and the retry ingest fires the whole chain a second time BY DESIGN,
    which made the stale render the normal outcome rather than the edge case."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
    db.commit()
    # The first render carries a completed GREEN check of the session, as `gauges.main` writes one.
    # Until 2026-10-07 this render had no check at all and the test read that as "no hold" — but a
    # session no check has proved holds its buys (A9), so the contrast is now green against red.
    _check(db, days[-1], "green")
    env = {"DATABASE_URL": migrated, "DB_SSLMODE": "disable", "PATH": "/usr/bin:/bin"}
    subprocess.run([sys.executable, str(ROOT / "src" / "brief.py")], check=True,
                   capture_output=True, text=True, env=env)
    with db.cursor() as cur:
        cur.execute("select id, body from briefs where kind='nightly'")
        first_id, first_body = cur.fetchone()

        # the night is re-scored and this time `check` is red
        cur.execute("""insert into runs (job, status, finished_at, detail)
                       values ('check','red', now(), %s)""",
                    (json.dumps({"verdict": "red", "blocks_buys": True,
                                 "red": ["sheet: qty does not follow from §3.5"]}),))
    db.commit()
    subprocess.run([sys.executable, str(ROOT / "src" / "brief.py")], check=True,
                   capture_output=True, text=True, env=env)

    with db.cursor() as cur:
        cur.execute("select count(*) from briefs where kind='nightly'")
        assert cur.fetchone()[0] == 1, "one brief per session, still"
        cur.execute("select id, body from briefs where kind='nightly'")
        second_id, second_body = cur.fetchone()
    assert second_id == first_id, "the same row, refreshed"
    assert "buys held; exits stand" in second_body, "and it carries the NEW verdict"
    assert "buys held; exits stand" not in first_body


def test_notify_finds_the_brief_however_long_ago_it_was_written(db, migrated):
    """The weekend case, which was permanent: Friday's bar is the newest session until Tuesday's
    ingest, so a wall-clock freshness window reports the desk silent for three days over a brief
    that was composed correctly and is sitting right there."""
    import notify
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
    db.commit()
    subprocess.run([sys.executable, str(ROOT / "src" / "brief.py")], check=True,
                   capture_output=True, text=True,
                   env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable", "PATH": "/usr/bin:/bin"})
    with db.cursor() as cur:
        cur.execute("update briefs set at = now() - interval '3 days' where kind = 'nightly'")
        db.commit()
        have = notify.fresh_composed(cur, ["nightly"])
    assert "nightly" in have, "the session is the anchor, not the clock"


def test_notify_reports_silence_when_a_new_session_has_no_brief(db, migrated):
    """The check must still be able to FAIL — a guard that always passes is not a guard. A brief
    for yesterday's session does not cover tonight's."""
    import notify
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
    db.commit()
    subprocess.run([sys.executable, str(ROOT / "src" / "brief.py")], check=True,
                   capture_output=True, text=True,
                   env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable", "PATH": "/usr/bin:/bin"})
    with db.cursor() as cur:
        cur.execute("""insert into engine_sessions (session_date, gate_on, gate_green,
                         universe_count, ranked_count, param_digest, mode)
                       values (%s, true, true, 20, 20, 'x', 'live')""",
                    (days[-1] + dt.timedelta(days=1),))
        db.commit()
        have = notify.fresh_composed(cur, ["nightly"])
    assert have == {}, "a new session with no brief is silence, and must read as silence"


def test_one_v1_brief_per_session_is_a_constraint_and_not_a_convention(db, migrated):
    """Why `notify` can never deliver superseded words.

    `briefs.at` defaults to `now()`, which in Postgres is TRANSACTION time — so two briefs written
    in one transaction carry a byte-identical timestamp, and `order by at desc` is a tie broken by
    whatever the heap hands back. `fresh_composed` keeps the first row per kind, so under a tie the
    message Zak reads would be decided by a coin toss. The same missing tiebreak flipped a compose
    test, which is how this got looked at.

    The reason it cannot bite is structural rather than careful: migration 058 makes (kind,
    session_date) UNIQUE for engine briefs, so there is only ever one row to choose between and the
    correction REPLACES its predecessor instead of racing it. This pins that, because if the index
    were ever dropped the ordering would silently start deciding what gets delivered.
    """
    import psycopg
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        session = days[-1]
        cur.execute("""insert into briefs (kind, session_date, summary, body, detail)
                       values ('nightly', %s, 'first', 'STALE — the book before the fills',
                               '{"composed": true, "engine": "v1"}'::jsonb)""", (session,))
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute("""insert into briefs (kind, session_date, summary, body, detail)
                           values ('nightly', %s, 'second', 'FRESH — NUE.US sold',
                                   '{"composed": true, "engine": "v1"}'::jsonb)""", (session,))
    db.rollback()


def test_the_brief_tells_the_park_apart_from_a_holding_queued_to_sell(db, migrated):
    """Two unranked holdings, opposite meanings, and the brief must not print the same note on both.

    A `.US` common stock that left §3.2's universe IS queued to sell: §3.5 queues anything below
    rank 12 and "not ranked at all" is below it. The park is unranked because it was never
    eligible — it is where §3.4 puts the money while the gate is off, and §6.5 converts it at the
    seed. Printing "§3.5 treats as below 12" against 810 shares of the Phase-0 bridge reads as
    "this is queued to sell", which is the opposite of what it is being held for. It did.
    """
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",), excluded=("N15.US",))     # left the universe: sells
        from test_desk import _park
        _park(cur, days)                                               # the bridge: does not
        _score(cur, days)
        db.commit()
        lines = "\n".join(brief.book_lines(brief.payload(cur)))

    assert "SPMO.US" in lines and "N15.US" in lines
    park_note = "park — engine capital, never a slot and never sold for failing to rank"
    exit_note = "outside §3.2's universe, which §3.5 treats as below 12"
    spmo = [ln for ln in lines.splitlines() if "SPMO.US" in ln or park_note in ln]
    assert any(park_note in ln for ln in spmo), "the park is named as the park"
    assert exit_note in lines, "and the genuinely-departed holding still says it is queued"
    # the two notes appear once each — the park did not inherit the sell warning
    assert lines.count(exit_note) == 1
    assert lines.count(park_note) == 1


def test_the_brief_carries_the_underweight_slots_zak_has_to_rule_on(db, migrated):
    """§3.5's slot is a WEIGHT, and `engine.orders` keeps a held name rather than re-buying it — so
    a partial line occupies a whole slot and the capital it was meant to carry stays parked.

    This belongs in the BRIEF and not only on the sheet, because it is the one thing there is
    nothing to execute about: at the seed it decides how much of the account is actually deployed,
    and a line nobody sees is a decision nobody makes.
    """
    with db.cursor() as cur:
        days = _world(cur)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','preseed',20,40.0,'open')""")
        _score(cur, days)
        db.commit()
        p = brief.payload(cur)
        lines = "\n".join(brief.underweight_lines(p))

    assert "N00.US" in lines
    # v1.1 (2026-10-06) ruled what this section used to leave with Zak (§0.3): "A slot filled below
    # weight counts as filled and is reported; it is never topped up."
    assert "NOT ordered" in lines and "never topped up" in lines and "Zak's (§0.3)" not in lines
    assert "so that much capital stays parked" in lines
    assert "%" in lines, "the shortfall is stated as a fraction of the slot it should fill"


def test_no_underweight_section_when_every_slot_is_at_weight(db, migrated):
    """A section that always prints is a section nobody reads."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        db.commit()
        assert brief.underweight_lines(brief.payload(cur)) == []


def test_a_position_with_no_mark_is_not_priced_at_zero(db, migrated):
    """VXC.TO, as production had it: no bars in this store, so `last_close` is null — and the brief
    rendered `float(None or 0)` as "last 0.00   P/L +0.0%".

    A price the position does not have and a return it has not earned, in the one document Zak reads
    numbers off. A dash cannot be mistaken for a fact; a zero can, and it also happens to be the
    most flattering possible lie about a loss.
    """
    with db.cursor() as cur:
        days = _world(cur)
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values ('VXC.TO','VXC','etf','CAD','active')""")
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,currency,status)
                       values ('VXC.TO','NONREG','levered',140,85.45,'CAD','open')""")
        _score(cur, days)
        db.commit()
        lines = "\n".join(brief.book_lines(brief.payload(cur)))

    vxc = [ln for ln in lines.splitlines() if "VXC.TO" in ln][0]
    assert "0.00" not in vxc.split("@")[1], f"no fabricated price or P/L: {vxc}"
    assert "no mark" in lines and "NOT in the marked equity" in lines


def test_a_holding_outside_the_engines_account_is_not_said_to_be_queued(db, migrated):
    """§2.1 puts the engine in the TFSA "and nowhere else". A NONREG or RRSP position is unranked
    because the engine does not rank it — not because §3.5 is about to sell it. Saying otherwise
    tells Zak the engine is queuing 140 shares of the levered layer it has no authority over."""
    with db.cursor() as cur:
        days = _world(cur)
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values ('VXC.TO','VXC','etf','CAD','active')""")
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,currency,status)
                       values ('VXC.TO','NONREG','levered',140,85.45,'CAD','open')""")
        _score(cur, days)
        db.commit()
        lines = "\n".join(brief.book_lines(brief.payload(cur)))

    assert "§2.1 puts the engine in the TFSA and nowhere else" in lines
    assert "§3.5 treats as below 12" not in lines, "the engine does not queue what it cannot trade"


def test_the_underweight_ruling_is_named_even_before_the_nav_lands(db, migrated):
    """The shortfall's arithmetic needs the slot size and the slot size needs the NAV — but the FACT
    does not wait: a ranked holding at a fraction of a slot occupies that slot whatever the NAV turns
    out to be. Staying silent until `config.engine_nav` is set hides the ruling behind the very
    thing it is waiting on, which is how production looked on 2026-08-18."""
    with db.cursor() as cur:
        days = _world(cur)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','preseed',20,40.0,'open')""")
        _score(cur, days)
        db.commit()
        p = brief.payload(cur)
        p["nav"] = dict(p["nav"] or {}, engine_nav=None)     # the state the board was actually in
        lines = "\n".join(brief.underweight_lines(p))

    assert "pending an engine NAV" in lines and "N00.US" in lines
    # the rule is v1.1's now (2026-10-06), not a ruling waiting on Zak (§0.3)
    assert "config.engine_nav" in lines and "never topped up" in lines


def test_the_brief_names_momentum_money_the_engine_cannot_reach(db, migrated):
    """The expiry notice on the account filter, in the document Zak reads.

    Zak, 2026-08-18: *"one day some of the RRSP may be used for Momentum."* On that day `held_book`
    misses it and the sheet looks completely normal — the position is simply absent. The brief has
    to say so, because there is no other symptom.
    """
    with db.cursor() as cur:
        days = _world(cur)
        cur.execute("""insert into accounts (code,label,kind,currency)
                       values ('RRSP','rrsp','registered','CAD') on conflict do nothing""")
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','RRSP','momentum',50,40.0,'open')""")
        _score(cur, days)
        db.commit()
        lines = "\n".join(brief.sleeve_lines(brief.payload(cur)))

    assert "N00.US" in lines and "RRSP" in lines
    assert "does NOT see this and its purpose says it should" in lines
    assert "can never be sold while the filter is the account" in lines
    assert "Zak's, never inferred here (§0.3)" in lines


def test_the_brief_is_silent_when_purpose_and_wrapper_agree(db, migrated):
    """§2.1's arrangement says nothing. A section that always prints is a section nobody reads."""
    with db.cursor() as cur:
        days = _world(cur)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','momentum',20,40.0,'open')""")
        _score(cur, days)
        db.commit()
        assert brief.sleeve_lines(brief.payload(cur)) == []


# ---- 2026-10-07: what the brief may call an order, and what may release a buy ------------------
#
# The QC review of 2026-10-07 found the brief rendering things no job had decided: withdrawn
# tickets as orders (A10), a check of another session or mode as tonight's (A9), a check that never
# finished as no reason to hold (A20), a name being sold as a slot held below weight (A25), the
# RRSP reserve as engine capital (A69), USD figures with no currency (A55), cash as drawdown (A28),
# a seven-week-old snapshot as the household (A50), and none of §3.2's exclusion table (A43), §2.3's
# tranche week (A71) or §2.4's account cash (A72). Each test below pins the rule, not the render.

ENV = {"DB_SSLMODE": "disable", "PATH": "/usr/bin:/bin"}


def _compose(migrated, **extra):
    out = subprocess.run([sys.executable, str(ROOT / "src" / "brief.py")], capture_output=True,
                         text=True, env={**ENV, "DATABASE_URL": migrated, **extra})
    assert out.returncode == 0, out.stdout + out.stderr
    return out


def test_a_withdrawn_or_executed_ticket_is_not_an_order(db, migrated):
    """§4.3: "The nightly sheet is the only source of engine orders." Learning 57: "A withdrawn
    proposal is not an order." On 2026-08-17 a re-score's withdrawals and a sell Zak had cancelled
    as already executed printed as SELL and BUY lines under the sheet, counted in "6 order(s)" with
    three live (A10). Proposed and approved are orders; the rest print apart, as what they are."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))           # rank 16: a rank-exit sell, and five buys
        _score(cur, days)
        cur.execute("update tickets set state = 'cancelled' where ticker = 'N15.US'")
        cur.execute("update tickets set state = 'reconciled' where ticker = 'N00.US'")
        cur.execute("update tickets set state = 'approved' where ticker = 'N01.US'")
    db.commit()
    _check(db, days[-1], "green")
    _compose(migrated)
    with db.cursor() as cur:
        p = brief.payload(cur)
        cur.execute("select summary, body from briefs where kind = 'nightly'")
        summary, body = cur.fetchone()

    on_sheet = body.split("## Order sheet")[1].split("## Book")[0].split("## Not orders")[0]
    assert "N15.US" not in on_sheet, "a withdrawn sell is not an order"
    assert "N00.US" not in on_sheet, "nor is a ticket already executed"
    assert "BUY  N01.US" in on_sheet, "an approved ticket still is"
    assert {r["state"] for r in p["order_sheet"]} == {"proposed", "approved"}
    assert summary == "gate ON · 4 order(s)", "the count notify sends is of orders"
    apart = body.split("## Not orders — withdrawn or already done; do not execute")[1]
    assert "N15.US     sell 100 — withdrawn [cancelled]" in apart.split("## Book")[0]
    assert "N00.US     buy" in apart and "already done [reconciled]" in apart


@pytest.mark.parametrize("shape", ["crashed", "died before its heartbeat", "still running"])
def test_a_check_that_did_not_finish_holds_the_buys(db, migrated, shape, tmp_path):
    """§4.4: "Any red holds buys." §4.3: "Red pipeline: no new buy tickets." A check that raised
    (Heartbeat's red: `fatal` and a trace), died before its heartbeat (report_fail's row) or is
    still `running` never wrote `blocks_buys` — only a finished check does — so the brief printed a
    bare "check RED" over sized buys and compose closed green (A20). A check that has not finished
    has proved nothing, which holds the buys exactly as a red verdict does."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
    db.commit()
    with db.cursor() as cur:
        if shape == "crashed":
            cur.execute("""insert into runs (job, status, finished_at, detail)
                           values ('check', 'red', now(), %s)""",
                        (json.dumps({"fatal": "KeyError: 'N00.US'", "trace": "..."}),))
        elif shape == "still running":
            cur.execute("""insert into runs (job, status, detail)
                           values ('check', 'running', %s)""",
                        (json.dumps({"actions": {"run_id": "7", "attempt": "1"}}),))
    db.commit()
    if shape == "died before its heartbeat":             # the workflow's own autopsy step
        tail = tmp_path / "job.out"
        tail.write_text("ModuleNotFoundError: No module named 'numpy'\n")
        out = subprocess.run([sys.executable, str(ROOT / "src" / "report_fail.py"), "check",
                              str(tail)], capture_output=True, text=True,
                             env={**ENV, "DATABASE_URL": migrated, "GITHUB_RUN_ID": "4242",
                                  "GITHUB_RUN_ATTEMPT": "1"})
        assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        p = brief.payload(cur)
    line = brief.freshness_line(p)
    assert "**buys held; exits stand**" in line.splitlines()[0], line
    assert "BUY  N00.US" in brief.render(p), "the sheet still ships; the banner says which half"

    _compose(migrated)
    with db.cursor() as cur:
        cur.execute("select status, detail from runs where job = 'compose' order by id desc limit 1")
        status, detail = cur.fetchone()
    assert status == "amber", "compose does not close green over a check that proved nothing"
    assert any("buys held" in a for a in detail["amber"])


def test_a_shadow_or_dry_check_does_not_speak_for_the_live_sheet(db, migrated):
    """Tonight's live check is red. A later `engine_mode=shadow` pass and a later DRY_RUN pass both
    come back green, and the brief read whichever `check` row was newest — so either lifted the
    hold over the live buys (A9). Learning 67: a row that is not a fact must not decide."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
    db.commit()
    _check(db, days[-1], "red", why="sheet: qty does not follow from §3.5")
    _check(db, days[-1], "green", mode="shadow")
    _check(db, days[-1], "green", dry_run=True)
    with db.cursor() as cur:
        line = brief.freshness_line(brief.payload(cur))
    assert line.startswith("✗ check RED — **buys held; exits stand**"), line
    assert "sheet: qty does not follow from §3.5" in line


def test_a_check_of_another_session_does_not_prove_tonight(db, migrated):
    """Last night's green is not tonight's proof. A check job that dies before it can connect leaves
    no row at all, and the newest row was then the previous session's verdict, rendered over
    tonight's sheet (A9)."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days[:-1])                        # last night's session
    db.commit()
    _check(db, days[-2], "green")
    with db.cursor() as cur:
        _score(cur, days)                             # tonight's, and no check of it
    db.commit()
    with db.cursor() as cur:
        line = brief.freshness_line(brief.payload(cur))
    assert line.startswith(f"✗ no check for session {days[-1]} — **buys held; exits stand**"), line


def test_a_check_begun_before_the_rescore_does_not_prove_the_new_sheet(db, migrated):
    """The retry chain re-scores the session, then re-checks it. The first chain's green proved the
    sheet as it stood; once the re-score has rewritten it, that green proves nothing about what is
    there now, and a second check that never wrote a row must not be covered for by it."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
    db.commit()
    _check(db, days[-1], "green")
    with db.cursor() as cur:
        _score(cur, days)                             # `write_session` restamps created_at
    db.commit()
    with db.cursor() as cur:
        line = brief.freshness_line(brief.payload(cur))
    assert line.startswith(f"✗ no check for session {days[-1]} — **buys held"), line


def test_a_name_tonight_sells_is_not_counted_as_held_below_weight(db, migrated):
    """"Held below §3.5's equal weight" is about KEPT names: `engine.orders` keeps a top-12 holding
    rather than re-buying it, so a partial line occupies a slot. A name the sheet sells tonight
    keeps nothing. Counted, it asked Zak to rule on topping up the name the same page told him to
    sell — WDC.US at rank 14 on 2026-10-05 — and overstated the shortfall by 108% (A25)."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))          # rank 16: sold tonight
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','momentum',20,40.0,'open')""")   # rank 1: kept
        _score(cur, days)
        db.commit()
        lines = "\n".join(brief.underweight_lines(brief.payload(cur)))
    assert "N00.US" in lines, "the kept partial line is still reported"
    assert "N15.US" not in lines, "the name being sold is not"
    assert "1 slot(s) count as filled" in lines


def test_a_gated_off_book_has_no_slot_held_below_weight(db, migrated):
    """§3.4: "Gate OFF: the entire book sells at the next executable open." Nothing is kept, so no
    slot is filled at any weight (A25)."""
    with db.cursor() as cur:
        days = _world(cur, rising=False, held=("N00.US",))
        _score(cur, days)
        db.commit()
        p = brief.payload(cur)
    assert p["gate"]["gate_on"] is False
    assert brief.underweight_lines(p) == []


def test_the_rrsp_reserve_is_never_called_engine_capital(db, migrated):
    """§2.1: "RRSP | Reserve | SPMO". §2.2: "SPMO in the RRSP". §8: "Park — SPY.US, where engine
    capital sits while gated off." The note checked the instrument before the account, so every
    brief since the TFSA bridge was sold has told Zak the RRSP's SPMO is engine capital (A69)."""
    with db.cursor() as cur:
        days = _world(cur)
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values ('SPMO.US','SPMO','etf','USD','active')""")
        for d in days[-5:]:
            cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                           values ('SPMO.US',%s,153,153,153,153,153,3000000)""", (d,))
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('SPMO.US','RRSP','reserve',107.1729,140.0,'open')""")
        _score(cur, days)
        db.commit()
        lines = "\n".join(brief.book_lines(brief.payload(cur)))
    assert "park — engine capital" not in lines
    assert "RRSP — reserve per §2.1's table, not engine capital" in lines


def test_engine_figures_say_they_are_usd(db, migrated):
    """`desk.derived_engine_nav` is USD — positions at their USD closes plus TFSA cash at USDCAD —
    and §3.5 sizes USD orders off whatever engine NAV is, override included. The brief printed it
    with no unit beside a Saturday sentence saying NAV is CAD "throughout this system" (A55)."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        cur.execute("""update engine_sessions set detail = detail || '{"nav_source":
                         {"source": "config"}}'::jsonb where session_date = %s""", (days[-1],))
        db.commit()
        p = brief.payload(cur)
        text = brief.render(p)
        letter = "\n".join(brief.saturday_lines(cur, p))
    assert "engine NAV 200,000.00 USD (config.engine_nav — Zak's override, sized as USD)" in text
    assert "engine-NAV peak of 200,000.00 USD" in text
    assert "throughout this system" not in letter


def test_cash_between_a_sell_and_its_buy_is_not_a_drawdown(db, migrated):
    """§5.2: "Pager at −10% engine DD" — engine NAV, positions plus TFSA cash, the number §3.5 sizes
    against. Measured on the positions alone, an exit whose buy is held read as a 19% fall and a
    gate-off whose proceeds sat in cash as −100% with every milestone passed (A28)."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        cur.execute("""update engine_sessions set nav = 100000, marked_equity = 99000
                        where session_date = %s""", (days[-1],))
        # next session: a 19,000 exit sold, its buy held by a red check — the money is cash
        cur.execute("""insert into engine_sessions
                         (session_date, gate_on, gate_green, universe_count, ranked_count,
                          marked_equity, nav, param_digest, mode)
                       values (%s, true, true, 20, 20, 80000, 99500, 'x', 'live')""",
                    (days[-1] + dt.timedelta(days=1),))
        db.commit()
        held = brief.render(brief.payload(cur))
        # and a gate-off night: every position sold, nothing bought, the proceeds in cash
        cur.execute("""update engine_sessions set marked_equity = 0, nav = 98000, gate_on = false
                        where session_date = %s""", (days[-1] + dt.timedelta(days=1),))
        db.commit()
        gated = brief.render(brief.payload(cur))
    assert "drawdown -0.5% from an engine-NAV peak of 100,000.00 USD" in held
    assert "pager" not in held
    assert "drawdown -2.0%" in gated and "milestones passed" not in gated


def test_the_letter_measures_the_household_from_the_store_not_a_snapshot(db, migrated):
    """§4.1: "NAV vs the §1 destination." The letter printed the newest `nav_snapshots` row, whose
    only writer is the retired `arming.py`: one provisional 2026-08-15 snapshot of the
    pre-liquidation book, 204,109 CAD, in seven letters running (A50). The household is every
    holding at the session's close, every account's cash, less the facility, in CAD."""
    with db.cursor() as cur:
        days = _world(cur, held=("N05.US",))          # 100 shares, USD, kept at rank 6
        _score(cur, days)
        cur.execute("""insert into nav_snapshots (d, nav_cad, provisional)
                       values ('2026-08-15', 204108.63, true)""")
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values ('USDCAD.FOREX','USDCAD','fx','CAD','active')""")
        cur.execute("""insert into prices (ticker,d,close) values ('USDCAD.FOREX',%s,1.40)""",
                    (days[-1],))
        cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source)
                       values ('TFSA', %s, 1000, 500, 'test')""", (days[-3],))
        cur.execute("select close from prices where ticker = 'N05.US' and d = %s", (days[-1],))
        px = cur.fetchone()[0]
        db.commit()
        text = "\n".join(brief.saturday_lines(cur, brief.payload(cur)))
    house = 100 * px * 1.40 + (1000 + 500 * 1.40)
    assert f"NAV vs the §1 destination: {house:,.0f} of 5,000,000 CAD" in text, text
    assert "204,109" not in text, "a seven-week-old snapshot is not the household"


def test_a_levered_draw_lands_in_the_nonreg_and_leaves_the_household_whole(db, migrated):
    """§2.3: "Every draw purchases VXC.TO in the NONREG the same day — one draw, one purchase." The
    ledger records the purchase and not the draw. Production, 2026-09-22: 139 VXC.TO for
    C$11,995.70 out of a NONREG anchored at C$37.01, while the LOC's newer reading took the C$12,000
    draw onto the debt side. Carried by trades alone the NONREG read −C$11,958.69 and the household
    lost the draw twice (A50, A72)."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        anchor = days[-30]
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values ('VXC.TO','VXC','etf','CAD','active')""")
        for d in days[-5:]:
            cur.execute("insert into prices (ticker,d,close) values ('VXC.TO',%s,86.83)", (d,))
        cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source) values
                         ('TFSA', %s, 100000, 0, 'test'), ('NONREG', %s, 37.01, 0, 'test')""",
                    (anchor, anchor))
        cur.execute("""insert into balances (account, as_of, drawn, credit_limit, source) values
                         ('LOC', %s, 12000, 75000, 'test'), ('LOC', %s, 24000, 58600, 'test')""",
                    (anchor, days[-3]))
        cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                                 trade_date, confirmed)
                       values ('VXC.TO','NONREG','buy',139,86.30,'CAD',%s,true)""", (days[-10],))
        db.commit()
        text = "\n".join(brief.saturday_lines(cur, brief.payload(cur)))
    house = 100000 + 139 * 86.83 + 41.31 - 24000      # the C$41.31 the NONREG really holds
    assert f"NAV vs the §1 destination: {house:,.0f} of 5,000,000 CAD" in text, text


def test_the_brief_shows_each_accounts_cash_and_the_age_of_its_anchor(db, migrated):
    """§2.4: "Cash that is not awaiting a same-week engine order sits in the account's designated
    holding." No brief ever showed account cash: the C$584.87 the RRSP was anchored with on
    2026-08-17 sat seven weeks unseen, and so did every anchor's age (A72). Information only — no
    ticket is proposed for it."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        anchor = days[-30]
        cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source) values
                         ('RRSP', %s, 584.87, 4.69, 'test'), ('TFSA', %s, 47.33, 1458.90, 'test')""",
                    (anchor, anchor))
    db.commit()
    _check(db, days[-1], "green")
    _compose(migrated)
    with db.cursor() as cur:
        cur.execute("select body from briefs where kind = 'nightly'")
        body = cur.fetchone()[0]
        cur.execute("select count(*) from tickets where account <> 'TFSA'")
        assert cur.fetchone()[0] == 0, "information, never a ticket"
    assert "## Cash (§2.4" in body
    rrsp = [ln for ln in body.split("## Cash (§2.4")[1].splitlines() if ln.startswith("  RRSP")][0]
    assert "584.87 CAD" in rrsp and "4.69 USD" in rrsp
    assert f"anchor {anchor}, 29 days before this session" in rrsp


def test_the_saturday_letter_surfaces_the_exclusion_table(db, migrated):
    """§3.2: "The live table is surfaced in the payload and the Saturday letter." It was in the
    payload and in no letter: SGI.US, a live common stock, was excluded to "keep TPX" — a line whose
    last bar is 2025-02-14 — and seven letters went by without the row (A43). Every row prints, with
    the excluded line's own last bar beside its reason: §3.2 keeps "the line still printing"."""
    with db.cursor() as cur:
        days = _world(cur, excluded=("N19.US",))
        _score(cur, days)
        db.commit()
        text = "\n".join(brief.saturday_lines(cur, brief.payload(cur)))
    assert "exclusions (§3.2 — the live table, 1 row(s)" in text
    assert f"N19.US       duplicate_listing  last bar {days[-1]} · planted by the test" in text


def test_a_drawn_tranche_does_not_print_its_planned_amount_as_drawn(db, migrated):
    """`levered_tranches.amount_cad` is the PLAN's figure; the ladder has no column for what was
    drawn. Printed as drawn, two C$12,000 draws read as C$25,000 one line below a facility drawn
    24,000.00 (A71)."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        cur.execute("""update levered_tranches set status = 'drawn', drawn_on = '2026-08-16'
                        where seq = 1""")
        db.commit()
        text = "\n".join(brief.tranche_lines(brief.payload(cur)))
    assert "tranche 1: $12,500 — drawn" not in text
    assert "tranche 1: drawn 2026-08-16 against a planned $12,500" in text


def test_tonights_gate_opens_a_tranche_only_in_its_own_week(db, migrated):
    """§2.3: "Each tranche requires the gate (§3.4) ON that week; a skipped tranche shifts one
    month." THAT week is the tranche's. The brief printed "gate ON this week" against every planned
    tranche whenever tonight's gate was ON — a month early, or after its week had passed with the
    gate OFF and §2.3 had already moved it on (A71)."""
    with db.cursor() as cur:
        days = _world(cur)                            # gate ON
        _score(cur, days)
        s = days[-1]
        for seq, planned in ((1, s + dt.timedelta(days=28)), (2, s - dt.timedelta(days=28)),
                             (3, s)):
            cur.execute("update levered_tranches set planned_on = %s where seq = %s",
                        (planned, seq))
        db.commit()
        lines = brief.tranche_lines(brief.payload(cur))
    one, two, three = (next(ln for ln in lines if ln.startswith(f"  tranche {k}:"))
                       for k in (1, 2, 3))
    assert "has not come" in one and "gate ON this week" not in one
    assert "has passed undrawn" in two and "skipped tranche shifts one month" in two
    assert "Zak's to record" in two
    assert "this is its planned week and the gate is ON" in three


def test_never_two_tranches_in_one_month(db, migrated):
    """§2.3: "never two tranches in one month." A tranche planned in the month another was drawn is
    held, whatever the gate says (A71)."""
    with db.cursor() as cur:
        days = _world(cur)                            # gate ON
        _score(cur, days)
        s = days[-1]
        cur.execute("""update levered_tranches set status = 'drawn', drawn_on = %s
                        where seq = 2""", (s,))
        cur.execute("update levered_tranches set planned_on = %s where seq = 3", (s,))
        db.commit()
        lines = brief.tranche_lines(brief.payload(cur))
    three = next(ln for ln in lines if ln.startswith("  tranche 3:"))
    assert f"held: §2.3 — never two tranches in one month; tranche 2 was drawn {s}" in three


def test_a_fill_below_its_slot_says_so_on_the_sheet():
    """§3.5 as v1.1 amended it: "A slot filled below weight counts as filled and is reported; it is
    never topped up." The desk writes the shortfall into the ticket's note; the page Zak executes
    from carries it beside the buy, and the retired top-up tag is gone with the clause."""
    p = {"order_sheet": [
        dict(action="buy", ticker="N04.US", qty=395, mark=126.7, rank=4, state="proposed",
             clause="fill", note="free slot | fill below §3.5 weight: 395 of 452 shares — "
                                 "deployable TFSA cash 50,000.00 USD over 1 buy(s) (v1.1)"),
        dict(action="buy", ticker="N05.US", qty=452, mark=110.0, rank=5, state="proposed",
             clause="fill", note="free slot")]}
    lines = brief.sheet_lines(p)
    short = next(l for l in lines if "N04.US" in l)
    full = next(l for l in lines if "N05.US" in l)
    assert "below §3.5 weight: 395 of 452 shares; never topped up" in short
    assert "below" not in full and "top-up" not in "\n".join(lines)


def test_a_held_name_with_no_bar_is_not_called_outside_the_universe(db, migrated):
    """R2 (Zak's ruling, 2026-10-07): a held name with no bar on the decision session keeps its
    slot and its quantity and holds the buys. Its rank is missing because it did not print, not
    because it ranked below 12 — and the book line used to tell Zak the engine treats it "as below
    12", the opposite of what the sheet above it did."""
    with db.cursor() as cur:
        days = _world(cur)
        cur.execute("""insert into universe (ticker,name,kind,exchange,currency,status)
                       values ('DARK.US','DARK','stock','US','USD','active')""")
        cur.executemany("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                           values ('DARK.US',%s,50,50,50,50,50,1000000)""",
                        [(d,) for d in days[:-3]])
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('DARK.US','TFSA','momentum',100,40.0,'open')""")
        s = _score(cur, days)
        db.commit()
        assert s["unbarred"] == ["DARK.US"]
        lines = brief.book_lines(brief.payload(cur))

    at = next(k for k, line in enumerate(lines) if line.startswith("  DARK.US"))
    notes = []
    for line in lines[at + 1:]:
        if not line.startswith("      "):              # the next holding's own line
            break
        notes.append(line)
    assert any("no bar on the decision session" in n for n in notes), lines
    assert not any("outside §3.2's universe" in n for n in notes), lines
