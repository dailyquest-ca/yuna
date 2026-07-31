"""backtest — Phase E. Run the momentum sleeve forward over our own bar history.

The plan is explicit (§4.8) that only the momentum side can be tested honestly: it needs
adjusted prices and nothing else. The compounder side cannot, because we hold exactly one
fundamentals snapshot per name and using today's filing at a past date is the first of the
two classic sins. So this simulates L0 → L1-M → L2 → L3 for momentum only, and the
compounder pipeline stays forward-validated by the shadow book.

Known biases, stated up front rather than buried in the result:

  * SURVIVORSHIP. The L0 census is today's listings. Names that delisted inside the window
    are absent, so the tape we test on is the tape that survived. This flatters everything.
  * NO M4. Point-in-time quarterly EPS is not stored, so the earnings-acceleration gate is
    off and L1-M is wider here than it would be live.
  * NO EARNINGS BLACKOUT. Historical report dates are not stored either, so entries that
    §3.3 would have blocked are taken here.
  * WARM-UP. The trend template needs 221 bars and the 52-week window needs 252, so the
    first tradeable day is ~280 bars in — roughly the last two years of a three-year window.
  * FILLS are modelled, not observed: a stop-limit fills at the pivot unless the day opened
    above it, in which case it fills at the open, and not at all above the limit. Slippage
    beyond that, and FX conversion cost, are not charged.

Everything else — M1's latch, the trend template, the base scan, MCN with its t−10 windows,
the pyramid, the 8% cap, the ratchet, the euphoria rule, the sleeve ceiling — is the same
arithmetic the live jobs run.
"""
import os, sys, json, math, datetime as dt
import numpy as np
import pandas as pd
import psycopg
from db import connect, config, dry, Heartbeat

START_NAV = float(os.environ.get("START_NAV", "200754.38"))
LABEL = os.environ.get("LABEL", "momentum v1")
WARMUP = 280

# ---- variant knobs. Defaults reproduce the plan exactly; every deviation is a hypothesis
# about the friction the baseline exposed, not a change to §3.2, which is FINAL.
VOL_MODE = os.environ.get("VOL_MODE", "fill_then_exit")   # fill_then_exit (§5.1) | confirm_first
BREAKEVEN_STEP = int(os.environ.get("BREAKEVEN_STEP", "3"))   # §3.2: breakeven at full size
MCN_EXIT = float(os.environ.get("MCN_EXIT", "55"))            # §3.3 exit-review threshold
MIN_HOLD = int(os.environ.get("MIN_HOLD_DAYS", "0"))          # §1: one-week intended hold


