"""The refactors that moved production arithmetic into `signals.py`, held to main's answers.

Two functions were lifted out of the jobs that run nightly and into `signals` so the backtest
measures the same rule the machine executes. That is the right shape — one definition, not two —
but it is also the shape that silently changes a live number, because the caller keeps working
whatever the new code returns.

    `fundamentals.py`  M4 acceleration      ->  `signals.m4_acceleration`
    `arming.py`        confirmation state   ->  `signals.confirmation_state`

`docs/wo-a15-v1-synthesis.md` §5 listed the M4 differential test as a condition of reaching main.
This is it, and the arming one alongside it.

These tests are **written against main's implementation, transcribed here** rather than imported,
so they keep their meaning after the branch merges and main moves on. Transcribing is the whole
point: a test that imported the new code would agree with the new code and prove nothing.
"""
import itertools
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import signals as sg                                                      # noqa: E402


def m4_on_main(eps):
    """`src/fundamentals.py` at e57dd34, lines 441-449, verbatim in behaviour.

    Year-on-year EPS growth off the same quarter a year earlier, then two conditions: the latest
    growth clears 25%, or it clears 15% while accelerating on the prior reading.
    """
    yoy = []
    for i, v in enumerate(eps):
        base = eps[i + 4] if i + 4 < len(eps) else None
        yoy.append((v / base - 1) if base and base > 0 else None)
    y0 = yoy[0] if yoy else None
    y1 = yoy[1] if len(yoy) > 1 else None
    m4 = bool((y0 is not None and y0 >= 0.25) or
              (y0 is not None and y1 is not None and y0 >= 0.15 and y0 > y1))
    return y0, y1, m4


@pytest.mark.parametrize("eps", [
    [],
    [1.0],
    [1.0, 0.9, 0.8, 0.7],                       # too short for a year-on-year comparison
    [1.30, 1.10, 1.00, 0.95, 1.00, 0.95, 0.90, 0.85],     # clean acceleration
    [1.05, 1.04, 1.00, 0.95, 1.00, 0.99, 0.98, 0.97],     # growth, but under both bars
    [1.26, 1.20, 1.10, 1.00, 1.00, 1.00, 1.00, 1.00],     # exactly through the 25% bar
    [0.50, 0.60, 0.70, 0.80, 1.00, 1.00, 1.00, 1.00],     # shrinking
    [1.00, 1.00, 1.00, 1.00, 0.00, 0.00, 0.00, 0.00],     # a zero base — must not divide
    [1.00, 1.00, 1.00, 1.00, -0.50, 1.0, 1.0, 1.0],       # a negative base — must not pass
    [2.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00],     # a doubling
])
def test_m4_matches_the_implementation_it_replaced(eps):
    y0, y1, passes = m4_on_main(eps)
    out = sg.m4_acceleration(eps)
    assert out["passes"] is passes, f"M4 verdict moved for {eps}"
    for key, want in (("yoy_latest", y0), ("yoy_prev", y1)):
        got = out[key]
        if want is None:
            assert got is None, f"{key} moved for {eps}"
        else:
            assert got == pytest.approx(want, abs=1e-12), f"{key} moved for {eps}"


def test_m4_over_a_generated_sweep():
    """The named cases above are the ones a person thinks of. This is the space around them."""
    vals = (-1.0, 0.0, 0.5, 1.0, 1.15, 1.25, 1.30, 2.0)
    checked = 0
    for head in itertools.product(vals, repeat=2):
        for tail in itertools.product(vals, repeat=2):
            eps = [head[0], head[1], 1.0, 1.0, tail[0], tail[1], 1.0, 1.0]
            y0, y1, passes = m4_on_main(eps)
            out = sg.m4_acceleration(eps)
            assert out["passes"] is passes, f"M4 verdict moved for {eps}"
            if y0 is None:
                assert out["yoy_latest"] is None
            else:
                assert out["yoy_latest"] == pytest.approx(y0, abs=1e-12)
            checked += 1
    assert checked == 4096


def confirmation_on_main(volumes, baselines, *, sessions, multiple):
    """Main's answer, which lived in TWO places and is why this is worth pinning.

    `signals.breakout_confirmed` at e57dd34 returned a plain bool over the **first**
    `CONFIRM_SESSIONS` of the window::

        for v, b in list(zip(volumes, baselines))[:CONFIRM_SESSIONS]:
            if v is None or b is None or not finite or b <= 0: continue
            if v >= multiple * b: return True
        return False

    and `arming.py:291` turned that into the tri-state the book actually stores::

        expired   = len(b) - idx >= sessions
        new_state = True if ok else (False if expired else None)

    `confirmation_state` absorbed both. The first draft of this test compared against
    `breakout_confirmed` alone and took the window from the END of the list — two mistakes, and it
    failed twice against code that was right. Transcribing from the diff instead of from the
    source is how that happens.
    """
    ok = False
    for v, b in list(zip(volumes, baselines))[:sessions]:
        if v is None or b is None or b <= 0:
            continue
        if v >= multiple * b:
            ok = True
            break
    expired = len(list(volumes)) >= sessions
    return True if ok else (False if expired else None)


@pytest.mark.parametrize("vols,bases,sessions,multiple", [
    ([100, 100, 100], [100, 100, 100], 3, 1.5),          # window closed, never confirmed -> False
    ([100, 100, 250], [100, 100, 100], 3, 1.5),          # confirms on the last session
    ([250, 100, 100], [100, 100, 100], 3, 1.5),          # confirms on the breakout day
    ([250, 100], [100, 100], 3, 1.5),                    # confirms early, window still open
    ([100, 100], [100, 100], 3, 1.5),                    # inside the window -> pending (None)
    ([100, 150, 100], [100, 100, 100], 3, 1.5),          # exactly on the multiple
    ([100, 149, 100], [100, 100, 100], 3, 1.5),          # a hair under it
    ([None, 200, 100], [100, 100, 100], 3, 1.5),         # a missing volume
    ([200, 200, 200], [None, 0, 100], 3, 1.5),           # a zero and a missing baseline
    ([100, 100, 100, 250], [100, 100, 100, 100], 3, 1.5),  # the spike is PAST the window
    ([], [], 3, 1.5),
])
def test_confirmation_state_matches_the_logic_it_replaced(vols, bases, sessions, multiple):
    want = confirmation_on_main(vols, bases, sessions=sessions, multiple=multiple)
    got = sg.confirmation_state(vols, bases, sessions=sessions, multiple=multiple)
    assert got["confirmed"] is want, (
        f"confirmation moved for volumes={vols} baselines={bases} "
        f"sessions={sessions} multiple={multiple}")
