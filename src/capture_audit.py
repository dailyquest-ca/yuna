"""capture_audit — did the arm actually buy the decade's winners?

Run 55 asked the question summary statistics cannot answer: *we know the return, but did we own
the names that produced the window's returns at all?* The answer for A2 was no, and it was not
marginal — six of the ten biggest buy-and-hold winners were never entered once in nine years, and
NVDA was held for three days at a loss. No headline number said so. Return, win rate, expectancy
and drawdown were all consistent with a working arm; only the name-by-name ledger showed that the
arm never saw the names it was built to hold.

That audit was done by hand, for one run. This is the same audit as a reusable instrument, so the
question gets asked of every arm rather than of the one that happened to arouse suspicion.

**It reads run outputs, never engine internals.** Everything it needs is in `backtest_trades`,
`backtest_runs` and `prices`, so it works on any run in the ledger regardless of which engine
revision produced it — including runs 54/55/56, and including whatever the corrected A2 becomes.

**It reports; it never gates.** Capture is a diagnostic, not a pass bar. The E-series pass bars are
§2.5 of the work order and they live in the report, not here. This exits non-zero only when it
cannot do its job — an unknown run, or a window with no price coverage.

    python src/capture_audit.py 56                     # the ten biggest winners vs what 56 traded
    python src/capture_audit.py 56 --top 25
    python src/capture_audit.py 56 --min-price 5 --min-addv 10e6   # E3's floors, opted into
    python src/capture_audit.py 56 --json

The eligibility flags are **off by default and opt-in on purpose.** E3's centre spec floors the
universe at price >= $5 and ADDV >= $10M, but those are that arm's parameters, not this tool's; an
audit that silently applied one arm's floors to another arm's run would be measuring the wrong
population. Pass them when auditing an arm that declares them.
"""
import argparse, json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from db import connect


# ------------------------------------------------------------------ the pure half (no database)
def audit(names, trades, top_n=10, min_bars=None, min_price=None, min_addv=None):
    """Rank the window's buy-and-hold winners and report what the run did with each.

    `names`  — ticker -> dict(ret, bars, first_d, last_d, addv, med_close). One row per name with
               price coverage in the window; `ret` is total return on the adjusted close.
    `trades` — the run's rows: dicts of ticker, pnl, bars_held.

    Returns the winners table, the aggregate capture summary, and what the run bought instead.
    """
    eligible = {}
    for tk, s in names.items():
        if s.get("ret") is None:
            continue                                    # single bar, or no usable price pair
        if min_bars is not None and (s.get("bars") or 0) < min_bars:
            continue
        if min_price is not None and (s.get("med_close") or 0) < min_price:
            continue
        if min_addv is not None and (s.get("addv") or 0) < min_addv:
            continue
        eligible[tk] = s

    by_ticker = {}
    for t in trades:
        b = by_ticker.setdefault(t["ticker"], {"n": 0, "held": 0, "pnl": 0.0, "held_known": 0})
        b["n"] += 1
        b["pnl"] += float(t.get("pnl") or 0.0)
        if t.get("bars_held") is not None:
            b["held"] += int(t["bars_held"])
            b["held_known"] += 1

    ranked = sorted(eligible.items(), key=lambda kv: -kv[1]["ret"])[:top_n]
    winners = []
    for tk, s in ranked:
        b = by_ticker.get(tk)
        winners.append(dict(
            ticker=tk, buy_hold=s["ret"], bars=s.get("bars"),
            trades=(b["n"] if b else 0),
            # averaged over the trades that recorded a hold, so a null never reads as a zero-day hold
            avg_hold=(b["held"] / b["held_known"] if b and b["held_known"] else None),
            pnl=(b["pnl"] if b else None),
            captured=bool(b)))

    missed = [w for w in winners if w["trades"] == 0]
    # P&L earned on the winners the arm did reach — the other half of "did we capture them".
    # A name entered and scratched is captured by presence and missed by outcome; both are shown.
    touched = [w for w in winners if w["trades"]]
    summary = dict(
        top_n=len(winners),
        never_entered=len(missed),
        never_entered_tickers=[w["ticker"] for w in missed],
        capture_rate=(1 - len(missed) / len(winners)) if winners else None,
        pnl_on_winners=sum(w["pnl"] for w in touched) if touched else 0.0,
        pnl_total=sum(b["pnl"] for b in by_ticker.values()),
        names_traded=len(by_ticker),
        trades=len(trades),
        eligible_names=len(eligible))

    bought = sorted(by_ticker.items(), key=lambda kv: (-kv[1]["n"], kv[0]))[:top_n]
    instead = [dict(ticker=tk,
                    trades=b["n"],
                    pnl=b["pnl"],
                    buy_hold=(eligible[tk]["ret"] if tk in eligible else None))
               for tk, b in bought]
    return dict(winners=winners, summary=summary, bought_instead=instead)


# ------------------------------------------------------------------------------ the database half
def load_run(cur, run_id):
    cur.execute("""select id, label, params, start_date, end_date, trades
                     from backtest_runs where id = %s""", (run_id,))
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"capture_audit: no run {run_id} in backtest_runs")
    return dict(zip([d.name for d in cur.description], row))


