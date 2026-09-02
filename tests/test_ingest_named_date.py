"""The named-date ingest path (learning 59).

A missed session used to be repairable only while it was still the vendor's newest day. These
pin the two things that make the repair safe: the requested date threads into EVERY bulk call
(bars, splits, dividends), and a blank or malformed input behaves the way learning 36 says a
workflow_dispatch input does — set, as "", never absent.
"""
import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import ingest  # noqa: E402


def _capture(monkeypatch):
    seen = []

    def fake_get(path, calls, **params):
        seen.append((path, dict(params)))
        return []

    monkeypatch.setattr(ingest, "get", fake_get)
    return seen


def test_a_named_date_threads_into_the_bars_call(monkeypatch):
    seen = _capture(monkeypatch)
    ingest.bulk_day([0], date=dt.date(2026, 8, 31))
    assert seen == [("eod-bulk-last-day/US", {"date": "2026-08-31"})]


def test_a_named_date_threads_into_corporate_actions_too(monkeypatch):
    """A repaired day's splits and dividends must be THAT day's, not the newest day's."""
    seen = _capture(monkeypatch)
    ingest.bulk_day([0], kind="dividends", date=dt.date(2026, 8, 31))
    assert seen == [("eod-bulk-last-day/US", {"type": "dividends", "date": "2026-08-31"})]


def test_no_date_asks_for_the_newest_day_exactly_as_before(monkeypatch):
    seen = _capture(monkeypatch)
    ingest.bulk_day([0])
    assert seen == [("eod-bulk-last-day/US", {})]


def test_blank_input_means_newest_because_a_dispatch_input_arrives_set(monkeypatch):
    """Learning 36: a blank workflow_dispatch input is "", not absent."""
    monkeypatch.setenv("INGEST_DATE", "   ")
    assert ingest.requested_tape_date() is None
    monkeypatch.delenv("INGEST_DATE", raising=False)
    assert ingest.requested_tape_date() is None


def test_a_named_date_parses_and_a_malformed_one_raises_before_any_fetch(monkeypatch):
    monkeypatch.setenv("INGEST_DATE", "2026-08-31")
    assert ingest.requested_tape_date() == dt.date(2026, 8, 31)
    monkeypatch.setenv("INGEST_DATE", "31/08/2026")
    with pytest.raises(ValueError):
        ingest.requested_tape_date()
