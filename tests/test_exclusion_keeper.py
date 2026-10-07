"""The line a duplicate-listing exclusion keeps, read back out of the row that names it.

`universe_excluded` has no column for the keeper; every row names it in prose, and the Saturday
census reads it back (`funnel.kept_line`) to ask §3.2's "keep the line still printing" of each row,
every week (QC 2026-10-07, A51). A human writes prose and a job reads tokens (learning 27), so the
interface is pinned here against the way the rows are actually written: the strings below are the
production rows verbatim, one per writer, and the scan's own writer is called rather than copied.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import dedupe_scan                                                        # noqa: E402
import funnel                                                             # noqa: E402


@pytest.mark.parametrize("detail,kept", [
    # 041, by hand — the row A17 is about. It keeps the dead line, and the census must still be
    # able to READ which line that is, or it could never say so.
    ("same series as TPX.US (Tempur Sealy renamed); keep TPX", "TPX.US"),
    ("same series as SGH.US; keep SGH", "SGH.US"),
    ("share-class spelling of GEF-B.US", "GEF-B.US"),
    ("share-class spelling of FOUR-P-A.US", "FOUR-P-A.US"),
    # 050 and 056, by hand
    ("same daily returns as BALL.US (99.4% of 1445 shared sessions) — Ball Corp renamed; keep BALL",
     "BALL.US"),
    ("same series as TBSI.US (100.0% of 1675 shared sessions); Q marks Chapter 11 status, not a "
     "security — keep the company's own ticker. Ruled by Zak 2026-08-16", "TBSI.US"),
    ("same company as VVUS.US (96.1% of 3853 shared sessions); Q marks Chapter 11 status, and the "
     "shared history far exceeds a bankruptcy window — the vendor back-filled this symbol with the "
     "base line's past. Keep VVUS. Ruled by Zak 2026-08-16", "VVUS.US"),
    # the 2026-08-13 pass, including an `_old` keeper and a hyphenated one
    ("same series as CNH_old.US (1952 of 1954 overlapping closes identical); CNH_old.US runs to "
     "2024-05-20 with 1955 bars against this line's 1954 to 2024-05-17 — keep the line that is "
     "still printing", "CNH_old.US"),
    ("same series as CWEN-A.US (2442 of 2442 overlapping closes identical); CWEN-A.US runs to "
     "2026-06-26 with 2481 bars against this line's 2442 to 2026-04-30 — keep the line that is "
     "still printing", "CWEN-A.US"),
    ("same daily returns as XYZ.US (2121 of 2121 overlapping sessions identical to 1e-9); XYZ.US "
     "runs to 2026-08-12 with 2518 bars against this line's 2122 to 2025-01-21 — keep the line "
     "that is still printing", "XYZ.US"),
    ("pre-merger line of MMAT.US (1,213 of 1,229 overlapping daily returns identical); MMAT carries "
     "the full history, keep it", "MMAT.US"),
    ("same series as LAZRQ.US (1,660 identical close+volume bars); LAZRQ is the longer line, keep it",
     "LAZRQ.US"),
    # a one-letter symbol: the keeper is the symbol, not the first capital after the phrase
    ("same series as P.US (2432 of 2432 overlapping closes identical); P.US runs to 2026-08-12",
     "P.US"),
])
def test_every_way_the_table_names_a_keeper_is_read(detail, kept):
    assert funnel.kept_line(detail) == kept


def test_the_scans_own_writer_is_read_back():
    """The only automated writer. If its phrasing drifts, the census stops being able to check a
    row it wrote — so the test calls the writer rather than copying its format string."""
    detail = dedupe_scan.exclusion_detail("BALL.US", 0.9942, 1445, 1500,
                                          "threshold 0.2341 read from a 26.0x gap in the census")
    assert detail.startswith("same daily returns as BALL.US (0.9942 of 1445 moving sessions")
    assert funnel.kept_line(detail) == "BALL.US"


@pytest.mark.parametrize("detail", [None, "", "planted by hand, no keeper named",
                                    "keep the line that is still printing"])
def test_a_row_that_names_no_keeper_reads_as_none(detail):
    """None, never a guess: the census flags a printing line it cannot check rather than inventing
    a keeper for it."""
    assert funnel.kept_line(detail) is None
