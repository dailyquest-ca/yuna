"""The rule a corporate-action re-pull is checked by (A14): a past raw close never changes.

A split or a dividend rewrites the ADJUSTED history and leaves every raw close where it was, so a
re-pulled history must carry the raw closes the store already holds. "The same close" is judged
at the precision the vendor quoted — every case below is one production holds.
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import ingest  # noqa: E402


def test_the_vendors_own_rounding_is_not_a_disagreement():
    """DCX.US 2026-09-23..25: the bulk file wrote 0.0734 / 0.0603 / 0.0494 into the store; the
    per-ticker history serves the same sessions as 0.073 / 0.06 / 0.049."""
    assert ingest.same_close(0.0734, 0.073)
    assert ingest.same_close(0.0603, 0.06)
    assert ingest.same_close(0.0494, 0.049)
    assert ingest.same_close(83.05, 83.05) and ingest.same_close(6.17, 6.17)


def test_a_different_print_is_a_disagreement():
    assert not ingest.same_close(783.22, 391.61), "IESC.US 2025-10-01: stored at twice the price"
    assert not ingest.same_close(0.504, 2.52), "TOP.US 2026-07-16: stored at a fifth of the price"
    assert not ingest.same_close(82.4, 83.9), "CTVA.US 2026-08-28: a frozen copy of the day before"
    assert not ingest.same_close(1226.52, 744.54), "IESC.US 2026-07-31: frozen against a real print"
    assert not ingest.same_close(None, 1.0) and not ingest.same_close(1.0, "n/a")


def test_the_verdict_counts_what_the_store_holds_and_only_inside_the_reply():
    d = [dt.date(2026, 9, i) for i in range(1, 6)]
    stored = {d[0]: 100.0, d[1]: 101.0, d[2]: 102.0, d[4]: 104.0}
    reply = [dict(date=d[0].isoformat(), close=100.0), dict(date=d[1].isoformat(), close=202.0),
             dict(date=d[3].isoformat(), close=103.0)]
    agree, contradicted, missing = ingest.confirms(stored, reply)
    assert agree == 1 and contradicted == [d[1]] and missing == [d[2]], (
        "the 5th is newer than the reply's newest bar: it is kept, so it does not vote")
    assert ingest.confirms(stored, []) == (0, [], sorted(stored)), "an empty reply confirms nothing"
