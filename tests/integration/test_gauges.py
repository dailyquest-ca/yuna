"""§4.4's check suite, against a real database.

A gauge that cannot go red is decoration. Every test below breaks one thing and asserts that the
gauge for it — and ideally only that gauge — notices. The recomputation gauges get the treatment
that matters most: the tape is edited underneath a stored decision, which is the failure this
system is actually exposed to. Nothing crashes, no log records it, and every number changes.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import desk                                                               # noqa: E402
import engine                                                             # noqa: E402
import gauges                                                             # noqa: E402
import sheet                                                              # noqa: E402
from test_desk import _world                                              # noqa: E402


def _score(cur, days, nav=200_000.0, mode="live"):
    s = desk.sheet(cur, days[-1], nav)
    sheet.write_session(cur, s, mode, engine.digest())
    sheet.write_ranks(cur, s, mode)
    sheet.write_tickets(cur, s)
    return s


def _statuses(gauge_list):
    return {g["gauge"]: g["status"] for g in gauge_list}


def test_a_clean_night_is_green_on_every_gauge(db, migrated):
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
    db.commit()
    verdict, got = gauges.run(db)
    st = _statuses(got)
    assert st["gate"] == "green"
    assert st["screen"] == "green"
    assert st["rank"] == "green"
    assert st["sheet"] == "green"
    # reconciliation has never run in this world, and freshness reads a tape dated 2023-24.
    assert st["reconciliation"] == "amber"
    assert verdict in ("amber", "red")     # the fixture's tape is deliberately old


def test_the_gate_gauge_catches_a_benchmark_the_tape_no_longer_supports(db, migrated):
    """§3.4's gate decides whether the ENTIRE book sells. A stored ON against a recomputed OFF is
    the most consequential disagreement in the system, so it is the one gauge that is plainly red."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        db.commit()
        stored = gauges.newest_session(cur)
        assert gauges.gate_reproduces(cur, stored)["status"] == "green"

        # A vendor restatement: the last 30 benchmark closes come back far below their SMA.
        cur.execute("""update prices set close = close * 0.4, adj_close = adj_close * 0.4
                        where ticker = 'SPY.US' and d > %s""", (days[-30],))
        db.commit()
        g = gauges.gate_reproduces(cur, stored)

    assert g["status"] == "red"
    assert g["stored"] is True and g["recomputed"] is False
    assert "recompute" in g["why"]


