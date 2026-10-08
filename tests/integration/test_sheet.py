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


def _engine_world(cur, days, *, cad=140.0, usd=16.0, anchored=None):
    """The engine's own numbers, for the derivation: two priced TFSA positions, a cash anchor,
    and an FX row."""
    cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                   values ('N00.US','TFSA','momentum',20,40.0,'open'),
                          ('N01.US','TFSA','momentum',10,40.0,'open')""")
    cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source)
                   values ('TFSA', %s, %s, %s, 'test')""", (anchored or days[-1], cad, usd))
    cur.execute("""insert into universe (ticker,name,kind,currency,status)
                   values ('USDCAD.FOREX','USDCAD','fx','CAD','active')
                   on conflict (ticker) do nothing""")
    cur.execute("""insert into prices (ticker,d,close,adj_close,volume) values (%s,%s,1.40,1.40,0)
                   on conflict (ticker,d) do update set close=1.40""",
                ('USDCAD.FOREX', days[-1]))


def test_the_nav_is_derived_from_the_engines_own_book_and_cash(db, migrated):
    """Zak, 2026-08-19: "You have the balances of all the accounts... You know the NAV."

    engine NAV = TFSA marked equity (every position at its last close, park included) + TFSA cash,
    CAD converted at the session's USDCAD. Every input has provenance in the store — the retired
    plan's "balances are truth, prices are the extrapolation" (§2.0, not in v1.0) as one number.
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


def _hold(cur, ticker, qty, closes, *, ccy="USD"):
    """A TFSA holding outside the ranked tape, carrying exactly the bars given ({date: close})."""
    cur.execute("""insert into universe (ticker,name,kind,currency,status)
                   values (%s,%s,'etf',%s,'active') on conflict (ticker) do nothing""",
                (ticker, ticker, ccy))
    for d, close in closes.items():
        cur.execute("""insert into prices (ticker,d,close,adj_close,volume)
                       values (%s,%s,%s,%s,1000)""", (ticker, d, close, close))
    if qty:
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values (%s,'TFSA','momentum',%s,10.0,'open')""", (ticker, qty))


def test_a_padded_zero_close_is_no_mark_and_the_derivation_names_it(db, migrated):
    """A15. The vendor pads a delisting tail with 0.0000 (learning 33), and production stores those
    rows as the last bars of AEL, CONN, HIBB and PACW. A held name marked at 0 is still a number, so
    it walked past the unpriced fail-closed: NAV silently lost the slot and every buy came out
    small. A close at or below zero is not a price — the derivation refuses and names it, and the
    sheet's own marked equity lists it instead of counting it at nothing."""
    import desk
    with db.cursor() as cur:
        days = _world(cur)
        _engine_world(cur, days)
        _hold(cur, "GONE.US", 50, {d: 30.0 for d in days[-10:-2]} | {days[-2]: 0.0, days[-1]: 0.0})
        db.commit()
        nav, source = sheet.engine_nav(cur, days[-1])
        assert nav is None
        assert "GONE.US" in source["why"] and "not a price" in source["why"]
        s = desk.sheet(cur, days[-1], 200_000.0)
        assert "GONE.US" in s["unpriced"], "named on the session row, not marked at zero"


def test_a_holding_its_exchange_printed_without_is_stale_and_named(db, migrated):
    """A15. §3.5 sizes at engine NAV ÷ 5 "marked at the decision close". A holding with no bar on
    the decision session — a halt, a vendor omission, a cash-merged line — has only an older close,
    and marking it there kept a full slot of NAV at a price nobody could trade, with every gauge
    green. SPY.US and the rest of `.US` printed the last session and HALT.US did not, so the
    derivation refuses and says which bar it has and which session it missed.

    The sheet's marked equity still counts HALT.US at its last close. That number is §5.2's
    drawdown record, where a halt is a data boundary and not a loss."""
    import desk
    with db.cursor() as cur:
        days = _world(cur)
        _engine_world(cur, days)
        _hold(cur, "HALT.US", 5, {d: 30.0 for d in days[-10:-2]})       # last bar: days[-3]
        db.commit()
        nav, source = sheet.engine_nav(cur, days[-1])
        assert nav is None
        why = source["why"]
        assert "stale TFSA position(s): HALT.US" in why
        assert str(days[-3]) in why and str(days[-1]) in why

        s = desk.sheet(cur, days[-1], 200_000.0)
        cur.execute("""select ticker, close from prices
                        where ticker in ('N00.US','N01.US') and d = %s""", (days[-1],))
        px = dict(cur.fetchall())
        assert "HALT.US" not in s["unpriced"]
        assert s["marked_equity"] == pytest.approx(20 * px["N00.US"] + 10 * px["N01.US"] + 5 * 30.0)


