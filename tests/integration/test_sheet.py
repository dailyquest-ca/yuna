"""§4.1's `score` job, against a real database.

`desk.py`'s tests pin the DECISION. These pin the RECORD, and the record has its own failure modes
— every one of which is a way for a re-run to lie about what the engine decided:

  * `pipeline.yml`'s retry ingest fires the whole chain a second time, so a night can be scored
    twice. Two rows for one close makes "what did the engine decide on the 14th" ambiguous.
  * A decision that CHANGES between passes must withdraw the first pass's proposal, visibly. A
    delete would leave §6.4's shadow unable to tell "never proposed" from "proposed and dropped".
  * A ticket Zak has already acted on must survive a re-score. Resetting it to `proposed` would
    lose the one fact the loop turns on.
"""
import pathlib
import pytest
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import engine                                                             # noqa: E402
import sheet                                                              # noqa: E402
from test_desk import _world                                              # noqa: E402


def _run(cur, days, nav=200_000.0, mode="live", as_of=None):
    import desk
    s = desk.sheet(cur, as_of or days[-1], nav)
    sheet.write_session(cur, s, mode, engine.digest())
    ranks = sheet.write_ranks(cur, s, mode)
    proposed, withdrawn = sheet.write_tickets(cur, s, mode)
    return s, ranks, proposed, withdrawn


def test_a_score_writes_the_session_the_ranks_and_the_sheet(db, migrated):
    with db.cursor() as cur:
        days = _world(cur)
        s, ranks, proposed, _ = _run(cur, days)
        db.commit()

        cur.execute("""select gate_on, gate_green, universe_count, ranked_count, nav, param_digest
                         from engine_sessions where session_date = %s""", (days[-1],))
        gate_on, green, universe, ranked, nav, digest = cur.fetchone()
        assert gate_on is True and green is True
        assert universe == s["universe"] and ranked == s["ranked"]
        assert nav == 200_000.0
        assert digest == engine.digest(), "the constants a decision was made under are stamped"

        cur.execute("select count(*) from engine_ranks where session_date = %s", (days[-1],))
        assert cur.fetchone()[0] == ranks == s["ranked"]

        cur.execute("""select ticker, rank from engine_ranks
                        where session_date = %s order by rank limit 1""", (days[-1],))
        assert cur.fetchone() == ("N00.US", 1)

        cur.execute("select count(*) from tickets where session_date = %s", (days[-1],))
        assert cur.fetchone()[0] == proposed == len(s["orders"])


def test_every_ticket_is_proposed_and_names_its_clause(db, migrated):
    """§4.3 starts a ticket at `proposed`; §0.2 forbids this job from advancing one. §2.1 houses
    the engine in the TFSA, so every row says so rather than inheriting a default."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))         # rank 16: below §3.5's exit rank of 12
        _run(cur, days)
        db.commit()
        cur.execute("""select distinct state, account, sleeve, order_type
                         from tickets where session_date = %s""", (days[-1],))
        assert cur.fetchall() == [("proposed", "TFSA", "momentum", "market")]

        cur.execute("""select action, clause from tickets
                        where session_date = %s order by action, ticker""", (days[-1],))
        rows = cur.fetchall()
        assert {c for a, c in rows if a == "buy"} == {"fill"}
        assert {c for a, c in rows if a == "sell"} == {"rank_exit"}
        # §4.3's states, and nothing outside them
        assert all(c in ("fill", "rank_exit", "displaced", "gate_off", "phase0")
                   for _, c in rows)


def test_scoring_the_same_close_twice_does_not_double_the_sheet(db, migrated):
    """`pipeline.yml`'s retry ingest re-fires the chain by design. Idempotence is not optional."""
    with db.cursor() as cur:
        days = _world(cur)
        _, ranks_a, proposed_a, _ = _run(cur, days)
        db.commit()
        _, ranks_b, proposed_b, withdrawn = _run(cur, days)
        db.commit()

        assert (ranks_a, proposed_a) == (ranks_b, proposed_b)
        assert withdrawn == 0, "a second identical pass withdraws nothing"
        cur.execute("select count(*) from tickets where session_date = %s", (days[-1],))
        assert cur.fetchone()[0] == proposed_a
        cur.execute("select count(*) from engine_sessions where session_date = %s", (days[-1],))
        assert cur.fetchone()[0] == 1


