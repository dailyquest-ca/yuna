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

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import desk                                                               # noqa: E402
import fixtures as world                                                  # noqa: E402
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


# ------------------------------------------- Zak's rule: a statement the export passed over

def test_a_stated_trade_the_export_reported_past_is_flagged(db):
    """Zak, 2026-08-18: *"if a stated transaction in an account pre-dates broker transactions...
    that's a bad sign and likely the stated transaction should be matched to one of the broker
    transactions or removed... because I had stated data that didn't actually come to pass."*

    059 gave a stated row one way out — a broker row for the same trade supersedes it — which covers
    the export CONFIRMING what Zak said. It said nothing about the export arriving, covering the
    day, and not mentioning the trade at all. That case is not neutral: it means the thing he
    believed happened did not.

    It is the worst shape the ghost book takes, because the ledger and the book AGREE. A stated sell
    that never executed empties a slot that is still full, and every later session sizes against it.
    """
    with db.cursor() as cur:
        _universe(cur, "NUE.US", "AXTI.US")
        _opening(cur, "NUE.US", 32, 267.715)
        db.commit()                    # the position exists before he says anything about it
        # Zak says he sold NUE on the 17th
        ledger.record(cur, dict(ticker="NUE.US", account="TFSA", side="sell", qty=32,
                                price=266.81, trade_date="2026-08-17"),
                      "stated", "stated in chat")
        db.commit()
        assert _book(cur, "NUE.US")[2] == "closed", "the book moves on his word, as it should"

        # the export lands covering the 19th — and carries no NUE sell
        ledger.record(cur, dict(ticker="AXTI.US", account="TFSA", side="buy", qty=20,
                                price=77.21, trade_date="2026-08-19", external_ref="ws-1"),
                      "broker", "csv ws.csv")
        db.commit()

        cur.execute("""select account, ticker, side, days_the_export_has_passed_it
                         from v_stale_statements""")
        assert cur.fetchall() == [("TFSA", "NUE.US", "sell", 2)]


def test_a_statement_the_export_confirmed_is_not_stale(db):
    """The ordinary case must stay quiet, or the rule is noise. A stated row the export superseded
    has already done its job and stops counting — it is not a statement that failed."""
    with db.cursor() as cur:
        _universe(cur, "NUE.US")
        _opening(cur, "NUE.US", 32, 267.715)
        ledger.record(cur, dict(ticker="NUE.US", account="TFSA", side="sell", qty=32,
                                price=266.81, trade_date="2026-08-17"),
                      "stated", "stated in chat")
        ledger.record(cur, dict(ticker="NUE.US", account="TFSA", side="sell", qty=32,
                                price=266.8111, trade_date="2026-08-17", external_ref="ws-1"),
                      "broker", "csv ws.csv")
        db.commit()
        cur.execute("select count(*) from v_stale_statements")
        assert cur.fetchone()[0] == 0, "superseded is resolved, not stale"


def test_the_rule_is_per_account(db):
    """An export for the NONREG says nothing about a statement in the TFSA. Accounts reconcile on
    their own schedules — Zak uploads what the bank gives him, one account at a time."""
    with db.cursor() as cur:
        _universe(cur, "NUE.US", "VXC.TO")
        _opening(cur, "NUE.US", 32, 267.715)
        ledger.record(cur, dict(ticker="NUE.US", account="TFSA", side="sell", qty=32,
                                price=266.81, trade_date="2026-08-17"),
                      "stated", "stated in chat")
        ledger.record(cur, dict(ticker="VXC.TO", account="NONREG", side="buy", qty=140,
                                price=85.45, trade_date="2026-08-19", external_ref="ws-9"),
                      "broker", "csv ws.csv")
        db.commit()
        cur.execute("select count(*) from v_stale_statements")
        assert cur.fetchone()[0] == 0, "a NONREG export does not report past a TFSA statement"


def test_an_opening_balance_is_not_a_failed_statement(db):
    """A `confirm` says a position EXISTS and what it cost. It is not a claim that a trade happened
    on that date, so an export that covers the day and does not mention the name does not refute it
    — it just does not explain it. Amber, and its own view."""
    with db.cursor() as cur:
        _universe(cur, "SPMO.US", "AXTI.US")
        ledger.record(cur, dict(ticker="SPMO.US", account="TFSA", side="confirm", qty=810,
                                price=155.5, trade_date="2026-08-17"),
                      "stated", "book adoption")
        ledger.record(cur, dict(ticker="AXTI.US", account="TFSA", side="buy", qty=20,
                                price=77.21, trade_date="2026-08-19", external_ref="ws-1"),
                      "broker", "csv ws.csv")
        db.commit()

        cur.execute("select count(*) from v_stale_statements")
        assert cur.fetchone()[0] == 0, "an opening balance is not a trade that failed to happen"
        cur.execute("""select account, ticker, broker_has_this_name
                         from v_unexplained_opening_balances""")
        assert cur.fetchall() == [("TFSA", "SPMO.US", False)]


