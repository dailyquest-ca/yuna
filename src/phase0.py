"""phase0 — the one-time re-underwrite (plan §6).

Every current holding is scored by both pipelines and kept only if the system would buy it
today: score ≥ 70, gates passed, §2 caps applied as though every position were a new entry.
The levered layer sits outside the sleeves and is judged at Step 5 under §2.5.

Then it builds the two opportunity lists — compounders at or below hurdle, momentum names
with a live trigger — sized against NAV, and writes the whole verdict to `briefs` with an
exit or entry ticket per line. Yuna never executes; Zak places every order.
"""
import os, sys, json, math, datetime as dt
import psycopg
from db import connect, config, dry, nav_cad, Heartbeat

ENTER = 70.0          # §3.3 enterable
FULL = 85.0           # §3.3 full conviction


def main():
    with connect() as conn:
        with Heartbeat(conn, "phase0") as hb:
            with conn.cursor() as cur:
                flat = float(config(cur, "ccn_flat_size", 0.12))
                floor_pct = float(config(cur, "position_floor_nav", 0.04))
                theme_cap = float(config(cur, "theme_entry_cap", 0.35))
                per_group = int(config(cur, "max_names_per_group", 2))
                budgets = config(cur, "mcn_risk_budget_validation", {"70": 0.005, "85": 0.007})
                max_stop = float(config(cur, "momentum_max_stop", 0.08))

                n = nav_cad(cur)
                fx, nav = n["fx"], n["nav"]
                equities, cash, debt = n["book_equities"], n["cash"], n["debt"]
                per_value, anchored = n["per_ticker"], n["balances_captured"]

                cur.execute("""select b.id, b.ticker, b.account, b.sleeve, b.qty, b.currency,
                                      u.name, u.sector, u.industry
                               from book b join universe u on u.ticker=b.ticker
                               where b.status='open' order by b.ticker""")
                held = [dict(id=r[0], ticker=r[1], account=r[2], sleeve=r[3], qty=float(r[4]),
                             currency=r[5], name=r[6], sector=r[7], industry=r[8]) for r in cur.fetchall()]

                cur.execute("select ticker, mcn from queue where source='holding'")
                mcn_hold = {t: (float(m) if m is not None else None) for t, m in cur.fetchall()}
                cur.execute("select ticker, mcn, m2, m4, state, pivot, stop_suggest, last_close from candidates")
                cand = {r[0]: dict(mcn=float(r[1]), m2=r[2], m4=r[3], state=r[4],
                                   pivot=r[5], stop=r[6], px=r[7]) for r in cur.fetchall()}
                cur.execute("""select ticker, ccn, c1_pass, c1_fail_reason, hurdle_price, last_close,
                                      gap_to_hurdle, data_confidence, cohort, serial_acquirer
                               from bench""")
                bench = {r[0]: dict(ccn=float(r[1]) if r[1] is not None else None, c1=r[2], why=r[3],
                                    hurdle=r[4], px=r[5], gap=r[6], conf=r[7], cohort=r[8],
                                    acq=r[9]) for r in cur.fetchall()}

            # ---------------- Step 2a/2b: re-underwrite every incumbent ----------------
            verdicts = []
            for h in held:
                tk = h["ticker"]
                b = bench.get(tk, {})
                c = cand.get(tk, {})
                mcn = mcn_hold.get(tk, c.get("mcn"))
                ccn = b.get("ccn")
                value = per_value.get(tk, 0.0)
                weight = value / nav if nav else None

                if h["sleeve"] == "levered":
                    verdicts.append({**h, "value_cad": value, "weight": weight, "ccn": ccn, "mcn": mcn,
                                     "verdict": "STEP 5", "sleeve_assigned": "levered",
                                     "why": "levered layer — outside the sleeves, judged under §2.5 "
                                            "(single name needs CCN ≥ 85)"})
                    continue

                comp_ok = bool(b.get("c1")) and ccn is not None and ccn >= ENTER
                mom_ok = mcn is not None and mcn >= ENTER and bool(c.get("m2")) and c.get("m4") is not False
                if comp_ok:
                    sleeve, why = "compounders", f"CCN {ccn:.1f} ≥ 70, Gate C1 passed"
                elif mom_ok:
                    sleeve, why = "momentum", f"MCN {mcn:.1f} ≥ 70, trend template intact"
                else:
                    bits = []
                    bits.append(f"CCN {ccn:.1f}" if ccn is not None else "CCN unscored")
                    if not b.get("c1") and b.get("why"):
                        bits.append(f"C1 fail: {b['why']}")
                    bits.append(f"MCN {mcn:.1f}" if mcn is not None else "MCN unscored")
                    if not c.get("m2"):
                        bits.append("fails trend template")
                    sleeve, why = None, " · ".join(bits)
                verdicts.append({**h, "value_cad": value, "weight": weight, "ccn": ccn, "mcn": mcn,
                                 "verdict": "KEEP" if sleeve else "EXIT",
                                 "sleeve_assigned": sleeve, "why": why})

            # §2 caps applied as if each survivor were a new entry today
            survivors = [v for v in verdicts if v["verdict"] == "KEEP"]
            survivors.sort(key=lambda v: -(v["ccn"] if v["sleeve_assigned"] == "compounders" else v["mcn"] or 0))
            group_count, theme_weight = {}, {}
            for v in survivors:
                g, th = v["industry"] or "unknown", v["sector"] or "unknown"
                intended = flat if v["sleeve_assigned"] == "compounders" else (v["weight"] or 0)
                if group_count.get(g, 0) >= per_group:
                    v["verdict"] = "EXIT"
                    v["why"] += f" · §2.2 breach: already {per_group} names in {g}"
                    continue
                if theme_weight.get(th, 0.0) + intended > theme_cap:
                    v["verdict"] = "EXIT"
                    v["why"] += f" · §2.2 breach: {th} theme would exceed {theme_cap:.0%}"
                    continue
                if (v["weight"] or 0) < floor_pct and v["sleeve_assigned"] != "compounders":
                    v["verdict"] = "EXIT"
                    v["why"] += f" · below the {floor_pct:.0%} position floor and not sized up"
                    continue
                group_count[g] = group_count.get(g, 0) + 1
                theme_weight[th] = theme_weight.get(th, 0.0) + intended

            # ---------------- the two opportunity lists ----------------
            comp_list = sorted(
                [dict(ticker=t, **b) for t, b in bench.items()
                 if b["c1"] and b["ccn"] is not None and b["ccn"] >= ENTER
                 and b["gap"] is not None and b["gap"] <= 0],
                key=lambda x: -x["ccn"])
            for c_ in comp_list:
                c_["size_pct"] = flat
                c_["size_cad"] = flat * nav if nav else None
                c_["shares"] = int((flat * nav) / (float(c_["px"]) * fx)) if nav and c_["px"] else None

            with conn.cursor() as cur:
                cur.execute("""select q.ticker, u.name, q.mcn, q.trigger_price, q.limit_price,
                                      q.stop_suggest, q.proximity, q.note, c.last_close
                               from queue q join universe u on u.ticker=q.ticker
                               left join candidates c on c.ticker=q.ticker
                               where q.source='momentum' and q.state='BUY'
                               order by q.proximity""")
                mom_list = []
                for tk, nm, mcn, trig, lim, stop, prox, note, px in cur.fetchall():
                    mcn = float(mcn); trig = float(trig); stop = float(stop)
                    risk = float(budgets.get("85" if mcn >= FULL else "70", 0.005))
                    dist = max((trig - stop) / trig, 0.0001)
                    if dist > max_stop:                      # §3.2 never wider than 8%
                        stop = trig * (1 - max_stop); dist = max_stop
                    size_pct = min(risk / dist, 0.12)        # capped by the momentum band
                    mom_list.append(dict(ticker=tk, name=nm, mcn=mcn, trigger=trig, limit=float(lim),
                                         stop=stop, stop_limit=stop * 0.97,
                                         away_pct=100 * float(prox), base=note,
                                         risk_budget=risk, stop_distance=dist,
                                         size_pct=size_pct,
                                         shares=int((size_pct * nav) / (trig * fx)) if nav else None))

            # ---------------- write it down ----------------
            exits = [v for v in verdicts if v["verdict"] == "EXIT"]
            keeps = [v for v in verdicts if v["verdict"] == "KEEP"]
            step5 = [v for v in verdicts if v["verdict"] == "STEP 5"]
            summary = (f"{len(keeps)} keep · {len(exits)} exit · {len(step5)} to Step 5 | "
                       f"{len(comp_list)} compounders at/below hurdle · {len(mom_list)} momentum triggers | "
                       f"NAV {'CAD ' + format(nav, ',.0f') if anchored else 'equities-only CAD ' + format(nav, ',.0f') + ' (provisional)'}")
            detail = dict(nav_cad=round(nav, 2), equities_cad=round(equities, 2),
                          cash_cad=round(cash, 2), debt_cad=round(debt, 2), usdcad=fx,
                          balances_captured=anchored, accounts=n["accounts"],
                          book_equities_cad=round(n["book_equities"], 2), verdicts=verdicts,
                          compounder_list=comp_list, momentum_list=mom_list)

            if not dry():
                with conn.cursor() as cur:
                    cur.execute("""insert into briefs(kind,session_date,freshness,summary,detail)
                                   values ('phase0',current_date,%s,%s,%s) returning id""",
                                ("phase 0 re-underwrite", summary, json.dumps(detail, default=str)))
                    brief_id = cur.fetchone()[0]
                    for v in exits:
                        cur.execute("""insert into tickets(ticker,account,sleeve,action,reason,
                                         order_type,qty,state,brief_id,note)
                                       values (%s,%s,%s,'sell','phase0','market',%s,'proposed',%s,%s)""",
                                    (v["ticker"], v["account"], v["sleeve"], v["qty"], brief_id, v["why"]))
                    for m in mom_list:
                        cur.execute("""insert into tickets(ticker,account,sleeve,action,reason,order_type,
                                         trigger_price,limit_price,qty,stop,stop_limit_price,state,brief_id,note)
                                       values (%s,'TFSA','momentum','buy','trigger','stop_limit',
                                         %s,%s,%s,%s,%s,'proposed',%s,%s)""",
                                    (m["ticker"], m["trigger"], m["limit"], m["shares"], m["stop"],
                                     m["stop_limit"], brief_id, f"MCN {m['mcn']:.1f} · {m['base']}"))
                    for c_ in comp_list[:5]:
                        cur.execute("""insert into tickets(ticker,account,sleeve,action,reason,order_type,
                                         limit_price,qty,state,brief_id,note)
                                       values (%s,'TFSA','compounders','buy','hurdle','limit',
                                         %s,%s,'proposed',%s,%s)""",
                                    (c_["ticker"], c_["px"], c_["shares"], brief_id,
                                     f"CCN {c_['ccn']:.1f} · hurdle {float(c_['hurdle']):.2f} · "
                                     f"{abs(100*float(c_['gap'])):.0f}% below · C2 memo pending"))
                conn.commit()

            hb.rows = len(exits) + len(mom_list) + min(5, len(comp_list)) + 1
            hb.detail.update(keeps=[v["ticker"] for v in keeps], exits=[v["ticker"] for v in exits],
                             step5=[v["ticker"] for v in step5], nav_cad=round(nav, 2),
                             balances_captured=anchored, compounders=len(comp_list),
                             momentum=len(mom_list))
            if not anchored:
                hb.amber("no balances captured — NAV is equities-only, sizing is directional")
            print("phase0:", summary)
            for v in verdicts:
                print(f"  {v['verdict']:>7}  {v['ticker']:<9} {v['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
