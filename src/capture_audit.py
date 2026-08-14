"""capture_audit — did the arm actually catch the moves it exists for?

Standing rule (docs/handoff-2026-08-13.md): **no arm's number is believed until a capture audit
runs.** Runs 54, 55 and 56 all passed their accounting invariants and produced plausible CAGRs,
and each was measuring something other than the specified arm. Four defects — a breakeven stop
hidden in the confirmation machine, an ungated entry door, A1's candidate pool, A1's candidate
order — and not one was visible in a summary statistic. The question that found every one was
"did it buy NVIDIA". This script asks that question mechanically, of every run.

Three parts, per the handoff:

  1. THE NET  — enumerate every large momentum push in the run's window, from the tape alone.
                What fraction did the arm enter at all?
  2. THE RIDE — for each push it caught, what share of the move did it keep? Entered near the
                start and held, or clipped after three days?
  3. THE JUNK — of everything it held, what share was neither a push nor caught one?

A PUSH is operationalized from the handoff's words ("name-months running +50%+ off a 252-high"):
a close strictly above the prior 252 of the name's own closes — the same test as
`signals.new_high_breakout` — whose level is then run up +50% before any close falls back below
it. A breakout that gives the level back first is a failed breakout, not a push. Episodes chain:
once a push completes, the next one for that name starts from the first new high after
completion, so a long trend counts once per +50% leg rather than once per new-high day. The
handoff's month bucketing is subsumed by that chaining; recorded as the one deviation (the
episode boundary question is exactly what the month unit was avoiding, and the chaining answers
it mechanically instead).

Eligibility at the breakout is the engine's own L0 census test, evaluated the way `rank()`
evaluates it — at least 210 of the name's own bars inside the last 252 union sessions, a raw
print of $5 or more, and a 50-union-session median dollar volume of $10M or more on the adjusted
series. A push in a name the census could never admit is not a catchable push.

The audit reads the market's pushes, NOT the arm's filtered view — no M2, no MCN, no market gate.
That is the point: the net measures the filters too.

    python src/capture_audit.py [run_id]     # defaults to the newest run; RUN_ID env also works

Writes `stats.capture_audit` on the run row (idempotent — same key, replaced) and prints the
table. DRY_RUN computes and prints but writes nothing. A crash records itself under the same key
before re-raising, because Actions logs are unreachable (learnings #13) and a failure nobody can
read is a failure that gets guessed at.
"""
import os
import sys
import json
import traceback
import datetime as dt

import numpy as np

from db import connect, dry

# The handoff's own numbers ("name-months running +50%+ off a 252-high"), and the engine's L0
# census floors exactly as rank() applies them — see src/backtest.py::rank.
PUSH_GAIN = 0.50
LOOKBACK = 252
L0_MIN_BARS = 210
L0_MIN_RAW = 5.0
L0_MIN_ADDV = 10_000_000.0
L0_ADDV_WINDOW = 50
TOP_N = 20                      # bounded detail in stats; stdout carries more


def run_row(cur, run_id=None):
    if run_id:
        cur.execute("""select id, label, start_date, end_date, params->>'hypothesis'
                         from backtest_runs where id = %s""", (run_id,))
    else:
        cur.execute("""select id, label, start_date, end_date, params->>'hypothesis'
                         from backtest_runs order by id desc limit 1""")
    row = cur.fetchone()
    if not row:
        raise RuntimeError("no backtest_runs row to audit")
    return dict(zip(("id", "label", "start_date", "end_date", "hypothesis"), row))