def test_a_changed_decision_withdraws_the_stale_ticket_without_deleting_it(db, migrated):
    """§4.3: the sheet is the only source of engine orders, so a proposal the re-score did not make
    is not an order. It is withdrawn by state — the row survives, because §6.4's shadow has to be
    able to read "proposed, then dropped" as distinct from "never proposed"."""
    with db.cursor() as cur:
        days = _world(cur)
        _run(cur, days)
        db.commit()
        cur.execute("""select count(*) from tickets
                        where session_date = %s and ticker = 'N04.US'""", (days[-1],))
        assert cur.fetchone()[0] == 1, "N04 is rank 5 and fills the last slot"

        # Now hold the four best names: only one slot is free, so N04 is no longer bought.
        for t in ("N00.US", "N01.US", "N02.US", "N03.US", "N04.US"):
            cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                           values (%s,'TFSA','momentum',100,40.0,'open')""", (t,))
        _, _, _, withdrawn = _run(cur, days)
        db.commit()

        assert withdrawn >= 1
        cur.execute("""select state from tickets
                        where session_date = %s and ticker = 'N04.US'""", (days[-1],))
        assert cur.fetchone()[0] == "cancelled", "withdrawn, not deleted"


def test_a_ticket_zak_has_acted_on_survives_a_rescore(db, migrated):
    """§4.3 makes execution Zak's event. A re-score that reset an approved ticket to `proposed`
    would erase the only record that he had already acted, and `reconcile` would then look for a
    receipt against a ticket the system believes was never approved."""
    with db.cursor() as cur:
        days = _world(cur)
        _run(cur, days)
        db.commit()
        cur.execute("""update tickets set state = 'approved'
                        where session_date = %s and ticker = 'N00.US'""", (days[-1],))
        db.commit()
        _run(cur, days)
        db.commit()
        cur.execute("""select state from tickets
                        where session_date = %s and ticker = 'N00.US'""", (days[-1],))
        assert cur.fetchone()[0] == "approved"


def test_a_shrinking_universe_leaves_no_stale_rank_behind(db, migrated):
    """A rank table carrying a name the engine no longer ranks reads as a decision. It is not one."""
    with db.cursor() as cur:
        days = _world(cur)
        _run(cur, days)
        db.commit()
        cur.execute("select count(*) from engine_ranks where ticker = 'N19.US'")
        assert cur.fetchone()[0] == 1

        cur.execute("""insert into universe_excluded (ticker, reason, detail)
                       values ('N19.US','duplicate_listing','planted mid-test')""")
        _run(cur, days)
        db.commit()
        cur.execute("select count(*) from engine_ranks where ticker = 'N19.US'")
        assert cur.fetchone()[0] == 0, "the dropped name must not survive at its old rank"


def test_without_a_nav_the_sells_still_carry_quantities(db, migrated):
    """§5.4: "Gate-off exits and rank-exit sells are protective-direction and are never blocked."
    A sell's quantity comes from the book, so an unknown NAV cannot silence the protective half."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))         # rank 16: below §3.5's exit rank of 12
        s, _, _, _ = _run(cur, days, nav=None)
        db.commit()
        cur.execute("""select action, qty from tickets
                        where session_date = %s order by action, ticker""", (days[-1],))
        rows = cur.fetchall()
        assert ("sell", 100.0) in rows, "the exit is sized from the book, not from NAV"
        assert all(q is None for a, q in rows if a == "buy"), "a buy is not sized on a guess"


def test_the_engine_nav_is_never_inferred_from_household_nav(db, migrated):
    """`nav_snapshots.nav_cad` is every account, converted to CAD. §3.5 sizes a USD sleeve. Using
    one for the other is wrong by the FX rate AND by the other two accounts, and it would not
    throw — it would produce a plausible position size.

    Still true after the 2026-08-19 derivation: the derived NAV is built from the engine's OWN
    book and cash, and household NAV remains no source. With an empty book and no cash anchor the
    derivation fails closed and SAYS WHY, rather than reaching for the wrong number that exists.
    """
    with db.cursor() as cur:
        cur.execute("""insert into nav_snapshots (d, nav_cad, provisional)
                       values (current_date, 500000, false)""")
        db.commit()
        nav, source = sheet.engine_nav(cur)
        assert nav is None
        assert "no balances anchor" in source["why"], "fails closed on the missing anchor"


