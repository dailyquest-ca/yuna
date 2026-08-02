"""Every stored hurdle must reproduce the §3.1 floor from its own stored components.

This is a *wiring* test, and it exists because the unit test could not catch what it catches.
`test_expected_return_at_the_hurdle_equals_the_floor` supplies its own inputs and proves the solver
is self-consistent — it says nothing about whether `score.py` persisted the same numbers it solved
with. Two of six bench rows checked by hand failed exactly that way: DOCS's stored hurdle implied a
7.3% expected return against a 15% floor, and TTD's implied 11.8%, both in the direction that makes
a name look buyable.

The check is the plan's own three-eyes discipline applied to one row: what the job computed must
equal what the database holds. A hurdle that cannot be rebuilt from its own row is not a hurdle.
"""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import signals as sg                                                      # noqa: E402

TOLERANCE = 0.005          # half a percent of price; the solver is exact to the cent


def bench_rows(conn):
    with conn.cursor() as cur:
        cur.execute("""select ticker, hurdle_price, last_close, fcf_yield, engine_growth,
                              fair_multiple
                       from bench
                       where hurdle_price is not null and last_close is not null
                         and fcf_yield is not null and fair_multiple is not null""")
        return cur.fetchall()


def test_every_stored_hurdle_reproduces_the_fifteen_percent_floor(db):
    """§3.1 defines the hurdle as min(the highest price where expected return still clears 15%,
    fair multiple x FCF/share). So re-running the one solver on the row's own stored components
    must give back the stored hurdle. When the fair cap binds, ER at the hurdle sits lawfully
    above the floor — cheaper than required is never a defect; a hurdle the solver won't rebuild
    always is."""
    rows = bench_rows(db)
    if not rows:
        pytest.skip("no scored bench rows in this database")

    floor = 0.15
    broken = []
    for ticker, hurdle, px, yield_, growth, fair in rows:
        hurdle, px, yield_ = float(hurdle), float(px), float(yield_)
        growth, fair = float(growth or 0), float(fair)
        if px <= 0 or yield_ <= 0 or fair <= 0:
            continue
        # the hurdle depends only on FCF per share, growth and the fair multiple — the market cap
        # cancels out, which is what makes this reconstruction independent of the vendor's cap
        fcf_per_share = yield_ * px
        implied = sg.hurdle_price(fcf_ttm=fcf_per_share, shares=1.0, growth=growth,
                                  fair_multiple=fair, floor=floor)
        if implied is None or implied <= 0 or abs(hurdle / implied - 1) > TOLERANCE:
            broken.append(f"{ticker}: stored hurdle {hurdle:.2f}, solver says "
                          f"{implied if implied is None else round(implied, 2)}")

    assert not broken, ("stored hurdles that cannot be rebuilt from their own row:\n  "
                        + "\n  ".join(broken))


def test_gap_to_hurdle_agrees_with_the_prices_it_is_built_from(db):
    """`gap_to_hurdle` drives the entire buyable list, and `duties.refresh_marks` rewrites it
    nightly while leaving `hurdle_price` alone. If the two ever disagree the machine buys on a
    number nobody computed."""
    rows = bench_rows(db)
    if not rows:
        pytest.skip("no scored bench rows in this database")
    with db.cursor() as cur:
        cur.execute("""select ticker, gap_to_hurdle, last_close, hurdle_price from bench
                       where gap_to_hurdle is not null and hurdle_price is not null
                         and last_close is not null""")
        wrong = [f"{t}: stored {float(g):+.4f} vs computed "
                 f"{(float(px) - float(h)) / float(h):+.4f}"
                 for t, g, px, h in cur.fetchall()
                 if abs(float(g) - (float(px) - float(h)) / float(h)) > 1e-4]
    assert not wrong, "gap_to_hurdle disagrees with last_close and hurdle_price:\n  " + \
                      "\n  ".join(wrong)
