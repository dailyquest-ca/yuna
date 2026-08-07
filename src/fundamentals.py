"""fundamentals — Phase D extraction sweep.

Pulls the full fundamentals document per name (broad, then filtered locally — the vendor's
section filter lies), derives the ~30 numbers the plan's formulas actually read, and appends
one row per (ticker, filing_date). Rows are never edited, so this table quietly becomes the
point-in-time history that cannot be bought (§4.8).

It also backfills sector / industry / market cap onto `universe`, which is what finally
kills the neutral-50 industry score in the MCN.

Sequential per name, 10 vendor calls each. TICKERS=A.US,B.US limits the sweep;
STALE_ONLY=true refreshes only names whose earnings date has passed since their last pull.
"""
import os, sys, json, math, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import psycopg
from db import connect, config, get, dry, FxRates, Heartbeat
import signals as sg

WORKERS = int(os.environ.get("WORKERS", "8"))
BATCH = 100
UNITS_PER_CALL = 10                       # EODHD bills a fundamentals request at ten
RESERVE = int(os.environ.get("QUOTA_RESERVE", "3000"))   # leave room for the nightly jobs
SWEEP_LIMIT = int(os.environ.get("SWEEP_LIMIT", "0"))    # 0 = everything; else top N by market cap
TOLERANCE = 0.05          # |engine - revenue CAGR| gap beyond which the engine is distrusted

# §3.1 (B4): C1 excludes only vendor industries named `Banks - …` or `Insurance - …`. EBITDA is
# meaningless for deposit-takers and underwriters — not for fee businesses, so Insurance Brokers,
# Credit Services, Capital Markets and the rest of Financial Services stay eligible. Matching the
# vendor's own strings is the whole point; the previous keyword sweep excluded a ruled-in cohort.
EXCLUDED_INDUSTRY_PREFIXES = ("banks - ", "insurance - ")
EXCLUDED_INDUSTRY_EXACT = {"banks", "insurance"}


# §3.0, the one-currency law: "foreign issuers are compounder-eligible only when FCF and market cap
# are expressed in one currency — financials converted at fiscal-period-end FX". The market cap the
# vendor serves is in the LISTING currency (USD for every US listing; CAD for CNQ.TO, checked), so
# that is the currency the statements have to be restated into — for every US listing, USD.
#
# Only these fields are money. Share counts on the balance sheet are counts and must never be
# touched; per-share EPS is left in its own currency on purpose, because M4 reads it as a YoY ratio
# where the currency cancels, and §3.2 already rules that FX-flattered EPS is a judgment call for
# the R3 workup rather than an arithmetic one.
INCOME_MONETARY = frozenset({
    "totalRevenue", "ebit", "ebitda", "netIncome", "incomeBeforeTax", "incomeTaxExpense",
    "depreciationAndAmortization", "grossProfit", "operatingIncome", "costOfRevenue"})
BALANCE_MONETARY = frozenset({
    "totalStockholderEquity", "cashAndShortTermInvestments", "cash", "shortLongTermDebtTotal",
    "longTermDebtTotal", "shortTermDebt", "netDebt", "goodWill", "totalAssets", "totalLiab"})
CASHFLOW_MONETARY = frozenset({
    "freeCashFlow", "totalCashFromOperatingActivities", "capitalExpenditures", "depreciation",
    "changeInWorkingCapital", "stockBasedCompensation", "netIncome"})


def convert_periods(table, fields, *, frm, to, fx, log):
    """A copy of `table` whose monetary `fields` are restated at each period's OWN period-end rate.

    The key of every statement table is its fiscal period end, which is exactly the date §3.0 names.
    A period with no rate keeps its raw figures and says so in `log`, so the caller can refuse to
    score a row rather than mixing two currencies inside one ratio.
    """
    if not table:
        return table, True
    out, all_exact = {}, True
    for period, row in table.items():
        rate, as_of, exact = fx.convert(frm, to, period)
        log[str(period)] = dict(rate=rate, as_of=str(as_of) if as_of else None, exact=exact)
        if rate is None or not isinstance(row, dict):
            all_exact = False
            out[period] = row
            continue
        all_exact = all_exact and exact
        converted = dict(row)
        for f in fields:
            v = num(row.get(f))
            if v is not None:
                converted[f] = v * rate
        out[period] = converted
    return out, all_exact


def excluded_industry(industry):
    """(is_excluded, industry_missing) — a name with no vendor industry is NOT excludable by this
    test; §3.1 says the gap is named on its C2 memo instead."""
    if not industry or not str(industry).strip():
        return False, True
    s = str(industry).strip().lower()
    return (s.startswith(EXCLUDED_INDUSTRY_PREFIXES) or s in EXCLUDED_INDUSTRY_EXACT), False


def num(x):
    if x is None or x == "":
        return None
    try:
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


def day(x):
    """A date the database will accept, or None. Vendors emit '0000-00-00' and ''."""
    if not x or not isinstance(x, str) or len(x) < 10:
        return None
    try:
        return dt.date.fromisoformat(x[:10]).isoformat()
    except ValueError:
        return None


def desc(d):
    return sorted((d or {}).keys(), reverse=True)


def s(vals):
    """Sum of the non-null values, or None if nothing is there."""
    got = [v for v in vals if v is not None]
    return sum(got) if got else None


def cagr(new, old, years):
    if new is None or old is None or old <= 0 or new <= 0 or years <= 0:
        return None
    return (new / old) ** (1.0 / years) - 1