def test_a_tsx_holding_is_judged_by_the_tsx_calendar(db, migrated):
    """A15, and the trap in it. The decision calendar is SPY's, and the TSX keeps holidays the
    NYSE does not: on 2025-10-13 and 2026-08-03 SPY.US printed and no `.TO` name in the store did.
    A `.TO` holding with no bar on such a session is on its own exchange's calendar, not stale, so
    staleness is read off the tape — did another name on the holding's own exchange print it?

    (§2.1 keeps the engine on `.US` names, but `held_book` reads the account, and the rule has to be
    right for whatever the account holds.)"""
    with db.cursor() as cur:
        days = _world(cur)
        _engine_world(cur, days)
        tsx_week = {d: 30.0 for d in days[-10:-1]}                       # shut on days[-1]
        _hold(cur, "XYZ.TO", 5, tsx_week, ccy="CAD")
        _hold(cur, "PEER.TO", 0, tsx_week, ccy="CAD")
        db.commit()
        nav, source = sheet.engine_nav(cur, days[-1])
        assert nav is not None, f"a TSX holiday is not a stale bar: {source}"

        # The same night with the TSX open: another `.TO` name printed it, and XYZ.TO did not.
        _hold(cur, "PEER.TO", 0, {days[-1]: 30.5}, ccy="CAD")
        db.commit()
        nav, source = sheet.engine_nav(cur, days[-1])
        assert nav is None and "stale TFSA position(s): XYZ.TO" in source["why"]


def test_a_negative_tfsa_balance_fails_closed_and_the_test_reads_the_total(db, migrated):
    """A52. A TFSA cannot borrow — §2.3's facility is a separate account whose draws buy VXC.TO in
    the NONREG — so cash that derives below zero is no state the account can be in: a credit the
    store never heard of, or a row on the wrong side of the anchor, of a size nobody can know from
    here. It flowed into NAV, and so into every NAV/5 buy, for as long as NAV stayed positive.

    The test reads the account's total in USD. A USD buy paid out of CAD takes the USD leg negative
    while NAV is right — the ledger has no row for the conversion — so -500 USD beside C$1,400
    (US$1,000 at 1.40) is a sound account and derives; -2,000 USD beside it is not, and does not."""
    buy = """insert into transactions (ticker, account, side, qty, price, currency, trade_date,
                                       confirmed)
             values ('N05.US','TFSA','buy',50,30.0,'USD',%s,true)"""
    with db.cursor() as cur:
        days = _world(cur)
        _engine_world(cur, days, cad=1_400.0, usd=1_000.0, anchored=days[-2])
        cur.execute(buy, (days[-1],))
        db.commit()
        nav, source = sheet.engine_nav(cur, days[-1])
        assert nav is not None, source
        assert source["cash_usd"] == pytest.approx(-500.0)

        cur.execute(buy, (days[-1],))
        db.commit()
        nav, source = sheet.engine_nav(cur, days[-1])
        assert nav is None
        why = source["why"]
        assert "TFSA cash derives to -1,000.00 USD (-2,000.00 USD + 1,400.00 CAD @ 1.4000)" in why
        assert f"anchor of {days[-2]} (1 day)" in why and "-3,000.00 USD by the ledger" in why


def test_the_anchors_date_and_age_ride_with_the_derived_nav(db, migrated):
    """A52. Every NAV/5 buy is sized off a cash term whose truth is a hand-written reading, and
    nothing said how old the reading was: production's sat at 2026-08-17 for seven weeks while the
    dividends and withholding the ledger does not model piled up behind it. No age fails — the
    plan rules no refresh cadence — but the date and the age travel with the number."""
    with db.cursor() as cur:
        days = _world(cur)
        _engine_world(cur, days, anchored=days[-31])
        db.commit()
        nav, source = sheet.engine_nav(cur, days[-1])
        assert nav is not None, "an old anchor is reported, never refused"
        assert source["cash_as_of"] == str(days[-31]) and source["cash_age_days"] == 30


