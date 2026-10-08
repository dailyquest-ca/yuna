"""The backfill button and the feed the plan retired (A74).

§4.5 names the product — EOD Historical Data — All World — and it carries no fundamentals: since
the 2026-09 downgrade every `fundamentals/` call answers 403. The button still ran that pass by
default, swallowed each 403 into the detail, and closed green with nothing written — learning
19's "green is not a result", and learning 63's rule that a retired product's endpoints leave the
jobs the same day.

No database here: the passes are driven with a vendor and a connection that stand in for both.
"""
import datetime as dt
import importlib
import pathlib
import sys
import urllib.error

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import backfill  # noqa: E402


class Beat:
    def __init__(self):
        self.detail, self.calls, self.status = {}, [0], "green"

    def amber(self, why):
        if self.status != "red":
            self.status = "amber"
        self.detail.setdefault("amber", []).append(why)

    def red(self, why):
        self.status = "red"
        self.detail.setdefault("red", []).append(why)


class Conn:
    """Just enough connection for a pass that writes nothing: an empty universe."""

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args):
        pass

    def fetchall(self):
        return []


def test_the_default_passes_leave_the_retired_feed_out(monkeypatch):
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "backfill.yml").read_text())
    assert "fundamentals" not in doc[True]["workflow_dispatch"]["inputs"]["what"]["default"]
    monkeypatch.delenv("WHAT", raising=False)                    # a local run with no input
    assert importlib.reload(backfill).WHAT == {"bars", "dividends"}


def test_a_403_turns_the_run_red_naming_the_endpoint(monkeypatch):
    def forbidden(path, calls, **params):
        calls[0] += 1
        raise urllib.error.HTTPError(f"https://eodhd.com/api/{path}", 403, "Forbidden", {}, None)

    monkeypatch.setattr(backfill, "get", forbidden)
    hb = Beat()
    assert backfill.backfill_fundamentals(Conn(), hb, ["AAA.US", "BBB.US"]) == 0
    assert hb.status == "red"
    assert "fundamentals/ answered 403 Forbidden for 2 of 2" in hb.detail["red"][0]


def test_any_other_failure_is_amber_with_its_count_not_a_quiet_green(monkeypatch):
    def flaky(path, calls, **params):
        calls[0] += 1
        if path == "eod/BBB.US":
            raise TimeoutError("read timed out")
        return []

    monkeypatch.setattr(backfill, "get", flaky)
    hb = Beat()
    backfill.backfill_bars(Conn(), hb, ["AAA.US", "BBB.US"], dt.date(2016, 1, 1))
    assert hb.status == "amber" and "eod/ failed for 1 of 2" in hb.detail["amber"][0]
    assert "BBB.US" in hb.detail["bar_errors"]
