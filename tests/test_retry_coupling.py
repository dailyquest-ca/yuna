"""The retry's identity lives in more than one place. Learning 58: change one, change all of them.

These tests are the "all of them". Each copy below was right on the day it was written; what fails
is the edit that moves one copy and not its twin, and nothing at the time says so.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# "the night is already green": a green, non-dry ingest-daily run inside the retry's lookback
NIGHT_GREEN = re.compile(r"status\s*=\s*'green'\s+and\s+dry_run\s*=\s*false\s+and\s+started_at\s*>"
                         r"\s*now\(\)\s*-\s*interval\s*'(\d+) hours'\s+and\s+not\s*\(detail\s*\?\s*"
                         r"'awaiting_vendor'\)")


def test_a_cancelled_trigger_judges_the_night_by_the_retrys_own_window():
    """QC 2026-10-07 (A48). `report_fail.py` decides whether a cancelled ingest firing lost
    anything by asking the question the retry asks before it skips — the same predicate and the
    same four hours (§5.6, 2026-09-13). If the retry's window moves and this copy does not, a
    cancelled firing is judged by a night the retry no longer recognises."""
    retry = NIGHT_GREEN.findall((SRC / "ingest.py").read_text())
    autopsy = NIGHT_GREEN.findall((SRC / "report_fail.py").read_text())
    assert len(retry) == 1, "the retry's own test is where it was"
    assert autopsy == retry, f"report_fail's window {autopsy} is not the retry's {retry}"
