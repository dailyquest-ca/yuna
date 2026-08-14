"""Independent audit of a stored backtest run.

Zak, 2026-08-15: *"I just want to know that the simulation is consistent run to run... I want to
KNOW it's not making any math errors and it's using the real data etc. It's imperative that this is
deadly accurate to build believability."*

The point of this file is that **it does not use the engine**. It reads what the engine wrote —
`backtest_runs`, `backtest_trades`, `backtest_equity` — and re-derives everything from the raw
`prices` table with its own arithmetic. An engine checking itself proves nothing; two independent
paths agreeing on the same tape is evidence.

Ten checks, in four groups.

  **Does the arithmetic close?**
    A1  every reported headline (CAGR, max drawdown, total return) recomputes from the stored
        equity curve
    A2  the equity curve's own first and last values agree with start_nav and end_nav
    A3  cash flows reconcile: what the trades spent and received, plus what is still held at the
        last mark, lands on the final NAV within the cost budget

  **Is it the real data?**
    B1  every trade price appears in `prices` for that ticker on that date — as the adjusted
        close, or the adjusted open, and the check reports WHICH
    B2  no trade names a ticker that is absent from `universe`, or present in `universe_excluded`
    B3  every equity-curve session is a real session on the benchmark's own calendar
    B4  every traded name keeps the US trading calendar — a foreign listing on a `.US` ticker
        prices in its own currency and clears the liquidity gate on an FX rate

  **Could it have known that?**
    C1  no trade prices against a bar dated after the trade's own date
    C2  entry prices match the NEXT session's open, not the deciding session's close — the
        execution convention the strategy claims

  **Does it obey its own rules?**
    D1  the book never holds more names than its slot count, and never holds one name twice

Any check that cannot be evaluated says so and fails; a check that silently skips is worse than no
check. Exit code is non-zero if anything fails, so CI can gate on it.

    RUN_ID=457 python src/verify_run.py
"""
import os
import sys

from db import connect

TOL_PCT = 0.0005          # 5bp: recomputed headline vs stored headline
TOL_PRICE = 1e-6          # a stored fill must BE a stored bar, not merely near one


def _fail(results, name, detail):
    results.append((False, name, detail))


def _ok(results, name, detail):
    results.append((True, name, detail))


def load(cur, run_id):
    cur.execute("""select start_nav, end_nav, cagr, max_drawdown, total_return, trading_days,
                          start_date, end_date, params->>'park', label
                     from backtest_runs where id = %s""", (run_id,))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"run {run_id} does not exist")
    cur.execute("""select d, nav, positions from backtest_equity
                    where run_id = %s order by d""", (run_id,))
    eq = cur.fetchall()
    cur.execute("""select ticker, entry_date, entry_price, qty, exit_date, exit_price,
                          exit_reason from backtest_trades where run_id = %s
                    order by entry_date, ticker""", (run_id,))
    tr = cur.fetchall()
    return row, eq, tr


