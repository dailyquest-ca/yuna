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


def test_a_rescored_night_refreshes_the_brief_rather_than_serving_the_first_render(db, migrated):
    """`check` runs before `compose`, so a re-scored night legitimately produces a different
    verdict, sheet and banner — and the retry ingest fires the whole chain a second time BY DESIGN,
    which made the stale render the normal outcome rather than the edge case."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
    db.commit()
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
    assert "NOT ordered" in lines and "Zak's (§0.3)" in lines
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
    assert "config.engine_nav" in lines and "Zak's (§0.3)" in lines


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