# ------------------------------------------------------------------ extraction
def extract(ticker, r, quote_ccy=None, fx=None):
    G = r.get("General") or {}
    H = r.get("Highlights") or {}
    SS = r.get("SharesStats") or {}
    F = r.get("Financials") or {}
    bs_y, is_y, cf_y = (F.get(k, {}).get("yearly") or {} for k in
                        ("Balance_Sheet", "Income_Statement", "Cash_Flow"))
    cf_q = (F.get("Cash_Flow") or {}).get("quarterly") or {}
    bs_q = (F.get("Balance_Sheet") or {}).get("quarterly") or {}

    ys = desc(is_y)
    if not ys:
        return None
    n_years = len(ys)
    y3 = ys[:3]                                   # the three most recent fiscal years

    # ---- filing date (§3.3: as of filing, never period end)
    cands = []
    for tbl in (bs_y, is_y, cf_y, bs_q, cf_q):
        for k in desc(tbl)[:2]:
            fd = (tbl[k] or {}).get("filing_date")
            if fd:
                cands.append(fd)
    cands = [c for c in (day(c) for c in cands) if c]
    filing_date = max(cands) if cands else day(ys[0])
    flagged = not cands
    if not filing_date:
        return None

    # ---- identity
    sector, industry = G.get("Sector"), G.get("Industry")
    gic_s, gic_i = G.get("GicSector"), G.get("GicIndustry")
    is_fin, industry_missing = excluded_industry(industry or gic_i)
    # General.CurrencyCode lies for depositary receipts (TSM says USD, files in TWD).
    # currency_symbol sits on every statement and does not.
    stmt_ccy = None
    for tbl in (is_y, cf_y, bs_y):
        for k in desc(tbl)[:1]:
            stmt_ccy = stmt_ccy or (tbl[k] or {}).get("currency_symbol")
    primary = G.get("PrimaryTicker")
    code = G.get("Code")
    is_adr = bool(primary and code and primary.split(".")[0].upper() != str(code).upper())
    mcap = num(H.get("MarketCapitalization"))
    shares = num(SS.get("SharesOutstanding")) or num((bs_y.get(ys[0]) or {}).get("commonStockSharesOutstanding"))

    # ---- §3.0: one currency, converted at fiscal-period-end FX --------------------------------
    #
    # TSM stored `statement_currency='TWD'` against a USD market cap, so its FCF yield, hurdle and
    # gap were all wrong by roughly 30x — a P/FCF of 1.76 where the truth is in the fifties. About
    # 185 more universe names carried the same defect and were simply excluded from the compounder
    # funnel rather than converted, which is not what §3.0 says to do with them.
    #
    # Every statement is restated at the rate that stood when THAT period closed, into the currency
    # the vendor's market cap uses. The market cap itself is never touched — §3.1 makes it the
    # authority that "resolves ADR ratios, listing currency, and share class", and restating it
    # would be converting a number that is already right.
    target_ccy = (quote_ccy or "USD").upper()
    fx_rate = fx_as_of = None
    converted = False
    fx_log = {}
    if stmt_ccy and stmt_ccy.upper() != target_ccy and fx is not None:
        rate, as_of, exact = fx.convert(stmt_ccy, target_ccy, ys[0])
        if rate:
            is_y, e1 = convert_periods(is_y, INCOME_MONETARY, frm=stmt_ccy, to=target_ccy,
                                       fx=fx, log=fx_log.setdefault("income_yearly", {}))
            bs_y, e2 = convert_periods(bs_y, BALANCE_MONETARY, frm=stmt_ccy, to=target_ccy,
                                       fx=fx, log=fx_log.setdefault("balance_yearly", {}))
            cf_y, e3 = convert_periods(cf_y, CASHFLOW_MONETARY, frm=stmt_ccy, to=target_ccy,
                                       fx=fx, log=fx_log.setdefault("cash_yearly", {}))
            bs_q, e4 = convert_periods(bs_q, BALANCE_MONETARY, frm=stmt_ccy, to=target_ccy,
                                       fx=fx, log=fx_log.setdefault("balance_quarterly", {}))
            cf_q, e5 = convert_periods(cf_q, CASHFLOW_MONETARY, frm=stmt_ccy, to=target_ccy,
                                       fx=fx, log=fx_log.setdefault("cash_quarterly", {}))
            converted, fx_rate, fx_as_of = True, rate, as_of
            fx_log["latest_period_exact"] = exact
            fx_log["all_periods_exact"] = bool(e1 and e2 and e3 and e4 and e5)
            # the Highlights fallback for EBITDA is a vendor figure in the statement currency too
            if num(H.get("EBITDA")) is not None:
                H = dict(H, EBITDA=num(H["EBITDA"]) * rate)
            if not exact:
                # §3.0: "if conversion data is unavailable … → data-confidence path". A rate older
                # than the period it prices is not the rate the plan asks for, so the row is flagged
                # rather than quietly used.
                flagged = True

    # a name is priceable when its statements and its market cap are in one currency — after the
    # conversion above, not before it. Unknown statement currency is never "fine" (§3.0).
    one_currency = bool(stmt_ccy) and (stmt_ccy.upper() == target_ccy or converted)

    # ---- compounding engine
    ebit_3y = s([num(is_y[k].get("ebit")) for k in y3])
    tax_num = s([num(is_y[k].get("incomeTaxExpense")) for k in y3])
    tax_den = s([num(is_y[k].get("incomeBeforeTax")) for k in y3])
    tax_rate = min(0.5, max(0.0, tax_num / tax_den)) if tax_num is not None and tax_den else 0.21
    nopat_3y = ebit_3y * (1 - tax_rate) if ebit_3y is not None else None

    ics, ics_ex = [], []
    for k in y3:
        b = bs_y.get(k) or {}
        eq = num(b.get("totalStockholderEquity"))
        cash = num(b.get("cashAndShortTermInvestments")) or num(b.get("cash"))
        debt = num(b.get("shortLongTermDebtTotal"))
        if debt is None:
            debt = s([num(b.get("longTermDebtTotal")), num(b.get("shortTermDebt"))])
        if debt is None:
            nd = num(b.get("netDebt"))
            debt = (nd + cash) if nd is not None and cash is not None else None
        if eq is None or cash is None or debt is None:
            continue
        ic = debt + eq - cash
        ics.append(ic)
        gw = num(b.get("goodWill")) or 0.0
        ics_ex.append(ic - gw)
    ic_avg = sum(ics) / len(ics) if ics else None
    ic_avg_ex = sum(ics_ex) / len(ics_ex) if ics_ex else None

    roic = (nopat_3y / 3.0) / ic_avg if nopat_3y is not None and ic_avg and ic_avg > 0 else None
    roic_ex = (nopat_3y / 3.0) / ic_avg_ex if nopat_3y is not None and ic_avg_ex and ic_avg_ex > 0 else None

    capex_3y = s([abs(num(cf_y[k].get("capitalExpenditures")) or 0.0) for k in y3 if k in cf_y]) or 0.0
    da_3y = s([num((cf_y.get(k) or {}).get("depreciation"))
               or num((is_y.get(k) or {}).get("depreciationAndAmortization")) for k in y3]) or 0.0
    # changeInWorkingCapital is the cash impact; capital *put into* WC is its negative
    dwc_3y = -(s([num((cf_y.get(k) or {}).get("changeInWorkingCapital")) for k in y3]) or 0.0)
    reinvest = None
    if nopat_3y and nopat_3y > 0:
        reinvest = max(0.0, min(1.5, (capex_3y - da_3y + dwc_3y) / nopat_3y))
    engine = roic * reinvest if roic is not None and reinvest is not None else None

    # ---- Durability (§3.1) — two name-level facts; score.py does the cross-sectional percentiles.
    # Five YoY comparisons need six fiscal years of revenue; the denominator is always 5, so a short
    # history counts against rather than being excused.
    revenues = [num((is_y.get(k) or {}).get("totalRevenue")) for k in ys[:6]]
    growth_consistency = sg.growth_consistency(revenues)

    # Per-year ROIC over the last five, from the same definitions the 3-year figures use: NOPAT =
    # EBIT x (1 - tax), invested capital = debt + equity - cash. Per-year tax where the statement
    # gives it, the blended rate where it does not.
    per_year = []
    for k in ys[:5]:
        i_row, b_row = is_y.get(k) or {}, bs_y.get(k) or {}
        ebit_y = num(i_row.get("ebit"))
        if ebit_y is None:
            continue
        tx, pre = num(i_row.get("incomeTaxExpense")), num(i_row.get("incomeBeforeTax"))
        rate = min(0.5, max(0.0, tx / pre)) if tx is not None and pre else tax_rate
        eq_y = num(b_row.get("totalStockholderEquity"))
        cash_y = num(b_row.get("cashAndShortTermInvestments")) or num(b_row.get("cash"))
        debt_y = num(b_row.get("shortLongTermDebtTotal"))
        if debt_y is None:
            debt_y = s([num(b_row.get("longTermDebtTotal")), num(b_row.get("shortTermDebt"))])
        if eq_y is None or cash_y is None or debt_y is None:
            continue
        per_year.append((ebit_y * (1 - rate), debt_y + eq_y - cash_y))
    roic_worst, roic_years = sg.worst_year_roic(per_year)

    rev_new = num((is_y.get(ys[0]) or {}).get("totalRevenue"))
    span = min(3, n_years - 1)
    rev_old = num((is_y.get(ys[span]) or {}).get("totalRevenue")) if span >= 1 else None
    rev_cagr = cagr(rev_new, rev_old, span)
    agrees = None
    if engine is not None and rev_cagr is not None:
        # 10pp was too loose in absolute terms: a 7% grower squeaked through and then
        # underwrote at 16%. Growth dominates the hurdle, so the floor is 5pp.
        agrees = abs(engine - rev_cagr) <= max(TOLERANCE, 0.5 * abs(rev_cagr))

    # ---- cash conversion
    def fcf_reported_of(row):
        """The industry-standard figure: CFO minus capex, SBC still inside it."""
        v = num(row.get("freeCashFlow"))
        if v is not None:
            return v
        cfo = num(row.get("totalCashFromOperatingActivities"))
        cx = num(row.get("capitalExpenditures"))
        return (cfo - abs(cx)) if cfo is not None and cx is not None else None

    def fcf_of(row):
        """FCF per the glossary, 2026-08-02: reported minus stock-based compensation.

        Pay handed out as shares is pay, and with the hurdle's share count frozen at the filing the
        dilution that funds it appears nowhere else — un-deducted it is free money. Measured before
        this change on our own stored filings: SBC was 78% of TTD's reported FCF and 92% of MELI's.
        A period with no reported SBC falls back to reported and the row is stamped (§3.3) —
        `sbc_missing` tracks it via the nonlocal below.
        """
        base = fcf_reported_of(row)
        if base is None:
            return None
        sbc = num(row.get("stockBasedCompensation"))
        if sbc is None:
            nonlocal_sbc_missing[0] = True
            return base
        return base - abs(sbc)

    nonlocal_sbc_missing = [False]

    fcf_3y = s([fcf_of(cf_y[k]) for k in y3 if k in cf_y])
    ni_3y = s([num(is_y[k].get("netIncome")) for k in y3])
    cash_conv = (fcf_3y / ni_3y) if fcf_3y is not None and ni_3y and ni_3y > 0 else None

    qs = desc(cf_q)
    fcf_ttm = s([fcf_of(cf_q[k]) for k in qs[:4]]) if len(qs) >= 4 else \
              (fcf_of(cf_y[ys[0]]) if ys[0] in cf_y else None)

    # ---- owner-FCF disclosure (§3.1 quarantine, §5.5 note): the three figures every bench row
    # carries so "customer float in costume" is a number Zak reads, not a suspicion.
    if len(qs) >= 4:
        fcf_ttm_reported = s([fcf_reported_of(cf_q[k]) for k in qs[:4]])
        sbc_ttm = s([num(cf_q[k].get("stockBasedCompensation")) for k in qs[:4]])
        dwc_ttm = s([num(cf_q[k].get("changeInWorkingCapital")) for k in qs[:4]])
    else:
        fcf_ttm_reported = fcf_reported_of(cf_y[ys[0]]) if ys[0] in cf_y else None
        sbc_ttm = num((cf_y.get(ys[0]) or {}).get("stockBasedCompensation"))
        dwc_ttm = num((cf_y.get(ys[0]) or {}).get("changeInWorkingCapital"))
    sbc_ttm = abs(sbc_ttm) if sbc_ttm is not None else None

    # a quarterly TTM-FCF / shares series, so the funnel can build P/FCF history from our bars.
    #
    # The series is priced against OUR bars, which quote the listed security — and for a depositary
    # receipt that is a bundle of ordinary shares. The balance sheet counts ordinary shares while
    # SharesStats counts the listed line (TSM: 25.9bn against 5.19bn, and the vendor cap ÷ its close
    # agrees with SharesStats to eight figures), so the per-quarter count is bridged onto the listed
    # basis. Un-bridged, an ADR's own median multiple is wrong by its ADR ratio — which the 30x
    # ceiling hides rather than fixes.
    bs_latest_count = num((bs_y.get(ys[0]) or {}).get("commonStockSharesOutstanding"))
    listing_ratio = (shares / bs_latest_count) if shares and bs_latest_count else 1.0
    qseries = []
    for i in range(len(qs) - 3):
        window = qs[i:i + 4]
        v = s([fcf_of(cf_q[k]) for k in window])
        q_count = num((bs_q.get(qs[i]) or {}).get("commonStockSharesOutstanding"))
        sh = (q_count * listing_ratio) if q_count else shares
        if v is not None and sh:
            qseries.append([qs[i], v, sh, day((cf_q.get(qs[i]) or {}).get("filing_date"))])
    qseries = qseries[:24]                      # six years of quarters — the hurdle's history

    # ---- Gate C1
    fails = []
    fcf_pos = (fcf_ttm if fcf_ttm is not None else fcf_3y)
    fcf_positive = fcf_pos is not None and fcf_pos > 0
    if not fcf_positive:
        fails.append("FCF not positive")

    sh_new = num((bs_y.get(ys[0]) or {}).get("commonStockSharesOutstanding"))
    sh_span = min(3, n_years - 1)
    sh_old = num((bs_y.get(ys[sh_span]) or {}).get("commonStockSharesOutstanding")) if sh_span >= 1 else None
    issuance = cagr(sh_new, sh_old, sh_span)
    if issuance is not None and issuance > 0.02:
        fails.append(f"net issuance {issuance:.1%}/yr")

    b0 = bs_y.get(ys[0]) or {}
    net_debt = num(b0.get("netDebt"))
    if net_debt is None and ics:
        net_debt = None
    ebitda = num((is_y.get(ys[0]) or {}).get("ebitda")) or num(H.get("EBITDA"))
    nd_ebitda = (net_debt / ebitda) if net_debt is not None and ebitda and ebitda > 0 else None
    if nd_ebitda is not None and nd_ebitda > 2.5:
        fails.append(f"net debt/EBITDA {nd_ebitda:.1f}x")

    nd_old = num((bs_y.get(ys[min(3, n_years - 1)]) or {}).get("netDebt")) if n_years > 1 else None
    eb_old = num((is_y.get(ys[min(3, n_years - 1)]) or {}).get("ebitda")) if n_years > 1 else None
    debt_faster = False
    if net_debt is not None and nd_old is not None and net_debt > 0 and nd_old > 0 \
       and ebitda and eb_old and eb_old > 0:
        debt_faster = (net_debt / nd_old) > (ebitda / eb_old)
        # §3.1 C1, ruling V4b: the growth test bites only ABOVE 1.0x net debt/EBITDA. Below that the
        # level is too small for the growth to mean anything — a near-zero base makes any increase
        # read as explosive — so it becomes a C2-memo flag and never a kill. This one clause was
        # rejecting 864 of 2,832 names, more than the 623 that passed the whole gate, and it is what
        # killed MSFT, GOOGL and BKNG at 0.2-0.5x leverage in the aristocrat autopsy.
        if debt_faster and nd_ebitda is not None and nd_ebitda > 1.0:
            fails.append("net debt growing faster than EBITDA")

    if is_fin:
        fails.append(f"vendor industry '{industry}' — deposit-taker or underwriter, EBITDA is "
                     f"meaningless (§3.1 C1)")
    if n_years < 3:
        fails.append(f"only {n_years} fiscal year(s)")

    gw_new = num(b0.get("goodWill"))
    gw_old = num((bs_y.get(ys[1]) or {}).get("goodWill")) if n_years > 1 else None
    gw_jump = bool(gw_new and gw_old and gw_old > 0 and gw_new / gw_old > 1.25)

    # ---- M4 (§3.2)
    hist = (r.get("Earnings") or {}).get("History") or {}
    eps = {k: num((hist[k] or {}).get("epsActual")) for k in desc(hist)}
    reported = [(k, v) for k, v in eps.items() if v is not None]
    yoy = []
    for i, (k, v) in enumerate(reported[:8]):
        if i + 4 < len(reported):
            base = reported[i + 4][1]
            yoy.append((v / base - 1) if base and base > 0 else None)
    y0 = yoy[0] if yoy else None
    y1 = yoy[1] if len(yoy) > 1 else None
    m4 = bool((y0 is not None and y0 >= 0.25) or
              (y0 is not None and y1 is not None and y0 > y1 and y0 >= 0.15))

    have = sum(x is not None for x in (engine, cash_conv, mcap))
    # §3.0, hardened 2026-08-01 and again 2026-08-07: a foreign issuer is compounder-eligible only
    # when FCF and market cap are expressed in one currency — "if conversion data is unavailable
    # **or the statement currency is unknown** → data-confidence path". Unknown is not the same as
    # matching, and unconvertible is not the same as unknown.
    #
    # The two flags now agree by construction, which is the other half of the TSM row's defect: it
    # carried quote_ok=false beside data_confidence='full', so the currency mismatch was visible to
    # the scorer and invisible to the guardrails. A name we cannot price in one currency is on the
    # data-confidence path, full stop.
    confidence = ("flagged" if flagged or have < 2 or not one_currency
                  else ("full" if have == 3 else "2of3"))

    # §3.1: cap at price P uses effective shares = vendor cap / the close on the cap's `as_of` date,
    # frozen with the filing. The vendor stamps General.UpdatedAt; where it gives none the plan names
    # the fetch date. `cap_close` and `effective_shares` are filled from our own bars after the write
    # (freeze_effective_shares) — extraction has no database.
    cap_as_of = day(G.get("UpdatedAt")) or dt.date.today().isoformat()

    return dict(
        ticker=ticker, name=G.get("Name"), filing_date=filing_date, period_end=day(ys[0]),
        currency=G.get("CurrencyCode"), sector=sector, industry=industry,
        gic_sector=gic_s, gic_industry=gic_i,
        ipo_date=day(G.get("IPODate")), is_financial=is_fin,
        industry_missing=industry_missing,
        primary_ticker=primary, statement_currency=stmt_ccy,
        # §3.0's one-currency test, and nothing else. The depositary-receipt veto that used to ride
        # here was the interim measure migration 011 called "deliberately deferred rather than
        # approximated" — §3.1 gives the vendor's cap the job of resolving ADR ratios, listing
        # currency and share class, and with the statements converted it now does it.
        quote_ok=one_currency,
        converted_to_usd=converted, statement_fx_rate=fx_rate, statement_fx_as_of=fx_as_of,
        market_cap=mcap, shares_out=shares, fiscal_years=n_years,
        ebit_3y=ebit_3y, tax_rate=tax_rate, nopat_3y=nopat_3y,
        invested_capital=ic_avg, invested_capital_ex_gw=ic_avg_ex,
        roic=roic, roic_ex_gw=roic_ex, reinvest_rate=reinvest, engine=engine,
        revenue_cagr_3y=rev_cagr, engine_agrees=agrees,
        fcf_3y=fcf_3y, ni_3y=ni_3y, cash_conversion=cash_conv, fcf_ttm=fcf_ttm,
        fcf_positive=fcf_positive, net_issuance_3y=issuance,
        net_debt=net_debt, ebitda=ebitda, net_debt_ebitda=nd_ebitda,
        debt_grows_faster=debt_faster, goodwill=gw_new, goodwill_jump=gw_jump,
        c1_pass=not fails, c1_fail_reason="; ".join(fails) or None,
        pfcf_current=(mcap / fcf_ttm) if mcap and fcf_ttm and fcf_ttm > 0 else None,
        pfcf_median=None, pfcf_obs=None,
        eps_yoy_latest=y0, eps_yoy_prev=y1, m4_pass=m4,
        data_confidence=confidence,
        cap_as_of=cap_as_of, cap_close=None, effective_shares=None,
        growth_consistency=growth_consistency, roic_worst_year=roic_worst,
        roic_years_reported=roic_years,
        fcf_ttm_reported=fcf_ttm_reported, sbc_ttm=sbc_ttm, dwc_ttm=dwc_ttm,
        sbc_missing=nonlocal_sbc_missing[0],
        # §4.1: the raw filing document lives in the database now, not compressed in the repo — the
        # point-in-time asset §4.8 calls the honest backtest is only honest if it is queryable.
        raw_doc=json.dumps(r, default=str),
        raw=json.dumps({
            "quarterly_fcf": qseries,
            # the restatement, auditable from the row: which currency, into which, at what rate,
            # per period. §3.0 asks for fiscal-period-end FX and this is the receipt for it.
            "fx": ({"from": stmt_ccy, "to": target_ccy, "rate_latest": fx_rate,
                    "as_of": str(fx_as_of) if fx_as_of else None,
                    "is_depositary_receipt": is_adr, "listing_share_ratio": listing_ratio,
                    "periods": fx_log} if converted else
                   {"from": stmt_ccy, "to": target_ccy, "converted": False,
                    "one_currency": one_currency}),
            # Point-in-time history. Every statement EODHD returns carries its own filing_date,
            # so a past date's CCN can be rebuilt from only what had been filed by then. This is
            # the asset §4.8 assumed could not be bought — it was in the document all along.
            # Caveat that cannot be engineered away: the vendor serves the CURRENT version of a
            # past statement, so a restatement is visible earlier than it really was.
            "yearly": [{
                "period": day(k),
                "filing": day((is_y.get(k) or {}).get("filing_date")
                              or (cf_y.get(k) or {}).get("filing_date")
                              or (bs_y.get(k) or {}).get("filing_date")),
                "rev": num((is_y.get(k) or {}).get("totalRevenue")),
                "ebit": num((is_y.get(k) or {}).get("ebit")),
                "ebitda": num((is_y.get(k) or {}).get("ebitda")),
                "ni": num((is_y.get(k) or {}).get("netIncome")),
                "pretax": num((is_y.get(k) or {}).get("incomeBeforeTax")),
                "tax": num((is_y.get(k) or {}).get("incomeTaxExpense")),
                "fcf": fcf_of(cf_y[k]) if k in cf_y else None,
                "capex": num((cf_y.get(k) or {}).get("capitalExpenditures")),
                "dep": num((cf_y.get(k) or {}).get("depreciation")),
                "dwc": num((cf_y.get(k) or {}).get("changeInWorkingCapital")),
                "equity": num((bs_y.get(k) or {}).get("totalStockholderEquity")),
                "cash": num((bs_y.get(k) or {}).get("cashAndShortTermInvestments"))
                        or num((bs_y.get(k) or {}).get("cash")),
                "debt": num((bs_y.get(k) or {}).get("shortLongTermDebtTotal")),
                "netdebt": num((bs_y.get(k) or {}).get("netDebt")),
                "goodwill": num((bs_y.get(k) or {}).get("goodWill")),
                "shares": num((bs_y.get(k) or {}).get("commonStockSharesOutstanding")),
            } for k in ys[:8]],
        }),
    )


