"""The class of bug the synthetic suite cannot catch.

Every fixture in `test_backtest_engine.py` is hand-built, and a hand-built fixture never contains
a split, a rename, or a duplicated vendor series. So 282 passing tests said nothing about the
defect that actually corrupted runs 18-44: the engine simulated on `prices.close`, which is the
raw print, while `prices.volume` is already split-adjusted.

What that produced, in the recorded runs:

    CMG   50:1    engine saw -98%   reality -5%
    TPX    4:1    engine saw -76%   reality -2%
    SPHR  spinoff engine saw -58%   reality -9%

The first guard written against this halted the run on any adjusted daily move beyond 85%, and
measured against the real tape it would have halted on 819 of 5,264 names — so the re-derivation
could never have started. It could not tell Yellow Corp going bankrupt from a broken series,
because on magnitude alone they are the same event.

So the gate now separates two questions, and these tests hold it to both:

    a broken TAPE halts       — asserted on its own invariant, not inferred from price behaviour
    a broken SECURITY is quarantined — dropped, counted, and named in the run record

Per `.claude/rules/trading-code.md`, a guard that detects a bad state must halt rather than warn
and continue; quarantining is not a warning, it is removal of the bad state, and the ceiling in
`screen_tape` is what keeps it from becoming one.
"""
import pathlib
import re
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import backtest as bt                                                    # noqa: E402


def _tape(n=300, names=("AAA.US", "BBB.US"), adjusted_share=0.6):
    """A clean tape: a gentle uptrend, no corporate actions, and a raw print that sits above the
    adjusted series for the earlier part of the history — which is what a dividend payer's
    `adj_close` actually looks like. 58.9% of the real tape differs from raw; the default here
    matches that order of magnitude so the tape-level invariant has something honest to measure.
    """
    base = np.linspace(100.0, 140.0, n)
    close = np.column_stack([base * (1 + 0.02 * i) for i in range(len(names))])
    raw = close.copy()
    raw[:int(n * adjusted_share), :] *= 1.03
    return dict(close=close, raw_close=raw), list(names), list(range(n))


def _wide(n=300, count=20):
    """A tape wide enough that one bad name sits under the 10% quarantine ceiling, as it does on
    the real 5,264-name universe. Quarantine tests break the FIRST name, `N0.US`."""
    return _tape(n=n, names=tuple(f"N{i}.US" for i in range(count)))


# --------------------------------------------------------------- the tape-level invariant
def test_a_raw_price_basis_halts_the_run():
    """THE regression test for runs 18-44. If the decision series is the raw print rather than
    the adjusted one, every split is about to arrive as a crash again — and unlike the old
    magnitude heuristic, this fires whether or not the window happens to contain a split."""
    arrays, cols, dates = _tape(adjusted_share=0.0)       # close == raw_close: the raw basis
    with pytest.raises(bt.DataIntegrityError) as e:
        bt.screen_tape(arrays, cols, dates)
    assert "raw print" in str(e.value)
    assert "runs 18-44" in str(e.value)


def test_a_clean_tape_passes_and_quarantines_nothing():
    arrays, cols, dates = _tape()
    assert bt.screen_tape(arrays, cols, dates) == {}


def test_two_tickers_sharing_a_series_halt_the_run():
    """TPX and SGI are one company under two symbols, and runs 29/32/34/35/36 held both — double
    the intended position, while max_names, the sleeve cap and the heat cap each saw two names."""
    arrays, cols, dates = _tape(names=("TPX.US", "SGI.US"))
    arrays["close"][:, 1] = arrays["close"][:, 0]
    arrays["raw_close"][:, 1] = arrays["raw_close"][:, 0]
    with pytest.raises(bt.DataIntegrityError) as e:
        bt.screen_tape(arrays, cols, dates)
    assert "identical price series" in str(e.value)


# ------------------------------------------------------------ quarantine, not halt
def test_an_unadjusted_split_in_one_name_is_quarantined_not_halted():
    """The CMG shape — a discrete 50:1 collapse in an otherwise continuous series. One name's
    vendor data being wrong is that name's problem; it must not cost us the other 5,263."""
    arrays, cols, dates = _wide()
    arrays["close"][150:, 0] /= 50.0
    excluded = bt.screen_tape(arrays, cols, dates)
    assert set(excluded) == {"N0.US"}
    assert "impossible" in excluded["N0.US"]