# ------------------------------------------------------------------ data
def load(cur):
    cur.execute("""select p.ticker, p.d, p.open, p.high, p.low, p.close, p.adj_close, p.volume
                   from prices p join universe u on u.ticker = p.ticker
                   where u.kind='stock' and u.status='active' and (u.in_l0 or u.is_holding)
                     and u.ticker like '%.US'
                   order by p.d""")
    df = pd.DataFrame(cur.fetchall(),
                      columns=["ticker", "d", "open", "high", "low", "close", "adj", "vol"])
    for c in ("open", "high", "low", "close", "adj", "vol"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["adj"] = df["adj"].fillna(df["close"])
    wide = {c: df.pivot(index="d", columns="ticker", values=c).sort_index()
            for c in ("open", "high", "low", "close", "adj", "vol")}
    cur.execute("select ticker, industry from universe where kind='stock'")
    ind = {t: i for t, i in cur.fetchall()}
    cur.execute("select d, close from prices where ticker='GSPC.INDX' order by d")
    spx = pd.Series({d: float(c) for d, c in cur.fetchall()}).sort_index()
    return wide, ind, spx


def m1_series(spx):
    """The Weinstein gate, resolved daily by carrying the latest weekly decision forward."""
    s = pd.Series(spx.values, index=pd.to_datetime(spx.index))
    weekly = s.resample("W-FRI").last().dropna()
    sma = weekly.rolling(30).mean()
    state, out, prev = None, {}, None
    for i, (d, px) in enumerate(weekly.items()):
        if i < 33 or pd.isna(sma.iloc[i]):
            out[d] = None; continue
        now, four = sma.iloc[i], sma.iloc[i - 4]
        if prev is None:
            state = "ON" if (px > now and now >= four) else "OFF"
        elif prev == "ON":
            state = "OFF" if px < now else "ON"          # latch: only the opposite trigger flips
        else:
            state = "ON" if (px > now and now >= four) else "OFF"
        out[d] = state; prev = state
    return pd.Series(out).sort_index()


def gate_on(m1, day):
    """The gate in force on `day` — the most recent Friday decision at or before it."""
    prior = m1.loc[:pd.Timestamp(day)]
    return (prior.iloc[-1] == "ON") if len(prior) and prior.iloc[-1] else False


def pct_rank(a):
    """Cross-sectional percentile 0..100, NaN-safe."""
    v = np.asarray(a, dtype=float)
    out = np.full(v.shape, np.nan)
    ok = ~np.isnan(v)
    n = ok.sum()
    if n > 1:
        out[ok] = 100.0 * v[ok].argsort().argsort() / (n - 1)
    elif n == 1:
        out[ok] = 50.0
    return out


# ------------------------------------------------------------------ weekly rank
def rank_week(w, t, ind):
    """Everything weekly-rank computes, as of bar index t. Returns a DataFrame of candidates."""
    C, H, L, V, A = (w[k].iloc[:t + 1] for k in ("close", "high", "low", "vol", "adj"))
    close, high, low, vol, adj = C.values, H.values, L.values, V.values, A.values
    cols = np.array(w["close"].columns)

    live = ~np.isnan(close[-1])
    nbars = (~np.isnan(close)).sum(axis=0)
    addv = np.nanmedian((close * vol)[-50:], axis=0)
    eff = live & (nbars >= 126) & (close[-1] >= 5) & (addv >= 10_000_000) & (nbars >= 210)
    if eff.sum() < 30:
        return None

    idx = np.where(eff)[0]
    T10 = 10
    a = adj[:-T10, idx]; c = close[:-T10, idx]; h = high[:-T10, idx]
    l = low[:-T10, idx]; v = vol[:-T10, idx]

    # momentum quality — 90d exp regression of log price, annualised slope x R2 / 90d vol
    y = np.log(a[-90:])
    x = np.arange(90.0)
    xc = x - x.mean()
    slope = (xc[:, None] * (y - y.mean(axis=0))).sum(axis=0) / (xc ** 2).sum()
    yhat = slope * xc[:, None] + y.mean(axis=0)
    ss_res = ((y - yhat) ** 2).sum(axis=0)
    ss_tot = ((y - y.mean(axis=0)) ** 2).sum(axis=0)
    r2 = np.clip(1 - ss_res / np.where(ss_tot == 0, 1e-12, ss_tot), 0, 1)
    vol90 = np.std(np.diff(np.log(a[-91:]), axis=0), axis=0)
    mq = slope * 252.0 * r2 / np.where(vol90 == 0, 1e-9, vol90)

    # setup proximity — four equal sub-scores
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = pd.DataFrame(tr).rolling(14, min_periods=8).mean().values
    hist = atr[-252:]
    s_atr = 100.0 - 100.0 * np.nanmean(hist <= atr[-1], axis=0)
    dd_r = 1 - np.min(c[-20:], axis=0) / np.max(c[-20:], axis=0)
    dd_p = 1 - np.min(c[-40:-20], axis=0) / np.max(c[-40:-20], axis=0)
    s_pull = dd_p - dd_r
    v50 = np.mean(v[-50:], axis=0)
    s_dry = -np.mean(v[-10:], axis=0) / np.where(v50 == 0, 1e-9, v50)
    hi52 = np.max(c[-252:], axis=0)
    s_prox = c[-1] / hi52
    setup = np.nanmean(np.vstack([s_atr, pct_rank(s_pull), pct_rank(s_dry), pct_rank(s_prox)]), axis=0)

    # industry group strength — equal-weight 6-month group return, percentile across groups
    ret6 = a[-1] / a[-126] - 1
    tick = cols[idx]
    gser = pd.Series(ret6, index=[ind.get(t_) for t_ in tick])
    gmean = gser.groupby(level=0).mean()
    gpct = pd.Series(pct_rank(gmean.values), index=gmean.index)
    grp = np.array([gpct.get(ind.get(t_), 50.0) if ind.get(t_) else 50.0 for t_ in tick])

    mcn = np.nanmean(np.vstack([pct_rank(mq), setup, grp]), axis=0)

    # trend template at the current price
    cc = close[:, idx]
    s50 = np.nanmean(cc[-50:], axis=0); s150 = np.nanmean(cc[-150:], axis=0)
    s200 = np.nanmean(cc[-200:], axis=0); s200_21 = np.nanmean(cc[-221:-21], axis=0)
    lo52 = np.nanmin(cc[-252:], axis=0); hh52 = np.nanmax(cc[-252:], axis=0); px = cc[-1]
    m2 = ((px > s150) & (px > s200) & (s150 > s200) & (s200 > s200_21) & (px > s50)
          & (px >= lo52 * 1.30) & (px >= hh52 * 0.75))

    # base scan — pivot is the highest high of the base, base is peak..today
    hh, ll = high[:, idx], low[:, idx]
    look = min(120, hh.shape[0])
    seg_h, seg_l = hh[-look:], ll[-look:]
    p = np.nanargmax(seg_h, axis=0)
    pivot = seg_h[p, np.arange(len(p))]
    blen = look - p
    depth = np.array([(pivot[j] - np.nanmin(seg_l[p[j]:, j])) / pivot[j] for j in range(len(p))])
    clow = np.nanmin(ll[-10:], axis=0)
    valid = (blen >= 25) & (depth <= 0.25) & (px <= pivot * 1.005)

    out = pd.DataFrame(dict(ticker=tick, mcn=mcn, m2=m2, valid=valid, pivot=pivot,
                            depth=depth, blen=blen, clow=clow, px=px,
                            stop=np.maximum(clow, pivot * 0.92)))
    l1m = out[out.m2].sort_values("mcn", ascending=False).head(150)
    return out.set_index("ticker"), l1m


# ------------------------------------------------------------------ simulation
def run(w, ind, m1, hb):
    dates = list(w["close"].index)
    O, H, L, C, V = (w[k] for k in ("open", "high", "low", "close", "vol"))
    # prior 50 days: the breakout day is the test, not the baseline. min_periods matters —
    # without it one missing bar anywhere in the window returns NaN and silently fails the gate.
    v50 = V.shift(1).rolling(50, min_periods=25).mean()

    budgets = {70: 0.007, 85: 0.009}          # §3.2 steady-state risk budgets
    MAXSTOP, CEIL, MAXN, BAND = 0.08, 0.40, 4, 0.12

    nav, cash = START_NAV, START_NAV
    book, trades, equity = {}, [], []
    queue = pd.DataFrame()
    fired = {}                               # ticker -> pivot already filled; re-arms on a new base
    diag = dict(weeks=0, l1m=0, valid=0, touched=0, no_fill_gap=0, no_volume=0,
                no_room=0, taken=0, days_slots_free=0, already_fired=0)

    for t in range(WARMUP, len(dates)):
        day = dates[t]
        on = gate_on(m1, day)

        # ---- weekly re-rank (Fridays), exactly as weekly-rank does it
        if pd.Timestamp(day).weekday() == 4 or queue.empty:
            got = rank_week(w, t, ind)
            if got is not None:
                scored, queue = got
                diag["weeks"] += 1
                diag["l1m"] += len(queue); diag["valid"] += int(queue.valid.sum())
                # §3.2 lists exactly three exits: the stop, the trend template failing, and
                # MCN < 55. Falling out of the top 150 is NOT one of them — L1-M is a
                # candidate list, not a holding rule, and treating it as one ejected every
                # position within days and made the sleeve untradeable.
                for tk in list(book):
                    if tk not in scored.index:
                        continue                            # no longer scoreable; leave it to the stop
                    row = scored.loc[tk]
                    px = C[tk].iloc[t]
                    if np.isnan(px):
                        continue
                    if t - book[tk]["entry_idx"] < MIN_HOLD:
                        continue                            # §1 minimum intended hold; stops exempt
                    if not bool(row.m2):
                        cash += book[tk]["qty"] * px
                        close_trade(book, trades, tk, day, px, "trend template fail", t)
                    elif float(row.mcn) < MCN_EXIT:
                        cash += book[tk]["qty"] * px
                        close_trade(book, trades, tk, day, px, "MCN < 55", t)

        # ---- gate off: the sleeve goes to cash (§3.3 crash protocol)
        if not on and book:
            for tk in list(book):
                px = O[tk].iloc[t]
                if np.isnan(px): px = C[tk].iloc[t]
                if not np.isnan(px):
                    cash += book[tk]["qty"] * px
                    close_trade(book, trades, tk, day, px, "market gate OFF", t)

        # ---- §5.1: a breakout that did not carry 1.4x volume is a failed breakout. The
        # broker order has already filled overnight, so the brief instructs an exit at the
        # next open — not a refusal to enter, which is what the first run modelled.
        for tk in list(book):
            p = book[tk]
            if p["vol_ok"] or p["entry_idx"] == t:
                continue
            px = O[tk].iloc[t]
            if np.isnan(px):
                px = C[tk].iloc[t]
            if not np.isnan(px):
                cash += p["qty"] * px
                close_trade(book, trades, tk, day, px, "volume unconfirmed", t)

        # ---- stops and trails on what we hold
        for tk in list(book):
            p = book[tk]
            lo, hi, cl, op = L[tk].iloc[t], H[tk].iloc[t], C[tk].iloc[t], O[tk].iloc[t]
            if np.isnan(cl):
                continue
            if lo <= p["stop"]:
                fill = min(p["stop"], op) if not np.isnan(op) else p["stop"]
                cash += p["qty"] * fill
                close_trade(book, trades, tk, day, fill, "stop", t)
                continue
            p["hi_close"] = max(p["hi_close"], cl)
            p["mfe"] = max(p["mfe"], hi / p["entry"] - 1)
            p["mae"] = min(p["mae"], lo / p["entry"] - 1)

            # pyramid — 50 / 25 / 25 at the pivot, +2.5%, +4.5%
            for step, mult in ((2, 1.025), (3, 1.045)):
                if p["vol_ok"] and p["step"] == step - 1 and hi >= p["pivot"] * mult and on:
                    add_cost = p["target_cad"] * 0.25
                    if cash >= add_cost:
                        fill = max(p["pivot"] * mult, op if not np.isnan(op) else 0)
                        q = add_cost / fill
                        p["entry"] = (p["entry"] * p["qty"] + fill * q) / (p["qty"] + q)
                        p["qty"] += q; cash -= add_cost; p["step"] = step

            # ratchet — breakeven at full size, 10% trail past +15%, 5% under euphoria
            win = cl / p["entry"] - 1
            hist = C[tk].iloc[max(0, t - 49):t + 1].dropna()
            euph = False
            if len(hist) >= 50:
                euph = cl > hist.mean() + 2 * hist.std()
            cand = p["stop"]
            if euph:
                cand = max(cand, p["hi_close"] * 0.95)
            elif win >= 0.15:
                cand = max(cand, p["hi_close"] * 0.90)
            elif p["step"] >= BREAKEVEN_STEP:
                cand = max(cand, p["entry"])
            p["stop"] = max(p["stop"], cand)               # ratchets up, never down

        # ---- entries
        if on and len(book) < MAXN and not queue.empty:
            diag["days_slots_free"] += 1
            exposure = sum(p["qty"] * C[p["ticker"]].iloc[t] for p in book.values()
                           if not np.isnan(C[p["ticker"]].iloc[t]))
            for _, r in queue[queue.valid].sort_values("mcn", ascending=False).iterrows():
                tk = r.ticker
                if tk in book or len(book) >= MAXN:
                    continue
                if fired.get(tk) == round(float(r.pivot), 4):
                    diag["already_fired"] += 1
                    continue                                # this order already filled once
                op = O[tk].iloc[t]
                if VOL_MODE == "confirm_first":
                    # wait for yesterday to CLOSE above the pivot on 1.4x volume, then buy this
                    # open. Costs a day of drift; never pays for a breakout that did not carry.
                    pc, pv, pv5 = C[tk].iloc[t - 1], V[tk].iloc[t - 1], v50[tk].iloc[t - 1]
                    if np.isnan(pc) or pc < r.pivot:
                        continue
                    diag["touched"] += 1
                    if np.isnan(pv) or np.isnan(pv5) or pv < 1.4 * pv5:
                        diag["no_volume"] += 1
                        continue
                    vol_ok = True
                    fill = op if not np.isnan(op) else pc
                    if fill > r.pivot * 1.05:               # §3.2 gap-up tolerance
                        diag["no_fill_gap"] += 1
                        continue
                else:
                    hi = H[tk].iloc[t]
                    if np.isnan(hi) or hi < r.pivot:
                        continue
                    diag["touched"] += 1
                    limit = r.pivot * 1.02
                    fill = r.pivot if (np.isnan(op) or op <= r.pivot) else op
                    if fill > limit:
                        diag["no_fill_gap"] += 1
                        continue                            # gapped through the limit — no fill
                    vv, v5 = V[tk].iloc[t], v50[tk].iloc[t]
                    vol_ok = bool(not np.isnan(vv) and not np.isnan(v5) and vv >= 1.4 * v5)
                    if not vol_ok:
                        diag["no_volume"] += 1              # filled anyway; exits at tomorrow's open
                stop = max(r.clow, fill * (1 - MAXSTOP))
                dist = max((fill - stop) / fill, 1e-4)
                budget = budgets[85] if r.mcn >= 85 else budgets[70]
                size = min(budget / dist, BAND)
                target = size * nav
                if exposure + target > CEIL * nav or cash < target * 0.5:
                    diag["no_room"] += 1
                    continue
                diag["taken"] += 1
                fired[tk] = round(float(r.pivot), 4)
                first = target * 0.5                        # pyramid step 1
                q = first / fill
                cash -= first
                exposure += first
                book[tk] = dict(ticker=tk, entry=fill, qty=q, stop=stop, pivot=r.pivot,
                                hi_close=fill, step=1, target_cad=target, mcn=float(r.mcn),
                                entry_date=day, entry_idx=t, init_stop=stop, size=size,
                                mfe=0.0, mae=0.0, last_mark=fill, vol_ok=vol_ok)

        # ---- mark
        held = 0.0
        for p in book.values():
            px = C[p["ticker"]].iloc[t]
            if np.isnan(px):
                px = p["last_mark"]                        # carry, never drop to zero
            else:
                p["last_mark"] = px
            held += p["qty"] * px
        nav = cash + held
        b = w["close"]["SPY.US"].iloc[t] if "SPY.US" in w["close"].columns else np.nan
        equity.append((day, nav, held / nav if nav else 0, len(book), "ON" if on else "OFF", b))

    # liquidate whatever is open at the end, so every trade has an exit
    t = len(dates) - 1
    for tk in list(book):
        px = C[tk].iloc[t]
        if not np.isnan(px):
            cash += book[tk]["qty"] * px
            close_trade(book, trades, tk, dates[t], px, "end of test", t)
    return trades, equity, diag


def close_trade(book, trades, tk, day, price, reason, t):
    p = book.pop(tk)
    pnl = (price - p["entry"]) * p["qty"]
    trades.append(dict(ticker=tk, entry_date=p["entry_date"], entry_price=p["entry"],
                       qty=p["qty"], exit_date=day, exit_price=price, mcn=p["mcn"],
                       pivot=p["pivot"], initial_stop=p["init_stop"], size_pct=p["size"],
                       pyramid_steps=p["step"], pnl_cad=pnl,
                       pnl_pct=price / p["entry"] - 1, bars_held=t - p["entry_idx"],
                       max_favorable=p["mfe"], max_adverse=p["mae"], exit_reason=reason))


# ------------------------------------------------------------------ stats + persistence
def summarise(trades, equity, spx):
    eq = pd.DataFrame(equity, columns=["d", "nav", "exposure", "positions", "gate", "bench"])
    eq["d"] = pd.to_datetime(eq["d"])
    nav = eq.nav
    years = max((eq.d.iloc[-1] - eq.d.iloc[0]).days / 365.25, 1e-9)
    total = nav.iloc[-1] / nav.iloc[0] - 1
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1
    peak = nav.cummax()
    dd = nav / peak - 1
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    s = pd.Series(spx.values, index=pd.to_datetime(spx.index))
    s = s.loc[eq.d.iloc[0]:eq.d.iloc[-1]]
    bench_total = (s.iloc[-1] / s.iloc[0] - 1) if len(s) > 1 else None
    return dict(
        start_date=eq.d.iloc[0].date(), end_date=eq.d.iloc[-1].date(), trading_days=len(eq),
        start_nav=float(nav.iloc[0]), end_nav=float(nav.iloc[-1]),
        total_return=float(total), cagr=float(cagr),
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
            exits={r: sum(1 for t in trades if t["exit_reason"] == r)
                   for r in {t["exit_reason"] for t in trades}},
            days_gate_on=int((eq.gate == "ON").sum()), days_gate_off=int((eq.gate == "OFF").sum()),
            pct_time_invested=float((eq.positions > 0).mean()),
            best=max((t["pnl_pct"] for t in trades), default=None),
            worst=min((t["pnl_pct"] for t in trades), default=None),
            biases=["survivorship — L0 is today's listings only",
                    "no M4 gate (point-in-time EPS not stored)",
                    "no earnings blackout (historical report dates not stored)",
                    "fills modelled at the pivot; no slippage or FX cost charged"]),
    )


