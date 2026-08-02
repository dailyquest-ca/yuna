"""verify — re-derive the machine's own published numbers from its own stored inputs.

Dispatch-only tooling (§4.2), and the most useful job in the repo for the same reason the heartbeat
is: it answers "is this number real" rather than "did the job run". Green is not a result — every
serious defect in this build shipped green — and the habit that actually worked was cross-checking
the model's output against an independent computation on the raw data.

What it checks, per §3.1 and §3.0:

  1. every stored hurdle reproduces the 15% floor from its own stored components
  2. gap_to_hurdle agrees with the last_close and hurdle_price beside it
  3. the CCN equals the mean of the component percentiles actually stored on the row
  4. what carries each top score — reported, so a bench topped by names with no measurable
     compounding engine cannot pass unnoticed

Every failure becomes an observation, so the finding survives the session that found it.
"""
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from db import connect, config, dry, jsonb, observe, Heartbeat
import signals as sg

ER_TOLERANCE = 0.005          # half a point of expected return
GAP_TOLERANCE = 1e-4
CCN_TOLERANCE = 0.05


def check_hurdles(cur, floor):
    """§3.1: the hurdle is the highest price where expected return still clears the floor. Evaluated
    at that price, from the row's own numbers, it must come back to the floor.

    The market cap cancels out of the arithmetic — only FCF per share, growth and the fair multiple
    matter — which is what makes this independent of whichever cap the vendor served."""
    cur.execute("""select ticker, hurdle_price, last_close, fcf_yield, engine_growth, fair_multiple
                   from bench
                   where hurdle_price is not null and last_close is not null
                     and fcf_yield is not null and fair_multiple is not null""")
    bad = []
    for ticker, hurdle, px, yield_, growth, fair in cur.fetchall():
        hurdle, px, yield_ = float(hurdle), float(px), float(yield_)
        growth, fair = float(growth or 0), float(fair)
        if px <= 0 or yield_ <= 0 or fair <= 0:
            continue
        er = sg.expected_return(hurdle, fcf_ttm=yield_ * px, shares=1.0, growth=growth,
                                fair_multiple=fair)
        if er is None or abs(er - floor) > ER_TOLERANCE:
            implied = sg.hurdle_price(fcf_ttm=yield_ * px, shares=1.0, growth=growth,
                                      fair_multiple=fair, floor=floor)
            bad.append(dict(ticker=ticker, stored_hurdle=round(hurdle, 2),
                            er_at_stored=round(er, 4) if er is not None else None,
                            hurdle_that_clears_the_floor=round(implied, 2) if implied else None,
                            overstated_by=(round(hurdle / implied - 1, 4) if implied else None)))
    return bad


def check_gaps(cur):
    cur.execute("""select ticker, gap_to_hurdle, last_close, hurdle_price from bench
                   where gap_to_hurdle is not null and hurdle_price is not null
                     and last_close is not null and hurdle_price <> 0""")
    return [dict(ticker=t, stored=round(float(g), 5),
                 computed=round((float(px) - float(h)) / float(h), 5))
            for t, g, px, h in cur.fetchall()
            if abs(float(g) - (float(px) - float(h)) / float(h)) > GAP_TOLERANCE]


def check_ccn(cur):
    """The CCN must be the mean of the percentiles the row actually stores (§3.1, §3.3)."""
    cur.execute("""select ticker, ccn, engine, cash_conv, durability, data_confidence
                   from bench where ccn is not null""")
    bad = []
    for ticker, ccn, eng, cc, dur, conf in cur.fetchall():
        parts = [float(x) for x in (eng, cc, dur) if x is not None]
        if not parts:
            continue
        expect = sum(parts) / len(parts)
        if abs(float(ccn) - expect) > CCN_TOLERANCE:
            bad.append(dict(ticker=ticker, stored_ccn=round(float(ccn), 2),
                            mean_of_stored_components=round(expect, 2),
                            components_present=len(parts), confidence=conf))
    return bad


def what_carries_the_scores(cur, top=15):
    """§3.1 calls the engine "the compounding engine" and weights it a third. If the top of the bench
    is carried by cash conversion and smallness, with no measurable engine at all, the score has
    stopped measuring what it is named after — and that is a plan question, not a bug."""
    cur.execute("""select ticker, round(ccn::numeric,1), engine, cash_conv, durability,
                          data_confidence, round((100*engine_used)::numeric,1), engine_provenance
                   from bench order by ccn desc limit %s""", (top,))
    rows = []
    engineless = 0
    for ticker, ccn, eng, cc, dur, conf, used, how in cur.fetchall():
        has_engine = eng is not None
        engineless += 0 if has_engine else 1
        rows.append(dict(ticker=ticker, ccn=float(ccn), engine_pct=float(eng) if eng else None,
                         cash_conv_pct=float(cc) if cc else None,
                         durability_pct=float(dur) if dur else None,
                         engine_used_pct=float(used) if used is not None else None,
                         provenance=how, confidence=conf))
    return rows, engineless


