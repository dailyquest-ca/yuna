"""§3.5 as v1.1 amended it (promoted 2026-10-06), and Zak's two rulings of 2026-10-07, against a
real database — the decision, through `desk.sheet`.

    v1.1 §3.5  "Order size = the lesser of slot weight and deployable TFSA cash — TFSA cash on the
               book plus the same session's sell proceeds, marked at the decision close. When
               several buys share a session, deployable cash divides equally among them, each
               capped at slot weight... A slot filled below weight counts as filled and is
               reported; it is never topped up." · "a shortfall beyond TFSA park and cash is
               reported as held-below-weight, not funded."
    R1         A gate that cannot be evaluated on fresh data is unevaluated: nothing new is
               proposed, buys are held, the brief names the stale bar, and a data outage alone
               never sells the book.
    R2         A held name with no bar on the decision session is never turned into a rank exit or
               a refill by inference: it keeps its quantity and its slot, buys are held, and it is
               named until Zak records what happened; a gate-off still lists it to sell, unpriced.

The worlds are `test_desk`'s; `_world(cash=...)` states the TFSA cash v1.1 sizes against.
"""
import datetime as dt
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import desk                                                               # noqa: E402
import engine                                                             # noqa: E402
from test_desk import _cash, _park, _shadow_passed, _world                # noqa: E402


def _close(cur, ticker, d):
    cur.execute("select close from prices where ticker = %s and d = %s", (ticker, d))
    return float(cur.fetchone()[0])


