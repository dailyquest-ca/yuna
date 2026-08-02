"""backtest_compounders — Phase E for the other sleeve (plan §3.1).

§4.8 says the compounder side cannot be honestly backtested because point-in-time
fundamentals are not for sale at our budget. That turned out to be wrong: every historical
statement EODHD returns carries its own `filing_date`, so what was knowable on any past date
is recoverable from a document we already hold. This walks that forward — Gate C1, CCN and
the hurdle rebuilt each month from only the filings that existed by then.

The bias that remains, stated on every run: the vendor serves the CURRENT version of a past
statement. A company that restated 2023 shows the restated figure against its original
filing date, so the simulation sees a correction earlier than the market did. Much smaller
than using today's filing at a past date, but not zero. Survivorship applies here too — the
L0 census is today's listings — and the bar window caps the test at roughly two years, which
is short evidence for a strategy whose holding period is measured in years.
"""
import os, sys, json, math, statistics as st, datetime as dt
import numpy as np
import pandas as pd
import psycopg
from db import connect, config, dry, Heartbeat
import signals as sg

START_NAV = float(os.environ.get("START_NAV", "200754.38"))
LABEL = os.environ.get("LABEL", "compounders v1")
ENTER = float(os.environ.get("CCN_ENTER", "70"))
EXIT = float(os.environ.get("CCN_EXIT", "55"))
SIZE = float(os.environ.get("POSITION_SIZE", "0.12"))
MAXN = int(os.environ.get("MAX_NAMES", "5"))
CEIL = float(os.environ.get("SLEEVE_CAP", "0.60"))
GROWTH_CAP, FAIR_CAP, FLOOR, TOL = 0.25, 30.0, 0.15, 0.05
WARMUP_DAYS = 260


def pct_rank(d):
    """{key: value} -> {key: percentile 0..100}."""
    items = [(k, v) for k, v in d.items() if v is not None and not math.isnan(v)]
    if not items:
        return {}
    if len(items) == 1:
        return {items[0][0]: 50.0}
    items.sort(key=lambda kv: kv[1])
    n = len(items) - 1
    return {k: 100.0 * i / n for i, (k, _) in enumerate(items)}


def hurdle_price(fcf, shares, growth, fair):
    """One solver in the system: signals.hurdle_price. This wrapper exists only to preserve the
    backtest's historical call shape. The previous body was a private copy with its own constants,
    which meant the backtest silently measured a different formula than production priced — the
    exact failure mode a backtest exists to rule out."""
    return sg.hurdle_price(fcf_ttm=fcf, shares=shares, growth=growth,
                           fair_multiple=fair, floor=FLOOR)