def test_the_gate_gauge_catches_a_decision_stamped_ahead_of_the_bars(db, migrated):
    """A session dated later than the newest benchmark bar cannot have been decided on those bars.
    §3.4 says an unevaluable gate reads OFF, and OFF sells the book — so this must not pass."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        db.commit()
        cur.execute("delete from prices where ticker = 'SPY.US' and d >= %s", (days[-3],))
        db.commit()
        g = gauges.gate_reproduces(cur, gauges.newest_session(cur))
    assert g["status"] == "red"
    assert "newest" in g["why"] and "stamped" in g["why"]


def test_the_screen_gauge_measures_the_uncensored_count(db, migrated):
    """Migration 053's whole reason: `ranked_count` is capped at §3.2's pool of 500 and cannot move
    when the tape breaks. The gauge must read the survivor count from BEFORE the cap."""
    with db.cursor() as cur:
        days = _world(cur)
        s = _score(cur, days)
        db.commit()
        cur.execute("select ranked_count, screen_count from engine_sessions")
        ranked, screened = cur.fetchone()
    assert ranked == screened == 20, "20 names, all below the cap, so the two agree here"
    assert s["screened"] == 20

    # and the cap is what makes them differ: the same tape, screened with and without it
    with db.cursor() as cur:
        sessions, tickers, adj, raw, dv, _ = desk.load(cur, days[-1])
    i = len(sessions) - 1
    assert len(engine.screen(i, adj, raw, dv, pool=None)) == 20
    assert len(engine.screen(i, adj, raw, dv, pool=8)) == 8, "the cap censors; the gauge must not"


def _three_sessions(cur, days):
    """Tonight scored, plus two prior sessions written from the same tape (20 survivors each)."""
    _score(cur, days)
    for d in (days[-3], days[-2]):
        s = desk.sheet(cur, d, 200_000.0)
        sheet.write_session(cur, s, "live", engine.digest())


def _set_count(cur, d, n):
    cur.execute("update engine_sessions set screen_count = %s where session_date = %s", (n, d))


def test_the_screen_gauge_ambers_on_a_jump_the_tape_has_never_made(db, migrated):
    """"Within historical band" is the band of session-to-session CHANGE (§5.6, 2026-09-14). No
    threshold is chosen here, because §4.4 names none and §0.3 makes choosing one a plan edit."""
    with db.cursor() as cur:
        days = _world(cur)
        _three_sessions(cur, days)
        db.commit()
        stored = gauges.newest_session(cur)
        g = gauges.screen_within_band(cur, stored)
        assert g["status"] == "green" and g["change"] == 0 and g["band"] == [0, 0]

        _set_count(cur, days[-1], 3)                   # 17 names gone overnight: a broken tape
        db.commit()
        g = gauges.screen_within_band(cur, gauges.newest_session(cur))

    assert g["status"] == "amber"
    assert g["change"] == -17 and g["band"] == [0, 0] and g["survivors"] == 3


def test_the_screen_gauge_lets_a_drift_it_has_seen_before_through(db, migrated):
    """Three weeks of −3 a night read as amber under the level band (learning 68). A change the
    history has already shown is green; one it has not is amber."""
    with db.cursor() as cur:
        days = _world(cur)
        _three_sessions(cur, days)
        _set_count(cur, days[-3], 20)
        _set_count(cur, days[-2], 17)                  # one prior change: −3
        _set_count(cur, days[-1], 14)                  # tonight: −3 again, a new low
        db.commit()
        g = gauges.screen_within_band(cur, gauges.newest_session(cur))
        assert g["status"] == "green" and g["change"] == -3 and g["band"] == [-3, -3]

        _set_count(cur, days[-1], 10)                  # tonight: −7, never seen
        db.commit()
        g = gauges.screen_within_band(cur, gauges.newest_session(cur))
    assert g["status"] == "amber" and g["change"] == -7


def test_the_screen_gauge_ambers_on_an_upward_jump_too(db, migrated):
    """A census regression or a duplicate listing re-admitting hundreds of names is a break in the
    other direction, and the band is two-sided."""
    with db.cursor() as cur:
        days = _world(cur)
        _three_sessions(cur, days)
        _set_count(cur, days[-1], 40)                  # +20 against a band of [0, 0]
        db.commit()
        g = gauges.screen_within_band(cur, gauges.newest_session(cur))
    assert g["status"] == "amber" and g["change"] == 20


def test_a_night_the_chain_did_not_score_does_not_read_as_a_jump(db, migrated):
    """The change is judged per elapsed session on the benchmark's calendar. A missed night (a
    dropped cron, learning 58) makes tonight's change span two sessions; at −3 a session it is the
    same drift the history has shown, not a −6 jump against a band of single-session −3s."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)                              # tonight, days[-1]
        for d in (days[-4], days[-3]):                 # two priors; days[-2] was never scored
            s = desk.sheet(cur, d, 200_000.0)
            sheet.write_session(cur, s, "live", engine.digest())
        _set_count(cur, days[-4], 23)
        _set_count(cur, days[-3], 20)                  # one prior change: −3 a session
        _set_count(cur, days[-1], 14)                  # −6 over the two sessions since days[-3]
        db.commit()
        g = gauges.screen_within_band(cur, gauges.newest_session(cur))
        assert g["status"] == "green", g["why"]
        assert g["change"] == -6 and g["sessions_elapsed"] == 2 and g["per_session"] == -3.0

        _set_count(cur, days[-1], 6)                   # −14 over two sessions: −7 a session
        db.commit()
        g = gauges.screen_within_band(cur, gauges.newest_session(cur))
    assert g["status"] == "amber" and g["per_session"] == -7.0


def test_the_screen_gauge_needs_two_prior_sessions_before_it_has_a_band(db, migrated):
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        db.commit()
        g = gauges.screen_within_band(cur, gauges.newest_session(cur))
        assert g["status"] == "green" and g["band"] is None and "first stored session" in g["why"]

        s = desk.sheet(cur, days[-2], 200_000.0)      # one prior session: a change, no band
        sheet.write_session(cur, s, "live", engine.digest())
        _set_count(cur, days[-1], 3)
        db.commit()
        g = gauges.screen_within_band(cur, gauges.newest_session(cur))
    assert g["status"] == "green" and g["change"] == -17 and g["band"] is None