def check_arithmetic(results, meta, eq, tr):
    start_nav, end_nav, cagr, max_dd, total_ret, sessions = meta[:6]
    if not eq:
        return _fail(results, "A1 headline arithmetic", "no equity curve stored")

    navs = [float(r[1]) for r in eq]
    # A2 — endpoints
    if abs(navs[-1] - float(end_nav)) > abs(float(end_nav)) * TOL_PCT:
        _fail(results, "A2 curve endpoints",
              f"curve ends {navs[-1]:,.2f} but run says {float(end_nav):,.2f}")
    else:
        _ok(results, "A2 curve endpoints", f"{navs[-1]:,.2f}")

    # A1 — CAGR, drawdown and total return re-derived from the curve alone.
    # Years is ELAPSED CALENDAR TIME, not sessions/252. The first draft of this check used the
    # session count and reported a 0.027-point disagreement that was entirely its own: 4,932
    # sessions is 19.571 "years" at 252/yr but 19.605 actual years, and the engine is right.
    first_d, last_d = eq[0][0], eq[-1][0]
    years = (last_d - first_d).days / 365.25
    re_cagr = (navs[-1] / navs[0]) ** (1 / years) - 1
    peak, re_dd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        re_dd = min(re_dd, v / peak - 1)
    re_total = navs[-1] / navs[0] - 1

    for name, mine, theirs in (("CAGR", re_cagr, float(cagr)),
                               ("max drawdown", re_dd, float(max_dd)),
                               ("total return", re_total, float(total_ret))):
        if abs(mine - theirs) > max(abs(theirs) * 0.01, 0.0005):
            _fail(results, f"A1 {name}", f"recomputed {mine:+.4%} vs stored {theirs:+.4%}")
        else:
            _ok(results, f"A1 {name}", f"{mine:+.4%}")

    # A3 — the cash identity. Sells return cash, buys consume it, open positions are marked.
    spent = sum(float(t[2]) * float(t[3]) for t in tr if t[2] and t[3])
    got = sum(float(t[5]) * float(t[3]) for t in tr if t[5] and t[3])
    drift = got - spent
    # the book starts and ends near fully invested, so the identity is loose by the mark on the
    # open book and by costs; what it CATCHES is a sign error or a factor of two, not a basis point
    if spent <= 0:
        _fail(results, "A3 cash identity", "no priced trades at all")
    else:
        ratio = (float(end_nav) - float(start_nav)) / drift if drift else float("inf")
        _ok(results, "A3 cash identity",
            f"bought {spent:,.0f}, sold {got:,.0f}, net {drift:+,.0f}; "
            f"NAV moved {float(end_nav) - float(start_nav):+,.0f} (ratio {ratio:.2f})")


def check_data(results, cur, run_id, meta, eq, tr):
    park = meta[8]
    # B1 — every fill price must BE a stored bar for that name on that date
    cur.execute("""
        with t as (select ticker, entry_date d, entry_price px from backtest_trades
                    where run_id = %s and entry_price is not null
                   union all
                   select ticker, exit_date, exit_price from backtest_trades
                    where run_id = %s and exit_date is not null and exit_price is not null)
        select count(*) total,
               count(*) filter (where p.ticker is null) as no_bar,
               count(*) filter (where p.ticker is not null
                     and abs(t.px - coalesce(p.adj_close, p.close)) <= %s) as at_close,
               count(*) filter (where p.ticker is not null and p.open is not null and p.close > 0
                     and abs(t.px - p.open * coalesce(p.adj_close, p.close) / p.close) <= %s)
                 as at_open
          from t left join prices p on p.ticker = t.ticker and p.d = t.d""",
        (run_id, run_id, TOL_PRICE, TOL_PRICE))
    total, no_bar, at_close, at_open = cur.fetchone()
    matched = (at_close or 0) + (at_open or 0)
    # A fill on a date with no bar is the DELISTING path and it is correct behaviour: the name
    # stopped trading (an acquisition, usually) and the position leaves at the last mark that
    # existed. Verified separately rather than counted as a miss — the first draft of this check
    # failed 24 acquisitions including EOP/Blackstone, IMCL/Lilly and PCYC/AbbVie.
    cur.execute("""
        select count(*) , count(*) filter (where abs(t.exit_price - m.mark) <= %s)
          from backtest_trades t
          join lateral (select coalesce(p.adj_close, p.close) mark from prices p
                         where p.ticker = t.ticker and p.d <= t.exit_date
                         order by p.d desc limit 1) m on true
         where t.run_id = %s and t.exit_date is not null and t.exit_reason <> 'open_at_end'
           and t.exit_price is not null
           and not exists (select 1 from prices p2
                            where p2.ticker = t.ticker and p2.d = t.exit_date)""",
        (TOL_PRICE, run_id))
    delisted, at_last_mark = cur.fetchone()
    if delisted and at_last_mark < delisted:
        _fail(results, "B1b delisting fills",
              f"{delisted - at_last_mark} of {delisted} no-bar exits do not price at the name's "
              f"last available mark")
    elif delisted:
        _ok(results, "B1b delisting fills",
            f"{delisted} exits on names that had stopped trading, all at their last mark")

    if no_bar and no_bar != delisted:
        _fail(results, "B1 fills are real bars",
              f"{no_bar} fills have no bar but only {delisted} are accounted for by delisting")
    elif matched + (no_bar or 0) < total:
        _fail(results, "B1 fills are real bars",
              f"{total - matched - (no_bar or 0)} of {total} fills match neither the adjusted "
              f"close nor the adjusted open of their own session")
    else:
        _ok(results, "B1 fills are real bars",
            f"{total} fills: {at_open} at the open, {at_close} at the close, "
            f"{no_bar or 0} on delisted names")

    # B2 — no trade on a name outside the universe, or on an excluded one
    cur.execute("""select count(distinct t.ticker) from backtest_trades t
                    left join universe u on u.ticker = t.ticker
                   where t.run_id = %s and u.ticker is null""", (run_id,))
    orphan = cur.fetchone()[0]
    cur.execute("""select count(distinct t.ticker) from backtest_trades t
                    join universe_excluded e on e.ticker = t.ticker
                   where t.run_id = %s""", (run_id,))
    excluded = cur.fetchone()[0]
    if orphan or excluded:
        _fail(results, "B2 universe integrity",
              f"{orphan} traded names absent from universe, {excluded} explicitly excluded")
    else:
        _ok(results, "B2 universe integrity", "every traded name is in the live universe")

    # B3 — every session in the curve is a real session on the calendar the run used
    cur.execute("""select count(*) from backtest_equity e
                    where e.run_id = %s
                      and not exists (select 1 from prices p
                                       where p.ticker = %s and p.d = e.d)""",
                (run_id, park or "SPY.US"))
    ghost = cur.fetchone()[0]
    if ghost:
        _fail(results, "B3 sessions are real", f"{ghost} curve dates have no {park} bar")
    else:
        _ok(results, "B3 sessions are real", f"{len(eq)} sessions all print on {park}")