COLS = ["ticker", "filing_date", "period_end", "currency", "sector", "industry", "gic_sector",
        "gic_industry", "ipo_date", "is_financial", "industry_missing", "market_cap", "shares_out", "fiscal_years",
        "ebit_3y", "tax_rate", "nopat_3y", "invested_capital", "invested_capital_ex_gw", "roic",
        "roic_ex_gw", "reinvest_rate", "engine", "revenue_cagr_3y", "engine_agrees", "fcf_3y",
        "ni_3y", "cash_conversion", "fcf_ttm", "fcf_positive", "net_issuance_3y", "net_debt",
        "ebitda", "net_debt_ebitda", "debt_grows_faster", "goodwill", "goodwill_jump", "c1_pass",
        "c1_fail_reason", "pfcf_current", "pfcf_median", "pfcf_obs", "eps_yoy_latest",
        "eps_yoy_prev", "m4_pass", "data_confidence", "primary_ticker", "statement_currency",
        "quote_ok", "converted_to_usd", "statement_fx_rate", "statement_fx_as_of",
        "cap_as_of", "cap_close", "effective_shares",
        "growth_consistency", "roic_worst_year", "roic_years_reported",
        "fcf_ttm_reported", "sbc_ttm", "dwc_ttm", "sbc_missing", "raw", "raw_doc"]
