"""§4.4's check suite, gauge by gauge. §4.1's `check` job for v1.0's engine.

    "Gate reproducibility from raw bars · screen survivor count within historical band · rank
     reproducibility on same-vintage data · order sheet completeness & sizing arithmetic ·
     book-vs-broker reconciliation age · data freshness. Any red holds buys; nothing holds exits."

Six gauges, one function each, named after the plan's own words. It **writes nothing but its own
`runs` row** — a check that repairs what it finds cannot be trusted to have found it, and a check
that ambers on a state it just fixed reports a night that did not happen.

Four of the six are RECOMPUTATIONS. They take the stored decision and derive it again from the
tape, which is the only way to catch the failure this system is actually exposed to: not a job that
crashes, but a job that ran perfectly on data that moved underneath it. A vendor restatement is
invisible in every log and changes every number.

**Any red holds buys; nothing holds exits.** §5.4 makes gate-off exits and rank-exit sells
protective-direction and never blocked, so the verdict this job writes is `blocks_buys`, never
`blocks_dispatch` — the sheet always ships, and the buy half of it is what a red withdraws.

On thresholds. §4.4 names six gauges and gives no tolerances, and this file invents none. Where a
gauge needs a comparison it comes from the plan's own arithmetic (§3.5's NAV/5, §3.2's screen,
§3.4's SMA) or from the stored history itself. The one gauge that reads as if it needs a constant
— "within historical band" — takes the band literally: the observed range of every prior session.
A tighter band would be a better gauge and it would also be a number nobody ruled, which is the
trade §0.3 exists to decide rather than this file.
"""
import os
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import desk                                                                # noqa: E402
import engine                                                              # noqa: E402
from db import connect, dry, freshness, Heartbeat                          # noqa: E402


def _gauge(name, status, why, **detail):
    return dict(gauge=name, status=status, why=why, **detail)


def newest_session(cur, mode="live"):
    cur.execute("""select session_date, gate_on, gate_green, index_close, index_sma,
                          universe_count, ranked_count, screen_count, nav, param_digest
                     from engine_sessions where mode = %s
                    order by session_date desc limit 1""", (mode,))
    row = cur.fetchone()
    if not row:
        return None
    keys = ("session_date", "gate_on", "gate_green", "index_close", "index_sma",
            "universe_count", "ranked_count", "screen_count", "nav", "param_digest")
    return dict(zip(keys, row))


# ---- 1. gate reproducibility from raw bars ----------------------------------------------------

def gate_reproduces(cur, stored):
    """Recompute §3.4 from the benchmark's bars and compare with what was decided.

    RED on a mismatch, and this is the one gauge where red is obviously right: the gate decides
    whether the entire book sells. A stored ON against a recomputed OFF means either the tape moved
    or the latch was carried wrong, and both of those are answered by looking, not by trading.
    """
    cur.execute("""select d, coalesce(adj_close, close) from prices
                    where ticker = %s and d <= %s order by d""",
                (engine.REGIME_SOURCE, stored["session_date"]))
    bars = cur.fetchall()
    if not bars:
        return _gauge("gate", "red", f"no {engine.REGIME_SOURCE} bars at or before "
                                     f"{stored['session_date']} — the gate cannot be evaluated, "
                                     f"and §3.4 says an unevaluable gate reads OFF")
    px = np.array([float(b[1]) for b in bars])
    i = len(px) - 1
    if bars[-1][0] != stored["session_date"]:
        return _gauge("gate", "red", f"the newest {engine.REGIME_SOURCE} bar is {bars[-1][0]}, "
                                     f"but the decision is stamped {stored['session_date']}",
                      newest_bar=str(bars[-1][0]))
    again = bool(engine.gate_history(px)[i])
    green = bool(engine.gate_green(i, px))
    if again != stored["gate_on"]:
        return _gauge("gate", "red",
                      f"stored gate {'ON' if stored['gate_on'] else 'OFF'} but the bars now "
                      f"recompute to {'ON' if again else 'OFF'}",
                      stored=stored["gate_on"], recomputed=again)
    if green != stored["gate_green"]:
        return _gauge("gate", "amber",
                      f"the latch agrees but §3.4's raw signal does not: stored {stored['gate_green']}, "
                      f"recomputed {green} — the tape under the 200-day window moved",
                      stored=stored["gate_green"], recomputed=green)
    return _gauge("gate", "green", f"{'ON' if again else 'OFF'}, reproduced from raw bars",
                  gate_on=again)


# ---- 2. screen survivor count within historical band -------------------------------------------

