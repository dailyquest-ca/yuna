"""§5.5's freeze, against a real database.

    "Zak may halt buying at any time, in any words; that state is a freeze. A freeze halts all buys
     (entries, refills, displacement buys, levered tranches). Exits fire normally; proceeds park.
     Lifted only by Zak's word."

Until 2026-08-16 nothing in this repository implemented that clause. It was law with no code behind
it, which is the worst state a safety control can be in — it reads as present. These tests are the
clause, line by line, and the sharpest of them is the one that proves a freeze does NOT touch the
sells: §5.4 names the freeze first in its list of things that never block an exit.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import brief                                                              # noqa: E402
import db as ydb                                                          # noqa: E402
import desk                                                               # noqa: E402
import engine                                                             # noqa: E402
import sheet                                                              # noqa: E402
from test_desk import _world                                              # noqa: E402

WORDS = "stop buying, I want to think about the semis concentration"


def _freeze(cur, on, words=WORDS):
    cur.execute("""insert into config (key, value, set_by)
                   values ('freeze', %s, 'zak')""",
                (json.dumps({"on": on, "words": words}),))


def _score(cur, days, nav=200_000.0):
    frozen, words, _, _ = ydb.freeze_state(cur)
    s = sheet.apply_freeze(desk.sheet(cur, days[-1], nav), frozen, words)
    sheet.write_session(cur, s, "live", engine.digest())
    sheet.write_ranks(cur, s, "live")
    sheet.write_tickets(cur, s, "live")
    return s


def test_no_row_reads_as_not_frozen(db, migrated):
    """§3.4's gate reads OFF when it cannot be evaluated, because an unevaluable gate must SELL. A
    freeze only ever stops action, so an unknown freeze must read OFF — the safe default of a
    control that halts is off, and of a control that acts is on."""
    with db.cursor() as cur:
        cur.execute("delete from config where key = 'freeze'")
        db.commit()
        assert ydb.freeze_state(cur) == (False, None, None, None)


def test_zaks_words_are_carried_not_paraphrased(db, migrated):
    """"Lifted only by Zak's word" needs the original words legible, so they can be compared
    against whatever he says next."""
    with db.cursor() as cur:
        _freeze(cur, True)
        db.commit()
        frozen, words, at, by = ydb.freeze_state(cur)
    assert frozen is True and words == WORDS and by == "zak" and at is not None


def test_a_freeze_drops_every_buy_and_keeps_every_sell(db, migrated):
    """The clause, and §5.4's "not by freeze, not by amber, not by any throttle"."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))         # rank 16 — a queued rank exit
        _freeze(cur, True)
        db.commit()
        s = _score(cur, days)
        db.commit()

        assert s["frozen"] is True
        assert [o["ticker"] for o in s["orders"]] == ["N15.US"], "the exit, and nothing else"
        assert len(s["frozen_buys"]) == 5, "five buys halted and named"

        cur.execute("""select action, count(*) from tickets where session_date = %s
                        group by action""", (days[-1],))
        assert cur.fetchall() == [("sell", 1)], "no buy ticket is written at all"


def test_the_halted_buys_are_named_rather_than_silently_absent(db, migrated):
    """A freeze that produced a shorter sheet with no explanation would read as a quiet night."""
    with db.cursor() as cur:
        days = _world(cur)
        _freeze(cur, True)
        db.commit()
        s = _score(cur, days)
    assert sorted(s["frozen_buys"]) == ["N00.US", "N01.US", "N02.US", "N03.US", "N04.US"]
    assert s["freeze_words"] == WORDS


def test_lifting_restores_the_buys(db, migrated):
    """Append, never edit: the freeze row stays and the lift is a row beside it, so the ledger
    answers when buying was halted AND when it resumed."""
    with db.cursor() as cur:
        days = _world(cur)
        _freeze(cur, True)
        db.commit()
        assert len(_score(cur, days)["orders"]) == 0
        db.commit()

        _freeze(cur, False, "ok, go again")
        db.commit()
        s = _score(cur, days)
        db.commit()

        assert s.get("frozen") is not True
        assert len([o for o in s["orders"] if o["action"] == "buy"]) == 5
        cur.execute("select count(*) from config where key = 'freeze'")
        assert cur.fetchone()[0] == 2, "both words are on the record"


