"""The book reconciliation of 2026-08-04, run against the committed manifest.

Four fills never reached the book. It was correct through 2026-07-29 and blind to the session
after it, and the cost was not bookkeeping: every brief on 2026-08-05 armed RS.US as a new
momentum entry at trigger 419.83 — the price Zak had already filled at.

The manifest in `data/fills/` is the input, so these assertions are on the real numbers: a typo in
the export fails here rather than in the book.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import arming                                                             # noqa: E402
import fills                                                              # noqa: E402
import fixtures as world                                                  # noqa: E402

MANIFEST = (pathlib.Path(__file__).resolve().parent.parent.parent
            / "data" / "fills" / "2026-08-04-wealthsimple.json")


@pytest.fixture
def the_book_before(db):
    """What production held on the morning of 2026-08-05: VRT still open at 0.0031, no NUE, no RS."""
    with db.cursor() as cur:
        for tk in ("VRT.US", "NUE.US", "RS.US"):
            world.add_name(cur, tk, industry="Steel")
            world.flat_then_base(cur, tk)
        cur.execute("""insert into book (ticker,account,sleeve,lot,qty,avg_cost,currency,
                                         opened_at,status)
                       values ('VRT.US','TFSA','unassigned','core',0.0031,332.5,'USD',
                               '2026-06-03','open')""")
    db.commit()
    return db


def book(conn):
    with conn.cursor() as cur:
        cur.execute("""select ticker, qty, avg_cost, sleeve, status, stop from book
                       order by ticker""")
        return {r[0]: dict(qty=float(r[1]), cost=float(r[2]), sleeve=r[3], status=r[4],
                           stop=r[5]) for r in cur.fetchall()}


def test_the_manifest_reproduces_the_broker_export(db, monkeypatch):
    """Arithmetic first: net cash is qty x price **in USD**, and the two NUE lots average 267.715.

    The currency was worth pinning. Read as CAD, the VRT line does not reconcile — 0.0031 x 274.182
    is 0.85 USD and 1.20 CAD, and only one of those is the number on the export.
    """
    rows = {f["ref"]: f for _, f in fills.manifests(str(MANIFEST))}
    assert len(rows) == 4
    for f in rows.values():
        cash = f["qty"] * f["price"] * (1 if f["side"] == "sell" else -1)
        assert cash == pytest.approx(f["net_cash_usd"], abs=0.01), f["ref"]
    nue = [f for f in rows.values() if f["ticker"] == "NUE.US"]
    total = sum(f["qty"] for f in nue)
    assert total == 32
    assert sum(f["qty"] * f["price"] for f in nue) / total == pytest.approx(267.715)


def test_the_fills_land_in_the_book_through_the_ticket_path(the_book_before, monkeypatch):
    """NUE 32 @ 267.715 new · RS 10 @ 419.83 new · VRT closes. Through tickets and transactions,
    because §4.3 keeps both the ledger and the book job-written and R4 routes a fill with no
    ticket behind it onto one."""
    monkeypatch.setenv("FILLS_GLOB", str(MANIFEST))
    assert fills.main() == 0

    after = book(the_book_before)
    assert after["NUE.US"]["qty"] == 32
    assert after["NUE.US"]["cost"] == pytest.approx(267.715)
    assert after["NUE.US"]["sleeve"] == "momentum"
    assert after["RS.US"]["qty"] == 10
    assert after["RS.US"]["cost"] == pytest.approx(419.83)
    assert after["VRT.US"]["status"] == "closed" and after["VRT.US"]["qty"] == 0

    with the_book_before.cursor() as cur:
        cur.execute("""select count(*) from transactions where confirmed and applied_at is not null""")
        assert cur.fetchone()[0] == 4, "settled tickets derive settled, applied ledger rows"


def test_running_it_twice_applies_nothing_twice(the_book_before, monkeypatch):
    """Every fill carries a ref, and a ref already on a ticket is skipped."""
    monkeypatch.setenv("FILLS_GLOB", str(MANIFEST))
    assert fills.main() == 0
    first = book(the_book_before)
    assert fills.main() == 0
    assert book(the_book_before) == first
    with the_book_before.cursor() as cur:
        cur.execute("select count(*) from transactions")
        assert cur.fetchone()[0] == 4


def test_a_dry_run_writes_nothing(the_book_before, monkeypatch):
    """DRY_RUN means compute everything and write nothing — including through the two passes this
    job borrows from `score`, which used to fold the book regardless of it."""
    monkeypatch.setenv("FILLS_GLOB", str(MANIFEST))
    monkeypatch.setenv("DRY_RUN", "true")
    assert fills.main() == 0
    with the_book_before.cursor() as cur:
        cur.execute("select count(*) from tickets")
        assert cur.fetchone()[0] == 0
        cur.execute("select count(*) from transactions")
        assert cur.fetchone()[0] == 0
    assert book(the_book_before)["VRT.US"]["status"] == "open"


def test_a_dry_run_still_says_what_it_would_do(the_book_before, monkeypatch):
    """A rehearsal nobody can read is not a rehearsal — the run row names every pending fill."""
    monkeypatch.setenv("FILLS_GLOB", str(MANIFEST))
    assert fills.main() == 0                      # write the tickets and the ledger for real
    with the_book_before.cursor() as cur:
        cur.execute("update transactions set applied_at = null")   # as if the book were behind
    the_book_before.commit()

    monkeypatch.setenv("DRY_RUN", "true")
    assert fills.main() == 0
    with the_book_before.cursor() as cur:
        cur.execute("select detail from runs where job='fills' order by id desc limit 1")
        detail = cur.fetchone()[0]
    assert len(detail["fills_would_apply"]) == 4
    with the_book_before.cursor() as cur:
        cur.execute("select count(*) from transactions where applied_at is not null")
        assert cur.fetchone()[0] == 0, "the rehearsal applied nothing"


def test_a_momentum_position_that_arrives_without_a_stop_gets_one(the_book_before, monkeypatch):
    """§3.2: initial stop = higher of the base's final-contraction low or entry − 8%.

    A ticket the machine armed carries its stop. A discretionary fill carries none, and the
    ratchet only ever moves an existing stop upward — so the position would have opened
    unprotected and stayed that way: nothing on the stop sheet, nothing for §4.6's broker GTC to
    mirror.
    """
    monkeypatch.setenv("FILLS_GLOB", str(MANIFEST))
    assert fills.main() == 0

    after = book(the_book_before)
    assert float(after["RS.US"]["stop"]) == pytest.approx(419.83 * 0.92, rel=1e-6)
    # the add does not re-open the question — stops ratchet up, never down (§3.2)
    assert float(after["NUE.US"]["stop"]) == pytest.approx(272.84 * 0.92, rel=1e-6)


def test_the_base_low_wins_when_it_is_the_higher_stop(the_book_before, monkeypatch):
    """"Higher of" is the rule, and a live base is the better shelf when there is one."""
    with the_book_before.cursor() as cur:
        world.candidate(cur, "RS.US", pivot=419.83, stop=400.0)
        cur.execute("update candidates set base_low = 400.0 where ticker='RS.US'")
    the_book_before.commit()
    monkeypatch.setenv("FILLS_GLOB", str(MANIFEST))
    assert fills.main() == 0
    assert float(book(the_book_before)["RS.US"]["stop"]) == pytest.approx(400.0)