def _ten_oh_five(cur):
    """The 2026-10-05 shape (QC A5). That night WDC left the band at rank 14 and ASX took its slot;
    the sheet asked for 580 ASX — a full NAV ÷ 5 — against about 512 the account could pay for,
    WDC's proceeds plus a little cash, and Zak re-sized it by hand.

    Here: four names held at weight and kept, N15 leaving at rank 16 on a line whose proceeds plus
    the cash fund less than the slot N04 takes. The cash is that night's TFSA balance — 1,458.90
    USD and 47.33 CAD — at USDCAD 1.40. Returns (days, deployable), the deployable cash worked out
    by hand: the cash, converted, plus 1,200 × N15's decision close."""
    days = _world(cur)
    _cash(cur, days, 1_458.90, cad=47.33, usdcad=1.40)
    for t in ("N00.US", "N01.US", "N02.US", "N03.US"):
        cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                       values (%s,'TFSA','momentum',1000,40.0,'open')""", (t,))
    cur.execute("""insert into book (ticker,account,sleeve,qty,avg_cost,status)
                   values ('N15.US','TFSA','momentum',1200,40.0,'open')""")
    return days, 1_458.90 + 47.33 / 1.40 + 1_200 * _close(cur, "N15.US", days[-1])


def test_a_fill_is_the_lesser_of_its_slot_and_deployable_cash(db, migrated):
    """§3.5 (v1.1): "Order size = the lesser of slot weight and deployable TFSA cash — TFSA cash on
    the book plus the same session's sell proceeds, marked at the decision close." On the 10-05
    shape, re-derived by hand: the one buy gets deployable cash // its close, not NAV ÷ 5 // it,
    and it says so — "a slot filled below weight counts as filled and is reported"."""
    nav = 200_000.0
    with db.cursor() as cur:
        days, deployable = _ten_oh_five(cur)
        out_px, in_px = _close(cur, "N15.US", days[-1]), _close(cur, "N04.US", days[-1])
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], nav)

    slot_qty = int(nav / 5 // in_px)
    expect = min(slot_qty, int(deployable // in_px))
    assert expect < slot_qty, "the 10-05 shape: proceeds and cash fund less than a slot"
    sells = [o for o in s["orders"] if o["action"] == "sell"]
    buys = [o for o in s["orders"] if o["action"] == "buy"]
    assert [(o["ticker"], o["qty"], o["mark"]) for o in sells] == [("N15.US", 1200, out_px)]
    assert [o["ticker"] for o in buys] == ["N04.US"]
    assert buys[0]["qty"] == expect, f"v1.1 gives {expect}; NAV ÷ 5 alone gives {slot_qty}"
    assert buys[0]["below_weight"] is True and buys[0]["slot_qty"] == slot_qty
    assert f"{expect:,} of {slot_qty:,} shares" in buys[0]["why"]
    assert s["sizing"]["buys"] == 1
    assert s["sizing"]["deployable"] == pytest.approx(deployable)
    assert s["sizing"]["alloc"] == pytest.approx(deployable)
    text = desk.render(s)
    assert "below §3.5 weight" in text and "deployable TFSA cash" in text


def test_several_buys_share_deployable_cash_equally_each_capped_at_its_slot(db, migrated):
    """§3.5 (v1.1): "When several buys share a session, deployable cash divides equally among
    them, each capped at slot weight." Five free slots and 50,000 of cash is 10,000 a buy against a
    40,000 slot, so every fill is below weight by the same share and the night never spends cash it
    does not have. With 1,000,000 of cash every buy stops at its slot."""
    nav = 200_000.0
    with db.cursor() as cur:
        days = _world(cur, cash=50_000.0)
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], nav)
    buys = [o for o in s["orders"] if o["action"] == "buy"]
    assert len(buys) == 5
    for o in buys:
        assert o["qty"] == min(int(nav / 5 // o["mark"]), int(50_000.0 / 5 // o["mark"]))
        assert o["below_weight"] is True
    assert sum(o["qty"] * o["mark"] for o in buys) <= 50_000.0

    with db.cursor() as cur:
        _cash(cur, days, 1_000_000.0)
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], nav)
    assert all(o["qty"] == engine.position_size(nav, o["mark"]) and not o["below_weight"]
               for o in s["orders"] if o["action"] == "buy"), "capped at slot weight"


def test_a_buy_the_cash_cannot_reach_is_reported_and_never_ticketed(db, migrated):
    """v1.1: a shortfall "is reported as held-below-weight, not funded". Ten dollars over five buys
    is two dollars a buy, which buys no share of anything: no buy is proposed, and the sheet names
    each slot left unfilled and why."""
    with db.cursor() as cur:
        days = _world(cur, cash=10.0)
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    assert not [o for o in s["orders"] if o["action"] == "buy"], "a zero-share buy is no order"
    assert [h["ticker"] for h in s["held_below"]] == ["N00.US", "N01.US", "N02.US", "N03.US",
                                                      "N04.US"]
    assert all("buys no whole share" in h["why"] for h in s["held_below"])
    assert "no ticket" in desk.render(s)


def test_a_nav_from_an_override_still_takes_its_cash_from_the_store(db, migrated):
    """Fail closed. A NAV given by `config` or the environment sizes the slot and says nothing
    about the money in the account. With no TFSA anchor the store cannot state deployable cash, so
    every buy is written unsized with the reason — never sized off NAV ÷ 5 alone, which is how 580
    ASX reached a sheet that could fund 512. A TFSA cannot hold negative cash either, so a cash
    that derives below zero is no better than none."""
    with db.cursor() as cur:
        days = _world(cur)                                      # no anchor
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    buys = [o for o in s["orders"] if o["action"] == "buy"]
    assert len(buys) == 5 and all(o["qty"] is None for o in buys)
    assert "no balances anchor for TFSA" in s["sizing"]["unsized"]
    assert all("unsized" in o["why"] for o in buys)

    with db.cursor() as cur:
        _cash(cur, days, -50.0)
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    assert all(o["qty"] is None for o in s["orders"] if o["action"] == "buy")
    assert "cannot hold negative cash" in s["sizing"]["unsized"]


def test_the_park_is_not_drawn_for_buys_that_were_not_sized(db, migrated):
    """QC A23: the fund sell shipped whenever any buy row existed, sized or not. With NAV unknown
    the buys carry no quantity and `score`'s amber holds them — and the park was sold into cash for
    orders nobody could place. The park pays for sized buys only."""
    with db.cursor() as cur:
        days = _world(cur, cash=0.0)
        _park(cur, days)
        _shadow_passed(cur, days)
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], None)
    assert [o for o in s["orders"] if o["action"] == "buy"], "the buys still stand, unsized"
    assert not [o for o in s["orders"] if o["clause"] == "fund"], "and the park is not drawn"


def test_the_park_is_not_drawn_beside_a_hold(db, migrated):
    """A23's other shape: buys a hold has stopped. With a held name dark tonight (R2) the buys are
    held, so the park is not sold to pay for them; they are sized to the cash and the night's
    proceeds alone, for the record."""
    with db.cursor() as cur:
        days = _world(cur, held=("N00.US", "N01.US", "N02.US", "N15.US"), cash=0.0)
        _park(cur, days)
        _shadow_passed(cur, days)
        cur.execute("delete from prices where ticker = 'N02.US' and d = %s", (days[-1],))
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    assert not [o for o in s["orders"] if o["clause"] == "fund"], "the park is not drawn"
    assert s["hold"] and [o for o in s["orders"] if o["action"] == "buy"], "beside held buys"


def test_a_gate_off_sheet_proposes_no_park_buy(db, migrated):
    """§3.4 (v1.1): "Park, interim (ruled 2026-10-06): USD cash in the TFSA — no park purchase is
    executed while OFF." So a gate-off sheet sells the book and buys nothing — not SPY.US, not
    anything — whatever cash and park the account holds. QC A16 asked for a SPY.US park buy under
    v1.0's text; v1.1 made the park cash, and this pins that no sheet ever prints one."""
    with db.cursor() as cur:
        days = _world(cur, rising=False, held=("N00.US", "N01.US"), cash=50_000.0)
        _park(cur, days, ticker="SPY.US", qty=40, px=500.0)
        _shadow_passed(cur, days)
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    assert s["gate"] == "OFF"
    assert not [o for o in s["orders"] if o["action"] == "buy"], "no buys of any kind while OFF"
    assert "SPY.US" not in [o["ticker"] for o in s["orders"]], "the park: neither bought nor drawn"
    assert sorted(o["ticker"] for o in s["orders"]) == ["N00.US", "N01.US"]