def load_positions(cur, run_id):
    """Trade rows grouped into positions. A trimmed position is several rows sharing a ticker and
    an entry date; its life runs to the last slice's exit and its P&L is the sum."""
    cur.execute("""select ticker, entry_date, exit_date, qty, entry_price, pnl_cad, exit_reason
                     from backtest_trades where run_id = %s order by ticker, entry_date""",
                (run_id,))
    positions = {}
    for tk, ed, xd, qty, ep, pnl, reason in cur.fetchall():
        key = (tk, ed)
        p = positions.setdefault(key, dict(ticker=tk, entry=ed, exit=xd, qty=0.0,
                                           entry_price=float(ep), pnl=0.0, open=False))
        p["qty"] += float(qty)
        # A leg still open at the end of the window has no realized P&L, and the ledger stores
        # NULL rather than a zero for exactly that reason. Coercing it crashed the audit; coercing
        # it to 0.0 would have been worse — an open winner would have read as a flat trade in the
        # capture arithmetic. It is counted as open and left out of the realized sum.
        if pnl is None:
            p["open"] = True
        else:
            p["pnl"] += float(pnl)
        if xd and (p["exit"] is None or xd > p["exit"]):
            p["exit"] = xd
    return list(positions.values())


def load_tape(cur, *, with_range=False, since=None, until=None):
    """The same census `backtest.load()` reads: US stocks, living and dead, minus the excluded.

    `with_range` appends high, low and open — the push study's ATR needs the bar's range and the
    concentrated arm's stop needs to know whether the session opened through it, and every reader
    must use the SAME census predicate or their universes silently drift.

    `since`/`until` bound the bars. WO-A9 added them because the 2005 backfill took this table from
    8.9M rows to 11.6M and the unbounded query started **timing out** — runs 391 and 392 both died
    on `canceling statement due to statement timeout`, in `load_tape`, before doing any work. A
    windowed test has no use for bars outside its window: the grid is built from the calendar's own
    sessions and the 252-session formation is taken from inside the window, so filtering here
    changes no result and cuts the query to the span actually read. Both default to None, which is
    the whole tape and the behaviour every existing caller gets.
    """
    extra = ", p.high, p.low, p.open" if with_range else ""
    bounds, args = "", []
    if since:
        bounds += " and p.d >= %s"
        args.append(since)
    if until:
        bounds += " and p.d <= %s"
        args.append(until)
    cur.execute(f"""select p.ticker, p.d, p.close, coalesce(p.adj_close, p.close), p.volume{extra}
                     from prices p join universe u on u.ticker = p.ticker
                    where u.kind = 'stock' and u.ticker like '%%.US'
                      and u.ticker not in (select ticker from universe_excluded){bounds}
                    order by p.ticker, p.d""", args)
    return cur.fetchall()


def episodes_for_name(dates_ord, upos, raw, adj, vol, *, start_ord, end_ord):
    """Every episode for one name, walking its own bars: the single definition the audit AND the
    push study share, so a lift measured by the study describes the same universe the audit
    counts. A second implementation of this walk is how the two would silently drift apart.

    `dates_ord`   the name's own sessions as ordinals, ascending
    `upos`        each session's position on the union date axis (for L0's calendar windows)

    Returns a list of episode dicts — kind 'push' (reached +50% before a close back below the
    level), 'failed' (gave the level back first), or 'unresolved' (the window ended mid-race) —
    each with own-bar indices `b` and, when resolved, `e`, plus the level, the ADDV at the
    breakout, and the gain (for a push, at completion; for a failure, the best close reached
    before it died — the size of the tease). Bars with a non-positive adjusted close were
    dropped by the caller (the vendor pads delisting tails with 0.0000 — learnings #33)."""
    n = len(adj)
    if n < LOOKBACK + 1:
        return []
    # prior-252-own-closes max, aligned so pm[i] covers adj[i-252 .. i-1] — the same window
    # signals.new_high_breakout reads. Strict > below, as the door has it.
    win_max = np.lib.stride_tricks.sliding_window_view(adj, LOOKBACK).max(axis=1)
    dv = adj * vol

    # the last own bar inside the run window: races are clipped here, not resolved by fiat
    idx_end = int(np.searchsorted(dates_ord, end_ord, side="right")) - 1
    if idx_end < LOOKBACK:
        return []

    out = []
    i = LOOKBACK
    while i <= idx_end:
        if dates_ord[i] < start_ord or not adj[i] > win_max[i - LOOKBACK]:
            i += 1
            continue
        # ---- L0 at the signal day, exactly as rank() computes it. Stated in the engine's own
        # polarity (>=), because with a NaN raw print `raw < 5` reads False and a name with no
        # price would sail through a floor written the other way round.
        bars_in_window = i - int(np.searchsorted(upos, upos[i] - (LOOKBACK - 1), side="left")) + 1
        k = int(np.searchsorted(upos, upos[i] - (L0_ADDV_WINDOW - 1), side="left"))
        addv = float(np.nanmedian(dv[k:i + 1])) if not np.all(np.isnan(dv[k:i + 1])) else np.nan
        eligible = (bars_in_window >= L0_MIN_BARS and raw[i] >= L0_MIN_RAW
                    and addv >= L0_MIN_ADDV)
        if not eligible:
            i += 1
            continue
        # ---- the race: +50% before a close back below the level
        level = float(adj[i])
        target = level * (1.0 + PUSH_GAIN)
        j = i + 1
        best = level
        outcome = None
        while j <= idx_end:
            c = adj[j]
            best = max(best, float(c))
            if c >= target:
                outcome = "push"
                break
            if c < level:
                outcome = "failed"
                break
            j += 1
        if outcome == "push":
            out.append(dict(kind="push", b=int(i), e=int(j), level=level, addv=addv,
                            gain=float(adj[j] / level - 1.0)))
            i = j + 1
        elif outcome == "failed":
            out.append(dict(kind="failed", b=int(i), e=int(j), level=level, addv=addv,
                            gain=float(best / level - 1.0)))
            i = j + 1
        else:
            out.append(dict(kind="unresolved", b=int(i), e=None, level=level, addv=addv,
                            gain=float(best / level - 1.0)))
            break
    return out


