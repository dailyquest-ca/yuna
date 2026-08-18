"""The ledger is the history, and the book is its arithmetic (migration 059).

Zak, 2026-08-18:

    "There are a list of transactions... And those will always come in with a transaction ledger csv
     from Wealthsimple or another bank... Those are law... You keep them in the transaction ledger
     and they should all match. That's our actual history. I will upload those to the chat so the
     chat should be able to write them... And know how...

     And then additionally sometimes those transactions are lagged... By days... So I will just tell
     the chat other sales so it can process the books correctly. Such as that I sold stock or the
     current dollar availability etc. Those are true to me... But they might change or be tweaked by
     the transactions later. Maybe the pennies are different.... But the engine should run assuming
     both."

Four claims, and one test each:

  1. a bank export is law and moves the book
  2. Zak's word moves the book NOW, without waiting for the export
  3. when the export lands it supersedes his word — pennies and all — and the book follows
  4. **the chat can do all of this in plain SQL**, because that is the surface it has

(4) is the one the whole design turns on. Zak uploads a CSV to a chat session, not to a shell.
"""
import pathlib
import sys

import psycopg
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import desk                                                               # noqa: E402
import ledger                                                             # noqa: E402

# A Wealthsimple-shaped export: headers by NAME, a dividend and a contribution mixed in with the
# trades, and a fractional line. Nothing here is read positionally — see `ledger.HEADERS`.
EXPORT = """date,transaction,symbol,quantity,price,amount,account,id
2026-08-17,Sell,NUE.US,32,266.8111,8537.96,TFSA,ws-nue-1
2026-08-17,Buy,AXTI.US,20,77.21,-1544.20,TFSA,ws-axti-1
2026-08-17,Dividend,NUE.US,,,41.60,TFSA,ws-div-1
2026-08-16,Contribution,,,,7000.00,TFSA,ws-dep-1
"""


def _universe(cur, *tickers):
    for tk in tickers:
        cur.execute("""insert into universe (ticker,name,kind,exchange,currency,status)
                       values (%s,%s,'stock','NASDAQ','USD','active')
                       on conflict (ticker) do nothing""", (tk, tk.split(".")[0]))


def _opening(cur, ticker, qty, price, account="TFSA", when="2026-08-01"):
    """The position as it stood before this ledger existed. §6.1's book entered exactly this way."""
    cur.execute("""insert into transactions (ticker,account,side,qty,price,currency,trade_date,
                                             confirmed,confirmed_at,grade,source)
                   values (%s,%s,'confirm',%s,%s,'USD',%s,true,now(),'stated','opening balance')""",
                (ticker, account, qty, price, when))


def _book(cur, ticker, account="TFSA"):
    cur.execute("""select qty, avg_cost, status from book
                    where ticker = %s and account = %s""", (ticker, account))
    return cur.fetchone()


# ---------------------------------------------------------------- 1. the export is law

def test_the_export_parses_by_header_and_skips_everything_that_is_not_a_trade(tmp_path):
    """A bank export carries dividends, interest, contributions and journal entries beside the
    trades. Every one of those folded in as a trade would move a position that never moved — so a
    row whose type cannot be read as a buy or a sell is SKIPPED and reported, never assumed."""
    path = tmp_path / "ws.csv"
    path.write_text(EXPORT)
    rows, skipped = ledger.parse_csv(str(path))

    assert [(r["side"], r["ticker"], r["qty"]) for r in rows] == [
        ("sell", "NUE.US", 32.0), ("buy", "AXTI.US", 20.0)]
    assert len(skipped) == 2 and any("Dividend" in s or "dividend" in s for s in skipped)
    assert rows[0]["external_ref"] == "ws-nue-1" and rows[0]["account"] == "TFSA"