def test_a_benchmark_missing_from_the_newest_session_proposes_nothing(db, migrated):
    """Zak, 2026-10-07 (R1): "if the gate cannot be evaluated on fresh data (SPY missing from the
    newest session's tape, or the tape older than §5.6's 4-day constant) it is unevaluated: the
    sheet proposes nothing new, buys are held, and the brief names the stale bar".

    Before it, `load` took its calendar from SPY's own bars, so a SPY bar missing from tonight's
    tape quietly re-scored LAST night's session — its orders proposed again as tonight's, the
    names' newest prints dropped (QC A39). Here the names print the last session and SPY does not,
    with a rank exit and free slots that would otherwise trade."""
    with db.cursor() as cur:
        days = _world(cur, held=("N00.US", "N01.US", "N15.US"), cash=200_000.0)
        cur.execute("delete from prices where ticker = 'SPY.US' and d = %s", (days[-1],))
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    assert s["orders"] == [], "nothing new — no exit re-proposed, no buy"
    assert s["stale"]["index_bar"] == str(days[-2]) and s["stale"]["tape_bar"] == str(days[-1])
    assert len(s["hold"]) == 1
    assert f"newest bar is {days[-2]}" in s["hold"][0] and f"printed {days[-1]}" in s["hold"][0]
    assert "missing from the newest session's tape" in s["hold"][0]
    text = desk.render(s)
    assert "unevaluated on fresh data" in text and "nothing new is proposed" in text


def test_a_stale_gate_never_sells_the_book(db, migrated):
    """R1's last clause: "a data outage alone never sells the book". The benchmark has rolled over
    and its newest bar reads the gate OFF — but that bar is a session behind the names, so the gate
    is unevaluated and no gate-off sheet is written on it. (The OFF it reached on fresh data was
    that session's own sheet, which stands.)"""
    with db.cursor() as cur:
        days = _world(cur, rising=False, held=("N00.US", "N01.US"))
        cur.execute("delete from prices where ticker = 'SPY.US' and d = %s", (days[-1],))
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    assert s["gate"] == "OFF", "the stale series says OFF"
    assert not [o for o in s["orders"] if o["clause"] == "gate_off"], "and sells nothing on it"
    assert s["stale"] is not None


def test_a_tape_older_than_the_four_day_constant_proposes_nothing(db, migrated):
    """R1's other half: "the tape older than §5.6's 4-day constant". Five days after the newest bar
    the gate is unevaluated and nothing is proposed; four days is one long weekend (§5.6), and the
    sheet stands."""
    with db.cursor() as cur:
        days = _world(cur, held=("N15.US",), cash=200_000.0)
    db.commit()
    with db.cursor() as cur:
        late = desk.sheet(cur, days[-1] + dt.timedelta(days=5), 200_000.0)
        weekend = desk.sheet(cur, days[-1] + dt.timedelta(days=4), 200_000.0)
    assert late["orders"] == [] and late["stale"]["age_days"] == 5
    assert "older than §5.6's 4" in late["hold"][0]
    assert weekend["stale"] is None and weekend["orders"], "four days is one long weekend"