def test_a_real_bankruptcy_is_kept():
    """The failure that made the first guard unusable. Yellow Corp and Express were liquid $50
    stocks that went bankrupt; a -90% session is what that looks like, and 814 of the 819 names
    the old guard condemned pass L0 at some point. Dropping them would reintroduce exactly the
    survivorship bias runs 15+ were rebuilt to remove."""
    arrays, cols, dates = _wide()
    arrays["close"][200:, 0] *= 0.10          # -90% in one session, and it stays down
    arrays["raw_close"][200:, 0] *= 0.10
    assert bt.screen_tape(arrays, cols, dates) == {}


def test_the_guard_tolerates_a_real_but_violent_market_move():
    """RXN genuinely fell 49% in a session on a real corporate event and must pass. A guard that
    fires on real volatility gets switched off within a week."""
    arrays, cols, dates = _wide()
    arrays["close"][200:, 0] *= 0.55
    arrays["raw_close"][200:, 0] *= 0.55
    assert bt.screen_tape(arrays, cols, dates) == {}


def test_a_series_that_collapses_repeatedly_is_quarantined():
    """A company collapses once. Of the 793 violating bars in the 'down 95%+' bucket, 94 names
    carry all of them — 8.4 collapses each. That is a discontinuous series, not a business.

    The arithmetic behind counting only collapses: after a real -85% the price sits at 15% of
    its old level, so a second one from above $5 needs a ~6.7x recovery in between. Equities do
    not make that round trip."""
    arrays, cols, dates = _wide()
    for t in (100, 150, 200):                 # three round trips, all above the $5 floor
        arrays["close"][t, 0] *= 0.08
        arrays["raw_close"][t, 0] *= 0.08
    excluded = bt.screen_tape(arrays, cols, dates)
    assert set(excluded) == {"N0.US"}
    assert "collapses" in excluded["N0.US"]


def test_repeated_explosions_upward_are_momentum_not_corruption():
    """THE regression test for the guard's second draft, which counted moves in both directions
    and quarantined GME, DJT, LUNR, INSM and CHK — the January 2021 squeeze (+93% then +135%),
    the Trump Media announcement (+357%), a lunar-lander contract, a phase-3 readout. This is a
    momentum sleeve. A data guard that deletes the decade's biggest momentum events from the
    tape is worse than no guard, because it removes precisely the trades under study."""
    arrays, cols, dates = _wide()
    for t, mult in ((100, 1.93), (101, 2.35), (200, 2.04)):     # GME's actual ratios
        arrays["close"][t:, 0] *= mult
        arrays["raw_close"][t:, 0] *= mult
    assert bt.screen_tape(arrays, cols, dates) == {}


def test_a_zero_close_is_quarantined_if_it_reaches_the_screen():
    """The backstop. `load` masks non-positive prices to NaN before screening (see the test
    below), so this should never fire in the pipeline — but a zero denominator turns every
    downstream return into an infinity, which is how one bad bar becomes a whole corrupt column,
    and a caller that skips the mask must not get silence."""
    arrays, cols, dates = _wide()
    arrays["close"][220, 0] = 0.0
    excluded = bt.screen_tape(arrays, cols, dates)
    assert set(excluded) == {"N0.US"}
    assert "zero" in excluded["N0.US"]


def test_the_delisting_tail_is_masked_rather_than_condemning_the_name():
    """PACW prints adj_close 0.0000 the day it merged into Banc of California; the vendor pads
    the delisting tail the same way for CONN (5 bars), HIBB (7) and AEL (2). Those are invalid
    BARS, not invalid securities — quarantining the ticker would throw away years of valid
    history and bias the sleeve against takeouts, which are the good ending for a momentum
    position. Masking them dropped the traded-name casualty list from 16 to 5."""
    source = (ROOT / "src" / "backtest.py").read_text()
    assert 'dead = arrays["close"] <= 0.0' in source, "load must mask non-positive prices"
    assert "np.where(dead, np.nan" in source, "and mask them to NaN, not to a substitute price"
    # the mask must run BEFORE the screen, or the backstop above condemns the name first
    assert source.index('dead = arrays["close"]') < source.index("excluded = screen_tape("), \
        "the mask has to precede the screen"


