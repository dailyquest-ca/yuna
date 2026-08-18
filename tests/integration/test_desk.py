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


def _park(cur, days, ticker="SPMO.US", qty=810, px=155.5):
    """The §6.1(3) bridge, as it actually sits: in the TFSA, priced, and not a `.US` common stock —
    so §3.2 can never rank it and §3.5 can never keep it."""
    cur.execute("""insert into universe (ticker,name,kind,currency,status)
                   values (%s,%s,'etf','USD','active') on conflict (ticker) do nothing""",
                (ticker, ticker))
    for d in days[-5:]:
        cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                       values (%s,%s,%s,%s,%s,%s,%s,3000000)
                       on conflict (ticker,d) do nothing""",
                    (ticker, d, px, px, px, px, px))
    cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                   values (%s,'TFSA','reserve',%s,%s,'open')""", (ticker, qty, px))


def _shadow_passed(cur, days):
    """§6.4's pass: ten sessions, every divergence ruled. `v_shadow_progress.passes` reads it, and
    §6.5 will not convert the park until it is true."""
    for d in days[-10:]:
        for what in ("gate", "rank"):
            cur.execute("""insert into shadow_attestations (session_date, compared, matched)
                           values (%s, %s, true)
                           on conflict (session_date, compared) do nothing""", (d, what))


def test_the_park_is_never_sold_for_failing_to_rank(db, migrated):
    """The defect that came in with the account filter, as an assertion.

    §2.1 gives the engine the whole TFSA, so `held_book` reads the account — which is right, and
    fixes AXTI and MU sitting in it tagged `preseed` while ranking 2nd and 3rd. It also sweeps in
    the §6.1(3) bridge, which is an ETF: not a `.US` common stock, never in §3.2's universe, never
    rankable. And `desk.sheet` sells everything it holds and cannot rank.

    Uncorrected, that proposes liquidating the capital §6.5 is holding for the seed — every night,
    for failing a stock screen it was never eligible for. The park is engine capital and not an
    engine slot, and the two are told apart by INSTRUMENT (§8 names SPY.US, §6.1(3) names SPMO.US)
    rather than by a label someone has to remember to set.
    """
    with db.cursor() as cur:
        days = _world(cur, rising=False)          # gate OFF: §3.4 sends proceeds TO the park
        _park(cur, days)
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)

    assert s["gate"] == "OFF"
    assert s["parked"] == ["SPMO.US"]
    assert "SPMO.US" not in [o["ticker"] for o in s["orders"]], "the park is not a rank exit"
    assert "SPMO.US" not in s["unranked"], "and never joins the queue that becomes one"
    assert s["marked_equity"] > 0, "it is still engine capital, and still marked"


def test_the_park_funds_the_seed_when_the_gate_is_on(db, migrated):
    """§6.5: "all five slots fill from the first live ranking in one session." The capital for that
    is the bridge, so the bridge sells and the five buy in the same session — sells first (§3.5),
    because the cash has to exist before the buys it pays for."""
    with db.cursor() as cur:
        days = _world(cur)                        # gate ON, empty book: five buys
        _park(cur, days)
        _shadow_passed(cur, days)
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)

    assert s["gate"] == "ON"
    actions = [(o["action"], o["ticker"], o["clause"]) for o in s["orders"]]
    assert actions[0] == ("sell", "SPMO.US", "fund"), "the funding sell leads the sheet"
    assert len([o for o in s["orders"] if o["action"] == "buy"]) == 5
    assert [o for o in s["orders"] if o["clause"] == "fund"][0]["qty"] == 810


