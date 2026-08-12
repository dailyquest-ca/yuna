"""The class of bug the synthetic suite cannot catch.

Every fixture in `test_backtest_engine.py` is hand-built, and a hand-built fixture never contains
a split, a rename, or a duplicated vendor series. So 282 passing tests said nothing about the
defect that actually corrupted runs 18-44: the engine simulated on `prices.close`, which is the
raw print, while `prices.volume` is already split-adjusted.

What that produced, in the recorded runs:

    CMG   50:1    engine saw -98%   reality -5%
    TPX    4:1    engine saw -76%   reality -2%
    SPHR  spinoff engine saw -58%   reality -9%

In a system whose widest stop is 30%, a -98% trade is not an outlier — it is an impossibility, and
four of them were sitting in the appendix. These tests assert the guards fire, per
`.claude/rules/trading-code.md`: a guard that detects a bad state must halt, not warn and continue.
"""
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import backtest as bt                                                    # noqa: E402


def _tape(n=300, names=("AAA.US", "BBB.US")):
    """A clean two-name tape: a gentle uptrend, no corporate actions."""
    base = np.linspace(100.0, 140.0, n)
    cols = list(names)
    close = np.column_stack([base * (1 + 0.02 * i) for i in range(len(cols))])
    return dict(close=close, raw_close=close.copy()), cols, list(range(n))


def test_a_split_in_the_tape_halts_the_run():
    """The exact shape of the CMG defect: a discrete collapse in an otherwise continuous series."""
    arrays, cols, dates = _tape()
    arrays["close"][150:, 0] /= 50.0                     # a 50:1 split left unadjusted (-98%)
    with pytest.raises(bt.DataIntegrityError) as e:
        bt._assert_price_integrity(arrays, cols, dates)
    assert "AAA.US" in str(e.value)
    assert "adjusted daily moves" in str(e.value)


def test_a_clean_tape_passes():
    arrays, cols, dates = _tape()
    bt._assert_price_integrity(arrays, cols, dates)      # must not raise


def test_two_tickers_sharing_a_series_halt_the_run():
    """TPX and SGI are one company under two symbols, and runs 29/32/34/35/36 held both — double
    the intended position, while max_names, the sleeve cap and the heat cap each saw two names."""
    arrays, cols, dates = _tape(names=("TPX.US", "SGI.US"))
    arrays["close"][:, 1] = arrays["close"][:, 0]        # identical series
    arrays["raw_close"] = arrays["close"].copy()
    with pytest.raises(bt.DataIntegrityError) as e:
        bt._assert_price_integrity(arrays, cols, dates)
    assert "identical price series" in str(e.value)


def test_the_guard_tolerates_a_real_but_violent_market_move():
    """A guard that fires on genuine volatility would be turned off within a week. -45% in a day
    is a real thing that happens to real equities; the threshold sits above it on purpose."""
    arrays, cols, dates = _tape()
    arrays["close"][200:, 0] *= 0.55                     # -45%, and it stays down, as a crash does
    bt._assert_price_integrity(arrays, cols, dates)      # must not raise


def test_the_engine_reads_the_adjusted_series_everywhere_but_the_price_floor():
    """A structural guard on the correction itself. Rules read `close` (adjusted); only the $5
    L0 floor may read `raw_close`. If a second `raw_close` reader appears, this fails and someone
    has to justify it."""
    source = (ROOT / "src" / "backtest.py").read_text()
    readers = source.count('arrays["raw_close"]') + source.count('"raw_close"]')
    assert 'raw_t = arrays["raw_close"][t]' in source, "the price floor must use the raw print"
    assert "raw_t >= 5" in source, "the $5 floor is a real-world fact about the actual price"
    assert readers <= 4, (
        f"{readers} references to raw_close — the adjusted series is the decision basis and "
        f"every extra raw reader is a place a split can re-enter")


def test_the_dividend_line_is_retired_not_forgotten():
    """P&L is total return now, because dividends live inside the adjusted series. The old
    price-only P&L handicapped the sleeve against VOO, which was always total return."""
    source = (ROOT / "src" / "backtest.py").read_text()
    assert "dividend = 0.0" in source
    assert "total return" in source.lower()
