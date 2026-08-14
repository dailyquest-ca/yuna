"""The duplicate-listing scan's pure arithmetic.

The scan's whole point is that its threshold is READ off the census distribution rather than
chosen, so the two things worth pinning are the gap-finder that reads it and the refusal to
propose a cut when there is no gap to read. Both are the difference between a rule and a fit.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import dedupe_scan as ds                                                    # noqa: E402


def test_the_gap_finder_reads_the_separation_in_the_measured_population():
    """The 18 pairs measured on 2026-08-14 fall in two clumps with nothing between them: the
    duplicate listings score 0.85-1.00 on daily-return agreement and the genuinely different
    securities score 0.006-0.033. The scan must find THAT gap and not one inside either clump."""
    clones = [1.0000, 0.9990, 0.9955, 0.9942, 0.9939, 0.9912, 0.9885, 0.9763,
              0.9599, 0.9599, 0.9599, 0.9523, 0.9236, 0.8710, 0.8518]
    distinct = [0.0332, 0.0144, 0.0056]
    lo, hi, ratio = ds.widest_gap(clones + distinct)
    assert lo == 0.0332 and hi == 0.8518, "the gap is between the two populations"
    assert ratio > 25
    cut = (lo * hi) ** 0.5
    assert all(c > cut for c in clones)
    assert all(d < cut for d in distinct)


def test_a_continuum_yields_no_defensible_threshold():
    """Evenly spaced scores have no gap, and a cut placed in one is fitted rather than read. The
    scan's contract is that it proposes nothing in that case — see THRESHOLD_MIN_GAP."""
    even = [0.50 + 0.02 * i for i in range(20)]
    lo, hi, ratio = ds.widest_gap(even)
    assert ratio < ds.THRESHOLD_MIN_GAP


def test_the_gap_finder_needs_two_points():
    assert ds.widest_gap([]) is None
    assert ds.widest_gap([0.9]) is None


def test_zero_scores_do_not_manufacture_an_infinite_gap():
    """A pair that agrees on nothing scores 0.0, and 0 -> anything is an infinite ratio. That
    would let a single non-duplicate define the threshold for the whole census."""
    lo, hi, ratio = ds.widest_gap([0.0, 0.0, 0.40, 0.95, 0.96])
    assert lo == 0.40 and hi == 0.95


def test_the_return_tolerance_is_looser_than_the_rounding_it_has_to_survive():
    """048 compared daily returns at 1e-9 and split the duplicate population in half: two vendor
    copies of one series, quoted in cents, differ in the fifth decimal of a daily return from
    rounding alone. A $30 stock moving a cent is 3.3e-4, so the tolerance has to sit above the
    rounding noise and below any real difference between two securities."""
    assert ds.TOL > 1e-9
    assert ds.TOL <= 1e-4
    # and a flat day must not count as agreement
    assert ds.MOVED > 0


@pytest.mark.parametrize("bars,last,expect", [
    # later last bar wins, whatever the bar count
    ({"A.US": (100, "2026-01-01"), "B.US": (5000, "2025-01-01")}, None, "A.US"),
    # tie on last bar -> more bars
    ({"A.US": (100, "2026-01-01"), "B.US": (5000, "2026-01-01")}, None, "B.US"),
    # tie on both -> lower ticker
    ({"A.US": (100, "2026-01-01"), "B.US": (100, "2026-01-01")}, None, "A.US"),
])
def test_the_keeper_rule_is_a_total_order(bars, last, expect):
    """047's rule: keep the line that is still printing. It must be a TOTAL order — if two lines
    could tie all the way down, the group's winner is ambiguous and a re-run could exclude a
    different member each time, which is how a company disappears from the census."""
    class FakeCur:
        def execute(self, *a): pass
        def fetchall(self): return [(t, b, l) for t, (b, l) in bars.items()]
    assert ds.keeper(FakeCur(), set(bars)) == expect
