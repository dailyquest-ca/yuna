"""End-to-end tests for the arming half of `score`, over a real database.

Each test states its whole world, runs the job, and asserts on what the machine concluded. Nothing
here reaches the network: since the §4.2 rewrite the vendor calls live in `ingest` and `check`, so
`score` has nothing to stub — which is the architecture doing its job.
"""
import datetime as dt
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import score                                                              # noqa: E402
import arming                                                             # noqa: E402
import ingest                                                             # noqa: E402
import fixtures as world                                                     # noqa: E402


@pytest.fixture(autouse=True)
def only_the_arming_half(monkeypatch):
    """These tests are about the book and the night's conclusions, so the bench scorer and the
    momentum ranker — the other two thirds of `score` — are stubbed out. They have their own
    coverage, they need a fully populated universe, and running them here would test the fixtures
    rather than the arming."""
    monkeypatch.setattr(score, "score_bench", lambda conn, hb: None)
    monkeypatch.setattr(score.rank, "run", lambda conn, hb: None)


class _HB:
    """The heartbeat's shape, without a runs row — enough for a helper called outside a job."""
    def __init__(self):
        self.detail, self.calls, self.rows, self.id = {}, [0], 0, None

    def amber(self, why):
        self.detail.setdefault("amber", []).append(why)


def quarantine(db, monkeypatch, quote):
    """Run the quarantine exactly as `ingest` does, then let `score` react to what it found.

    §4.2 moved this pass into the first verb, which makes exit-blocking a contract ACROSS jobs:
    ingest decides which prints nobody can confirm, score refuses to sell on them. Testing the two
    together is the point — a quarantine nothing honours is decoration.
    """
    monkeypatch.setattr(ingest, "get", quote)
    with db.cursor() as cur:
        cur.execute("""select ticker from universe
                       where is_holding or ticker in (select ticker from queue)
                          or ticker in (select ticker from bench)
                          or ticker in (select ticker from book where status='open')""")
        bars = ingest.load_bars(cur, [r[0] for r in cur.fetchall()])
        watched_exits = ingest.stops_breached(cur, bars)
    return ingest.quarantine_pass(db, _HB(), bars, 0.40, 0.02, watched_exits)


def run():
    assert score.main() == 0


def armed(conn, kind=None, ticker=None):
    q = "select kind,ticker,sleeve,account,reason,urgency,order_type,trigger_price,limit_price," \
        "stop,qty,size_pct,score,blocked_by,note,detail,currency,fx_estimate,risk_cad," \
        "risk_pct_nav from armed where true"
    args = []
    if kind:
        q += " and kind=%s"; args.append(kind)
    if ticker:
        q += " and ticker=%s"; args.append(ticker)
    with conn.cursor() as cur:
        cur.execute(q, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def book_row(conn, ticker):
    with conn.cursor() as cur:
        cur.execute("""select qty, avg_cost, pyramid_step, stop, trail_mode, pivot, target_qty,
                              confirmed, theme, status, pyramid_stalled_since
                       from book where ticker=%s""", (ticker,))
        r = cur.fetchone()
        if not r:
            return None
        return dict(zip(["qty", "avg_cost", "step", "stop", "trail_mode", "pivot", "target_qty",
                         "confirmed", "theme", "status", "stalled"], r))


# --------------------------------------------------------------------------- the fill loop (§4.5)

def test_a_fill_opens_a_position_at_half_size_carrying_its_pivot_and_target(db, fx):
    """§3.2's first position is 50% of full size. The pivot and the full-size target must travel
    from the ticket to the book row, or the pyramid has nothing to size off and the hair-trigger
    has no reference — both were broken until migration 022."""
    with db.cursor() as cur:

        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur)
        tid = world.ticket(cur, "AAA.US", qty=100, target=200, trigger=110.0)
        world.fill(cur, tid, "AAA.US", qty=100, price=110.0)
        world.balances(cur)
    db.commit()
    run()

    row = book_row(db, "AAA.US")
    assert row["qty"] == 100 and row["target_qty"] == 200        # half now, full is the target
    assert row["pivot"] == pytest.approx(110.0)
    assert row["theme"] == "test theme"                          # §2.2 theme rides the ticket
    assert row["stalled"] is not None                            # §3.2's four-week clock started
    with db.cursor() as cur:
        cur.execute("select state from tickets where id=%s", (tid,))
        assert cur.fetchone()[0] == "provisional"                # §4.5 proposed→approved→provisional
        cur.execute("select applied_at from transactions where ticker='AAA.US'")
        assert cur.fetchone()[0] is not None


