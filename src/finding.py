"""finding — §2.5 applied to a stored run: may this number be called a finding?

The bars live in `src/bars.py` as pure functions; this is the driver its docstring promises. It
reads one run from `backtest_runs` / `backtest_trades` / `backtest_equity` and applies the
E-series' formal definition of "proven" (wo-e-series-2026-08-12 §2.5):

  (a) two cuts — the full window, and the Aug-2025 OOS cut (sessions from 2025-08-01, the plain
      reading of the work order's "Aug-2025");
  (b) winner-exclusion jackknife, ex-top-{1,3,5}. Arithmetic, and FLAGGED as such: it removes the
      winner's P&L but keeps the compounding the winner financed, so it flatters the ex-top-k
      figure — a claim that fails it would fail the honest version by more. The honest version of
      an exclusion is a re-run without the name, which is what the `e1` preset is for MU;
  (c) circular block bootstrap on the run's daily returns (63-session blocks, 10,000 draws,
      seed 0), bar: bootstrap-median CAGR above the benchmark's realized CAGR on the same cut;
  (d) deflated Sharpe against the logged E-series configuration count. Zak's 2026-08-12 ruling:
      the count runs FORWARD ONLY — trials are the ledger's runs carrying a `param_hash` (P1
      landed with the E-series), deduplicated by (param_hash, code_stamp). A run with no
      code_stamp counts as its own trial: 54/55/56 proved identical params can wrap three
      different engines, so sameness cannot be assumed where the code identity was never stamped.
      The DSR is computed on per-session terms — Sharpe and moments from the same daily return
      series — because mixing a daily Sharpe with per-trade moments would put two frequencies in
      one formula. (The work order says "the trade distribution's skew/kurtosis"; the Bailey-
      López de Prado expression is defined on the return series the Sharpe is measured on, and
      the daily series is where this family's violent right skew actually lives.)
  (e) costs — nothing to do here: the engine already prices §2.2's curve into every trade.

Also reported, because E1's question is asked against it: the 90/10 chassis counterfactual —
daily-rebalanced 0.9 x benchmark with the cash earning nothing. That construction reproduces the
recorded +222.10% on run 53's window to the basis point (validated 2026-08-13), so the same
arithmetic is used here rather than a second opinion.

    python src/finding.py [run_id]      # defaults to the newest run; RUN_ID env also works
    DD_BAR=-0.34                        # optional: the arm's declared drawdown kill bar (E3
                                        # cells declare -0.34; nothing is assumed when unset)

Writes `stats.bars_25` on the run row (idempotent) and prints the verdict. DRY_RUN computes and
prints but writes nothing. A crash records itself under the same key before re-raising, because
Actions logs are unreachable (learnings #13).
"""
import os
import sys
import json
import datetime as dt
import traceback

import numpy as np

import bars
from db import connect, dry

OOS_START = dt.date(2025, 8, 1)      # §2.5(a) "Aug-2025 OOS cut"


def fetch_run(cur, run_id=None):
    where = "where id = %s" if run_id else ""
    cur.execute(f"""select id, label, start_date, end_date, start_nav, total_return,
                           params->>'hypothesis', params->>'param_hash', params->>'code_stamp'
                      from backtest_runs {where} order by id desc limit 1""",
                (run_id,) if run_id else ())
    row = cur.fetchone()
    if not row:
        raise RuntimeError("no backtest_runs row to score")
    return dict(zip(("id", "label", "start_date", "end_date", "start_nav", "total_return",
                     "hypothesis", "param_hash", "code_stamp"), row))


def fetch_equity(cur, run_id):
    cur.execute("""select d, nav, benchmark from backtest_equity
                    where run_id = %s order by d""", (run_id,))
    rows = cur.fetchall()
    if not rows:
        raise RuntimeError(f"run {run_id} has no equity path — nothing to score")
    return rows


def fetch_trade_pnls(cur, run_id):
    """Every trade's P&L and the date it landed on, for the jackknife.

    Rows with a NULL P&L are legs an arm never closed. An arm that writes them is one whose
    ledger is incomplete — the position is in the equity curve's return and absent from the trade
    list, so the biggest winner can be one the jackknife cannot reach. They are dropped here with
    the count on the record rather than coerced, because `float(None)` is a crash and `0.0` is a
    lie about a trade that made money. The fix belongs in whatever wrote the row.
    """
    cur.execute("""select exit_date, pnl_cad from backtest_trades
                    where run_id = %s order by exit_date""", (run_id,))
    rows = cur.fetchall()
    priced = [(d, float(p)) for d, p in rows if p is not None and d is not None]
    if len(priced) < len(rows):
        print(f"  note: {len(rows) - len(priced)} of {len(rows)} trade rows carry no P&L or no "
              f"exit date and are outside the jackknife — run {run_id}'s ledger is incomplete")
    return priced


