"""shadow — §6.4's nightly attestation. The live engine against the sim, on the same bars.

    "**6.4 Shadow — 10 sessions.** The pipeline runs live producing order sheets nobody trades.
     Each night: live output vs the sim's decision on the same-vintage bars, attested in writing.
     Pass = 10/10 matches, or every divergence named and ruled."

    DATABASE_URL=... python src/shadow.py
    DATABASE_URL=... AS_OF=2026-08-14 python src/shadow.py

**What this compares, exactly.** The live side is `engine.py`, which `sheet.py` runs every night.
The sim side is `concentrated.py` — the research engine that produced the cell of record, run at
the same session index on the same closes, with its dollar volume built from the same bars the way
its own grid builds it (`sim_dollar_volume`, since QC finding A7):

  rank   `engine.rank`          vs  `concentrated.rank_at(risk_adjusted=True, top_by_addv=500)`
  gate   `engine.gate_history`  vs  `concentrated.regime_latch(confirm_out=1, confirm_in=3)`

**What it does NOT compare, and why that is stated rather than hidden.** §3.5's banded order rule
has exactly one implementation outside the sim's own loop — `engine.orders` — and the sim's copy is
inline in `simulate()`, carried on a book that has evolved from the start of its own window. There
is no way to ask it "what would you do tonight" without also giving it a year of its own history,
so a per-session comparison of the ORDER rule is not available and this file does not pretend to
make one. What stands in its place is named: `tests/test_engine_parity.py` (42 assertions that the
two ranks agree over adversarial tapes) and `tests/test_engine_book.py` (14 tests pinning
`engine.orders` to §3.5's clauses, one clause at a time).

An attestation that claimed more than it checked would be worse than none, because §6.5 gates the
seed on this record.

**Nothing here places an order** (§0.2), and nothing here writes a ticket.
"""
import datetime as dt
import json
import os
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import concentrated                                                        # noqa: E402
import desk                                                                # noqa: E402
import engine                                                              # noqa: E402
from db import connect, dry, Heartbeat                                     # noqa: E402

# §3.4's latch, in the sim's own parameter names. `b5_12_2_L1_3` — the L1_3 suffix IS this pair,
# and §3.4 states it in words: "1 red session -> OFF", "3rd consecutive green session -> ON".
SIM_LATCH = dict(confirm_out=engine.LATCH_OUT, confirm_in=engine.LATCH_IN, window=engine.GATE_SMA)


def sim_gate(index_px, upto):
    """The sim's latch, walked forward exactly as `simulate()` walks it.

    Walked rather than evaluated at a point, because a latch has memory: asking `regime_latch` about
    session i with a fresh state gives the answer for a book that started today, which is not the
    answer the sim would have. The state dict is the sim's own carrier.
    """
    state = {}
    on = False
    for i in range(upto + 1):
        on = concentrated.regime_latch(i, index_px, state, **SIM_LATCH)
    return bool(on)


def sim_reads():
    """`concentrated.rank_at`'s reads of the tape, in the sim's own constants, as sessions back from
    the decision session — for `rank_at` as `compare` calls it (risk-adjusted, no participation
    floor). `desk.tape` loads only the window the engine reads (A34), so the sim's reads are handed
    to it as well: the two sets agree today, and if they ever stop, the window still covers both
    and the comparison stays one of rules rather than of bars the window left out.
    """
    return {
        "sim formation close, adj[i - FORMATION]": concentrated.FORMATION,
        "sim skip close, adj[i - SKIP]": concentrated.SKIP,
        "sim finite bars, the last FORMATION closes": concentrated.FORMATION - 1,
        "sim ADDV, the median of the last ADDV_WINDOW sessions": concentrated.ADDV_WINDOW - 1,
        "sim vol, VOL_WINDOW daily returns ending at i": concentrated.VOL_WINDOW,
    }


def sim_dollar_volume(sessions, tickers, rows):
    """The sim side's dollar volume, built from `desk.tape`'s rows the way `concentrated.build_grid`
    builds the cell of record's: a bar off the benchmark's calendar is no session, a bar with no
    positive adjusted close is no bar, and dollar volume is the adjusted close times the volume,
    NaN where the vendor sent none.

    QC finding A7, 2026-10-07. Both sides of the rank comparison used to read `desk.load`'s dollar
    volume, so a live loader that priced §3.2's ADDV on another basis than the sim's was invisible
    here by construction — and one did: from 2026-08-17 live read the raw close times
    split-adjusted volume while build_grid read the adjusted close times volume, and this file
    attested a match every night. Built here, from the rows and not from the live arrays, so the
    two constructions can disagree and the comparison can see it. `tests/test_addv_basis.py` pins
    this to build_grid's own output, so the copy cannot drift from the rule it copies.
    """
    at = {d: i for i, d in enumerate(sessions)}
    col = {t: j for j, t in enumerate(tickers)}
    dv = np.full((len(sessions), len(tickers)), np.nan)
    for tk, d, a, _close, vol in rows:
        i = at.get(d)
        if i is None or a is None or a <= 0:
            continue
        dv[i, col[tk]] = float(a) * float(vol) if vol is not None else np.nan
    return dv


