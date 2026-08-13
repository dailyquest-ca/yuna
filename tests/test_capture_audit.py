"""The capture audit's arithmetic, on hand-built names and trades.

The audit exists because run 55's headline numbers were consistent with a working arm while six of
the window's ten biggest winners had never been entered. So the case that matters most here is the
one that reads as *absence*: a name with no trades at all must survive into the winners table and
be counted as a miss, because a name that is silently dropped is exactly the failure the instrument
was built to catch. No database, no network — `audit()` is pure by design.
"""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from capture_audit import audit                                          # noqa: E402


def name(ret, bars=2244, addv=50e6, med_close=100.0):
    return dict(ret=ret, bars=bars, addv=addv, med_close=med_close)


def trade(ticker, pnl=0.0, bars_held=10):
    return dict(ticker=ticker, pnl=pnl, bars_held=bars_held)


# ------------------------------------------------------------------- the run-55 signature

def test_a_winner_never_entered_is_ranked_and_counted_as_missed():
    """MSFT compounds for nine years, the arm never buys it once. It must appear."""
    names = {"MSFT": name(6.48), "BLDR": name(1.20)}
    res = audit(names, [trade("BLDR", pnl=500)], top_n=10)

    msft = next(w for w in res["winners"] if w["ticker"] == "MSFT")
    assert msft["trades"] == 0
    assert msft["captured"] is False
    assert msft["pnl"] is None                      # never entered is not the same as flat
    assert res["summary"]["never_entered"] == 1
    assert res["summary"]["never_entered_tickers"] == ["MSFT"]
    assert res["summary"]["capture_rate"] == pytest.approx(0.5)


def test_winners_rank_by_buy_and_hold_not_by_what_was_traded():
    names = {"NVDA": name(54.45), "AAPL": name(7.48), "META": name(2.50)}
    res = audit(names, [trade("META", pnl=254)] * 9, top_n=3)
    assert [w["ticker"] for w in res["winners"]] == ["NVDA", "AAPL", "META"]


def test_top_n_truncates_the_ranking():
    names = {f"T{i}": name(float(i)) for i in range(20)}
    res = audit(names, [], top_n=5)
    assert [w["ticker"] for w in res["winners"]] == ["T19", "T18", "T17", "T16", "T15"]
    assert res["summary"]["top_n"] == 5


# ------------------------------------------------------------------- holds, P&L, aggregates

def test_a_name_held_briefly_at_a_loss_is_captured_by_presence_and_missed_by_outcome():
    """NVDA, run 55: two trades, three days, −$3,327. Present in the book, absent from the trend."""
    names = {"NVDA": name(54.45)}
    res = audit(names, [trade("NVDA", pnl=-1800, bars_held=3),
                        trade("NVDA", pnl=-1527, bars_held=3)], top_n=10)

    nvda = res["winners"][0]
    assert nvda["captured"] is True and nvda["trades"] == 2
    assert nvda["avg_hold"] == pytest.approx(3.0)
    assert nvda["pnl"] == pytest.approx(-3327)
    assert res["summary"]["never_entered"] == 0     # capture by presence...
    assert res["summary"]["pnl_on_winners"] == pytest.approx(-3327)   # ...and the outcome shown


def test_a_null_hold_never_reads_as_a_zero_day_hold():
    """Averaging over trades that recorded a hold, not over all trades."""
    names = {"AAPL": name(7.48)}
    res = audit(names, [trade("AAPL", bars_held=78), trade("AAPL", bars_held=None)], top_n=10)
    assert res["winners"][0]["avg_hold"] == pytest.approx(78.0)


def test_a_name_with_no_recorded_holds_reports_no_average():
    names = {"AAPL": name(7.48)}
    res = audit(names, [trade("AAPL", bars_held=None)], top_n=10)
    assert res["winners"][0]["avg_hold"] is None
    assert res["winners"][0]["trades"] == 1


def test_totals_span_every_name_while_winner_pnl_spans_only_the_winners():
    names = {"NVDA": name(54.45), "SEDG": name(0.30)}
    res = audit(names, [trade("NVDA", pnl=-3327), trade("SEDG", pnl=900),
                        trade("TSEM", pnl=120)], top_n=1)          # TSEM has no price row
    s = res["summary"]
    assert s["pnl_on_winners"] == pytest.approx(-3327)
    assert s["pnl_total"] == pytest.approx(-2307)
    assert s["names_traded"] == 3 and s["trades"] == 3


def test_bought_instead_ranks_by_trade_count():
    names = {"NVDA": name(54.45), "BLDR": name(1.2), "DDS": name(0.9)}
    res = audit(names, [trade("BLDR")] * 5 + [trade("DDS")] * 3 + [trade("NVDA")], top_n=3)
    assert [r["ticker"] for r in res["bought_instead"]] == ["BLDR", "DDS", "NVDA"]
    assert res["bought_instead"][0]["trades"] == 5


# ------------------------------------------------------------------- eligibility is opt-in

def test_filters_are_off_by_default():
    """One arm's floors are not another arm's, so nothing is filtered unless asked."""
    names = {"PENNY": name(9.0, bars=30, addv=100e3, med_close=0.80)}
    res = audit(names, [], top_n=10)
    assert [w["ticker"] for w in res["winners"]] == ["PENNY"]


@pytest.mark.parametrize("kwargs", [
    dict(min_price=5.0),                 # E3's price floor
    dict(min_addv=10e6),                 # E3's liquidity floor
    dict(min_bars=252),
])
def test_each_floor_excludes_when_opted_into(kwargs):
    names = {"PENNY": name(9.0, bars=30, addv=100e3, med_close=0.80), "MSFT": name(6.48)}
    res = audit(names, [], top_n=10, **kwargs)
    assert [w["ticker"] for w in res["winners"]] == ["MSFT"]
    assert res["summary"]["eligible_names"] == 1


def test_a_name_without_a_usable_price_pair_is_not_ranked():
    names = {"IPO": name(None, bars=1), "MSFT": name(6.48)}
    res = audit(names, [], top_n=10)
    assert [w["ticker"] for w in res["winners"]] == ["MSFT"]


def test_an_empty_run_reports_total_absence_rather_than_failing():
    names = {"MSFT": name(6.48), "NVDA": name(54.45)}
    res = audit(names, [], top_n=10)
    assert res["summary"]["capture_rate"] == pytest.approx(0.0)
    assert res["summary"]["never_entered"] == 2
    assert res["bought_instead"] == []