def test_the_rank_gauge_goes_red_when_the_top_twelve_moves(db, migrated):
    """§3.5's fill band and exit rank are both 12. A different top 12 is a different book."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        db.commit()
        assert gauges.rank_reproduces(cur, gauges.newest_session(cur))["status"] == "green"

        # A vendor restatement of the kind that leaves no trace: 60 sessions of N05's history are
        # withdrawn, so it no longer carries §3.2's 210 finite bars in 252 and drops out of the
        # ranking entirely. The stored decision still has it at rank 6.
        cur.execute("delete from prices where ticker = 'N05.US' and d > %s", (days[-60],))
        db.commit()
        g = gauges.rank_reproduces(cur, gauges.newest_session(cur))

    assert g["status"] == "red"
    assert "N05.US" in g["left"], "the name the stored top 12 has and the tape no longer supports"


def test_the_rank_gauge_ambers_when_only_the_deep_ranks_move(db, migrated):
    """Real, worth knowing, and not a decision — nothing below rank 12 reaches the book."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        db.commit()
        # N15 is stored at 16 and N19 at 20; swap them. Both sit far below §3.5's band of 12, so
        # the book is unaffected and the disagreement is still real.
        cur.execute("update engine_ranks set rank = 20 where ticker = 'N15.US'")
        cur.execute("update engine_ranks set rank = 16 where ticker = 'N19.US'")
        db.commit()
        g = gauges.rank_reproduces(cur, gauges.newest_session(cur))
    assert g["status"] == "amber"
    assert g["moved"] == 2 and g["worst"] == 4


def test_the_sheet_gauge_re_derives_every_quantity_from_the_plan(db, migrated):
    """§3.5's own arithmetic, recomputed. A quantity that does not follow from it is the single
    most expensive defect this repository can produce, because it does not throw."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        db.commit()
        assert gauges.sheet_arithmetic(cur, gauges.newest_session(cur))["status"] == "green"

        cur.execute("""update tickets set qty = qty + 1
                        where action = 'buy' and session_date = %s""", (days[-1],))
        db.commit()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))

    assert g["status"] == "red"
    assert len(g["failures"]) == 5
    assert "§3.5 gives" in g["failures"][0]


def test_the_sheet_gauge_refuses_a_sell_with_no_quantity(db, migrated):
    """§5.4 makes exits unblockable. An exit that cannot be executed is blocked by arithmetic."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))
        _score(cur, days)
        db.commit()
        cur.execute("update tickets set qty = null where action = 'sell'")
        db.commit()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "red"
    assert any("a sell with no quantity" in f for f in g["failures"])


def test_the_sheet_gauge_rejects_a_clause_the_plan_does_not_name(db, migrated):
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        db.commit()
        cur.execute("update tickets set clause = 'because_it_looked_good' where action = 'buy'")
        db.commit()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "red"
    assert any("not a recognised clause" in f for f in g["failures"])


def test_an_unsized_sheet_is_amber_not_red(db, migrated):
    """§4.3 already names this state: amber means no new buy tickets. The rows exist, unexecutable,
    and the sells beside them still stand."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))
        _score(cur, days, nav=None)
        db.commit()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "amber" and g["unsized"] == 5


FULL_BOOK = ("N00.US", "N01.US", "N02.US", "N03.US", "N04.US")   # the fixture's top five


def test_a_quiet_night_with_a_full_book_is_green_not_amber(db, migrated):
    """The book already matches the rank, so score decides nothing and writes nothing. Before the
    attestation landed this read amber on 25 of the first 36 live sessions (2026-08-14 to 10-06;
    64 of 93 check runs), every one gate-ON with a full five-name book."""
    with db.cursor() as cur:
        days = _world(cur, held=FULL_BOOK)
        s = _score(cur, days)
        db.commit()
        assert s["orders"] == []
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "green" and g["decided"] == 0 and g["tickets"] == 0


def test_a_decided_sheet_that_was_never_written_is_red(db, migrated):
    """The failure the old amber existed to catch, now wearing its own colour."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        db.commit()
        cur.execute("delete from tickets where session_date = %s", (days[-1],))
        db.commit()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "red" and g["decided"] == 5
    assert "never written" in g["why"]
    # The sheet is empty, so the brief has no order line to show — the reason has to name them.
    assert all(f"BUY {t}" in g["why"] for t in FULL_BOOK)