def compare(cur, as_of):
    """Both comparisons for one session. Returns [(compared, matched, live, sim, detail)].

    The sim side ranks on its own dollar volume (`sim_dollar_volume`) and on the live closes; the
    closes are one read of one table, and ADDV is the clause where the two loaders were built twice.
    """
    sessions, index_px, tickers, rows = desk.tape(cur, as_of, also=sim_reads())
    adj, raw, dv = desk.grid(sessions, tickers, rows)
    sim_dv = sim_dollar_volume(sessions, tickers, rows)
    i = len(sessions) - 1
    out = []

    live_gate = bool(engine.gate_history(index_px)[i])
    sim_g = sim_gate(index_px, i)
    out.append(("gate", live_gate == sim_g, live_gate, sim_g,
                dict(index_close=float(index_px[i]), session=str(sessions[i]),
                     latch=f"{engine.LATCH_OUT} red -> OFF, {engine.LATCH_IN} green -> ON")))

    live_rank = [tickers[j] for j in engine.rank(i, adj, raw, dv)]
    sim_rank = [tickers[j] for j in concentrated.rank_at(i, adj, raw, sim_dv, risk_adjusted=True,
                                                        top_by_addv=engine.POOL)]
    band = engine.FILL_BAND
    # The whole ordering is compared, and the top 12 is reported separately because that is the
    # slice §3.5 acts on: a disagreement at rank 340 is a curiosity, and one at rank 3 is a
    # different book tomorrow morning.
    same_all = live_rank == sim_rank
    same_band = live_rank[:band] == sim_rank[:band]
    first_diff = next((k for k, (a, b) in enumerate(zip(live_rank, sim_rank), start=1) if a != b),
                      None)
    # Written down even when the ranks agree: names whose §3.2 ADDV differs between the live loader
    # and the sim's construction tonight. Zero is the attestation that the two bases are one; a
    # difference too small to move tonight's pool is still a difference in the rule.
    live_addv = engine.median_addv(dv, i)
    sim_addv = engine.median_addv(sim_dv, i, window=concentrated.ADDV_WINDOW)
    differs = ~((live_addv == sim_addv) | (np.isnan(live_addv) & np.isnan(sim_addv)))
    out.append(("rank", same_all, live_rank[:band], sim_rank[:band],
                dict(session=str(sessions[i]), ranked_live=len(live_rank), ranked_sim=len(sim_rank),
                     top_band_matches=same_band, first_disagreement_at=first_diff,
                     band=band, addv_differs=int(differs.sum()),
                     addv_differs_first=[tickers[j] for j in np.where(differs)[0][:5]])))
    return out


def write(cur, session, rows):
    for compared, matched, live, sim, detail in rows:
        cur.execute("""
            insert into shadow_attestations (session_date, compared, matched, live, sim, detail)
            values (%s,%s,%s,%s,%s,%s)
            on conflict (session_date, compared) do update set
                matched = excluded.matched, live = excluded.live, sim = excluded.sim,
                detail = excluded.detail, created_at = now()""",
                    (session, compared, matched, json.dumps(live), json.dumps(sim),
                     json.dumps(detail)))


def render(session, rows, progress):
    out = [f"### shadow · {session}", ""]
    for compared, matched, live, sim, detail in rows:
        out.append(f"  {'✓' if matched else '✗'} {compared:<6} "
                   f"{'match' if matched else 'DIVERGENCE'}")
        if not matched:
            out.append(f"      live: {live}")
            out.append(f"      sim:  {sim}")
            out.append(f"      {detail}")
    out += ["", f"§6.4 progress: {progress['sessions']}/10 session(s) · "
                f"{progress['divergences']} divergence(s), {progress['unruled']} unruled · "
                f"pass = {progress['passes']}"]
    out += ["", "Compared: §3.3's rank and §3.4's gate, against `concentrated.py` on the same "
                "bars. NOT compared: §3.5's order rule, which has no second implementation to "
                "compare against — see `tests/test_engine_book.py` and `test_engine_parity.py`."]
    return "\n".join(out)


def main():
    as_of = os.environ.get("AS_OF", "").strip()
    as_of = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    with connect() as conn, Heartbeat(conn, "shadow", dry_run=dry()) as hb:
        with conn.cursor() as cur:
            rows = compare(cur, as_of)
            session = rows[0][4]["session"]
            if not dry():
                write(cur, session, rows)
                conn.commit()
            cur.execute("select * from v_shadow_progress")
            cols = [d[0] for d in cur.description]
            progress = dict(zip(cols, cur.fetchone()))

        report = render(session, rows, progress)
        print(report)
        hb.rows = 0 if dry() else len(rows)
        hb.detail.update(session=session, progress={k: str(v) for k, v in progress.items()},
                         results={c: m for c, m, _, _, _ in rows})
        for compared, matched, live, sim, detail in rows:
            if not matched:
                # §6.4 does not tolerate a divergence; it requires one to be NAMED AND RULED. Amber
                # is the state of an open question, and `v_shadow_progress.passes` stays false
                # until a ruling lands on the row.
                hb.amber(f"{compared} diverged on {session}: live {live} vs sim {sim} — §6.4 "
                         f"requires this named and ruled before the shadow can pass")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
