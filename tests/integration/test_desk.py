"""The nightly engine decision, against a real database.

`desk.py` is what Zak reads in the morning and what §6.4's shadow compares against the sim, so the
tests that matter are about the SHEET, not about the arithmetic — `engine.py` already has that
pinned. What can go wrong here is the seam: a holding that left the universe, a gate read off the
wrong series, a sell that waits on a buy, or a job that writes when it was told not to.
"""
import datetime as dt
import pathlib
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import desk                                                               # noqa: E402
import engine                                                             # noqa: E402


def _world(cur, *, n_days=700, rising=True, held=(), excluded=()):
    """A tape with a benchmark and enough names to fill a book of five."""
    names = [f"N{i:02d}.US" for i in range(20)]
    cur.execute("""insert into accounts (code, label, kind, currency)
                   values ('TFSA','TFSA','registered','CAD') on conflict do nothing""")
    for t in ["SPY.US"] + names:
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values (%s,%s,%s,'USD','active')""",
                    (t, t, "index" if t == "SPY.US" else "stock"))
    for t in excluded:
        cur.execute("""insert into universe_excluded (ticker, reason, detail)
                       values (%s,'duplicate_listing','planted by the test')""", (t,))

    days = [dt.date(2023, 1, 2) + dt.timedelta(days=i) for i in range(n_days)]
    # one shared noise path, so every name carries the SAME volatility and only the drift differs
    wiggle = np.cumsum(np.random.default_rng(3).normal(0, 0.006, n_days))
    for i, d in enumerate(days):
        # the benchmark: rising the whole way, or rolling over at the end so the gate reads OFF
        bm = 100.0 + i * 0.2 if rising else (100.0 + i * 0.2 if i < n_days - 60
                                             else 100.0 + (n_days - 60) * 0.2 - (i - n_days + 60) * 2.0)
        cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                       values ('SPY.US',%s,%s,%s,%s,%s,%s,90000000)""",
                    (d, bm, bm * 1.01, bm * 0.99, bm, bm))
        for k, t in enumerate(names):
            # A strict ladder AFTER the vol divisor, which is the part that matters: §3.3 ranks
            # momentum / stdev, so names must differ in DRIFT and agree on VOLATILITY. The first
            # draft of this fixture used linear ramps, which give a steeper name a higher variance
            # in daily returns and inverted the ladder — the test caught its own fixture.
            #
            # The rung spacing is 3e-4 and that number is load-bearing. The shared `wiggle` cancels
            # between any two names, so their daily returns differ by exactly the drift gap — and
            # at the original 4e-5 that gap sat BELOW `bars.TWIN_TOL` (1e-4), which made every
            # adjacent pair in this world a §3.7(3) twin. Nothing noticed until the live engine
            # learned the pair rule and refused to buy any two neighbours. Distinct names in a
            # fixture have to be distinct securities; 3e-4 is three times the tolerance and leaves
            # the ladder's ORDER untouched, because vol is identical and drift stays monotone.
            #
            # 1.5e-4 rather than more, because the spacing is squeezed from both sides: too small
            # and the neighbours are twins, too large and the bottom rungs fall through §3.2's $5
            # floor and stop being ranked at all. Measured, not reasoned: at 1.5e-4 the cheapest
            # last close is $18.32 and no adjacent pair reads as one security; at 3e-4 the cheapest
            # is $2.50 and four names silently leave the universe.
            px = 50.0 * float(np.exp((0.0010 - 0.00015 * k) * i + wiggle[i]))
            cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                           values (%s,%s,%s,%s,%s,%s,%s,4000000)""",
                        (t, d, px, px * 1.01, px * 0.99, px, px))
    for t in held:
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values (%s,'TFSA','momentum',100,40.0,'open')""", (t,))
    return days


def test_an_empty_book_seeds_five_from_the_top_of_the_rank(db, migrated):
    """§3.5: "Seeding fills all five in one session." """
    with db.cursor() as cur:
        days = _world(cur)
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)

    assert s["gate"] == "ON"
    buys = [o for o in s["orders"] if o["action"] == "buy"]
    assert [o["ticker"] for o in buys] == ["N00.US", "N01.US", "N02.US", "N03.US", "N04.US"]
    assert all(o["rank"] <= engine.FILL_BAND for o in buys)
    assert all(o["qty"] > 0 for o in buys), "a seeded slot must size to something"


