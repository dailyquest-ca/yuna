"""What the fundamentals extractor must say about a filing, pinned to the plan's own words.

These are the rules that shipped green and wrong before: a name whose statement currency we never
read was scored as though it matched ours, and the hurdle's share count was re-derived from tonight's
quote instead of frozen at the filing. Both are one-line rules with expensive consequences, so each
gets a test that fails before the fix and passes after it.
"""
import json
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import fundamentals as fu                                                # noqa: E402


def doc(**over):
    """A minimal but complete three-year filer. Override any section to break one rule at a time."""
    years = {"2025-12-31": {}, "2024-12-31": {}, "2023-12-31": {}}
    is_y = {k: dict(ebit=1000.0, incomeTaxExpense=200.0, incomeBeforeTax=1000.0,
                    totalRevenue=10000.0 - 1000.0 * i, netIncome=800.0, ebitda=1400.0,
                    currency_symbol="USD", filing_date="2026-02-14")
            for i, k in enumerate(years)}
    bs_y = {k: dict(totalStockholderEquity=5000.0, cashAndShortTermInvestments=500.0,
                    shortLongTermDebtTotal=1000.0, netDebt=500.0, goodWill=100.0,
                    commonStockSharesOutstanding=1000.0, filing_date="2026-02-14")
            for k in years}
    cf_y = {k: dict(freeCashFlow=700.0, capitalExpenditures=-300.0, depreciation=200.0,
                    changeInWorkingCapital=-50.0, totalCashFromOperatingActivities=1000.0,
                    filing_date="2026-02-14")
            for k in years}
    base = {
        "General": dict(Code="TEST", Name="Test Co", Sector="Technology",
                        Industry="Software - Infrastructure", CurrencyCode="USD",
                        PrimaryTicker="TEST.US", UpdatedAt="2026-07-31"),
        "Highlights": dict(MarketCapitalization=1_000_000.0, EBITDA=1400.0),
        "SharesStats": dict(SharesOutstanding=1000.0),
        "Financials": {"Income_Statement": {"yearly": is_y},
                       "Balance_Sheet": {"yearly": bs_y, "quarterly": {}},
                       "Cash_Flow": {"yearly": cf_y, "quarterly": {}}},
        "Earnings": {"History": {}},
    }
    for k, v in over.items():
        if v is None:
            base.pop(k, None)
        else:
            base[k] = v
    return base


# --------------------------------------------------- §3.0 · unknown currency is not agreement

def test_unknown_statement_currency_routes_to_data_confidence():
    """§3.0: eligible only when FCF and cap are in one currency — 'or the statement currency is
    unknown → data-confidence path'. Silence is not a match."""
    d = doc()
    for section in ("Income_Statement", "Cash_Flow", "Balance_Sheet"):
        for row in d["Financials"][section]["yearly"].values():
            row.pop("currency_symbol", None)
    row = fu.extract("TEST.US", d, "USD")
    assert row["statement_currency"] is None
    assert row["data_confidence"] == "flagged"


def test_known_matching_currency_scores_full():
    row = fu.extract("TEST.US", doc(), "USD")
    assert row["statement_currency"] == "USD"
    assert row["quote_ok"] is True
    assert row["data_confidence"] == "full"


# --------------------------------------------------- §3.1 · the cap's as_of date

def test_cap_as_of_takes_the_vendor_stamp():
    """The vendor stamps General.UpdatedAt; §3.1 freezes the share count against that date's close."""
    assert fu.extract("TEST.US", doc(), "USD")["cap_as_of"] == "2026-07-31"


def test_cap_as_of_falls_back_to_the_fetch_date():
    """'the fetch date when no statement date is given' — never null, or the count cannot freeze."""
    d = doc()
    d["General"].pop("UpdatedAt")
    row = fu.extract("TEST.US", d, "USD")
    assert row["cap_as_of"] is not None
    assert row["effective_shares"] is None      # filled from our own bars, after the write


# --------------------------------------------------- §4.1 · the raw document is kept

def test_raw_document_is_stored_whole():
    """§4.1 moved the filing into the database. The derived extract stays beside it, not instead."""
    row = fu.extract("TEST.US", doc(), "USD")
    kept = json.loads(row["raw_doc"])
    assert kept["General"]["Code"] == "TEST"
    assert "Financials" in kept                                  # the statements, not a summary
    assert "yearly" in json.loads(row["raw"])                    # the derived series survives too


# --------------------------------------------------- §3.1 C1 · the debt tripwire has a floor

def test_debt_growth_is_only_a_kill_above_one_turn_of_leverage():
    """V4b: 'the growth test applies only above 1.0× net debt/EBITDA; below, C2 flag, never a kill.'
    A near-zero base makes any growth read as infinite — MSFT, GOOGL and BKNG all died here."""
    d = doc()
    ys = sorted(d["Financials"]["Balance_Sheet"]["yearly"], reverse=True)
    d["Financials"]["Balance_Sheet"]["yearly"][ys[0]]["netDebt"] = 700.0     # grew a lot...
    d["Financials"]["Balance_Sheet"]["yearly"][ys[-1]]["netDebt"] = 100.0
    row = fu.extract("TEST.US", d, "USD")
    assert row["net_debt_ebitda"] < 1.0
    assert row["debt_grows_faster"] is True                       # observed, and reported
    assert "growing faster" not in (row["c1_fail_reason"] or "")  # but never a kill down here
    assert row["c1_pass"] is True
