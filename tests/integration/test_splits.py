"""A split on a held name, through the ledger (migration 075, Zak's ruling of 2026-10-07).

Zak chose "Pipeline records splits" on 2026-10-07: a vendor-reported split on a held name is
written to the ledger, quantity only and no cash, before score runs, and the brief shows it; ticker
changes and takeovers still fail closed until he records them.

The doctrine (`market-mechanics`): "Split / reverse split — share count and per-share cost base
change; total cost base does not." Every test below is that sentence, or the QC finding it closes:

  A1   after a split every exit sold the pre-split count
  A2   derived engine NAV marked the pre-split count at the post-split close
  A21  the true post-split sale was refused by the ledger, every night
  A32  a reverse split stored an inflated marked equity, and the running peak kept it

Hand-built tapes, deliberately: `market-mechanics` warns that "hand-built fixtures never contain a
split" — so each of these contains one, the way the vendor and the tape carry it: the raw print
restated on the ex-date by the ratio, and the vendor's adjusted history restated before it.
"""
import datetime as dt
import json
import pathlib
import subprocess
import sys

import psycopg
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import db as dbm                                                          # noqa: E402
import desk                                                               # noqa: E402
import engine                                                             # noqa: E402
import fixtures as world                                                  # noqa: E402
import gauges                                                             # noqa: E402
import ledger                                                             # noqa: E402
import sheet                                                              # noqa: E402
from test_desk import _world                                              # noqa: E402

D = dt.date


def _name(cur, ticker, currency="USD"):
    cur.execute("""insert into universe (ticker,name,kind,currency,status)
                   values (%s,%s,'stock',%s,'active') on conflict (ticker) do nothing""",
                (ticker, ticker.split(".")[0], currency))


def _row(cur, ticker, side, qty, price, when, *, account="TFSA", currency="USD",
         grade="broker"):
    """One ledger row, already applied — the way a broker export or Zak's word lands."""
    cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                             trade_date, confirmed, confirmed_at, applied_at,
                                             grade, source)
                   values (%s,%s,%s,%s,%s,%s,%s,true,now(),now(),%s,'test') returning id""",
                (ticker, account, side, qty, price, currency, when, grade))
    return cur.fetchone()[0]


def _tape(cur, ticker, closes):
    """Raw prints, {date: close}; the adjusted close starts equal to the print."""
    for d, c in closes.items():
        cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                       values (%s,%s,%s,%s,%s,%s,%s,1000000)
                       on conflict (ticker,d) do update set close = excluded.close,
                         adj_close = excluded.adj_close""",
                    (ticker, d, c, c, c, c, c))


def _split(cur, ticker, d, text):
    """The row `ingest` writes from the vendor's bulk splits file — production's own shape."""
    cur.execute("""insert into corporate_actions (ticker, d, kind, detail)
                   values (%s, %s, 'split', %s)""",
                (ticker, d, json.dumps({"code": ticker.split(".")[0], "date": str(d),
                                        "split": text, "exchange": "US"})))


def _book(cur, ticker, account="TFSA"):
    cur.execute("""select qty, avg_cost, status from book
                    where ticker = %s and account = %s order by id desc limit 1""",
                (ticker, account))
    return cur.fetchone()


def _splits(cur, ticker=None):
    cur.execute("""select account, ticker, qty, trade_date from transactions
                    where side = 'split' and (%s::text is null or ticker = %s)
                    order by account, ticker, trade_date""", (ticker, ticker))
    return cur.fetchall()


def _reconcile(migrated, tmp_path, **env):
    """The job as `pipeline.yml` runs it, before `score`, on a night with no manifest."""
    return subprocess.run([sys.executable, str(ROOT / "src" / "reconcile.py")],
                          capture_output=True, text=True,
                          env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                               "RECONCILE_GLOB": str(tmp_path / "*.json"),
                               "PATH": "/usr/bin:/bin", **env})


def _newest_run(db):
    with db.cursor() as cur:
        cur.execute("""select status, detail from runs where job = 'reconcile'
                        order by id desc limit 1""")
        return cur.fetchone()


