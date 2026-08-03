"""rank — the momentum brain's ranking half (§3.0 cadence, §3.2 formulas).

Market gate -> group RS -> L1-M rebuild -> MCN -> L2 re-rank -> the company we keep.

**A library, not a job.** §4.2 gives every derived number one writer, and that writer is `score`,
which calls `run()` below. There is no entrypoint here on purpose: two jobs writing the queue is
the shape of bug this architecture exists to make impossible.

Every formula is imported from `signals`, never restated. Before that module this file carried
its own base detector, which drifted from the plan and from the backtest's copy.
"""
import numpy as np

from db import config, dry, observe
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


def company_we_keep(conn, dry_run):
    """§3.1, 2026-08-02 — the weekly two-way check against the reference investors.

    Both directions read the top-holder records already stored with every filing; no vendor call.
    (a) bench rows get `corroborated_by` — which reference investors appear among the holders;
    (b) the reverse sweep lists every L0 name held by two or more of them that our bench lacks,
    with the exact reason it missed. A mirror, never a source: nothing here moves a score.
    """
    with conn.cursor() as cur:
        pats = config(cur, "named_investors",
                      ["Fundsmith", "Akre", "Polen", "TCI Fund", "Pershing",
                       "WCM Invest", "Giverny"])
        cur.execute("""
            select f.ticker, array_agg(distinct p.pat order by p.pat)
              from v_fundamentals_latest f
              join universe u on u.ticker = f.ticker
               and u.kind='stock' and u.status='active' and (u.in_l0 or u.is_holding)
             cross join lateral (
                   select value->>'name' as nm
                     from jsonb_each(coalesce(f.raw_doc->'Holders'->'Institutions','{}'::jsonb))
                   union all
                   select value->>'name'
                     from jsonb_each(coalesce(f.raw_doc->'Holders'->'Funds','{}'::jsonb))
             ) h
              join unnest(%s::text[]) p(pat) on h.nm ilike '%%' || p.pat || '%%'
             group by f.ticker""", (list(pats),))
        matches = {r[0]: r[1] for r in cur.fetchall()}

        if not dry_run:
            cur.execute("update bench set corroborated_by = null")
            for tk, who in matches.items():
                cur.execute("update bench set corroborated_by = %s where ticker = %s", (who, tk))

        # the reverse sweep: >=2 reference investors hold it, our bench does not
        cur.execute("select ticker from bench")
        on_bench = {r[0] for r in cur.fetchall()}
        sweep = []
        for tk, who in sorted(matches.items()):
            if len(who) < 2 or tk in on_bench:
                continue
            cur.execute("""select c1_pass, c1_fail_reason from v_fundamentals_latest
                           where ticker = %s""", (tk,))
            row = cur.fetchone()
            if row is None:
                why = "never swept — no fundamentals row"
            elif row[0] is False:
                why = f"C1: {row[1] or 'failed, reason not stored'}"
            else:
                why = "eligible but outside the top-60 by CCN, or not bench-eligible (engine/durability)"
            sweep.append(dict(ticker=tk, held_by=who, missed_because=why))
        if sweep and not dry_run:
            observe(cur, "note",
                    "The company we keep — reverse sweep: "
                    + "; ".join(f"{s['ticker']} ({', '.join(s['held_by'])}) — {s['missed_because']}"
                                for s in sweep[:15]),
                    detail=dict(sweep=sweep), once=True)
    conn.commit()
    return dict(corroborated_on_bench=len(matches.keys() & on_bench),
                held_anywhere_in_l0=len(matches),
                reverse_sweep=sweep[:25], investors=list(pats))


def run(conn, hb):
    """The ranking half of `score`. Writes gate_state, candidates, queue, group_strength and the
    corroboration column; returns nothing — every finding lands on the caller's heartbeat."""
    with conn.cursor() as cur:
        queue_cap = int(config(cur, "queue_cap", 20))
        limit_over = float(config(cur, "entry_limit_over_pivot", 0.02))
        max_stop = float(config(cur, "momentum_max_stop", 0.08))
        hurdle_near = float(config(cur, "l2_hurdle_proximity", 0.10))

        cur.execute("select d, close from prices where ticker='GSPC.INDX' order by d")
        spx = cur.fetchall()
        cur.execute("select week_end, state from gate_state order by id desc limit 1")
        last = cur.fetchone()
        prev = last[1] if last else None
        gate = sg.market_gate([r[0] for r in spx], [float(r[1]) for r in spx], previous=prev)
        # §4.2 makes every job idempotent, and `score` now runs after every ingest rather than
        # once a week. M1 is a WEEKLY reading, so a second run inside the same week must not
        # append a second row — the ledger records gate readings, not job invocations.
        same_week = bool(last) and last[0] == gate["week_end"] and last[1] == gate["state"]
        if not dry() and not same_week:
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
    # §3.0: "Holdings are always scored, by both pipelines — membership lists never drop a
    # name the book owns." The L0 bar filters decide MEMBERSHIP, not scoreability, so a
    # holding that sits outside L0 still gets an MCN. CNQ.TO is the case in the book: a TSX
    # listing, `in_l0=false` by the US-exchange rule, 754 bars of perfectly good history —
    # and it carried a null MCN into every queue and every brief because this line dropped
    # it before a single component was computed.
    ranked = [t for t, f in feats.items()
              if f["scoreable"] and (f["eff"] or meta[t]["hold"])]

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

    rows, m4_missing = [], []
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
    # Scored is not the same as a member: L1-M is still an L0 population, so a holding that
    # is scored but outside L0 gets its MCN and no candidacy.
    l1m = sorted([r for r in rows if r["m2"] and r["m4"] is True and feats[r["t"]]["eff"]],
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
        # WATCH was invented here and exists nowhere in the plan. §6 step 3 names the state
        # in plain words — approved names at or below hurdle enter immediately, "above-hurdle
        # names wait on the daily check" — so the legislated pair is BUY / WAIT, and the
        # queue's state column is now constrained to it (migration 025).
        seat(ticker, "compounder", "BUY" if gap <= 0 else "WAIT", trigger=float(hurdle),
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

    keep = company_we_keep(conn, dry())
    hb.detail["company_we_keep"] = keep

    hb.rows = 0 if dry() else len(l1m) + len(seats) + len(groups)
    hb.detail.update(gate=gate["state"], gate_flipped=gate["flipped"],
                     effective_l0=len(ranked), l1m=len(l1m),
                     buy=sum(1 for r in l1m if r["state"] == "BUY"),
                     queue=len(seats), groups=len(groups), m4_unknown=len(m4_missing),
                     spent_pivots=sum(1 for r in rows if r["broken"] == "spent"))
    if m4_missing:
        # Named, not counted. A bare count reads as weather; the names read as a work list — these
        # are exactly the tickers a filings sweep would make eligible.
        hb.detail["m4_missing"] = sorted(m4_missing)
        hb.detail["m4_note"] = (f"{len(m4_missing)} scoreable names have no fundamentals row, so "
                                f"they cannot pass M4 and are not L1-M members: "
                                + ", ".join(sorted(m4_missing)[:40])
                                + (" ..." if len(m4_missing) > 40 else ""))
    print(f"score/rank: gate {gate['state']} | effective L0 {len(ranked)} | "
          f"L1-M {len(l1m)} | BUY {sum(1 for r in l1m if r['state'] == 'BUY')} | "
          f"queue {len(seats)} | groups {len(groups)}")
