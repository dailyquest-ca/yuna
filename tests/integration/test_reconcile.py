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
        assert cur.fetchone() == (24.0, 1650.10, 1650.10, "open", "momentum")
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


def test_a_sell_of_something_the_book_does_not_hold_stops_the_job(db, migrated):
    """Silent failure is the enemy: the book and the broker disagree about what EXISTS, which is
    the one disagreement that cannot be repaired by arithmetic."""
    with db.cursor() as cur:
        _universe(cur, "GHOST.US")
        with pytest.raises(SystemExit, match="the book holds no open position"):
            reconcile.fold_fill(cur, "m.json", "TFSA", _fill("ws-7", "GHOST.US", "sell", 10, 5.0))


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