def check_provenance(cur):
    """§3.1: every bench name has an engine by one method or the other, and says which.

    A null provenance on a scored row means something reached the bench without going through the
    waterfall — which is precisely the state the waterfall exists to make impossible.
    """
    cur.execute("""select ticker, ccn, engine, engine_provenance, durability, data_confidence
                     from bench where ccn is not null""")
    bad = []
    for ticker, ccn, eng, how, dur, conf in cur.fetchall():
        if how not in ("measured", "growth-derived") or eng is None or dur is None:
            bad.append(dict(ticker=ticker, ccn=round(float(ccn), 1), engine_pct=eng,
                            provenance=how, durability=dur,
                            why="scored without an engine, a durability or a provenance"))
        elif how == "growth-derived" and conf != "flagged":
            # §3.1 attaches §3.3's guardrails to growth-derived names — bottom of the band and
            # manual sign-off. Those only bite if the row is marked.
            bad.append(dict(ticker=ticker, ccn=round(float(ccn), 1), provenance=how,
                            confidence=conf, why="growth-derived but not flagged for guardrails"))
    return bad


def check_hurdle_is_price_invariant(cur):
    """§3.1: the hurdle moves when a filing moves it, never because the quote moved.

    The share count must come from the FILING — cap over the close on the cap's `as_of` date. If a
    bench row's hurdle implies a share count that matches today's close instead, the divisor is
    travelling with price again, which is what produced eleven two-way mismatches.
    """
    cur.execute("""select b.ticker, f.effective_shares, f.market_cap, f.cap_close, b.last_close
                     from bench b join v_fundamentals_latest f on f.ticker = b.ticker
                    where b.hurdle_price is not null and f.effective_shares is not null
                      and f.market_cap is not null and b.last_close is not null
                      and f.cap_close is not null""")
    bad = []
    for ticker, eff, cap, cap_close, last in cur.fetchall():
        frozen = float(cap) / float(cap_close)
        drifting = float(cap) / float(last)
        # only interesting when the two answers differ — an unmoved quote makes them identical
        if abs(frozen - drifting) / max(frozen, 1e-9) > 0.005 \
           and abs(float(eff) - drifting) < abs(float(eff) - frozen):
            bad.append(dict(ticker=ticker, stored_shares=float(eff),
                            frozen_at_filing=frozen, implied_by_todays_close=drifting,
                            why="share count tracks the quote, not the filing"))
    return bad


def calibration_gauges(cur, knife_max, buyable_max):
    """§5.5, 2026-08-02 — the falling-knife gauge and the buyable-share gauge, as standing alarms.

    Gauge 1: Spearman rank correlation between how far a name has fallen from its stored high and
    how rich a multiple of FCF the hurdle permits. Near zero is healthy; positive means the screen
    grants its most generous licences to its biggest losers — the exact pathology of 2026-08-01,
    stated as one number. Gauge 2: the share of the ranked bench called buyable; a value screen
    calling most of its own bench cheap is describing itself, not the market.
    """
    cur.execute("""select b.ticker,
                          b.hurdle_price * f.effective_shares / f.fcf_ttm,
                          1.0 - b.last_close / mx.mx
                     from bench b
                     join v_fundamentals_latest f on f.ticker = b.ticker
                     join lateral (select max(close) mx from prices p where p.ticker = b.ticker) mx on true
                    where b.rank is not null and b.hurdle_price is not null
                      and b.last_close is not null and mx.mx > 0
                      and f.fcf_ttm is not null and f.fcf_ttm > 0
                      and f.effective_shares is not null""")
    rows = cur.fetchall()
    rho = None
    if len(rows) >= 10:
        import numpy as np
        mult = np.array([float(r[1]) for r in rows])
        draw = np.array([float(r[2]) for r in rows])
        rank = lambda a: a.argsort().argsort().astype(float)
        rm, rd = rank(mult), rank(draw)
        denom = float(np.std(rm) * np.std(rd))
        rho = float(np.mean((rm - rm.mean()) * (rd - rd.mean())) / denom) if denom else None

    cur.execute("""select count(*) filter (where gap_to_hurdle <= 0), count(*)
                     from bench where rank is not null and gap_to_hurdle is not null""")
    buyable, ranked = cur.fetchone()
    share = (buyable / ranked) if ranked else None
    return dict(knife_corr=round(rho, 3) if rho is not None else None, knife_n=len(rows),
                knife_fail=(rho is not None and rho > knife_max),
                buyable_share=round(share, 3) if share is not None else None,
                buyable_n=ranked, buyable_fail=(share is not None and share > buyable_max))