def test_running_twice_does_not_apply_a_fill_twice(db, fx):
    """Idempotence is the property no amount of code-reading proves. §4.2: all jobs are safe to
    re-run, and the retry job exists precisely to re-run them."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur)
        tid = world.ticket(cur, "AAA.US", qty=100, target=200)
        world.fill(cur, tid, "AAA.US", qty=100, price=110.0)
        world.balances(cur)
    db.commit()
    run()
    first = book_row(db, "AAA.US")
    run()
    again = book_row(db, "AAA.US")
    assert first["qty"] == again["qty"] == 100
    with db.cursor() as cur:
        cur.execute("select count(*) from book where ticker='AAA.US' and status='open'")
        assert cur.fetchone()[0] == 1


def test_a_sell_fill_closes_the_position(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur)
        world.position(cur, "AAA.US", qty=100)
        tid = world.ticket(cur, "AAA.US", action="sell", qty=100)
        world.fill(cur, tid, "AAA.US", side="sell", qty=100, price=115.0)
        world.balances(cur)
    db.commit()
    run()
    assert book_row(db, "AAA.US")["status"] == "closed"


# --------------------------------------------------------------------------- protection (§3.2/§4.6)

def test_a_crossed_stop_arms_a_protective_exit(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        # the session's low pierces the stop at 101.2
        world.flat_then_base(cur, "AAA.US", last_close=100.0, last_low=99.0, last_open=100.5)
        world.gate(cur)
        world.position(cur, "AAA.US", stop=101.2)
        world.balances(cur)
    db.commit()
    run()
    rows = armed(db, "exit", "AAA.US")
    assert len(rows) == 1
    assert rows[0]["reason"] == "stop" and rows[0]["urgency"] == "protective"


def test_a_gap_below_the_stop_limit_arms_a_market_sell_at_open(db, fx):
    """§4.6: the rare case — price opens below the limit, the resting sell never fills, and the
    instruction becomes market sell at open."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", last_open=90.0, last_close=91.0, last_low=89.0)
        world.gate(cur)
        world.position(cur, "AAA.US", stop=101.2)          # stop_limit is 0.97 x stop = 98.16
        world.balances(cur)
    db.commit()
    run()
    row = armed(db, "exit", "AAA.US")[0]
    assert row["reason"] == "gap" and row["urgency"] == "protective"
    assert "market sell at open" in row["note"]


def test_the_gate_going_off_sends_the_momentum_sleeve_to_cash(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur, "OFF")
        world.position(cur, "AAA.US", stop=None)
        world.balances(cur)
    db.commit()
    run()
    row = armed(db, "exit", "AAA.US")[0]
    assert row["reason"] == "gate_off" and row["urgency"] == "protective"


def test_an_unconfirmed_breakout_closing_below_its_pivot_exits(db, fx):
    """§3.2's one hair-trigger while unconfirmed. It keys off the pivot the position was ENTERED
    on — reading it from `queue` broke as soon as the base re-scanned."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", last_close=108.0)     # below the 110 pivot
        world.gate(cur)
        world.position(cur, "AAA.US", confirmed=False, pivot=110.0, stop=95.0)
        world.balances(cur)
    db.commit()
    run()
    row = armed(db, "exit", "AAA.US")[0]
    assert row["reason"] == "unconfirmed" and row["urgency"] == "protective"


def test_a_confirmed_breakout_holding_above_its_pivot_is_left_alone(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", last_close=112.0)
        world.gate(cur)
        world.position(cur, "AAA.US", confirmed=True, pivot=110.0, stop=95.0, step=1, target=200)
        world.balances(cur)
    db.commit()
    run()
    assert armed(db, "exit", "AAA.US") == []


# --------------------------------------------------------------------------- the pyramid (§3.2)

def test_a_confirmed_breakout_arms_both_pyramid_steps_with_the_ceiling_limit(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", last_close=111.0)
        world.gate(cur)
        world.position(cur, "AAA.US", confirmed=True, pivot=100.0, step=1, target=200, stop=95.0)
        world.balances(cur)
    db.commit()
    run()
    adds = sorted(armed(db, "add", "AAA.US"), key=lambda r: r["trigger_price"])
    assert [r["trigger_price"] for r in adds] == pytest.approx([102.0, 104.0])
    assert [r["limit_price"] for r in adds] == pytest.approx([105.0, 105.0])
    assert [r["qty"] for r in adds] == pytest.approx([50.0, 50.0])       # 25% of 200 each


def test_an_unconfirmed_breakout_arms_no_pyramid_at_all(db, fx):
    """§3.2: unconfirmed freezes the pyramid at step 1. Half size, and it stays half size."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", last_close=111.0)
        world.gate(cur)
        world.position(cur, "AAA.US", confirmed=False, pivot=100.0, step=1, target=200, stop=95.0)
        world.balances(cur)
    db.commit()
    run()
    assert armed(db, "add", "AAA.US") == []


def test_volume_confirms_a_breakout_from_the_bars_themselves(db, fx):
    """The breakout session is measured against the 50 sessions BEFORE it, never its own."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        days = world.flat_then_base(cur, "AAA.US", volume=1_000_000, last_close=111.0,
                                 last_volume=2_000_000)                    # 2.0x the baseline
        world.gate(cur)
        world.position(cur, "AAA.US", opened_days_ago=0, pivot=110.0, stop=95.0, confirmed=None)
        world.balances(cur)
    db.commit()
    run()
    assert book_row(db, "AAA.US")["confirmed"] is True


def test_thin_volume_leaves_a_breakout_unconfirmed_without_exiting_it(db, fx):
    """The amended §3.2: no exit on volume alone. The old rule exited next morning and cost 4.7%
    of NAV over two years in the backtest."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", volume=1_000_000, last_close=111.0,
                          last_volume=1_000_000)                           # 1.0x — not 1.4x
        world.gate(cur)
        world.position(cur, "AAA.US", opened_days_ago=0, pivot=110.0, stop=95.0, confirmed=None)
        world.balances(cur)
    db.commit()
    run()
    assert book_row(db, "AAA.US")["confirmed"] is None       # still inside the 3-session window
    assert armed(db, "exit", "AAA.US") == []                 # and emphatically not an exit