def pushes_for_name(dates_ord, upos, raw, adj, vol, *, start_ord, end_ord):
    """The audit's view of the shared walk: completed pushes, and a count of unresolved races."""
    eps = episodes_for_name(dates_ord, upos, raw, adj, vol,
                            start_ord=start_ord, end_ord=end_ord)
    pushes = [{k: ep[k] for k in ("b", "e", "level", "gain")} for ep in eps
              if ep["kind"] == "push"]
    return pushes, sum(1 for ep in eps if ep["kind"] == "unresolved")


def audit(run, positions, tape_rows):
    start_ord = run["start_date"].toordinal()
    end_ord = run["end_date"].toordinal()

    # union date axis — L0's bar-count and ADDV windows are calendar windows on it, so a name
    # that skipped sessions is judged the way the engine judges it, not by its own bar count
    all_dates = sorted({d for _, d, _, _, _ in tape_rows})
    union = np.array([d.toordinal() for d in all_dates], dtype=np.int64)

    by_pos = {}                    # ticker -> [(entry_ord, exit_ord, position)]
    for p in positions:
        by_pos.setdefault(p["ticker"], []).append(
            (p["entry"].toordinal(), (p["exit"] or run["end_date"]).toordinal(), p))

    pushes, total_unresolved = [], 0
    tk_dates, tk_raw, tk_adj, tk_vol = [], [], [], []
    current = None

    def flush():
        nonlocal total_unresolved
        if current is None or not tk_dates:
            return
        do = np.array(tk_dates, dtype=np.int64)
        adj = np.array(tk_adj, dtype=float)
        keep = adj > 0.0                                  # the vendor's 0.0000 delisting pad
        do, adj = do[keep], adj[keep]
        raw = np.array(tk_raw, dtype=float)[keep]
        vol = np.array(tk_vol, dtype=float)[keep]
        upos = np.searchsorted(union, do)
        got, unres = pushes_for_name(do, upos, raw, adj, vol,
                                     start_ord=start_ord, end_ord=end_ord)
        total_unresolved += unres
        for g in got:
            b_ord, e_ord = int(do[g["b"]]), int(do[g["e"]])
            overlapping = [p for eo, xo, p in by_pos.get(current, [])
                           if eo <= e_ord and xo >= b_ord]
            entry = dict(ticker=current,
                         b=dt.date.fromordinal(b_ord).isoformat(),
                         e=dt.date.fromordinal(e_ord).isoformat(),
                         level=round(g["level"], 4), gain=round(g["gain"], 4),
                         caught=bool(overlapping))
            if overlapping:
                first = min(overlapping, key=lambda p: p["entry"])
                close_e = float(adj[g["e"]])
                counterfactual = first["qty"] * (close_e - first["entry_price"])
                actual = sum(p["pnl"] for p in overlapping)
                # A push still being ridden at the end of the window has no realized P&L to
                # divide, and scoring it 0/counterfactual would report the best trades in the
                # book as the ones that kept none of their move.
                still_open = any(p["open"] for p in overlapping)
                entry.update(actual_pnl=round(actual, 2), open_at_end=still_open,
                             hold_to_end_pnl=(round(counterfactual, 2)
                                              if counterfactual > 0 else None),
                             ride_share=(round(actual / counterfactual, 4)
                                         if counterfactual > 0 and not still_open else None))
            pushes.append(entry)

    for tk, d, close, adj, vol in tape_rows:
        if tk != current:
            flush()
            current, tk_dates, tk_raw, tk_adj, tk_vol = tk, [], [], [], []
        tk_dates.append(d.toordinal())
        tk_raw.append(float(close) if close is not None else np.nan)
        tk_adj.append(float(adj) if adj is not None else 0.0)
        # NaN, not zero: the engine's nanmedian IGNORES a missing volume, and mapping NULL to 0
        # here would instead drag the median down — a different rule wearing the same name
        tk_vol.append(float(vol) if vol is not None else np.nan)
    flush()

    # ---- the three parts
    caught = [p for p in pushes if p["caught"]]
    net = dict(pushes=len(pushes), caught=len(caught),
               fraction=(len(caught) / len(pushes)) if pushes else None,
               unresolved_at_end=total_unresolved)

    rideable = [p for p in caught if p.get("ride_share") is not None]
    ride = dict(pushes_measurable=len(rideable),
                dollar_share=(round(sum(p["actual_pnl"] for p in rideable)
                                    / sum(p["hold_to_end_pnl"] for p in rideable), 4)
                              if rideable else None),
                median_share=(round(float(np.median([p["ride_share"] for p in rideable])), 4)
                              if rideable else None))

    push_windows = {}
    for p in pushes:
        push_windows.setdefault(p["ticker"], []).append(
            (dt.date.fromisoformat(p["b"]).toordinal(), dt.date.fromisoformat(p["e"]).toordinal()))
    junk_positions = [p for p in positions
                      if not any(b <= (p["exit"] or run["end_date"]).toordinal()
                                 and e >= p["entry"].toordinal()
                                 for b, e in push_windows.get(p["ticker"], ()))]
    junk = dict(positions=len(positions), junk=len(junk_positions),
                share=(len(junk_positions) / len(positions)) if positions else None,
                junk_pnl_usd=round(sum(p["pnl"] for p in junk_positions), 2))

    # ---- the "did it buy NVIDIA" tables, bounded
    missed = sorted((p for p in pushes if not p["caught"]), key=lambda p: -p["gain"])
    offenders = {}
    for p in pushes:
        o = offenders.setdefault(p["ticker"], dict(ticker=p["ticker"], pushes=0, caught=0,
                                                   best_gain=0.0))
        o["pushes"] += 1
        o["caught"] += bool(p["caught"])
        o["best_gain"] = max(o["best_gain"], p["gain"])
    worst_names = sorted((o for o in offenders.values() if o["caught"] < o["pushes"]),
                         key=lambda o: (o["caught"] - o["pushes"], -o["best_gain"]))

    return dict(
        definition=dict(
            push=f"close > prior {LOOKBACK} own closes, then +{PUSH_GAIN:.0%} before a close "
                 f"back below the level; episodes chain after completion",
            eligibility=f">= {L0_MIN_BARS} bars in the last {LOOKBACK} union sessions, raw close "
                        f">= ${L0_MIN_RAW:.0f}, {L0_ADDV_WINDOW}-session median dollar volume "
                        f">= ${L0_MIN_ADDV / 1e6:.0f}M at the breakout (rank()'s L0)",
            source="docs/handoff-2026-08-13.md",
            deviation="the handoff's month bucketing is subsumed by episode chaining"),
        window=[run["start_date"].isoformat(), run["end_date"].isoformat()],
        net=net, ride=ride, junk=junk,
        missed_top=[{k: p[k] for k in ("ticker", "b", "e", "gain")} for p in missed[:TOP_N]],
        caught_top=[{k: p.get(k) for k in ("ticker", "b", "e", "gain", "actual_pnl",
                                           "hold_to_end_pnl", "ride_share", "open_at_end")}
                    for p in sorted(caught, key=lambda p: -p["gain"])[:TOP_N]],
        worst_names=worst_names[:TOP_N])