def _restate(cur, ticker, ex_date, ratio):
    """The vendor's half of a split: the print on and after the ex-date is the old price / ratio
    with no market move, and the adjusted history before it is restated the same way."""
    cur.execute("select close from prices where ticker = %s and d < %s order by d desc limit 1",
                (ticker, ex_date))
    was = float(cur.fetchone()[0])
    cur.execute("update prices set adj_close = close / %s where ticker = %s and d < %s",
                (ratio, ticker, ex_date))
    cur.execute("""update prices set open = %(p)s, high = %(p)s, low = %(p)s, close = %(p)s,
                          adj_close = %(p)s
                    where ticker = %(t)s and d >= %(d)s""",
                dict(p=was / ratio, t=ticker, d=ex_date))
    return was


def _held_through_a_split(cur, ticker="N01.US", *, ratio_text="2.000000/1.000000", ratio=2.0,
                          account="TFSA", currency="USD", bought=D(2026, 8, 3), qty=100,
                          price=40.0, ex=D(2026, 8, 14)):
    """A held name, its tape through a split on `ex` (the print restated by the ratio, no market
    move), and the vendor's row for the split."""
    _name(cur, ticker, currency)
    _tape(cur, ticker, {D(2026, 8, 3): 40.0, D(2026, 8, 12): 44.0, D(2026, 8, 13): 46.0,
                        ex: 46.0 / ratio, ex + dt.timedelta(days=1): 47.0 / ratio})
    _row(cur, ticker, "buy", qty, price, bought, account=account, currency=currency)
    _split(cur, ticker, ex, ratio_text)


# ---------------------------------------------------------------- the ledger's arithmetic

def test_a_split_row_restates_the_shares_and_carries_the_cost_with_sells_before_it(db):
    """Why `split` is a verb of its own (075). A `confirm +60 @ 0` would get the shares right and
    the cost wrong, because the average is over everything ever bought: buy 100 @ 50, sell 40, then
    2:1 — the 60 held become 120 at 25.00, where a +60 confirm averages 5,000 / 160 = 31.25. A row
    after the split is already in the new shares and is not restated."""
    with db.cursor() as cur:
        _name(cur, "N01.US")
        _row(cur, "N01.US", "buy", 100, 50.0, D(2026, 8, 3))
        _row(cur, "N01.US", "sell", 40, 55.0, D(2026, 8, 5))
        _row(cur, "N01.US", "split", 2.0, 0, D(2026, 8, 10), grade="stated")
        db.commit()
        assert _book(cur, "N01.US") == (120.0, 25.0, "open"), "shares x2, cost/share /2"

        _row(cur, "N01.US", "buy", 30, 26.0, D(2026, 8, 12))      # post-split shares, not restated
        db.commit()
        assert _book(cur, "N01.US")[0] == 150.0
        assert _book(cur, "N01.US")[1] == pytest.approx((5000.0 + 780.0) / 230.0)

        cur.execute("select count(*) from v_ledger_vs_book")
        assert cur.fetchone()[0] == 0, "the view says what the function says"
        cur.execute("select qty, avg_buy_price from v_ledger_positions where ticker = 'N01.US'")
        assert cur.fetchone() == (150.0, pytest.approx((5000.0 + 780.0) / 230.0))
        assert ledger.rebuild_book(cur) == [], "and the sweep finds nothing to repair"


def test_a_reverse_split_row_restates_the_shares_and_the_cost_the_other_way(db):
    """The direction a `confirm` cannot express at all: buy 100 @ 50, sell 90, then 1:10 — the 10
    held become 1 at 500.00. A `confirm -9 @ 0` would average 5,000 / 91 = 54.95. A later split
    compounds on the restated rows: a 4:1 after it makes the 1 @ 500 into 4 @ 125."""
    with db.cursor() as cur:
        _name(cur, "N02.US")
        _row(cur, "N02.US", "buy", 100, 50.0, D(2026, 8, 3))
        _row(cur, "N02.US", "sell", 90, 40.0, D(2026, 8, 5))
        _row(cur, "N02.US", "split", 0.1, 0, D(2026, 8, 10), grade="stated")
        db.commit()
        qty, avg, status = _book(cur, "N02.US")
        assert (qty, status) == (pytest.approx(1.0), "open")
        assert avg == pytest.approx(500.0)

        _row(cur, "N02.US", "split", 4.0, 0, D(2026, 8, 20), grade="stated")
        db.commit()
        qty, avg, _ = _book(cur, "N02.US")
        assert qty == pytest.approx(4.0) and avg == pytest.approx(125.0), "1 @ 500 -> 4 @ 125"