def test_an_opening_balance_the_export_now_covers_is_a_double_count(db):
    """The loose end migration 059 left, made loud. When the export finally carries the purchases
    behind an adopted balance, BOTH count and the position doubles — 810 adopted plus 810 bought.
    The system cannot decide which to retire (the file might hold the original purchase or a later
    top-up, and only Zak knows), so it says so instead of guessing. §0.3."""
    with db.cursor() as cur:
        _universe(cur, "SPMO.US")
        ledger.record(cur, dict(ticker="SPMO.US", account="TFSA", side="confirm", qty=810,
                                price=155.5, trade_date="2026-08-17"),
                      "stated", "book adoption")
        ledger.record(cur, dict(ticker="SPMO.US", account="TFSA", side="buy", qty=810,
                                price=155.4821, trade_date="2026-08-17", external_ref="ws-spmo"),
                      "broker", "csv ws.csv")
        db.commit()

        assert _book(cur, "SPMO.US")[0] == 1620.0, "both count — that is the defect being named"
        cur.execute("""select account, ticker, broker_has_this_name
                         from v_unexplained_opening_balances""")
        assert cur.fetchall() == [("TFSA", "SPMO.US", True)], "and it is flagged, not resolved"


def test_the_ledger_opens_a_position_unassigned_not_book(db):
    """Sleeves are subsets of the book, so `book` is a category error as a sleeve name — it labels a
    part with the name of the whole. `unassigned` is honest: the ledger knows a trade happened and
    in which account, and genuinely does not know which sleeve the position belongs to. §0.3.

    Since 064 this is the TICKET-LESS half of the rule, and still the point: a row with no ticket
    behind it has no engine sleeve to transcribe, so the ledger says so rather than guessing."""
    with db.cursor() as cur:
        _universe(cur, "MU.US")
        ledger.record(cur, dict(ticker="MU.US", account="TFSA", side="buy", qty=2,
                                price=954.58, trade_date="2026-08-14"),
                      "stated", "stated in chat")
        db.commit()
        cur.execute("select sleeve from book where ticker = 'MU.US'")
        assert cur.fetchone()[0] == "unassigned"


def test_the_same_export_uploaded_twice_collides_instead_of_doubling(db):
    """The gap the first REAL import surfaced (2026-08-20), closed by migration 062.

    Wealthsimple's export carries no per-row id, so the importing session synthesizes
    `<filename>#<row>`. Without uniqueness a re-upload doubles every position it touches, and
    NOTHING catches it — the ledger and the book agree on the doubled number, so every
    reconciliation view reads clean. A hard collision is the only honest outcome.
    """
    with db.cursor() as cur:
        _universe(cur, "SPMO.US")
        cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                                 trade_date, confirmed, confirmed_at, grade,
                                                 external_ref, source)
                       values ('SPMO.US','TFSA','buy',713,155.40,'USD','2026-08-17',true,now(),
                               'broker','activitiesexport.csv#1','csv activitiesexport.csv')""")
        db.commit()
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                                     trade_date, confirmed, confirmed_at, grade,
                                                     external_ref, source)
                           values ('SPMO.US','TFSA','buy',713,155.40,'USD','2026-08-17',true,now(),
                                   'broker','activitiesexport.csv#1','csv activitiesexport.csv')""")
    db.rollback()
    with db.cursor() as cur:
        cur.execute("select qty from book where ticker = 'SPMO.US' and status = 'open'")
        assert cur.fetchone()[0] == 713.0, "the position did not double"