def screen_within_band(cur, stored, mode="live"):
    """Today's §3.2 survivor count against the observed range of every prior session.

    Uncensored on purpose — see migration 053. `ranked_count` is capped at §3.2's pool of 500 and
    sits at exactly 500 whatever happens to the tape, so it is the one number in this row that
    cannot report a broken ingest.

    AMBER rather than red, and the level is §4.3's rather than a preference: amber already means
    "no new buy tickets", which is the correct response to "the universe changed shape and nobody
    knows why". Red is reserved for a decision that provably disagrees with itself.
    """
    if stored["screen_count"] is None:
        return _gauge("screen", "amber", "the session predates `screen_count` — no survivor count "
                                         "was recorded, so there is nothing to band")
    cur.execute("""select min(screen_count), max(screen_count), count(*) from engine_sessions
                    where mode = %s and session_date < %s and screen_count is not null""",
                (mode, stored["session_date"]))
    lo, hi, n = cur.fetchone()
    now = stored["screen_count"]
    if not n:
        return _gauge("screen", "green", f"{now} survivors — first stored session, no band yet",
                      survivors=now, band=None)
    if now < lo or now > hi:
        return _gauge("screen", "amber",
                      f"{now} survivors is outside the observed band [{lo}, {hi}] over {n} prior "
                      f"session(s)", survivors=now, band=[lo, hi], sessions=n)
    return _gauge("screen", "green", f"{now} survivors, inside [{lo}, {hi}]",
                  survivors=now, band=[lo, hi], sessions=n)


# ---- 3. rank reproducibility on same-vintage data ----------------------------------------------

def rank_reproduces(cur, stored, mode="live"):
    """Recompute §3.3 from the tape and compare with the stored ordering.

    "Same-vintage" is the point and it is also the trap: this store does not snapshot bars, so a
    recomputation reads TODAY's tape. That makes disagreement meaningful rather than tautological —
    the only way a past session's rank changes is if the bars behind it changed, which is exactly
    the restatement no log records.

    RED when the top 12 differs, because §3.5's fill band and exit rank are both 12: a different
    top 12 is a different book. AMBER when only deeper ranks moved — real, worth knowing, and not
    a decision.
    """
    cur.execute("""select ticker, rank from engine_ranks
                    where session_date = %s and mode = %s order by rank""",
                (stored["session_date"], mode))
    was = cur.fetchall()
    if not was:
        return _gauge("rank", "amber", "no stored ranks for this session — nothing to reproduce")

    s = desk.sheet(cur, stored["session_date"], None)
    now = {r["ticker"]: r["rank"] for r in s["ranks"]}
    then = {t: r for t, r in was}

    band = engine.FILL_BAND
    top_then = {t for t, r in then.items() if r <= band}
    top_now = {t for t, r in now.items() if r <= band}
    if top_then != top_now:
        return _gauge("rank", "red",
                      f"the top {band} no longer reproduces: "
                      f"gone {sorted(top_then - top_now)}, new {sorted(top_now - top_then)}",
                      left=sorted(top_then - top_now), joined=sorted(top_now - top_then))

    moved = {t: (then[t], now[t]) for t in then if t in now and then[t] != now[t]}
    dropped = sorted(set(then) - set(now))
    if moved or dropped:
        worst = max((abs(a - b), t) for t, (a, b) in moved.items()) if moved else (0, None)
        return _gauge("rank", "amber",
                      f"the top {band} holds, but {len(moved)} name(s) moved and {len(dropped)} "
                      f"left the ranking — worst displacement {worst[0]} ({worst[1]})",
                      moved=len(moved), dropped=dropped[:20], worst=worst[0])
    return _gauge("rank", "green", f"{len(then)} name(s) reproduce exactly", ranked=len(then))


# ---- 4. order sheet completeness & sizing arithmetic --------------------------------------------

