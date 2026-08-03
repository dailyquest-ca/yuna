"""The fair multiple's window (§3.1: the stock's own FIVE-year median P/FCF).

This test exists because the bound was invisible for as long as it did not bite. With three years
of bars stored, "every quarter we can price" and "the last twenty quarters" were the same set, so
an unbounded median looked correct. The ten-year backfill makes them different, and an unbounded
median would quietly start answering a different question — what the business was worth across a
cycle and a half, rather than lately.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import score                                                              # noqa: E402


def quarters(n, start_year=2016):
    """n quarter-ends, oldest first, as the extractor stores them: [date, ttm_fcf, shares]."""
    out = []
    y, m = start_year, 3
    for _ in range(n):
        out.append([f"{y}-{m:02d}-28", 100.0, 10.0])
        m += 3
        if m > 12:
            m, y = 3, y + 1
    return out


def closes_at(qs, price):
    return {str(q[0])[:7]: price for q in qs}


def test_the_median_uses_the_most_recent_twenty_quarters():
    """Ten years priced, five years counted — and the newest five, not the oldest."""
    old, new = quarters(20, 2014), quarters(20, 2019)
    raw = {"quarterly_fcf": old + new}
    closes = {**closes_at(old, 500.0), **closes_at(new, 100.0)}    # 50x then 10x
    median, n = score.pfcf_history(raw, closes)
    assert n == 20                                   # the window, not the 40 available
    assert median == 10.0                            # the recent regime, not a blend


def test_a_short_history_still_reports_what_it_has():
    """Fewer than the window is not an error — it is the count §3.1's 12-quarter test reads."""
    qs = quarters(9, 2023)
    median, n = score.pfcf_history({"quarterly_fcf": qs}, closes_at(qs, 200.0))
    assert n == 9 and median == 20.0


def test_unpriceable_quarters_do_not_consume_the_window():
    """A quarter we cannot price is not an observation, so it must not push a priceable one out —
    otherwise a gap in the bars silently shortens the median's reach."""
    qs = quarters(30, 2016)
    closes = closes_at(qs[:5], 100.0)                # only the five OLDEST are priceable
    closes.update(closes_at(qs[-3:], 100.0))         # plus the three newest
    median, n = score.pfcf_history({"quarterly_fcf": qs}, closes)
    assert n == 8 and median == 10.0


def test_the_window_is_the_five_years_the_plan_names():
    """20 quarters is 5 years. Stated as its own assertion so a change to the constant has to be
    a deliberate act rather than a side effect."""
    assert score.FAIR_WINDOW_QUARTERS == 20