JSON_COLS = {"raw", "raw_doc"}


def freeze_effective_shares(conn, tickers):
    """§3.1 — pin the hurdle's share count to the filing, not to tonight's quote.

    effective shares = vendor cap / the close on the cap's `as_of` date. The close is taken from our
    own bars, using the last session at or before that date: a document stamped on a weekend or
    fetched before the day's bar landed must not silently produce no share count.

    Why this exists at all: with the count re-derived from the *latest* close every night, the hurdle
    moved whenever the quote moved. `verify` found eleven mismatches running in both directions —
    names that had risen showed understated hurdles, names that had fallen showed overstated ones —
    which is the signature of a divisor that travels with price. A hurdle is a statement about the
    business; it may only move when a filing moves it.
    """
    if dry():
        return 0
    with conn.cursor() as cur:
        # The close is per-row ("the last bar at or before this filing's cap date"), which wants a
        # correlated lookup — but an UPDATE's own target cannot be referenced from a LATERAL in its
        # FROM clause, so the correlation happens inside a CTE and the UPDATE joins that. Production
        # rejected the lateral form outright; this is the shape Postgres actually allows.
        cur.execute("""with px as (
                         select f.ticker, f.filing_date, f.market_cap,
                                (select p.close from prices p
                                  where p.ticker = f.ticker and p.d <= f.cap_as_of
                                  order by p.d desc limit 1) as close
                           from fundamentals f
                          where f.ticker = any(%s)
                            and f.market_cap is not null and f.market_cap > 0
                            and f.cap_as_of is not null
                            and f.effective_shares is null)
                       update fundamentals f
                          set cap_close = px.close,
                              effective_shares = px.market_cap / px.close
                         from px
                        where px.ticker = f.ticker and px.filing_date = f.filing_date
                          and px.close is not null and px.close > 0""", (list(tickers),))
        n = cur.rowcount
    conn.commit()
    return n


