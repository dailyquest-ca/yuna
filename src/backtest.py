"""backtest — the momentum sleeve replayed under the law, using the law's own code.

This job is a **driver**, not a second implementation. Every rule it applies is a call into
`signals.py`, the same module `arming.py` calls tonight: one market gate, one trend template, one
base detector, one confirmation state machine, one stop ladder, one sizing formula. Before this
rewrite the backtest re-derived all of them by hand, and the private copy had drifted in nine
places — four MCN setup sub-scores against the law's three, pyramid adds at +2.5%/+4.5% against
+2%/+4%, no add ceiling, no MCN floor, a `volume unconfirmed` exit the plan deleted, and no
blackout at all. 211 of run 5's 296 trades were entries §3.2 forbids outright. A backtest that
measures a sincere restatement of the rules measures nothing.

What it models, per the 2026-08-10 rulings:

  * **USD-native.** US listings only; no FX translation and no conversion fee. NAV starts in USD.
  * **VOO is the benchmark**, on adjusted closes — total return, dividends included. The sleeve's
    own P&L is price-only, so the comparison is biased *against* us, which is the safe direction;
    the magnitude is reported as `stats.dividend_bps` rather than left to the imagination.
  * **Delisted names are retained.** L0 membership is derived from bars at each date, never from
    today's `universe.status`, so a name that died in 2019 is in the census until the day its bars
    stop — and a position holding it exits on the `delisted` rule instead of being marked forever.
  * **Costs.** Half-spread by ADDV bucket, per side; commission zero (Wealthsimple). Gross and net
    both recorded on every trade.
  * **Fixed 280-bar tails.** No rule reads deeper than 266 bars, so the driver hands each call a
    280-bar window and the cost per rank date is constant in the length of the test.
    `tests/test_tail_equivalence.py` pins that the tail and the full series agree.

Biases that remain, stated on every run rather than buried: the vendor serves the current version
of a past statement, so a restatement is seen earlier than the market saw it; industry mappings are
today's; and the L0 census is reconstructed from bars rather than from a stored point-in-time
listing, so a name whose bars we never pulled is still absent.
"""
import os, sys, json, bisect, hashlib, datetime as dt
import numpy as np
import pandas as pd
from db import connect, config, dry, Heartbeat
import signals as sg

START_NAV = float(os.environ.get("START_NAV", "200000"))       # USD (ruled 2026-08-10)
LABEL = os.environ.get("LABEL", "law-v0")
VARIANT = os.environ.get("VARIANT", "law-v0")
LAW_STAMP = os.environ.get("LAW_STAMP", "2026-08-09")
START_DATE = os.environ.get("START_DATE") or None
END_DATE = os.environ.get("END_DATE") or None

WARMUP = 280            # >= 266, the deepest window any rule reads (see tests/test_tail_equivalence)
TAIL = 280
T10 = 10                # §3.2: every MCN ranking window ends 10 trading days ago
BENCH = os.environ.get("BENCHMARK", "VOO.US")
DELISTED_AFTER = 5      # sessions without a bar before a holding is treated as gone