def test_a_broker_row_lands_as_law_and_the_book_follows(db, tmp_path):
    with db.cursor() as cur:
        _universe(cur, "NUE.US", "AXTI.US")
        _opening(cur, "NUE.US", 32, 267.715)
        db.commit()

        path = tmp_path / "ws.csv"
        path.write_text(EXPORT)
        fills, _ = ledger.parse_csv(str(path))
        for f in fills:
            ledger.record(cur, f, "broker", "csv ws.csv")
        db.commit()

        assert _book(cur, "NUE.US")[:1] == (0.0,) and _book(cur, "NUE.US")[2] == "closed"
        qty, cost, status = _book(cur, "AXTI.US")
        assert (qty, status) == (20.0, "open") and cost == pytest.approx(77.21)


def test_the_same_export_read_twice_writes_nothing_the_second_time(db, tmp_path):
    """The chain re-fires on the retry ingest and Zak may upload the same file twice. The bank's own
    id is the idempotence key, so a re-import is free rather than a doubled position."""
    with db.cursor() as cur:
        _universe(cur, "NUE.US", "AXTI.US")
        _opening(cur, "NUE.US", 32, 267.715)
        db.commit()
        path = tmp_path / "ws.csv"
        path.write_text(EXPORT)
        fills, _ = ledger.parse_csv(str(path))

        first = [ledger.record(cur, f, "broker", "csv ws.csv")[1] for f in fills]
        second = [ledger.record(cur, f, "broker", "csv ws.csv")[1] for f in fills]
        db.commit()

        assert first == ["recorded", "recorded"]
        assert second == ["already imported", "already imported"]
        cur.execute("select count(*) from transactions where side <> 'confirm'")
        assert cur.fetchone()[0] == 2
        assert _book(cur, "AXTI.US")[0] == 20.0


# ------------------------------------------------------- 2 & 3. the lag, and what closes it

def test_zaks_word_moves_the_book_before_the_export_arrives(db):
    """*"I will just tell the chat other sales so it can process the books correctly."* The book
    does not wait: for however many days the export lags, an engine reasoning from the un-sold
    position proposes a sell Zak has already made. That is the ghost book, and it happened."""
    with db.cursor() as cur:
        _universe(cur, "NUE.US")
        _opening(cur, "NUE.US", 32, 267.715)
        db.commit()

        ledger.record(cur, dict(ticker="NUE.US", account="TFSA", side="sell", qty=32,
                                price=266.81, trade_date="2026-08-17"),
                      "stated", "stated in chat")
        db.commit()

        assert _book(cur, "NUE.US") == (0.0, pytest.approx(267.715), "closed")
        assert desk.held_book(cur) == {}, "and the engine cannot propose selling it again"


def test_the_export_supersedes_the_statement_pennies_and_all(db):
    """*"they might change or be tweaked by the transactions later. Maybe the pennies are
    different."*

    The match is on account, ticker, side and the DAY — deliberately not on quantity or price,
    because the whole reason a broker row supersedes a stated one is that those numbers differ
    slightly. Matching on them would never match the case the rule exists for.

    §0.6 keeps the record: the stated row stays and stops counting, so the history shows both what
    Zak believed on the day and what the bank confirmed after.
    """
    with db.cursor() as cur:
        _universe(cur, "NUE.US")
        _opening(cur, "NUE.US", 32, 267.715)
        ledger.record(cur, dict(ticker="NUE.US", account="TFSA", side="sell", qty=32,
                                price=266.81, trade_date="2026-08-17"),
                      "stated", "stated in chat")
        db.commit()

        # the export lands: a different quantity AND a different price for the same trade
        new_id, note = ledger.record(cur, dict(ticker="NUE.US", account="TFSA", side="sell",
                                               qty=31.5, price=266.8111,
                                               trade_date="2026-08-17",
                                               external_ref="ws-nue-1"),
                                     "broker", "csv ws.csv")
        db.commit()

        assert "superseding 1 stated row" in note
        cur.execute("""select grade, qty, price, superseded_by is not null from transactions
                        where side = 'sell' order by id""")
        assert cur.fetchall() == [("stated", 32.0, 266.81, True),
                                  ("broker", 31.5, 266.8111, False)]
        # the book counts the broker row and no longer counts the stated one: 32 - 31.5
        assert _book(cur, "NUE.US")[0] == pytest.approx(0.5)
        assert _book(cur, "NUE.US")[2] == "open"