def sheet_arithmetic(cur, stored):
    """Every ticket on the newest sheet, re-derived: does its quantity follow from §3.5?

    Three separate claims, and they fail in different ways:

      completeness  a sell whose ticket is missing is a position that never leaves
      sizing        `int(nav / 5 // price)` — §3.5's own arithmetic, §3.7(4)'s rounding
      participation §3.5's 0.98 ADDV cap, "a correctness check, not a live constraint at
                    current size", which is exactly why it needs a gauge: a check that never
                    fires at $200k is the one that fires silently at $2M

    A sizing error is RED. A quantity that does not follow from the plan's arithmetic is the single
    most expensive class of defect this repository can produce, because it does not throw.
    """
    # Withdrawn tickets are excluded, and that is §4.3's own definition rather than a convenience.
    # "The nightly sheet is the only source of engine orders", and a re-score that no longer stands
    # behind a proposal cancels it — so a `cancelled` row is a record of an order that is NOT one.
    # Counting them inflated this gauge the day the account filter landed (5 unsized buys reported
    # against 3 real ones), and the sizing check below is worse: a stale quantity on a withdrawn
    # ticket would go RED for failing to match §3.5's arithmetic for a sheet nobody is executing.
    cur.execute("""select ticker, action, qty, mark, rank, state, clause from tickets
                    where session_date = %s and state not in ('cancelled', 'void')
                    order by action, ticker""", (stored["session_date"],))
    rows = cur.fetchall()
    if not rows:
        return _gauge("sheet", "amber", f"no tickets for {stored['session_date']} — a session with "
                                        f"no orders is ordinary, but so is a score that failed to "
                                        f"write them")

    bad, unsized = [], 0
    nav = stored["nav"]
    for tk, action, qty, mark, rank, state, clause in rows:
        if clause not in ("fill", "rank_exit", "displaced", "gate_off", "phase0",
                          "fund", "top_up"):
            bad.append(f"{tk}: clause {clause!r} is not a recognised clause")
        if clause == "fund":
            # The park's cash leg (§6.5). Not §3.5 arithmetic — its quantity is the park position,
            # not NAV/5 — so the sizing check below must not measure it against a slot. The sell
            # branch's own completeness check (a sell must carry a positive quantity) still runs.
            if action != "buy" and (qty is None or float(qty) <= 0):
                bad.append(f"{tk}: a fund sell with no quantity cannot be executed")
            continue
        if action != "buy":
            if qty is None or float(qty) <= 0:
                bad.append(f"{tk}: a sell with no quantity — §5.4 makes exits unblockable and this "
                           f"one cannot be executed")
            continue
        if qty is None:
            unsized += 1
            continue
        if nav is None:
            bad.append(f"{tk}: sized at {qty:g} against a session that recorded no NAV")
            continue
        if mark is None or float(mark) <= 0:
            # A sized buy with no mark cannot have come from §3.5, which sizes at the decision
            # close. Reported rather than raised: this job's whole purpose is to say what is wrong,
            # and a traceback here takes down the proof instead of delivering it.
            bad.append(f"{tk}: sized at {qty:g} with no decision close to size against")
            continue
        want = engine.position_size(nav, float(mark))
        if clause == "top_up":
            # §6.5's top-up: the slot less the line already held. The held quantity is read from
            # the book NOW rather than stored on the ticket — safe because this gauge runs minutes
            # after `score` in the same chain and nothing trades in between; a re-run after Zak
            # executes would find the position at weight and the cancelled ticket excluded above.
            cur.execute("""select coalesce(sum(qty), 0) from book
                            where ticker = %s and account = %s and status = 'open'""",
                        (tk, stored.get("account") or "TFSA"))
            held_now = float(cur.fetchone()[0])
            want = max(0, want - int(held_now))
        if int(qty) != want:
            bad.append(f"{tk}: qty {qty:g} but §3.5 gives {want} for clause {clause}")

    if bad:
        return _gauge("sheet", "red", f"{len(bad)} arithmetic or completeness failure(s)",
                      failures=bad[:20], tickets=len(rows))
    if unsized:
        return _gauge("sheet", "amber", f"{unsized} buy ticket(s) carry no quantity — the session "
                                        f"recorded no engine NAV, so §4.3's amber applies and none "
                                        f"of them may be executed", unsized=unsized)
    return _gauge("sheet", "green", f"{len(rows)} ticket(s), every quantity re-derived from §3.5",
                  tickets=len(rows))


# ---- 5. book-vs-broker reconciliation age ------------------------------------------------------