def main():
    with connect() as conn:
        with Heartbeat(conn, "backtest") as hb:
            with conn.cursor() as cur:
                w, ind, spx = load(cur)
            hb.detail["tickers"] = int(w["close"].shape[1])
            hb.detail["bars"] = int(w["close"].shape[0])
            print(f"backtest: {w['close'].shape[1]} tickers x {w['close'].shape[0]} bars")
            m1 = m1_series(spx)
            trades, equity, diag = run(w, ind, m1, hb)
            hb.detail["diagnostics"] = diag
            print("  diagnostics:", diag)
            summary = summarise(trades, equity, spx)
            summary["stats"]["diagnostics"] = diag
            print(f"  {summary['trades']} trades | CAGR {summary['cagr']:.1%} | "
                  f"maxDD {summary['max_drawdown']:.1%} | win {summary['win_rate'] or 0:.0%}")
            if not dry():
                with conn.cursor() as cur:
                    cur.execute("""insert into backtest_runs(label,params,start_date,end_date,trading_days,
                          start_nav,end_nav,total_return,cagr,max_drawdown,max_dd_date,trades,wins,
                          win_rate,avg_win,avg_loss,expectancy,avg_exposure,avg_hold_days,
                          benchmark_return,benchmark_cagr,stats)
                        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        returning id""",
                        (LABEL, json.dumps(dict(start_nav=START_NAV, max_names=4, sleeve_cap=0.40,
                                                budgets={"70": 0.007, "85": 0.009}, warmup=WARMUP)),
                         summary["start_date"], summary["end_date"], summary["trading_days"],
                         summary["start_nav"], summary["end_nav"], summary["total_return"],
                         summary["cagr"], summary["max_drawdown"], summary["max_dd_date"],
                         summary["trades"], summary["wins"], summary["win_rate"],
                         summary["avg_win"], summary["avg_loss"], summary["expectancy"],
                         summary["avg_exposure"], summary["avg_hold_days"],
                         summary["benchmark_return"], summary["benchmark_cagr"],
                         json.dumps(summary["stats"], default=str)))
                    rid = cur.fetchone()[0]
                    cur.executemany("""insert into backtest_trades(run_id,ticker,entry_date,entry_price,
                          qty,exit_date,exit_price,mcn,pivot,initial_stop,size_pct,pyramid_steps,
                          pnl_cad,pnl_pct,bars_held,max_favorable,max_adverse,exit_reason)
                        values (%(run_id)s,%(ticker)s,%(entry_date)s,%(entry_price)s,%(qty)s,
                          %(exit_date)s,%(exit_price)s,%(mcn)s,%(pivot)s,%(initial_stop)s,%(size_pct)s,
                          %(pyramid_steps)s,%(pnl_cad)s,%(pnl_pct)s,%(bars_held)s,%(max_favorable)s,
                          %(max_adverse)s,%(exit_reason)s)""",
                        [{**t, "run_id": rid} for t in trades])
                    cur.executemany("""insert into backtest_equity(run_id,d,nav,exposure,positions,gate,benchmark)
                                       values (%s,%s,%s,%s,%s,%s,%s)""",
                        [(rid, d, n, e, p, g, None if (b is None or (isinstance(b, float) and np.isnan(b))) else b)
                         for d, n, e, p, g, b in equity])
                conn.commit()
                hb.detail["run_id"] = rid
            hb.rows = len(trades) + len(equity)
            hb.detail.update({k: v for k, v in summary.items() if k != "stats"})
            hb.detail["exits"] = summary["stats"]["exits"]
    return 0


if __name__ == "__main__":
    sys.exit(main())
