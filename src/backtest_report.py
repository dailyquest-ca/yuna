"""backtest_report — the delta against the pinned baseline, as markdown.

A number reassures nobody. The question a run has to answer is not "what is the CAGR" but "did
what I just changed move it, and by how much" — so every run is read against
`config.backtest_baseline_run_id` and reported as a difference.

The report **never fails a build on performance.** It exits non-zero only when a *conformance*
clause fails: an entry below the MCN floor, an exit reason §3.2 does not name, a clause whose data
covered none of the window. A merge gate on CAGR is a standing instruction to fit the parameters to
history, and it would corrupt the one instrument the exit-rule ablation grid is supposed to trust.
Performance moves get printed, and the pull request owes them a sentence.

    python src/backtest_report.py [run_id]        # defaults to the newest law-v0 run
"""
import os, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from db import connect, config

ROWS = [
    ("CAGR", "cagr", "pct"),
    ("vs benchmark", None, "pct"),
    ("total return", "total_return", "pct"),
    ("expectancy / trade", "expectancy", "bps"),
    ("trades", "trades", "int"),
    ("win rate", "win_rate", "pct"),
    ("max drawdown", "max_drawdown", "pct"),
    ("avg exposure", "avg_exposure", "pct"),
    ("avg hold (days)", "avg_hold_days", "num"),
]


def fmt(kind, v):
    if v is None:
        return "—"
    return {"pct": f"{v:+.2%}" if abs(v) < 1 else f"{v:+.1%}",
            "bps": f"{v * 10_000:+.0f} bps", "int": f"{v:.0f}", "num": f"{v:.1f}"}[kind]


def delta(kind, a, b):
    if a is None or b is None:
        return "—"
    d = a - b
    return {"pct": f"{d:+.2%}", "bps": f"{d * 10_000:+.0f}", "int": f"{d:+.0f}",
            "num": f"{d:+.1f}"}[kind]


def fetch(cur, run_id=None, variant="law-v0"):
    if run_id:
        cur.execute("select * from backtest_runs where id = %s", (run_id,))
    else:
        cur.execute("""select * from backtest_runs where params->>'variant' = %s
                        order by id desc limit 1""", (variant,))
    row = cur.fetchone()
    return dict(zip([d.name for d in cur.description], row)) if row else None


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 else None
    with connect() as conn:
        with conn.cursor() as cur:
            run = fetch(cur, want)
            if not run:
                print("no law-v0 run found — nothing to report")
                return 0
            base_id = config(cur, "backtest_baseline_run_id", None)
            base = fetch(cur, int(base_id)) if base_id and int(base_id) != run["id"] else None

    p, s = run["params"] or {}, run["stats"] or {}
    out = [f"### backtest `{p.get('variant', run['label'])}` · run {run['id']}",
           "",
           f"law stamp `{p.get('law_stamp', '?')}` · config `{p.get('config_stamp', '?')}` · "
           f"{run['start_date']} → {run['end_date']} · {p.get('currency', 'USD')} · "
           f"benchmark `{p.get('benchmark', s.get('benchmark', '?'))}`",
           ""]

    against = f"baseline (run {base['id']})" if base else "baseline"
    out += [f"| | this run | {against} | Δ |", "|---|---:|---:|---:|"]
    for name, key, kind in ROWS:
        if key is None:
            a = (run["cagr"] - run["benchmark_cagr"]) if run["benchmark_cagr"] is not None else None
            b = ((base["cagr"] - base["benchmark_cagr"])
                 if base and base["benchmark_cagr"] is not None else None)
        else:
            a, b = run[key], (base[key] if base else None)
        a = float(a) if a is not None else None
        b = float(b) if b is not None else None
        out.append(f"| {name} | {fmt(kind, a)} | {fmt(kind, b)} | {delta(kind, a, b)} |")

    exits = s.get("exits") or {}
    if exits:
        out += ["", "exits: " + " · ".join(f"`{k}` {v}" for k, v in sorted(exits.items()))]
    if s.get("dividend_bps") is not None:
        out += [f"dividends not banked by the sleeve: {float(s['dividend_bps']):.0f} bps "
                f"(the benchmark is total return, so this handicap runs against us)"]

    # ---- conformance is the only thing that can fail a build
    table = s.get("conformance") or []
    bad = []
    for c in table:
        why = []
        if c.get("violations"):
            why.append(f"{c['violations']} violation(s)")
        if c.get("unknown_reasons"):
            why.append(f"exit reasons not in §3.2: {c['unknown_reasons']}")
        if c.get("coverage") in (None, 0, 0.0):
            why.append("no data covered this clause anywhere in the window")
        if why:
            bad.append((c["clause"], "; ".join(why)))

    out += ["", f"**conformance {len(table) - len(bad)}/{len(table)}**"]
    partial = [c for c in table
               if c.get("coverage") not in (None, 0, 0.0) and float(c["coverage"]) < 1.0]
    for c in partial:
        out.append(f"- {c['clause']} — enforceable over {float(c['coverage']):.0%} of the window")
    for clause, why in bad:
        out.append(f"- ❌ **{clause}** — {why}")

    report = "\n".join(out)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report + "\n")
    path = os.environ.get("REPORT_PATH")
    if path:
        pathlib.Path(path).write_text(report + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