def test_a_split_moves_no_cash(db):
    """Zak's ruling: "(no cash)". `db.cash_by_account` moves cash on buy and sell only; a split
    after the anchor leaves the account's cash exactly where the buy left it."""
    with db.cursor() as cur:
        _name(cur, "N01.US")
        cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source)
                       values ('TFSA', '2026-08-01', 0, 10000, 'test')""")
        _row(cur, "N01.US", "buy", 100, 40.0, D(2026, 8, 3))
        db.commit()
        before = dbm.cash_by_account(cur)["TFSA"]
        _row(cur, "N01.US", "split", 2.0, 0, D(2026, 8, 10), grade="stated")
        db.commit()
        after = dbm.cash_by_account(cur)["TFSA"]
    assert before["usd"] == pytest.approx(6000.0)
    assert after["usd"] == before["usd"] and after["cad"] == before["cad"]
    assert after["moved_since_anchor"] == before["moved_since_anchor"]


def test_a_split_row_has_one_shape_and_one_row_per_position_per_date(db):
    """The ratio is positive, finite and not 1, the price is 0, and a position carries one split row
    per date EVER — a re-run collides instead of squaring the ratio."""
    with db.cursor() as cur:
        _name(cur, "N01.US")
        _row(cur, "N01.US", "buy", 100, 40.0, D(2026, 8, 3))
        _row(cur, "N01.US", "split", 2.0, 0, D(2026, 8, 10), grade="stated")
        db.commit()
        for qty, price in ((1.0, 0), (-2.0, 0), (float("nan"), 0), (float("inf"), 0), (2.0, 5.0)):
            cur.execute("savepoint shape")
            with pytest.raises(psycopg.errors.CheckViolation):
                _row(cur, "N01.US", "split", qty, price, D(2026, 8, 11), grade="stated")
            cur.execute("rollback to savepoint shape")
        with pytest.raises(psycopg.errors.UniqueViolation):
            _row(cur, "N01.US", "split", 2.0, 0, D(2026, 8, 10), grade="stated")
    db.rollback()


# ------------------------------------------------------------ reconcile records it, before score

def test_a_forward_split_on_a_held_tfsa_name_doubles_the_book_and_moves_no_nav(db, migrated,
                                                                             tmp_path):
    """A1 and A2, end to end. A 2:1 on a TFSA holding, gated off: the book doubles, the cost per
    share halves, the cash does not move, derived engine NAV marked at the post-split print is the
    NAV of the night before, and the gate-off sheet sells the post-split count — not half of it."""
    with db.cursor() as cur:
        days = _world(cur, rising=False)             # SPY rolls over: the gate reads OFF tonight
        ex, prev = days[-1], days[-2]
        _row(cur, "N01.US", "buy", 100, 40.0, days[-30])
        cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source)
                       values ('TFSA', %s, 0, 5000, 'test')""", (days[-40],))
        db.commit()
        nav_before, _ = desk.derived_engine_nav(cur, prev)
        cash_before = dbm.cash_by_account(cur)["TFSA"]
        was = _restate(cur, "N01.US", ex, 2.0)
        _split(cur, "N01.US", ex, "2.000000/1.000000")
    db.commit()

    out = _reconcile(migrated, tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "SPLIT TFSA N01.US 2:1 split" in out.stdout

    with db.cursor() as cur:
        assert _book(cur, "N01.US") == (200.0, 20.0, "open")
        assert dbm.cash_by_account(cur)["TFSA"]["usd"] == cash_before["usd"]
        nav_after, src = desk.derived_engine_nav(cur, ex)
        assert nav_after == nav_before == 100 * was + 1000.0
        assert src["marked_equity"] == pytest.approx(200 * was / 2)

        s = desk.sheet(cur, ex, nav_after)
        assert s["gate"] == "OFF"
        sells = [(o["ticker"], o["qty"], o["clause"]) for o in s["orders"] if o["action"] == "sell"]
        assert sells == [("N01.US", 200.0, "gate_off")], "the whole post-split position exits"

    status, detail = _newest_run(db)
    assert status == "amber"
    assert detail["splits"]["recorded"] and "100 -> 200 shares" in detail["splits"]["recorded"][0]
    assert any("split(s) recorded in the ledger before score" in a for a in detail["amber"])
    with db.cursor() as cur:
        # "and the brief shows it": the ledger row carries the run's own line, to print as it is
        cur.execute("select note, source, grade from transactions where side = 'split'")
        note, source, grade = cur.fetchone()
    assert note == detail["splits"]["recorded"][0]
    assert "2.000000/1.000000" in source and "2026-10-07" in source and grade == "stated"


def test_a_reverse_split_restates_the_book_and_stores_no_fake_peak(db, migrated, tmp_path):
    """A32, and a 1:10 the other way round from A2. The session scored before the split and the one
    after it mark the same equity, so `v_engine_drawdown`'s running peak never sees the
    ten-times-too-large number the pre-split count at the post-split print would have stored."""
    with db.cursor() as cur:
        days = _world(cur)                             # gate ON
        ex, prev = days[-1], days[-2]
        _row(cur, "N01.US", "buy", 100, 40.0, days[-30])
        cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source)
                       values ('TFSA', %s, 0, 5000, 'test')""", (days[-40],))
        db.commit()
        nav, src = sheet.engine_nav(cur, prev)          # the night before, as the chain scored it
        sheet.write_session(cur, dict(desk.sheet(cur, prev, nav), nav_source=src), "live",
                            engine.digest())
        cash_before = dbm.cash_by_account(cur)["TFSA"]
        was = _restate(cur, "N01.US", ex, 0.1)
        _split(cur, "N01.US", ex, "1.000000/10.000000")
    db.commit()

    out = _reconcile(migrated, tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr

    with db.cursor() as cur:
        qty, avg, status = _book(cur, "N01.US")
        assert (qty, status) == (pytest.approx(10.0), "open")
        assert avg == pytest.approx(400.0), "cost/share x10, total cost unchanged"
        assert dbm.cash_by_account(cur)["TFSA"]["usd"] == cash_before["usd"]

        nav, src = sheet.engine_nav(cur, ex)
        sheet.write_session(cur, dict(desk.sheet(cur, ex, nav), nav_source=src), "live",
                            engine.digest())
        db.commit()
        cur.execute("""select marked_equity, peak, drawdown from v_engine_drawdown
                        order by session_date""")
        (m0, p0, d0), (m1, p1, d1) = cur.fetchall()
    assert m0 == pytest.approx(100 * was)
    assert m1 == pytest.approx(m0), "the split moved no equity"
    assert p1 == pytest.approx(m0) and d1 == pytest.approx(0.0), "no fake peak, no fake drawdown"


def test_the_vendors_awkward_ratios_restate_exactly_in_both_of_its_formats(db, migrated,
                                                                           tmp_path):
    """The two splits the vendor posted in production that `ingest` missed (A4), in the format its
    per-ticker history serves them: CTVA.US "6665/1000" on 2026-10-01 and DCX.US "1/160" on
    2026-09-28 (raw 0.0494 -> 6.17, a day's move on top of the ratio). Held, each restates to the
    ratio's own arithmetic: 26 CTVA become 173.29, 1,000 DCX become 6.25, and neither position's
    total cost moves by a cent."""
    with db.cursor() as cur:
        _name(cur, "CTVA.US")
        _tape(cur, "CTVA.US", {D(2026, 9, 1): 70.0, D(2026, 9, 30): 77.65,
                               D(2026, 10, 1): 77.65 / 6.665})
        _row(cur, "CTVA.US", "buy", 26, 70.0, D(2026, 9, 1))
        _split(cur, "CTVA.US", D(2026, 10, 1), "6665/1000")
        _name(cur, "DCX.US")
        _tape(cur, "DCX.US", {D(2026, 9, 1): 0.06, D(2026, 9, 25): 0.0494, D(2026, 9, 28): 6.17})
        _row(cur, "DCX.US", "buy", 1000, 0.06, D(2026, 9, 1))
        _split(cur, "DCX.US", D(2026, 9, 28), "1/160")
    db.commit()

    out = _reconcile(migrated, tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "SPLIT TFSA CTVA.US 6.665:1 split" in out.stdout
    assert "SPLIT TFSA DCX.US 1:160 split" in out.stdout
    with db.cursor() as cur:
        qty, avg, _ = _book(cur, "CTVA.US")
        assert qty == pytest.approx(26 * 6.665) and qty * avg == pytest.approx(26 * 70.0)
        qty, avg, _ = _book(cur, "DCX.US")
        assert qty == pytest.approx(6.25) and avg == pytest.approx(0.06 * 160)
        assert qty * avg == pytest.approx(1000 * 0.06)
        assert _splits(cur) == [("TFSA", "CTVA.US", 6.665, D(2026, 10, 1)),
                                ("TFSA", "DCX.US", 1 / 160, D(2026, 9, 28))]


def test_a_split_recorded_late_names_the_sessions_already_marked_on_the_old_count(db, migrated,
                                                                                   tmp_path):
    """A32's residual, said out loud. On time — the vendor posts the split on its ex-date night —
    reconcile records it before `score` writes that session, so no session is ever marked on the
    old count. Posted a night late (A4), the ex-date's session was already scored on it, and a
    reverse split's inflated mark is a peak `v_engine_drawdown` keeps. That session's record is
    not rewritten (§0.6); the line that records the split names it."""
    with db.cursor() as cur:
        _held_through_a_split(cur, ratio_text="1.000000/10.000000", ratio=0.1)
        cur.execute("""insert into engine_sessions (session_date, gate_on, gate_green,
                                                    universe_count, ranked_count, marked_equity,
                                                    param_digest, mode)
                       values ('2026-08-14', true, true, 1, 1, 46000, 'test', 'live')""")
    db.commit()
    out = _reconcile(migrated, tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        assert _book(cur, "N01.US")[0] == pytest.approx(10.0)
    status, detail = _newest_run(db)
    assert status == "amber"
    assert ("recorded late: 1 live session(s) 2026-08-14..2026-08-14 were scored on the "
            "pre-split count") in detail["splits"]["recorded"][0]


def test_a_split_reaches_only_the_positions_held_before_its_date(db, migrated, tmp_path):
    """"Dated after the position opened", per position. The same name in two accounts: the TFSA
    bought it before the split and is restated; the RRSP bought it after, in post-split shares, and
    is not. A split dated before ANY purchase restates nothing — and none of these is an error."""
    with db.cursor() as cur:
        _held_through_a_split(cur)
        _row(cur, "N01.US", "buy", 50, 23.5, D(2026, 8, 15), account="RRSP")
        _name(cur, "N03.US")
        _tape(cur, "N03.US", {D(2026, 8, 3): 30.0, D(2026, 8, 4): 15.0, D(2026, 8, 20): 16.0})
        _split(cur, "N03.US", D(2026, 8, 4), "2.000000/1.000000")
        _row(cur, "N03.US", "buy", 10, 16.0, D(2026, 8, 20))
    db.commit()

    out = _reconcile(migrated, tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        assert _book(cur, "N01.US", "TFSA") == (200.0, 20.0, "open")
        assert _book(cur, "N01.US", "RRSP") == (50.0, 23.5, "open"), "bought after: untouched"
        assert _book(cur, "N03.US") == (10.0, 16.0, "open"), "a split before the purchase"
        assert _splits(cur) == [("TFSA", "N01.US", 2.0, D(2026, 8, 14))]
    status, detail = _newest_run(db)
    assert status == "amber" and not detail.get("red")


def test_a_rerun_records_nothing_twice(db, migrated, tmp_path):
    """The chain re-fires on the retry ingest by design, so every night reconciles twice. One split,
    one row, one doubling: the second pass finds the row and has nothing to say — and an amber that
    only says "recorded" holds nothing (§4.3: an `ingest-daily` or `score` amber holds buys)."""
    sessions = world.trading_days(5)
    ex = sessions[-1]
    with db.cursor() as cur:
        _name(cur, "N01.US")
        _tape(cur, "N01.US", {sessions[0]: 40.0, sessions[-2]: 44.0, ex: 22.0})
        _row(cur, "N01.US", "buy", 100, 40.0, sessions[0])
        _split(cur, "N01.US", ex, "2.000000/1.000000")
    db.commit()

    first = _reconcile(migrated, tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    assert _newest_run(db)[0] == "amber"
    line, allowed = dbm.freshness(db)
    assert allowed, line
    assert "reconcile amber (that domain only)" in line, "seen, and holding nothing"
    with db.cursor() as cur:
        assert gauges.reconciliation_age(cur)["status"] != "red"

    second = _reconcile(migrated, tmp_path)
    assert second.returncode == 0, second.stdout + second.stderr
    with db.cursor() as cur:
        assert _book(cur, "N01.US") == (200.0, 20.0, "open"), "doubled once"
        assert _splits(cur) == [("TFSA", "N01.US", 2.0, ex)]
    status, detail = _newest_run(db)
    assert status == "green" and detail["splits"]["recorded"] == []


def test_the_true_post_split_sale_lands_once_the_split_is_recorded(db, migrated, tmp_path):
    """A21's root. Zak sees 200 shares at the broker after a 2:1 and sells all 200 — correctly —
    and the chat writes it on the exit ticket. The split goes into the ledger first, so the sale
    nets against the post-split count and closes the position, the same night, beside an
    unrelated fill; nothing is refused and nothing is red."""
    with db.cursor() as cur:
        _held_through_a_split(cur, price=50.0, bought=D(2026, 8, 10))
        cur.execute("""insert into tickets (session_date, ticker, account, sleeve, action, clause,
                                            order_type, qty, state, fill_qty, fill_price,
                                            fill_date)
                       values ('2026-08-14','N01.US','TFSA','momentum','sell','rank_exit',
                               'market',100,'executed',200,30.0,'2026-08-17')""")
        _name(cur, "N05.US")
        cur.execute("""insert into tickets (session_date, ticker, account, sleeve, action, clause,
                                            order_type, qty, state, fill_qty, fill_price,
                                            fill_date)
                       values ('2026-08-14','N05.US','TFSA','momentum','buy','fill','market',
                               10,'executed',10,20.0,'2026-08-17')""")
    db.commit()

    out = _reconcile(migrated, tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "REFUSED" not in out.stdout
    with db.cursor() as cur:
        assert _book(cur, "N01.US")[::2] == (0.0, "closed"), "the post-split sale closed it"
        assert _book(cur, "N05.US")[::2] == (10.0, "open")
    status, detail = _newest_run(db)
    assert status == "amber", detail
    assert detail["refused"] == [] and len(detail["ticket_fills_derived"]) == 2


def test_a_split_on_a_nonreg_holding_is_recorded_in_that_account(db, migrated, tmp_path):
    """Not only the engine's account. NONREG VXC.TO, both tranches as the ledger holds them (140 @
    85.45 and 139 @ 86.30, CAD), through a 2:1: 558 shares at half the cost, the NONREG's cash
    untouched, and the TFSA's book not involved."""
    with db.cursor() as cur:
        _name(cur, "VXC.TO", "CAD")
        _tape(cur, "VXC.TO", {D(2026, 9, 22): 86.30, D(2026, 10, 5): 88.0, D(2026, 10, 6): 44.1})
        cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source)
                       values ('NONREG', '2026-08-01', 50, 0, 'test')""")
        _row(cur, "VXC.TO", "buy", 140, 85.45, D(2026, 8, 17), account="NONREG", currency="CAD")
        _row(cur, "VXC.TO", "buy", 139, 86.30, D(2026, 9, 22), account="NONREG", currency="CAD")
        _split(cur, "VXC.TO", D(2026, 10, 6), "2.000000/1.000000")
        db.commit()
        cash_before = dbm.cash_by_account(cur)["NONREG"]
        _, avg_before, _ = _book(cur, "VXC.TO", "NONREG")

    out = _reconcile(migrated, tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        qty, avg, status = _book(cur, "VXC.TO", "NONREG")
        assert (qty, status) == (558.0, "open")
        assert avg == pytest.approx(avg_before / 2)
        cash_after = dbm.cash_by_account(cur)["NONREG"]
        assert (cash_after["cad"], cash_after["usd"]) == (cash_before["cad"], cash_before["usd"])
        assert _splits(cur) == [("NONREG", "VXC.TO", 2.0, D(2026, 10, 6))]
        cur.execute("select currency from transactions where side = 'split'")
        assert cur.fetchone()[0] == "CAD"


# ---------------------------------------------------------------- never twice

def test_a_split_already_recorded_by_hand_is_not_recorded_again(db, migrated, tmp_path):
    """"If the ledger already reflects the split, do not apply it again." Zak's ruling words the
    split as a quantity-only confirm, and a session may have written exactly that when he reported
    the post-split count: `confirm +100 @ 0` on the ex-date. That IS the split — recording the
    vendor's too would hold 300. A 1:10 written as `sell 90 @ 0` is the same thing the other way
    (1 share would be the double). A quantity-only row that is not the split's arithmetic is a
    different claim about what the broker holds, and is Zak's to settle: red, named, nothing
    written."""
    with db.cursor() as cur:
        _held_through_a_split(cur)
        by_hand = _row(cur, "N01.US", "confirm", 100, 0, D(2026, 8, 14), grade="stated")
        _held_through_a_split(cur, "N02.US")
        _row(cur, "N02.US", "confirm", 120, 0, D(2026, 8, 15), grade="stated")   # not 100
        # a 1:10 written down the other way: 90 of the 100 shares gone, for no money
        _held_through_a_split(cur, "N03.US", ratio_text="1.000000/10.000000", ratio=0.1)
        _row(cur, "N03.US", "sell", 90, 0, D(2026, 8, 14), grade="stated")
    db.commit()

    out = _reconcile(migrated, tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        assert _book(cur, "N01.US") == (200.0, 20.0, "open"), "200, not 300"
        assert _book(cur, "N02.US")[0] == 220.0, "left exactly as the ledger had it"
        assert _book(cur, "N03.US")[0] == pytest.approx(10.0), "10, not 1"
        assert _splits(cur) == []
    status, detail = _newest_run(db)
    assert status == "red"
    assert [(r["ticker"], r["split"]) for r in detail["refused"]] == [
        ("N02.US", "2:1 split, ex 2026-08-14")]
    assert "not as this split does" in detail["red"][0]
    assert any(f"already in the ledger as quantity-only row(s) #{by_hand} (+100)" in a
               for a in detail["splits"]["already"])


def test_the_same_split_under_another_date_is_refused_not_doubled(db, migrated, tmp_path):
    """A split row a session wrote by hand on the broker's date, a day after the vendor's ex-date.
    No trade separates the two, so they restate the same shares by the same ratio: recording the
    vendor's would apply 2:1 twice. Refused, by name — which date is the split is Zak's call."""
    with db.cursor() as cur:
        _held_through_a_split(cur)
        twin = _row(cur, "N01.US", "split", 2.0, 0, D(2026, 8, 15), grade="stated")
    db.commit()
    out = _reconcile(migrated, tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        assert _book(cur, "N01.US")[0] == 200.0, "doubled once, by the hand row"
        assert _splits(cur) == [("TFSA", "N01.US", 2.0, D(2026, 8, 15))]
    status, detail = _newest_run(db)
    assert status == "red"
    assert f"split #{twin} already restates the same shares" in detail["refused"][0]["why"]


def test_a_vendor_posting_the_tape_contradicts_is_not_recorded(db, migrated, tmp_path):
    """Production's own shape: RUSHA.US carries a 3:2 on 2026-08-11, when the raw close went
    80.20 -> 81.59, and the real one on 09-01 (76.83 -> 48.75). Held through both, the position is
    restated once — on 09-01 — not 2.25x. The August posting is named, not recorded; once the real
    split is in the ledger it goes quiet rather than ambering every night for ever."""
    with db.cursor() as cur:
        _name(cur, "RUSHA.US")
        _tape(cur, "RUSHA.US", {D(2026, 8, 5): 81.80, D(2026, 8, 10): 80.20, D(2026, 8, 11): 81.59,
                                D(2026, 8, 31): 76.83, D(2026, 9, 1): 48.75})
        _row(cur, "RUSHA.US", "buy", 100, 81.80, D(2026, 8, 5))
        _split(cur, "RUSHA.US", D(2026, 8, 11), "3.000000/2.000000")
        _split(cur, "RUSHA.US", D(2026, 9, 1), "3.000000/2.000000")
    db.commit()

    out = _reconcile(migrated, tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        assert _book(cur, "RUSHA.US")[0] == pytest.approx(150.0), "x1.5 once, not x2.25"
        assert _splits(cur) == [("TFSA", "RUSHA.US", 1.5, D(2026, 9, 1))]
    status, detail = _newest_run(db)
    assert status == "amber"
    contradicted = detail["splits"]["contradicted"]
    assert len(contradicted) == 1
    assert contradicted[0].startswith("TFSA RUSHA.US 1.5:1 split, ex 2026-08-11: the tape says no")
    assert any("tape contradicts" in a for a in detail["amber"])

    out = _reconcile(migrated, tmp_path)
    status, detail = _newest_run(db)
    assert status == "green", "the early posting is quiet once the real split is recorded"
    assert detail["splits"]["contradicted"] == []
    assert any("2026-08-11" in a and "already restates" in a for a in detail["splits"]["already"])


def test_a_split_that_cannot_be_recorded_holds_the_buys_by_name(db, migrated, tmp_path):
    """Fail closed, like a ticker change or a takeover. A held name the ledger has no history for
    (a holding older than the ledger, SPMO's state on 2026-08-18) has nothing a split row could
    restate: the run is red and says what to record first, and §4.4's reconciliation gauge — the
    line of the brief that holds the buys — names the ticker and the reason."""
    with db.cursor() as cur:
        _name(cur, "SPMO.US")
        _tape(cur, "SPMO.US", {D(2026, 8, 13): 156.0, D(2026, 8, 14): 78.0})
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,currency,opened_at,
                                         status)
                       values ('SPMO.US','RRSP','reserve',107,155.6,'USD','2026-08-01','open')""")
        _split(cur, "SPMO.US", D(2026, 8, 14), "2.000000/1.000000")
    db.commit()

    out = _reconcile(migrated, tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "REFUSED RRSP SPMO.US" in out.stdout
    status, detail = _newest_run(db)
    assert status == "red"
    assert "no ledger history" in detail["red"][0]
    with db.cursor() as cur:
        assert _book(cur, "SPMO.US", "RRSP")[0] == 107.0, "left exactly alone"
        g = gauges.reconciliation_age(cur)
    assert g["status"] == "red"
    assert "1 split(s) on a held name not recorded: RRSP SPMO.US" in g["why"]
    assert "no ledger history" in g["why"]


def test_a_dry_run_says_what_it_would_record_and_writes_nothing(db, migrated, tmp_path):
    """DRY_RUN: compute everything, write nothing (§4.2)."""
    with db.cursor() as cur:
        _held_through_a_split(cur)
    db.commit()
    out = _reconcile(migrated, tmp_path, DRY_RUN="true")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "1 split(s) would be recorded" in out.stdout
    assert "would restate 100 pre-split shares to 200" in out.stdout
    with db.cursor() as cur:
        assert _splits(cur) == [] and _book(cur, "N01.US")[0] == 100.0