def flush(conn, rows, errors):
    """Batch first; on any failure fall back to row-by-row so one poisoned name
    cannot cost us the other ninety-nine."""
    if not rows or dry():
        return 0
    ph = ",".join("%s::jsonb" if c in JSON_COLS else "%s" for c in COLS)
    setters = ",".join(f"{c}=excluded.{c}" for c in COLS if c not in ("ticker", "filing_date"))
    sql = (f"insert into fundamentals({','.join(COLS)}) values ({ph}) "
           f"on conflict (ticker,filing_date) do update set {setters}, fetched_at=now()")
    upd = ("update universe set name=coalesce(%s, name), sector=%s, industry=%s, "
           "market_cap_usd=coalesce(%s, market_cap_usd) where ticker=%s")
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, [tuple(r[c] for c in COLS) for r in rows])
            cur.executemany(upd, [(r["name"], r["sector"], r["industry"], r["market_cap"], r["ticker"]) for r in rows])
        conn.commit()
        return len(rows)
    except Exception as e:
        conn.rollback()
        print(f"  batch insert failed ({type(e).__name__}: {e}) — retrying row by row")
        errors.setdefault("_batch_fallback", f"{type(e).__name__}: {e}")
        ok = 0
        for r in rows:
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, tuple(r[c] for c in COLS))
                    cur.execute(upd, (r["name"], r["sector"], r["industry"], r["market_cap"], r["ticker"]))
                conn.commit(); ok += 1
            except Exception as e2:
                conn.rollback()
                if len(errors) < 40:
                    errors[r["ticker"]] = f"insert {type(e2).__name__}: {e2}"
        return ok


