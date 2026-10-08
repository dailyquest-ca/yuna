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


def anchor(cur, *, cad=10_000.0, usd=50_000.0, as_of=YESTERDAY, account="TFSA",
           recorded_at=None):
    cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source, recorded_at)
                   values (%s,%s,%s,%s,'test',coalesce(%s::timestamptz, now()))""",
                (account, as_of, cad, usd, recorded_at))


def utc(d, hour):
    """`d` at `hour`:00 UTC. The regular session opens at 09:30 New York time — 13:30 UTC under
    daylight time, 14:30 UTC under standard time — so an hour in UTC lands on a known side of it."""
    return dt.datetime.combine(d, dt.time(hour, 0), tzinfo=dt.timezone.utc)


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
    """Zak reads the balance off Wealthsimple after the day's trades; anything up to that date is
    already in it. Double-counting would be the same defect with the sign flipped.

    The reading is written after the close on purpose, and that line is the only change since A30.
    The time a reading was written is now part of how it is ordered against that day's fills — one
    written before its date's open precedes all of them — so leaving it at `now()` made this test's
    answer depend on the hour it ran: before 13:30 UTC the buy below is correctly counted."""
    today = dt.date.today()
    with db.cursor() as cur:
        anchor(cur, as_of=today, recorded_at=utc(today, 22))
        fill(cur, side="buy", qty=10, price=419.83, when=today)
        fill(cur, side="buy", qty=10, price=419.83, when=YESTERDAY)
    db.commit()
    assert cash(db)["usd"] == pytest.approx(50_000)


def test_a_reading_written_before_the_open_holds_none_of_that_days_fills(db):
    """A30. Zak states his cash before the open, then trades at it. The session writes the reading
    dated today, and the date alone read today's buy as already inside it — so the money that paid
    for the buy stayed in the account, NAV read high by the whole fill, and every NAV/5 slot was
    sized off cash that was gone, until somebody wrote another anchor.

    No fill precedes its session's open (§4.3 — market orders at the open), so a reading written
    before the open was taken before every fill of that date. 14:00 UTC on a January session is
    09:00 in New York, half an hour before it."""
    winter = dt.date(2026, 1, 15)                          # a Thursday, standard time
    with db.cursor() as cur:
        anchor(cur, as_of=winter, recorded_at=utc(winter, 14))
        fill(cur, side="buy", qty=10, price=419.83, when=winter)
    db.commit()
    c = cash(db)
    assert c["usd"] == pytest.approx(50_000 - 4_198.30), "the buy came after the reading"
    assert c["moved_since_anchor"] == {"USD": pytest.approx(-4_198.30)}
    assert c["same_day_assumed_inside"] is None, "nothing on that date is left unordered"


def test_a_same_day_fill_the_store_cannot_order_is_named_rather_than_assumed(db):
    """A30, the other side. 14:00 UTC on a July session is 10:00 in New York — after the open — and
    the store cannot say whether the reading was taken before the buy or after it: `trade_date` is a
    date, and `recorded_at`, `confirmed_at` and `applied_at` are only when rows were written. The
    fill stays inside the reading, as before — a post-trade screenshot dated the day of the trades
    is right that way, and 2026-08-17's is one — but the assumption is now stated, with its size.

    Together with the January test this pins the clock as New York's: a fixed 13:30 UTC open would
    get January wrong, and a fixed 14:30 UTC open would get this one wrong."""
    summer = dt.date(2026, 7, 16)                          # a Thursday, daylight time
    with db.cursor() as cur:
        anchor(cur, as_of=summer, recorded_at=utc(summer, 14))
        fill(cur, side="buy", qty=10, price=419.83, when=summer)
        fill(cur, side="buy", qty=1, price=100.0, when=summer - dt.timedelta(days=1))
    db.commit()
    c = cash(db)
    assert c["usd"] == pytest.approx(50_000), "an unordered fill is not counted"
    assert c["same_day_assumed_inside"] == {"fills": 1, "net": {"USD": pytest.approx(-4_198.30)}}, \
        "only the anchor's own date is unordered; the day before is inside the reading by date"


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


def test_a_superseded_statement_is_not_paid_for_twice(db):
    """Migration 059's supersession, from the cash side.

    Zak says in chat that he bought; days later the bank's export lands with the same trade and
    slightly different pennies. §0.6 keeps both rows — the stated one is stamped `superseded_by` and
    stops counting — so anything that SUMS the ledger has to say which rows it means.

    `cash_by_account` did not, and the failure is the expensive direction: one purchase taken out of
    the account twice reads as less cash than exists, and §2.0 only writes a ticket "if that account
    holds the cash". A trade Zak can afford gets refused for want of money that is there.
    """
    with db.cursor() as cur:
        anchor(cur)
        held(cur, qty=10, price=400.0)
        fill(cur, side="buy", qty=10, price=419.83)                 # stated: 4,198.30 out
        cur.execute("select id from transactions where side = 'buy'")
        stated = cur.fetchone()[0]
        fill(cur, side="buy", qty=10, price=419.85)                 # the export, two cents apart
        cur.execute("""update transactions set superseded_by = (select max(id) from transactions)
                        where id = %s""", (stated,))
    db.commit()
    # the broker's number, once — not both, and not the stated one
    assert cash(db)["usd"] == pytest.approx(50_000 - 4_198.50)