def test_saying_the_same_thing_twice_restates_rather_than_doubles(db):
    """Zak correcting himself in chat is a restatement, not a second sale. A stated row carries no
    bank identifier to key on, so it is matched on the trade itself."""
    with db.cursor() as cur:
        _universe(cur, "NUE.US")
        _opening(cur, "NUE.US", 32, 267.715)
        db.commit()                    # the position exists before Zak says anything about it
        for qty in (30, 32):
            ledger.record(cur, dict(ticker="NUE.US", account="TFSA", side="sell", qty=qty,
                                    price=266.81, trade_date="2026-08-17"),
                          "stated", "stated in chat")
        db.commit()

        cur.execute("select count(*) from transactions where side = 'sell'")
        assert cur.fetchone()[0] == 1, "one statement about one trade"
        assert _book(cur, "NUE.US")[2] == "closed"


# ------------------------------------------------------------------- the guard, and the repair

def test_selling_what_the_ledger_never_bought_is_refused_and_says_how_to_fix_it(db):
    """A book quietly holding minus 810 shares is not an outcome; it is the ghost book with the
    sign flipped. The refusal names the repair, because there is a real one."""
    with db.cursor() as cur:
        _universe(cur, "SPMO.US")
        # the refusal lands at COMMIT, because the trigger is deferred: the book is what the ledger
        # says at the end of a transaction, not part-way through one
        with pytest.raises(psycopg.errors.RaiseException,
                           match="history for this name is incomplete"):
            ledger.record(cur, dict(ticker="SPMO.US", account="TFSA", side="sell", qty=810,
                                    price=155.5, trade_date="2026-08-17"),
                          "stated", "stated in chat")
            db.commit()
    db.rollback()


def test_an_opening_position_is_what_lets_a_pre_ledger_holding_be_sold(db):
    """The repair the message names, and the shape of the §6.1 book: SPMO bought with the
    liquidation proceeds while the export was still days away, then sold to seed the five slots."""
    with db.cursor() as cur:
        _universe(cur, "SPMO.US")
        ledger.record(cur, dict(ticker="SPMO.US", account="TFSA", side="confirm", qty=810,
                                price=155.5, trade_date="2026-08-17"),
                      "stated", "opening balance")
        db.commit()
        assert _book(cur, "SPMO.US")[:1] == (810.0,)

        ledger.record(cur, dict(ticker="SPMO.US", account="TFSA", side="sell", qty=810,
                                price=158.0, trade_date="2026-08-19"),
                      "stated", "stated in chat")
        db.commit()
        assert _book(cur, "SPMO.US")[2] == "closed"


def test_an_unknown_symbol_is_refused_in_words_rather_than_as_a_constraint_name(db):
    """The reader of this message is a chat session that has just been handed a CSV. "book_ticker_
    fkey" tells it nothing about what to do."""
    with db.cursor() as cur:
        with pytest.raises(psycopg.errors.RaiseException, match="is not in `universe`"):
            ledger.record(cur, dict(ticker="NOPE.US", account="TFSA", side="buy", qty=1,
                                    price=10.0, trade_date="2026-08-17"),
                          "stated", "stated in chat")
            db.commit()
    db.rollback()


# ----------------------------------------------------------------- the sweep and the check

