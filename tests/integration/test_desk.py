"""The nightly engine decision, against a real database.

`desk.py` is what Zak reads in the morning and what §6.4's shadow compares against the sim, so the
tests that matter are about the SHEET, not about the arithmetic — `engine.py` already has that
pinned. What can go wrong here is the seam: a holding that left the universe, a gate read off the
wrong series, a sell that waits on a buy, or a job that writes when it was told not to.
"""
import datetime as dt
import math
import pathlib
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import desk                                                               # noqa: E402
import engine                                                             # noqa: E402


def _cash(cur, days, usd, cad=0.0, usdcad=None):
    """A TFSA balances anchor on the last session — and, for CAD cash, the USDCAD close that
    converts it. Since v1.1 (§3.5) a buy is sized to the lesser of NAV ÷ 5 and deployable TFSA cash,
    and the cash comes from the store whatever the NAV's source: a world whose buys are meant to
    carry quantities has to state the money as well as the NAV."""
    cur.execute("""insert into balances (account, as_of, cash_cad, cash_usd, source)
                   values ('TFSA', %s, %s, %s, 'test')""", (days[-1], cad, usd))
    if usdcad is not None:
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values ('USDCAD.FOREX','USDCAD','fx','CAD','active')
                       on conflict (ticker) do nothing""")
        cur.execute("""insert into prices (ticker,d,close,adj_close,volume) values (%s,%s,%s,%s,0)
                       on conflict (ticker,d) do update set close = excluded.close""",
                    ("USDCAD.FOREX", days[-1], usdcad, usdcad))


def _world(cur, *, n_days=700, rising=True, held=(), excluded=(), cash=None):
    """A tape with a benchmark and enough names to fill a book of five.

    `cash` stages a TFSA anchor of that many USD (`_cash`). Left None the store states no cash, and
    every buy on the sheet is unsized — with the reason — however its NAV was given."""
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
    if cash is not None:
        _cash(cur, days, cash)
    return days


def test_an_empty_book_seeds_five_from_the_top_of_the_rank(db, migrated):
    """§3.5: "Seeding fills all five in one session." The account holds the cash its NAV says it
    does (an empty book, so NAV is all cash) — and v1.1 sizes against that cash, so every slot
    fills at weight."""
    with db.cursor() as cur:
        days = _world(cur, cash=200_000.0)
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)

    assert s["gate"] == "ON"
    buys = [o for o in s["orders"] if o["action"] == "buy"]
    assert [o["ticker"] for o in buys] == ["N00.US", "N01.US", "N02.US", "N03.US", "N04.US"]
    assert all(o["rank"] <= engine.FILL_BAND for o in buys)
    assert all(o["qty"] > 0 for o in buys), "a seeded slot must size to something"
    assert all(o["qty"] == engine.position_size(200_000.0, o["mark"]) for o in buys), \
        "200,000 of cash over five buys is a full slot each"


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
    because the cash has to exist before the buys it pays for.

    v1.1 (§3.5): the park pays the buys' shortfall beyond cash, and a shortfall beyond the park is
    "reported as held-below-weight, not funded". With no cash at all, five slots need 200,000 and
    the bridge holds 125,955: the whole lot is drawn because the shortfall is bigger than it, and
    the five buys share what it raised — each below weight, by hand below."""
    with db.cursor() as cur:
        days = _world(cur, cash=0.0)              # gate ON, empty book: five buys, no cash
        _park(cur, days)                          # SPMO 810 @ 155.5
        _shadow_passed(cur, days)
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)

    assert s["gate"] == "ON"
    actions = [(o["action"], o["ticker"], o["clause"]) for o in s["orders"]]
    assert actions[0] == ("sell", "SPMO.US", "fund"), "the funding sell leads the sheet"
    buys = [o for o in s["orders"] if o["action"] == "buy"]
    assert len(buys) == 5
    assert [o for o in s["orders"] if o["clause"] == "fund"][0]["qty"] == 810, \
        "200,000 of shortfall is more than the lot, so the draw stops at the lot"
    share = 810 * 155.5 / 5                       # 25,191 each
    for o in buys:
        assert o["qty"] == min(int(200_000.0 / 5 // o["mark"]), int(share // o["mark"]))
        assert o["below_weight"] is True and "below §3.5 weight" in o["why"]


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
    rebalance, and rebalancing a momentum book trims winners. So the sheet REPORTS it, in dollars.
    This test pins both halves: nothing is ordered, and the shortfall is impossible to miss.

    The ruling the sheet used to leave with Zak (§0.3) is made: v1.1's §3.5, "A slot filled below
    weight counts as filled and is reported; it is never topped up." The render now quotes it
    rather than asking for it.
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
    assert "NOT ordered" in desk.render(s) and "it is never topped up" in desk.render(s)


def test_a_buy_of_a_line_the_account_already_holds_is_never_emitted(db, migrated, monkeypatch):
    """The belt, exercised through the sheet. `engine.orders` keeps a held name in the top 12
    rather than handing it back as a buy, so the rule as written never produces this — which is
    why it is forced here, by an `engine.orders` that re-buys every line it keeps.

    The belt used to NET such a buy: the slot less the line held. That is a top-up by another name,
    and v1.1's §3.5 settles it: "A slot filled below weight counts as filled and is reported; it is
    never topped up." So the buy is no order at all — it is reported, with the reason."""
    with db.cursor() as cur:
        days = _world(cur, cash=200_000.0)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','momentum',20,40.0,'open')""")
    db.commit()
    real = engine.orders

    def orders_that_rebuy(ranked, held, **kw):
        sells, buys = real(ranked, held, **kw)
        return sells, list(held) + list(buys)

    monkeypatch.setattr(engine, "orders", orders_that_rebuy)
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)

    assert "N00.US" not in [o["ticker"] for o in s["orders"]], "no buy, and no sell"
    assert [h["ticker"] for h in s["held_below"]] == ["N00.US"]
    assert "never tops a slot up" in s["held_below"][0]["why"]
    assert len([o for o in s["orders"] if o["action"] == "buy"]) == engine.SLOTS - 1


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


def test_the_engine_cannot_see_momentum_money_outside_its_account(db, migrated):
    """Zak, 2026-08-18: *"The sleeve is the purpose of the money. We just set the boundaries as the
    account for simplicity but one day some of the RRSP may be used for Momentum and maybe some of
    the TFSA will be used for something else."*

    The day that happens, `held_book` — which reads the account — silently misses it. Nothing about
    the sheet looks different: the position is simply absent, so it can never be sold, never counts
    against §3.5's five slots, and never nets against a buy. That is the AXTI/MU defect with the
    wrapper swapped for the label, and the account filter cannot detect it by itself.

    `sleeve_divergence` is what refuses to let it be silent.
    """
    with db.cursor() as cur:
        days = _world(cur)
        cur.execute("""insert into accounts (code,label,kind,currency)
                       values ('RRSP','rrsp','registered','CAD') on conflict do nothing""")
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','RRSP','momentum',50,40.0,'open')""")
        db.commit()

        assert "N00.US" not in desk.held_book(cur), "the account filter misses it — the defect"
        d = desk.sleeve_divergence(cur)
        assert len(d) == 1 and d[0]["ticker"] == "N00.US"
        assert d[0]["engine_sees_it"] is False, "the engine does not trade it today"
        assert d[0]["engine_would_see_it"] is True, "and its PURPOSE says it should"
        assert d[0]["expected"] == ("reserve",), "§2.1 puts reserve in the RRSP"


def test_a_tfsa_position_whose_purpose_is_not_momentum_is_flagged_too(db, migrated):
    """The mirror, and the one that is true of production today. §2.1 puts momentum in the TFSA, so
    a TFSA line labelled anything else is money the engine IS trading whose stated purpose says it
    should not. Both directions matter — one hides a position, the other trades someone else's."""
    with db.cursor() as cur:
        days = _world(cur)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','preseed',20,40.0,'open')""")
        db.commit()

        assert "N00.US" in desk.held_book(cur), "the account filter includes it"
        d = desk.sleeve_divergence(cur)
        assert len(d) == 1
        assert d[0]["engine_sees_it"] is True and d[0]["engine_would_see_it"] is False


def test_an_account_whose_labels_match_the_plan_is_silent(db, migrated):
    """A guard that fires on the healthy case is a guard that gets ignored. §2.1's arrangement —
    momentum in the TFSA, reserve in the RRSP, reserve or levered in the NONREG — says nothing."""
    with db.cursor() as cur:
        days = _world(cur)
        for acct in ("RRSP", "NONREG"):
            cur.execute("""insert into accounts (code,label,kind,currency)
                           values (%s,%s,'registered','CAD') on conflict do nothing""",
                        (acct, acct.lower()))
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','momentum',20,40.0,'open'),
                              ('N01.US','RRSP','reserve',10,40.0,'open'),
                              ('N02.US','NONREG','levered',10,40.0,'open'),
                              ('N03.US','NONREG','reserve',10,40.0,'open')""")
        db.commit()
        assert desk.sleeve_divergence(cur) == []


def test_a_partial_slot_is_reported_and_the_park_pays_only_the_shortfall(db, migrated):
    """What the 2026-08-19 seed ruling became under v1.1, and the defect it replaces (QC A6).

    At seed conditions (gate ON, shadow passed, a park held) the sheet used to TOP UP every kept
    top-12 name below its weight and sell the WHOLE park to pay for it — a rebalance, proposed
    whenever any park lot sat in the account. v1.1's §3.5 ends both halves: "A slot filled below
    weight counts as filled and is reported; it is never topped up", and "a shortfall beyond TFSA
    park and cash is reported as held-below-weight, not funded" — so the park pays the buys'
    shortfall beyond cash and proceeds, and only that.

    Here N00 sits at 20 shares (rank 1), four slots are free, the cash is 100,000 and the bridge is
    810 SPMO at 155.5. Four slots need 160,000; the cash covers 100,000; the park draws the other
    60,000 in whole shares — 386, not 810 — and the four fills land at weight.
    """
    nav = 200_000.0
    with db.cursor() as cur:
        days = _world(cur, cash=100_000.0)
        _park(cur, days)                                # SPMO 810 @ 155.5 ≈ 125.9k
        _shadow_passed(cur, days)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','momentum',20,40.0,'open')""")
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], nav)

    assert not [o for o in s["orders"] if o["clause"] == "top_up"], "never topped up"
    assert not [o for o in s["orders"] if o["ticker"] == "N00.US"], "kept: no buy, and no sell"
    assert [u["ticker"] for u in s["underweight"]] == ["N00.US"], "reported instead"
    fund = [o for o in s["orders"] if o["clause"] == "fund"]
    shortfall = 4 * nav / 5 - 100_000.0                           # 60,000
    assert len(fund) == 1 and fund[0]["qty"] == math.ceil(shortfall / 155.5) == 386, \
        "the shortfall in whole shares — never the whole lot because a lot exists"
    assert s["orders"][0] is fund[0], "and the cash leg leads the sheet (§3.5: sells first)"
    fills = [o for o in s["orders"] if o["clause"] == "fill"]
    assert len(fills) == 4, "the four genuinely free slots fill"
    assert all(o["qty"] == engine.position_size(nav, o["mark"]) for o in fills), "at weight"


