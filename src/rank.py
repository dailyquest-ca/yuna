"""weekly-rank — the Saturday half of the momentum brain (§3.0 cadence, §3.2 formulas).

Group RS -> L1-M rebuild -> MCN -> L2 re-rank. Everything price-shaped and *calm* lives here;
the daily half — base re-scan, trigger states, stops, arming — is `duties.py`, because §3.2 says
WAIT names are re-scanned nightly and §3.0 puts the trigger check in the pre-open run.

Every formula is imported from `signals`, never restated. Before that module this file carried
its own base detector, which drifted from the plan and from the backtest's copy.
"""
import sys
import numpy as np

from db import connect, config, dry, observe, Heartbeat
import signals as sg

T10 = 10                    # §3.2: all ranking windows end 10 trading days ago
L1M_SIZE = 150
SCOREABLE_BARS = 210        # 200-day average + the t-10 offset needs this much history


def load_bars(cur):
    cur.execute("""select p.ticker, p.d, p.high, p.low, p.close, p.adj_close, p.volume
                   from prices p join universe u on u.ticker = p.ticker
                   where u.kind='stock' and u.status='active' and (u.in_l0 or u.is_holding)
                   order by p.ticker, p.d""")
    data = {}
    for t, d, hi, lo, cl, ac, vol in cur.fetchall():
        data.setdefault(t, []).append((d, hi, lo, cl, ac, vol))
    return data


def features(data, meta):
    """Per-name arrays plus the effective-L0 bar filters (§3.0 L0)."""
    feats = {}
    for t, rows in data.items():
        cl = np.array([r[3] for r in rows], dtype=float)
        n = len(cl)
        vol = np.array([r[5] or 0 for r in rows], dtype=float)
        addv = float(np.median((cl * vol)[-50:])) if n >= 50 else 0.0
        feats[t] = dict(
            hi=np.array([r[1] for r in rows], dtype=float),
            lo=np.array([r[2] for r in rows], dtype=float),
            cl=cl,
            ac=np.array([r[4] if r[4] is not None else r[3] for r in rows], dtype=float),
            vol=vol, n=n, addv=addv,
            eff=bool(meta[t]["l0"] and n >= 126 and cl[-1] >= 5 and addv >= 10_000_000),
            scoreable=n >= SCOREABLE_BARS)
    return feats


