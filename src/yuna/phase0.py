"""phase0 — the one-time re-underwrite (plan §6).

Every current holding is scored by both pipelines and kept only if the system would buy it
today: score ≥ 70, gates passed, §2 caps applied as though every position were a new entry.
The levered layer sits outside the sleeves and is judged at Step 5 under §2.5.

Then it builds the two opportunity lists — compounders at or below hurdle, momentum names
with a live trigger — sized against NAV, and writes the whole verdict to `briefs` with an
exit or entry ticket per line. Yuna never executes; Zak places every order.
"""
import json
import sys

from yuna.db import Heartbeat, config, connect, dry, nav_cad
from yuna.rules import implements

ENTER = 70.0          # §3.3 enterable
FULL = 85.0           # §3.3 full conviction


@implements("6/re-underwrite",
            "scores every open position through both pipelines and keeps it only if the system "
            "would enter it today, then re-applies the §2 caps as though it were a new entry")
@implements("6/conforming-target-book",
            "hands over the two opportunity pools cut down to the sleeve counts, the sleeve "
            "weights, the §2.2 caps and the blackout — not a raw list")
@implements("2.7/non-conformance",
            "an incumbent that breaches a cap is named with the clause it breaches and leaves "
            "the re-underwrite as an exit line")
@implements("3.3/thresholds",
            "70 is enterable on both CCN and MCN; 85 is full conviction and picks the momentum "
            "risk budget")
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
            # These are candidate pools. What Zak gets is a *conforming target book* drawn
            # from them: §2.1 name counts and sleeve ceilings, §2.2 independence, §3.3
            # blackout. Handing over ten momentum names at 6% each would be 63% of NAV in a
            # sleeve capped at 40% — a list, not a plan.
            with conn.cursor() as cur:
                cur.execute("""select ticker from earnings
                               where report_date >= current_date
                                 and report_date <= current_date + 8""")
                blackout = {r[0] for r in cur.fetchall()}
                cur.execute("select ticker, sector, industry from universe")
                sec = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

            comp_pool = sorted(
                [dict(ticker=t, **b) for t, b in bench.items()
                 if b["c1"] and b["ccn"] is not None and b["ccn"] >= ENTER
                 and b["gap"] is not None and b["gap"] <= 0],
                key=lambda x: -x["ccn"])

            with conn.cursor() as cur:
                cur.execute("""select q.ticker, u.name, q.mcn, q.trigger_price, q.limit_price,
                                      q.stop_suggest, q.proximity, q.note
                               from queue q join universe u on u.ticker=q.ticker
                               where q.source='momentum' and q.state='BUY'
                               order by q.mcn desc nulls last""")
                mom_pool = []
                for tk, nm, mcn, trig, lim, stop, prox, note in cur.fetchall():
                    mcn = float(mcn); trig = float(trig); stop = float(stop)
                    # Stays inline until policy.momentum_size takes a max_stop and hands back the
                    # capped stop: it caps at its own MAX_STOP where §3.2's 8% is read here from
                    # the `momentum_max_stop` row (§4.3 — config is the plan's runtime copy), and
                    # the mutated stop below is what the ticket carries, not just the distance.
                    risk = float(budgets.get("85" if mcn >= FULL else "70", 0.005))
                    dist = max((trig - stop) / trig, 0.0001)
                    if dist > max_stop:                      # §3.2 never wider than 8%
                        stop = trig * (1 - max_stop); dist = max_stop
                    size_pct = min(risk / dist, 0.12)        # capped by the momentum band
                    mom_pool.append(dict(ticker=tk, name=nm, mcn=mcn, trigger=trig,
                                         limit=float(lim), stop=stop, stop_limit=stop * 0.97,
                                         away_pct=100 * float(prox), base=note,
                                         risk_budget=risk, stop_distance=dist, size_pct=size_pct,
                                         shares=int((size_pct * nav) / (trig * fx)) if nav else None))

            # ---------------- select the conforming target book ----------------
            groups, themes = dict(group_count), dict(theme_weight)

            def admit(tk, weight):
                """§2.2: at most two names per industry group, no theme above 35% on entry."""
                th, g = sec.get(tk, (None, None))
                g, th = g or "unknown", th or "unknown"
                # The "2" stays on the config row rather than policy.MAX_NAMES_PER_GROUP, which
                # policy.group_has_room hardcodes: wiring it would silently ignore
                # `max_names_per_group` here while the breach message still quotes it.
                if groups.get(g, 0) >= per_group:
                    return None, f"§2.2 — already {per_group} names in {g}"
                if themes.get(th, 0.0) + weight > theme_cap:
                    return None, f"§2.2 — {th} theme would exceed {theme_cap:.0%}"
                return (g, th), None

            comp_list, comp_rejected = [], []
            comp_room = 0.60
            for c_ in comp_pool:
                if len(comp_list) >= 5 or comp_room < flat:
                    comp_rejected.append({**c_, "held_back": "§2.1 — compounder sleeve full"}); continue
                if c_["ticker"] in blackout:
                    comp_rejected.append({**c_, "held_back": "§3.3 — earnings blackout"}); continue
                keys, why = admit(c_["ticker"], flat)
                if not keys:
                    comp_rejected.append({**c_, "held_back": why}); continue
                g, th = keys
                groups[g] = groups.get(g, 0) + 1
                themes[th] = themes.get(th, 0.0) + flat
                comp_room -= flat
                c_.update(size_pct=flat, size_cad=flat * nav if nav else None,
                          shares=int((flat * nav) / (float(c_["px"]) * fx)) if nav and c_["px"] else None)
                comp_list.append(c_)

            mom_list, mom_rejected = [], []
            mom_room = 0.40
            for m in mom_pool:
                if len(mom_list) >= 4 or mom_room < m["size_pct"]:
                    mom_rejected.append({**m, "held_back": "§2.1 — momentum sleeve full"}); continue
                if m["ticker"] in blackout:
                    mom_rejected.append({**m, "held_back": "§3.3 — earnings blackout"}); continue
                keys, why = admit(m["ticker"], m["size_pct"])
                if not keys:
                    mom_rejected.append({**m, "held_back": why}); continue
                g, th = keys
                groups[g] = groups.get(g, 0) + 1
                themes[th] = themes.get(th, 0.0) + m["size_pct"]
                mom_room -= m["size_pct"]
                mom_list.append(m)

            # ---------------- write it down ----------------
            exits = [v for v in verdicts if v["verdict"] == "EXIT"]
            keeps = [v for v in verdicts if v["verdict"] == "KEEP"]
            step5 = [v for v in verdicts if v["verdict"] == "STEP 5"]
            summary = (f"{len(keeps)} keep · {len(exits)} exit · {len(step5)} to Step 5 | "
                       f"target book: {len(comp_list)} compounders (of {len(comp_pool)} at/below hurdle) · "
                       f"{len(mom_list)} momentum (of {len(mom_pool)} triggered) | "
                       f"NAV {'CAD ' + format(nav, ',.0f') if anchored else 'equities-only CAD ' + format(nav, ',.0f') + ' (provisional)'}")
            detail = dict(nav_cad=round(nav, 2), equities_cad=round(equities, 2),
                          cash_cad=round(cash, 2), debt_cad=round(debt, 2), usdcad=fx,
                          balances_captured=anchored, accounts=n["accounts"],
                          book_equities_cad=round(n["book_equities"], 2), verdicts=verdicts,
                          compounder_list=comp_list, momentum_list=mom_list,
                          compounder_pool=comp_pool, momentum_pool=mom_pool,
                          held_back=comp_rejected + mom_rejected,
                          blackout=sorted(blackout & (set(c["ticker"] for c in comp_pool)
                                                      | set(m["ticker"] for m in mom_pool))),
                          target_weights=dict(compounders=round(0.60 - comp_room, 3),
                                              momentum=round(0.40 - mom_room, 3)),
                          groups=groups, themes={k: round(v, 3) for k, v in themes.items()})

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
                    rrsp_cash = float((n["accounts"].get("RRSP") or {}).get("cash_cad") or 0)
                    for c_ in comp_list:
                        cost = float(c_["size_cad"] or 0)
                        # §2.6 / §6 Step 3: idle RRSP cash deploys into compounders first —
                        # multi-year no-touch holds, and US dividend withholding is treaty-exempt
                        if rrsp_cash >= cost:
                            acct = "RRSP"; rrsp_cash -= cost
                        else:
                            acct = "TFSA"
                        c_["account"] = acct
                        cur.execute("""insert into tickets(ticker,account,sleeve,action,reason,order_type,
                                         limit_price,qty,state,brief_id,note)
                                       values (%s,%s,'compounders','buy','hurdle','limit',
                                         %s,%s,'proposed',%s,%s)""",
                                    (c_["ticker"], acct, c_["px"], c_["shares"], brief_id,
                                     f"CCN {c_['ccn']:.1f} · hurdle {float(c_['hurdle']):.2f} · "
                                     f"{abs(100*float(c_['gap'])):.0f}% below · C2 memo pending"))
                conn.commit()

            hb.rows = len(exits) + len(mom_list) + min(5, len(comp_list)) + 1
            proceeds = sum(v["value_cad"] for v in exits)
            outlay = (sum(float(c["size_cad"] or 0) for c in comp_list)
                      + sum((m["size_pct"] or 0) * nav for m in mom_list))
            hb.detail["funding"] = {"exit_proceeds_cad": round(proceeds, 2),
                                    "entry_outlay_cad": round(outlay, 2),
                                    "cash_before_cad": round(cash, 2),
                                    "sequence": "sells settle before buys — T+1 at Wealthsimple"}
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