def as_of(ticker_raw, T):
    """Everything §3.1 needs, rebuilt from only the filings that existed on date T."""
    ys = [y for y in (ticker_raw.get("yearly") or [])
          if y.get("filing") and y["filing"] <= T and y.get("rev") is not None]
    ys.sort(key=lambda y: y["period"], reverse=True)
    if len(ys) < 3:
        return None
    y3 = ys[:3]

    ebit = sum(y["ebit"] for y in y3 if y.get("ebit") is not None) if any(y.get("ebit") for y in y3) else None
    tax_n = sum(y["tax"] for y in y3 if y.get("tax") is not None)
    tax_d = sum(y["pretax"] for y in y3 if y.get("pretax") is not None)
    tax = min(0.5, max(0.0, tax_n / tax_d)) if tax_d else 0.21
    nopat = ebit * (1 - tax) if ebit is not None else None

    ics = []
    for y in y3:
        eq, cash, debt, nd = y.get("equity"), y.get("cash"), y.get("debt"), y.get("netdebt")
        if debt is None and nd is not None and cash is not None:
            debt = nd + cash
        if eq is None or cash is None or debt is None:
            continue
        ics.append(debt + eq - cash)
    ic = sum(ics) / len(ics) if ics else None
    roic = (nopat / 3.0) / ic if nopat is not None and ic and ic > 0 else None

    capex = sum(abs(y["capex"]) for y in y3 if y.get("capex") is not None)
    dep = sum(y["dep"] for y in y3 if y.get("dep") is not None)
    dwc = -sum(y["dwc"] for y in y3 if y.get("dwc") is not None)
    reinvest = max(0.0, min(1.5, (capex - dep + dwc) / nopat)) if nopat and nopat > 0 else None
    engine = roic * reinvest if roic is not None and reinvest is not None else None

    span = min(3, len(ys) - 1)
    rev_new, rev_old = ys[0].get("rev"), ys[span].get("rev") if span >= 1 else None
    rev_cagr = ((rev_new / rev_old) ** (1 / span) - 1) if (rev_new and rev_old and rev_old > 0
                                                           and rev_new > 0 and span) else None

    # Durability, point-in-time (§3.1) — the same two facts the live sweep derives, from only the
    # filings that existed on T. `signals` owns both formulas; this file must never restate them.
    growth_cons = sg.growth_consistency([y.get("rev") for y in ys[:6]])
    per_year = []
    for y in ys[:5]:
        eq, cash, debt, nd = y.get("equity"), y.get("cash"), y.get("debt"), y.get("netdebt")
        if debt is None and nd is not None and cash is not None:
            debt = nd + cash
        if y.get("ebit") is None or eq is None or cash is None or debt is None:
            continue
        tx, pre = y.get("tax"), y.get("pretax")
        rate = min(0.5, max(0.0, tx / pre)) if tx is not None and pre else tax
        per_year.append((y["ebit"] * (1 - rate), debt + eq - cash))
    roic_worst, _ = sg.worst_year_roic(per_year)

    fcf3 = sum(y["fcf"] for y in y3 if y.get("fcf") is not None) if any(y.get("fcf") for y in y3) else None
    ni3 = sum(y["ni"] for y in y3 if y.get("ni") is not None) if any(y.get("ni") for y in y3) else None
    cash_conv = (fcf3 / ni3) if fcf3 is not None and ni3 and ni3 > 0 else None

    # Gate C1, on the same filings
    fails = []
    if not (fcf3 and fcf3 > 0):
        fails.append("FCF")
    sh_new = ys[0].get("shares")
    sh_old = ys[span].get("shares") if span >= 1 else None
    if sh_new and sh_old and sh_old > 0 and span:
        if (sh_new / sh_old) ** (1 / span) - 1 > 0.02:
            fails.append("issuance")
    nd, ebitda = ys[0].get("netdebt"), ys[0].get("ebitda")
    if nd is not None and ebitda and ebitda > 0 and nd / ebitda > 2.5:
        fails.append("leverage")

    # quarterly TTM FCF and share count, again as of T
    qs = [q for q in (ticker_raw.get("quarterly_fcf") or [])
          if len(q) >= 4 and q[3] and q[3] <= T]
    qs.sort(key=lambda q: q[0], reverse=True)
    fcf_ttm = qs[0][1] if qs else fcf3 / 3.0 if fcf3 else None
    shares = qs[0][2] if qs else sh_new

    return dict(engine=engine, cash_conv=cash_conv,
                growth_cons=growth_cons, roic_worst=roic_worst, rev_cagr=rev_cagr, roic=roic,
                reinvest=reinvest, c1=not fails, why="; ".join(fails) or None,
                fcf_ttm=fcf_ttm, shares=shares, quarters=qs)