# --------------------------------------------------------------------------- stops ratchet (§3.2)

def test_full_size_ratchets_the_stop_to_breakeven_and_arms_the_move(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", level=100.0, last_close=101.0)
        world.gate(cur)
        world.position(cur, "AAA.US", cost=100.0, stop=95.0, step=3, confirmed=True, target=200,
                    opened_days_ago=120)
        world.balances(cur)
    db.commit()
    run()
    row = book_row(db, "AAA.US")
    assert row["trail_mode"] == "breakeven" and row["stop"] == pytest.approx(100.0)
    move = armed(db, "stop_move", "AAA.US")[0]
    assert move["urgency"] == "protective" and move["stop"] == pytest.approx(100.0)


def test_a_stop_never_ratchets_down(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", level=100.0, last_close=100.0)
        world.gate(cur)
        world.position(cur, "AAA.US", cost=100.0, stop=99.0, step=0, confirmed=True,
                    opened_days_ago=120)
        world.balances(cur)
    db.commit()
    run()
    assert book_row(db, "AAA.US")["stop"] == pytest.approx(99.0)
    assert armed(db, "stop_move", "AAA.US") == []


# --------------------------------------------------------------------------- entries and caps

def test_a_live_trigger_arms_a_half_size_entry_with_its_stop_pair(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "BBB.US")
        world.flat_then_base(cur, "BBB.US")
        world.gate(cur)
        world.candidate(cur, "BBB.US", mcn=80.0, pivot=125.0, stop=115.0, last_close=120.0)
        world.queued(cur, "BBB.US", trigger=125.0, stop=115.0, mcn=80.0)
        world.balances(cur)
    db.commit()
    run()
    row = armed(db, "entry", "BBB.US")[0]
    assert row["blocked_by"] is None
    # the nightly re-scan owns these numbers, not the seeded queue row: pivot 110 from the base,
    # stop at the higher of the contraction low and pivot - 8%
    assert row["trigger_price"] == pytest.approx(110.0)
    assert row["stop"] == pytest.approx(110.0 * 0.92, abs=1.5)
    assert "50% of a" in row["note"]
    assert row["detail"]["target_qty"] > row["qty"]              # half now, full as the target


def test_an_earnings_blackout_blocks_an_entry_without_deleting_it(db, fx):
    """§3.3. The row still exists so R1 can name it as context — 'at its trigger but reporting
    Thursday' is information, not noise."""
    with db.cursor() as cur:
        world.add_name(cur, "BBB.US")
        world.flat_then_base(cur, "BBB.US")
        world.gate(cur)
        world.candidate(cur, "BBB.US", pivot=125.0, stop=115.0)
        world.queued(cur, "BBB.US", trigger=125.0, stop=115.0)
        world.earnings_on(cur, "BBB.US", dt.date.today() + dt.timedelta(days=2))
        world.balances(cur)
    db.commit()
    run()
    row = armed(db, "entry", "BBB.US")[0]
    assert "blackout" in row["blocked_by"]


def test_two_names_in_a_group_blocks_a_third(db, fx):
    """§2.2's hard cap — maximum two names per industry group."""
    with db.cursor() as cur:
        for t in ("AAA.US", "CCC.US"):
            world.add_name(cur, t, industry="Steel")
            world.flat_then_base(cur, t)
            world.position(cur, t, sleeve="momentum", stop=None, cost=90.0, confirmed=True,
                            step=3)
        world.add_name(cur, "BBB.US", industry="Steel")
        world.flat_then_base(cur, "BBB.US")
        world.gate(cur)
        world.candidate(cur, "BBB.US", pivot=125.0, stop=115.0)
        world.queued(cur, "BBB.US", trigger=125.0, stop=115.0)
        world.balances(cur)
    db.commit()
    run()
    row = armed(db, "entry", "BBB.US")[0]
    assert "already 2 names in Steel" in row["blocked_by"]


def test_a_full_sleeve_swaps_when_the_challenger_clears_the_ten_point_margin(db, fx):
    """§3.3 displacement, both legs armed: the weakest incumbent exits, the challenger enters."""
    with db.cursor() as cur:
        for i, t in enumerate(("H1.US", "H2.US", "H3.US", "H4.US")):
            world.add_name(cur, t, industry=f"Group{i}")
            world.flat_then_base(cur, t)
            world.position(cur, t, sleeve="momentum", stop=None, qty=200, cost=90.0,
                            confirmed=True, step=3)
            world.candidate(cur, t, mcn=60.0 + i, rank=10 + i)       # H1 weakest at 60
        world.add_name(cur, "BBB.US", industry="Fresh")
        world.flat_then_base(cur, "BBB.US")
        world.gate(cur)
        world.candidate(cur, "BBB.US", mcn=85.0, pivot=125.0, stop=115.0, rank=1)
        world.queued(cur, "BBB.US", trigger=125.0, stop=115.0, mcn=85.0)
        world.balances(cur)
    db.commit()
    run()
    swap = [r for r in armed(db, "exit") if r["reason"] == "swap"]
    assert len(swap) == 1 and swap[0]["ticker"] == "H1.US"
    assert armed(db, "entry", "BBB.US")[0]["blocked_by"] is None


def test_a_full_sleeve_with_no_weak_incumbent_blocks_instead(db, fx):
    with db.cursor() as cur:
        for i, t in enumerate(("H1.US", "H2.US", "H3.US", "H4.US")):
            world.add_name(cur, t, industry=f"Group{i}")
            world.flat_then_base(cur, t)
            world.position(cur, t, sleeve="momentum", stop=None, qty=200, cost=90.0,
                            confirmed=True, step=3)
            world.candidate(cur, t, mcn=84.0, rank=10 + i)
        world.add_name(cur, "BBB.US", industry="Fresh")
        world.flat_then_base(cur, "BBB.US")
        world.gate(cur)
        world.candidate(cur, "BBB.US", mcn=85.0, pivot=125.0, stop=115.0, rank=1)
        world.queued(cur, "BBB.US", trigger=125.0, stop=115.0, mcn=85.0)
        world.balances(cur)
    db.commit()
    run()
    assert [r for r in armed(db, "exit") if r["reason"] == "swap"] == []
    assert "no incumbent is 10 points weaker" in armed(db, "entry", "BBB.US")[0]["blocked_by"]


def test_no_entry_is_armed_while_the_gate_is_off(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "BBB.US")
        world.flat_then_base(cur, "BBB.US")
        world.gate(cur, "OFF")
        world.candidate(cur, "BBB.US", pivot=125.0, stop=115.0)
        world.queued(cur, "BBB.US", trigger=125.0, stop=115.0)
        world.balances(cur)
    db.commit()
    run()
    assert armed(db, "entry") == []


# --------------------------------------------------------------------------- housekeeping

def test_a_blackout_cancels_a_live_entry_order_and_says_stops_remain(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur)
        world.ticket(cur, "AAA.US", state="approved", trigger=110.0)
        world.earnings_on(cur, "AAA.US", dt.date.today() + dt.timedelta(days=1))
        world.balances(cur)
    db.commit()
    run()
    row = armed(db, "cancel", "AAA.US")[0]
    assert row["urgency"] == "protective"
    assert "protective stops remain" in row["note"]


def test_the_brief_records_effective_bets_and_flags_a_concentrated_book(db, fx):
    """§2.2: printed on every draft ticket, warned below 4, and never a blocker."""
    with db.cursor() as cur:
        for t in ("AAA.US", "CCC.US"):
            world.add_name(cur, t, industry=f"G{t}")
            world.flat_then_base(cur, t, wobble=0.03)      # identical series → perfectly correlated
            world.position(cur, t, sleeve="momentum", stop=None, cost=90.0, confirmed=True,
                            step=3)
        world.gate(cur)
        world.balances(cur)
    db.commit()
    run()
    with db.cursor() as cur:
        cur.execute("""select freshness, summary, detail from briefs where kind='nightly'
                       order by id desc limit 1""")
        freshness, summary, detail = cur.fetchone()
    assert detail["effective_bets"] == pytest.approx(1.0, abs=0.05)   # two identical names = 1 bet
    assert detail["effective_bets_warn"] is True
    assert freshness


def test_a_stalled_pyramid_completes_on_a_new_base_rather_than_exiting(db, fx):
    """§3.2: it 'either completes on the next base or exits'. With a valid base, completion wins."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", last_close=100.0)
        world.gate(cur)
        world.position(cur, "AAA.US", step=1, target=200, qty=100, confirmed=True, stop=90.0,
                    stalled_days_ago=40, opened_days_ago=40)
        world.candidate(cur, "AAA.US", state="BUY", pivot=110.0, stop=101.2, mcn=75.0)
        world.balances(cur)
    db.commit()
    run()
    stall_add = [r for r in armed(db, "add", "AAA.US") if r["reason"] == "stall"]
    assert len(stall_add) == 1 and stall_add[0]["qty"] == pytest.approx(100.0)   # 200 target - 100
    assert [r for r in armed(db, "exit", "AAA.US") if r["reason"] == "stall"] == []


def test_a_stalled_pyramid_with_no_base_exits(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        # a close above the pivot spends the base (§3.2), so there is nothing to complete on
        world.flat_then_base(cur, "AAA.US", last_close=115.0)
        world.gate(cur)
        world.position(cur, "AAA.US", step=1, target=200, qty=100, confirmed=True, stop=90.0,
                    stalled_days_ago=40, opened_days_ago=40)
        world.candidate(cur, "AAA.US", state="WAIT", pivot=None, stop=None, mcn=75.0)
        world.balances(cur)
    db.commit()
    run()
    assert [r for r in armed(db, "exit", "AAA.US") if r["reason"] == "stall"]


def test_stale_bars_suppress_entries_but_never_protection(db, fx):
    """§4.7's law, and the one that most needs a test: stale data ⇒ no new tickets, protective
    moves only. The brief still sends — silence is the alarm."""
    old = world.trading_days(n=300, end=dt.date.today() - dt.timedelta(days=10))
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", days=old, last_close=100.0, last_low=99.0)
        world.gate(cur)
        world.position(cur, "AAA.US", stop=101.2)
        world.add_name(cur, "BBB.US")
        world.flat_then_base(cur, "BBB.US", days=old)
        world.candidate(cur, "BBB.US", pivot=125.0, stop=115.0)
        world.queued(cur, "BBB.US", trigger=125.0, stop=115.0)
        world.balances(cur)
    db.commit()
    run()
    with db.cursor() as cur:
        cur.execute("""select freshness, detail from briefs where kind='nightly'
                       order by id desc limit 1""")
        freshness, detail = cur.fetchone()
    assert "stale" in freshness and detail["tickets_allowed"] is False
    assert [r for r in armed(db, "exit", "AAA.US") if r["urgency"] == "protective"]


# --------------------------------------------------------------------------- compounders (§3.1)

def bench_row(cur, ticker, *, ccn=80.0, hurdle=100.0, last_close=95.0, approved=True,
              confidence="full"):
    cur.execute("""insert into bench (ticker,rank,cohort,ccn,c1_pass,hurdle_price,last_close,
                                      gap_to_hurdle,approved,data_confidence)
                   values (%s,1,'large',%s,true,%s,%s,%s,%s,%s)""",
                (ticker, ccn, hurdle, last_close, (last_close - hurdle) / hurdle, approved,
                 confidence))


def test_an_unapproved_bench_name_at_its_hurdle_arms_nothing(db, fx):
    """§3.1: nothing joins the bench without Zak's ruling, so nothing is bought on it either.
    This is why the compounder sleeve reads zero until the first R5 — by design, not by accident."""
    with db.cursor() as cur:
        world.add_name(cur, "CMP.US")
        world.flat_then_base(cur, "CMP.US", level=95.0)
        world.gate(cur)
        bench_row(cur, "CMP.US", approved=False)
        world.balances(cur)
    db.commit()
    run()
    assert armed(db, "entry", "CMP.US") == []


def test_an_approved_name_below_its_hurdle_arms_a_full_size_entry(db, fx):
    """Compounders enter at full size in a single order (§3.1) — no pyramid, no half position.

    The order is a **GTC buy limit at the hurdle**, not a day limit at the last close: it fills
    anywhere at or below the hurdle, waits above it, and is cancelled and replaced only when a
    filing moves the hurdle. A day limit could expire while the name sat below it all week.
    """
    with db.cursor() as cur:
        world.add_name(cur, "CMP.US")
        world.flat_then_base(cur, "CMP.US", level=95.0)
        world.gate(cur)
        bench_row(cur, "CMP.US", ccn=82.0, hurdle=100.0, last_close=95.0)
        world.balances(cur)
    db.commit()
    run()
    row = armed(db, "entry", "CMP.US")[0]
    assert row["sleeve"] == "compounders" and row["blocked_by"] is None
    assert row["size_pct"] == pytest.approx(0.12)        # §3.1 flat 12% until an R5 ruling
    assert row["order_type"] == "gtc_limit"
    assert row["limit_price"] == pytest.approx(100.0)    # the hurdle, not the quote
    assert row["account"] in ("TFSA", "RRSP")            # §2.6 chose one that can fund it whole
    assert row["currency"] == "USD" and row["fx_estimate"] is not None


def test_a_partially_scored_compounder_needs_manual_sign_off(db, fx):
    """§3.3: an incompletely-scored name is capped at the bottom of its band and requires manual
    sign-off. It must not arm as an ordinary entry."""
    with db.cursor() as cur:
        world.add_name(cur, "CMP.US")
        world.flat_then_base(cur, "CMP.US", level=95.0)
        world.gate(cur)
        bench_row(cur, "CMP.US", confidence="2of3")
        world.balances(cur)
    db.commit()
    run()
    assert "sign-off" in armed(db, "entry", "CMP.US")[0]["blocked_by"]


def test_a_held_compounder_ten_percent_below_hurdle_arms_a_half_size_add(db, fx):
    """§3.1's averaging-down tiers: 5-15% below the hurdle adds 50% of original size."""
    with db.cursor() as cur:
        world.add_name(cur, "CMP.US")
        world.flat_then_base(cur, "CMP.US", level=90.0)
        world.gate(cur)
        bench_row(cur, "CMP.US", ccn=80.0, hurdle=100.0, last_close=90.0)
        world.position(cur, "CMP.US", sleeve="compounders", account="RRSP", qty=100, cost=100.0,
                       stop=None, step=0, pivot=None, target=None, opened_days_ago=200)
        world.balances(cur)
    db.commit()
    run()
    add = armed(db, "add", "CMP.US")[0]
    assert add["sleeve"] == "compounders"
    assert add["size_pct"] == pytest.approx(0.06)         # 50% of a 12% position
    assert "50% of original size" in add["note"]


def test_a_compounder_twenty_percent_below_hurdle_adds_a_full_size(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "CMP.US")
        world.flat_then_base(cur, "CMP.US", level=80.0)
        world.gate(cur)
        bench_row(cur, "CMP.US", ccn=80.0, hurdle=100.0, last_close=80.0)
        world.position(cur, "CMP.US", sleeve="compounders", account="RRSP", qty=100, cost=100.0,
                       stop=None, step=0, pivot=None, target=None, opened_days_ago=200)
        world.balances(cur)
    db.commit()
    run()
    assert armed(db, "add", "CMP.US")[0]["size_pct"] == pytest.approx(0.12)


def test_a_compounder_carries_no_stop_and_no_trail(db, fx):
    """§3.1: no trailing stops, no market gate — weakness is the opportunity."""
    with db.cursor() as cur:
        world.add_name(cur, "CMP.US")
        world.flat_then_base(cur, "CMP.US", level=95.0, last_close=70.0)   # deeply down
        world.gate(cur, "OFF")                                             # and the gate is shut
        world.position(cur, "CMP.US", sleeve="compounders", qty=100, cost=100.0, stop=None,
                       step=0, pivot=None, target=None)
        world.balances(cur)
    db.commit()
    run()
    assert armed(db, "stop_move", "CMP.US") == []
    assert [r for r in armed(db, "exit", "CMP.US") if r["reason"] == "gate_off"] == []


# --------------------------------------------------------------------------- earnings (§3.3)

def test_a_momentum_position_without_the_cushion_exits_before_its_print(db, fx):
    """§3.3: it holds through only at 1.08x average cost — one full stop-width of profit."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", level=103.0, last_close=103.0)   # +3% on a 100 cost
        world.gate(cur)
        world.position(cur, "AAA.US", cost=100.0, stop=90.0, confirmed=True, step=3)
        world.earnings_on(cur, "AAA.US", dt.date.today() + dt.timedelta(days=1))
        world.balances(cur)
    db.commit()
    run()
    row = [r for r in armed(db, "exit", "AAA.US") if r["reason"] == "earnings"]
    assert len(row) == 1 and "cushion" in row[0]["note"]


def test_a_momentum_position_with_the_cushion_holds_through(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", level=112.0, last_close=112.0)   # +12%
        world.gate(cur)
        world.position(cur, "AAA.US", cost=100.0, stop=90.0, confirmed=True, step=3)
        world.earnings_on(cur, "AAA.US", dt.date.today() + dt.timedelta(days=1))
        world.balances(cur)
    db.commit()
    run()
    assert [r for r in armed(db, "exit", "AAA.US") if r["reason"] == "earnings"] == []


# --------------------------------------------------------------------------- §2.3 the hard caps

def test_a_position_that_would_exceed_the_single_name_cap_is_blocked(db, fx):
    """§2.3's 25% ceiling, entry-only. Config seeded it long ago; nothing read it until now."""
    with db.cursor() as cur:
        world.add_name(cur, "BBB.US")
        world.flat_then_base(cur, "BBB.US")
        world.gate(cur)
        world.candidate(cur, "BBB.US", mcn=90.0)
        world.queued(cur, "BBB.US", trigger=110.0, stop=109.9, mcn=90.0)   # a 0.1% stop
        world.balances(cur)
        cur.execute("""insert into config (key,value,note,set_by)
                       values ('single_name_entry_cap','0.05','test override','test')""")
    db.commit()
    run()
    assert "single-name entry cap" in armed(db, "entry", "BBB.US")[0]["blocked_by"]


# --------------------------------------------------------------------------- §4.1 quarantine

def test_a_suspicious_print_blocks_the_exit_it_would_have_fired(db, fx, monkeypatch):
    """§4.1's whole purpose: a bad tick must not sell a real position. The stop is breached by a
    −45% print with no corporate action behind it, and the second source disagrees."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", level=100.0, last_close=55.0, last_low=54.0,
                             last_open=56.0)
        world.gate(cur)
        world.position(cur, "AAA.US", cost=100.0, stop=95.0, confirmed=True, step=3)
        world.balances(cur)
    db.commit()
    quarantine(db, monkeypatch, lambda path, calls, **kw: {"close": 100.0})
    run()
    assert [r for r in armed(db, "exit", "AAA.US") if r["reason"] == "stop"] == []
    check = [r for r in armed(db, "check", "AAA.US") if r["reason"] == "quarantine"]
    assert len(check) == 1 and check[0]["urgency"] == "protective"
    assert "broker stop stands" in check[0]["note"]
    with db.cursor() as cur:
        cur.execute("select status, second_source from quarantine where ticker='AAA.US'")
        status, second = cur.fetchone()
    assert status == "cleared" and second == pytest.approx(100.0)   # sources disagreed


def test_a_verified_print_confirms_and_stops_blocking(db, fx, monkeypatch):
    """When the live quote agrees, the move was real — the print is confirmed and trading resumes
    on it the next night."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", level=100.0, last_close=55.0, last_low=54.0)
        world.gate(cur)
        world.position(cur, "AAA.US", cost=100.0, stop=95.0, confirmed=True, step=3)
        world.balances(cur)
    db.commit()
    quarantine(db, monkeypatch, lambda path, calls, **kw: {"close": 55.0})
    run()
    with db.cursor() as cur:
        cur.execute("select status from quarantine where ticker='AAA.US'")
        assert cur.fetchone()[0] == "confirmed"


def test_a_corporate_action_explains_the_move_and_raises_nothing(db, fx, monkeypatch):
    """A 4:1 split reads as −75%. With the split logged, that is arithmetic, not a bad tick — and
    §4.1 says the quarantine trigger is a big move *with no corporate action*."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        days = world.flat_then_base(cur, "AAA.US", level=100.0, last_close=25.0, last_low=24.0)
        world.gate(cur)
        world.position(cur, "AAA.US", cost=100.0, stop=95.0, pivot=110.0, qty=100, target=200,
                       confirmed=True, step=3)
        cur.execute("""insert into corporate_actions (ticker,d,kind,detail)
                       values ('AAA.US',%s,'split','{"split":"4.000000/1.000000"}')""", (days[-1],))
        world.balances(cur)
    db.commit()
    quarantine(db, monkeypatch, lambda path, calls, **kw: {"close": 25.0})
    run()
    with db.cursor() as cur:
        cur.execute("select count(*) from quarantine where ticker='AAA.US' and reason='move'")
        assert cur.fetchone()[0] == 0          # the split explains the move; it is not a bad tick
    # and the position's own numbers were re-based, or its stop would sit 4x above the market
    row = book_row(db, "AAA.US")
    assert row["qty"] == pytest.approx(400)
    assert row["avg_cost"] == pytest.approx(25.0)
    assert row["pivot"] == pytest.approx(27.5)
    assert row["target_qty"] == pytest.approx(800)


def test_a_split_is_re_based_only_once(db, fx, monkeypatch):
    """The marker on the action makes it idempotent; without it every night would divide again."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        days = world.flat_then_base(cur, "AAA.US", level=100.0, last_close=25.0)
        world.gate(cur)
        world.position(cur, "AAA.US", cost=100.0, stop=95.0, qty=100, confirmed=True, step=3)
        cur.execute("""insert into corporate_actions (ticker,d,kind,detail)
                       values ('AAA.US',%s,'split','{"split":"4.000000/1.000000"}')""", (days[-1],))
        world.balances(cur)
    db.commit()
    quarantine(db, monkeypatch, lambda path, calls, **kw: {"close": 25.0})
    run()
    run()
    assert book_row(db, "AAA.US")["avg_cost"] == pytest.approx(25.0)


def test_an_unparseable_split_leaves_the_position_alone_and_shouts(db, fx, monkeypatch):
    """Guessing a ratio is worse than not adjusting: it would silently corrupt the cost basis."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        days = world.flat_then_base(cur, "AAA.US", level=100.0, last_close=25.0)
        world.gate(cur)
        world.position(cur, "AAA.US", cost=100.0, stop=95.0, qty=100, confirmed=True, step=3)
        cur.execute("""insert into corporate_actions (ticker,d,kind,detail)
                       values ('AAA.US',%s,'split','{"split":"nonsense"}')""", (days[-1],))
        world.balances(cur)
    db.commit()
    quarantine(db, monkeypatch, lambda path, calls, **kw: {"close": 25.0})
    run()
    assert book_row(db, "AAA.US")["avg_cost"] == pytest.approx(100.0)
    with db.cursor() as cur:
        cur.execute("""select detail->'amber' from runs where job='score' order by id desc limit 1""")
        assert "NOT re-based" in str(cur.fetchone()[0])


def test_an_unverifiable_print_stays_held_rather_than_trading(db, fx, monkeypatch):
    """If the second source cannot be reached, the print stays quarantined. Silence is not
    agreement — §4.1 needs two sources, and one source plus an outage is one source."""
    def boom(path, calls, **kw):
        raise RuntimeError("vendor unreachable")
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", level=100.0, last_close=55.0, last_low=54.0)
        world.gate(cur)
        world.position(cur, "AAA.US", cost=100.0, stop=95.0, confirmed=True, step=3)
        world.balances(cur)
    db.commit()
    quarantine(db, monkeypatch, boom)
    run()
    with db.cursor() as cur:
        cur.execute("select status from quarantine where ticker='AAA.US'")
        assert cur.fetchone()[0] == "held"
    assert [r for r in armed(db, "exit", "AAA.US") if r["reason"] == "stop"] == []


# --------------------------------------------------------------------------- §3.3 shadow book

def test_a_blocked_entry_is_recorded_as_a_pass(db, fx):
    """§3.3: every pass snapshots score and price. A name the machine wanted and a rule held back
    is exactly a pass — and it is the only way we will ever learn whether the rule cost us."""
    with db.cursor() as cur:
        world.add_name(cur, "BBB.US")
        world.flat_then_base(cur, "BBB.US")
        world.gate(cur)
        world.candidate(cur, "BBB.US", mcn=82.0)
        world.queued(cur, "BBB.US", trigger=110.0, stop=101.2, mcn=82.0)
        world.earnings_on(cur, "BBB.US", dt.date.today() + dt.timedelta(days=1))   # blackout
        world.balances(cur)
    db.commit()
    run()
    with db.cursor() as cur:
        cur.execute("""select kind, ticker, score, price, detail->>'blocked_by'
                       from observations where kind='pass'""")
        rows = cur.fetchall()
    assert len(rows) == 1
    kind, tk, score, price, blocked = rows[0]
    assert tk == "BBB.US" and score == pytest.approx(82.0) and price is not None
    assert "blackout" in blocked


def test_a_taken_entry_is_not_a_pass(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "BBB.US")
        world.flat_then_base(cur, "BBB.US")
        world.gate(cur)
        world.candidate(cur, "BBB.US", mcn=82.0)
        world.queued(cur, "BBB.US", trigger=110.0, stop=101.2, mcn=82.0)
        world.balances(cur)
    db.commit()
    run()
    with db.cursor() as cur:
        cur.execute("select count(*) from observations where kind='pass'")
        assert cur.fetchone()[0] == 0


def test_an_exit_is_recorded_in_the_shadow_book(db, fx):
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", last_close=100.0, last_low=99.0)
        world.gate(cur)
        world.position(cur, "AAA.US", stop=101.2, confirmed=True, step=3, cost=105.0)
        world.balances(cur)
    db.commit()
    run()
    with db.cursor() as cur:
        cur.execute("select ticker, price from observations where kind='exit'")
        rows = cur.fetchall()
    assert len(rows) == 1 and rows[0][0] == "AAA.US"


def test_the_same_pass_is_recorded_once_a_day_not_once_a_run(db, fx):
    """The nightly job re-arms the same conclusion every night a rule keeps holding. Sixty identical
    rows would drown the marks that make the shadow book worth keeping."""
    with db.cursor() as cur:
        world.add_name(cur, "BBB.US")
        world.flat_then_base(cur, "BBB.US")
        world.gate(cur)
        world.candidate(cur, "BBB.US", mcn=82.0)
        world.queued(cur, "BBB.US", trigger=110.0, stop=101.2, mcn=82.0)
        world.earnings_on(cur, "BBB.US", dt.date.today() + dt.timedelta(days=1))
        world.balances(cur)
    db.commit()
    run()
    run()
    with db.cursor() as cur:
        cur.execute("select count(*) from observations where kind='pass'")
        assert cur.fetchone()[0] == 1


def test_a_pass_gets_its_thirty_day_mark_when_the_anniversary_arrives(db, fx):
    """The mark is the whole point: a score and a price at decision time are worthless until you
    know what happened next."""
    with db.cursor() as cur:
        world.add_name(cur, "BBB.US")
        days = world.flat_then_base(cur, "BBB.US", level=100.0)
        world.gate(cur)
        world.balances(cur)
        # a pass recorded 40 days ago, with bars covering the 30-day anniversary
        cur.execute("""insert into observations (kind, ticker, score, price, body, at)
                       values ('pass','BBB.US',80,100.0,'test pass', now() - interval '40 days')""")
    db.commit()
    run()
    with db.cursor() as cur:
        cur.execute("select mark_30, mark_60, marked_at from observations where kind='pass'")
        mark_30, mark_60, marked_at = cur.fetchone()
    assert mark_30 is not None and marked_at is not None
    assert mark_60 is None                    # not yet due


def test_one_name_one_score_across_candidates_and_queue(db, fx):
    """Dev-fix 6, pinned: NUE was written at 77.0 in `candidates` and 63.9 in `queue` in the same
    run. The queue COPIES the candidate score; it never recomputes. Nothing else can be true of a
    single name in a single run, and only a test keeps it that way."""
    with db.cursor() as cur:
        cur.execute("""select c.ticker, c.mcn, q.mcn from candidates c
                       join queue q on q.ticker = c.ticker
                       where c.mcn is not null and q.mcn is not null""")
        disagree = [(t, float(a), float(b)) for t, a, b in cur.fetchall()
                    if abs(float(a) - float(b)) > 1e-9]
    assert not disagree, f"one name carrying two scores in one run: {disagree}"


def test_a_below_seventy_name_never_arms_an_entry(db, fx):
    """§3.2: 'MCN < 70 never tickets — BUY-state names below 70 stay queued.' Not blocked_by, which
    still prints a row the session must reason about. Production armed RS at 63.9."""
    with db.cursor() as cur:
        world.add_name(cur, "WEAK.US")
        world.flat_then_base(cur, "WEAK.US")
        world.gate(cur)
        world.queued(cur, "WEAK.US", mcn=63.9)
        world.balances(cur)
    db.commit()
    run()
    assert armed(db, "entry", "WEAK.US") == []


def test_a_holding_outside_l0_is_still_scored(db, fx):
    """§3.0: 'Holdings are always scored, by both pipelines — membership lists never drop a name the
    book owns.' The L0 bar filters decide membership, not scoreability.

    CNQ.TO is the live case: a TSX listing, in_l0=false by the US-exchange rule, 754 bars of good
    history — and it carried a NULL MCN into every queue and every brief because the ranker dropped
    it before computing a single component. A dev-fix item confirmed at source and then missed.
    """
    import rank
    with db.cursor() as cur:
        world.add_name(cur, "FOREIGN.TO")
        cur.execute("update universe set in_l0=false, is_holding=true where ticker='FOREIGN.TO'")
        world.flat_then_base(cur, "FOREIGN.TO")
        world.position(cur, "FOREIGN.TO", sleeve="levered", account="NONREG", qty=100)
        world.gate(cur)
    db.commit()

    meta = {"FOREIGN.TO": dict(industry="Oil & Gas E&P", hold=True, l0=False)}
    with db.cursor() as cur:
        data = rank.load_bars(cur)
    feats = rank.features({k: v for k, v in data.items() if k == "FOREIGN.TO"}, meta)
    assert feats["FOREIGN.TO"]["eff"] is False, "fixture must be outside L0 for this test to mean anything"

    scored = [t for t, f in feats.items() if f["scoreable"] and (f["eff"] or meta[t]["hold"])]
    assert "FOREIGN.TO" in scored, "a holding outside L0 must still be scored (§3.0)"
