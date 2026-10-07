"""§3.5 as v1.1 amended it (promoted 2026-10-06), tested against what the plan SAYS.

    "Order size = the lesser of slot weight and deployable TFSA cash... When several buys share a
     session, deployable cash divides equally among them, each capped at slot weight... A slot
     filled below weight counts as filled and is reported; it is never topped up."
    "Buys never draw on capital outside the TFSA; a shortfall beyond TFSA park and cash is
     reported as held-below-weight, not funded."

The arithmetic lives in `engine.py` so the desk that sizes an order and the gauge that re-derives
it read one definition. And §5.6's 4-day constant, now read by two jobs, is held to one number.
"""
import inspect
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import db                                                                 # noqa: E402
import engine                                                             # noqa: E402


def test_a_buy_is_the_lesser_of_its_slot_and_its_share_of_cash():
    """The 2026-10-05 shape in numbers: NAV 138,063.46 makes a 27,612.69 slot, 580 ASX at 47.53.
    WDC's 53 shares at 441.64 plus 1,458.90 of cash is 24,865.82 deployable — 523 shares."""
    nav, px = 138_063.46, 47.53
    deployable = 1_458.90 + 53 * 441.64
    assert engine.position_size(nav, px) == 580
    assert engine.capped_size(nav, px, deployable) == 523 == int(deployable // px)
    assert engine.capped_size(nav, px, 1e9) == 580, "capped at slot weight"
    assert engine.capped_size(nav, px, 0.0) == 0, "no cash, no shares — reported, not funded"


def test_a_buy_never_sizes_against_a_missing_or_negative_share():
    with pytest.raises(ValueError):
        engine.capped_size(200_000.0, 50.0, None)
    with pytest.raises(ValueError):
        engine.capped_size(200_000.0, 50.0, -0.01)


def test_the_park_pays_the_shortfall_in_whole_shares_and_never_more_than_the_lot():
    """The park covers what cash and proceeds do not — whole shares, enough to cover it — and a
    shortfall beyond the lot is the lot: the rest is held below weight, not funded."""
    assert engine.park_draw(60_000.0, 810, 155.5) == math.ceil(60_000.0 / 155.5) == 386
    assert engine.park_draw(155.5, 810, 155.5) == 1, "exactly one share's worth is one share"
    assert engine.park_draw(200_000.0, 810, 155.5) == 810, "never more than the lot"
    assert engine.park_draw(0.0, 810, 155.5) == 0 and engine.park_draw(-5.0, 810, 155.5) == 0
    with pytest.raises(ValueError):
        engine.park_draw(100.0, 810, None)


def test_the_four_day_constant_is_one_number():
    """§5.6, 2026-09-13: "bars older than 4 days hold buys". `freshness` holds the buys on it and
    `desk.gate_unevaluable` holds the gate on it (Zak's ruling, 2026-10-07); learning 58's lesson is
    that a constant written twice is changed once. `freshness`'s default must be the named one."""
    assert db.STALE_DAYS == 4
    assert inspect.signature(db.freshness).parameters["stale_days"].default == db.STALE_DAYS
