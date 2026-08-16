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

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _world(cur, *, lie_about_dd=True, foreign=True, overstuff=True, split=False, twin=False):
    """One clean name, one acquired mid-run, one that keeps a foreign calendar."""
    names = [("SPY.US", "bench", "index"), ("AAA.US", "clean", "stock"),
             ("DEAD.US", "acquired", "stock")]
    if foreign:
        names.append(("FGN.US", "foreign", "stock"))
    if split:
        names.append(("SPLIT.US", "mis-stated split factor", "stock"))
    if twin:
        names.append(("AAA_old.US", "the same company again", "stock"))
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
        if split:
            # dark for forty sessions, then back on the far side of a seam: the vendor recorded a
            # 20x adjustment where the raw print stepped 400x, so the ADJUSTED series jumps too.
            if not 100 <= i < 140:
                px = 0.40 if i < 100 else 8.0 + i * 0.01
                cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                               values ('SPLIT.US',%s,%s,%s,%s,%s,%s,1000000)""",
                            (d, px, px * 1.01, px * 0.99, px, px))
        if twin:                          # AAA under a second symbol, tick for tick
            cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                           values ('AAA_old.US',%s,%s,%s,%s,%s,%s,1000000)""",
                        (d, 100 + i, 103 + i, 99 + i, 102 + i, 102 + i))

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
    if split:
        cur.execute("""insert into backtest_trades (run_id,ticker,entry_date,entry_price,qty,
                         exit_reason) values (%s,'SPLIT.US',%s,9.4,10,'open_at_end')""",
                    (rid, days[140]))
    if twin:
        # held across the SAME window as AAA.US, which is the harm: one company, two slots
        cur.execute("""insert into backtest_trades (run_id,ticker,entry_date,entry_price,qty,
                         exit_date,exit_price,exit_reason)
                       values (%s,'AAA_old.US',%s,105.0,10,%s,150.0,'rank_band')""",
                    (rid, days[5], days[50]))
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
        rid = _world(cur, split=True, twin=True)
    db.commit()
    text, code = _audit(migrated, rid)

    assert code != 0, f"a world full of planted defects must not pass:\n{text}"
    # the fabricated drawdown: the curve never falls, so -5% is a fiction
    assert _verdict(text, "max drawdown") == "FAIL", text
    # the foreign listing, which is the real defect this check was written for
    assert _verdict(text, "B4 listed where we think") == "FAIL", text
    assert "FGN.US" in text
    # a mis-stated split factor, across a trading gap — the shape that got past the first guard
    assert _verdict(text, "B5 the tape is prices") == "FAIL", text
    assert "SPLIT.US" in text
    # one company under two symbols, held at the same time
    assert _verdict(text, "B7 one company one slot") == "FAIL", text
    assert "AAA_old.US" in text
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
    # the tape checks must not fire on a clean world either — a guard that always trips is noise
    assert _verdict(text, "B5 the tape is prices") == "PASS", text
    assert _verdict(text, "B6 bar geometry") == "PASS", text
    assert _verdict(text, "B7 one company one slot") == "PASS", text


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


def test_a_breach_shorter_than_the_old_sampling_stride_is_still_caught(db, migrated):
    """D1 sampled `dates[::5]` and called it "enough to catch a breach". It was not.

    The book re-decides every session and displacement is capped at one per session, so a breach
    can open and close inside five sessions and never be looked at. This plants exactly that: three
    extra names held for two sessions, in a world whose equity rows report three slots. Under the
    old stride, whether it was seen at all depended on where the breach happened to fall.

    The report must also say what the breach COST. A breach in names is not yet a breach in
    capital: §3.5 sizes at NAV / slots, so the question a reader actually has is whether the extra
    names carried their own money or are duplicate listings wearing a second symbol.
    """
    with db.cursor() as cur:
        rid = _world(cur, lie_about_dd=False, foreign=False, overstuff=False)
        cur.execute("select d from backtest_equity where run_id=%s order by d", (rid,))
        days = [r[0] for r in cur.fetchall()]
        brief, back = days[120], days[121]
        for n in range(3):
            tk = f"BRF{n}.US"
            cur.execute("""insert into universe (ticker,name,kind,currency,status)
                           values (%s,'brief','stock','USD','active')""", (tk,))
            for i, d in enumerate(days):
                cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                               values (%s,%s,%s,%s,%s,%s,%s,1000000)""",
                            (tk, d, 10 + i, 13 + i, 9 + i, 12 + i, 12 + i))
            cur.execute("""insert into backtest_trades (run_id,ticker,entry_date,entry_price,qty,
                             exit_date,exit_price,exit_reason)
                           values (%s,%s,%s,130.0,50,%s,131.0,'rank_band')""",
                        (rid, tk, brief, back))
    db.commit()
    text, _ = _audit(migrated, rid)

    assert _verdict(text, "D1 slot discipline") == "FAIL", (
        f"a two-session breach must be caught, not sampled past:\n{text}")
    assert str(brief) in text, f"the report must name the session it broke on:\n{text}"
    assert "of NAV at cost" in text, (
        f"a slot breach must report what it cost, not only that it happened:\n{text}")


def test_same_session_turnover_is_not_a_slot_breach(db, migrated):
    """The bug that made D1 accuse the engine of something it never did.

    Run 589 reported "7 concurrent names, engine reported max 5" and it was the CHECK that was
    wrong. Counting a name as live on its exit date and on its entry date double-counts ordinary
    turnover: §3.5 sequences sells before buys inside the same morning, and `concentrated.py`
    books the exit and drops the position from `held` on that same date. Sell one name at the open
    and buy another at the open and a five-slot book momentarily reads as six.

    So this plants exactly that shape — one name leaving on the session another arrives — and
    asserts D1 stays quiet. It is the counterpart to the short-breach test above: that one proves
    the check still fires, this one proves it does not fire on the legal case. A check is only
    worth having if both hold.
    """
    with db.cursor() as cur:
        rid = _world(cur, lie_about_dd=False, foreign=False, overstuff=False)
        cur.execute("select d from backtest_equity where run_id=%s order by d", (rid,))
        days = [r[0] for r in cur.fetchall()]
        swap = days[120]
        # OUT on `swap`, and IN on `swap` — the same session, which is a displacement, not a breach
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values ('SWAP.US','the replacement','stock','USD','active')""")
        for i, d in enumerate(days):
            cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                           values ('SWAP.US',%s,%s,%s,%s,%s,%s,1000000)""",
                        (d, 20 + i, 23 + i, 19 + i, 22 + i, 22 + i))
        cur.execute("""insert into backtest_trades (run_id,ticker,entry_date,entry_price,qty,
                         exit_date,exit_price,exit_reason)
                       values (%s,'AAA.US',%s,100.0,50,%s,101.0,'rank_band')""",
                    (rid, days[60], swap))
        cur.execute("""insert into backtest_trades (run_id,ticker,entry_date,entry_price,qty,
                         exit_date,exit_price,exit_reason)
                       values (%s,'SWAP.US',%s,140.0,50,%s,141.0,'rank_band')""",
                    (rid, swap, days[180]))
    db.commit()
    text, _ = _audit(migrated, rid)

    assert _verdict(text, "D1 slot discipline") == "PASS", (
        f"a sell and a buy on the same session is turnover, not a slot breach:\n{text}")