def test_same_day_fills_the_anchor_is_taken_to_contain_ride_with_the_nav(db, migrated):
    """A30 at the derivation. The anchor here is dated the session and written long after its open,
    so a round trip that day cannot be ordered against the reading: it is taken as inside it, as
    before, and named beside the NAV whose size rests on that reading of the date."""
    with db.cursor() as cur:
        days = _world(cur)
        _engine_world(cur, days)
        cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                                 trade_date, confirmed)
                       values ('N05.US','TFSA','buy',1,30.0,'USD',%s,true),
                              ('N05.US','TFSA','sell',1,31.0,'USD',%s,true)""",
                    (days[-1], days[-1]))
        db.commit()
        nav, source = sheet.engine_nav(cur, days[-1])
        assert nav is not None
        assert source["cash_usd"] == pytest.approx(16.0), "inside the reading: not counted again"
        assert source["cash_same_day_assumed_inside"] == {"fills": 2,
                                                          "net": {"USD": pytest.approx(1.0)}}


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


def _score(migrated, days):
    """The job as CI runs it — no ENGINE_NAV, so the NAV is derived."""
    out = subprocess.run([sys.executable, str(ROOT / "src" / "sheet.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "AS_OF": days[-1].isoformat(), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    return out


def test_the_anchors_age_reaches_the_session_row_and_the_score_run(db, migrated):
    """A52: the anchor's date and age are stored where the NAV is — `engine_sessions.detail` and
    the score run's detail — so the brief and the check read them off the night's own record."""
    with db.cursor() as cur:
        days = _world(cur)
        _engine_world(cur, days, anchored=days[-8])
    db.commit()
    _score(migrated, days)
    with db.cursor() as cur:
        cur.execute("""select nav, detail->'nav_source' from engine_sessions
                        where session_date = %s and mode = 'live'""", (days[-1],))
        nav, stored = cur.fetchone()
        assert nav is not None
        assert stored["cash_as_of"] == str(days[-8]) and stored["cash_age_days"] == 7
        cur.execute("""select status, detail->'nav_source' from runs
                        where job = 'score' order by id desc limit 1""")
        status, ran = cur.fetchone()
        assert status == "green"
        assert ran["cash_as_of"] == str(days[-8]) and ran["cash_age_days"] == 7


def test_a_negative_balance_holds_the_buys_and_lets_the_sells_stand(db, migrated):
    """A52 through the job: NAV is None with the reason, so `score` goes amber — a price-critical
    amber, which holds the buys (§4.3 as amended 2026-09-14) — and the protective half of the sheet
    is untouched (§5.4)."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))         # rank 16: below §3.5's exit rank of 12
        _engine_world(cur, days, cad=0.0, usd=-250.0)
    db.commit()
    _score(migrated, days)
    with db.cursor() as cur:
        cur.execute("select status, detail from runs where job='score' order by id desc limit 1")
        status, detail = cur.fetchone()
        assert status == "amber"
        assert any("TFSA cash derives to -250.00 USD" in a for a in detail["amber"]), detail
        cur.execute("""select action, ticker, qty from tickets
                        where session_date = %s""", (days[-1],))
        rows = cur.fetchall()
        assert ("sell", "N15.US", 100.0) in rows, "the exit is sized from the book, not from NAV"
        assert [q for a, _, q in rows if a == "buy"] and \
            all(q is None for a, _, q in rows if a == "buy"), "every buy is written unsized"


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


def _proposal(cur, session, ticker, *, state="proposed", qty=40, fill=None):
    cur.execute("""insert into tickets (session_date, ticker, account, sleeve, action, clause,
                                        order_type, qty, state, fill_qty, fill_price, fill_date)
                   values (%s,%s,'TFSA','momentum','buy','fill','market',%s,%s,%s,%s,%s)
                   returning id""",
                (session, ticker, qty, state, fill, 41.0 if fill else None,
                 session if fill else None))
    return cur.fetchone()[0]


