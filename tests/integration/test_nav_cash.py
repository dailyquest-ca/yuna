"""Cash moves when a fill happens (§2.0).

"Balances are truth, prices are the extrapolation" — and the other half of the same section: a
ticket "is only written if that account holds the cash", and cash "includes unsettled proceeds of
same-account sells". Money leaves the account when the buy fills. It does not wait for Sunday.

`nav_cad` read the anchor and stopped there, so between Sunday readings a purchase added its stock
to the book and left the money that paid for it sitting in the account. Found on 2026-08-05, when
four fills from the 4th were reconciled against an anchor dated the 3rd: NAV read C$222,764 against
a true C$204,827 — **8.1% high**, C$17,937 of stock the book was credited with owning and with
still having the money for. Before the reconciliation the two errors cancelled, which is the least
comfortable way for a number to be right.
"""
import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import db as dbm                                                          # noqa: E402
import fixtures as world                                                  # noqa: E402

YESTERDAY = dt.date.today() - dt.timedelta(days=1)


def anchor(cur, *, cad=10_000.0, usd=50_000.0, as_of=YESTERDAY, account="TFSA"):
    cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source)
                   values (%s,%s,%s,%s,'test')""", (account, as_of, cad, usd))


def fill(cur, *, side, qty, price, ccy="USD", when=None, account="TFSA", fees=0):
    # The name has to exist. Since migration 059 a ledger row moves the book, and `book.ticker`
    # references `universe` — so a transaction in a symbol nothing has ever heard of now fails at
    # the write instead of opening a position in it. That is the intended behaviour and these
    # tests are about the cash arithmetic, not about inventing instruments.
    cur.execute("""insert into universe (ticker,name,kind,exchange,currency,status)
                   values ('AAA.US','AAA','stock','NASDAQ','USD','active')
                   on conflict (ticker) do nothing""")
    cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                             trade_date, fees, confirmed)
                   values ('AAA.US',%s,%s,%s,%s,%s,%s,%s,true)""",
                (account, side, qty, price, ccy, when or dt.date.today(), fees))


def held(cur, *, qty, price, ccy="USD", account="TFSA", when=None):
    """An opening position, so a sell has something to sell. Moves no cash by construction."""
    cur.execute("""insert into universe (ticker,name,kind,exchange,currency,status)
                   values ('AAA.US','AAA','stock','NASDAQ','USD','active')
                   on conflict (ticker) do nothing""")
    cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                             trade_date, confirmed, confirmed_at, applied_at,
                                             grade, source)
                   values ('AAA.US',%s,'confirm',%s,%s,%s,%s,true,now(),now(),'stated','test')""",
                (account, qty, price, ccy, when or (YESTERDAY - dt.timedelta(days=1))))


def cash(conn, account="TFSA"):
    with conn.cursor() as cur:
        return dbm.cash_by_account(cur)[account]


def test_a_buy_after_the_anchor_takes_its_own_currency_out(db):
    with db.cursor() as cur:
        anchor(cur)
        fill(cur, side="buy", qty=10, price=419.83)          # 4,198.30 USD
    db.commit()
    c = cash(db)
    assert c["usd"] == pytest.approx(50_000 - 4_198.30)
    assert c["cad"] == pytest.approx(10_000), "a USD trade does not touch the CAD side"
    assert c["anchored_usd"] == pytest.approx(50_000), "the anchor itself is still readable"


def test_a_sell_puts_the_proceeds_back(db):
    with db.cursor() as cur:
        anchor(cur)
        # There has to be something to sell. A `confirm` row is the opening balance — it establishes
        # the position and moves no money, which is the whole reason `cash_by_account` skips it —
        # and without one the sell drives the position to minus ten shares and is refused.
        held(cur, qty=10, price=400.0)
        fill(cur, side="sell", qty=10, price=419.83, fees=2.5)
    db.commit()
    assert cash(db)["usd"] == pytest.approx(50_000 + 4_198.30 - 2.5)


def test_a_fill_the_anchor_already_saw_is_not_counted_twice(db):
    """Zak reads the balance off Wealthsimple on Sunday; anything up to that date is already in it.
    Double-counting would be the same defect with the sign flipped."""
    with db.cursor() as cur:
        anchor(cur, as_of=dt.date.today())
        fill(cur, side="buy", qty=10, price=419.83, when=dt.date.today())
        fill(cur, side="buy", qty=10, price=419.83, when=YESTERDAY)
    db.commit()
    assert cash(db)["usd"] == pytest.approx(50_000)


def test_a_quantity_confirmation_moves_no_money(db):
    """R4 writes `confirm` rows to restate a share count (§4.5 step 5). No cash changes hands."""
    with db.cursor() as cur:
        anchor(cur)
        fill(cur, side="confirm", qty=40, price=180.35)
    db.commit()
    assert cash(db)["usd"] == pytest.approx(50_000)


def test_a_cad_trade_moves_the_cad_side(db):
    with db.cursor() as cur:
        anchor(cur)
        fill(cur, side="buy", qty=100, price=56.20, ccy="CAD")
    db.commit()
    c = cash(db)
    assert c["cad"] == pytest.approx(10_000 - 5_620)
    assert c["usd"] == pytest.approx(50_000)


def test_nav_counts_the_position_and_the_money_that_bought_it_once(db, fx):
    """The whole point, as one number: buying stock at its market price leaves NAV unmoved."""
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US", level=100.0, last_close=100.0)
        anchor(cur, cad=0.0, usd=50_000.0)
        with db.cursor() as c2:
            before = dbm.nav_cad(c2)["nav"]
        cur.execute("""insert into book (ticker,account,sleeve,lot,qty,avg_cost,currency,
                                         opened_at,status)
                       values ('AAA.US','TFSA','momentum','core',100,100.0,'USD',
                               current_date,'open')""")
        fill(cur, side="buy", qty=100, price=100.0)
    db.commit()
    with db.cursor() as cur:
        after = dbm.nav_cad(cur)
    assert after["nav"] == pytest.approx(before, abs=0.01)
    assert after["accounts"]["TFSA"]["cash_native"]["USD"] == pytest.approx(40_000)
    assert after["accounts"]["TFSA"]["cash_moved_since_anchor"]["USD"] == pytest.approx(-10_000)


def test_an_account_the_ledger_has_outspent_cannot_fund_another_position(db, fx):
    """§2.6's funding rule reads the same number: "one position, one account, one order", and the
    account has to hold the cash. Money spent on Tuesday is not available again on Wednesday."""
    with db.cursor() as cur:
        anchor(cur, cad=0.0, usd=50_000.0)
        fill(cur, side="buy", qty=100, price=480.0)          # 48,000 USD gone
        cash_now = dbm.cash_by_account(cur)["TFSA"]
    assert cash_now["usd"] == pytest.approx(2_000)
    assert cash_now["cad"] + cash_now["usd"] * 1.4 < 5_000, \
        "the funding check must see what is left, not what Sunday saw"