def test_a_partly_written_sheet_names_the_exit_that_never_left(db, migrated):
    """Completeness is checked against what score decided, not against a count. A sheet that
    carries its buys but lost its sell is the sharpest case: §5.4 makes the exit unblockable, and a
    sell with no ticket is a position that never leaves."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))
        s = _score(cur, days)
        db.commit()
        assert {(o["ticker"], o["action"]) for o in s["orders"]} >= {("N15.US", "sell")}
        cur.execute("delete from tickets where session_date = %s and action = 'sell'", (days[-1],))
        db.commit()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "red"
    assert "SELL N15.US: decided by score and never written" in g["failures"]
    assert "SELL N15.US" in g["why"]


def test_a_ticket_cancelled_by_hand_was_still_written(db, migrated):
    """Zak's own sessions have cancelled engine tickets by hand (2026-08-17: "CANCELLED
    (superseded…)"). That is his call, and the order WAS written — completeness asks whether score
    wrote what it decided, not whether Zak kept it. Red here would hold his buys for exercising it."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        cur.execute("""update tickets set state = 'cancelled', note = note || ' — CANCELLED by hand'
                        where session_date = %s""", (days[-1],))
        db.commit()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "green", g
    assert "since withdrawn" in g["why"] and g["withdrawn"] == 5


def test_a_ticket_beyond_the_decision_is_not_a_failure(db, migrated):
    """A re-score withdraws only `proposed` tickets, so one Zak already executed survives a pass
    that no longer decides it. That is the record of a real trade, not a missing order — the
    completeness check must compare sets, never counts."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        cur.execute("""insert into tickets (session_date, ticker, account, sleeve, action, reason,
                                            clause, order_type, qty, mark, rank, state, note)
                       values (%s, 'N09.US', 'TFSA', 'momentum', 'sell', 'rank_exit', 'rank_exit',
                               'market', 10, 50.0, 15, 'executed', 'an earlier pass, executed')""",
                    (days[-1],))
        db.commit()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "green", g
    assert g["tickets"] == 6


def test_the_job_attests_what_it_writes_under_a_freeze(db, migrated):
    """The attestation is only worth something if `score` itself — not a test helper — counts the
    sheet AFTER the freeze drops its buys. Run the real job under a freeze with one exit due, and
    the record must say one sell, no buys, and match the tickets on the table."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",))
        cur.execute("""insert into config (key, value, set_by) values ('freeze', %s, 'zak')""",
                    (json.dumps({"on": True, "words": "hold the buys"}),))
    db.commit()
    out = subprocess.run([sys.executable, str(ROOT / "src" / "sheet.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "AS_OF": days[-1].isoformat(), "ENGINE_NAV": "200000",
                              "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        cur.execute("""select detail from engine_sessions
                        where session_date = %s and mode = 'live'""", (days[-1],))
        detail = cur.fetchone()[0]
        cur.execute("""select ticker, action from tickets
                        where session_date = %s and state not in ('cancelled', 'void')""",
                    (days[-1],))
        written = cur.fetchall()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert detail["orders"] == 1 and detail["sells"] == ["N15.US"] and detail["buys"] == []
    assert written == [("N15.US", "sell")]
    assert g["status"] == "green", g


def test_a_shadow_session_reads_green_and_is_not_held_to_tickets(db, migrated):
    """Shadow mode writes no tickets by design (sheet.write_tickets), so its decided orders have no
    sheet to be compared with — and the gauge must not borrow the live one for the same close."""
    with db.cursor() as cur:
        days = _world(cur)
        s = desk.sheet(cur, days[-1], 200_000.0)
        sheet.write_session(cur, s, "shadow", engine.digest())
        sheet.write_ranks(cur, s, "shadow")
        assert sheet.write_tickets(cur, s, "shadow") == (0, 0)
        db.commit()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur, "shadow"))
    assert g["status"] == "green"
    assert "shadow mode writes no tickets" in g["why"]
    assert g["decided"] == 5 and g["tickets"] == 0


def test_a_session_without_the_attestation_keeps_the_old_amber(db, migrated):
    """Sessions stored before the attestation carry no `orders` key. The gauge still cannot tell a
    quiet night from a failed write for those, so it must not call them green."""
    with db.cursor() as cur:
        days = _world(cur, held=FULL_BOOK)
        _score(cur, days)
        cur.execute("update engine_sessions set detail = detail - 'orders' - 'sells' - 'buys'")
        db.commit()
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "amber"
    assert "no attestation" in g["why"]


def test_the_reconciliation_gauge_reddens_when_an_approval_outlives_a_session(db, migrated):
    """The tolerance is derived rather than chosen: an approval still awaiting a receipt after a
    LATER session was scored means the book has been reasoned from without knowing whether that
    trade happened."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days[:-1])
        _score(cur, days)
        db.commit()
        cur.execute("""update tickets set state = 'approved' where session_date = %s""",
                    (days[-2],))
        cur.execute("""insert into runs (job, status, finished_at) values
                       ('reconcile','green', now())""")
        db.commit()
        g = gauges.reconciliation_age(cur)
    assert g["status"] == "red"
    assert "a session has been scored since" in g["why"]


def test_the_reconciliation_gauge_ambers_when_it_has_never_run(db, migrated):
    with db.cursor() as cur:
        g = gauges.reconciliation_age(cur)
    assert g["status"] == "amber"
    assert "never been checked" in g["why"]


def test_the_suite_writes_nothing_but_its_own_run_row(db, migrated):
    """A check that repairs what it finds cannot be trusted to have found it."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        db.commit()
        cur.execute("select count(*) from tickets")
        tickets = cur.fetchone()[0]
        cur.execute("select count(*) from engine_ranks")
        ranks = cur.fetchone()[0]

    subprocess.run([sys.executable, str(ROOT / "src" / "gauges.py")], check=True,
                   capture_output=True, text=True,
                   env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable", "PATH": "/usr/bin:/bin"})
    with db.cursor() as cur:
        cur.execute("select count(*) from tickets")
        assert cur.fetchone()[0] == tickets
        cur.execute("select count(*) from engine_ranks")
        assert cur.fetchone()[0] == ranks
        cur.execute("select count(*) from book")
        assert cur.fetchone()[0] == 0


def test_a_red_is_a_result_not_a_crash_and_holds_only_the_buys(db, migrated):
    """§4.2 gives a red check the power to ship nothing but the stale banner and the protective
    lines. Exiting non-zero would take `compose` down with it, and §4.7 rules that a missing
    message is itself the alarm — silence is the one outcome with no reader."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        db.commit()
        cur.execute("""update tickets set qty = 999999 where action = 'buy'""")
        db.commit()

    out = subprocess.run([sys.executable, str(ROOT / "src" / "gauges.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, "a red is a result; the job ran perfectly"
    assert "### check · RED" in out.stdout
    with db.cursor() as cur:
        cur.execute("select status, detail from runs where job='check' order by id desc limit 1")
        status, detail = cur.fetchone()
    assert status == "red"
    assert detail["blocks_buys"] is True
    assert "nothing holds exits" in out.stdout


def test_the_suite_survives_a_database_with_no_engine_session(db, migrated):
    """Before the first score there is nothing to recompute. That is amber and a sentence, not a
    traceback — this job runs on every chain pass including the first."""
    verdict, got = gauges.run(db)
    st = _statuses(got)
    assert st["session"] == "amber"
    assert "no engine session has been scored" in got[0]["why"]
    assert verdict in ("amber", "red")


def test_a_red_reconcile_today_holds_the_buys_even_after_a_green_yesterday(db, migrated):
    """The hole `last_attested` leaves on its own. It counts only green and amber runs, because it
    answers "when did the comparison last succeed" — so yesterday's success would read right
    through today's position break, and §4.4's "any red holds buys" would never fire on the finding
    that most obviously should hold them. §3.5 sizes and queues against `book`."""
    import json
    with db.cursor() as cur:
        cur.execute("""insert into runs (job, status, finished_at)
                       values ('reconcile','green', now() - interval '1 day')""")
        cur.execute("""insert into runs (job, status, finished_at, detail)
                       values ('reconcile','red', now(), %s)""",
                    (json.dumps({"breaks": [{"ticker": "MU.US", "broker": 82.0, "book": 41.0}]}),))
        db.commit()
        g = gauges.reconciliation_age(cur)

    assert g["status"] == "red"
    assert "MU.US broker=82.0 book=41.0" in g["why"]
    assert g["last_attested"] is not None, "yesterday's success is still reported, just not trusted"


def test_a_red_reconcile_names_the_receipt_the_ledger_refused(db, migrated):
    """QC 2026-10-07, A21. A receipt the ledger refuses — the true post-split sale, a mistyped
    quantity — holds the buys every night until the history is repaired, and the gauge is the line
    of the brief that says why. It used to print "went red on 0 position break(s):" and nothing
    else, because it read only the broker breaks; the refusal's ticker and the ledger's reason are
    what Zak needs to act on."""
    import json
    refused = [{"account": "TFSA", "ticker": "N01.US", "ticket": 7,
                "receipt": "sell 200 @ 30 on 2026-08-17",
                "why": "ledger drives TFSA N01.US to -100 shares — the history for this name is "
                       "incomplete"}]
    with db.cursor() as cur:
        cur.execute("""insert into runs (job, status, finished_at, detail)
                       values ('reconcile','red', now(), %s)""",
                    (json.dumps({"breaks": [], "refused": refused}),))
        db.commit()
        g = gauges.reconciliation_age(cur)
    assert g["status"] == "red"
    assert "TFSA N01.US: ledger drives TFSA N01.US to -100 shares" in g["why"]


def test_a_green_reconcile_after_a_red_one_clears_the_gauge(db, migrated):
    """The newest run is what governs, in both directions — a gauge that latched red would need a
    hand to clear it, and §4.4's suite has no such state."""
    import json
    with db.cursor() as cur:
        cur.execute("""insert into runs (job, status, finished_at, detail)
                       values ('reconcile','red', now() - interval '1 hour', %s)""",
                    (json.dumps({"breaks": [{"ticker": "MU.US", "broker": 82.0, "book": 41.0}]}),))
        cur.execute("""insert into runs (job, status, finished_at)
                       values ('reconcile','green', now())""")
        db.commit()
        g = gauges.reconciliation_age(cur)
    assert g["status"] == "green"


def test_a_withdrawn_ticket_is_not_counted_as_an_order(db, migrated):
    """§4.3: "the nightly sheet is the only source of engine orders", and a re-score that no longer
    stands behind a proposal cancels it. A `cancelled` row is therefore a record of an order that is
    NOT one, and counting it makes this gauge describe a sheet nobody is executing.

    Found in production on 2026-08-18: the account filter withdrew two buy tickets the engine had
    proposed for names it already held, and the sheet gauge went on reporting "5 buy ticket(s) carry
    no quantity" against three real ones. The sizing check is the sharper half — a stale quantity on
    a withdrawn ticket would go RED for failing to match §3.5's arithmetic.
    """
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        cur.execute("""select count(*) from tickets where session_date = %s""", (days[-1],))
        before = cur.fetchone()[0]
        assert before == engine.SLOTS, "five buys on an empty book"
        # withdraw two, exactly as `write_tickets` does on a re-score
        cur.execute("""update tickets set state = 'cancelled'
                        where session_date = %s and ticker in ('N00.US','N01.US')""", (days[-1],))
    db.commit()
    verdict, got = gauges.run(db)
    sheet_gauge = next(g for g in got if g["gauge"] == "sheet")

    assert sheet_gauge["status"] == "green", sheet_gauge["why"]
    assert sheet_gauge["tickets"] == before - 2, "the withdrawn pair is not an order"


def test_a_stale_quantity_on_a_withdrawn_ticket_does_not_go_red(db, migrated):
    """The expensive half of the same defect: §3.5's arithmetic re-derived against a proposal the
    engine has already retracted. Red holds the buys (§4.4), so this would hold a correct sheet on
    the strength of an incorrect one nobody is being asked to execute."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days)
        cur.execute("""update tickets set state = 'cancelled', qty = 999999
                        where session_date = %s and ticker = 'N00.US'""", (days[-1],))
    db.commit()
    verdict, got = gauges.run(db)
    sheet_gauge = next(g for g in got if g["gauge"] == "sheet")
    assert sheet_gauge["status"] == "green", sheet_gauge["why"]


def test_the_gauge_re_derives_a_seed_sheet_fund_and_topups_included(db, migrated):
    """The first real seed sheet must not be held by its own arithmetic check. A `fund` sell's
    quantity is the park position, not NAV/5; a `top_up` buy is the slot LESS the line held. The
    gauge validates each by its own rule — and still goes red when a top-up quantity is wrong,
    because a wrong size on the one sheet that deploys everything is the most expensive number
    this system can produce."""
    from test_desk import _park, _shadow_passed
    with db.cursor() as cur:
        days = _world(cur)
        _park(cur, days)
        _shadow_passed(cur, days)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','momentum',20,40.0,'open')""")
        _score(cur, days)
    db.commit()
    verdict, got = gauges.run(db)
    sheet_gauge = next(g for g in got if g["gauge"] == "sheet")
    assert sheet_gauge["status"] == "green", sheet_gauge

    with db.cursor() as cur:                            # now break the top-up's size
        cur.execute("""update tickets set qty = qty + 7
                        where clause = 'top_up' and session_date = %s""", (days[-1],))
    db.commit()
    verdict, got = gauges.run(db)
    sheet_gauge = next(g for g in got if g["gauge"] == "sheet")
    assert sheet_gauge["status"] == "red", "a mis-sized top-up must hold the buys"


def test_a_tape_that_advanced_past_the_newest_session_is_red(db, migrated):
    """The suite's currency check (QC 2026-10-07, A46). Tonight's bars landed and no session was
    scored on them — score never ran, ran dry, or was cancelled — so every recomputation gauge would
    re-prove yesterday's sheet against itself, and on a quiet night all six read green. The gate
    gauge already reddened a decision stamped AFTER the newest bar; this is the other direction."""
    with db.cursor() as cur:
        days = _world(cur)
        _score(cur, days[:-1])                      # the tape runs to days[-1]; the desk stopped a day short
        db.commit()
        stored = gauges.newest_session(cur)
        assert stored["session_date"] == days[-2]
        g = gauges.gate_reproduces(cur, stored)
    assert g["status"] == "red", g
    assert "no session was scored on it" in g["why"] and g["newest_bar"] == str(days[-1])
    verdict, _ = gauges.run(db)
    assert verdict == "red", "a stale sheet holds the buys (§0.4)"


def test_a_fractionally_held_name_tops_up_green(db, migrated):
    """desk.sheet sizes a top-up as int(slot - held), the held line being whatever the broker
    filled — ASX.US is 512.4837 shares. The gauge truncated the held line first and asked for one
    share more, so every top-up of a fractional holding read RED and held the night's buys
    (QC 2026-10-07, A8). Re-derived the desk's way, a correct top-up is green."""
    from test_desk import _park, _shadow_passed
    with db.cursor() as cur:
        days = _world(cur)
        _park(cur, days)
        _shadow_passed(cur, days)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','momentum',20.5,40.0,'open')""")
        s = _score(cur, days)
    db.commit()
    assert any(o["clause"] == "top_up" and o["ticker"] == "N00.US" for o in s["orders"])
    verdict, got = gauges.run(db)
    sheet_gauge = next(g for g in got if g["gauge"] == "sheet")
    assert sheet_gauge["status"] == "green", sheet_gauge


def test_an_order_over_the_participation_cap_is_red(db, migrated):
    """§3.5: "an order may not exceed 0.98 of the name's ADDV — a correctness check, not a live
    constraint at current size". The docstring always claimed this gauge checked it; nothing did
    (QC 2026-10-07, A64). At a NAV large enough that a fifth of it outweighs a day's trading in the
    name, every fill breaks the cap, and the sheet must not read green."""
    with db.cursor() as cur:
        days = _world(cur)
        s = _score(cur, days, nav=1e12)
    db.commit()
    assert all(o["participation_ok"] is False for o in s["orders"] if o["action"] == "buy")
    with db.cursor() as cur:
        g = gauges.sheet_arithmetic(cur, gauges.newest_session(cur))
    assert g["status"] == "red", g
    assert sum("ADDV" in f for f in g["failures"]) == 5