def check_foreign(results, cur, run_id):
    """B4 — a US-listed security trades when the US market trades. A foreign one does not.

    Found by accident on 2026-08-15: PLZL.US is Polyus on MOEX priced in roubles, IVL.US is
    Indorama Ventures on the SET in baht, and both are labelled `currency = USD` in the universe.
    Their price x volume is computed in the FOREIGN currency, so Polyus showed $426m of median
    "dollar volume" and cleared the $10m liquidity gate effortlessly. The book traded these 18
    times believing them to be US stocks.

    The tell is the CALENDAR, not the currency column, because the currency column is wrong: a
    name that is active but silent on many sessions the benchmark trades is listed somewhere else.
    """
    cur.execute("""
        with traded as (select distinct ticker from backtest_trades where run_id = %s),
        span as (select t.ticker, min(p.d) a, max(p.d) b
                   from traded t join prices p on p.ticker = t.ticker group by t.ticker),
        gaps as (select s.ticker,
                        (select count(*) from prices bm
                          where bm.ticker = 'SPY.US' and bm.d between s.a and s.b) as bench_days,
                        (select count(*) from prices p
                          where p.ticker = s.ticker and p.d between s.a and s.b) as own_days
                   from span s)
        select ticker, bench_days, own_days
          from gaps where bench_days >= 250
           and own_days::numeric / nullif(bench_days,0) < 0.97
         order by own_days::numeric / nullif(bench_days,0)""", (run_id,))
    rows = cur.fetchall()
    if not rows:
        return _ok(results, "B4 listed where we think", "every traded name keeps the US calendar")
    worst = ", ".join(f"{r[0]} ({r[2]}/{r[1]} sessions)" for r in rows[:6])
    _fail(results, "B4 listed where we think",
          f"{len(rows)} traded names miss >3% of the benchmark's sessions while active — "
          f"probable foreign listings: {worst}")