def fx_coverage(cur, fx, hb):
    """Which statement currencies this sweep must convert out of, and which it cannot yet.

    The pairs are registered and backfilled by `ingest-daily` (§4.2 gives it the FX feed), so a
    filings sweep that runs before the first nightly after a new currency appears will find no
    rates for it. That is a one-run gap and it is named rather than survived quietly: those names
    stay on §3.3's data-confidence path until the bars land, which is the correct outcome and an
    invisible one without this line.
    """
    cur.execute("""select distinct f.statement_currency from v_fundamentals_latest f
                     join universe u on u.ticker = f.ticker
                    where f.statement_currency is not null
                      and upper(f.statement_currency) <> upper(coalesce(u.currency, 'USD'))""")
    need = sorted({str(r[0]).upper() for r in cur.fetchall()})
    missing = [c for c in need if not fx.series.get(c)]
    hb.detail["fx_coverage"] = dict(needed=need, missing=missing,
                                    have=sorted(fx.series))
    if missing:
        hb.amber(f"no FX bars yet for {', '.join(missing)} — those statements stay unconverted and "
                 f"on the data-confidence path (§3.0). `ingest-daily` registers and backfills the "
                 f"pairs; re-run this sweep after the next nightly.")
    return need, missing


def reextract(conn, hb):
    """Re-derive every stored row from the raw filing document already in the database.

    Zero vendor calls. This is the entire payoff of §4.1 moving `raw_doc` into the store: a law
    change to the extraction (SBC net of FCF, new disclosure fields) re-prices 2,700 filings from
    what the vendor already served, instead of burning a 27,000-unit sweep to learn the same facts.
    """
    with conn.cursor() as cur:
        cur.execute("select ticker, currency from universe where kind='stock'")
        quote = {r[0]: r[1] for r in cur.fetchall()}
        fx = FxRates.load(cur)
        fx_coverage(cur, fx, hb)
    done, fail, errors, last = 0, 0, {}, ""
    while True:
        with conn.cursor() as cur:
            cur.execute("""select ticker, raw_doc from v_fundamentals_latest
                           where raw_doc is not null and ticker > %s
                           order by ticker limit 50""", (last,))
            page = cur.fetchall()
        if not page:
            break
        buf = []
        for tk, doc in page:
            last = tk
            try:
                row = extract(tk, doc, quote.get(tk), fx=fx)
            except Exception as e:
                fail += 1
                if len(errors) < 40:
                    errors[tk] = f"reextract {type(e).__name__}: {e}"
                continue
            if row is not None:
                buf.append(row)
        done += flush(conn, buf, errors)
    frozen = freeze_effective_shares(conn, list(quote))
    hb.rows = done
    hb.detail.update(mode="reextract", written=done, failed=fail, errors=errors,
                     effective_shares_frozen=frozen, api_units=0)
    if fail:
        hb.amber(f"{fail} stored documents failed to re-extract")
    print(f"fundamentals: re-extracted {done} rows from stored filings, {fail} failed, 0 API calls")