def test_the_config_row_supplies_the_nav_when_the_environment_does_not(db, migrated):
    """And a config row is a RULING: it outranks the derivation for as long as it stands."""
    with db.cursor() as cur:
        cur.execute("""insert into config (key, value, set_by)
                       values ('engine_nav', %s, 'test')""", ("187500",))
        db.commit()
        nav, source = sheet.engine_nav(cur)
        assert nav == 187_500.0 and source["source"] == "config"


def _engine_world(cur, days):
    """The engine's own numbers, for the derivation: two priced TFSA positions, a cash anchor,
    and an FX row."""
    cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                   values ('N00.US','TFSA','momentum',20,40.0,'open'),
                          ('N01.US','TFSA','momentum',10,40.0,'open')""")
    cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source)
                   values ('TFSA', %s, 140.0, 16.0, 'test')""", (days[-1],))
    cur.execute("""insert into universe (ticker,name,kind,currency,status)
                   values ('USDCAD.FOREX','USDCAD','fx','CAD','active')
                   on conflict (ticker) do nothing""")
    cur.execute("""insert into prices (ticker,d,close,adj_close,volume) values (%s,%s,1.40,1.40,0)
                   on conflict (ticker,d) do update set close=1.40""",
                ('USDCAD.FOREX', days[-1]))


def test_the_nav_is_derived_from_the_engines_own_book_and_cash(db, migrated):
    """Zak, 2026-08-19: "You have the balances of all the accounts... You know the NAV."

    engine NAV = TFSA marked equity (every position at its last close, park included) + TFSA cash,
    CAD converted at the session's USDCAD. Every input has provenance in the store — §2.0's
    "balances are truth, prices are the extrapolation" as one number.
    """
    with db.cursor() as cur:
        days = _world(cur)
        _engine_world(cur, days)
        cur.execute("""select ticker, close from prices
                        where ticker in ('N00.US','N01.US') and d = %s""", (days[-1],))
        px = dict(cur.fetchall())
        db.commit()

        nav, source = sheet.engine_nav(cur, days[-1])
        want = 20 * float(px['N00.US']) + 10 * float(px['N01.US']) + 16.0 + 140.0 / 1.40
        assert nav == pytest.approx(want)
        assert source["source"] == "derived"
        assert source["cash_cad"] == pytest.approx(140.0) and source["usdcad"] == 1.40


def test_the_derivation_fails_closed_on_an_unpriced_position(db, migrated):
    """A TFSA holding with no bar would silently understate the equity — so the answer is "no NAV,
    and here is which name", never a smaller number that looks fine."""
    with db.cursor() as cur:
        days = _world(cur)
        _engine_world(cur, days)
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values ('DARK.US','DARK','etf','USD','active')""")
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('DARK.US','TFSA','momentum',5,10.0,'open')""")
        db.commit()
        nav, source = sheet.engine_nav(cur, days[-1])
        assert nav is None and "DARK.US" in source["why"]


def test_shadow_and_live_are_separate_records_of_the_same_close(db, migrated):
    """§6.4 runs the pipeline live producing sheets nobody trades. The shadow's answer for a close
    must not overwrite the live answer for that close, or the comparison compares nothing."""
    with db.cursor() as cur:
        days = _world(cur)
        _run(cur, days, mode="live")
        _run(cur, days, mode="shadow")
        db.commit()
        cur.execute("""select mode from engine_sessions
                        where session_date = %s order by mode""", (days[-1],))
        assert [r[0] for r in cur.fetchall()] == ["live", "shadow"]
        cur.execute("""select mode, count(*) from engine_ranks
                        where session_date = %s group by mode order by mode""", (days[-1],))
        live, shadow = cur.fetchall()
        assert live[1] == shadow[1] > 0


