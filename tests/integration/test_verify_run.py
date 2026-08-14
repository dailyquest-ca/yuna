"""The run auditor, proved against a world with defects deliberately planted in it.

An audit that only ever passes is decoration. This builds a miniature tape carrying one of each
failure the auditor claims to detect — a lied-about headline, a monotone curve with a fabricated
drawdown, a foreign listing on a `.US` ticker, and a book holding more names than it reported —
and asserts that each one is caught by name.

The foreign-listing case is not hypothetical. On 2026-08-15 the live universe was found to contain
PLZL.US (Polyus, MOEX, roubles), IVL.US (Indorama Ventures, SET, baht), NVTK.US and MGROS.US, all
labelled `currency = USD`. Their price x volume is computed in the foreign currency, so Polyus
showed $426m of median "dollar volume" and cleared the $10m liquidity gate on an FX rate. The book
traded them 18 times. `check_foreign` exists because of that and this test is what keeps it honest.
"""
import datetime as dt
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _world(cur, *, lie_about_dd=True, foreign=True, overstuff=True):
    """One clean name, one acquired mid-run, one that keeps a foreign calendar."""
    names = [("SPY.US", "bench", "index"), ("AAA.US", "clean", "stock"),
             ("DEAD.US", "acquired", "stock")]
    if foreign:
        names.append(("FGN.US", "foreign", "stock"))
    for t, n, k in names:
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values (%s,%s,%s,'USD','active')""", (t, n, k))

    days = [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(300)]
    for i, d in enumerate(days):
        for t in ("SPY.US", "AAA.US"):
            cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                           values (%s,%s,%s,%s,%s,%s,%s,1000000)""",
                        (t, d, 100 + i, 103 + i, 99 + i, 102 + i, 102 + i))
        if i < 200:                       # DEAD stops printing — the acquisition path
            cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                           values ('DEAD.US',%s,%s,%s,%s,%s,%s,1000000)""",
                        (d, 50 + i, 53 + i, 49 + i, 52 + i, 52 + i))
        if foreign and i % 10:            # FGN misses a tenth of the US calendar
            cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                           values ('FGN.US',%s,%s,%s,%s,%s,%s,1000000)""",
                        (d, 70 + i, 73 + i, 69 + i, 72 + i, 72 + i))

    # the curve rises monotonically, so its TRUE max drawdown is zero
    cur.execute("""insert into backtest_runs (label,params,start_date,end_date,trading_days,
                     start_nav,end_nav,total_return,cagr,max_drawdown)
                   values ('audit fixture','{"park":"SPY.US"}',%s,%s,300,100000,130000,0.30,
                           0.3778,%s) returning id""",
                (days[0], days[-1], -0.05 if lie_about_dd else 0.0))
    rid = cur.fetchone()[0]
    for i, d in enumerate(days):
        cur.execute("insert into backtest_equity (run_id,d,nav,positions) values (%s,%s,%s,%s)",
                    (rid, d, 100000 * (1 + 0.30 * i / 299), 2 if overstuff else 3))

    rows = [(rid, "AAA.US", days[5], 105.0, days[50], 150.0),
            (rid, "DEAD.US", days[10], 60.0, days[250], 251.0)]
    for r in rows:
        cur.execute("""insert into backtest_trades (run_id,ticker,entry_date,entry_price,qty,
                         exit_date,exit_price,exit_reason)
                       values (%s,%s,%s,%s,10,%s,%s,'rank_band')""", r)
    if foreign:
        cur.execute("""insert into backtest_trades (run_id,ticker,entry_date,entry_price,qty,
                         exit_reason) values (%s,'FGN.US',%s,71.0,10,'open_at_end')""",
                    (rid, days[1]))
    return rid


def _audit(url, run_id):
    out = subprocess.run([sys.executable, str(ROOT / "src" / "verify_run.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": url, "RUN_ID": str(run_id),
                              "DB_SSLMODE": "disable", "PATH": "/usr/bin:/bin"})
    return out.stdout + out.stderr, out.returncode


def _verdict(text, name):
    for line in text.splitlines():
        if name in line:
            return line.strip().split()[0]
    return None


def test_the_auditor_catches_every_defect_it_claims_to(db, migrated):
    with db.cursor() as cur:
        rid = _world(cur)
    db.commit()
    text, code = _audit(migrated, rid)

    assert code != 0, f"a world full of planted defects must not pass:\n{text}"
    # the fabricated drawdown: the curve never falls, so -5% is a fiction
    assert _verdict(text, "max drawdown") == "FAIL", text
    # the foreign listing, which is the real defect this check was written for
    assert _verdict(text, "B4 listed where we think") == "FAIL", text
    assert "FGN.US" in text
    # the book held three names while reporting two
    assert _verdict(text, "D1 slot discipline") == "FAIL", text


def test_the_auditor_passes_a_world_with_nothing_wrong_with_it(db, migrated):
    """The other half. A check that fails on everything is as useless as one that passes on it."""
    with db.cursor() as cur:
        rid = _world(cur, lie_about_dd=False, foreign=False, overstuff=False)
    db.commit()
    text, _ = _audit(migrated, rid)

    assert _verdict(text, "max drawdown") == "PASS", text
    assert _verdict(text, "B4 listed where we think") == "PASS", text
    assert _verdict(text, "D1 slot discipline") == "PASS", text
    assert _verdict(text, "C2 execution convention") == "PASS", text
    # and the acquisition is recognised rather than reported as a missing bar
    assert _verdict(text, "B1b delisting fills") == "PASS", text


def test_an_entry_priced_at_the_deciding_close_is_reported_as_such(db, migrated):
    """C2 is the check that would have caught the one-bar advantage this engine carried until
    2026-08-14, when `next_open` turned out to be inert for any cell without a trailing stop."""
    with db.cursor() as cur:
        rid = _world(cur, lie_about_dd=False, foreign=False, overstuff=False)
        cur.execute("""update backtest_trades set entry_price = (
                         select coalesce(p.adj_close,p.close) from prices p
                          where p.ticker = backtest_trades.ticker
                            and p.d = backtest_trades.entry_date)
                       where run_id = %s""", (rid,))
    db.commit()
    text, code = _audit(migrated, rid)
    assert code != 0
    assert _verdict(text, "C2 execution convention") == "FAIL", text
    assert "CLOSE" in text, "the failure must name the defect, not merely count it"
