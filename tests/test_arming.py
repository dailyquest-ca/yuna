"""Tests for the arming layer's own plumbing — no database, no vendor.

These exist because the first live run of the arming layer died on a NOT NULL column that every caller
had left to a default that did not exist. The formula tests would never have caught it; a
ten-line test on the collector would have.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))


def _arm():
    """Import Arm without pulling in psycopg — arming imports db, which imports psycopg."""
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "arming.py").read_text()
    start = src.index("class Arm:")
    end = src.index("def arm_exits")
    ns = {"dry": lambda: True, "jsonb": lambda o: o}
    exec(compile(src[start:end], "arming_arm", "exec"), ns)
    return ns["Arm"]


def test_every_armed_row_carries_an_urgency():
    """`armed.urgency` is NOT NULL. Most conclusions are normal; protective is the exception."""
    Arm = _arm()
    a = Arm()
    a.add("entry", "RS.US", "trigger", trigger_price=419.83)
    a.add("stop_move", "NVDA.US", "trail", urgency="protective", stop=176.20)
    assert [r["urgency"] for r in a.rows] == ["normal", "protective"]
    assert all(r.get("urgency") for r in a.rows)


def test_add_returns_the_row_it_appended():
    Arm = _arm()
    a = Arm()
    row = a.add("exit", "TSM.US", "stop", stop=180.0)
    assert row is a.rows[-1] and row["kind"] == "exit" and row["reason"] == "stop"


def test_protective_rows_are_distinguishable_from_offerable_ones():
    """R1 and R2 split on exactly this: protective survives a stale night, nothing else does."""
    Arm = _arm()
    a = Arm()
    a.add("exit", "A.US", "stop", urgency="protective")
    a.add("entry", "B.US", "trigger")
    a.add("entry", "C.US", "trigger", blocked_by="§2.1 — sleeve full")
    protective = [r for r in a.rows if r["urgency"] == "protective"]
    offerable = [r for r in a.rows if r["urgency"] != "protective" and not r.get("blocked_by")]
    assert len(protective) == 1 and len(offerable) == 1