def test_topups_never_fire_while_the_shadow_runs(db, migrated):
    """The same book without §6.4's pass: the shortfall is REPORTED and nothing is ordered. §6.5
    gates the whole deployment, and a proposal is what Zak acts on."""
    with db.cursor() as cur:
        days = _world(cur)
        _park(cur, days)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','momentum',20,40.0,'open')""")
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    assert not [o for o in s["orders"] if o["clause"] in ("top_up", "fund")]
    assert [u["ticker"] for u in s["underweight"]] == ["N00.US"], "reported instead"


def test_topups_cannot_pyramid_winners_once_the_park_is_empty(db, migrated):
    """The scoping that keeps Zak's ruling §3.5-clean, and it needs no invented constant: a top-up
    exists only while the park can pay for it. Post-seed the park is empty, so NAV growth lifting
    NAV/5 above every entry weight can never start feeding winners — a name bought at weight is
    never bought again."""
    with db.cursor() as cur:
        days = _world(cur)
        _shadow_passed(cur, days)                       # seed conditions, but NO park held
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('N00.US','TFSA','momentum',20,40.0,'open')""")
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    assert not [o for o in s["orders"] if o["clause"] in ("top_up", "fund")]
    assert [u["ticker"] for u in s["underweight"]] == ["N00.US"], "still visible, never bought"


def test_the_tape_is_read_over_the_window_the_engine_reads_and_decides_as_the_whole_tape(
        db, migrated, monkeypatch):
    """QC 2026-10-07, A34. The load read every bar since 2003 — 9.2M rows a call, 73.7 s on average
    and 117.1 s at worst against the server's 120 s statement timeout — for a decision that reads
    the last 253 sessions. Both halves have to hold: nothing before the window reaches the arrays,
    and the sheet is exactly the one the whole tape gives.

    The depth is stated here from §3's constants rather than read back from `desk.reads()`: the
    deepest reads are §3.3's formation close and its 252-return vol window, and §3.7(3)'s
    252-return pair test.
    """
    import bars
    deepest = max(engine.FORMATION, engine.SKIP, engine.VOL_WINDOW, engine.SCREEN_WINDOW - 1,
                  engine.ADDV_WINDOW - 1, bars.TWIN_WINDOW)
    with db.cursor() as cur:
        days = _world(cur, held=("N03.US", "N15.US"))     # one kept, one a rank exit
        # a listed name that stopped printing long ago: it has bars, and none in the window
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values ('GONE.US','GONE.US','stock','USD','active')""")
        for d in days[:200]:
            cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                           values ('GONE.US',%s,30,30,30,30,30,9000000)""", (d,))
    db.commit()
    with db.cursor() as cur:
        sessions, tickers, adj, raw, dv, _ = desk.load(cur, days[-1])
        s = desk.sheet(cur, days[-1], 200_000.0)
    i = len(sessions) - 1
    first = i - deepest
    assert first > 0, "the fixture must reach further back than the window, or this proves nothing"
    for name, a in (("adj", adj), ("raw", raw), ("dv", dv)):
        assert np.isnan(a[:first]).all(), f"{name}: a bar from before the window was loaded"
    printing = [j for j, t in enumerate(tickers) if t != "GONE.US"]
    assert np.isfinite(adj[first:, printing]).all(), "and every bar inside it was"
    assert "GONE.US" in tickers and s["universe"] == 21, \
        "a name with no bar in the window keeps its column — universe_count means what it did"
    assert [o["ticker"] for o in s["orders"] if o["action"] == "sell"] == ["N15.US"]

    # The same code with the window opened to every session: the decision may not move.
    monkeypatch.setattr(desk, "reads", lambda: {"the whole tape": len(sessions)}, raising=False)
    with db.cursor() as cur:
        whole = desk.sheet(cur, days[-1], 200_000.0)
    assert whole == s


def _split(cur, days, ticker, *, ratio, at, turnover, drift=0.0013):
    """A name stored the way the vendor's per-ticker history stores a split once it is re-pulled:
    the RAW close on every bar — before `at`, `ratio` times the adjusted close (2.0 for a 2:1, 0.1
    for a 1:10 reverse) — the adjusted close continuous, and the volume restated in post-split
    shares. Production's APH.US is this shape. It trades `turnover` dollars every session, straight
    through the split, and its drift is above the ladder's so that if it is ranked it ranks first.
    """
    wiggle = np.cumsum(np.random.default_rng(3).normal(0, 0.006, len(days)))
    cur.execute("""insert into universe (ticker,name,kind,currency,status)
                   values (%s,%s,'stock','USD','active')""", (ticker, ticker))
    for k, d in enumerate(days):
        a = 50.0 * float(np.exp(drift * k + wiggle[k]))
        c = a * ratio if k < at else a
        cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                       values (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (ticker, d, c, c * 1.01, c * 0.99, c, a, int(round(turnover / a))))


def test_a_split_leaves_a_names_liquidity_where_it_was(db, migrated):
    """QC 2026-10-07, A7. §3.2's floor and pool ask how much a name trades, and a split changes
    nothing about that. Live ADDV was the raw close times the stored volume, and the stored volume
    is split-adjusted once a name is re-pulled — so every bar before a split read at the split
    factor times its turnover (APH.US, 2:1 on 2026-09-03, read 1.67x on 10-05). The code of record
    prices it on the adjusted close, where the factor cancels.

    This name trades $7M a day through a 2:1 split ten sessions before the decision. Its ADDV is
    $7M on every session across the split, it sits below §3.2's $10M floor, and it is not ranked —
    under the raw close it read $14M, ranked first and was bought."""
    turnover = 7_000_000.0
    with db.cursor() as cur:
        days = _world(cur)
        _split(cur, days, "SPL.US", ratio=2.0, at=len(days) - 10, turnover=turnover)
    db.commit()
    with db.cursor() as cur:
        sessions, tickers, adj, raw, dv, _ = desk.load(cur, days[-1])
        s = desk.sheet(cur, days[-1], 200_000.0)
    i, j = len(sessions) - 1, tickers.index("SPL.US")
    addv = [float(engine.median_addv(dv, k)[j]) for k in range(i - 60, i + 1)]
    assert max(abs(a / turnover - 1) for a in addv) < 1e-4, \
        f"ADDV stepped across the split: {min(addv):,.0f} .. {max(addv):,.0f}"
    assert raw[i, j] >= engine.SCREEN_MIN_PRICE, "the $5 floor still reads the print, and passes"
    assert "SPL.US" not in [r["ticker"] for r in s["ranks"]], "below the $10M floor: not ranked"
    assert "SPL.US" not in [o["ticker"] for o in s["orders"]], "and never bought"


def test_a_reverse_split_does_not_sell_a_liquid_holding(db, migrated):
    """The mirror. Before a 1:10 reverse split the raw prints sit at a tenth of the adjusted close
    beside volume restated in post-split shares, so the raw close read a tenth of the turnover: a
    $40M name read $4M, failed §3.2's $10M floor, fell out of the rank, and — held — was queued to
    sell as a rank exit (§3.5) for something that never happened to its trading."""
    turnover = 40_000_000.0
    with db.cursor() as cur:
        days = _world(cur, held=("N00.US",))
        _split(cur, days, "RVS.US", ratio=0.1, at=len(days) - 10, turnover=turnover)
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values ('RVS.US','TFSA','momentum',100,40.0,'open')""")
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    rank = {r["ticker"]: r for r in s["ranks"]}
    assert "RVS.US" in rank, "a $40M name passes the $10M floor and is ranked"
    assert abs(rank["RVS.US"]["addv"] / turnover - 1) < 1e-4
    assert rank["RVS.US"]["rank"] == 1
    assert "RVS.US" not in [o["ticker"] for o in s["orders"] if o["action"] == "sell"], \
        "a held name ranked first is kept, not sold"