def render(run, out):
    net, ride, junk = out["net"], out["ride"], out["junk"]
    lines = [f"### capture audit · run {run['id']} · `{run['label']}`",
             "",
             f"window {out['window'][0]} → {out['window'][1]} · "
             f"push = {out['definition']['push']}",
             "",
             f"**THE NET** — {net['caught']} of {net['pushes']} pushes entered "
             f"({net['fraction']:.1%})" if net["pushes"] else "**THE NET** — no pushes in window",
             f"**THE RIDE** — dollar share kept {ride['dollar_share']:.1%}, median "
             f"{ride['median_share']:.1%} across {ride['pushes_measurable']} caught pushes"
             if ride["dollar_share"] is not None else
             "**THE RIDE** — nothing caught, nothing to measure",
             f"**THE JUNK** — {junk['junk']} of {junk['positions']} positions "
             f"({junk['share']:.1%}) overlapped no push; their P&L ${junk['junk_pnl_usd']:,.0f}"
             if junk["positions"] else "**THE JUNK** — the run held nothing",
             ""]
    if net["unresolved_at_end"]:
        lines.append(f"{net['unresolved_at_end']} races unresolved when the window closed "
                     f"(neither +50% nor a failure) — counted in neither column")
    if out["missed_top"]:
        lines += ["", "largest pushes never entered:", "",
                  "| name | breakout | +50% reached | gain |", "|---|---|---|---:|"]
        lines += [f"| {p['ticker']} | {p['b']} | {p['e']} | {p['gain']:+.1%} |"
                  for p in out["missed_top"]]
    if out["caught_top"]:
        lines += ["", "largest pushes entered:", "",
                  "| name | breakout | +50% reached | gain | P&L | hold-to-end | share kept |",
                  "|---|---|---|---:|---:|---:|---:|"]
        for p in out["caught_top"]:
            share = ("still open" if p.get("open_at_end")
                     else f"{p['ride_share']:.0%}" if p.get("ride_share") is not None else "—")
            hold = f"${p['hold_to_end_pnl']:,.0f}" if p.get("hold_to_end_pnl") else "—"
            lines += [f"| {p['ticker']} | {p['b']} | {p['e']} | {p['gain']:+.1%} | "
                      f"${p['actual_pnl']:,.0f} | {hold} | {share} |"]
    return "\n".join(lines)


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 else (
        int(os.environ["RUN_ID"]) if os.environ.get("RUN_ID") else None)
    with connect() as conn:
        with conn.cursor() as cur:
            run = run_row(cur, want)
            try:
                positions = load_positions(cur, run["id"])
                tape = load_tape(cur)
                out = audit(run, positions, tape)
            except Exception:
                # Actions logs are unreachable (learnings #13); the run row is not. Record where
                # a reader will look, then die loudly — recording is not tolerating.
                cur.execute("""update backtest_runs
                                  set stats = jsonb_set(stats, '{capture_audit}', %s::jsonb)
                                where id = %s""",
                            (json.dumps(dict(error=traceback.format_exc())), run["id"]))
                conn.commit()
                raise

        report = render(run, out)
        print(report)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a") as fh:
                fh.write(report + "\n")

        if dry():
            print("\nDRY_RUN — nothing written")
            return 0
        with conn.cursor() as cur:
            cur.execute("""update backtest_runs
                              set stats = jsonb_set(stats, '{capture_audit}', %s::jsonb)
                            where id = %s""", (json.dumps(out), run["id"]))
        conn.commit()
        print(f"\nstats.capture_audit written on run {run['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