def test_a_holiday_print_by_a_name_the_engine_never_ranks_is_not_a_session(db, migrated):
    """Why R1 asks the names the engine RANKS and not every stock row. The vendor ships thin files
    for US market holidays — the store holds stock bars dated 2026-05-25, 06-19, 07-03 and 09-07
    from OTC lines and dead tickers no live session ever ranked — so the whole store's newest bar
    names each holiday as the newest session, and would hold every buy on the morning after it."""
    with db.cursor() as cur:
        days = _world(cur, cash=200_000.0)
        holiday = days[-1] + dt.timedelta(days=1)
        cur.execute("""insert into universe (ticker,name,kind,currency,status)
                       values ('OTCY.US','OTCY','stock','USD','active')""")
        cur.execute("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                       values ('OTCY.US',%s,16.5,16.6,16.4,16.58,16.58,78782)""", (holiday,))
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, holiday, 200_000.0)
    assert not s.get("stale") and not s.get("hold") and s["session"] == days[-1]
    assert len([o for o in s["orders"] if o["action"] == "buy"]) == 5


def test_a_held_name_with_no_bar_keeps_its_slot_and_holds_the_buys(db, migrated):
    """Zak, 2026-10-07 (R2): a held name with no bar on the decision session "is never turned into
    a rank exit or a refill by inference: the name keeps its last recorded quantity and its slot,
    buys are held, and it is named until Zak records what happened."

    QC A70 and A3: it was sold in full as a rank exit — with no mark, unexecutable after a rename —
    and its slot refilled; a halted rank-2 holding went round trip on a decision the rank never
    made. Here N02 misses tonight's bar while N15 leaves at rank 16: N15's slot refills, and the
    dark name's does not."""
    with db.cursor() as cur:
        days = _world(cur, held=("N00.US", "N01.US", "N02.US", "N15.US"), cash=200_000.0)
        cur.execute("delete from prices where ticker = 'N02.US' and d = %s", (days[-1],))
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    assert "N02.US" not in [o["ticker"] for o in s["orders"]], "not sold, not replaced"
    assert [o["ticker"] for o in s["orders"] if o["action"] == "sell"] == ["N15.US"]
    assert len([o for o in s["orders"] if o["action"] == "buy"]) == 2, \
        "five slots: N00, N01 and the dark N02 hold three, so two fill — N15's and the empty one"
    assert s["unbarred"] == ["N02.US"] and "N02.US" not in s["unranked"]
    assert len(s["hold"]) == 1 and "N02.US" in s["hold"][0] and "keeps its slot" in s["hold"][0]
    assert f"newest bar {days[-2]}" in s["hold"][0]


def test_a_gate_off_still_sells_a_held_name_with_no_bar_unpriced(db, migrated):
    """R2's other half: "A gate-off still lists it to sell (§5.4), marked unpriced." The exit is an
    obligation whatever the tape knows about the name; what the sheet cannot give it is a decision
    close it does not have."""
    with db.cursor() as cur:
        days = _world(cur, rising=False, held=("N00.US", "N01.US"))
        cur.execute("delete from prices where ticker = 'N01.US' and d = %s", (days[-1],))
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    sells = {o["ticker"]: o for o in s["orders"] if o["action"] == "sell"}
    assert sorted(sells) == ["N00.US", "N01.US"]
    assert all(o["clause"] == "gate_off" for o in sells.values())
    assert sells["N01.US"]["qty"] == 100 and sells["N01.US"]["mark"] is None
    assert "unpriced" in sells["N01.US"]["why"] and sells["N00.US"]["mark"] is not None
    assert s["unbarred"] == ["N01.US"] and "listed to sell" in s["hold"][0]


def test_a_holding_that_left_the_universe_sells_at_its_decision_close(db, migrated):
    """A name excluded since it was bought has no column on the tape — and it printed tonight, so
    its sell carries the close it printed, and its proceeds count toward the night's deployable
    cash (§3.5, v1.1). It used to be written with no mark at all."""
    with db.cursor() as cur:
        days = _world(cur, held=("N00.US",), excluded=("N00.US",), cash=0.0)
        px = _close(cur, "N00.US", days[-1])
    db.commit()
    with db.cursor() as cur:
        s = desk.sheet(cur, days[-1], 200_000.0)
    sell = next(o for o in s["orders"] if o["action"] == "sell")
    assert (sell["ticker"], sell["mark"]) == ("N00.US", px)
    assert s["sizing"]["proceeds"] == pytest.approx(100 * px), "its proceeds fund tonight's buys"
