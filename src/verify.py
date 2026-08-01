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
    cur.execute("""select ticker, ccn, engine, cash_conv, size_score, data_confidence
                   from bench where ccn is not null""")
    bad = []
    for ticker, ccn, eng, cc, size, conf in cur.fetchall():
        parts = [float(x) for x in (eng, cc, size) if x is not None]
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
    cur.execute("""select ticker, round(ccn::numeric,1), engine, cash_conv, size_score,
                          data_confidence, round((100*engine_raw)::numeric,1)
                   from bench order by ccn desc limit %s""", (top,))
    rows = []
    engineless = 0
    for ticker, ccn, eng, cc, size, conf, raw in cur.fetchall():
        has_engine = eng is not None
        engineless += 0 if has_engine else 1
        rows.append(dict(ticker=ticker, ccn=float(ccn), engine_pct=float(eng) if eng else None,
                         cash_conv_pct=float(cc) if cc else None,
                         size_pct=float(size) if size else None,
                         engine_raw_pct=float(raw) if raw is not None else None, confidence=conf))
    return rows, engineless


def main():
    with connect() as conn:
        with Heartbeat(conn, "verify") as hb:
            with conn.cursor() as cur:
                floor = float(config(cur, "hurdle_min_return", 0.15))
                hurdles = check_hurdles(cur, floor)
                gaps = check_gaps(cur)
                ccns = check_ccn(cur)
                top, engineless = what_carries_the_scores(cur)

                findings = dict(hurdle_mismatches=hurdles, gap_mismatches=gaps,
                                ccn_mismatches=ccns, top_of_bench=top,
                                engineless_in_top=engineless)
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
                    for b in gaps + ccns:
                        observe(cur, "breach",
                                f"{b['ticker']}: a stored figure disagrees with the row it sits on "
                                f"— {jsonb(b)}", ticker=b["ticker"], detail=b, once=True)
                conn.commit()

            if hurdles or gaps or ccns:
                hb.amber(f"{len(hurdles)} hurdle, {len(gaps)} gap and {len(ccns)} CCN mismatch(es)")
            print(f"verify: {len(hurdles)} hurdle mismatches · {len(gaps)} gap · {len(ccns)} CCN · "
                  f"{engineless} of {len(top)} top-bench names have no measurable engine")
            for b in hurdles:
                print(f"  HURDLE {b['ticker']}: stored {b['stored_hurdle']} → ER "
                      f"{b['er_at_stored']:.1%}; clears at {b['hurdle_that_clears_the_floor']}")
            for row in top:
                print(f"  TOP {row['ticker']:<9} CCN {row['ccn']:>5} · engine "
                      f"{row['engine_pct'] if row['engine_pct'] is not None else 'DROPPED':>7} · "
                      f"cash {row['cash_conv_pct']} · size {row['size_pct']} · {row['confidence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