def test_a_frozen_run_is_green_not_amber(db, migrated):
    """A freeze is a state Zak CHOSE, not a fault the pipeline found. Colouring it amber would put
    his own instruction in the same column as a broken ingest."""
    with db.cursor() as cur:
        days = _world(cur)
        _freeze(cur, True)
    db.commit()
    out = subprocess.run([sys.executable, str(ROOT / "src" / "sheet.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "AS_OF": days[-1].isoformat(), "ENGINE_NAV": "200000",
                              "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        cur.execute("select status, detail from runs where job='score' order by id desc limit 1")
        status, detail = cur.fetchone()
    assert status == "green"
    assert detail["frozen"] is True and detail["freeze_words"] == WORDS


def test_the_brief_leads_with_the_freeze_and_quotes_it(db, migrated):
    """It governs everything below it, so it goes above the freshness line — and the words are
    repeated back verbatim rather than paraphrased."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))
        _freeze(cur, True)
        db.commit()
        _score(cur, days)
        db.commit()
        text = brief.render(brief.payload(cur), frozen=True, words=WORDS)

    assert text.index("FROZEN") < text.index("gate **"), "the freeze leads"
    assert WORDS in text
    assert "Exits fire normally and proceeds park" in text
    assert "SELL N15.US" in text, "the exit still ships"
    assert "BUY " not in text.split("## Book")[0], "and no buy is offered"


def test_a_freeze_holds_the_levered_tranches_too(db, migrated):
    """§5.5 names them explicitly: "entries, refills, displacement buys, levered tranches"."""
    with db.cursor() as cur:
        days = _world(cur)                            # gate ON — so only the freeze can hold them
        _score(cur, days)
        db.commit()
        p = brief.payload(cur)
    frozen_text = "\n".join(brief.tranche_lines(p, frozen=True))
    open_text = "\n".join(brief.tranche_lines(p, frozen=False))
    assert "FROZEN — §5.5 halts levered tranches" in frozen_text
    assert "gate ON this week" in open_text


def test_the_brief_warns_when_the_ramp_would_breach_the_cap(db, migrated):
    """§2.3's cap is HARD and its ramp is a plan of draws, so the two can disagree arithmetically
    without either being wrong on its own. At the limit Zak stated — 75,000, cap 37,500 — the three
    tranches total 37,600. Nothing else in the system compares them, and a 100 overshoot discovered
    at the third draw is discovered at the worst possible moment."""
    with db.cursor() as cur:
        cur.execute("""insert into balances (account, as_of, drawn, credit_limit, source)
                       values ('LOC', current_date, 0, 75000, 'zak')""")
        db.commit()
        text = "\n".join(brief.tranche_lines(brief.payload(cur)))

    assert "§2.3 BREACH AHEAD" in text
    assert "37,600.00 against 37,500.00" in text
    assert "over by 100.00" in text


def test_no_warning_when_the_ramp_fits(db, migrated):
    """At the plan's own stated limit of 75,200 the ramp lands exactly on the cap, so the check
    must be silent — a guard that always fires is one nobody reads."""
    with db.cursor() as cur:
        cur.execute("""insert into balances (account, as_of, drawn, credit_limit, source)
                       values ('LOC', current_date, 0, 75200, 'zak')""")
        db.commit()
        text = "\n".join(brief.tranche_lines(brief.payload(cur)))
    assert "BREACH AHEAD" not in text
    assert "cap 37,600.00" in text


def test_headroom_counts_only_the_open_facilities(db, migrated):
    """The first version of the breach check took whichever facility row iterated last — MARGIN,
    unopened, limit zero — and reported 0.00 of headroom against a live $37,500. §2.3: "the
    TFSA-secured LOC is the only live facility... HELOC and margin are not opened". A facility with
    no limit is not open, which is the plan's own definition and not a hardcoded account code."""
    with db.cursor() as cur:
        cur.execute("""insert into balances (account, as_of, drawn, credit_limit, source) values
                         ('LOC',    current_date, 0, 75000, 'zak'),
                         ('HELOC',  current_date, 0, 0,     'zak'),
                         ('MARGIN', current_date, 0, 0,     'zak')""")
        db.commit()
        text = "\n".join(brief.tranche_lines(brief.payload(cur)))

    assert "against 37,500.00 of headroom" in text, "the LOC's headroom, not MARGIN's zero"
    assert "over by 100.00" in text