def test_a_chat_imported_export_counts_as_a_receipt(db):
    """§4.4's gauge reads "book-vs-broker reconciliation age", and 052 keyed last_receipt on
    `broker_ref` — which only the manifest path sets. On a desk whose receipts all arrive through
    chat, the gauge's newest receipt would read null forever. Migration 062: the newest live
    broker-grade trade date, whatever the route."""
    with db.cursor() as cur:
        _universe(cur, "SPMO.US")
        cur.execute("select last_receipt from v_reconciliation_age")
        assert cur.fetchone()[0] is None
        ledger.record(cur, dict(ticker="SPMO.US", account="TFSA", side="buy", qty=810,
                                price=155.5, trade_date="2026-08-17", external_ref="ws.csv#1"),
                      "broker", "csv ws.csv")
        db.commit()
        cur.execute("select last_receipt from v_reconciliation_age")
        assert str(cur.fetchone()[0]) == "2026-08-17"


# ------------------------------------------------ a position is one book row (migration 069)
#
# QC 2026-10-07, A11 and A13. `yuna_book_from_ledger` found a position with `limit 1` and no ORDER
# BY, and `book_open_unique` (007) allowed one open row per LOT. On 2026-09-28 the trigger set
# NONREG VXC.TO's row to the whole ledger (279), and six seconds later a chat session — logged in
# as `postgres`, which `guard_book` admits — inserted a second open row of 139 beside it. Every
# reader that sums a position counted 418 from then on. Migration 069 closes that row on Zak's
# word and makes the state impossible; the tests that need it rebuild it inside
# `world.book_before_069`.

MIGRATION_069 = ROOT / "migrations" / "069_a_position_is_one_row.sql"


def _split(cur, ticker="N00.US", account="TFSA"):
    """VXC.TO as production held it until 069: two broker buys the ledger moved into one row (279),
    then a second open row of 139 written straight into `book` beside it. Nothing in a
    `book_before_069` block commits, so the ledger is made to move the book row by row."""
    cur.execute("set constraints ledger_moves_the_book immediate")
    _universe(cur, ticker)
    for qty, px, ref in ((140, 85.45, "ws-t1"), (139, 86.30, "ws-t2")):
        ledger.record(cur, dict(ticker=ticker, account=account, side="buy", qty=qty, price=px,
                                trade_date="2026-08-17", external_ref=ref), "broker", "csv")
    cur.execute("""insert into book (ticker,account,sleeve,lot,qty,avg_cost,currency,status)
                   values (%s,%s,'levered','tranche2',139,86.30,'USD','open')""", (ticker, account))


def _open_rows(cur, ticker):
    cur.execute("""select id, lot, qty from book where ticker = %s and status = 'open'
                    order by id""", (ticker,))
    return cur.fetchall()


def _sold_out_with_a_row_left_open(cur, ticker="N00.US"):
    """A11's phantom: the ledger bought and sold the name out, and a row is open anyway."""
    _universe(cur, ticker)
    for side in ("buy", "sell"):
        ledger.record(cur, dict(ticker=ticker, account="TFSA", side=side, qty=100, price=50.0,
                                trade_date="2026-08-17"), "stated", "chat")
        cur.connection.commit()              # the deferred trigger moves the book at each commit
    assert _book(cur, ticker)[2] == "closed"
    cur.execute("""insert into book (ticker,account,sleeve,lot,qty,avg_cost,currency,status)
                   values (%s,'TFSA','momentum','tranche2',50,50.0,'USD','open')""", (ticker,))
    cur.connection.commit()


