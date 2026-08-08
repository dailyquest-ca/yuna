"""§3.0's one-currency law, as arithmetic: foreign statements restated at fiscal-period-end FX.

The defect these pin is the most expensive kind — green, plausible, and wrong by a factor. TSM.US
stored `statement_currency='TWD'` against a USD market cap, so its FCF yield, hurdle and gap were
all out by roughly thirty times and its implied P/FCF read 1.76x. About 185 more universe names
carried non-USD statement currencies and were excluded from the compounder funnel rather than
converted, which is not what §3.0 says to do with them.

Two rules do the work and each gets a test that fails before the fix:

  * every period converts at **its own** fiscal-period-end rate, never at tonight's;
  * the market cap is never converted — §3.1 makes the vendor's figure the authority that already
    resolves ADR ratios, listing currency and share class.
"""
import datetime as dt
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import db                                                                # noqa: E402
import fundamentals as fu                                                # noqa: E402
from test_extract import doc                                             # noqa: E402


TWD = 0.0325          # USD per TWD, the rate at the newest period end
TWD_OLD = 0.0300      # and an older, different one — so a single-rate conversion cannot pass


def twd_rates():
    """An FX book quoting TWD, with a step between the fiscal years."""
    rows = []
    d = dt.date(2022, 1, 1)
    while d <= dt.date.today():
        rows.append((d, TWD_OLD if d < dt.date(2025, 6, 30) else TWD))
        d += dt.timedelta(days=1)
    return db.FxRates({"TWD": rows})


def twd_doc(**over):
    """The USD fixture, refiled in New Taiwan dollars — same business, different unit."""
    d = doc(**over)
    for section in ("Income_Statement", "Cash_Flow", "Balance_Sheet"):
        for row in d["Financials"][section]["yearly"].values():
            row["currency_symbol"] = "TWD"
    d["General"]["PrimaryTicker"] = "2330.TW"        # a depositary receipt, like TSM
    return d


# --------------------------------------------------- the pair convention, both directions

def test_the_pair_convention_round_trips():
    """Majors quote XXXUSD, everything else USDXXX. `fx_pair` and `fx_pair_currency` are inverses,
    which is the only reason nothing downstream has to know which way round a pair reads."""
    assert db.fx_pair("TWD") == ("USDTWD.FOREX", True)
    assert db.fx_pair("EUR") == ("EURUSD.FOREX", False)
    assert db.fx_pair("USD") is None and db.fx_pair("") is None
    assert db.fx_pair_currency("USDTWD.FOREX") == ("TWD", True)
    assert db.fx_pair_currency("EURUSD.FOREX") == ("EUR", False)
    assert db.fx_pair_currency("GSPC.INDX") == (None, False)


def test_an_inverted_pair_is_read_as_usd_per_unit():
    """USDJPY prints ~150; a yen is worth 1/150 of a dollar, and the loader must know that."""
    rates = db.FxRates({"JPY": [(dt.date(2025, 12, 31), 1 / 150.0)]})
    rate, as_of, exact = rates.usd_per("JPY", "2025-12-31")
    assert rate == pytest.approx(1 / 150.0) and exact is True and as_of == dt.date(2025, 12, 31)


def test_usd_is_its_own_rate_and_a_missing_currency_is_none():
    assert db.FxRates().usd_per("USD", "2025-12-31")[0] == 1.0
    assert db.FxRates().usd_per("TWD", "2025-12-31")[0] is None


def test_a_date_older_than_every_bar_is_marked_inexact():
    """§3.0 wants the period-end rate. The closest observation is the honest substitute and it
    travels marked, so a name whose LATEST period needed one is flagged rather than used."""
    rates = db.FxRates({"TWD": [(dt.date(2024, 1, 1), TWD)]})
    rate, as_of, exact = rates.usd_per("TWD", "2019-12-31")
    assert rate == pytest.approx(TWD) and exact is False and as_of == dt.date(2024, 1, 1)


# --------------------------------------------------- §3.0 · the conversion itself

def test_foreign_statements_are_restated_into_the_market_cap_currency():
    """The whole point: FCF and market cap end up in one currency, so P/FCF is a multiple again."""
    native = fu.extract("TSM.US", twd_doc(), "USD")                    # no FX book — as it was
    converted = fu.extract("TSM.US", twd_doc(), "USD", fx=twd_rates())

    assert native["quote_ok"] is False and native["data_confidence"] == "flagged"
    assert converted["quote_ok"] is True
    assert converted["converted_to_usd"] is True
    assert converted["statement_fx_rate"] == pytest.approx(TWD)
    assert converted["statement_fx_as_of"] is not None

    assert converted["fcf_ttm"] == pytest.approx(native["fcf_ttm"] * TWD)
    assert converted["market_cap"] == native["market_cap"], "the vendor cap is already USD (§3.1)"
    # 1.76x was the number on the real TSM row. The multiple only becomes a multiple after this.
    assert converted["pfcf_current"] == pytest.approx(native["pfcf_current"] / TWD)