def test_the_gate_off_sells_the_whole_book_and_buys_nothing(db, migrated):
    """§3.4: "the entire book sells at the next executable open... No buys of any kind while OFF." """
    with db.cursor() as cur:
        days = _world(cur, rising=False, held=("N00.US", "N01.US"))
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)

    assert s["gate"] == "OFF"
    assert sorted(o["ticker"] for o in s["orders"] if o["action"] == "sell") == ["N00.US", "N01.US"]
    assert not [o for o in s["orders"] if o["action"] == "buy"], "no buys of any kind while OFF"


def test_a_holding_that_left_the_universe_is_still_sold(db, migrated):
    """The seam that a rank-only rule misses. An excluded or delisted name has no rank at all, and
    "not ranked" is below rank 12 — but a naive implementation drops it from the sheet entirely and
    the position is held for ever, invisibly."""
    with db.cursor() as cur:
        days = _world(cur, held=("N00.US",), excluded=("N00.US",))
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)

    sells = [o["ticker"] for o in s["orders"] if o["action"] == "sell"]
    assert "N00.US" in sells, "a holding with no rank must still be queued to sell"
    assert "N00.US" not in s["top"], "and it must not be rankable"


def test_the_sheet_writes_nothing(db, migrated):
    """§6.4 runs this for ten sessions producing order sheets nobody trades. A job that can write
    cannot be trusted to have not written."""
    with db.cursor() as cur:
        days = _world(cur)
    db.commit()
    with db.cursor() as cur:
        cur.execute("select count(*) from tickets")
        before_t = cur.fetchone()[0]
        cur.execute("select count(*) from book")
        before_b = cur.fetchone()[0]
        desk.sheet(cur, days[-1], 200_000.0)
        cur.execute("select count(*) from tickets")
        cur.execute("select count(*) from tickets")
        assert cur.fetchone()[0] == before_t
        cur.execute("select count(*) from book")
        assert cur.fetchone()[0] == before_b


def test_it_refuses_to_size_without_a_nav(migrated):
    """§3.5 sizes at NAV/5. There is no defensible default, so it fails rather than invent one."""
    out = subprocess.run([sys.executable, str(ROOT / "src" / "desk.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "PATH": "/usr/bin:/bin"})
    assert out.returncode != 0
    assert "ENGINE_NAV is required" in (out.stdout + out.stderr)


def test_the_rendered_sheet_says_nothing_was_ordered(db, migrated):
    """§0.2 — Yuna proposes, Zak executes. The sheet has to say so where he reads it."""
    with db.cursor() as cur:
        days = _world(cur)
    db.commit()
    with db.cursor() as cur:
        text = desk.render(desk.sheet(cur, days[-1], 200_000.0))
    assert "Nothing here has been ordered" in text
    assert "sells first, then buys" in text


def test_the_fixtures_names_are_distinct_securities(db, migrated):
    """The guard on the fixture itself, added after §3.7(3)'s pair rule caught it out.

    Every name here shares one noise path so that §3.3's vol divisor is identical across the ladder
    — which means two names differ ONLY by their drift gap, and if that gap sits under
    `bars.TWIN_TOL` the whole world is one company under twenty symbols. It did, for as long as
    nothing tested pairs. A fixture whose names are secretly twins does not fail loudly; it just
    stops testing whatever the pair rule was supposed to govern.
    """
    import bars
    with db.cursor() as cur:
        days = _world(cur)
        sessions, tickers, adj, raw, dv, _ = desk.load(cur, days[-1])
    i = len(sessions) - 1
    lo = max(1, i - bars.TWIN_WINDOW + 1)

    def ret(j):
        return adj[lo:i + 1, j] / adj[lo - 1:i, j] - 1.0

    pairs = [(tickers[a], tickers[b])
             for a in range(len(tickers)) for b in range(a + 1, len(tickers))
             if bars.same_security(ret(a), ret(b))]
    assert pairs == [], f"the fixture's names read as one security: {pairs[:5]}"


def test_a_twin_pair_in_the_top_twelve_takes_only_one_slot(db, migrated):
    """§3.7(3), end to end through the real tape loader: "hold at most one of a pair"."""
    with db.cursor() as cur:
        days = _world(cur)
        # N01 is re-priced as an exact copy of N00 — one company, two symbols, both near the top.
        cur.execute("""update prices p set close = src.close, adj_close = src.adj_close
                         from prices src
                        where src.ticker = 'N00.US' and p.ticker = 'N01.US' and p.d = src.d""")
        db.commit()
        s = desk.sheet(cur, days[-1], 200_000.0)

    bought = [o["ticker"] for o in s["orders"] if o["action"] == "buy"]
    assert "N00.US" in bought, "the better-ranked line fills"
    assert "N01.US" not in bought, "and its twin does not join it"
    assert len(bought) == engine.SLOTS, "the skipped twin costs no slot — the band reaches deeper"
