"""The retry's identity lives in more than one place. Learning 58: change one, change all of them.

These tests are the "all of them". Each copy below was right on the day it was written; what fails
is the edit that moves one copy and not its twin, and nothing at the time says so.
"""
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
INGEST_DAILY = ROOT / ".github" / "workflows" / "ingest-daily.yml"


# ---- the retry's cron (QC 2026-10-07, A78) ------------------------------------------------------
#
# The 23:23 firing behaves as the retry only because two step-env expressions compare
# `github.event.schedule` with its cron string, letter for letter: SKIP_IF_GREEN (exit if the night
# is green) and SCHEDULED_UTC (which slot it is late against). The workflow's header and learning 58
# both say the string lives three times (the schedule and those two), the clock twice more, and
# the first firing's clock once more as SCHEDULE_UTC's default in src/ingest.py. Move the schedule
# and not the literal, and the retry stops recognising itself: on a night the vendor posts late it
# records `awaiting_vendor` GREEN like a first firing, where it should have gone red.

TESTED = re.compile(r"github\.event\.schedule == '([^']+)'")
CLOCKS = re.compile(r"&& '(\d\d:\d\d)' \|\| '(\d\d:\d\d)'")
DEFAULT = re.compile(r'SCHEDULE_UTC = os\.environ\.get\("SCHEDULED_UTC", "(\d\d:\d\d)"\)')


def _clock(cron):
    minute, hour = cron.split()[:2]
    return f"{int(hour):02d}:{int(minute):02d}"


def coupling_breaks(workflow, ingest_source):
    """Every way the copies disagree, as sentences. An empty list is a retry that knows itself."""
    doc = yaml.safe_load(workflow)
    crons = [s["cron"] for s in doc[True]["schedule"]]
    env, = [s.get("env") or {} for s in doc["jobs"]["ingest"]["steps"]
            if "src/ingest.py" in (s.get("run") or "")]
    out = []
    tested = {k: TESTED.findall(str(env.get(k, ""))) for k in ("SKIP_IF_GREEN", "SCHEDULED_UTC")}
    for key, found in tested.items():
        if len(found) != 1:
            out.append(f"{key} should test github.event.schedule once; it tests {found}")
    literals = sorted({c for found in tested.values() for c in found})
    if len(literals) != 1:
        return out + [f"SKIP_IF_GREEN and SCHEDULED_UTC test different crons: {literals}"]
    retry, = literals
    if retry not in crons:
        return out + [f"the step tests for {retry!r}, which is not scheduled ({crons}): the retry "
                      f"would never recognise itself"]
    first = [c for c in crons if c != retry]
    if len(first) != 1:
        return out + [f"expected the first firing and the retry, scheduled: {crons}"]
    first, = first
    clocks = CLOCKS.findall(str(env.get("SCHEDULED_UTC", "")))
    if len(clocks) != 1:
        out.append("SCHEDULED_UTC no longer reads `retry-clock || first-clock`")
    else:
        (retry_clock, first_clock), = clocks
        if retry_clock != _clock(retry):
            out.append(f"SCHEDULED_UTC gives the retry {retry_clock}; its cron {retry!r} fires "
                       f"at {_clock(retry)}")
        if first_clock != _clock(first):
            out.append(f"SCHEDULED_UTC gives the first firing {first_clock}; its cron {first!r} "
                       f"fires at {_clock(first)}")
    default = DEFAULT.findall(ingest_source)
    if len(default) != 1:
        out.append("src/ingest.py's SCHEDULE_UTC default is not where it was")
    elif default[0] != _clock(first):
        out.append(f"src/ingest.py defaults SCHEDULE_UTC to {default[0]}; the first firing's cron "
                   f"{first!r} fires at {_clock(first)}")
    return out


def test_the_retry_recognises_its_own_cron_in_every_copy():
    """A78. The production nights of 2026-09-29 to 10-06 show the retry exiting "already green"
    every time, so the copies agree today; this keeps them agreeing tomorrow."""
    breaks = coupling_breaks(INGEST_DAILY.read_text(), (SRC / "ingest.py").read_text())
    assert breaks == [], "\n".join(breaks)


@pytest.mark.parametrize("old,new", [
    ("- cron: '23 23 * * 1-5'", "- cron: '53 23 * * 1-5'"),     # learning 58's own example
    ("&& '23:23' ||", "&& '23:53' ||"),                          # the retry's clock alone
    ("- cron: '23 22 * * 1-5'", "- cron: '53 22 * * 1-5'"),     # the first firing alone
], ids=["retry-cron-moved", "retry-clock-moved", "first-cron-moved"])
def test_the_guard_fires_on_each_edit_learning_58_warns_about(old, new):
    """The guard proved, not assumed: move one copy and leave its twins, and it must say so."""
    workflow = INGEST_DAILY.read_text()
    assert workflow.count(old) == 1, f"the copy {old!r} is not where it was"
    assert coupling_breaks(workflow.replace(old, new), (SRC / "ingest.py").read_text())


# ---- the night already green (QC 2026-10-07, A48) -----------------------------------------------

# "the night is already green": a green, non-dry ingest-daily run inside the retry's lookback
NIGHT_GREEN = re.compile(r"status\s*=\s*'green'\s+and\s+dry_run\s*=\s*false\s+and\s+started_at\s*>"
                         r"\s*now\(\)\s*-\s*interval\s*'(\d+) hours'\s+and\s+not\s*\(detail\s*\?\s*"
                         r"'awaiting_vendor'\)")


def test_a_cancelled_trigger_judges_the_night_by_the_retrys_own_window():
    """`report_fail.py` decides whether a cancelled ingest firing lost anything by asking the
    question the retry asks before it skips — the same predicate and the same four hours (§5.6,
    2026-09-13). If the retry's window moves and this copy does not, a cancelled firing is judged
    by a night the retry no longer recognises."""
    retry = NIGHT_GREEN.findall((SRC / "ingest.py").read_text())
    autopsy = NIGHT_GREEN.findall((SRC / "report_fail.py").read_text())
    assert len(retry) == 1, "the retry's own test is where it was"
    assert autopsy == retry, f"report_fail's window {autopsy} is not the retry's {retry}"
