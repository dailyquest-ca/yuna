"""§3.1 Gate C1's bank/insurer exclusion, pinned to the vendor's own strings (ruling B4).

This rule decides who is even eligible for the compounder bench, and it had no test. The previous
implementation keyword-matched and excluded an entire ruled-in cohort; the point-in-time compounder
backtest lost the exclusion altogether and let a reinsurer take a slot. Both directions matter, so
both are asserted here.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from fundamentals import excluded_industry                                # noqa: E402


def test_deposit_takers_and_underwriters_are_excluded():
    """EBITDA is meaningless for them — that is the whole reason for the gate."""
    for industry in ("Banks - Regional", "Banks - Diversified", "Insurance - Life",
                     "Insurance - Property & Casualty", "Insurance - Reinsurance",
                     "banks - regional"):                                # case-insensitive
        excluded, missing = excluded_industry(industry)
        assert excluded is True, industry
        assert missing is False


def test_fee_businesses_stay_eligible():
    """B4 is explicit: Insurance Brokers, Credit Services, Capital Markets and the rest of
    Financial Services remain eligible. The old keyword sweep excluded all of these."""
    for industry in ("Insurance Brokers", "Credit Services", "Capital Markets",
                     "Asset Management", "Financial Data & Stock Exchanges",
                     "Mortgage Finance", "Financial Conglomerates", "Shell Companies"):
        excluded, missing = excluded_industry(industry)
        assert excluded is False, industry
        assert missing is False


def test_ordinary_industries_are_untouched():
    for industry in ("Semiconductors", "Steel", "Software - Application", "Medical Devices"):
        assert excluded_industry(industry) == (False, True) or excluded_industry(industry)[0] is False


def test_a_missing_industry_is_not_excludable_and_says_so():
    """§3.1: 'A name with no vendor industry is not excludable by this test — the gap is named on
    its C2 memo.' Silence must not become exclusion, and it must not become silence either."""
    for value in (None, "", "   "):
        excluded, missing = excluded_industry(value)
        assert excluded is False
        assert missing is True


def test_the_bare_category_names_are_excluded_too():
    """Some vendor rows carry the family without the suffix."""
    assert excluded_industry("Banks")[0] is True
    assert excluded_industry("Insurance")[0] is True


def test_a_name_containing_bank_is_not_excluded_by_accident():
    """'Bank' inside another word is not a deposit-taker. This is what pinning to vendor strings
    buys us over keyword matching."""
    assert excluded_industry("Beverages - Non-Alcoholic")[0] is False
    assert excluded_industry("Banking Software")[0] is False