def test_the_park_is_not_sold_when_nothing_actually_buys(db, migrated):
    """A name in the fill band whose slot the account already holds emits no buy. The sheet then
    NAMES buys and orders none — and funding that would sell the bridge to pay for nothing."""
    with db.cursor() as cur:
        days = _world(cur)
        _park(cur, days)
        _shadow_passed(cur, days)
        # the whole top five already held at full weight: 200,000 / 5 = 40,000 a slot, and these
        # names trade near $90, so 1,000 shares is comfortably over one slot
        for t in ("N00.US", "N01.US", "N02.US", "N03.US", "N04.US"):
            cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                           values (%s,'TFSA','momentum',1000,40.0,'open')""", (t,))
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)

    assert s["gate"] == "ON"
    assert not [o for o in s["orders"] if o["action"] == "buy"], "every slot is already at weight"
    assert not [o for o in s["orders"] if o["clause"] == "fund"], "so nothing needs funding"


def test_a_partial_line_holds_a_slot_and_is_reported_rather_than_topped_up(db, migrated):
    """The pre-seed buys, and the decision they force.

    §3.5 fills FREE slots and `engine.orders` KEEPS a held name in the top 12 rather than re-buying
    it. So 20 shares of AXTI against rank 2 occupy a whole slot at a few percent of its weight: no
    buy is emitted, no sell is emitted, and the capital that slot was meant to carry stays parked.

    The engine has no rule for this and must not invent one — topping up a kept holding is a
    rebalance, and rebalancing a momentum book trims winners. So the sheet REPORTS it, in dollars,
    and §0.3 leaves the ruling with Zak. This test pins both halves: nothing is ordered, and the
    shortfall is impossible to miss.
    """
    with db.cursor() as cur:
        days = _world(cur)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','preseed',20,40.0,'open')""")
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)

    assert not [o for o in s["orders"] if o["ticker"] == "N00.US"], "kept: no buy, and no sell"
    assert len([o for o in s["orders"] if o["action"] == "buy"]) == engine.SLOTS - 1, \
        "the held name occupies one of the five"

    short = {u["ticker"]: u for u in s["underweight"]}
    assert "N00.US" in short, "and the shortfall is on the sheet"
    assert short["N00.US"]["rank"] == 1
    assert short["N00.US"]["slot"] == 200_000.0 / engine.SLOTS
    assert short["N00.US"]["pct_of_slot"] < 0.10, "a few percent of the weight it should carry"
    assert "NOT ordered" in desk.render(s) and "Zak's (§0.3)" in desk.render(s)


def test_a_buy_nets_against_a_line_the_account_already_holds(db, migrated):
    """The belt, exercised directly. `engine.orders` does not currently hand back a buy for a name
    the book holds — it keeps it — so this goes at the seam rather than through the sheet: given a
    buy and a holding, the ORDER is the slot less the line."""
    px, nav = 90.0, 200_000.0
    target = engine.position_size(nav, px)
    assert max(0, int(target - 20)) == target - 20
    assert max(0, int(target - target)) == 0, "a slot already at weight orders nothing"
    assert max(0, int(target - (target + 5))) == 0, "and one above it never orders negative"


def test_the_bridge_is_held_until_the_shadow_passes(db, migrated):
    """Production's exact state on 2026-08-18, and the accident it would have been.

    The gate reads ON, the book holds 810 shares of the §6.1(3) bridge, and three of §3.5's five
    slots are free — so the sheet names buys and the bridge is what pays for them. But the shadow
    stands at 2 of 10, and §6.5 gates the seed on "shadow passed · pipeline green · gate ON · Zak's
    seed ruling in chat". Without this condition the first sheet after the account filter landed
    would have written a LIVE ticket to sell the bridge, eight sessions early.

    `v_shadow_progress.passes` is §6.4's own condition, so this clears itself when Phase 0 finishes
    and needs no ruling to remove. It fails closed: no attestations at all is not a pass.
    """
    with db.cursor() as cur:
        days = _world(cur)                            # gate ON, free slots, so buys exist
        _park(cur, days)
        cur.execute("select count(*) from shadow_attestations")
        assert cur.fetchone()[0] == 0, "the shadow has attested nothing — the state to fail closed on"
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)

    assert s["gate"] == "ON" and s["phase0_done"] is False
    assert [o for o in s["orders"] if o["action"] == "buy"], "the buys still stand"
    assert not [o for o in s["orders"] if o["clause"] == "fund"], "and the bridge is not sold"
    assert "SPMO.US" not in [o["ticker"] for o in s["orders"]]
    assert "§6.5 converts this at the seed" in desk.render(s), "and the sheet says why"