def _state(cur, tid):
    cur.execute("select state, note from tickets where id = %s", (tid,))
    return cur.fetchone()


def test_tonights_sheet_supersedes_every_earlier_proposal(db, migrated):
    """QC 2026-10-07, A57. §4.3: "The nightly sheet is the only source of engine orders", and §3.5
    cancels an entry that found no print rather than retrying it. `write_tickets` withdrew only its
    own session's stale proposals, so 27 from 2026-08-14..26 sat `proposed` for six weeks — where
    `reconcile` would have linked a receipt to the oldest of them.

    Tonight's sheet now withdraws every earlier proposal, by state, saying which session superseded
    it — except one Zak has already acted on (a fill on it, or a ledger row behind it), and except
    his `approved` word, which only a receipt moves. Idempotent, and nothing that reads tonight's
    sheet — the payload's order sheet, the sheet gauge — sees any of it."""
    import gauges
    with db.cursor() as cur:
        days = _world(cur)
        # TFSA cash to size the buys against: once v1.1 lands (§3.5, "the lesser of slot weight
        # and deployable TFSA cash") a sheet with no cash anchor leaves its buys unsized, and the
        # sheet gauge below reads amber for that rather than for anything this test is about. A
        # million covers five slots of NAV / 5 at weight; before v1.1 the cash is not read here.
        cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source)
                       values ('TFSA', %s, 0, 1000000, 'test')""", (days[-40],))
        earlier = days[-8]
        stale = _proposal(cur, earlier, "N10.US")
        approved = _proposal(cur, earlier, "N11.US", state="approved")
        filled = _proposal(cur, earlier, "N12.US", fill=40)
        receipted = _proposal(cur, earlier, "N13.US")
        cur.execute("""insert into transactions (ticket_id, ticker, account, side, qty, price,
                                                 currency, trade_date, confirmed, confirmed_at,
                                                 grade, source)
                       values (%s,'N13.US','TFSA','buy',40,41.0,'USD',%s,true,now(),'stated',
                               'zak in chat')""", (receipted, days[-7]))
        db.commit()

        _, _, proposed, withdrawn = _run(cur, days)
        db.commit()
        assert withdrawn == 1
        state, note = _state(cur, stale)
        assert state == "cancelled" and note.endswith(f"superseded by session {days[-1]}")
        assert [_state(cur, t)[0] for t in (approved, filled, receipted)] == [
            "approved", "proposed", "proposed"], "what Zak acted on is left for its receipt"
        cur.execute("""select count(*) from tickets
                        where session_date = %s and state = 'proposed'""", (days[-1],))
        assert cur.fetchone()[0] == proposed > 0, "tonight's sheet stands"

        _, _, again, withdrawn_again = _run(cur, days)
        db.commit()
        assert withdrawn_again == 0 and _state(cur, stale)[1].count("superseded") == 1

        cur.execute("select jsonb_array_length(order_sheet) from v_session_payload")
        assert cur.fetchone()[0] == again, "the brief's sheet is tonight's, and only tonight's"
        assert gauges.sheet_arithmetic(cur, gauges.newest_session(cur))["status"] == "green"


def test_a_superseded_proposal_zak_executed_still_reaches_executed(db, migrated):
    """A57's other half. Zak trades a sheet at the open and may tell the chat after the next sheet
    is scored — "sometimes those transactions are lagged... by days" (2026-08-18). The proposal is
    superseded by then, and the receipt that names it is still the event (§4.3): it advances the
    ticket to `executed` rather than leaving an order he filled recorded as withdrawn."""
    import reconcile
    with db.cursor() as cur:
        days = _world(cur)
        order = _proposal(cur, days[-2], "N00.US")
        _run(cur, days)
        db.commit()
        assert _state(cur, order)[0] == "cancelled", "superseded by tonight's sheet"

        cur.execute("""insert into transactions (ticket_id, ticker, account, side, qty, price,
                                                 currency, trade_date, confirmed, confirmed_at,
                                                 grade, source)
                       values (%s,'N00.US','TFSA','buy',40,41.0,'USD',%s,true,now(),'stated',
                               'zak in chat, a night late')""", (order, days[-1]))
        db.commit()
        assert reconcile.apply_unapplied(cur) != []
        db.commit()
        assert _state(cur, order)[0] == "executed"
