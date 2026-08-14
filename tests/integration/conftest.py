"""Integration harness — a real Postgres, the real migrations, the real jobs.

Every defect that has actually bitten this build lived at a seam: a column one function read and
none wrote, a NOT NULL with no default, a pivot taken from the wrong table. None of them were
findable by reading a formula, and all of them were findable by running the job over data and
looking at what came out. That is what this harness does, in CI, in seconds.

Needs `DATABASE_URL` pointing at a throwaway database. CI supplies a Postgres service container;
locally, `tests/integration/local_pg.sh` starts one. Without it these tests skip rather than fail,
so `pytest tests/` stays green on a machine with no database.
"""
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("EODHD_API_KEY", "integration-stub-never-called")

pytest.importorskip("psycopg")
import psycopg                                                            # noqa: E402


def _url():
    return os.environ.get("DATABASE_URL", "")


pytestmark = pytest.mark.skipif(not _url(), reason="no DATABASE_URL — integration tests skipped")


@pytest.fixture(scope="session")
def migrated():
    """Apply every migration once, exactly as the `migrate` workflow does."""
    if not _url():
        pytest.skip("no DATABASE_URL")
    out = subprocess.run([sys.executable, str(ROOT / "src" / "migrate.py")],
                         capture_output=True, text=True, env={**os.environ})
    assert out.returncode == 0, f"migrations failed:\n{out.stdout}\n{out.stderr}"
    return _url()


@pytest.fixture
def db(migrated):
    """A connection with the machine's own tables emptied — migration seed data included.

    Truncating rather than re-migrating keeps the suite fast, and truncating *everything* the jobs
    write means each test states its own world explicitly. A test that depends on leftover rows
    from another test is not a test.
    """
    with psycopg.connect(migrated) as conn:
        with conn.cursor() as cur:
            # `balances` joined this list on 2026-08-05. It is not guarded, so the schema test
            # never demanded it — but it is an append ledger with a "latest row wins" read, so a
            # row left behind by one test became the anchor every later test read, and a cash
            # figure nobody wrote governed the funding checks and NAV.
            # `rulings` and `learnings` joined this list on 2026-08-07, and they are the sharpest
            # case yet: neither is guarded — §4.3 puts both on the session write list — so the
            # schema test could not demand them, and both are append ledgers read latest-wins.
            # A ruling written by one test therefore governed every later test AND every later
            # pytest RUN, because the database outlives the process. Found the same day the jobs
            # started reading the ledger, on a sign-off nobody in that test had logged.
            cur.execute("""truncate armed, candidates, queue, bench, book, tickets, transactions,
                                    observations, briefs, nav_snapshots, earnings, prices,
                                    gate_state, group_strength, quarantine, corporate_actions,
                                    fundamentals, balances, rulings, learnings, backtest_runs,
                                    backtest_trades, backtest_equity, runs, bill_rates,
                                    universe_excluded, push_study restart identity
                                    cascade""")
            cur.execute("delete from universe")
            # config is append-only by design (§4.3), so a test that overrides a threshold leaves
            # its row behind and silently governs every later test — and every later *run*, since
            # the database outlives pytest. Found exactly that way: a 5% single-name cap from one
            # test blocked six compounder entries in another.
            cur.execute("delete from config where set_by='test'")
            cur.execute("""insert into accounts (code,label,kind,currency) values
                             ('TFSA','test tfsa','registered','CAD'),
                             ('RRSP','test rrsp','registered','CAD'),
                             ('NONREG','test nonreg','taxable','CAD')
                           on conflict (code) do nothing""")
        conn.commit()
        yield conn


@pytest.fixture
def fx(db):
    """USDCAD, because `nav_cad` needs it and every CAD figure carries its rate (§4.1)."""
    with db.cursor() as cur:
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values ('USDCAD.FOREX','USDCAD','fx','CAD','active')
                       on conflict (ticker) do nothing""")
        cur.execute("""insert into prices (ticker,d,close) values ('USDCAD.FOREX',current_date,1.40)
                       on conflict (ticker,d) do update set close=1.40""")
    db.commit()
    return 1.40
