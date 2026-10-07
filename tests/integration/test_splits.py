"""A split on a held name, through the ledger (migration 075, Zak's ruling of 2026-10-07).

Zak, 2026-10-07: *"Pipeline records splits — a vendor-reported split on a held name is written to
the ledger as a quantity-only confirm (no cash) before score runs, and the brief shows it. Ticker
changes and takeovers still fail closed until you record them."*

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
import pathlib
import sys

import psycopg
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import db as dbm                                                          # noqa: E402
import ledger                                                             # noqa: E402

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


def _book(cur, ticker, account="TFSA"):
    cur.execute("""select qty, avg_cost, status from book
                    where ticker = %s and account = %s order by id desc limit 1""",
                (ticker, account))
    return cur.fetchone()


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