def load_names(cur, start, end):
    """Per-name window aggregates, computed in Postgres — nine years of bars for the whole census
    is a million rows, and none of them need to cross the wire.

    Buy-and-hold is measured on the ADJUSTED close, so it is total return: dividends and splits are
    in the series, which is what makes it comparable to VOO's total return under §2.1. ADDV is
    adj_close x volume for the reason the engine gives at its own L0 filter — `volume` is already
    split-adjusted, so the split factors cancel there and do not cancel against a raw close.
    """
    excl = ""
    cur.execute("select to_regclass('public.universe_excluded') is not null")
    if cur.fetchone()[0]:                    # only on engine revisions that define it
        excl = " and u.ticker not in (select ticker from universe_excluded)"
    cur.execute(f"""
        select p.ticker,
               count(*)                                                        as bars,
               min(p.d)                                                        as first_d,
               max(p.d)                                                        as last_d,
               (array_agg(coalesce(p.adj_close, p.close) order by p.d))[1]     as first_px,
               (array_agg(coalesce(p.adj_close, p.close) order by p.d desc))[1] as last_px,
               avg(coalesce(p.adj_close, p.close) * p.volume)                  as addv,
               percentile_cont(0.5) within group (order by p.close)            as med_close
          from prices p join universe u on u.ticker = p.ticker
         where p.d between %s and %s and u.kind = 'stock'
           and coalesce(p.adj_close, p.close) is not null{excl}
         group by p.ticker""", (start, end))
    out = {}
    for tk, bars, first_d, last_d, first_px, last_px, addv, med in cur.fetchall():
        ret = (float(last_px) / float(first_px) - 1) if first_px and last_px and bars > 1 else None
        out[tk] = dict(ret=ret, bars=bars, first_d=first_d, last_d=last_d,
                       addv=float(addv or 0), med_close=float(med or 0))
    return out


def load_trades(cur, run_id):
    # `pnl_cad` is the column's historical name; the E-series runs are USD (WO §Basis, "no FX").
    cur.execute("""select ticker, pnl_cad, bars_held from backtest_trades where run_id = %s""",
                (run_id,))
    return [dict(ticker=tk, pnl=pnl, bars_held=held) for tk, pnl, held in cur.fetchall()]


# ----------------------------------------------------------------------------------- presentation
def pct(v):
    return "—" if v is None else f"{v:+,.1%}"


def render(run, res, top_n):
    w, s = res["winners"], res["summary"]
    label = (run.get("params") or {}).get("variant") or run.get("label") or "—"
    out = [f"# capture audit — run {run['id']} ({label})",
           f"window {run['start_date']} → {run['end_date']} · "
           f"{s['eligible_names']} names with price coverage · "
           f"{s['trades']} trades across {s['names_traded']} names", ""]

    out.append(f"## the {len(w)} biggest buy-and-hold winners of the window")
    out.append("| Name | Buy & hold | Trades | Avg hold | P&L |")
    out.append("|---|---|---|---|---|")
    for r in w:
        hold = "—" if r["avg_hold"] is None else f"{r['avg_hold']:.0f}d"
        pnl = "—" if r["pnl"] is None else f"{r['pnl']:+,.0f}"
        name = f"**{r['ticker']}**" if not r["captured"] else r["ticker"]
        out.append(f"| {name} | {pct(r['buy_hold'])} | {r['trades']} | {hold} | {pnl} |")

    cap = "—" if s["capture_rate"] is None else f"{s['capture_rate']:.0%}"
    out += ["", f"**Capture: {cap}** — {s['never_entered']} of {s['top_n']} never entered"
                + (f" ({', '.join(s['never_entered_tickers'])})" if s["never_entered_tickers"] else "")
                + ".",
            f"P&L on the winners reached: {s['pnl_on_winners']:+,.0f} · "
            f"P&L across all names: {s['pnl_total']:+,.0f}.", ""]

    out.append(f"## what it bought instead (top {top_n} by trade count)")
    out.append("| Name | Trades | P&L | Buy & hold |")
    out.append("|---|---|---|---|")
    for r in res["bought_instead"]:
        out.append(f"| {r['ticker']} | {r['trades']} | {r['pnl']:+,.0f} | {pct(r['buy_hold'])} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="capture audit for a backtest run")
    ap.add_argument("run_id", type=int)
    ap.add_argument("--top", type=int, default=10, help="winners to rank (default 10, as run 55)")
    ap.add_argument("--min-bars", type=float, default=None,
                    help="drop names with fewer bars in the window (default: no filter)")
    ap.add_argument("--min-price", type=float, default=None,
                    help="drop names whose MEDIAN close is below this — a coarse window-aggregate "
                         "proxy for the engine's point-in-time floor (default: no filter)")
    ap.add_argument("--min-addv", type=float, default=None,
                    help="drop names whose mean adjusted dollar volume is below this — same "
                         "coarse-proxy caveat (default: no filter)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    with connect() as conn:
        with conn.cursor() as cur:
            run = load_run(cur, a.run_id)
            names = load_names(cur, run["start_date"], run["end_date"])
            trades = load_trades(cur, a.run_id)
    if not names:
        raise SystemExit(f"capture_audit: no price coverage in "
                         f"{run['start_date']} → {run['end_date']}")

    res = audit(names, trades, top_n=a.top, min_bars=a.min_bars,
                min_price=a.min_price, min_addv=a.min_addv)
    if a.json:
        print(json.dumps(dict(run_id=run["id"], start=str(run["start_date"]),
                              end=str(run["end_date"]), **res), indent=2, default=str))
    else:
        print(render(run, res, a.top))


if __name__ == "__main__":
    main()
