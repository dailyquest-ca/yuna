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


def test_the_reused_symbol_population_separates_where_the_whole_census_does_not():
    """Why the `_old` pass exists at all.

    Over all 471 candidate pairs the census is a continuum — the scan's own run on 2026-08-14
    reported a widest gap of 1.6x and correctly proposed nothing. But `_old` is not a score, it is
    the vendor stating that a symbol carried a different company before, and inside THAT population
    the two cases separate cleanly. These are the measured values for the 42 overlapping pairs.

    The pair that keeps this honest is WTW_old/WTW at 0.0015 — Weight Watchers against Willis
    Towers Watson. Two genuinely different companies sharing a symbol, and excluding either would
    delete real history, which is why the suffix alone can never be the rule.
    """
    same_company = [1.0000, 1.0000, 1.0000, 1.0000, 1.0000, 1.0000, 0.9991, 0.9991, 0.9978,
                    0.9974, 0.9971, 0.9958, 0.9953, 0.9947, 0.9944, 0.9931, 0.9918, 0.9860,
                    0.9838, 0.9831, 0.9810, 0.9792, 0.9788, 0.9767, 0.9513, 0.8930, 0.8736]
    ambiguous = [0.6665, 0.5434, 0.2740]     # WFRD, CBIO, GCI — reorganisations and a split
    different = [0.0516, 0.0120, 0.0066, 0.0060, 0.0053, 0.0050,
                 0.0038, 0.0036, 0.0024, 0.0016, 0.0015, 0.0010]
    lo, hi, ratio = ds.widest_gap(same_company + ambiguous + different)
    assert ratio >= ds.THRESHOLD_MIN_GAP, "this population is separated well enough to cut"
    cut = (lo * hi) ** 0.5
    assert all(s > cut for s in same_company), "every clear duplicate must land above the cut"
    assert all(d < cut for d in different), "WTW_old/WTW must survive — it is a second company"
    # The middle is NOT asserted either way, deliberately. The gap-finder puts the cut at 0.119,
    # which classes all three as duplicates; the first draft of this test asserted the opposite
    # because that was the author's reading of what WFRD and GCI are, not a measurement. A test
    # that encodes an opinion about ambiguous cases would fail whenever the data was right.
    assert lo in different and hi in ambiguous, "the cut sits below the ambiguous middle"


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


def test_a_line_an_earlier_pass_excluded_is_not_eligible_to_be_kept():
    """What killed run 31855520505. The reused-symbol pass proposed dropping `GCI_old.US` in
    favour of `GCI.US`, which an earlier pass had already excluded — so the group would have lost
    both lines and the company would have vanished from the census. 048's guard halted the run,
    correctly. The defect was upstream of the guard: the keeper rule nominated a dead line.

    `GCI.US` here is the one that would win on merit — a later last bar — and must still lose.
    """
    bars = {"GCI_old.US": (1124, "2020-11-16"), "GCI.US": (2500, "2026-08-13")}

    class FakeCur:
        def execute(self, *a): pass
        def fetchall(self): return [(t, b, l) for t, (b, l) in bars.items()]

    assert ds.keeper(FakeCur(), set(bars)) == "GCI.US", "on merit alone the live line wins"
    assert ds.keeper(FakeCur(), set(bars), {"GCI.US"}) == "GCI_old.US", (
        "an excluded line cannot be the one kept, so the survivor keeps the group alive")


def test_a_group_whose_every_line_is_excluded_still_yields_a_keeper():
    """The guard behind this must stay armed. If every member is already excluded there is no live
    line to prefer, so the rule falls back to merit and 048's check downstream is what refuses —
    silently returning nothing here would drop the group without anyone noticing."""
    bars = {"A.US": (100, "2026-01-01"), "B.US": (100, "2025-01-01")}

    class FakeCur:
        def execute(self, *a): pass
        def fetchall(self): return [(t, b, l) for t, (b, l) in bars.items()]

    assert ds.keeper(FakeCur(), set(bars), {"A.US", "B.US"}) == "A.US"