# =============================================================================== data
def load(cur):
    """Every US bar we hold, living and dead. The census is rebuilt from bars, not from `status`."""
    cur.execute("""select p.ticker, p.d, p.open, p.high, p.low, p.close, p.adj_close, p.volume
                     from prices p join universe u on u.ticker = p.ticker
                    where u.kind = 'stock' and u.ticker like '%%.US'
                    order by p.d""")
    df = pd.DataFrame(cur.fetchall(),
                      columns=["ticker", "d", "open", "high", "low", "close", "adj", "vol"])
    for c in ("open", "high", "low", "close", "adj", "vol"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["adj"] = df["adj"].fillna(df["close"])
    wide = {c: df.pivot(index="d", columns="ticker", values=c).sort_index()
            for c in ("open", "high", "low", "close", "adj", "vol")}

    cur.execute("select ticker, industry from universe where kind='stock'")
    industry = {t: i for t, i in cur.fetchall()}

    cur.execute("""select d, close, coalesce(adj_close, close) from prices
                    where ticker = %s order by d""", (BENCH,))
    rows = cur.fetchall()
    bench = pd.Series({d: float(a) for d, _, a in rows}).sort_index() if rows else pd.Series(dtype=float)

    # M1 is the S&P 500 (§3.2). GSPC if we hold it deep enough, else the tracker standing in for it.
    cur.execute("select d, close from prices where ticker='GSPC.INDX' order by d")
    spx = pd.Series({d: float(c) for d, c in cur.fetchall()}).sort_index()
    gate_source = "GSPC.INDX"
    if len(spx) < len(bench):
        spx, gate_source = pd.Series({d: float(c) for d, c, _ in rows}).sort_index(), BENCH

    cur.execute("select ticker, report_date from earnings order by ticker, report_date")
    reports = {}
    for tk, rd in cur.fetchall():
        reports.setdefault(tk, []).append(rd)

    # Point-in-time EPS for M4: each quarter carries its own reportDate, so what was knowable on a
    # past date is a prefix cut, not a guess. Period order and report order agree, so one bisect.
    cur.execute("""select f.ticker,
                          array_agg((h.value->>'reportDate')::date order by h.key desc)  as rds,
                          array_agg((h.value->>'epsActual')::double precision
                                    order by h.key desc)                                 as eps
                     from v_fundamentals_latest f,
                          lateral jsonb_each(coalesce(f.raw_doc->'Earnings'->'History','{}'::jsonb)) h
                    where h.value->>'epsActual' is not null
                      and h.value->>'reportDate' is not null
                    group by f.ticker""")
    eps = {}
    for tk, rds, vals in cur.fetchall():
        pairs = [(r, v) for r, v in zip(rds, vals) if r is not None and v is not None]
        if pairs:
            eps[tk] = (np.array([r.toordinal() for r, _ in pairs]), [v for _, v in pairs])

    return dict(wide=wide, industry=industry, bench=bench, spx=spx, gate_source=gate_source,
                reports=reports, eps=eps)


def eps_as_of(eps_entry, day):
    """The quarters already reported by `day`, newest first — a prefix cut on report date."""
    rds, vals = eps_entry
    # rds descends, so the first index whose report date is on or before `day` starts the slice.
    i = int(np.searchsorted(-rds, -day.toordinal(), side="left"))
    return vals[i:]


# =============================================================================== the weekly rank
def rank(frame, t, cols, arrays):
    """L1-M as `rank.py` builds it: M2 + M4, ranked by MCN, top 150 — same calls, same order.

    Gates and stops read current price; MCN reads windows ending 10 sessions ago (§3.2, "rank is
    calm; protection is real-time"). Both slices are 280 bars, so both are constant-cost.
    """
    O, H, L, C, A, V = (arrays[k] for k in ("open", "high", "low", "close", "adj", "vol"))
    lo_full, lo_mcn = max(0, t - TAIL + 1), max(0, t - T10 - TAIL + 1)
    hi_mcn = t - T10 + 1
    if hi_mcn <= lo_mcn:
        return None

    # ---- L0 liquidity, evaluated on the bars of the day. Not a §3.2 rule: it is the census, and
    # it is what makes a delisted name leave the universe on the day its bars stop.
    close_t = C[t]
    live = ~np.isnan(close_t)
    nbars = (~np.isnan(C[max(0, t - 251):t + 1])).sum(axis=0)
    addv = np.nanmedian((C[max(0, t - 49):t + 1] * V[max(0, t - 49):t + 1]), axis=0)
    eff = live & (nbars >= 210) & (close_t >= 5) & (addv >= 10_000_000)
    idx = np.where(eff)[0]
    if len(idx) < 30:
        return None

    quality, atr_pct, dryup, near_high = {}, {}, {}, {}
    m2, bases, group_returns = {}, {}, {}
    for j in idx:
        tk = cols[j]
        cl_f, hi_f, lo_f = C[lo_full:t + 1, j], H[lo_full:t + 1, j], L[lo_full:t + 1, j]
        if np.isnan(cl_f).any():
            continue                                     # a hole in the window is not a verdict
        ac, hh, ll, cc, vv = (X[lo_mcn:hi_mcn, j] for X in (A, H, L, C, V))

        m2[tk] = sg.trend_template(cl_f)
        bases[tk] = sg.base_scan(hi_f, lo_f, cl_f)
        quality[tk] = sg.momentum_quality(ac)
        subs = sg.setup_proximity(hh, ll, cc, vv)
        atr_pct[tk], dryup[tk], near_high[tk] = subs["atr_pct"], subs["dryup"], subs["near_high"]
        ind = frame["industry"].get(tk)
        if ind and len(ac) >= 126 and ac[-126] > 0:
            group_returns.setdefault(ind, []).append(float(ac[-1]) / float(ac[-126]) - 1)

    ranked = sorted(quality)
    if not ranked:
        return None
    groups = sorted(group_returns)
    group_mean = {g: float(np.nanmean(group_returns[g])) for g in groups}
    group_pct = dict(zip(groups, sg.pct_rank([group_mean[g] for g in groups])))
    q_p = dict(zip(ranked, sg.pct_rank([quality[tk] for tk in ranked])))
    d_p = dict(zip(ranked, sg.pct_rank([dryup[tk] for tk in ranked])))
    x_p = dict(zip(ranked, sg.pct_rank([near_high[tk] for tk in ranked])))

    day = frame["dates"][t]
    out, m4_known = {}, 0
    for tk in ranked:
        setup = float(np.nanmean([atr_pct[tk], d_p[tk], x_p[tk]]))
        ind = frame["industry"].get(tk)
        grp = group_pct.get(ind, 50.0) if ind else 50.0
        score = sg.mcn(q_p[tk], setup, grp)
        entry = frame["eps"].get(tk)
        if entry is not None:
            m4 = sg.m4_acceleration(eps_as_of(entry, day))["passes"]
            m4_known += 1
        else:
            m4 = None                       # unknown is not a pass; §3.3 never guesses a component
        out[tk] = dict(mcn=score, m2=bool(m2[tk]), m4=m4, base=bases[tk])

    # L1-M = M2 and M4 pass, ranked by MCN, top 150 (§3.2). An unknown M4 is not a pass.
    eligible = [tk for tk in out if out[tk]["m2"] and out[tk]["m4"] is True
                and out[tk]["mcn"] == out[tk]["mcn"]]
    l1m = sorted(eligible, key=lambda tk: -out[tk]["mcn"])[:150]
    return dict(scored=out, l1m=l1m, evaluated=len(ranked), m4_known=m4_known)


# =============================================================================== the simulation
def simulate(frame, cfg):
    """The day loop. Pure: no database, no clock — `tests/test_backtest_engine.py` runs it on
    hand-built bars, which is the only way to assert what the engine refuses to do."""
    dates, cols = frame["dates"], frame["cols"]
    arrays = frame["arrays"]
    O, H, L, C, A, V = (arrays[k] for k in ("open", "high", "low", "close", "adj", "vol"))
    col = {tk: j for j, tk in enumerate(cols)}
    n = len(dates)

    # the 50 sessions *before* each day — the breakout day is the test, never its own baseline
    v50 = pd.DataFrame(V).shift(1).rolling(50, min_periods=25).mean().values

    gate_weeks, gate_states = _gate_series(frame["spx"])

    nav = cash = cfg["start_nav"]
    book, trades, equity, pending = {}, [], [], {}
    fired, queue, conf = {}, None, dict(m4_evaluated=0, m4_known=0, blackout_decisions=0,
                                        blackout_known=0, rank_dates=0, entries=0,
                                        entries_refused_below_70=0, gap_no_fill=0)

    def spread(j, t):
        """§ WO-12: half-spread by ADDV bucket, per side. Wide names cost more to touch."""
        advv = np.nanmedian(C[max(0, t - 49):t + 1, j] * V[max(0, t - 49):t + 1, j])
        bps = cfg["spread_bps"][0] if advv >= cfg["addv_break"] else cfg["spread_bps"][1]
        return bps / 10_000.0

    def close_position(tk, day, price, reason, t, gross_price=None):
        p = book.pop(tk)
        j = col[tk]
        # Decisions ride raw prices, so the sleeve's P&L is price-only. The dividend the adjusted
        # series implies is measured and reported (`stats.dividend_bps`) rather than either banked
        # silently or forgotten — VOO's benchmark is total return, so this is the size of the
        # handicap we are giving it.
        adj_t, px_t = A[t, j], C[t, j]
        if np.isfinite(adj_t) and np.isfinite(px_t):
            total = sum(d * (adj_t / a) for d, _, a in p["lots"])
            dividend = total - sum(d * (px_t / e) for d, e, _ in p["lots"])
        else:
            dividend = 0.0
        proceeds = p["qty"] * price
        gross = p["qty"] * (gross_price if gross_price is not None else price)
        trades.append(dict(
            ticker=tk, entry_date=p["entry_date"], entry_price=p["invested"] / p["qty"],
            qty=p["qty"], exit_date=day, exit_price=price, mcn=p["mcn"], pivot=p["pivot"],
            initial_stop=p["init_stop"], size_pct=p["size"], pyramid_steps=p["step"],
            pnl_usd=proceeds - p["invested"], pnl_pct=proceeds / p["invested"] - 1,
            pnl_gross_usd=gross - p["gross_invested"],
            cost_usd=(gross - proceeds) + (p["invested"] - p["gross_invested"]),
            dividend_usd=dividend,
            bars_held=t - p["entry_idx"], max_favorable=p["mfe"], max_adverse=p["mae"],
            exit_reason=reason, confirmed=p["confirmed"]))
        return proceeds

    for t in range(WARMUP, n):
        day = dates[t]
        on = _gate_on(gate_weeks, gate_states, day)

        # ---- exits flagged at yesterday's close fill at this open (§5.1: the desk arms, the
        # morning executes). Only the stop is intraday, because the broker holds it.
        for tk, reason in list(pending.items()):
            pending.pop(tk)
            if tk not in book:
                continue
            j = col[tk]
            px = O[t, j]
            if np.isnan(px):
                px = C[t, j]
            if np.isnan(px):
                px = book[tk]["last_mark"]
            cash += close_position(tk, day, px * (1 - spread(j, t)), reason, t, gross_price=px)

        # ---- weekly re-rank (§3.0 cadence: M2 and M4 weekly, MCN weekly)
        if pd.Timestamp(day).weekday() == 4 or queue is None:
            got = rank(frame, t, cols, arrays)
            if got is not None:
                queue = got
                conf["rank_dates"] += 1
                conf["m4_evaluated"] += got["evaluated"]
                conf["m4_known"] += got["m4_known"]

        scored = (queue or {}).get("scored", {})

        # ---- what we hold: stops first, then the conclusions the law draws
        for tk in list(book):
            p, j = book[tk], col[tk]
            lo, hi, cl, op = L[t, j], H[t, j], C[t, j], O[t, j]

            if np.isnan(cl):
                p["stale"] += 1
                if p["stale"] >= DELISTED_AFTER:
                    cash += close_position(tk, day, p["last_mark"], "delisted", t,
                                           gross_price=p["last_mark"])
                continue
            p["stale"] = 0

            # the stop is a resting broker order: it fires intraday, and a gap fills at the open
            if p["stop"] is not None and lo <= p["stop"]:
                gapped = not np.isnan(op) and op < p["stop"]
                fill = op if gapped else p["stop"]
                cash += close_position(tk, day, fill * (1 - spread(j, t)),
                                       "gap" if gapped else "stop", t, gross_price=fill)
                continue

            p["hi_close"] = max(p["hi_close"], cl)
            p["mfe"] = max(p["mfe"], hi / p["avg_cost"] - 1)
            p["mae"] = min(p["mae"], lo / p["avg_cost"] - 1)

            # ---- §3.2 breakout confirmation, judged at EOD on the sessions since entry
            k = t - p["entry_idx"] + 1
            window = range(p["entry_idx"], min(p["entry_idx"] + sg.CONFIRM_SESSIONS, t + 1))
            state = sg.confirmation_state([V[i, j] for i in window],
                                          [v50[i, j] for i in window],
                                          closes=[C[i, j] for i in window],
                                          pivot=p["pivot"])
            p["confirmed"] = state["confirmed"]

            if not on:
                pending[tk] = "gate_off"                 # §3.3 crash protocol, acted next open
                continue
            if state["exit_next_open"]:
                pending[tk] = "unconfirmed"              # the hair-trigger — the only volume exit
                continue

            row = scored.get(tk)
            if row is not None and row["m2"] is False:
                pending[tk] = "template"
                continue
            if row is not None and row["mcn"] == row["mcn"] and row["mcn"] < cfg["mcn_exit"]:
                pending[tk] = "score"
                continue
            if sg.stalled_pyramid(pyramid_step=p["step"], sessions_held=k - 1):
                pending[tk] = "stalled"
                continue

            nxt = _next_report(frame["reports"].get(tk), day)
            if nxt is not None:
                conf["blackout_decisions"] += 1
                conf["blackout_known"] += 1
                if sg.trading_days_between(day, nxt) <= 1 and \
                        sg.holds_through_earnings(cl, p["avg_cost"], cushion=cfg["cushion"]) is False:
                    pending[tk] = "earnings"
                    continue
            else:
                conf["blackout_decisions"] += 1

            # ---- pyramid: adds arm only once confirmed, both limits at the ceiling (§3.2)
            if state["pyramid_armed"] and p["step"] < 3 and not _blacked_out(frame, tk, day):
                for order in sg.pyramid_orders(p["pivot"], ceiling=cfg["pyramid_ceiling"]):
                    if order["step"] <= p["step"] or hi < order["trigger"]:
                        continue
                    fill = max(order["trigger"], op if not np.isnan(op) else order["trigger"])
                    if fill > order["limit"]:
                        continue                          # a gap beyond +5% fills nothing
                    dollars = p["target"] * order["fraction"]
                    if cash < dollars:
                        continue
                    paid = dollars * (1 + spread(j, t))
                    cash -= paid
                    p["lots"].append((dollars, fill, A[t, j] if np.isfinite(A[t, j]) else fill))
                    p["qty"] += dollars / fill
                    p["invested"] += paid
                    p["gross_invested"] += dollars
                    p["avg_cost"] = p["invested"] / p["qty"]
                    p["step"] = order["step"]

            # ---- the stop ladder
            out = sg.ratchet_stop(closes=C[max(0, p["entry_idx"]):t + 1, j][
                                      ~np.isnan(C[max(0, p["entry_idx"]):t + 1, j])],
                                  avg_cost=p["avg_cost"], current_stop=p["stop"],
                                  highest_close=p["hi_close"], pyramid_step=p["step"])
            if out["stop"] is not None:
                p["stop"] = out["stop"]
            p["last_mark"] = cl

        # ---- entries. A resting GTC buy stop-limit at the pivot, judged daily (§3.2 M3 is a
        # daily trigger check — the pre-rewrite sim reused Friday's pivot all week).
        if on and queue and len(book) < cfg["max_names"]:
            exposure = sum(p["qty"] * (C[t, col[p["ticker"]]] if not np.isnan(C[t, col[p["ticker"]]])
                                       else p["last_mark"]) for p in book.values())
            for tk in queue["l1m"]:
                if tk in book or len(book) >= cfg["max_names"]:
                    continue
                row = scored[tk]
                if not sg.enterable(row["mcn"], floor=cfg["min_mcn"]):
                    conf["entries_refused_below_70"] += 1
                    continue
                j = col[tk]
                # The base is read on LAST NIGHT's bars, and today's session is what fills the
                # order resting at its pivot (§5.1). Scanning through today instead would mark the
                # base broken by the very breakout it is supposed to trigger — the scan says
                # "spent" the moment a high clears pivot x 1.005 — so nothing but marginal touches
                # could ever fill.
                a, b = max(0, t - TAIL), t
                base = sg.base_scan(H[a:b, j], L[a:b, j], C[a:b, j])
                if not base["valid"]:
                    continue
                pivot = base["pivot"]
                if fired.get(tk) == round(float(pivot), 4):
                    continue                              # this order already filled once
                if _blacked_out(frame, tk, day):
                    continue                              # §3.3: the wall cancels resting orders
                hi, op = H[t, j], O[t, j]
                if np.isnan(hi) or hi < pivot:
                    continue
                order = sg.entry_order(pivot, base["contraction_low"],
                                       limit_over=cfg["limit_over"], max_stop=cfg["max_stop"])
                fill = pivot if (np.isnan(op) or op <= pivot) else op
                if fill > order["limit"]:
                    conf["gap_no_fill"] += 1
                    continue                              # gapped through the limit — no fill
                size = sg.momentum_size(nav=nav, mcn_score=row["mcn"],
                                        stop_distance=order["stop_distance"])
                if not size:
                    continue
                target = size["size_pct"] * nav
                if exposure + target > cfg["sleeve_cap"] * nav:
                    continue
                dollars = target * order["fraction"]       # step 1 — 50%
                if cash < dollars * (1 + 0.01):
                    continue
                paid = dollars * (1 + spread(j, t))
                cash -= paid
                exposure += dollars
                fired[tk] = round(float(pivot), 4)
                conf["entries"] += 1
                book[tk] = dict(ticker=tk, lots=[(dollars, fill, A[t, j] if np.isfinite(A[t, j]) else fill)],
                                qty=dollars / fill, invested=paid, gross_invested=dollars,
                                avg_cost=paid / (dollars / fill), stop=order["stop"], pivot=pivot,
                                hi_close=fill, step=1, target=target, mcn=row["mcn"],
                                entry_date=day, entry_idx=t, init_stop=order["stop"],
                                size=size["size_pct"], mfe=0.0, mae=0.0, last_mark=fill,
                                confirmed=None, stale=0)

        # ---- mark
        held = 0.0
        for p in book.values():
            px = C[t, col[p["ticker"]]]
            if np.isnan(px):
                px = p["last_mark"]
            else:
                p["last_mark"] = px
            held += p["qty"] * px
        nav = cash + held
        equity.append((day, nav, held / nav if nav else 0.0, len(book),
                       "ON" if on else "OFF", frame["bench_by_day"].get(day)))

    for tk in list(book):
        j = col[tk]
        px = C[n - 1, j]
        cash += close_position(tk, dates[n - 1], px if not np.isnan(px) else book[tk]["last_mark"],
                               "end_of_test", n - 1)
    return trades, equity, conf


def _stamp(obj):
    """A short, stable digest of the config a run was decided by."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _gate_series(spx):
    """M1 for every week of the test, latched — `market_gate` carrying its own previous state.

    The rule returns one verdict for one moment and needs the prior state to latch, so the driver
    walks it forward week by week. The walking is the driver's job; the verdict is never the
    driver's job, which is why this calls §3.2's own function 520 times rather than reimplementing
    the comparison once.
    """
    dates, closes = list(spx.index), list(spx.values)
    weeks = sg.weekly_closes(dates, closes)
    ends, states, prev = [], [], None
    for i, (week_end, _) in enumerate(weeks):
        k = bisect.bisect_right(dates, week_end)
        try:
            out = sg.market_gate(dates[:k], closes[:k], previous=prev)
        except ValueError:
            continue                              # not yet 35 weekly closes — no verdict exists
        prev = out["state"]
        ends.append(week_end)
        states.append(prev)
    return ends, states


def _gate_on(ends, states, day):
    """The M1 decision in force — the most recent weekly verdict at or before `day` (§3.2 latch)."""
    i = bisect.bisect_right(ends, day) - 1
    return bool(i >= 0 and states[i] == "ON")


def _next_report(reports, day):
    if not reports:
        return None
    i = bisect.bisect_left(reports, day)
    return reports[i] if i < len(reports) else None


def _blacked_out(frame, ticker, day):
    """§3.3: no entries and no adds within 5 trading days of a scheduled report."""
    nxt = _next_report(frame["reports"].get(ticker), day)
    return nxt is not None and sg.in_blackout(day, nxt)


# =============================================================================== conformance
def conformance(conf, trades, equity):
    """Every §3.2/§3.3 clause the run claims to implement, and how much of the window had the data
    to enforce it. A green tick on a clause that was unenforceable for most of the test is the
    failure this table exists to end (learnings #19 — green is not a result)."""
    reasons = {t["exit_reason"] for t in trades}
    legal = {"stop", "gap", "gate_off", "unconfirmed", "template", "score", "earnings",
             "stalled", "delisted", "end_of_test"}
    cov = lambda a, b: (a / b) if b else None
    return [
        dict(clause="M1 latch — weekly, 30-week SMA", fn="signals.market_gate", coverage=1.0),
        dict(clause="M2 trend template — six conditions", fn="signals.trend_template", coverage=1.0),
        dict(clause="M3 base detection, checked daily", fn="signals.base_scan", coverage=1.0),
        dict(clause="M4 earnings acceleration", fn="signals.m4_acceleration",
             coverage=cov(conf["m4_known"], conf["m4_evaluated"])),
        dict(clause="MCN — three components, windows end t-10", fn="signals.mcn", coverage=1.0),
        dict(clause="Entry — GTC stop-limit, pivot / pivot+2%", fn="signals.entry_order", coverage=1.0),
        dict(clause="EOD confirmation, freeze at 50%, late window",
             fn="signals.confirmation_state", coverage=1.0),
        dict(clause="Pyramid +2%/+4%, both limits pivot x 1.05", fn="signals.pyramid_orders",
             coverage=1.0),
        dict(clause="Stops — initial, breakeven, 10% trail, euphoria", fn="signals.ratchet_stop",
             coverage=1.0),
        dict(clause="Exits — stop, template, MCN < 55", fn="driver",
             coverage=1.0, unknown_reasons=sorted(reasons - legal)),
        dict(clause="Earnings blackout — 5 trading days", fn="signals.in_blackout",
             coverage=cov(conf["blackout_known"], conf["blackout_decisions"])),
        dict(clause="Sizing — budget / stop distance", fn="signals.momentum_size", coverage=1.0),
        dict(clause="MCN < 70 never tickets", fn="signals.enterable", coverage=1.0,
             refused=conf["entries_refused_below_70"],
             violations=sum(1 for t in trades if t["mcn"] is not None and t["mcn"] < 70)),
        dict(clause="Stalled pyramid — 4 weeks", fn="signals.stalled_pyramid", coverage=1.0),
        dict(clause="Survivorship — delisted retained", fn="driver", coverage=1.0,
             delisted_exits=sum(1 for t in trades if t["exit_reason"] == "delisted")),
    ]


def summarise(trades, equity, frame, conf):
    eq = pd.DataFrame(equity, columns=["d", "nav", "exposure", "positions", "gate", "bench"])
    eq["d"] = pd.to_datetime(eq["d"])
    nav = eq.nav
    years = max((eq.d.iloc[-1] - eq.d.iloc[0]).days / 365.25, 1e-9)
    dd = nav / nav.cummax() - 1
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    b = eq.bench.dropna()
    bench_total = (b.iloc[-1] / b.iloc[0] - 1) if len(b) > 1 else None
    invested = sum(t["qty"] * t["entry_price"] for t in trades) or 1.0
    table = conformance(conf, trades, equity)
    return dict(
        start_date=eq.d.iloc[0].date(), end_date=eq.d.iloc[-1].date(), trading_days=len(eq),
        start_nav=float(nav.iloc[0]), end_nav=float(nav.iloc[-1]),
        total_return=float(nav.iloc[-1] / nav.iloc[0] - 1),
        cagr=float((nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1),
        max_drawdown=float(dd.min()), max_dd_date=eq.d.iloc[int(dd.idxmin())].date(),
        trades=len(trades), wins=len(wins),
        win_rate=(len(wins) / len(trades)) if trades else None,
        avg_win=float(np.mean([t["pnl_pct"] for t in wins])) if wins else None,
        avg_loss=float(np.mean([t["pnl_pct"] for t in losses])) if losses else None,
        expectancy=float(np.mean([t["pnl_pct"] for t in trades])) if trades else None,
        avg_exposure=float(eq.exposure.mean()),
        avg_hold_days=float(np.mean([t["bars_held"] for t in trades])) if trades else None,
        benchmark_return=float(bench_total) if bench_total is not None else None,
        benchmark_cagr=float((1 + bench_total) ** (1 / years) - 1) if bench_total is not None else None,
        stats=dict(
            benchmark=BENCH, gate_source=frame["gate_source"], currency="USD",
            conformance=table,
            conformance_ok=all(c.get("coverage") not in (None, 0) for c in table)
                           and not any(c.get("unknown_reasons") for c in table)
                           and not any(c.get("violations") for c in table),
            exits={r: sum(1 for t in trades if t["exit_reason"] == r)
                   for r in sorted({t["exit_reason"] for t in trades})},
            cost_usd=float(sum(t["cost_usd"] for t in trades)),
            expectancy_gross=float(np.mean([t["pnl_gross_usd"] / (t["qty"] * t["entry_price"])
                                            for t in trades])) if trades else None,
            dividend_bps=float(10_000 * sum(t["dividend_usd"] for t in trades) / invested)
                         if trades else None,
            days_gate_on=int((eq.gate == "ON").sum()), days_gate_off=int((eq.gate == "OFF").sum()),
            pct_time_invested=float((eq.positions > 0).mean()),
            best=max((t["pnl_pct"] for t in trades), default=None),
            worst=min((t["pnl_pct"] for t in trades), default=None),
            diagnostics=conf,
            biases=["vendor serves the current version of a past statement (restatements)",
                    "industry mappings are today's",
                    "L0 census rebuilt from stored bars — names never ingested are still absent"]),
    )


# =============================================================================== entry point
def main():
    with connect() as conn:
        with Heartbeat(conn, "backtest") as hb:
            with conn.cursor() as cur:
                frame = load(cur)
                # The SAME config rows the nightly reads, spelled the same way. Inventing
                # `momentum_min_mcn` here would have read a row that does not exist, fallen
                # through to a default, and measured a threshold nobody set — learnings #21,
                # which this repo has already paid for once (`score_thresholds.enter` was
                # decorative for weeks because the code asked for `enterable`).
                thresholds = config(cur, "score_thresholds", {}) or {}
                ceilings = config(cur, "sleeve_ceiling", {"momentum": 0.40}) or {}
                cfg = dict(start_nav=START_NAV,
                           max_names=int(config(cur, "momentum_max_names", 4)),
                           sleeve_cap=float(ceilings.get("momentum", 0.40)),
                           min_mcn=float(thresholds.get("enter", 70)),
                           mcn_exit=float(thresholds.get("hold", 55)),
                           cushion=float(config(cur, "holdthrough_cushion", 1.08)),
                           max_stop=0.08, limit_over=0.02, pyramid_ceiling=1.05,
                           spread_bps=(5.0, 15.0), addv_break=50_000_000.0)
                # Behaviour lives in the database as well as in git, so the run stamps what it
                # ran under. A config change with no re-test is then a visible condition rather
                # than a silent one (Phase 5 of the backtest plan).
                config_stamp = _stamp(dict(score_thresholds=thresholds, sleeve_ceiling=ceilings,
                                           max_names=cfg["max_names"], cushion=cfg["cushion"]))

            wide = frame.pop("wide")
            index = list(wide["close"].index)
            if START_DATE:
                index = [d for d in index if str(d) >= START_DATE]
            if END_DATE:
                index = [d for d in index if str(d) <= END_DATE]
            sub = {k: v.loc[index] for k, v in wide.items()}
            frame["dates"] = index
            frame["cols"] = list(sub["close"].columns)
            frame["arrays"] = {k: v.values.astype(float) for k, v in sub.items()}
            frame["bench_by_day"] = {d: float(v) for d, v in frame["bench"].items()}

            hb.detail.update(tickers=len(frame["cols"]), bars=len(index),
                             benchmark=BENCH, gate_source=frame["gate_source"])
            print(f"backtest {VARIANT}: {len(frame['cols'])} tickers x {len(index)} bars "
                  f"| bench {BENCH} | gate {frame['gate_source']}")

            trades, equity, conf = simulate(frame, cfg)
            summary = summarise(trades, equity, frame, conf)
            print(f"  {summary['trades']} trades | CAGR {summary['cagr']:.1%} "
                  f"vs {BENCH} {summary['benchmark_cagr'] or 0:.1%} | "
                  f"maxDD {summary['max_drawdown']:.1%} | "
                  f"conformance {'OK' if summary['stats']['conformance_ok'] else 'FAILED'}")
            for c in summary["stats"]["conformance"]:
                if c.get("coverage") is not None and c["coverage"] < 1.0:
                    print(f"    coverage {c['coverage']:.0%} — {c['clause']}")

            if not dry():
                params = dict(variant=VARIANT, law_stamp=LAW_STAMP, currency="USD",
                              config_stamp=config_stamp,
                              benchmark=BENCH, start_nav=START_NAV, warmup=WARMUP,
                              costs=dict(commission_per_trade=0.0, fx_fee_per_side=0.0,
                                         half_spread_bps=dict(deep=cfg["spread_bps"][0],
                                                              thin=cfg["spread_bps"][1]),
                                         addv_break=cfg["addv_break"]),
                              max_names=cfg["max_names"], sleeve_cap=cfg["sleeve_cap"],
                              min_mcn=cfg["min_mcn"])
                with conn.cursor() as cur:
                    cur.execute("""insert into backtest_runs(label,params,start_date,end_date,
                          trading_days,start_nav,end_nav,total_return,cagr,max_drawdown,max_dd_date,
                          trades,wins,win_rate,avg_win,avg_loss,expectancy,avg_exposure,
                          avg_hold_days,benchmark_return,benchmark_cagr,stats)
                        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        returning id""",
                        (LABEL, json.dumps(params),
                         summary["start_date"], summary["end_date"], summary["trading_days"],
                         summary["start_nav"], summary["end_nav"], summary["total_return"],
                         summary["cagr"], summary["max_drawdown"], summary["max_dd_date"],
                         summary["trades"], summary["wins"], summary["win_rate"],
                         summary["avg_win"], summary["avg_loss"], summary["expectancy"],
                         summary["avg_exposure"], summary["avg_hold_days"],
                         summary["benchmark_return"], summary["benchmark_cagr"],
                         json.dumps(summary["stats"], default=str)))
                    rid = cur.fetchone()[0]
                    cur.executemany("""insert into backtest_trades(run_id,ticker,entry_date,
                          entry_price,qty,exit_date,exit_price,mcn,pivot,initial_stop,size_pct,
                          pyramid_steps,pnl_cad,pnl_pct,bars_held,max_favorable,max_adverse,
                          exit_reason)
                        values (%(run_id)s,%(ticker)s,%(entry_date)s,%(entry_price)s,%(qty)s,
                          %(exit_date)s,%(exit_price)s,%(mcn)s,%(pivot)s,%(initial_stop)s,
                          %(size_pct)s,%(pyramid_steps)s,%(pnl_usd)s,%(pnl_pct)s,%(bars_held)s,
                          %(max_favorable)s,%(max_adverse)s,%(exit_reason)s)""",
                        [{**t, "run_id": rid} for t in trades])
                    cur.executemany("""insert into backtest_equity(run_id,d,nav,exposure,positions,
                                         gate,benchmark) values (%s,%s,%s,%s,%s,%s,%s)""",
                        [(rid, d, nv, e, p, g, None if bch is None or
                          (isinstance(bch, float) and np.isnan(bch)) else bch)
                         for d, nv, e, p, g, bch in equity])
                conn.commit()
                hb.detail["run_id"] = rid

            hb.rows = len(trades) + len(equity)
            hb.detail.update({k: v for k, v in summary.items() if k != "stats"})
            hb.detail["exits"] = summary["stats"]["exits"]
            hb.detail["conformance_ok"] = summary["stats"]["conformance_ok"]
            if not summary["stats"]["conformance_ok"]:
                hb.amber("conformance table has a failing clause — see stats.conformance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
