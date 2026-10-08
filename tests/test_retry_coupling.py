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


# ---- the night already green (QC 2026-10-07, A48, A53) ------------------------------------------

# The predicate from `status = 'green'` to its `order by`: in `report_fail.py` the NIGHT_GREEN
# string, in `ingest.py` the query inside `night_already_green` — scoped to that function, because
# the module has other queries over `runs`.
PREDICATE = re.compile(r"status\s*=\s*'green'(.*?)order\s+by", re.S)
RETRY = re.compile(r"\ndef night_already_green\(.*?(?=\ndef )", re.S)
AUTOPSY = re.compile(r'NIGHT_GREEN = """(.*?)"""', re.S)


def clauses(sql):
    """One copy of the predicate as a set of clauses, whitespace normalised. The retry's
    `id <> %s` is left out on purpose: it keeps the retry from counting its own row, and a cancelled
    firing that never opened a heartbeat has no row to count."""
    match = PREDICATE.search(sql)
    assert match, "no `status = 'green' … order by` predicate here"
    parts = (" ".join(c.split()) for c in re.split(r"\s+and\s+", match.group(1)))
    return {c for c in parts if c and c != "id <> %s"}


def retry_and_autopsy():
    retry = RETRY.findall((SRC / "ingest.py").read_text())
    autopsy = AUTOPSY.findall((SRC / "report_fail.py").read_text())
    assert len(retry) == 1 and len(autopsy) == 1, "each copy is where it was"
    return retry[0], autopsy[0]


def test_a_cancelled_trigger_judges_the_night_by_the_retrys_own_test():
    """`report_fail.py` decides whether a cancelled ingest firing lost anything by asking the
    question the retry asks before it skips — every clause of it, the four hours included (§5.6,
    2026-09-13). The window was once the only clause compared; then the retry learned that only a
    scheduled firing landing tonight's tape counts (A53), the copy did not, and a hand dispatch's
    green repair of an older session would have told the autopsy a cancelled firing lost nothing
    while the retry, asked the same night, refetched."""
    retry, autopsy = retry_and_autopsy()
    assert "started_at > now() - interval '4 hours'" in clauses(retry)
    assert clauses(autopsy) == clauses(retry), (
        f"the autopsy's test differs from the retry's: "
        f"only the retry asks {sorted(clauses(retry) - clauses(autopsy))}, "
        f"only the autopsy asks {sorted(clauses(autopsy) - clauses(retry))}")


@pytest.mark.parametrize("drop", ["detail ? 'schedule'", "coalesce(rows_written, 0) > 0",
                                  "interval '4 hours'"])
def test_the_guard_fires_when_the_retry_moves_and_the_copy_does_not(drop):
    retry, autopsy = retry_and_autopsy()
    moved = (retry.replace(drop, "interval '6 hours'") if "hours" in drop
             else retry.replace(f"and {drop}", ""))
    assert moved != retry, f"the edit under test reached the retry's query: {drop}"
    assert clauses(moved) != clauses(autopsy)