def main():
    with connect() as conn:
        with Heartbeat(conn, "verify") as hb:
            with conn.cursor() as cur:
                floor = float(config(cur, "hurdle_min_return", 0.15))
                hurdles = check_hurdles(cur, floor)
                gaps = check_gaps(cur)
                ccns = check_ccn(cur)
                prov = check_provenance(cur)
                drift = check_hurdle_is_price_invariant(cur)
                top, engineless = what_carries_the_scores(cur)
                knife_max = float(config(cur, "verify_knife_corr_max", 0.30))
                buyable_max = float(config(cur, "verify_buyable_share_max", 0.60))
                gauges = calibration_gauges(cur, knife_max, buyable_max)

                # §4.7: a job that half-fails goes amber — but "amber" with a count is a status, not
                # a cause. Production went amber with the reasons discoverable only by reading rows.
                # Every check now names itself, passing or failing, so the run log answers "what is
                # wrong" without an investigation.
                checks = [
                    dict(check="hurdle_reproduces_floor", failures=len(hurdles),
                         detail=f"stored hurdle does not re-derive the {floor:.0%} floor from its "
                                f"own components (§3.1)",
                         names=[b["ticker"] for b in hurdles][:20]),
                    dict(check="gap_matches_close_and_hurdle", failures=len(gaps),
                         detail="gap_to_hurdle disagrees with the last_close and hurdle beside it",
                         names=[b["ticker"] for b in gaps][:20]),
                    dict(check="ccn_is_mean_of_components", failures=len(ccns),
                         detail="stored CCN is not the mean of the percentiles on its own row "
                                "(§3.1, §3.3)",
                         names=[b["ticker"] for b in ccns][:20]),
                    dict(check="top_bench_has_measurable_engines", failures=engineless,
                         detail="top-of-bench names carrying no measurable compounding engine — "
                                "§3.1 makes those not bench-eligible",
                         names=[r["ticker"] for r in top if r["engine_pct"] is None][:20]),
                    dict(check="every_score_declares_its_engine", failures=len(prov),
                         detail="a bench row scored without an engine, a durability or a stated "
                                "provenance — or growth-derived without §3.3's guardrail flag",
                         names=[b["ticker"] for b in prov][:20]),
                    dict(check="falling_knife_gauge",
                         failures=1 if gauges["knife_fail"] else 0,
                         detail=f"drawdown-vs-permitted-multiple rank correlation "
                                f"{gauges['knife_corr']} over {gauges['knife_n']} names "
                                f"(alarm above {knife_max}) — positive means the screen pays up "
                                f"for falling knives (§5.5)", names=[]),
                    dict(check="buyable_share_gauge",
                         failures=1 if gauges["buyable_fail"] else 0,
                         detail=f"{gauges['buyable_share']} of the ranked bench called buyable "
                                f"(alarm above {buyable_max}) — a screen calling most of its own "
                                f"bench cheap is describing itself (§5.5)", names=[]),
                    dict(check="hurdle_is_price_invariant", failures=len(drift),
                         detail="the hurdle's share count tracks today's quote rather than the "
                                "close on the cap's as_of date (§3.1)",
                         names=[b["ticker"] for b in drift][:20]),
                ]
                failed = [c for c in checks if c["failures"]]
                findings = dict(hurdle_mismatches=hurdles, gap_mismatches=gaps,
                                ccn_mismatches=ccns, provenance_gaps=prov, share_drift=drift,
                                top_of_bench=top,
                                engineless_in_top=engineless, gauges=gauges,
                                checks=checks, causes=[c["check"] for c in failed])
                hb.detail.update(findings)

                if not dry():
                    for b in hurdles:
                        observe(cur, "breach",
                                f"{b['ticker']}: stored hurdle {b['stored_hurdle']} implies an "
                                f"expected return of {b['er_at_stored']:.1%} against the "
                                f"{floor:.0%} floor — the price that actually clears it is "
                                f"{b['hurdle_that_clears_the_floor']}. A hurdle that cannot be "
                                f"rebuilt from its own row must not be traded on.",
                                ticker=b["ticker"], detail=b, once=True)
                    for b in gaps + ccns + prov + drift:
                        observe(cur, "breach",
                                f"{b['ticker']}: a stored figure disagrees with the row it sits on "
                                f"— {jsonb(b)}", ticker=b["ticker"], detail=b, once=True)
                conn.commit()

            for c in failed:
                hb.amber(f"{c['check']}: {c['failures']} — {c['detail']}"
                         + (f" · {', '.join(c['names'])}" if c["names"] else ""))
            print(f"verify: {len(failed)} check(s) failing — "
                  f"{', '.join(c['check'] for c in failed) or 'none'}")
            print(f"verify: {len(hurdles)} hurdle mismatches · {len(gaps)} gap · {len(ccns)} CCN · "
                  f"{engineless} of {len(top)} top-bench names have no measurable engine")
            for b in hurdles:
                print(f"  HURDLE {b['ticker']}: stored {b['stored_hurdle']} → ER "
                      f"{b['er_at_stored']:.1%}; clears at {b['hurdle_that_clears_the_floor']}")
            for row in top:
                print(f"  TOP {row['ticker']:<9} CCN {row['ccn']:>5} · engine "
                      f"{row['engine_pct'] if row['engine_pct'] is not None else 'DROPPED':>7} "
                      f"({row['provenance']}) · cash {row['cash_conv_pct']} · "
                      f"durability {row['durability_pct']} · {row['confidence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