def test_rebuild_is_a_no_op_on_a_healthy_book_and_names_what_it_cannot_explain(db):
    """A repair tool whose no-op case is silent is one you can run to find out whether you needed
    it. A position with no history is left exactly alone: deleting a real holding because one table
    cannot explain it is not a repair."""
    with db.cursor() as cur:
        _universe(cur, "NUE.US", "SPMO.US")
        _opening(cur, "NUE.US", 32, 267.715)
        db.commit()
        assert ledger.rebuild_book(cur) == [], "nothing to fix"

        # a holding older than the ledger — exactly SPMO's state on 2026-08-18
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,currency,status)
                       values ('SPMO.US','TFSA','reserve',810,155.5,'USD','open')""")
        db.commit()
        changes = ledger.rebuild_book(cur)
        assert changes == ["TFSA SPMO.US: 810 held with NO ledger history — left untouched"]
        assert _book(cur, "SPMO.US")[:1] == (810.0,), "and still there afterwards"


def test_the_check_separates_a_real_break_from_a_holding_older_than_its_history(db):
    """The two rows in `v_ledger_vs_book` are not the same kind of thing. One is a defect; the other
    is merely incomplete, is TRUE of the book today, and heals itself when the export lands. Red on
    the second would make the gauge cry wolf every night until then."""
    with db.cursor() as cur:
        _universe(cur, "NUE.US", "SPMO.US")
        _opening(cur, "NUE.US", 32, 267.715)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,currency,status)
                       values ('SPMO.US','TFSA','reserve',810,155.5,'USD','open')""")
        db.commit()

        cur.execute("select ticker, predates_the_ledger from v_ledger_vs_book")
        assert cur.fetchall() == [("SPMO.US", True)], "the pre-ledger holding, and nothing else"

        # now a genuine break: the book moved without the ledger. Only a superuser can do this —
        # `guard_book` is what stops anything else — which is itself the point.
        cur.execute("update book set qty = 99 where ticker = 'NUE.US'")
        db.commit()
        cur.execute("""select ticker, predates_the_ledger from v_ledger_vs_book
                        order by predates_the_ledger""")
        assert cur.fetchall() == [("NUE.US", False), ("SPMO.US", True)]


# --------------------------------------------------------------- 4. the chat's own surface

def test_a_chat_session_writing_plain_sql_moves_the_book(db):
    """**The requirement, stated as a test.** Zak uploads the CSV to a chat session; a chat session
    has a SQL connector and no shell, so whatever it can do it does in one INSERT. The book has to
    follow from that alone — no job to wait for, no fold to forget.

    This is what was broken. `transactions` was locked three ways (grant revoked, RLS on with no
    policy, jobs-only trigger), all three from migration 033 enforcing the 2026-08-04 write list
    that v1.0 does not carry, and the book only ever moved when a job ran.
    """
    with db.cursor() as cur:
        _universe(cur, "MU.US")
        # exactly what a session would send, and nothing else
        cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                                 trade_date, confirmed, confirmed_at, grade, source)
                       values ('MU.US','TFSA','buy',2,954.58,'USD','2026-08-14',true,now(),
                               'stated','stated in chat')""")
        db.commit()

        assert _book(cur, "MU.US")[:1] == (2.0,), "one INSERT, and the position exists"
        assert desk.held_book(cur) == {"MU.US": 2.0}, "and the engine sees it tonight"


def test_the_session_role_may_write_the_ledger_and_still_may_not_write_the_book(db):
    """The direction of the whole design: a session writes HISTORY, and history moves positions.

    Skipped where `yuna_session` does not exist — it is created by migration 020 against the real
    Supabase project and a throwaway local Postgres may not carry it.
    """
    with db.cursor() as cur:
        cur.execute("select 1 from pg_roles where rolname = 'yuna_session'")
        if not cur.fetchone():
            pytest.skip("no yuna_session role in this database")
        cur.execute("""select table_name,
                              string_agg(privilege_type, ',' order by privilege_type)
                         from information_schema.role_table_grants
                        where grantee = 'yuna_session' and table_name in ('transactions','book')
                        group by table_name""")
        grants = dict(cur.fetchall())
    assert "INSERT" in grants.get("transactions", ""), "§4.3 + Zak 2026-08-18: the chat writes these"
    assert "INSERT" not in grants.get("book", ""), "and never writes a position directly"
