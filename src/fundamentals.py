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
from db import connect, config, get, dry, Heartbeat

WORKERS = int(os.environ.get("WORKERS", "8"))
BATCH = 100
UNITS_PER_CALL = 10                       # EODHD bills a fundamentals request at ten
RESERVE = int(os.environ.get("QUOTA_RESERVE", "3000"))   # leave room for the nightly jobs
SWEEP_LIMIT = int(os.environ.get("SWEEP_LIMIT", "0"))    # 0 = everything; else top N by market cap
TOLERANCE = 0.05          # |engine - revenue CAGR| floor before the engine is distrusted
FIN_SECTORS = {"financial services", "financials", "financial"}
FIN_WORDS = ("bank", "insur", "capital markets", "credit services", "reinsur",
             "savings", "thrift", "mortgage finance")


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
def extract(ticker, r, quote_ccy=None):
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
    hay = " ".join(filter(None, [sector, industry, gic_s, gic_i])).lower()
    is_fin = (sector or "").lower() in FIN_SECTORS or (gic_s or "").lower() in FIN_SECTORS \
             or any(w in hay for w in FIN_WORDS)
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
    def fcf_of(row):
        v = num(row.get("freeCashFlow"))
        if v is not None:
            return v
        cfo = num(row.get("totalCashFromOperatingActivities"))
        cx = num(row.get("capitalExpenditures"))
        return (cfo - abs(cx)) if cfo is not None and cx is not None else None

    fcf_3y = s([fcf_of(cf_y[k]) for k in y3 if k in cf_y])
    ni_3y = s([num(is_y[k].get("netIncome")) for k in y3])
    cash_conv = (fcf_3y / ni_3y) if fcf_3y is not None and ni_3y and ni_3y > 0 else None

    qs = desc(cf_q)
    fcf_ttm = s([fcf_of(cf_q[k]) for k in qs[:4]]) if len(qs) >= 4 else \
              (fcf_of(cf_y[ys[0]]) if ys[0] in cf_y else None)

    # a quarterly TTM-FCF / shares series, so the funnel can build P/FCF history from our bars
    qseries = []
    for i in range(len(qs) - 3):
        window = qs[i:i + 4]
        v = s([fcf_of(cf_q[k]) for k in window])
        sh = num((bs_q.get(qs[i]) or {}).get("commonStockSharesOutstanding")) or shares
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
        if debt_faster:
            fails.append("net debt growing faster than EBITDA")

    if is_fin:
        fails.append("bank/insurer — excluded in v1")
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
    confidence = "flagged" if flagged or have < 2 else ("full" if have == 3 else "2of3")

    return dict(
        ticker=ticker, name=G.get("Name"), filing_date=filing_date, period_end=day(ys[0]),
        currency=G.get("CurrencyCode"), sector=sector, industry=industry,
        gic_sector=gic_s, gic_industry=gic_i,
        ipo_date=day(G.get("IPODate")), is_financial=is_fin,
        primary_ticker=primary, statement_currency=stmt_ccy, is_adr=is_adr,
        quote_ok=(not is_adr and stmt_ccy is not None and stmt_ccy == quote_ccy),
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
        raw=json.dumps({
            "quarterly_fcf": qseries,
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
        "gic_industry", "ipo_date", "is_financial", "market_cap", "shares_out", "fiscal_years",
        "ebit_3y", "tax_rate", "nopat_3y", "invested_capital", "invested_capital_ex_gw", "roic",
        "roic_ex_gw", "reinvest_rate", "engine", "revenue_cagr_3y", "engine_agrees", "fcf_3y",
        "ni_3y", "cash_conversion", "fcf_ttm", "fcf_positive", "net_issuance_3y", "net_debt",
        "ebitda", "net_debt_ebitda", "debt_grows_faster", "goodwill", "goodwill_jump", "c1_pass",
        "c1_fail_reason", "pfcf_current", "pfcf_median", "pfcf_obs", "eps_yoy_latest",
        "eps_yoy_prev", "m4_pass", "data_confidence", "primary_ticker", "statement_currency",
        "quote_ok", "raw"]


def flush(conn, rows, errors):
    """Batch first; on any failure fall back to row-by-row so one poisoned name
    cannot cost us the other ninety-nine."""
    if not rows or dry():
        return 0
    ph = ",".join("%s::jsonb" if c == "raw" else "%s" for c in COLS)
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


def main():
    only = [t.strip() for t in os.environ.get("TICKERS", "").split(",") if t.strip()]
    stale_only = os.environ.get("STALE_ONLY", "false").lower() in ("1", "true", "yes")
    with connect() as conn:
        with Heartbeat(conn, "fundamentals") as hb:
            with conn.cursor() as cur:
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
                if SWEEP_LIMIT and len(targets) > SWEEP_LIMIT:
                    # the largest names first — a partial sweep should be a defensible universe,
                    # not an alphabetical accident
                    cur.execute("""select ticker from universe where ticker = any(%s)
                                   order by market_cap_usd desc nulls last limit %s""",
                                (targets, SWEEP_LIMIT))
                    targets = [r[0] for r in cur.fetchall()]
                cur.execute("select ticker, currency from universe where kind='stock'")
                quote = {r[0]: r[1] for r in cur.fetchall()}
            # We have run out of daily quota twice. Ask before spending, and truncate the
            # sweep rather than dying two-thirds through it.
            try:
                used = get("user", hb.calls).get("apiRequests", 0)
                limit = get("user", hb.calls).get("dailyRateLimit", 100000)
                afford = max(0, int((limit - RESERVE - used) / UNITS_PER_CALL))
                hb.detail["quota"] = dict(used=used, limit=limit, affordable_names=afford)
                if len(targets) > afford:
                    hb.amber(f"quota allows {afford} of {len(targets)} names today")
                    targets = targets[:afford]
            except Exception as e:
                hb.detail["quota_check_failed"] = f"{type(e).__name__}: {e}"
            hb.detail["targets"] = len(targets)
            print(f"fundamentals: sweeping {len(targets)} names, {WORKERS} workers")

            done = fail = 0
            errors = {}
            buf = []

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
                        row = extract(t, doc, quote.get(t))
                    except Exception as e:
                        fail += 1
                        if len(errors) < 40:
                            errors[t] = f"extract {type(e).__name__}: {e}"
                        continue
                    if row is None:
                        fail += 1
                        if len(errors) < 40:
                            errors[t] = "no fiscal years"
                        continue
                    buf.append(row)
                    if len(buf) >= BATCH:
                        done += flush(conn, buf, errors); buf = []
                        print(f"  {done} written, {fail} failed, {hb.calls[0]} calls")
            done += flush(conn, buf, errors)

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
