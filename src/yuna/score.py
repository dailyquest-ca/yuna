"""score — the compounder funnel's Stage 2 (plan §3.1): Gate C1 → CCN → hurdle → bench.

Reads `fundamentals` and `prices`; calls no API. Percentiles are cross-sectional within L0
at run time, exactly as §3.0 says, so scores move when the field moves.

Deviation, announced: the hurdle's "fair multiple" wants the stock's own 5-year median
P/FCF. We hold a 3-year bar window, so the median is taken over the quarters we can price
and `pfcf_obs` records how many that was. Under 8 observations the name falls back to the
plan's short-history rule (fair = lower of current or 25x).
"""
import json
import statistics as st
import sys

from yuna.db import Heartbeat, config, connect, dry
from yuna.policy import (
    ccn as ccn_score,
    engine_growth,
    hurdle_price,
    inverted_log_size,
    pct_rank,
    size_cohort,
    within_hurdle,
)
from yuna.rules import implements

SIZE_BOUNDARY_DEFAULT = 10_000_000_000


def month_closes(cur, tickers):
    """{ticker: {YYYY-MM: last close of that month}} over our bar window."""
    cur.execute("""select distinct on (ticker, date_trunc('month', d))
                          ticker, to_char(d,'YYYY-MM') as m, close
                   from prices where ticker = any(%s)
                   order by ticker, date_trunc('month', d), d desc""", (tickers,))
    out = {}
    for t, m, c in cur.fetchall():
        out.setdefault(t, {})[m] = float(c)
    return out


def pfcf_history(raw, closes):
    """Median P/FCF over the quarters we can price, and the observation count."""
    obs = []
    for q in (raw or {}).get("quarterly_fcf", []):
        try:
            qdate, ttm_fcf, shares = q[0], float(q[1]), float(q[2])
        except (TypeError, ValueError, IndexError):
            continue
        if ttm_fcf <= 0 or shares <= 0:
            continue
        px = closes.get(str(qdate)[:7])
        if px:
            obs.append(px * shares / ttm_fcf)
    return (st.median(obs) if obs else None), len(obs)


@implements("3.1/bench-eviction",
            "gate failure evicts immediately; rank eviction needs two months outside the top "
            "60 and spares holdings and names within 10% of their hurdle")
@implements("3.1/statement-currency",
            "refuses to underwrite a name whose statements are filed in a currency other than "
            "the one it quotes in — no fair multiple, no hurdle, and C1 fails with the reason "
            "(the sweep detects the mismatch; this is where it bites)")