def reconciliation_age(cur):
    """How long since the book was checked against an outside witness — and what is still waiting.

    The tolerance is derived, not chosen. A ticket sits in `approved` from the moment Zak says he
    will trade it until a receipt settles it, so an approval still waiting after a LATER session has
    been scored means the loop demonstrably did not close: either the trade did not happen or the
    receipt was never read, and the book is wrong either way. That comparison needs no constant.
    """
    cur.execute("select last_receipt, last_attested, awaiting_receipt, oldest_awaiting "
                "from v_reconciliation_age")
    receipt, attested, awaiting, oldest = cur.fetchone()
    detail = dict(last_receipt=str(receipt) if receipt else None,
                  last_attested=str(attested) if attested else None,
                  awaiting_receipt=awaiting, oldest_awaiting=str(oldest) if oldest else None)

    # The NEWEST reconcile run, whatever it concluded. `last_attested` deliberately counts only
    # green and amber runs — it answers "when did the comparison last succeed" — so on its own it
    # would read yesterday's success right through today's position break, and §4.4's "any red
    # holds buys" would never fire on the one finding that most obviously should hold them. §3.5
    # sizes and queues against `book`, so a book the broker contradicts makes every decision
    # tonight a decision about a position that may not exist.
    cur.execute("""select status, detail from runs where job = 'reconcile'
                    order by id desc limit 1""")
    newest = cur.fetchone()
    if newest and newest[0] == "red":
        breaks = (newest[1] or {}).get("breaks") or []
        return _gauge("reconciliation", "red",
                      f"the last reconcile went red on {len(breaks)} position break(s): "
                      + "; ".join(f"{b['ticker']} broker={b['broker']} book={b['book']}"
                                  for b in breaks[:8]),
                      breaks=breaks[:8], **detail)

    if attested is None:
        return _gauge("reconciliation", "amber",
                      "the book has never been checked against the broker", **detail)
    if awaiting:
        cur.execute("select max(session_date) from engine_sessions where mode = 'live'")
        newest = cur.fetchone()[0]
        if newest and oldest and oldest < newest:
            return _gauge("reconciliation", "red",
                          f"{awaiting} approved ticket(s) still await a receipt, the oldest from "
                          f"{oldest} — a session has been scored since, so the book has been "
                          f"reasoned from without knowing whether that trade happened", **detail)
        return _gauge("reconciliation", "amber",
                      f"{awaiting} approved ticket(s) await a receipt (oldest {oldest})", **detail)
    return _gauge("reconciliation", "green", f"last attested {attested:%Y-%m-%d %H:%M} UTC",
                  **detail)


# ---- 6. data freshness --------------------------------------------------------------------------

def data_fresh(conn):
    """§4.4's sixth gauge, from the shared helper — stale means the BARS, not the clock (§5.6).

    Lateness rides the line and decides nothing. That ruling is not decoration: an `ingest-daily`
    that started 194 minutes behind its slot with perfectly current bars used to write amber, and
    every brief that day said "tickets held" over a punctuality note.
    """
    line, allowed = freshness(conn)
    return _gauge("freshness", "green" if allowed else "red", line, tickets_allowed=allowed)


# ---- the suite ---------------------------------------------------------------------------------

def run(conn, mode="live"):
    """All six, in §4.4's order. Returns (verdict, [gauge, ...])."""
    out = []
    with conn.cursor() as cur:
        stored = newest_session(cur, mode)
        if stored is None:
            out.append(_gauge("session", "amber",
                              "no engine session has been scored — every recomputation gauge has "
                              "nothing to check against"))
        else:
            out.append(gate_reproduces(cur, stored))
            out.append(screen_within_band(cur, stored, mode))
            out.append(rank_reproduces(cur, stored, mode))
            out.append(sheet_arithmetic(cur, stored))
        out.append(reconciliation_age(cur))
    out.append(data_fresh(conn))

    if any(g["status"] == "red" for g in out):
        verdict = "red"
    elif any(g["status"] == "amber" for g in out):
        verdict = "amber"
    else:
        verdict = "green"
    return verdict, out


def render(verdict, gauges, stored=None):
    mark = {"green": "✓", "amber": "⚠", "red": "✗"}
    out = [f"### check · {verdict.upper()}", ""]
    if stored:
        out.append(f"session {stored['session_date']} · digest {stored['param_digest']}")
        out.append("")
    for g in gauges:
        out.append(f"  {mark[g['status']]} {g['gauge']:<15} {g['why']}")
    out += ["", "§4.4: any red holds buys; nothing holds exits. §5.4 makes gate-off exits and "
                "rank-exit sells protective-direction and never blocked."]
    return "\n".join(out)


def main():
    mode = (os.environ.get("ENGINE_MODE") or "live").strip().lower()
    with connect() as conn, Heartbeat(conn, "check", dry_run=dry()) as hb:
        verdict, gauges = run(conn, mode)
        with conn.cursor() as cur:
            stored = newest_session(cur, mode)
        report = render(verdict, gauges, stored)
        print(report)

        hb.detail.update(gauges=gauges, verdict=verdict, mode=mode,
                         session=str(stored["session_date"]) if stored else None,
                         # §4.4/§5.4: the sheet always ships. A red withdraws the BUY half only.
                         blocks_buys=verdict == "red")
        for g in gauges:
            if g["status"] == "red":
                hb.red(f"{g['gauge']}: {g['why']}")
            elif g["status"] == "amber":
                hb.amber(f"{g['gauge']}: {g['why']}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report + "\n")
    # A red is a RESULT, not a crash (§4.2): the job ran perfectly and the answer was "hold the
    # buys". Exiting non-zero would fail the workflow and take `compose` down with it, and §4.2
    # gives a red check the power to ship the stale banner and the protective lines — silence is
    # the one outcome with no reader.
    return 0


if __name__ == "__main__":
    sys.exit(main())