def cut(equity, pnls, since=None):
    """One §2.5(a) cut: the NAV path, the benchmark path, and the trades realized inside it."""
    rows = [r for r in equity if since is None or r[0] >= since]
    if len(rows) < 2:
        raise RuntimeError(f"cut from {since} holds {len(rows)} sessions — nothing to measure")
    nav = np.array([float(r[1]) for r in rows])
    bench = np.array([float(r[2]) for r in rows if r[2] is not None])
    trade_pnls = [p for d, p in pnls if since is None or (d is not None and d >= since)]
    return dict(window=[rows[0][0].isoformat(), rows[-1][0].isoformat()],
                sessions=len(rows), nav=nav, bench=bench, trade_pnls=trade_pnls)


def score_cut(c, dd_bar=None):
    r = bars.daily_returns(c["nav"])
    br = bars.daily_returns(c["bench"])
    total = float(c["nav"][-1] / c["nav"][0] - 1)
    bench_total = float(c["bench"][-1] / c["bench"][0] - 1)
    counterfactual = float(np.prod(1.0 + 0.9 * br) - 1.0)

    jk = bars.jackknife_arithmetic(c["trade_pnls"], float(c["nav"][0])) if c["trade_pnls"] \
        else {"all": 0.0, "ex_top_1": 0.0, "ex_top_3": 0.0, "ex_top_5": 0.0}
    # account-level ex-top-k: the run's own total return minus the removed winners' contribution.
    # Same arithmetic approximation as the module documents — flatters, so a FAIL is conclusive.
    ex = {k: total - (jk["all"] - jk[k]) for k in ("ex_top_1", "ex_top_3", "ex_top_5")}

    boot = bars.block_bootstrap(r, seed=0)
    return dict(window=c["window"], sessions=c["sessions"],
                total_return=round(total, 6),
                cagr=round(bars.cagr(c["nav"][0], c["nav"][-1], c["sessions"]), 6),
                benchmark=dict(total_return=round(bench_total, 6),
                               cagr=round(bars.cagr(c["bench"][0], c["bench"][-1],
                                                    len(c["bench"])), 6)),
                counterfactual_90_10=dict(total_return=round(counterfactual, 6),
                                          beaten=bool(total > counterfactual)),
                jackknife=dict(trade_level=jk,
                               account_ex_top={k: round(v, 6) for k, v in ex.items()},
                               ex_top_3_beats_benchmark=bool(ex["ex_top_3"] > bench_total)),
                bootstrap=boot,
                bootstrap_median_beats_benchmark=bool(
                    boot["cagr"]["p50"] > bars.cagr(c["bench"][0], c["bench"][-1],
                                                    len(c["bench"]))),
                max_drawdown=round(bars.max_drawdown(c["nav"]), 6),
                sharpe=dict(annualized=round(bars.sharpe(r), 4),
                            per_session=round(bars.sharpe(r, periods_per_year=1.0), 6)),
                moments=bars.moments(r),
                dd_bar=dd_bar)