def main():
    with connect() as conn:
        with Heartbeat(conn, "backtest-compounders") as hb:
            with conn.cursor() as cur:
                # §3.1 Gate C1 excludes banks and insurers in v1 — EBITDA is meaningless for
                # them. The point-in-time gate rebuilds C1 from filings, which carry no sector,
                # so the exclusion has to come from the identity row. Without it a reinsurer
                # and an asset manager took two of six slots, including the biggest winner.
                cur.execute("""select f.ticker, f.raw, f.quote_ok, u.sector, u.industry
                               from v_fundamentals_latest f join universe u on u.ticker=f.ticker
                               where u.kind='stock' and u.status='active' and u.in_l0
                                 and f.quote_ok and f.raw is not null
                                 and not coalesce(f.is_financial, false)""")
                names = {}
                for tk, raw, ok, sec, ind in cur.fetchall():
                    r = raw if isinstance(raw, dict) else json.loads(raw)
                    if r.get("yearly"):
                        names[tk] = dict(raw=r, sector=sec, industry=ind)
                if not names:
                    hb.amber("no point-in-time history stored — run the fundamentals sweep first")
                    print("compounders: fundamentals.raw carries no yearly history yet")
                    return 0
                cur.execute("""select ticker, d, close from prices
                               where ticker = any(%s) order by ticker, d""", (list(names),))
                px = pd.DataFrame(cur.fetchall(), columns=["ticker", "d", "close"])
            px["close"] = pd.to_numeric(px["close"])
            wide = px.pivot(index="d", columns="ticker", values="close").sort_index()
            dates = list(wide.index)
            hb.detail["names"] = len(names)
            print(f"compounders: {len(names)} names with point-in-time history, {len(dates)} bars")

            # month-end rebalance dates
            months = pd.Series(range(len(dates)), index=pd.to_datetime(dates))
            rebal = set(months.resample("ME").last().dropna().astype(int).tolist())

            nav, cash, book, trades, equity = START_NAV, START_NAV, {}, [], []
            for t in range(WARMUP_DAYS, len(dates)):
                day = dates[t]
                T = str(day)

                if t in rebal:
                    snap = {}
                    for tk, meta in names.items():
                        a = as_of(meta["raw"], T)
                        if not a or not a["shares"]:
                            continue
                        p = wide[tk].iloc[t]
                        if np.isnan(p):
                            continue
                        a["price"] = float(p)
                        a["mcap"] = float(p) * a["shares"]
                        # the engine waterfall, point-in-time — measured where the cross-check
                        # agrees, observed growth capped at 25% where it does not (§3.1)
                        a["engine_used"], a["provenance"] = sg.engine_waterfall(
                            a["engine"], a["rev_cagr"], tolerance=TOL, cap=GROWTH_CAP)
                        snap[tk] = a
                    if snap:
                        e_p = pct_rank({k: v["engine_used"] for k, v in snap.items()})
                        c_p = pct_rank({k: v["cash_conv"] for k, v in snap.items()})
                        f_p = pct_rank({k: v["roic_worst"] for k, v in snap.items()})
                        d_p = pct_rank({k: sg.durability(v["growth_cons"], f_p.get(k))
                                        for k, v in snap.items()})
                        for tk, a in snap.items():
                            # Size is repealed; Durability replaces it, and neither the engine nor
                            # durability may be renormalized away (§3.1, §3.3).
                            scored = sg.ccn(dict(engine=e_p.get(tk), cash_conv=c_p.get(tk),
                                                 durability=d_p.get(tk)))
                            a["ccn"] = scored["score"]
                            if a["ccn"] is None:
                                continue
                            g = a["engine_used"] if a["engine_used"] is not None else 0.0
                            obs = []
                            for q in a["quarters"][:20]:
                                qd = str(q[0])[:7]
                                col = wide[tk]
                                near = col[[d for d in col.index if str(d)[:7] == qd]]
                                if len(near) and q[1] and q[1] > 0 and q[2]:
                                    obs.append(float(near.iloc[-1]) * q[2] / q[1])
                            fair = (min(st.median(obs), FAIR_CAP) if len(obs) >= 8 else
                                    (min(a["mcap"] / a["fcf_ttm"], 25.0)
                                     if a["fcf_ttm"] and a["fcf_ttm"] > 0 else None))
                            a["hurdle"] = hurdle_price(a["fcf_ttm"], a["shares"], g, fair)

                        # exits: §3.1 has no stops and no market gate — only the score decaying
                        for tk in list(book):
                            a = snap.get(tk)
                            if a and a["ccn"] is not None and a["ccn"] < EXIT:
                                p = float(wide[tk].iloc[t])
                                cash += book[tk]["qty"] * p
                                b = book.pop(tk)
                                trades.append(dict(ticker=tk, entry_date=b["entry_date"],
                                                   entry_price=b["entry"], qty=b["qty"], exit_date=day,
                                                   exit_price=p, mcn=b["ccn"], pivot=None,
                                                   initial_stop=None, size_pct=SIZE, pyramid_steps=0,
                                                   pnl_cad=(p - b["entry"]) * b["qty"],
                                                   pnl_pct=p / b["entry"] - 1,
                                                   bars_held=t - b["entry_idx"],
                                                   max_favorable=b["mfe"], max_adverse=b["mae"],
                                                   exit_reason=f"CCN < {EXIT:.0f}"))

                        # entries: at or below hurdle, best CCN first, §2.2 caps applied
                        groups, themes = {}, {}
                        for tk in book:
                            g_, th = names[tk]["industry"] or "?", names[tk]["sector"] or "?"
                            groups[g_] = groups.get(g_, 0) + 1
                            themes[th] = themes.get(th, 0.0) + SIZE
                        cands = sorted([(tk, a) for tk, a in snap.items()
                                        if tk not in book and a["c1"] and a["ccn"] is not None
                                        and a["ccn"] >= ENTER and a["hurdle"]
                                        and a["price"] <= a["hurdle"]],
                                       key=lambda kv: -kv[1]["ccn"])
                        for tk, a in cands:
                            if len(book) >= MAXN or len(book) * SIZE + SIZE > CEIL:
                                break
                            g_, th = names[tk]["industry"] or "?", names[tk]["sector"] or "?"
                            if groups.get(g_, 0) >= 2 or themes.get(th, 0.0) + SIZE > 0.35:
                                continue
                            spend = SIZE * nav
                            if cash < spend:
                                continue
                            q = spend / a["price"]
                            cash -= spend
                            groups[g_] = groups.get(g_, 0) + 1
                            themes[th] = themes.get(th, 0.0) + SIZE
                            book[tk] = dict(entry=a["price"], qty=q, ccn=a["ccn"], entry_date=day,
                                            entry_idx=t, mfe=0.0, mae=0.0, last=a["price"])

                held = 0.0
                for tk, b in book.items():
                    p = wide[tk].iloc[t]
                    p = b["last"] if np.isnan(p) else p
                    b["last"] = float(p)
                    b["mfe"] = max(b["mfe"], p / b["entry"] - 1)
                    b["mae"] = min(b["mae"], p / b["entry"] - 1)
                    held += b["qty"] * float(p)
                nav = cash + held
                equity.append((day, nav, held / nav if nav else 0, len(book), "N/A", None))

            t = len(dates) - 1
            for tk in list(book):
                p = float(wide[tk].iloc[t]) if not np.isnan(wide[tk].iloc[t]) else book[tk]["last"]
                cash += book[tk]["qty"] * p
                b = book.pop(tk)
                trades.append(dict(ticker=tk, entry_date=b["entry_date"], entry_price=b["entry"],
                                   qty=b["qty"], exit_date=dates[t], exit_price=p, mcn=b["ccn"],
                                   pivot=None, initial_stop=None, size_pct=SIZE, pyramid_steps=0,
                                   pnl_cad=(p - b["entry"]) * b["qty"], pnl_pct=p / b["entry"] - 1,
                                   bars_held=t - b["entry_idx"], max_favorable=b["mfe"],
                                   max_adverse=b["mae"], exit_reason="end of test"))

            import backtest as bt
            with conn.cursor() as cur:
                cur.execute("select d, close from prices where ticker='GSPC.INDX' order by d")
                spx = pd.Series({d: float(c) for d, c in cur.fetchall()}).sort_index()
            summary = bt.summarise(trades, equity, spx)
            summary["stats"]["biases"] = [
                "survivorship — L0 is today's listings only",
                "restatements — the vendor serves the current version of a past statement",
                f"~{len(equity)} trading days; a multi-year strategy tested over two",
                "CCN < 55 is modelled as a sell; §3.1 makes it a review memo Zak rules on"]
            print(f"  {summary['trades']} trades | CAGR {summary['cagr']:.1%} | "
                  f"maxDD {summary['max_drawdown']:.1%} | exposure {summary['avg_exposure']:.1%}")
            if not dry():
                with conn.cursor() as cur:
                    cur.execute("""insert into backtest_runs(label,sleeve,params,start_date,end_date,
                          trading_days,start_nav,end_nav,total_return,cagr,max_drawdown,max_dd_date,
                          trades,wins,win_rate,avg_win,avg_loss,expectancy,avg_exposure,avg_hold_days,
                          benchmark_return,benchmark_cagr,stats)
                        values (%s,'compounders',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        returning id""",
                        (LABEL, json.dumps(dict(enter=ENTER, exit=EXIT, size=SIZE, max_names=MAXN,
                                                sleeve_cap=CEIL, start_nav=START_NAV)),
                         summary["start_date"], summary["end_date"], summary["trading_days"],
                         summary["start_nav"], summary["end_nav"], summary["total_return"],
                         summary["cagr"], summary["max_drawdown"], summary["max_dd_date"],
                         summary["trades"], summary["wins"], summary["win_rate"], summary["avg_win"],
                         summary["avg_loss"], summary["expectancy"], summary["avg_exposure"],
                         summary["avg_hold_days"], summary["benchmark_return"],
                         summary["benchmark_cagr"], json.dumps(summary["stats"], default=str)))
                    rid = cur.fetchone()[0]
                    cur.executemany("""insert into backtest_trades(run_id,ticker,entry_date,entry_price,
                          qty,exit_date,exit_price,mcn,pivot,initial_stop,size_pct,pyramid_steps,
                          pnl_cad,pnl_pct,bars_held,max_favorable,max_adverse,exit_reason)
                        values (%(run_id)s,%(ticker)s,%(entry_date)s,%(entry_price)s,%(qty)s,
                          %(exit_date)s,%(exit_price)s,%(mcn)s,%(pivot)s,%(initial_stop)s,%(size_pct)s,
                          %(pyramid_steps)s,%(pnl_cad)s,%(pnl_pct)s,%(bars_held)s,%(max_favorable)s,
                          %(max_adverse)s,%(exit_reason)s)""",
                        [{**tr, "run_id": rid} for tr in trades])
                    cur.executemany("""insert into backtest_equity(run_id,d,nav,exposure,positions,gate,benchmark)
                                       values (%s,%s,%s,%s,%s,%s,%s)""",
                        [(rid, d, n, e, p, None, None) for d, n, e, p, _, _ in equity])
                conn.commit()
                hb.detail["run_id"] = rid
            hb.rows = len(trades) + len(equity)
            hb.detail.update({k: v for k, v in summary.items() if k != "stats"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