def test_the_book_holds_a_position_in_one_open_row(db):
    """A11's door, closed where it opened. `guard_book` cannot tell a chat session from a job —
    both arrive as `postgres` — so the rule is the schema's: a second open row for a position is
    refused for every role, the owner included. The key is the POSITION, (account, ticker): the
    same name in another account is another position."""
    with db.cursor() as cur:
        _universe(cur, "N00.US")
        ledger.record(cur, dict(ticker="N00.US", account="TFSA", side="buy", qty=140,
                                price=85.45, trade_date="2026-08-17"), "stated", "chat")
        db.commit()
        with pytest.raises(psycopg.errors.UniqueViolation, match="book_one_open_row_per_position"):
            cur.execute("""insert into book (ticker,account,sleeve,lot,qty,avg_cost,currency,status)
                           values ('N00.US','TFSA','levered','tranche2',139,86.30,'USD','open')""")
        db.rollback()
        assert [(lot, q) for _, lot, q in _open_rows(cur, "N00.US")] == [("core", 140.0)]

        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,currency,status)
                       values ('N00.US','RRSP','reserve',5,80.0,'USD','open')""")
        db.commit()
        cur.execute("select count(*) from book where ticker = 'N00.US' and status = 'open'")
        assert cur.fetchone()[0] == 2, "one open row in each account"


def test_a_position_held_in_two_book_rows_is_refused_rather_than_picked(db):
    """A11, where the index is not. The function moved whichever open row Postgres returned first:
    tranche three would have set ONE of VXC's rows to 289 and left the other on top of it (428 or
    568), and the full sale would close one row and leave the other open for ever — a phantom that
    sells, holds a §3.5 slot and is marked into NAV. Which row is the position is the broker's fact,
    so the ledger refuses to choose (§0.2), says which position, and moves neither row."""
    with world.book_before_069(db), db.cursor() as cur:
        _split(cur)
        before = _open_rows(cur, "N00.US")
        assert sum(q for _, _, q in before) == 418.0

        for side, qty in (("buy", 10), ("sell", 279)):          # tranche three, then the exit
            cur.execute("savepoint attempt")
            with pytest.raises(psycopg.errors.RaiseException,
                               match=r"TFSA N00\.US in 2 open rows .* against a ledger of"):
                ledger.record(cur, dict(ticker="N00.US", account="TFSA", side=side, qty=qty,
                                        price=87.0, trade_date="2026-10-15",
                                        external_ref=f"ws-{side}"), "broker", "csv")
            cur.execute("rollback to savepoint attempt")
            assert _open_rows(cur, "N00.US") == before, f"the {side} moved neither row"


def test_a_position_split_across_rows_is_a_real_break_even_where_the_rows_add_up(db):
    """A11, where the index is not. Every summed reader counts both rows and the ledger refuses to
    move them, so `v_ledger_vs_book` lists a split position as a real break whatever the sums say
    — here the rows add up to the ledger exactly, and the view used to read that as agreement."""
    with world.book_before_069(db), db.cursor() as cur:
        cur.execute("set constraints ledger_moves_the_book immediate")
        _universe(cur, "N00.US")
        ledger.record(cur, dict(ticker="N00.US", account="TFSA", side="buy", qty=100,
                                price=50.0, trade_date="2026-08-17"), "stated", "chat")
        cur.execute("update book set qty = 60 where ticker = 'N00.US'")
        cur.execute("""insert into book (ticker,account,sleeve,lot,qty,avg_cost,currency,status)
                       values ('N00.US','TFSA','levered','tranche2',40,50.0,'USD','open')""")

        cur.execute("""select ticker, ledger_qty, book_qty, predates_the_ledger
                         from v_ledger_vs_book""")
        assert cur.fetchall() == [("N00.US", 100.0, 100.0, False)]
        cur.execute("select open_rows from v_ledger_vs_book where ticker = 'N00.US'")
        assert cur.fetchone()[0] == 2


def _production_vxc(cur, stray_qty=139.0):
    """NONREG VXC.TO exactly as production holds it on 2026-10-07: txns 25 and 39 in the ledger
    (279), book 22 carrying both, and book 28 restating txn 39 beside it."""
    _universe(cur, "VXC.TO")
    cur.execute("""insert into transactions (ticker,account,side,qty,price,currency,trade_date,
                                             confirmed,confirmed_at,applied_at,grade,source)
                   values ('VXC.TO','NONREG','buy',140,85.45,'CAD','2026-08-17',true,now(),now(),
                           'broker','ws_export_2026-08-17'),
                          ('VXC.TO','NONREG','buy',139,86.30,'CAD','2026-09-22',true,now(),now(),
                           'broker','zak_chat_2026-09-28')""")
    cur.execute("""insert into book (id,ticker,account,sleeve,lot,qty,avg_cost,currency,opened_at,
                                     status,note) overriding system value
                   values (22,'VXC.TO','NONREG','levered','tranche1',279,85.873476702509,'CAD',
                           '2026-08-17','open','§2.3 tranche 1'),
                          (28,'VXC.TO','NONREG','levered','tranche2',%s,86.30,'CAD',
                           '2026-09-22','open','§2.3 tranche 2, applied in chat')""", (stray_qty,))


def test_069_closes_the_row_zak_confirmed_is_not_a_position(db):
    """A13, on Zak's word (2026-10-07: the NONREG account holds 279 VXC.TO, not 418). The stray row
    is closed the way the function closes a position — never deleted (§0.6) — with a note saying
    who confirmed what; the row the ledger moves carries the ledger; the break is gone; and the
    index that makes the next one impossible exists."""
    with world.book_before_069(db), db.cursor() as cur:
        _production_vxc(cur)
        cur.execute(MIGRATION_069.read_text())

        cur.execute("""select id, qty, status, closed_at = current_date, note from book
                        where ticker = 'VXC.TO' order by id""")
        (keep, kept_qty, kept_status, _, kept_note), (stray, qty, status, closed_today, note) = (
            cur.fetchall())
        assert (keep, kept_qty, kept_status, kept_note) == (22, 279.0, "open", "§2.3 tranche 1")
        assert (stray, qty, status, closed_today) == (28, 0.0, "closed", True)
        assert note.startswith("§2.3 tranche 2, applied in chat | Closed by migration 069")
        assert "Zak's confirmation of 2026-10-07" in note and "A13" in note
        cur.execute("select count(*) from v_ledger_vs_book")
        assert cur.fetchone()[0] == 0, "the ledger and the book agree"
        cur.execute("select 1 from pg_indexes where indexname = 'book_one_open_row_per_position'")
        assert cur.fetchone() is not None


def test_069_stops_rather_than_apply_a_confirmation_to_another_state(db):
    """A13. Zak confirmed one state — book 28 holding 139 beside book 22. If the book has moved
    since (the old function picks a VXC row at random on the next tranche), closing row 28 would
    apply his confirmation to a state he never saw. The migration then closes nothing, refuses to
    build the index over a split, and names every split position, in one transaction that leaves
    the database exactly as it was."""
    with world.book_before_069(db), db.cursor() as cur:
        _production_vxc(cur, stray_qty=289.0)
        with pytest.raises(psycopg.errors.RaiseException,
                           match=r"migration 069 stops: .*NONREG VXC\.TO \(book 22 lot tranche1: "
                                 r"279, book 28 lot tranche2: 289\)"):
            cur.execute(MIGRATION_069.read_text())


def test_a_row_left_open_after_the_ledger_sold_the_name_out_is_a_break(db):
    """A26. `v_ledger_positions` drops a name whose rows net to zero, so a SOLD-OUT name read
    exactly like one the ledger had never heard of: `predates_the_ledger` true, "the export has not
    landed yet", amber and self-healing — for a row no export will ever heal. The question is
    whether history EXISTS, the same one `yuna_book_from_ledger` asks before it touches anything."""
    with db.cursor() as cur:
        _sold_out_with_a_row_left_open(cur)
        cur.execute("""select ticker, ledger_qty, book_qty, predates_the_ledger
                         from v_ledger_vs_book""")
        assert cur.fetchall() == [("N00.US", None, 50.0, False)], "a break, not a pre-ledger row"


def test_the_sweep_closes_a_row_the_ledger_sold_out(db):
    """A76. The sweep walked only the names `v_ledger_positions` lists, which leaves out every name
    the ledger has sold out — so the one stray it most needed to close was the one it never saw,
    and it reported nothing to do."""
    with db.cursor() as cur:
        _sold_out_with_a_row_left_open(cur)
        assert ledger.rebuild_book(cur) == ["TFSA N00.US: 50 -> closed"]
        db.commit()
        assert _open_rows(cur, "N00.US") == []
        assert desk.held_book(cur) == {}, "and no slot is held by it tonight"


def test_the_sweep_never_reports_a_repair_it_did_not_make(db):
    """A76, where the index is not. Recording anything through `ledger.py` sweeps the whole book,
    and the sweep printed the ledger's quantity as the book's new state: VXC.TO read "418 -> 279" on
    every pass while the book stayed at 418, so an operator who ran it to clear the double count
    would read success and stop. A split position is now refused by name — raised to a caller with
    nowhere to report it, listed for one that has — the book is left exactly as it was, and the rest
    of the sweep still runs."""
    with world.book_before_069(db), db.cursor() as cur:
        _split(cur)
        _universe(cur, "MU.US")
        ledger.record(cur, dict(ticker="MU.US", account="TFSA", side="buy", qty=2, price=954.58,
                                trade_date="2026-08-14"), "stated", "chat")
        cur.execute("update book set qty = 1 where ticker = 'MU.US'")   # something to repair

        cur.execute("savepoint sweep")
        with pytest.raises(psycopg.errors.RaiseException, match=r"TFSA N00\.US in 2 open rows"):
            ledger.rebuild_book(cur)
        cur.execute("rollback to savepoint sweep")

        refused = []
        assert ledger.rebuild_book(cur, refused=refused) == ["TFSA MU.US: 1 -> 2"]
        assert len(refused) == 1 and refused[0].startswith("TFSA N00.US: book holds")
        assert sum(q for _, _, q in _open_rows(cur, "N00.US")) == 418.0, "left as it was"