def test_a_reused_ticker_is_quarantined():
    """SPDL prints a 6,900,000x session move: one ticker symbol, two unrelated companies, one
    continuous vendor series. No market does this."""
    arrays, cols, dates = _wide()
    arrays["close"][:150, 0] = 0.0001         # the dead shell that held the symbol first
    arrays["raw_close"][:150, 0] = 0.0001
    excluded = bt.screen_tape(arrays, cols, dates)
    assert set(excluded) == {"N0.US"}
    assert "impossible" in excluded["N0.US"]


def test_sub_penny_quantization_is_not_mistaken_for_a_move():
    """Under $1 the vendor's 4-decimal precision makes a ratio noise rather than a return:
    $0.0001 -> $0.0002 reads as +100%, and a shell ticking between the two bottom representable
    prices would otherwise look like a series of doublings. The basis floor is why the impossible
    check needs a real price underneath it — and the name is untradeable either way, so nothing
    here can reach the book."""
    arrays, cols, dates = _wide()
    rng = np.arange(300)
    arrays["close"][:, 0] = np.where(rng % 2 == 0, 0.0001, 0.0004)      # 4x, every other session
    arrays["raw_close"][:, 0] = arrays["close"][:, 0]
    assert bt.screen_tape(arrays, cols, dates) == {}


def test_a_discontinuity_below_the_price_floor_is_ignored():
    """§3.2 puts the sleeve out below $5, so a break down there cannot become a trade. The floor
    reads the RAW print, exactly as the L0 admission test does — an adjusted $6 on a stock that
    printed $0.30 is not a tradeable bar."""
    arrays, cols, dates = _wide()
    arrays["raw_close"][:, 0] = 0.30                    # never tradeable
    arrays["close"][120, 0] *= 0.10                     # a violent break, but out of reach
    arrays["close"][160, 0] *= 0.10
    assert bt.screen_tape(arrays, cols, dates) == {}


# --------------------------------------------------------------------- the ceiling
def test_wholesale_discontinuity_halts_rather_than_quarantining():
    """Past a ceiling the diagnosis flips. Quarantining 60% of the universe and reporting a
    number on the rest is how a broken tape produces a plausible result."""
    names = tuple(f"N{i}.US" for i in range(10))
    arrays, cols, dates = _tape(names=names)
    for j in range(6):                                   # 60%, well past the 10% ceiling
        arrays["close"][150:, j] /= 50.0
    with pytest.raises(bt.DataIntegrityError) as e:
        bt.screen_tape(arrays, cols, dates)
    assert "bad tape" in str(e.value)


# ----------------------------------------------------------------- structural guards
def test_only_the_price_floor_decides_on_the_raw_series():
    """A structural guard on the correction itself. Rules read `close` (adjusted). `raw_close` is
    legitimate in exactly three places — building the grid, the two integrity screens, and §3.2's
    $5 floor — and nowhere that ranks, scores, or sizes. Counting references is too blunt now
    that the screens read it, so this checks WHICH functions do."""
    source = (ROOT / "src" / "backtest.py").read_text()
    assert 'raw_t = arrays["raw_close"][t]' in source, "the price floor must use the raw print"
    assert "raw_t >= 5" in source, "the $5 floor is a real-world fact about the actual price"

    allowed = {"load", "_discontinuous", "_assert_price_integrity", "rank"}
    bodies = re.split(r"^def (\w+)", source, flags=re.M)
    readers = {bodies[i] for i in range(1, len(bodies), 2)
               if 'arrays["raw_close"]' in bodies[i + 1]}
    assert readers <= allowed, (
        f"{sorted(readers - allowed)} read the raw series — the adjusted series is the decision "
        f"basis and every extra raw reader is a place a split can re-enter")


def test_the_dividend_line_is_retired_not_forgotten():
    """P&L is total return now, because dividends live inside the adjusted series. The old
    price-only P&L handicapped the sleeve against VOO, which was always total return."""
    source = (ROOT / "src" / "backtest.py").read_text()
    assert "dividend = 0.0" in source
    assert "total return" in source.lower()


def test_the_exclusion_list_reaches_the_run_record():
    """An exclusion nobody can review is indistinguishable from a silent filter, and some of
    these are real bankruptcies whose absence biases the result."""
    source = (ROOT / "src" / "backtest.py").read_text()
    assert "excluded_discontinuous=frame.get" in source, "summarise must record what was dropped"
    assert "correction is imperfect" in source, "and must state the cost"
