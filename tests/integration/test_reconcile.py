"""§4.1's `reconcile`, against a real database.

This is the only job in the system that moves the book off an outside document, which makes its
failure modes the expensive kind. A fill folded twice doubles a position. A position break waved
through means §3.5 sizes and queues against a book that does not exist. A ticket advanced to
`reconciled` on an account that did not verify puts a green attestation on a lie, and §4.4's age
gauge then reads clean for ever.

Each test below is one of those.
"""
import json
import pathlib
import subprocess
import sys

import psycopg
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import reconcile                                                          # noqa: E402


def _universe(cur, *tickers):
    for t in tickers:
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values (%s,%s,'stock','USD','active') on conflict do nothing""", (t, t))


def _ticket(cur, ticker, action, qty, *, session="2026-08-14", state="approved"):
    cur.execute("""insert into tickets (session_date, ticker, account, sleeve, action, clause,
                                        order_type, qty, state)
                   values (%s,%s,'TFSA','momentum',%s,%s,'market',%s,%s) returning id""",
                (session, ticker, action, "fill" if action == "buy" else "rank_exit", qty, state))
    return cur.fetchone()[0]


def _fill(ref, ticker, side, qty, price, date="2026-08-17"):
    return dict(ref=ref, ticker=ticker, side=side, qty=qty, price=price, trade_date=date, fees=0)


def test_a_receipt_opens_the_position_and_settles_its_ticket(db, migrated):
    """§4.3: Zak's execution is the event, and the receipt is what the system learns it from."""
    with db.cursor() as cur:
        _universe(cur, "SNDK.US")
        tid = _ticket(cur, "SNDK.US", "buy", 24)
        f = _fill("ws-1", "SNDK.US", "buy", 24, 1650.10)
        txn, what = reconcile.fold_fill(cur, "m.json", "TFSA", f)
        settled, orphans = reconcile.settle_tickets(cur, "TFSA", [f])
        db.commit()

        assert txn is not None and what == "folded"
        assert not orphans and len(settled) == 1
        cur.execute("""select qty, avg_cost, entry_fill, status, sleeve from book
                        where ticker = 'SNDK.US'""")
        # `momentum` since migration 064, and the history of this one assertion is the history of
        # the label. 059 wrote 'book' on the reading that the label had stopped deciding anything;
        # 060 corrected it to `unassigned` — "the ledger knows a trade happened and in which
        # account, and genuinely does not know which sleeve it belongs to" (§0.3). Both missed
        # that THIS row has a ticket behind it, and the ticket names the sleeve: `sheet.SLEEVE`,
        # §2.1's placement ruling, approved and executed by Zak. Zak, 2026-09-02, on three real
        # positions reading `unassigned` in the brief: "Why are they unassigned?? ... They were
        # recommended to me." A ticket-less row still lands `unassigned` — see
        # `test_a_position_the_engine_proposed_carries_the_tickets_sleeve` and `test_ledger`.
        #
        # `approx` on the cost for the same reason the sleeve changed: avg_cost is now DERIVED —
        # sum(qty x price) / sum(qty) over the ledger — where it used to be the receipt's price
        # copied across. One lot at 1650.10 comes back as 1650.0999999999997, and a book that
        # recomputes is worth a float ulp.
        qty, cost, entry, status, sleeve = cur.fetchone()
        assert (qty, status, sleeve) == (24.0, "open", "momentum")
        assert cost == pytest.approx(1650.10) and entry == pytest.approx(1650.10)
        cur.execute("select state, executed_at is not null from tickets where id = %s", (tid,))
        assert cur.fetchone() == ("executed", True)


def test_the_same_receipt_read_twice_folds_once(db, migrated):
    """The chain re-fires on the retry ingest by design. A doubled position is a doubled slot."""
    with db.cursor() as cur:
        _universe(cur, "MU.US")
        f = _fill("ws-2", "MU.US", "buy", 41, 971.66)
        first, _ = reconcile.fold_fill(cur, "m.json", "TFSA", f)
        second, what = reconcile.fold_fill(cur, "m.json", "TFSA", f)
        db.commit()

        assert first is not None
        assert second is None and what == "already folded"
        cur.execute("select qty from book where ticker = 'MU.US'")
        assert cur.fetchone()[0] == 41.0, "read twice, folded once"
        cur.execute("select count(*) from transactions where broker_ref = 'ws-2'")
        assert cur.fetchone()[0] == 1