def test_the_sheet_view_puts_sells_before_buys(db, migrated):
    """§3.5 executes sells first. A sheet that lists them in any other order invites the one
    mistake that costs money: buying against proceeds that have not landed."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))         # rank 16: below §3.5's exit rank of 12
        _run(cur, days)
        db.commit()
        cur.execute("""select action from v_engine_sheet where session_date = %s""", (days[-1],))
        actions = [r[0] for r in cur.fetchall()]
        assert actions[0] == "sell"
        assert actions == sorted(actions, key=lambda a: 0 if a == "sell" else 1)


def test_the_job_fails_loudly_when_there_is_no_tape(db, migrated):
    """No benchmark bars means no calendar and no gate. §3.4 says a gate that cannot be evaluated
    reads OFF — and an OFF gate SELLS THE BOOK, so quietly proceeding on an empty tape would
    liquidate on missing data. It has to stop instead."""
    out = subprocess.run([sys.executable, str(ROOT / "src" / "sheet.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "PATH": "/usr/bin:/bin"})
    assert out.returncode != 0
    assert "no SPY.US bars" in (out.stdout + out.stderr)


def test_the_job_runs_end_to_end_and_reports_amber_without_a_nav(db, migrated):
    """The whole job, as CI invokes it. An unsized sheet is amber, not green and not a crash —
    §4.3 forbids new buy tickets under amber, which is exactly the state an unknown NAV produces."""
    with db.cursor() as cur:
        days = _world(cur)
    db.commit()
    out = subprocess.run([sys.executable, str(ROOT / "src" / "sheet.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "AS_OF": days[-1].isoformat(), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    assert "buys unsized" in out.stdout
    with db.cursor() as cur:
        cur.execute("select status, detail from runs where job='score' order by id desc limit 1")
        status, detail = cur.fetchone()
        assert status == "amber"
        assert any("engine NAV unknown" in a for a in detail["amber"])
        cur.execute("select count(*) from tickets where session_date = %s and qty is null",
                    (days[-1],))
        assert cur.fetchone()[0] == 5, "five unsized buys, written and explicitly not executable"


def test_the_job_writes_a_green_run_when_it_is_sized(db, migrated):
    with db.cursor() as cur:
        days = _world(cur)
    db.commit()
    out = subprocess.run([sys.executable, str(ROOT / "src" / "sheet.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "AS_OF": days[-1].isoformat(), "ENGINE_NAV": "200000",
                              "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        cur.execute("select status, rows_written from runs where job='score' order by id desc limit 1")
        status, rows = cur.fetchone()
        assert status == "green"
        assert rows == 25, "20 ranks + 5 proposals"


def test_a_shadow_pass_writes_no_tickets_at_all(db, migrated):
    """`engine_sessions` and `engine_ranks` are keyed by (session, mode); tickets are not, because
    §4.3 makes the sheet "the only source of engine orders" and a ticket carries no mode — Zak
    either executes it or he does not.

    So a shadow pass over the same close would overwrite the live sheet's rows and, worse, WITHDRAW
    every live ticket its own decision did not reproduce. §6.4's shadow produces "order sheets
    nobody trades"; a proposal sitting in the same queue as ones that should be traded is the
    opposite of that.
    """
    with db.cursor() as cur:
        days = _world(cur)
        _run(cur, days, mode="live")
        db.commit()
        cur.execute("""select id, state from tickets where session_date = %s order by id""",
                    (days[-1],))
        before = cur.fetchall()
        assert before and all(st == "proposed" for _, st in before)

        # A shadow pass whose decision differs — four of the five slots are now held, so the live
        # sheet's buys are not on the shadow's sheet at all.
        for t in ("N00.US", "N01.US", "N02.US", "N03.US"):
            cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                           values (%s,'TFSA','momentum',100,40.0,'open')""", (t,))
        _, ranks, proposed, withdrawn = _run(cur, days, mode="shadow")
        db.commit()

        assert (proposed, withdrawn) == (0, 0)
        assert ranks > 0, "the shadow still records what it ranked"
        cur.execute("""select id, state from tickets where session_date = %s order by id""",
                    (days[-1],))
        assert cur.fetchall() == before, "the live sheet is untouched, in both directions"