def test_each_period_converts_at_its_own_period_end_rate():
    """§3.0 says *fiscal-period-end* FX, not one rate for the whole document. The fixture's rate
    steps between fiscal years, so a single-rate conversion gets the three-year sums wrong."""
    r = fu.extract("TSM.US", twd_doc(), "USD", fx=twd_rates())
    # 2025 converts at 0.0325; 2024 and 2023 at 0.0300 — 700 of FCF in each of three years
    assert r["fcf_3y"] == pytest.approx(700.0 * TWD + 700.0 * TWD_OLD * 2)
    assert r["fcf_3y"] != pytest.approx(700.0 * 3 * TWD), "one rate for every period is not §3.0"
    fx = json.loads(r["raw"])["fx"]
    assert fx["from"] == "TWD" and fx["to"] == "USD"
    assert len(fx["periods"]["cash_yearly"]) == 3, "the receipt names every period it converted"


def test_currency_neutral_ratios_are_untouched_by_the_conversion():
    """ROIC, cash conversion and net debt / EBITDA are ratios of same-period figures, so the rate
    cancels. If any of them moves, the conversion has touched something it should not have."""
    native = fu.extract("TSM.US", twd_doc(), "USD")
    conv = fu.extract("TSM.US", twd_doc(), "USD", fx=twd_rates())
    for field in ("roic", "reinvest_rate", "cash_conversion", "net_debt_ebitda", "tax_rate",
                  "engine", "net_issuance_3y"):
        assert conv[field] == pytest.approx(native[field]), f"{field} is not a currency-free ratio"
    assert conv["shares_out"] == native["shares_out"], "a share count is a count, not money"


def test_growth_is_measured_in_the_currency_we_underwrite_in():
    """The one figure that MUST move, and it is the point rather than a side effect.

    Converting each period at its own period-end rate means multi-year growth is measured in the
    currency the hurdle is priced in. A local-currency grower whose currency halved has not
    compounded a USD shareholder's money, and §3.2 already names the pathology from the momentum
    side — "EM ADRs whose EPS is inflation- or FX-flattered pass this test mechanically". §3.1's
    engine cross-check and the growth-derived fallback both read this number, so a name can change
    provenance on conversion; that is the honest answer changing, not the formula.
    """
    native = fu.extract("TSM.US", twd_doc(), "USD")
    conv = fu.extract("TSM.US", twd_doc(), "USD", fx=twd_rates())
    assert conv["revenue_cagr_3y"] != pytest.approx(native["revenue_cagr_3y"])
    # the fixture's currency APPRECIATED into the newest year, so USD growth exceeds local growth
    assert conv["revenue_cagr_3y"] > native["revenue_cagr_3y"]


def test_an_unconvertible_currency_stays_on_the_data_confidence_path():
    """§3.0: 'if conversion data is unavailable … → data-confidence path'. No rate, no score."""
    r = fu.extract("TSM.US", twd_doc(), "USD", fx=db.FxRates({"EUR": [(dt.date.today(), 1.1)]}))
    assert r["quote_ok"] is False
    assert r["converted_to_usd"] is False
    assert r["data_confidence"] == "flagged"


def test_a_depositary_receipt_is_eligible_once_it_is_in_one_currency():
    """Migration 011 vetoed every ADR as 'deliberately deferred rather than approximated'. §3.1
    gives the vendor cap the job of resolving ADR ratios, and with the statements converted it
    does — so the veto retires rather than surviving as a second, redundant gate."""
    r = fu.extract("TSM.US", twd_doc(), "USD", fx=twd_rates())
    assert json.loads(r["raw"])["fx"]["is_depositary_receipt"] is True
    assert r["quote_ok"] is True and r["c1_pass"] is True


def test_a_name_already_in_the_cap_currency_is_never_converted():
    """CNQ.TO reports in CAD and the vendor prices it in CAD. There is nothing to convert, and
    converting anyway would break a row that was already right."""
    d = doc()
    for section in ("Income_Statement", "Cash_Flow", "Balance_Sheet"):
        for row in d["Financials"][section]["yearly"].values():
            row["currency_symbol"] = "CAD"
    r = fu.extract("CNQ.TO", d, "CAD", fx=db.FxRates({"CAD": [(dt.date(2020, 1, 1), 0.73)]}))
    assert r["quote_ok"] is True and r["converted_to_usd"] is False
    assert r["fcf_ttm"] == pytest.approx(700.0), "untouched"
    assert r["data_confidence"] == "full"