def test_a_partial_fill_averages_the_cost_but_never_moves_the_entry_fill(db, migrated):
    """§029: add bands measure from the ENTRY fill, never from `avg_cost`, which moves with each
    add — so the second add would measure from a base the first had already shifted."""
    with db.cursor() as cur:
        _universe(cur, "WDC.US")
        reconcile.fold_fill(cur, "m.json", "TFSA", _fill("ws-3", "WDC.US", "buy", 40, 500.00))
        reconcile.fold_fill(cur, "m.json", "TFSA", _fill("ws-4", "WDC.US", "buy", 40, 520.00))
        db.commit()
        cur.execute("select qty, avg_cost, entry_fill from book where ticker = 'WDC.US'")
        qty, avg, entry = cur.fetchone()
        assert (qty, avg, entry) == (80.0, 510.0, 500.0)


def test_a_full_sell_closes_the_position_rather_than_leaving_a_zero_row(db, migrated):
    """§3.5 counts held slots. A closed position left at status `open` with qty 0 occupies one of
    the five for ever, and no entry can ever fill it."""
    with db.cursor() as cur:
        _universe(cur, "NUE.US")
        reconcile.fold_fill(cur, "m.json", "TFSA", _fill("ws-5", "NUE.US", "buy", 32, 180.0))
        reconcile.fold_fill(cur, "m.json", "TFSA", _fill("ws-6", "NUE.US", "sell", 32, 191.0))
        db.commit()
        cur.execute("select qty, status, closed_at from book where ticker = 'NUE.US'")
        qty, status, closed = cur.fetchone()
        assert (qty, status) == (0.0, "closed") and closed is not None


def test_a_sell_of_something_never_bought_stops_the_job(db, migrated):
    """Silent failure is the enemy: the book and the broker disagree about what EXISTS, which is
    the one disagreement that cannot be repaired by arithmetic.

    Migration 059 moved where this is caught and improved the basis. It used to be "the book holds
    no open position", read off `book`; it is now the LEDGER refusing to drive a position below
    zero, which is the same event measured against the history instead of against whatever the book
    happened to say. The message names the repair, because there is a real one: a holding that
    predates the ledger needs its opening `confirm` row before the sells that follow it.
    """
    with db.cursor() as cur:
        _universe(cur, "GHOST.US")
        with pytest.raises(psycopg.errors.RaiseException, match="history for this name is incomplete"):
            reconcile.fold_fill(cur, "m.json", "TFSA", _fill("ws-7", "GHOST.US", "sell", 10, 5.0))
        db.rollback()


def test_a_receipt_missing_its_ref_stops_the_job(db, migrated):
    """No ref means no idempotence, and a receipt that cannot be recognised on a re-run is a
    position that doubles the next time the chain fires."""
    with db.cursor() as cur:
        f = _fill("ws-8", "MU.US", "buy", 1, 100.0)
        del f["ref"]
        with pytest.raises(SystemExit, match="missing 'ref'"):
            reconcile.fold_fill(cur, "m.json", "TFSA", f)