def main():
    with connect() as conn:
        with Heartbeat(conn, "score") as hb:
            with conn.cursor() as cur:
                boundary = float(config(cur, "small_large_boundary_usd", SIZE_BOUNDARY_DEFAULT))
                take = int(config(cur, "bench_cohort_take", 30))
                growth_cap = float(config(cur, "hurdle_growth_cap", 0.25))
                fair_cap = float(config(cur, "hurdle_fair_multiple_cap", 30))
                fair_cap_short = float(config(cur, "hurdle_fair_multiple_cap_short", 25))
                floor = float(config(cur, "hurdle_min_return", 0.15))
                tol = float(config(cur, "engine_agreement_tolerance", 0.05))

                cur.execute("""select f.ticker, f.engine, f.cash_conversion, f.market_cap, f.shares_out,
                                      f.fcf_ttm, f.c1_pass, f.c1_fail_reason, f.roic, f.reinvest_rate,
                                      f.pfcf_current, f.data_confidence, f.goodwill_jump,
                                      f.engine_agrees, f.revenue_cagr_3y, f.quote_ok, f.raw, u.is_holding
                               from v_fundamentals_latest f
                               join universe u on u.ticker=f.ticker
                               where u.kind='stock' and u.status='active' and (u.in_l0 or u.is_holding)""")
                rows = cur.fetchall()
                if not rows:
                    hb.amber("no fundamentals yet — nothing to score")
                    print("score: fundamentals table empty; run the sweep first")
                    return 0

                names = [r[0] for r in rows]
                closes = month_closes(cur, names)
                cur.execute("""select distinct on (ticker) ticker, close from prices
                               where ticker = any(%s) order by ticker, d desc""", (names,))
                last = {t: float(c) for t, c in cur.fetchall()}

            # ---- percentiles across all of L0 (§3.0) ----
            eng_p = pct_rank([(r[0], r[1]) for r in rows])
            cc_p = pct_rank([(r[0], r[2]) for r in rows])
            # smaller scores higher, on a log scale — policy owns the transform. The positive-cap
            # filter stays: market_cap is a float8, so it can arrive as NaN, and a NaN that
            # reached the sort would scramble every other name's size percentile, not just its own
            size_p = pct_rank([(r[0], inverted_log_size(r[3])) for r in rows if r[3] and r[3] > 0])

            out, unscored = [], []
            for (tk, engine, cc, mcap, shares, fcf, c1, c1why, roic, reinv,
                 pfcf_cur, conf, gw_jump, agrees, rev_cagr, quote_ok, raw, is_hold) in rows:
                # CCN v1.0 (§3.1) and the §3.3 renormalization both live in policy.ccn — including
                # the floor that keeps a name with no measurable business off the bench, which is
                # how a $4 microcap once topped it on smallness alone. None = not scorable at all.
                ccn, conf_calc = ccn_score(eng_p.get(tk), cc_p.get(tk), size_p.get(tk))
                if ccn is None:
                    unscored.append(tk)
                    continue
                # the sweep's own data_confidence wins whenever all three components are present:
                # it carries flags the percentiles cannot see (short history, engine divergence).
                # Only the "scored on 2 of 3" fact is policy's to state.
                confidence = conf if conf_calc == "full" else conf_calc

                # statements in one currency divided by a market cap in another is not a
                # multiple, it is a category error — so it produces no hurdle at all (§009)
                raw_d = {} if quote_ok is False else (raw if isinstance(raw, dict) else (json.loads(raw) if raw else {}))
                pfcf_med, obs = pfcf_history(raw_d, closes.get(tk, {}))
                if obs >= 8 and pfcf_med:
                    fair = min(pfcf_med, fair_cap)
                elif pfcf_cur and quote_ok is not False:
                    fair = min(pfcf_cur, fair_cap_short)
                else:
                    fair = None
                # §3.1 engine reliability check: growth = ROIC x reinvestment is an identity, so
                # it must agree with observed revenue growth. When it doesn't — usually a net-cash
                # balance sheet shrinking invested capital toward zero and sending ROIC to the moon
                # — we underwrite on the number we can check, never on the flattering one.
                # agreement is re-decided at scoring time, not read from the sweep: the tolerance
                # is a scoring policy, and changing it here costs no API calls
                # the row's stored verdict rides along: when the check cannot be recomputed here
                # (no revenue CAGR on the row) a stored False still means untrustworthy, and
                # promoting it back to full engine growth because an input went missing is
                # exactly the failure this check exists to prevent
                g, agrees_calc = engine_growth(engine, rev_cagr, growth_cap, tol, prior_agrees=agrees)
                # a None verdict means the check could not run at all, and an unrunnable check
                # overwrites nothing — the sweep's own flag stands
                if agrees_calc is not None:
                    agrees = agrees_calc
                hp = hurdle_price(fcf, shares, g, fair, floor)
                px = last.get(tk)
                gap = ((px - hp) / hp) if px and hp else None

                out.append(dict(
                    ticker=tk, ccn=ccn,
                    engine=eng_p.get(tk), cash_conv=cc_p.get(tk), size_score=size_p.get(tk),
                    engine_raw=engine, cash_conv_raw=cc, roic=roic, reinvest_rate=reinv,
                    c1_pass=(c1 and quote_ok is True),
                    c1_fail_reason=(c1why if c1 else None) if quote_ok is True else
                        ((c1why + " · " if c1why else "") +
                         "reports in a foreign currency or trades as a depositary receipt — "
                         "not priceable in v1"),
                    cohort=size_cohort(mcap, boundary),
                    hurdle_price=hp, fcf_yield=(fcf / mcap if fcf and mcap else None),
                    engine_growth=g, fair_multiple=fair,
                    derating_drag=(max(0.0, 1 - (fair / pfcf_cur) ** 0.2) if fair and pfcf_cur else None),
                    last_close=px, gap_to_hurdle=gap,
                    data_confidence=("flagged" if (agrees is False or quote_ok is False) else confidence),
                    serial_acquirer=bool(gw_jump),
                    pfcf_obs=obs, engine_agrees=agrees, is_holding=is_hold))

            # ---- bench: top-N by CCN from each size cohort (§3.1) ----
            eligible = [o for o in out if o["c1_pass"]]
            bench = []
            for cohort in ("small", "large"):
                pool = sorted([o for o in eligible if o["cohort"] == cohort],
                              key=lambda o: -o["ccn"])[:take]
                bench.extend(pool)
            # holdings always carry a score, whether or not they make the bench
            held = [o for o in out if o["is_holding"] and o["ticker"] not in {b["ticker"] for b in bench}]
            bench.extend(held)
            bench.sort(key=lambda o: -o["ccn"])
            for i, o in enumerate(bench):
                o["rank"] = i + 1

            # §3.1 seatbelt: rank eviction never touches a name within 10% of its hurdle.
            # Computed here rather than in the delete's SQL so `within_hurdle` stays the one
            # definition of "within 10%" — the same test the L2 seating rule uses.
            near_hurdle = sorted({o["ticker"] for o in out
                                  if within_hurdle(o["last_close"], o["hurdle_price"])})

            if not dry():
                with conn.cursor() as cur:
                    # §3.1: gate failure evicts immediately — no two-month seatbelt. Without
                    # this a name that later fails C1 keeps its stale row, and Phase 0 reads it
                    # as a live candidate (Karooooo survived the currency gate exactly this way).
                    failed = unscored + [o["ticker"] for o in out if not o["c1_pass"]]
                    cur.execute("""delete from bench where ticker = any(%s)
                                   and ticker not in (select ticker from universe where is_holding)""",
                                (failed,))
                    cur.execute("""update bench set months_outside_top60 = months_outside_top60 + 1
                                   where ticker <> all(%s)""", ([o["ticker"] for o in bench],))
                    cur.execute("""delete from bench where months_outside_top60 >= 2
                                   and not approved and ticker <> all(%s)
                                   and ticker not in (select ticker from universe where is_holding)""",
                                (near_hurdle,))
                    cur.executemany("""insert into bench(ticker,rank,cohort,ccn,engine,cash_conv,size_score,
                            engine_raw,cash_conv_raw,roic,reinvest_rate,c1_pass,c1_fail_reason,
                            hurdle_price,fcf_yield,engine_growth,derating_drag,fair_multiple,
                            last_close,gap_to_hurdle,data_confidence,serial_acquirer,computed_at)
                          values (%(ticker)s,%(rank)s,%(cohort)s,%(ccn)s,%(engine)s,%(cash_conv)s,%(size_score)s,
                            %(engine_raw)s,%(cash_conv_raw)s,%(roic)s,%(reinvest_rate)s,%(c1_pass)s,%(c1_fail_reason)s,
                            %(hurdle_price)s,%(fcf_yield)s,%(engine_growth)s,%(derating_drag)s,%(fair_multiple)s,
                            %(last_close)s,%(gap_to_hurdle)s,%(data_confidence)s,%(serial_acquirer)s,now())
                          on conflict (ticker) do update set rank=excluded.rank, cohort=excluded.cohort,
                            ccn=excluded.ccn, engine=excluded.engine, cash_conv=excluded.cash_conv,
                            size_score=excluded.size_score, engine_raw=excluded.engine_raw,
                            cash_conv_raw=excluded.cash_conv_raw, roic=excluded.roic,
                            reinvest_rate=excluded.reinvest_rate, c1_pass=excluded.c1_pass,
                            c1_fail_reason=excluded.c1_fail_reason, hurdle_price=excluded.hurdle_price,
                            fcf_yield=excluded.fcf_yield, engine_growth=excluded.engine_growth,
                            derating_drag=excluded.derating_drag, fair_multiple=excluded.fair_multiple,
                            last_close=excluded.last_close, gap_to_hurdle=excluded.gap_to_hurdle,
                            data_confidence=excluded.data_confidence, serial_acquirer=excluded.serial_acquirer,
                            months_outside_top60=0, computed_at=now()""", bench)
                conn.commit()

            buyable = [o["ticker"] for o in bench if o["gap_to_hurdle"] is not None and o["gap_to_hurdle"] <= 0]
            hb.rows = len(bench)
            hb.detail.update(scored=len(out), unscored=len(unscored),
                             c1_pass=len(eligible), bench=len(bench),
                             buyable=len(buyable), buyable_names=buyable[:20],
                             flagged=sum(1 for o in out if o["data_confidence"] != "full"))
            print(f"score: {len(out)} scored ({len(unscored)} unscorable) | C1 pass {len(eligible)} | "
                  f"bench {len(bench)} | at-or-below hurdle {len(buyable)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