def main():
    with connect() as conn:
        with Heartbeat(conn, "weekly-rank") as hb:
            with conn.cursor() as cur:
                queue_cap = int(config(cur, "queue_cap", 20))
                limit_over = float(config(cur, "entry_limit_over_pivot", 0.02))
                max_stop = float(config(cur, "momentum_max_stop", 0.08))
                hurdle_near = float(config(cur, "l2_hurdle_proximity", 0.10))

                cur.execute("select d, close from prices where ticker='GSPC.INDX' order by d")
                spx = cur.fetchall()
                cur.execute("select state from gate_state order by id desc limit 1")
                prev = (cur.fetchone() or [None])[0]
                gate = sg.market_gate([r[0] for r in spx], [float(r[1]) for r in spx], previous=prev)
                if not dry():
                    cur.execute("""insert into gate_state(week_end,state,spx_close,sma30,
                                     sma30_4w_ago,flipped)
                                   values (%s,%s,%s,%s,%s,%s)""",
                                (gate["week_end"], gate["state"], gate["spx"], gate["sma"],
                                 gate["sma_lookback"], gate["flipped"]))
                    conn.commit()

                cur.execute("""select ticker, industry, is_holding, in_l0 from universe
                               where kind='stock' and status='active'""")
                meta = {r[0]: dict(industry=r[1], hold=r[2], l0=r[3]) for r in cur.fetchall()}
                cur.execute("select ticker, m4_pass from v_fundamentals_latest")
                m4 = {r[0]: r[1] for r in cur.fetchall()}
                data = load_bars(cur)

            feats = features(data, meta)
            ranked = [t for t, f in feats.items() if f["eff"] and f["scoreable"]]

            # ---- MCN components, all windows ending t-10 (§3.2) ----
            quality, atr_pct, dryup, near_high, group_returns = {}, {}, {}, {}, {}
            for t in ranked:
                f = feats[t]
                ac, hi, lo, cl, vol = (f[k][:-T10] for k in ("ac", "hi", "lo", "cl", "vol"))
                quality[t] = sg.momentum_quality(ac)
                subs = sg.setup_proximity(hi, lo, cl, vol)
                atr_pct[t], dryup[t], near_high[t] = subs["atr_pct"], subs["dryup"], subs["near_high"]
                ind = meta[t]["industry"]
                if ind and len(ac) >= 126:
                    group_returns.setdefault(ind, []).append(float(ac[-1]) / float(ac[-126]) - 1)

            groups = sorted(group_returns)
            group_mean = {g: float(np.nanmean(group_returns[g])) for g in groups}
            group_pct = dict(zip(groups, sg.pct_rank([group_mean[g] for g in groups])))

            q_p = dict(zip(ranked, sg.pct_rank([quality[t] for t in ranked])))
            d_p = dict(zip(ranked, sg.pct_rank([dryup[t] for t in ranked])))
            x_p = dict(zip(ranked, sg.pct_rank([near_high[t] for t in ranked])))

            rows, m4_unknown = [], 0
            for t in ranked:
                f = feats[t]
                setup = float(np.nanmean([atr_pct[t], d_p[t], x_p[t]]))    # three sub-scores (S1-S5)
                grp = group_pct.get(meta[t]["industry"], 50.0) if meta[t]["industry"] else 50.0
                score = sg.mcn(q_p[t], setup, grp)
                base = sg.base_scan(f["hi"], f["lo"], f["cl"])
                m2 = sg.trend_template(f["cl"])
                if m4.get(t) is None:
                    m4_unknown += 1
                stop = (sg.initial_stop(base["pivot"], base["contraction_low"], max_stop=max_stop)
                        if base["valid"] else None)
                rows.append(dict(t=t, mcn=score, mq=q_p[t], setup=setup, grp=grp, m2=m2,
                                 m4=m4.get(t), state=base["state"], pivot=base["pivot"],
                                 blen=base["base_len"], depth=base["depth"],
                                 c_low=base["contraction_low"], stop=stop,
                                 px=float(f["cl"][-1]), broken=base["broken"]))

            # §3.2: L1-M membership = M2 and M4 pass, ranked by MCN, top 150. A name we have never
            # swept cannot pass M4, so it is not a member — the previous build treated an unknown
            # M4 as a pass, which is a gate the plan does not grant.
            l1m = sorted([r for r in rows if r["m2"] and r["m4"] is True],
                         key=lambda r: -(r["mcn"] or 0))[:L1M_SIZE]
            for i, r in enumerate(l1m):
                r["rank"] = i + 1

            # ---- L2 (§3.0): holdings + top-10 BUY + bench within 10% of hurdle + spare seats ----
            with conn.cursor() as cur:
                cur.execute("""select ticker, hurdle_price, last_close, ccn from bench
                               where hurdle_price is not null and last_close is not null
                                 and last_close <= hurdle_price * %s""", (1 + hurdle_near,))
                near_hurdle = cur.fetchall()

            by_ticker = {r["t"]: r for r in rows}
            seats, seen = [], set()

            def seat(ticker, source, state, trigger=None, limit=None, stop=None, score=None,
                     note=None):
                if ticker in seen:
                    return
                seen.add(ticker)
                px = float(feats[ticker]["cl"][-1]) if ticker in feats else None
                prox = abs(px - trigger) / px if (px and trigger) else None
                seats.append(dict(ticker=ticker, source=source, state=state, trig=trigger,
                                  lim=limit, stop=stop, prox=prox, mcn=score, note=note))

            for t in [t for t in feats if meta[t]["hold"]]:
                r = by_ticker.get(t, {})
                seat(t, "holding", "HOLD", score=r.get("mcn"), note="book")

            for r in sorted([r for r in l1m if r["state"] == "BUY"],
                            key=lambda r: -(r["mcn"] or 0))[:10]:
                seat(r["t"], "momentum", "BUY", trigger=r["pivot"],
                     limit=r["pivot"] * (1 + limit_over), stop=r["stop"], score=r["mcn"],
                     note=f"base {r['blen']}d/{r['depth']:.0%}")

            for ticker, hurdle, last_close, ccn_score in near_hurdle:
                gap = (float(last_close) - float(hurdle)) / float(hurdle)
                seat(ticker, "compounder", "BUY" if gap <= 0 else "WATCH", trigger=float(hurdle),
                     limit=float(hurdle), score=float(ccn_score) if ccn_score else None,
                     note=f"hurdle {float(hurdle):.2f} · {gap:+.1%}")

            for r in l1m:                                       # spare seats, for visibility
                if len(seats) >= queue_cap:
                    break
                seat(r["t"], "momentum", r["state"], trigger=r["pivot"],
                     limit=r["pivot"] * (1 + limit_over) if r["pivot"] else None,
                     stop=r["stop"], score=r["mcn"], note="L1-M rank %d" % r["rank"])

            seats.sort(key=lambda r: (r["source"] != "holding",
                                      r["prox"] if r["prox"] is not None else 9,
                                      -(r["mcn"] or 0)))
            seats = seats[:queue_cap]

            if not dry():
                with conn.cursor() as cur:
                    cur.execute("truncate candidates")
                    cur.execute("truncate queue")
                    cur.executemany("""insert into candidates(ticker,rank,mcn,mq,setup,grp,m2,m4,
                                         state,pivot,base_len,base_depth,base_low,stop_suggest,
                                         last_close)
                                       values (%(t)s,%(rank)s,%(mcn)s,%(mq)s,%(setup)s,%(grp)s,
                                         %(m2)s,%(m4)s,%(state)s,%(pivot)s,%(blen)s,%(depth)s,
                                         %(c_low)s,%(stop)s,%(px)s)""", l1m)
                    cur.executemany("""insert into queue(ticker,rank,source,state,trigger_price,
                                         limit_price,stop_suggest,proximity,mcn,note)
                                       values (%(ticker)s,%(rank)s,%(source)s,%(state)s,%(trig)s,
                                         %(lim)s,%(stop)s,%(prox)s,%(mcn)s,%(note)s)""",
                                    [{**r, "rank": i + 1} for i, r in enumerate(seats)])
                    cur.executemany("""insert into group_strength(week_end,industry,ret_6m,
                                         percentile,members)
                                       values (%s,%s,%s,%s,%s)
                                       on conflict (week_end,industry) do update set
                                         ret_6m=excluded.ret_6m, percentile=excluded.percentile,
                                         members=excluded.members""",
                                    [(gate["week_end"], g, group_mean[g], group_pct[g],
                                      len(group_returns[g])) for g in groups])
                    if gate["flipped"]:
                        observe(cur, "gate_flip",
                                f"M1 flipped {gate['previous']} -> {gate['state']} on the "
                                f"{gate['week_end']} weekly close",
                                detail=dict(spx=gate["spx"], sma=gate["sma"],
                                            sma_4w=gate["sma_lookback"]),
                                once=True)
                conn.commit()

            hb.rows = 0 if dry() else len(l1m) + len(seats) + len(groups)
            hb.detail.update(gate=gate["state"], gate_flipped=gate["flipped"],
                             effective_l0=len(ranked), l1m=len(l1m),
                             buy=sum(1 for r in l1m if r["state"] == "BUY"),
                             queue=len(seats), groups=len(groups), m4_unknown=m4_unknown,
                             spent_pivots=sum(1 for r in rows if r["broken"] == "spent"))
            if m4_unknown:
                hb.detail["m4_note"] = (f"{m4_unknown} scoreable names have no fundamentals row, "
                                        "so they cannot pass M4 and are not L1-M members")
            print(f"weekly-rank: gate {gate['state']} | effective L0 {len(ranked)} | "
                  f"L1-M {len(l1m)} | BUY {sum(1 for r in l1m if r['state'] == 'BUY')} | "
                  f"queue {len(seats)} | groups {len(groups)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