def test_a_break_is_found_in_both_directions(db, migrated):
    """They fail differently. A name the broker holds and the book does not can never be queued for
    exit; a name the book holds and the broker does not blocks a slot with a phantom."""
    with db.cursor() as cur:
        _universe(cur, "AAA.US", "BBB.US", "CCC.US")
        for t, q in (("AAA.US", 10), ("BBB.US", 20)):
            cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                           values (%s,'TFSA','momentum',%s,100,'open')""", (t, q))
        db.commit()
        breaks = reconcile.compare_positions(cur, "TFSA", [
            dict(ticker="AAA.US", qty=10),      # agrees
            dict(ticker="BBB.US", qty=25),      # quantity differs
            dict(ticker="CCC.US", qty=7),       # broker only
        ])                                      # book-only: nothing here, so none

    found = {b["ticker"]: b for b in breaks}
    assert set(found) == {"BBB.US", "CCC.US"}
    assert "differ by +5" in found["BBB.US"]["why"]
    assert found["CCC.US"]["book"] is None

    # and the other direction, on its own
    with db.cursor() as cur:
        breaks = reconcile.compare_positions(cur, "TFSA", [dict(ticker="AAA.US", qty=10)])
    assert [b["ticker"] for b in breaks] == ["BBB.US"]
    assert breaks[0]["broker"] is None and "phantom" in breaks[0]["why"]


def test_a_position_break_holds_the_ticket_at_executed(db, migrated, tmp_path):
    """§4.4: any red holds buys. The attestation is the ticket state, so a break must not let one
    reach `reconciled` — a green age gauge computed off an unverified book is worse than a red one.
    """
    with db.cursor() as cur:
        _universe(cur, "SNDK.US")
        _ticket(cur, "SNDK.US", "buy", 24)
    db.commit()
    doc = {"as_of": "2026-08-17", "account": "TFSA",
           "fills": [_fill("ws-9", "SNDK.US", "buy", 24, 1650.10)],
           "positions": [{"ticker": "SNDK.US", "qty": 30}]}       # the broker says 30, not 24
    (tmp_path / "r.json").write_text(json.dumps(doc))

    out = subprocess.run([sys.executable, str(ROOT / "src" / "reconcile.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "RECONCILE_GLOB": str(tmp_path / "*.json"), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    assert "BREAK" in out.stdout
    with db.cursor() as cur:
        cur.execute("select status, detail from runs where job='reconcile' order by id desc limit 1")
        status, detail = cur.fetchone()
        assert status == "red"
        assert detail["breaks"][0]["ticker"] == "SNDK.US"
        cur.execute("select state from tickets where ticker = 'SNDK.US'")
        assert cur.fetchone()[0] == "executed", "executed, but NOT reconciled"


def test_a_clean_manifest_closes_the_loop(db, migrated, tmp_path):
    with db.cursor() as cur:
        _universe(cur, "SNDK.US")
        _ticket(cur, "SNDK.US", "buy", 24)
    db.commit()
    doc = {"as_of": "2026-08-17", "account": "TFSA",
           "fills": [_fill("ws-10", "SNDK.US", "buy", 24, 1650.10)],
           "positions": [{"ticker": "SNDK.US", "qty": 24}]}
    (tmp_path / "r.json").write_text(json.dumps(doc))

    out = subprocess.run([sys.executable, str(ROOT / "src" / "reconcile.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "RECONCILE_GLOB": str(tmp_path / "*.json"), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        cur.execute("select status from runs where job='reconcile' order by id desc limit 1")
        assert cur.fetchone()[0] == "green"
        cur.execute("select state, reconciled_at is not null from tickets where ticker='SNDK.US'")
        assert cur.fetchone() == ("reconciled", True)
        cur.execute("select last_receipt, last_attested from v_reconciliation_age")
        receipt, attested = cur.fetchone()
        assert str(receipt) == "2026-08-17" and attested is not None


def test_a_manifest_with_no_positions_block_reconciles_nothing_and_says_so(db, migrated, tmp_path):
    """Folding a fill and then trusting the arithmetic that folded it proves nothing. Only the
    outside witness reconciles, so a manifest without one must not read as a clean night."""
    with db.cursor() as cur:
        _universe(cur, "MU.US")
        _ticket(cur, "MU.US", "buy", 41)
    db.commit()
    (tmp_path / "r.json").write_text(json.dumps(
        {"account": "TFSA", "fills": [_fill("ws-11", "MU.US", "buy", 41, 971.66)]}))

    out = subprocess.run([sys.executable, str(ROOT / "src" / "reconcile.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "RECONCILE_GLOB": str(tmp_path / "*.json"), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        cur.execute("select status, detail from runs where job='reconcile' order by id desc limit 1")
        status, detail = cur.fetchone()
        assert status == "amber"
        assert any("no `positions` block" in a for a in detail["amber"])
        cur.execute("select state from tickets where ticker='MU.US'")
        assert cur.fetchone()[0] == "executed", "the fill settled; nothing was reconciled"


def test_a_fill_with_no_engine_ticket_is_folded_and_reported(db, migrated, tmp_path):
    """§0.2 makes execution Zak's prerogative, so a trade outside the sheet is not an error. It is
    still reported: a position the engine did not propose is one it will not manage."""
    with db.cursor() as cur:
        _universe(cur, "TSLA.US")
    db.commit()
    (tmp_path / "r.json").write_text(json.dumps(
        {"account": "TFSA", "fills": [_fill("ws-12", "TSLA.US", "buy", 5, 400.0)],
         "positions": [{"ticker": "TSLA.US", "qty": 5}]}))

    out = subprocess.run([sys.executable, str(ROOT / "src" / "reconcile.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "RECONCILE_GLOB": str(tmp_path / "*.json"), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    with db.cursor() as cur:
        cur.execute("select status, detail from runs where job='reconcile' order by id desc limit 1")
        status, detail = cur.fetchone()
        assert status == "amber"
        assert len(detail["orphan_fills"]) == 1
        cur.execute("select qty from book where ticker = 'TSLA.US'")
        assert cur.fetchone()[0] == 5.0, "the book still learns the truth"


def test_no_manifest_is_an_ordinary_night(db, migrated, tmp_path):
    """§4.4 gauges the AGE of the last reconciliation. A night with no export is not a failure —
    the gauge is what notices a stale one, and it needs this job to keep running to say so."""
    out = subprocess.run([sys.executable, str(ROOT / "src" / "reconcile.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "RECONCILE_GLOB": str(tmp_path / "nothing-*.json"),
                              "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    assert "no manifest" in out.stdout
    with db.cursor() as cur:
        cur.execute("select status from runs where job='reconcile' order by id desc limit 1")
        assert cur.fetchone()[0] == "green"


def test_dry_run_writes_nothing_but_still_compares(db, migrated, tmp_path):
    """"Compute everything, write nothing" — and the comparison is the everything. A dry run that
    skipped it would answer whether the file parses, not whether the book agrees."""
    with db.cursor() as cur:
        _universe(cur, "MU.US")
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('MU.US','TFSA','momentum',41,900,'open')""")
    db.commit()
    (tmp_path / "r.json").write_text(json.dumps(
        {"account": "TFSA", "fills": [_fill("ws-13", "MU.US", "buy", 41, 971.66)],
         "positions": [{"ticker": "MU.US", "qty": 82}]}))     # broker says 82; the book says 41

    out = subprocess.run([sys.executable, str(ROOT / "src" / "reconcile.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable", "DRY_RUN": "true",
                              "RECONCILE_GLOB": str(tmp_path / "*.json"), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    assert "BREAK" in out.stdout, "the disagreement is reported even though nothing is written"
    with db.cursor() as cur:
        cur.execute("select count(*) from transactions")
        assert cur.fetchone()[0] == 0
        cur.execute("select qty from book where ticker = 'MU.US'")
        assert cur.fetchone()[0] == 41.0, "the book is untouched"


# ---- the chat route: §4.3's ORDINARY path, restored 2026-08-18 ---------------------------------
#
# The ghost-book morning. A full §6.1 liquidation was reported in chat on the 17th, landed on
# tickets, and never reached `book` — so the next brief rendered seven positions the broker no
# longer held and proposed a NUE sell Zak had already executed.
#
# The cause was mine. §4.3's write list says a session writes TICKETS and never the ledger: it puts
# `fill_*` on the ticket and a JOB derives the transaction and folds it. That job was
# `arming.sync_fills_from_tickets` + `apply_fills`, called by the legacy `score` and `fills` — and
# §6.3 retired both from the schedule while `reconcile` replaced only the MANIFEST half.

def _filled_ticket(cur, ticker, action, qty, price, *, state="executed", sleeve="momentum",
                   session="2026-08-14", fill_date="2026-08-17"):
    cur.execute("""insert into tickets (session_date, ticker, account, sleeve, action, clause,
                                        order_type, qty, state, fill_qty, fill_price, fill_date)
                   values (%s,%s,'TFSA',%s,%s,%s,'market',%s,%s,%s,%s,%s)
                   returning id""",
                (session, ticker, sleeve, action, "fill" if action == "buy" else "rank_exit",
                 qty, state, qty, price, fill_date))
    return cur.fetchone()[0]


def test_a_position_the_engine_proposed_carries_the_tickets_sleeve(db, migrated):
    """Migration 064. Zak, 2026-09-02, on SNDK, WDC and RVMD reading `unassigned` in the brief:
    *"Why are they unassigned?? ... They were recommended to me... What's broken there?"*

    What broke: 059 moved the book's movement into `yuna_book_from_ledger`, and the ticket's sleeve
    — which the retired fill loop used to copy across — stopped crossing. 060 named the gap
    honestly (`unassigned`: the ledger does not know) and `sleeve_divergence` then reported the
    same three rows every night. With a ticket behind the row the ledger DOES know: the sheet
    wrote the sleeve on the ticket as §2.1's placement ruling, and Zak executed it.

    Three facts in one history: a ticketed fill opens the position under the ticket's sleeve; a
    ticket-less top-up (AXTI's +25 on 2026-08-28) keeps it; and a label set by hand outranks any
    later ticket. The ticket-less OPENING still lands `unassigned` — `test_ledger` pins that half.
    """
    with db.cursor() as cur:
        _universe(cur, "SNDK.US")
        _filled_ticket(cur, "SNDK.US", "buy", 16, 1486.02)
        assert len(reconcile.derive_ticket_fills(cur)) == 1
        db.commit()                       # the deferred trigger moves the book here
        cur.execute("select sleeve, qty from book where ticker = 'SNDK.US'")
        assert cur.fetchone() == ("momentum", 16.0), "the engine's own ticket names the sleeve"

        # a broker row with no ticket behind it — Zak topping up outside the sheet
        cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                                 trade_date, confirmed, confirmed_at, grade, source)
                       values ('SNDK.US','TFSA','buy',5,1500.0,'USD','2026-08-28',true,now(),
                               'broker','export')""")
        db.commit()
        cur.execute("select sleeve, qty from book where ticker = 'SNDK.US'")
        assert cur.fetchone() == ("momentum", 21.0), "a ticket-less add does not unlabel it"

        # a label Zak set by hand is his ruling (§0.3), and no ticket rewrites it
        cur.execute("update book set sleeve = 'reserve' where ticker = 'SNDK.US'")
        _filled_ticket(cur, "SNDK.US", "buy", 4, 1510.0, session="2026-08-27",
                       fill_date="2026-08-28")
        assert len(reconcile.derive_ticket_fills(cur)) == 1
        db.commit()
        cur.execute("select sleeve, qty from book where ticker = 'SNDK.US'")
        assert cur.fetchone() == ("reserve", 25.0), "a hand-set sleeve outranks a ticket"


def test_a_fill_reported_in_chat_reaches_the_book_with_no_manifest_at_all(db, migrated):
    """The whole break, end to end: ticket -> derived ledger row -> book moved."""
    with db.cursor() as cur:
        _universe(cur, "NUE.US")
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('NUE.US','TFSA','momentum',32,267.715,'open')""")
        # What the account already held, as the ledger sees it. Since migration 059 the book is the
        # ledger's arithmetic, so a position with no rows behind it cannot be sold: the sell drives
        # it negative and `yuna_book_from_ledger` refuses.
        cur.execute("""insert into transactions (ticker,account,side,qty,price,currency,trade_date,
                                                 confirmed,confirmed_at,applied_at,grade,source)
                       values ('NUE.US','TFSA','confirm',32,267.715,'USD','2026-08-10',true,now(),
                               now(),'stated','opening balance')""")
        tid = _filled_ticket(cur, "NUE.US", "sell", 32, 266.8111)
        db.commit()

        assert reconcile.derive_ticket_fills(cur) != [], "the ledger row is derived from the ticket"
        assert reconcile.apply_unapplied(cur) != [], "and folded into the book"
        db.commit()

        cur.execute("select qty, status from book where ticker = 'NUE.US'")
        assert cur.fetchone() == (0.0, "closed")
        cur.execute("""select ticket_id, confirmed, applied_at is not null
                         from transactions where ticker = 'NUE.US'""")
        assert cur.fetchone() == (tid, True, True)


def test_the_chat_route_is_idempotent_in_both_halves(db, migrated):
    """The chain re-fires on the retry ingest, and a doubled liquidation is not recoverable."""
    with db.cursor() as cur:
        _universe(cur, "MU.US")
        _filled_ticket(cur, "MU.US", "buy", 41, 971.66)
        db.commit()
        reconcile.derive_ticket_fills(cur)
        reconcile.apply_unapplied(cur)
        db.commit()

        assert reconcile.derive_ticket_fills(cur) == [], "one transaction per ticket"
        assert reconcile.apply_unapplied(cur) == [], "applied_at is the stamp"
        db.commit()
        cur.execute("select count(*), sum(qty) from transactions where ticker = 'MU.US'")
        assert cur.fetchone() == (1, 41.0)
        cur.execute("select qty from book where ticker = 'MU.US'")
        assert cur.fetchone()[0] == 41.0


def test_a_manifest_and_a_chat_report_of_the_same_fill_move_the_book_once(db, migrated):
    """The door the ticket route opens, and the reason `fold_fill` now records `ticket_id`.

    Zak reports a fill in chat AND later exports the manifest containing it. Before this, the
    manifest transaction carried no ticket link, so `derive_ticket_fills` saw a ticket with no
    transaction and derived a SECOND row for the same fill — 82 shares of MU where 41 were bought.
    """
    with db.cursor() as cur:
        _universe(cur, "MU.US")
        tid = _ticket(cur, "MU.US", "buy", 41)                     # proposed, awaiting a receipt
        db.commit()
        reconcile.fold_fill(cur, "m.json", "TFSA", _fill("ws-99", "MU.US", "buy", 41, 971.66))
        db.commit()

        cur.execute("select ticket_id from transactions where broker_ref = 'ws-99'")
        assert cur.fetchone()[0] == tid, "the manifest row records which ticket it settles"

        # the same fill now also appears on the ticket, reported in chat
        cur.execute("""update tickets set fill_qty = 41, fill_price = 971.66,
                              fill_date = '2026-08-17', state = 'executed' where id = %s""", (tid,))
        db.commit()
        assert reconcile.derive_ticket_fills(cur) == [], "the ticket already has its ledger row"
        db.commit()

        cur.execute("select count(*) from transactions where ticker = 'MU.US'")
        assert cur.fetchone()[0] == 1
        cur.execute("select qty from book where ticker = 'MU.US'")
        assert cur.fetchone()[0] == 41.0, "41 bought, 41 in the book"


def test_a_provisional_fill_moves_the_book_and_is_graded_as_stated(db, migrated):
    """**This assertion inverted on 2026-08-18, on Zak's instruction, and the inversion is the
    point.**

    It used to read "recorded but does not move the book": confirmation was the boundary, and a
    provisional fill sat in the ledger waiting for it. Zak: *"sometimes those transactions are
    lagged... by days... so I will just tell the chat other sales so it can process the books
    correctly... those are true to me... but they might change or be tweaked by the transactions
    later. Maybe the pennies are different.... **But the engine should run assuming both.**"*

    The old rule made the book wait days for an export, and for those days the engine reasoned from
    a position Zak had already sold — the ghost book, written down as policy. The new rule records
    which KIND of truth the row is (`stated` vs `broker`) instead of refusing the provisional one,
    so the correction is a supersession rather than a delay.
    """
    with db.cursor() as cur:
        _universe(cur, "RS.US")
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('RS.US','TFSA','momentum',10,419.83,'open')""")
        cur.execute("""insert into transactions (ticker,account,side,qty,price,currency,trade_date,
                                                 confirmed,confirmed_at,applied_at,grade,source)
                       values ('RS.US','TFSA','confirm',10,419.83,'USD','2026-08-10',true,now(),
                               now(),'stated','opening balance')""")
        _filled_ticket(cur, "RS.US", "sell", 10, 419.83, state="provisional")
        db.commit()

        made = reconcile.derive_ticket_fills(cur)
        db.commit()
        assert len(made) == 1 and "stated" in made[0], "recorded, and graded as Zak's word"
        cur.execute("select grade from transactions where side = 'sell' and ticker = 'RS.US'")
        assert cur.fetchone()[0] == "stated"
        cur.execute("select qty, status from book where ticker = 'RS.US'")
        assert cur.fetchone() == (0.0, "closed"), "the engine runs on what Zak already knows"


def test_the_park_is_held_capital_and_never_one_of_the_five_slots(db, migrated):
    """§3.5 counts five slots, and the park is not one of them.

    **The protection moved from the sleeve label to the instrument, and got stronger.** It used to
    rest on folding a ticket-less receipt in as `unassigned`, because `desk.held_book` read only
    `sleeve = 'momentum'` — a label doing load-bearing work. Zak, 2026-08-18: *"As for tagging as
    pre-seed or momentum etc... I'm not so certain why we would do either. That's just the book."*
    He is right, and the label was also failing in the other direction: 20 shares of AXTI and 2 of
    MU sat in the TFSA tagged `preseed`, invisible to an engine that ranked them 2nd and 3rd.

    So the engine reads the ACCOUNT (§2.1 gives it the whole TFSA) and splits the park off by
    INSTRUMENT — SPY.US by §8, SPMO.US as §6.1(3)'s Phase-0 bridge. That is not a label anyone can
    forget to set: it is what the position IS. The park counts as engine capital, is marked in the
    equity, and can never be sold for failing to rank a stock screen it was never eligible for.
    """
    import desk
    with db.cursor() as cur:
        _universe(cur, "SPMO.US")
        cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                                 trade_date, confirmed, confirmed_at, source)
                       values ('SPMO.US','TFSA','buy',810,155.5,'USD','2026-08-17',
                               true, now(), 'chat')""")
        db.commit()
        # The book moved on the WRITE — `apply_unapplied` only stamps and advances tickets now.
        cur.execute("select qty, status from book where ticker = 'SPMO.US'")
        assert cur.fetchone() == (810.0, "open"), "the ledger row opened the position by itself"
        assert reconcile.apply_unapplied(cur) != []
        db.commit()

        assert desk.held_book(cur) == {"SPMO.US": 810.0}, "the engine sees the whole account"
        assert "SPMO.US" in desk.PARKED, "and knows this one is capital, not a slot"


def test_the_job_folds_chat_receipts_on_a_night_with_no_manifest(db, migrated, tmp_path):
    """The nightly path, as the chain runs it — this used to return early and do nothing."""
    with db.cursor() as cur:
        _universe(cur, "NUE.US")
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('NUE.US','TFSA','momentum',32,267.715,'open')""")
        cur.execute("""insert into transactions (ticker,account,side,qty,price,currency,trade_date,
                                                 confirmed,confirmed_at,applied_at,grade,source)
                       values ('NUE.US','TFSA','confirm',32,267.715,'USD','2026-08-10',true,now(),
                               now(),'stated','opening balance')""")
        _filled_ticket(cur, "NUE.US", "sell", 32, 266.8111)
    db.commit()
    out = subprocess.run([sys.executable, str(ROOT / "src" / "reconcile.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "RECONCILE_GLOB": str(tmp_path / "none-*.json"),
                              "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    assert "1 ticket fill(s) derived" in out.stdout and "1 folded into the book" in out.stdout
    with db.cursor() as cur:
        cur.execute("select qty, status from book where ticker = 'NUE.US'")
        assert cur.fetchone() == (0.0, "closed")