def no_symbol_doc(**over):
    """The USD fixture as the vendor actually serves ADP, PG, KLAC, LRCX and STX: statements with
    no `currency_symbol` on them at all, and General.CurrencyCode carrying the only answer."""
    d = doc(**over)
    for section in ("Income_Statement", "Cash_Flow", "Balance_Sheet"):
        for row in d["Financials"][section]["yearly"].values():
            row.pop("currency_symbol", None)
    return d


def test_a_missing_currency_symbol_falls_back_to_the_vendors_declared_currency():
    """Silence from the vendor is not the same fact as a currency we cannot reconcile. 21 names —
    ADP, PG, KLAC, LRCX, STX among them — were losing bench eligibility to a blank field on a
    US filer that quotes and reports in the same currency."""
    r = fu.extract("ADP.US", no_symbol_doc(), "USD", fx=twd_rates())
    assert r["statement_currency"] == "USD"
    assert r["quote_ok"] is True and r["data_confidence"] == "full"
    assert json.loads(r["raw"])["fx"]["from_source"] == "general_currency_code"


def test_the_fallback_is_refused_for_a_depositary_receipt():
    """The one case the whole rule exists for: an ADR quotes USD and files in its home currency,
    so General.CurrencyCode is exactly the field that lied about TSM. No statement symbol and no
    trustworthy fallback means the name fails closed, as §3.0 says it must."""
    d = no_symbol_doc()
    d["General"]["PrimaryTicker"] = "2330.TW"          # TSM's shape: receipt here, listing there
    r = fu.extract("TSM.US", d, "USD", fx=twd_rates())
    assert r["statement_currency"] is None
    assert r["quote_ok"] is False and r["data_confidence"] == "flagged"


def test_a_stated_symbol_always_beats_the_fallback():
    """The fallback never overrides evidence — a statement that names its currency is the answer,
    even when General.CurrencyCode disagrees with it."""
    r = fu.extract("TSM.US", twd_doc(), "USD", fx=twd_rates())
    assert r["statement_currency"] == "TWD"            # not the "USD" General claims
    assert json.loads(r["raw"])["fx"]["from_source"] == "statement"


def test_the_two_flags_can_no_longer_disagree():
    """The TSM row carried quote_ok=false beside data_confidence='full' — the currency mismatch was
    visible to the scorer and invisible to §3.3's guardrails. They are one fact now."""
    for fx in (None, twd_rates(), db.FxRates()):
        r = fu.extract("TSM.US", twd_doc(), "USD", fx=fx)
        assert r["quote_ok"] is (r["data_confidence"] != "flagged") or r["data_confidence"] == "2of3"


# --------------------------------------------------- §3.1 · the P/FCF history an ADR is priced on

def quarterly_twd_doc():
    """Ordinary shares on the balance sheet, ADR-equivalents in SharesStats — TSM's real shape."""
    d = twd_doc()
    quarters = ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31"]
    d["Financials"]["Cash_Flow"]["quarterly"] = {
        q: dict(freeCashFlow=200.0, capitalExpenditures=-80.0,
                totalCashFromOperatingActivities=280.0, currency_symbol="TWD",
                filing_date="2026-02-14") for q in quarters}
    d["Financials"]["Balance_Sheet"]["quarterly"] = {
        q: dict(commonStockSharesOutstanding=5000.0) for q in quarters}   # ordinary shares
    for row in d["Financials"]["Balance_Sheet"]["yearly"].values():
        row["commonStockSharesOutstanding"] = 5000.0                      # the same basis, annually
    d["SharesStats"]["SharesOutstanding"] = 1000.0                        # 5 ordinary per receipt
    return d


def test_the_quarterly_series_is_priced_on_the_listed_share_count():
    """The P/FCF history is priced against OUR bars, which quote the receipt, not the ordinary
    share. Un-bridged, an ADR's own 5-yr median multiple is wrong by its ADR ratio — and the 30x
    ceiling hides that rather than fixing it."""
    r = fu.extract("TSM.US", quarterly_twd_doc(), "USD", fx=twd_rates())
    series = json.loads(r["raw"])["quarterly_fcf"]
    assert series, "the hurdle's own history has to exist before it can be right"
    for _period, ttm_fcf, shares, _filed in series:
        assert shares == pytest.approx(1000.0), "ordinary count bridged onto the listed basis"
        assert ttm_fcf == pytest.approx(200.0 * 4 * TWD, rel=0.15), "and the cash is in USD"