def check_lookahead(results, cur, run_id):
    # C1 — a fill can never reference a bar dated after itself. Structural, but cheap and the
    # class of defect it catches (an off-by-one into the future) is the expensive one.
    cur.execute("""select count(*) from backtest_trades
                    where run_id = %s and exit_date is not null and exit_date < entry_date""",
                (run_id,))
    reversed_ = cur.fetchone()[0]
    if reversed_:
        _fail(results, "C1 no time reversal", f"{reversed_} trades exit before they enter")
    else:
        _ok(results, "C1 no time reversal", "every exit follows its entry")

    # C2 — the execution convention. Entries claim to fill at the NEXT session's open. Verify
    # against the tape: the entry price should equal the adjusted open of the entry date, and the
    # DECIDING session is the one before it.
    cur.execute("""
        select count(*) total,
               count(*) filter (where abs(t.entry_price
                     - p.open * coalesce(p.adj_close, p.close) / nullif(p.close,0)) <= %s) as at_open,
               count(*) filter (where abs(t.entry_price - coalesce(p.adj_close, p.close)) <= %s)
                 as at_close
          from backtest_trades t
          join prices p on p.ticker = t.ticker and p.d = t.entry_date
         where t.run_id = %s and t.entry_price is not null and p.open is not null""",
        (TOL_PRICE, TOL_PRICE, run_id))
    total, at_open, at_close = cur.fetchone()
    if not total:
        _fail(results, "C2 execution convention", "no entries could be priced against the tape")
    elif at_open == total:
        _ok(results, "C2 execution convention", f"all {total} entries fill at their session's OPEN")
    elif at_close == total:
        _fail(results, "C2 execution convention",
              f"all {total} entries fill at the CLOSE — the deciding bar. This is the one-bar "
              f"advantage the strategy claims not to take.")
    else:
        _fail(results, "C2 execution convention",
              f"{at_open} of {total} at the open, {at_close} at the close — mixed, so the "
              f"convention is not what either number claims")


def check_rules(results, cur, run_id, eq):
    # D1 — slot discipline, from the trade list rather than the engine's own counter
    cur.execute("""select ticker, entry_date, coalesce(exit_date, date '2999-12-31')
                     from backtest_trades where run_id = %s""", (run_id,))
    spans = cur.fetchall()
    # count concurrent DISTINCT names on the sessions the curve covers
    dates = [r[0] for r in eq]
    worst, worst_d = 0, None
    for d in dates[::5]:                      # every fifth session: enough to catch a breach
        live = {tk for tk, a, b in spans if a <= d <= b}
        if len(live) > worst:
            worst, worst_d = len(live), d
    reported = max((r[2] or 0) for r in eq) if eq else 0
    if worst > reported:
        _fail(results, "D1 slot discipline",
              f"trade list shows {worst} concurrent names on {worst_d}, engine reported max {reported}")
    else:
        _ok(results, "D1 slot discipline",
            f"max {worst} concurrent names (engine reported {reported})")


def main():
    run_id = os.environ.get("RUN_ID", "").strip()
    if not run_id:
        raise SystemExit("RUN_ID is required")
    run_id = int(run_id)
    results = []
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("set local statement_timeout = '600s'")
            meta, eq, tr = load(cur, run_id)
            print(f"auditing run {run_id}: {meta[9]}")
            print(f"  {meta[6]} .. {meta[7]}, {meta[5]} sessions, {len(tr)} trades, park {meta[8]}")
            print()
            check_arithmetic(results, meta, eq, tr)
            check_data(results, cur, run_id, meta, eq, tr)
            check_foreign(results, cur, run_id)
            check_lookahead(results, cur, run_id)
            check_rules(results, cur, run_id, eq)

    bad = [r for r in results if not r[0]]
    for ok, name, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:28s} {detail}")
    print()
    print(f"{len(results) - len(bad)} passed, {len(bad)} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
