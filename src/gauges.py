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
gauge needs a comparison it comes from the plan's own arithmetic (§3.5's size — since v1.1 NAV/5
or a share of deployable cash, the lesser — §3.2's screen, §3.4's SMA) or from the stored history
itself; a dollar figure derived twice is compared to the cent, money's own unit (half a cent,
`db.VALUATION_TOLERANCE`). The one gauge that reads as if it needs a constant
— "within historical band" — takes the band from the history itself: the observed range of every
prior session-to-session CHANGE in the count (ruled 2026-09-14, §5.6; it was the range of levels,
and a level band can never admit a new low). A tighter band would be a better gauge and it would
also be a number nobody ruled, which is the trade §0.3 exists to decide rather than this file.
"""
import os
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import desk                                                                # noqa: E402
import engine                                                              # noqa: E402
from db import VALUATION_TOLERANCE, connect, dry, freshness, Heartbeat     # noqa: E402


def _gauge(name, status, why, **detail):
    return dict(gauge=name, status=status, why=why, **detail)


def newest_session(cur, mode="live"):
    cur.execute("""select session_date, gate_on, gate_green, index_close, index_sma,
                          universe_count, ranked_count, screen_count, nav, param_digest,
                          detail, mode
                     from engine_sessions where mode = %s
                    order by session_date desc limit 1""", (mode,))
    row = cur.fetchone()
    if not row:
        return None
    keys = ("session_date", "gate_on", "gate_green", "index_close", "index_sma",
            "universe_count", "ranked_count", "screen_count", "nav", "param_digest",
            "detail", "mode")
    return dict(zip(keys, row))


# ---- 1. gate reproducibility from raw bars ----------------------------------------------------

def gate_reproduces(cur, stored):
    """Recompute §3.4 from the benchmark's bars and compare with what was decided.

    RED on a mismatch, and this is the one gauge where red is obviously right: the gate decides
    whether the entire book sells. A stored ON against a recomputed OFF means either the tape moved
    or the latch was carried wrong, and both of those are answered by looking, not by trading.

    It is also the suite's currency check, in both directions. A decision stamped AFTER the newest
    bar was decided on bars that are gone; a newest bar LATER than the newest decision means the
    tape advanced and no session was scored on it, so every gauge below is re-proving an old sheet
    against itself — and with the sheet gauge green on a quiet night, nothing else would say so
    (QC 2026-10-07, A46). Both are red: §0.4, a stale pipeline means no new tickets.
    """
    cur.execute("select max(d) from prices where ticker = %s", (engine.REGIME_SOURCE,))
    newest = cur.fetchone()[0]
    if newest is not None and newest > stored["session_date"]:
        return _gauge("gate", "red", f"the newest {engine.REGIME_SOURCE} bar is {newest}, but the "
                                     f"newest scored session is {stored['session_date']} — the "
                                     f"tape advanced and no session was scored on it, so this "
                                     f"check is proving an old sheet", newest_bar=str(newest))
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
    """Tonight's CHANGE in the §3.2 survivor count against the observed range of every prior
    session-to-session change.

    Ruled 2026-09-14 (§5.6). The gauge exists to catch a broken tape — hundreds of names vanishing
    between one close and the next, which no log records — and until then it banded the LEVEL:
    the observed min–max of every prior count. A level band can never admit a new low, so three
    weeks of ordinary attrition (2,336 → 2,274 survivors, 2026-08-21 to 09-11: 47 names losing
    their $10M median as the summer tape rolled into the 50-session window, 15 closing under $5)
    read as amber on every down day while the universe stood still. The band is now of the
    day-to-day change: a jump the tape has never made is amber; a drift it makes every week is
    green. Still the plan's own arithmetic — the observed history — and still no number chosen
    here. The band learns from what it is shown: a broken-tape session left in `engine_sessions`
    becomes part of the history, so the standing repair for a broken night is the existing one —
    re-ingest the date and re-score it (the chain is idempotent per session) — not to leave the
    row and let the band widen around it.

    Uncensored on purpose — see migration 053. `ranked_count` is capped at §3.2's pool of 500 and
    sits at exactly 500 whatever happens to the tape, so it is the one number in this row that
    cannot report a broken ingest.

    AMBER rather than red: red is reserved for a decision that provably disagrees with itself.
    Amber warns; only red holds buys (§4.4, and §5.6's 2026-09-14 reading of §4.3).
    """
    if stored["screen_count"] is None:
        return _gauge("screen", "amber", "the session predates `screen_count` — no survivor count "
                                         "was recorded, so there is nothing to band")
    cur.execute("""select session_date, screen_count from engine_sessions
                    where mode = %s and session_date <= %s and screen_count is not null
                    order by session_date""", (mode, stored["session_date"]))
    rows = cur.fetchall()                       # tonight is the last row
    now = stored["screen_count"]
    if len(rows) < 2:
        return _gauge("screen", "green", f"{now} survivors — first stored session, no band yet",
                      survivors=now, change=None, band=None)
    # Changes are measured PER ELAPSED SESSION on the benchmark's own calendar (desk.load's
    # calendar too), so a night the chain did not score does not make the next night's change span
    # two sessions and read as a jump against single-session history.
    cur.execute("select d from prices where ticker = %s and d between %s and %s order by d",
                (engine.REGIME_SOURCE, rows[0][0], rows[-1][0]))
    pos = {d: i for i, (d,) in enumerate(cur.fetchall())}

    def rate(a, b):
        (da, ca), (db_, cb) = a, b
        gap = (pos[db_] - pos[da]) if (da in pos and db_ in pos) else 1
        return (cb - ca) / max(gap, 1), max(gap, 1)

    per_session, elapsed = rate(rows[-2], rows[-1])
    change = now - rows[-2][1]
    deltas = [rate(a, b)[0] for a, b in zip(rows[:-2], rows[1:-1])]
    if not deltas:
        return _gauge("screen", "green", f"{now} survivors ({change:+d} on the day) — one prior "
                                         f"session, no band of changes yet",
                      survivors=now, change=change, band=None)
    lo, hi = min(deltas), max(deltas)
    over = f"{change:+d} over {elapsed} session(s)" if elapsed > 1 else f"{change:+d} on the day"
    if per_session < lo or per_session > hi:
        return _gauge("screen", "amber",
                      f"{now} survivors, {over}, outside the observed band of per-session "
                      f"changes [{lo:+.1f}, {hi:+.1f}] over {len(deltas)} prior change(s)",
                      survivors=now, change=change, sessions_elapsed=elapsed,
                      per_session=per_session, band=[lo, hi], changes=len(deltas))
    return _gauge("screen", "green", f"{now} survivors, {over}, inside [{lo:+.1f}, {hi:+.1f}]",
                  survivors=now, change=change, sessions_elapsed=elapsed,
                  per_session=per_session, band=[lo, hi], changes=len(deltas))


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

def _attested(stored):
    """The decision `score` attested for this session, as {(ticker, action)} — or None when the
    session carries no attestation (stored before 2026-10-06) or was scored outside live mode.

    A shadow session is never compared with tickets: tickets carry no mode, so the rows for its
    close belong to the live sheet, not to it (sheet.write_tickets).
    """
    detail = stored.get("detail") or {}
    if detail.get("orders") is None or stored.get("mode") not in (None, "live"):
        return None
    return ({(t, "sell") for t in detail.get("sells") or ()}
            | {(t, "buy") for t in detail.get("buys") or ()})


def _named(pairs):
    """Orders as Zak reads them, sells first — §3.5 executes them first."""
    return ", ".join(f"{a.upper()} {t}"
                     for t, a in sorted(pairs, key=lambda p: (p[1] != "sell", p[0])))


def _sheet_without_tickets(stored):
    """No ticket on the newest sheet. Three different facts produce that row count, and until
    2026-10-06 this gauge could not tell them apart — so it read amber on 25 of the first 36 live
    sessions (2026-08-14 to 10-06; 64 of 93 check runs), every one of them gate-ON with a full
    five-name book, and the colour stopped carrying information. An amber that fires on most nights
    is one everyone learns to read past (learning 68).

    `score` now attests its decision in `engine_sessions.detail` (sheet.write_session, counted
    after apply_freeze, so in live mode it is what write_tickets will write). Then:

      decided none      green — a full book that matches the rank is the ordinary night
      decided some      red   — the sheet was decided and never written. This is the failure the
                               old amber existed to catch, and it deserves its own colour. The
                               reason names the orders, because the sheet that should carry them
                               is empty and the brief has nothing else to show.
      shadow mode       green — sheet.write_tickets writes no tickets outside live mode, by design
      no attestation    amber — a session stored before the attestation existed; the old wording
                               stands, because the gauge still cannot tell.
    """
    detail = stored.get("detail") or {}
    decided = detail.get("orders")
    if stored.get("mode") not in (None, "live"):
        return _gauge("sheet", "green", f"{stored.get('mode')} mode writes no tickets "
                                        f"(sheet.write_tickets); score decided "
                                        f"{'?' if decided is None else decided} order(s)",
                      tickets=0, decided=decided)
    if decided is None:
        return _gauge("sheet", "amber", f"no tickets for {stored['session_date']} — a session with "
                                        f"no orders is ordinary, but so is a score that failed to "
                                        f"write them, and this session carries no attestation "
                                        f"either way")
    if decided == 0:
        return _gauge("sheet", "green", f"no orders for {stored['session_date']}: score ranked "
                                        f"{stored.get('ranked_count')} name(s) and decided none — "
                                        f"by rule", tickets=0, decided=0)
    return _gauge("sheet", "red", f"score decided {decided} order(s) for {stored['session_date']} "
                                  f"— {_named(_attested(stored))} — but no ticket exists for any "
                                  f"of them: the sheet was decided and never written",
                  tickets=0, decided=decided,
                  sells=detail.get("sells"), buys=detail.get("buys"))


def _score_hold(cur, stored):
    """The holds tonight's `score` declared — Zak's 2026-10-07 R1 (a gate that cannot be evaluated
    on fresh data) and R2 (a held name with no bar on the decision session), worded by the desk.

    Read from the newest `score` run of this mode rather than from the stored session, because R1
    writes no session at all: its whole point is that nothing new is proposed, so the newest
    session on record is the last one decided on fresh data, and the only place the hold is
    written down is the run that declared it. Dry runs are not facts (learning 67).
    """
    cur.execute("""select detail from runs
                    where job = 'score' and not dry_run
                      and coalesce(detail->>'mode', 'live') = %s
                    order by id desc limit 1""", (stored.get("mode") or "live",))
    row = cur.fetchone()
    return ((row[0] if row else None) or {}).get("hold") or []


def sheet_arithmetic(cur, stored):
    """Every ticket on the newest sheet, re-derived: does its quantity follow from §3.5?

    Three separate claims, and they fail in different ways:

      completeness  a sell whose ticket is missing is a position that never leaves — checked
                    against what `score` attested it decided (detail.sells / detail.buys)
      sizing        §3.5 as v1.1 amended it, from the inputs `score` attested (detail.sizing): a
                    fill is `min(NAV / 5 // price, share // price)`, the share being deployable
                    TFSA cash over the night's buys; a park's `fund` sell is the whole shares that
                    cover the recorded shortfall, never more than the lot; and the deployable cash
                    itself is re-added from its parts — tonight's sell tickets at their quantity ×
                    decision close, the park's draw likewise, and the cash. A session stored before
                    the attestation carried sizing is held to `NAV / 5 // price` alone, the rule it
                    was sized by.
      participation §3.5's 0.98 ADDV cap, "a correctness check, not a live constraint at
                    current size", which is exactly why it needs a gauge: a check that never
                    fires at $200k is the one that fires silently at $2M

    A sizing error is RED. A quantity that does not follow from the plan's arithmetic is the single
    most expensive class of defect this repository can produce, because it does not throw.

    And two things it reports rather than checks, as an amber that holds nothing by itself (§4.3:
    the check suite's own amber warns): a hold `score` declared (`_score_hold`) — the hold proper
    is `score`'s amber, which the freshness gauge turns into held buys — and a buy the cash could
    not reach, which is no ticket and so appears on no sheet. The brief prints the check's reasons
    and nothing of `score`'s, and both are things Zak is to be told: his ruling is that the brief
    names the stale bar and the held name, and v1.1's that a shortfall "is reported".
    """
    g = _sheet_verdict(cur, stored)
    hold = _score_hold(cur, stored)
    short = (stored.get("detail") or {}).get("held_below") or []
    said = []
    if hold:
        said.append("score held the buys — " + "; ".join(hold))
    if short:
        said.append(f"{len(short)} buy(s) held below weight, no ticket (§3.5, v1.1): "
                    + "; ".join(f"{h['ticker']} — {h['why']}" for h in short))
    if not said:
        return g
    said = " · ".join(said)
    return dict(g, status="red" if g["status"] == "red" else "amber", held=hold,
                held_below=[h["ticker"] for h in short],
                why=said if g["status"] == "green" else f"{g['why']} · {said}")


def _sheet_verdict(cur, stored):
    cur.execute("""select ticker, action, qty, mark, rank, state, clause from tickets
                    where session_date = %s order by action, ticker""", (stored["session_date"],))
    written = cur.fetchall()
    if not written:
        return _sheet_without_tickets(stored)

    # Withdrawn tickets are excluded from the ARITHMETIC, and that is §4.3's own definition rather
    # than a convenience. "The nightly sheet is the only source of engine orders", and a re-score
    # that no longer stands behind a proposal cancels it — so a `cancelled` row is a record of an
    # order that is NOT one. Counting them inflated this gauge the day the account filter landed (5
    # unsized buys reported against 3 real ones), and the sizing check below is worse: a stale
    # quantity on a withdrawn ticket would go RED for failing to match §3.5's arithmetic for a
    # sheet nobody is executing.
    rows = [r for r in written if r[5] not in ("cancelled", "void")]

    # Completeness, against the decision itself rather than a count: every (ticker, action) score
    # attested must have been WRITTEN. A ticket in any state counts — a withdrawn one was written,
    # and Zak's own sessions have cancelled tickets by hand (2026-08-17), which is his call and not
    # a missing order. One with no row at all was decided and never written; on the sell side that
    # is a position that never leaves. Tickets BEYOND the attestation are not failures either:
    # write_tickets withdraws only `proposed` rows, so a ticket Zak already acted on keeps its
    # state through a re-score that no longer proposes it.
    attested = _attested(stored)
    missing = attested - {(r[0], r[1]) for r in written} if attested else set()
    if not rows and not missing:
        if attested is None:
            return _sheet_without_tickets(stored)
        return _gauge("sheet", "green", f"no live tickets for {stored['session_date']}: all "
                                        f"{len(written)} written and since withdrawn",
                      tickets=0, withdrawn=len(written))
    bad = [f"{_named([pair])}: decided by score and never written"
           for pair in sorted(missing, key=lambda p: (p[1] != "sell", p[0]))]
    unsized = 0
    nav = stored["nav"]
    detail = stored.get("detail") or {}
    # A session `score` attested after v1.1's sizing landed carries `sizing` — None on a night with
    # no buy, a dict otherwise. One without the key was sized by NAV / 5 alone and is held to it.
    v11 = "sizing" in detail
    sizing = detail.get("sizing") or {}
    alloc = sizing.get("alloc")
    shortfall = sizing.get("shortfall")
    # The park's draw, re-derived from the shortfall the desk recorded, lot by lot in the desk's
    # order. A lot the desk did not draw has no entry, so a fund sell of it is not one §3.5 made.
    fund_want, left = {}, shortfall
    for d in sorted(sizing.get("park") or [], key=lambda d: d["ticker"]):
        if left is None or left <= 0:
            break
        q = engine.park_draw(float(left), float(d["lot"]), float(d["mark"]))
        fund_want[d["ticker"]] = q
        left -= q * float(d["mark"])
    if alloc is not None:
        bad += _deployable_re_added(written, sizing, nav)
    cur.execute("""select ticker, addv from engine_ranks
                    where session_date = %s and mode = %s and addv is not null""",
                (stored["session_date"], stored.get("mode") or "live"))
    addv_of = {t: float(a) for t, a in cur.fetchall()}
    for tk, action, qty, mark, rank, state, clause in rows:
        if attested is not None and (tk, action) not in attested:
            # Beyond tonight's decision. One Zak has acted on was sized by an earlier pass of this
            # close, against that pass's cash, so tonight's share cannot re-derive it — and it is
            # his trade, not tonight's order (see completeness above). One still `proposed` is
            # neither: write_tickets withdraws every proposal its own pass did not make, so a live
            # proposal score never decided is a line on Zak's sheet that nothing stands behind.
            if state == "proposed":
                bad.append(f"{_named([(tk, action)])}: proposed on the sheet and never decided "
                           f"by score")
            continue
        if clause not in ("fill", "rank_exit", "displaced", "gate_off", "phase0", "fund"):
            # `top_up` left this list with v1.1 (§3.5: a slot filled below weight "is never topped
            # up"), so a top-up proposed tonight is a clause the plan no longer has.
            bad.append(f"{tk}: clause {clause!r} is not a recognised clause")
        if clause == "fund":
            # The park's cash leg: its quantity is a draw on a lot, not a slot, so the slot
            # arithmetic below must not measure it. It must be an executable sell, and since v1.1
            # it must be the draw the recorded shortfall gives — never the lot because a lot
            # exists (A6), never beside buys that were not sized (A23).
            if action != "sell":
                bad.append(f"{tk}: a fund {action} — the park's draw is a sell")
            elif qty is None or float(qty) <= 0:
                bad.append(f"{tk}: a fund sell with no quantity cannot be executed")
            elif v11 and tk not in fund_want:
                bad.append(f"{tk}: a fund sell of {float(qty):g} the session's sizing does not "
                           f"draw — the park pays the shortfall of sized buys and only that "
                           f"(§3.5, v1.1)")
            elif v11 and float(qty) != float(fund_want[tk]):
                bad.append(f"{tk}: fund sell {float(qty):g} but the recorded shortfall of "
                           f"{float(shortfall):,.2f} draws {float(fund_want[tk]):g}")
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
        if v11 and alloc is None:
            bad.append(f"{tk}: sized at {qty:g} but the session's sizing recorded none — "
                       f"{sizing.get('unsized') or 'no buy was sized'}")
            continue
        want = (engine.capped_size(nav, float(mark), float(alloc)) if v11
                else engine.position_size(nav, float(mark)))
        if int(qty) != want:
            bad.append(f"{tk}: qty {qty:g} but §3.5 gives {want} for clause {clause}"
                       + (f" (NAV ÷ 5 or {float(alloc):,.2f} of deployable cash, the lesser)"
                          if v11 else ""))
        # §3.5's participation cap, re-derived from the ADDV `score` ranked the name on. "A
        # correctness check, not a live constraint at current size" — which is why it is checked
        # here: a cap that never fires at this size is the one that fires silently at a larger
        # one. Unknown liquidity is not permission (engine.participation_ok), and every buy comes
        # from a ranked name, so a buy with no ranked ADDV is itself a failure.
        addv = addv_of.get(tk)
        if not engine.participation_ok(float(qty), float(mark), addv):
            bad.append(f"{tk}: qty {qty:g} at {float(mark):g} is "
                       + (f"{float(qty) * float(mark) / addv:.2f}x the name's ADDV "
                          f"({addv:,.0f}); §3.5 caps an order at {engine.MAX_PARTICIPATION}x"
                          if addv else "a buy with no ranked ADDV — its participation cannot "
                                       "be checked against §3.5"))

    if bad:
        # The reason carries the first failures, not just their count: the brief renders this
        # string and nothing else from the gauge, so a count alone tells Zak something is wrong
        # with the sheet without saying which line.
        return _gauge("sheet", "red", f"{len(bad)} arithmetic or completeness failure(s): "
                                      + "; ".join(bad[:3]) + ("; …" if len(bad) > 3 else ""),
                      failures=bad[:20], tickets=len(rows))
    if unsized:
        return _gauge("sheet", "amber", f"{unsized} buy ticket(s) carry no quantity — "
                                        + (sizing.get("unsized") or "the session recorded no "
                                                                    "engine NAV")
                                        + " — so none of them can be executed; `score`'s own amber"
                                          " holds the buys through the freshness rule (§4.4)",
                      unsized=unsized)
    return _gauge("sheet", "green", f"{len(rows)} ticket(s), every quantity re-derived from §3.5",
                  tickets=len(rows))


def _deployable_re_added(written, sizing, nav):
    """v1.1's deployable cash, added up again from what was written. Returns [failure, ...].

    The share every fill is re-derived against is `deployable ÷ buys`, and deployable is three
    parts: the cash the store stated (re-added from its own legs), tonight's sells at their
    tickets' quantity × decision close, and the park's draw likewise. A share that does not follow
    from its parts sizes every buy on the sheet wrong at once, so each step is checked to the cent
    — money is counted in cents, and VALUATION_TOLERANCE is half of one.
    """
    out = []
    cash = sizing.get("cash") or {}
    legs = float(cash.get("usd") or 0) + (float(cash.get("cad") or 0) / float(cash["usdcad"])
                                          if cash.get("cad") else 0.0)
    if abs(max(legs, 0.0) - float(cash.get("in_usd") or 0)) > VALUATION_TOLERANCE:
        out.append(f"the attested cash {float(cash.get('in_usd') or 0):,.2f} USD does not follow "
                   f"from its own legs ({legs:,.2f})")
    sells = {r[0]: r for r in written if r[1] == "sell" and r[6] != "fund"}
    proceeds = 0.0
    for s in sizing.get("sold") or []:
        r = sells.get(s["ticker"])
        if r is None or r[2] is None or r[3] is None:
            out.append(f"SELL {s['ticker']}: its proceeds count toward deployable cash and its "
                       f"ticket carries no quantity × decision close")
            continue
        proceeds += float(r[2]) * float(r[3])
    drawn = sum(float(r[2]) * float(r[3]) for r in written
                if r[6] == "fund" and r[2] is not None and r[3] is not None)
    deployable = float(cash.get("in_usd") or 0) + proceeds + drawn
    if abs(deployable - float(sizing["deployable"])) > VALUATION_TOLERANCE:
        out.append(f"deployable cash attested {float(sizing['deployable']):,.2f} but cash + "
                   f"tonight's sells + the park's draw re-add to {deployable:,.2f}")
    if abs(deployable / int(sizing["buys"]) - float(sizing["alloc"])) > VALUATION_TOLERANCE:
        out.append(f"each buy's share attested {float(sizing['alloc']):,.2f} but "
                   f"{deployable:,.2f} over {int(sizing['buys'])} buy(s) is "
                   f"{deployable / int(sizing['buys']):,.2f}")
    if sizing.get("shortfall") is not None and nav:
        need = int(sizing["buys"]) * nav / engine.SLOTS - (float(cash.get("in_usd") or 0)
                                                           + proceeds)
        if abs(need - float(sizing["shortfall"])) > VALUATION_TOLERANCE:
            out.append(f"the park's shortfall attested {float(sizing['shortfall']):,.2f} but "
                       f"{int(sizing['buys'])} slot(s) less cash and proceeds is {need:,.2f}")
    return out


# ---- 5. book-vs-broker reconciliation age ------------------------------------------------------

def ledger_breaks(cur):
    """§4.4 (v1.2): where `book` and the ledger disagree, as `v_ledger_vs_book` states it (069,
    075). Returns (red, amber) — one line per position.

    Red is a break in the engine's account: §3.5 sizes, marks and sells against the TFSA's book, so
    a book the ledger contradicts there is a decision about shares that may not exist. A break in
    another account is amber — the engine neither ranks nor trades it (§2.1) — and so is a holding
    with no ledger history behind it at all, which the next export explains (069's
    `predates_the_ledger`). A position held in more than one open book row is a break wherever it
    sits; 069's index refuses a second row, so one is a write that went around it.

    Found by the 2026-10-07 review (A22): nothing read this view. VXC.TO's stray NONREG row printed
    in seven briefs, 418 shares against the ledger's 279, with every gauge quiet.
    """
    cur.execute("""select account, ticker, ledger_qty, book_qty, predates_the_ledger, open_rows
                     from v_ledger_vs_book order by account, ticker""")
    red, amber = [], []
    for account, ticker, ledger, book, predates, rows in cur.fetchall():
        line = (f"{account} {ticker} ledger={float(ledger or 0):g} book={float(book or 0):g}"
                + (f" in {rows} open rows" if rows and rows > 1 else ""))
        if predates and not (rows and rows > 1):
            amber.append(line + " — no ledger history behind it")
        elif account == desk.ENGINE_ACCOUNT:
            red.append(line)
        else:
            amber.append(line)
    return red, amber


def last_statement(cur):
    """When a broker statement was last compared with the book: the newest reconcile run that read
    a manifest's positions, or None. §4.4 (v1.2) shows it beside the gauge and never colours it —
    no statement feed exists, so its age measures Zak's exports, not the system's health.

    Neither condition may throw on any `detail`: runs 453-486 recorded `manifests` as a count, and
    SQL does not evaluate an AND left to right, so a type test cannot guard `jsonb_array_length`
    beside it. The first night on this gauge died on exactly that (2026-10-09)."""
    cur.execute("""select max(finished_at) from runs
                    where job = 'reconcile' and not dry_run and status in ('green', 'amber')
                      and jsonb_typeof(detail->'manifests') = 'array'
                      and detail->'manifests' <> '[]'::jsonb""")
    return cur.fetchone()[0]


def reconciliation_age(cur):
    """§4.4: does the book agree with its witnesses — the ledger every night, the broker when Zak
    exports — and what is still waiting on a receipt?

    The tolerance is derived, not chosen. A ticket sits in `approved` from the moment Zak says he
    will trade it until a receipt settles it, so an approval still waiting after a LATER session has
    been scored means the loop demonstrably did not close: either the trade did not happen or the
    receipt was never read, and the book is wrong either way. That comparison needs no constant.

    Book against ledger (`ledger_breaks`) is the comparison that runs every night. The broker
    statement's age rides along uncoloured (`last_statement`).
    """
    cur.execute("select last_receipt, last_attested, awaiting_receipt, oldest_awaiting "
                "from v_reconciliation_age")
    receipt, attested, awaiting, oldest = cur.fetchone()
    detail = dict(last_receipt=str(receipt) if receipt else None,
                  last_attested=str(attested) if attested else None,
                  awaiting_receipt=awaiting, oldest_awaiting=str(oldest) if oldest else None)
    led_red, led_amber = ledger_breaks(cur)
    statement = last_statement(cur)
    detail.update(ledger_breaks=led_red + led_amber,
                  last_statement=str(statement) if statement else None)
    seen = (f"last broker statement compared: "
            f"{f'{statement:%Y-%m-%d}' if statement else 'never'}")

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
        run = newest[1] or {}
        breaks = run.get("breaks") or []
        refused = run.get("refused") or []
        # A receipt the ledger refused (QC A21) is a red with no position break behind it: its
        # ticker and the ledger's reason ride in the run's `refused`, and a brief that printed only
        # "0 position break(s)" over held buys named nothing to repair. A run that died with
        # neither says how it died, where the heartbeat or the autopsy recorded it.
        said = []
        if breaks:
            said.append(f"{len(breaks)} position break(s): "
                        + "; ".join(f"{b['ticker']} broker={b['broker']} book={b['book']}"
                                    for b in breaks[:8]))
        # Since 075 a split reconcile could not record rides in `refused` too, carrying `split`:
        # the book may hold the pre-split count, which is the same reason to hold the buys.
        splits = [r for r in refused if r.get("split")]
        receipts = [r for r in refused if not r.get("split")]
        if splits:
            said.append(f"{len(splits)} split(s) on a held name not recorded: "
                        + "; ".join(f"{r['account']} {r['ticker']} ({r['split']}): {r['why']}"
                                    for r in splits[:8]))
        if receipts:
            said.append(f"{len(receipts)} receipt(s) the ledger refused: "
                        + "; ".join(f"{r['account']} {r['ticker']}: {r['why']}"
                                    for r in receipts[:8]))
        return _gauge("reconciliation", "red",
                      "the last reconcile went red — "
                      + (" · ".join(said) or run.get("fatal") or "no reason recorded"),
                      breaks=breaks[:8], refused=refused[:8], **detail)

    if led_red:
        return _gauge("reconciliation", "red",
                      f"the {desk.ENGINE_ACCOUNT}'s book disagrees with its ledger — "
                      + "; ".join(led_red[:8])
                      + f" — §3.5 sizes and sells against the book · {seen}", **detail)
    ledger_said = ((" · the book disagrees with the ledger outside the engine: "
                    + "; ".join(led_amber[:8])) if led_amber else "")
    if attested is None:
        return _gauge("reconciliation", "amber",
                      "the book has never been checked against the broker" + ledger_said,
                      **detail)
    if awaiting:
        cur.execute("select max(session_date) from engine_sessions where mode = 'live'")
        newest = cur.fetchone()[0]
        if newest and oldest and oldest < newest:
            return _gauge("reconciliation", "red",
                          f"{awaiting} approved ticket(s) still await a receipt, the oldest from "
                          f"{oldest} — a session has been scored since, so the book has been "
                          f"reasoned from without knowing whether that trade happened", **detail)
        return _gauge("reconciliation", "amber",
                      f"{awaiting} approved ticket(s) await a receipt (oldest {oldest})"
                      + ledger_said, **detail)
    if led_amber:
        return _gauge("reconciliation", "amber", ledger_said.removeprefix(" · ") + f" · {seen}",
                      **detail)
    return _gauge("reconciliation", "green",
                  f"the book agrees with the ledger · last attested {attested:%Y-%m-%d %H:%M} UTC"
                  f" · {seen}", **detail)


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