def main():
    if os.environ.get("REEXTRACT", "false").lower() in ("1", "true", "yes"):
        with connect() as conn:
            with Heartbeat(conn, "ingest-filings") as hb:
                reextract(conn, hb)
        return 0
    only = [t.strip() for t in os.environ.get("TICKERS", "").split(",") if t.strip()]
    stale_only = os.environ.get("STALE_ONLY", "false").lower() in ("1", "true", "yes")
    with connect() as conn:
        with Heartbeat(conn, "ingest-filings") as hb:
            with conn.cursor() as cur:
                missing_cap = int(config(cur, "fundamentals_missing_cap", 300))
                if only:
                    targets = only
                else:
                    cur.execute("""select u.ticker from universe u
                                   where u.kind='stock' and u.status='active'
                                     and (u.in_l0 or u.is_holding) order by u.ticker""")
                    targets = [r[0] for r in cur.fetchall()]
                    if stale_only:
                        # a name whose report date has passed since its last pull gets re-fetched
                        cur.execute("""select f.ticker from v_fundamentals_latest f
                                       where not exists (
                                         select 1 from earnings e where e.ticker=f.ticker
                                           and e.report_date > f.filing_date
                                           and e.report_date <= current_date)""")
                        fresh = {r[0] for r in cur.fetchall()}
                        targets = [t for t in targets if t not in fresh]

                        # ---- WO-8: the standing backlog, metered ------------------------------
                        # 298 universe names hold no fundamentals row at all. They are invisible
                        # to C1 and the CCN and they auto-fail M4 — "not wrong, just dark" — and
                        # the staleness pass leaves them in the target list where the quota cap
                        # then truncates them away alphabetically, every week, forever.
                        #
                        # So they are separated out and taken in a bounded slice, largest first,
                        # skipping the names the vendor has already told us it has nothing for.
                        # Two weekly runs clear the backlog; a permanent gap costs one pull once.
                        cur.execute("""select u.ticker from universe u
                                        where u.kind='stock' and u.status='active'
                                          and (u.in_l0 or u.is_holding) and not u.no_vendor_data
                                          and not exists (select 1 from fundamentals f
                                                           where f.ticker = u.ticker)
                                        order by u.market_cap_usd desc nulls last
                                        limit %s""", (missing_cap,))
                        missing = [r[0] for r in cur.fetchall()]
                        # a row whose filing document was never stored cannot be re-derived, so it
                        # is not point-in-time history and WO-2's currency backfill cannot reach it
                        # from disk — one pull makes it auditable and re-derivable forever after
                        cur.execute("""select ticker from v_fundamentals_latest
                                        where raw_doc is null order by ticker limit %s""",
                                    (missing_cap,))
                        no_doc = [r[0] for r in cur.fetchall()]
                        stale_n = len(targets)
                        seen = set(targets)
                        targets += [t for t in missing + no_doc if not (t in seen or seen.add(t))]
                        hb.detail["sweep_plan"] = dict(stale=stale_n, missing_row=len(missing),
                                                       missing_raw_doc=len(no_doc),
                                                       total=len(targets))
                if SWEEP_LIMIT and len(targets) > SWEEP_LIMIT:
                    # the largest names first — a partial sweep should be a defensible universe,
                    # not an alphabetical accident
                    cur.execute("""select ticker from universe where ticker = any(%s)
                                   order by market_cap_usd desc nulls last limit %s""",
                                (targets, SWEEP_LIMIT))
                    targets = [r[0] for r in cur.fetchall()]
                cur.execute("select ticker, currency from universe where kind='stock'")
                quote = {r[0]: r[1] for r in cur.fetchall()}
                ceiling = float(config(cur, "api_quota_ceiling", 0.70))
                fx = FxRates.load(cur)
                fx_coverage(cur, fx, hb)
            # We have run out of daily quota twice. Ask before spending, and truncate the
            # sweep rather than dying two-thirds through it.
            #
            # §4.1 sets the bar in words — "every run meters its calls via EODHD's usage endpoint;
            # the brief alarms past ~70% of daily quota" — so the sweep stops at that fraction of
            # the budget rather than at a fixed reserve that happened to be 3,000 calls. Whichever
            # of the two bites first wins; the nightly jobs are the reason the reserve exists.
            try:
                usage = get("user", hb.calls)
                used = float(usage.get("apiRequests") or 0)
                limit = float(usage.get("dailyRateLimit") or 100000)
                budget = max(0.0, min(limit * ceiling, limit - RESERVE) - used)
                afford = max(0, int(budget / UNITS_PER_CALL))
                hb.detail["quota"] = dict(used=used, limit=limit, ceiling=ceiling,
                                          affordable_names=afford)
                if len(targets) > afford:
                    # never a silent cap (§4.1): the names dropped are named, so next week's run
                    # and tonight's reader both know exactly what was not swept
                    hb.amber(f"quota allows {afford} of {len(targets)} names today "
                             f"(stop at {ceiling:.0%} of the daily budget, §4.1)")
                    hb.detail["quota_deferred"] = targets[afford:afford + 200]
                    targets = targets[:afford]
            except Exception as e:
                hb.detail["quota_check_failed"] = f"{type(e).__name__}: {e}"
            hb.detail["targets"] = len(targets)
            print(f"fundamentals: sweeping {len(targets)} names, {WORKERS} workers")

            done = fail = 0
            errors = {}
            buf, barren = [], []

            def fetch_one(t):
                try:
                    return t, get(f"fundamentals/{t}", hb.calls, tries=2, timeout=120), None
                except Exception as e:
                    return t, None, f"{type(e).__name__}: {e}"

            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                for t, doc, err in pool.map(fetch_one, targets):
                    if err or not isinstance(doc, dict):
                        fail += 1
                        if len(errors) < 40:
                            errors[t] = err or "unexpected payload"
                        continue
                    try:
                        row = extract(t, doc, quote.get(t), fx=fx)
                    except Exception as e:
                        fail += 1
                        if len(errors) < 40:
                            errors[t] = f"extract {type(e).__name__}: {e}"
                        continue
                    if row is None:
                        fail += 1
                        barren.append(t)
                        if len(errors) < 40:
                            errors[t] = "no fiscal years"
                        continue
                    buf.append(row)
                    if len(buf) >= BATCH:
                        done += flush(conn, buf, errors); buf = []
                        print(f"  {done} written, {fail} failed, {hb.calls[0]} calls")
            done += flush(conn, buf, errors)
            # WO-8: a name the vendor served with no fiscal years is not a gap to retry — it is a
            # fact about the security (SPACs, trusts, preferreds). Marked once, it stops costing ten
            # units a week; a full sweep (STALE_ONLY=false) still re-asks, because listings change.
            if barren and not dry():
                with conn.cursor() as cur:
                    cur.execute("""update universe set no_vendor_data = true,
                                     no_vendor_data_at = coalesce(no_vendor_data_at, current_date)
                                   where ticker = any(%s)""", (barren,))
                conn.commit()
            hb.detail["no_vendor_data_marked"] = sorted(barren)[:100]
            frozen = freeze_effective_shares(conn, targets)
            hb.detail["effective_shares_frozen"] = frozen

            hb.rows = done
            # EODHD bills a fundamentals request at 10 units — calls_used counts requests
            hb.detail.update(written=done, failed=fail, errors=errors,
                             api_units=hb.calls[0] * 10)
            # SPACs, preferreds and trusts have no fiscal years and never will — counting them
            # as a failure leaves the pipeline permanently amber, and a permanently amber
            # pipeline never writes a ticket. Structural misses are recorded, not alarmed.
            transient = sum(1 for e in errors.values() if "no fiscal years" not in str(e))
            if transient:
                hb.amber(f"{transient} names failed to fetch or parse")
            hb.detail["structural_misses"] = fail - transient
            if "_batch_fallback" in errors:
                hb.amber("batch insert fell back to row-by-row — a per-row step may have been skipped")
            print(f"fundamentals: {done} written, {fail} failed, {hb.calls[0]} calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