def trial_sharpes(cur, scored_run_id):
    """One per-session Sharpe per E-SERIES TRIAL. Forward-only per Zak's 2026-08-12 ruling: a
    trial is a distinct (param_hash, code_stamp) among runs that carry a hash at all; a hashed run
    with no code stamp is its own trial, because 54/55/56 share a hash across three engines."""
    cur.execute("""select distinct on (params->>'param_hash',
                                       coalesce(params->>'code_stamp', 'run:' || id::text))
                          id
                     from backtest_runs
                    where params->>'param_hash' is not null
                    order by params->>'param_hash',
                             coalesce(params->>'code_stamp', 'run:' || id::text), id desc""")
    ids = sorted({r[0] for r in cur.fetchall()} | {scored_run_id})
    out = {}
    for rid in ids:
        cur.execute("select nav from backtest_equity where run_id = %s order by d", (rid,))
        nav = np.array([float(r[0]) for r in cur.fetchall()])
        if len(nav) < 2:
            continue
        out[rid] = bars.sharpe(bars.daily_returns(nav), periods_per_year=1.0)
    if len(out) < 2:
        raise RuntimeError(
            f"only {len(out)} E-series trial(s) in the ledger — the deflated Sharpe needs the "
            f"spread of Sharpes ACROSS trials, and inventing one would defeat the deflation")
    return out


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 else (
        int(os.environ["RUN_ID"]) if os.environ.get("RUN_ID") else None)
    dd_bar = float(os.environ["DD_BAR"]) if os.environ.get("DD_BAR") else None

    with connect() as conn:
        with conn.cursor() as cur:
            run = fetch_run(cur, want)
            try:
                equity = fetch_equity(cur, run["id"])
                pnls = fetch_trade_pnls(cur, run["id"])

                full = score_cut(cut(equity, pnls), dd_bar=dd_bar)
                # A run can END before the OOS cut — the 2007-2017 half of a disjoint split has no
                # Aug-2025 sessions to be tested on. That is a third case, and neither of the two
                # obvious answers is right. Asking anyway raised `cut from 2025-08-01 holds 0
                # sessions`, which under the workflow's `bash -e` loop killed the finding step for
                # every remaining run in the batch (run 607). Skipping quietly would be worse: an
                # untestable claim would score as a tested one. It fails closed instead — no OOS
                # block, and `proven` is unreachable.
                oos = (score_cut(cut(equity, pnls, since=OOS_START), dd_bar=dd_bar)
                       if equity[-1][0] >= OOS_START else None)

                trials = trial_sharpes(cur, run["id"])
                sds = np.array(list(trials.values()))
                r_full = bars.daily_returns(cut(equity, pnls)["nav"])
                m = full["moments"]
                dsr = bars.deflated_sharpe(full["sharpe"]["per_session"],
                                           n_obs=len(r_full), skew=m["skew"],
                                           kurtosis=m["kurtosis"],
                                           trial_sharpe_sd=float(sds.std(ddof=1)),
                                           n_trials=len(trials))

                verdict = bars.verdict(
                    ex_top_3_beats_benchmark=full["jackknife"]["ex_top_3_beats_benchmark"],
                    bootstrap_median_cagr=full["bootstrap"]["cagr"]["p50"],
                    benchmark_cagr=full["benchmark"]["cagr"],
                    dsr=dsr["dsr"], dd_bar=dd_bar,
                    bootstrap_median_drawdown=full["bootstrap"]["max_drawdown"]["p50"],
                    bootstrap_p5_drawdown=full["bootstrap"]["max_drawdown"]["p5"])
                # §2.5(a) makes the OOS cut part of the definition, not decoration: a full-window
                # pass with an OOS miss is unproven, with the reason on the record.
                if verdict["verdict"] == "proven":
                    if oos is None:
                        verdict = dict(verdict="unproven",
                                       reasons=[f"the equity path ends {equity[-1][0].isoformat()}, "
                                                f"before the Aug-2025 cut — §2.5(a)'s out-of-sample "
                                                f"test cannot be run on this window"])
                    elif not oos["bootstrap_median_beats_benchmark"]:
                        verdict = dict(verdict="unproven",
                                       reasons=["OOS bootstrap-median CAGR does not exceed the "
                                                "benchmark's on the Aug-2025 cut"])

                out = dict(source="wo-e-series-2026-08-12 §2.5",
                           scored_at=dt.date.today().isoformat(),
                           full=full, oos=oos,
                           dsr=dsr,
                           trials=dict(n=len(trials),
                                       runs={str(k): round(v, 6) for k, v in trials.items()},
                                       sd_per_session_sharpe=round(float(sds.std(ddof=1)), 6),
                                       rule="distinct (param_hash, code_stamp); hashed runs "
                                            "without a code stamp count singly (54/55/56)"),
                           verdict=verdict)
            except Exception:
                cur.execute("""update backtest_runs
                                  set stats = jsonb_set(stats, '{bars_25}', %s::jsonb)
                                where id = %s""",
                            (json.dumps(dict(error=traceback.format_exc())), run["id"]))
                conn.commit()
                raise

        lines = [f"### §2.5 bars · run {run['id']} · `{run['label']}`", ""]
        cuts = [("full", full)]
        cuts.append(("OOS (Aug-2025)", oos) if oos is not None else (None, None))
        for name, c in cuts:
            if c is None:
                lines += [f"**OOS (Aug-2025)** not applicable — the path ends "
                          f"{equity[-1][0].isoformat()}, before the cut. Verdict cannot read "
                          f"`proven` on this window.", ""]
                continue
            b = c["bootstrap"]
            lines += [f"**{name}** {c['window'][0]} → {c['window'][1]} · "
                      f"{c['total_return']:+.2%} vs benchmark {c['benchmark']['total_return']:+.2%} "
                      f"vs 90/10 {c['counterfactual_90_10']['total_return']:+.2%}",
                      f"  ex-top-3 {c['jackknife']['account_ex_top']['ex_top_3']:+.2%} "
                      f"({'beats' if c['jackknife']['ex_top_3_beats_benchmark'] else 'loses to'} "
                      f"the benchmark) · bootstrap CAGR "
                      f"p5 {b['cagr']['p5']:+.2%} / p50 {b['cagr']['p50']:+.2%} / "
                      f"p95 {b['cagr']['p95']:+.2%} · DD p5 {b['max_drawdown']['p5']:+.1%}",
                      ""]
        lines += [f"DSR {dsr['dsr']:.4f} (z={dsr['z']:.2f}, SR0={dsr['sr0']:.4f}, "
                  f"trials logged {dsr['n_trials_logged']}, used {dsr['n_trials_used']})",
                  "",
                  f"**verdict: {verdict['verdict'].upper()}**"]
        lines += [f"- {r}" for r in verdict.get("reasons", [])]
        report = "\n".join(lines)
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
                              set stats = jsonb_set(stats, '{bars_25}', %s::jsonb)
                            where id = %s""", (json.dumps(out, default=str), run["id"]))
        conn.commit()
        print(f"\nstats.bars_25 written on run {run['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
