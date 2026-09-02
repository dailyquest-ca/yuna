"""§4.7's drift record under the 22:23 UTC slot (2026-09-02).

A schedule never fires early. The old ±12h heuristic read a slot that had drifted past twelve
hours as "early by the remainder" — unreachable from 02:23, reachable from 22:23 (learning 58
measured 707 minutes). The number decides nothing (§4.7), which is exactly why it must be right:
it is the only witness to the queue.
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import db as dbm  # noqa: E402


def _drift_for(monkeypatch, due):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    hb = dbm.Heartbeat(None, "ingest-daily", dry_run=False, scheduled_utc=due.strftime("%H:%M"))
    hb._drift()
    return hb.detail


def test_thirteen_hours_behind_is_thirteen_hours_late_not_eleven_early(monkeypatch):
    due = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=13)
    d = _drift_for(monkeypatch, due)
    assert 13 * 60 - 2 <= d["late_minutes"] <= 13 * 60 + 2
    assert d["schedule"]["drift_minutes"] == d["late_minutes"]


def test_a_slot_still_ahead_on_todays_clock_was_yesterdays(monkeypatch):
    due = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    d = _drift_for(monkeypatch, due)
    assert 23 * 60 - 2 <= d["late_minutes"] <= 23 * 60 + 2


def test_three_hours_late_reads_as_before(monkeypatch):
    due = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)
    d = _drift_for(monkeypatch, due)
    assert 178 <= d["late_minutes"] <= 182


def test_a_hand_dispatch_has_no_appointment_to_be_late_for(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    hb = dbm.Heartbeat(None, "ingest-daily", dry_run=False, scheduled_utc="22:23")
    hb._drift()
    assert "schedule" not in hb.detail and "late_minutes" not in hb.detail
