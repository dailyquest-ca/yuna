"""compose — §4.2's fourth verb, first half: the pipeline writes the words down.

Dispatch is a sequence, not a moment: score → check → compose → notify. This job reads the same
one-read payload the sessions read (`v_session_payload`) and renders it **mechanically** —
clinical sections, every number exact. A red `check` ships nothing but the stale banner and the
protective lines; that rule is enforced here, before any prose exists to argue with.

Deliberately keyless — ruled 2026-08-05: the §5.0 voice layer is NOT applied here. The scheduled
project sessions (the Routines, running on Zak's Claude plan) read the composed row and speak it
in voice; a GitHub Actions job calling a metered model API would pay twice for words the project
already writes. So this job's output is the data layer §5.0 demands anyway — personality lives in
the prose, never in the data, and this is the data.

Products by slot:
  nightly  (weekdays, after the 03:50 check) — the stop sheet (§5.2, whose line set is clinical
           by law and needs no voice at all) and the next morning's brief sections (§5.1),
           pre-composed. Nothing writes to the database between tonight's check and the open, so
           composing the morning's sections now is the same content, earlier — waiting in
           `briefs` for the morning chat's single read.
  saturday (after the 12:30 weekly check)    — the Saturday letter sections (§5.3).

The monthly letter is deliberately NOT composed here: §5.5 makes it Yuna's letter — rulings
first, then the words — and rulings are judgment, which belongs to a session, not a job (§4.0).
"""
import datetime as dt
import hashlib
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from db import connect, data_date, dry, jsonb, session_date_for, Heartbeat


# --------------------------------------------------------------------------- mechanical layer

def payload(cur):
    cur.execute("select * from v_session_payload")
    cols = [d.name for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else {}


def stale(check_report):
    """§4.2: a red check, or no check at all, blocks the dispatch."""
    if not check_report:
        return "no check row — the night never proved itself"
    if check_report.get("status") == "red" or (check_report.get("blocks_dispatch") or []):
        blocked = ", ".join(check_report.get("blocks_dispatch") or []) or "red"
        return f"check red — {blocked}"
    return None


def protective_lines(armed):
    """§5.2's data layer: one clinical line per action. Volume is judged elsewhere; this is the
    stop sheet, so only stop moves, cancels and protective exits speak."""
    def num(x):
        return f"{float(x):g}" if x is not None else "?"
    lines = []
    for a in armed or []:
        kind, urgent = a.get("kind"), a.get("urgency") == "protective"
        if kind == "stop_move":
            lines.append(f"{a['ticker']} · stop {num(a.get('stop'))} / limit "
                         f"{num(a.get('stop_limit_price'))}")
        elif kind == "cancel":
            lines.append(f"{a['ticker']} · {a.get('reason')} — cancel entry order")
        elif kind == "exit" and urgent:
            lines.append(f"{a['ticker']} · {a.get('reason')} — exit ticket, "
                         f"{a.get('order_type') or 'market'}")
    return lines


def stopsheet_body(pay, stale_reason):
    if stale_reason:
        return f"⚠️ pipeline red — touch nothing, GTCs stand as placed ({stale_reason})"
    lines = protective_lines(pay.get("armed"))
    return "\n".join(lines) if lines else "✓ stops all placed correctly"


def _table(rows, cols, headers):
    if not rows:
        return "_none_"
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(
            "" if r.get(c) is None else (f"{r[c]:g}" if isinstance(r[c], float) else str(r[c]))
            for c in cols) + " |")
    return "\n".join(out)


def brief_skeleton(pay, freshness_line):
    """§5.1 step 9's snapshot, rendered mechanically. The session (or the voice layer) frames
    this; nothing may alter it. Gaps are named, never papered over (§5.6 no-improvise)."""
    nav = pay.get("nav") or {}
    gate = pay.get("gate") or {}
    armed = [a for a in (pay.get("armed") or [])]
    offer = [a for a in armed if not a.get("blocked_by") and a.get("kind") in ("entry", "add")]
    held = [a for a in armed if a.get("blocked_by")]
    prot = protective_lines(armed)
    sections = [
        f"**Freshness:** {freshness_line}",
        f"**NAV:** ${nav.get('nav_cad'):,.0f} CAD ({nav.get('d')}"
        f"{', provisional' if nav.get('provisional') else ''})" if nav.get("nav_cad")
        else "**NAV:** not stored — say so, don't guess",
        f"**Gate:** {gate.get('state', 'unknown')} (week ending {gate.get('week_end')})",
        "**Blackout wall (holdings included, in full):**\n"
        + _table(pay.get("blackout_wall") or [], ["ticker", "report_date", "report_when"],
                 ["name", "reports", "when"]),
        "**Protective (never throttled):**\n" + ("\n".join(prot) if prot else "_none — quiet_"),
        "**Armed & offerable (max 2 new-entry tickets ship — §5.1):**\n"
        + _table(offer, ["kind", "ticker", "sleeve", "account", "order_type", "trigger_price",
                         "limit_price", "stop", "stop_limit_price", "qty", "score", "note"],
                 ["kind", "name", "sleeve", "acct", "order", "trigger", "limit", "stop",
                  "stop-limit", "qty", "score", "note"]),
        "**Armed but held back (context, never tickets):**\n"
        + _table(held, ["kind", "ticker", "score", "blocked_by"],
                 ["kind", "name", "score", "blocked by"]),
        # §3.1's docket, and only the docket. Until migration 034 this listed every name at the
        # line whether or not the desk had already ruled it — 44 of them on 2026-08-07, nearly all
        # carrying blind C2 rulings from the day before (obs 113). The ruled ones now sit in their
        # own section, with the verdict and the ruling id, so R1 cites instead of re-deciding.
        "**Unruled at the line (§3.1 — rule blind before any GTC ships):**\n"
        + _table(pay.get("unruled_at_the_line") or [],
                 ["ticker", "ccn", "hurdle_price", "last_close", "engine_provenance"],
                 ["name", "CCN", "hurdle", "close", "engine"]),
        "**Ruled at the line (cite the ruling — §3.1 binds later sessions):**\n"
        + _table(pay.get("ruled_at_the_line") or [],
                 ["ticker", "ccn", "verdict", "ruling_id", "ruled_at", "blind"],
                 ["name", "CCN", "verdict", "ruling", "ruled", "blind"]),
        "**Escalated — awaiting Zak (§5.6, not a ruling Yuna may make):**\n"
        + _table(pay.get("escalated_awaiting_zak") or [],
                 ["ticker", "ccn", "verdict", "ruling_id", "escalated_at"],
                 ["name", "CCN", "verdict", "ruling", "escalated"]),
        "**Queue:**\n" + _table((pay.get("queue") or [])[:12],
                                ["rank", "ticker", "state", "trigger_price", "mcn", "away_pct"],
                                ["#", "name", "state", "trigger", "MCN", "away %"]),
        "**Open tickets:**\n" + _table(pay.get("open_tickets") or [],
                                       ["ticker", "action", "state", "account"],
                                       ["name", "action", "state", "acct"]),
    ]
    brewing = pay.get("learnings_brewing") or []
    if brewing:   # §5.8: exception-only — absent most days
        sections.append("**Learnings:** " + " · ".join(
            f"{l['key']} ({l['status']})" for l in brewing[:3]))
    return "\n\n".join(sections)


def saturday_skeleton(cur, pay, freshness_line):
    cur.execute("""select week_end, industry, ret_6m, percentile from group_strength
                   where week_end >= current_date - 14 order by week_end desc, percentile desc""")
    rows = cur.fetchall()
    weeks = sorted({r[0] for r in rows}, reverse=True)
    latest = [dict(industry=r[1], ret_6m=r[2], pct=r[3]) for r in rows if r[0] == weeks[0]] \
        if weeks else []
    prior = {r[1]: r[3] for r in rows if len(weeks) > 1 and r[0] == weeks[1]}
    for g in latest:
        g["wow"] = (round(g["pct"] - prior[g["industry"]], 1)
                    if g["industry"] in prior and g["pct"] is not None else None)
    cur.execute("""select kind, ticker, verdict, blind, at::date, memo is not null as has_memo
                   from rulings where at > now() - interval '7 days' order by at""")
    week_rulings = [dict(kind=k, ticker=t, verdict=v, blind=b, on=str(d), memo=m)
                    for k, t, v, b, d, m in cur.fetchall()]
    cur.execute("""select d, nav_cad from nav_snapshots
                   where d >= current_date - 380 order by d""")
    navs = cur.fetchall()
    perf = "not stored"
    if navs:
        last = float(navs[-1][1])
        week_ago = next((float(n) for d, n in reversed(navs) if d <= navs[-1][0]
                         - dt.timedelta(days=7)), None)
        ytd0 = next((float(n) for d, n in navs if d.year == navs[-1][0].year), None)
        perf = (f"NAV ${last:,.0f}"
                + (f" · WoW {last / week_ago - 1:+.1%}" if week_ago else "")
                + (f" · YTD {last / ytd0 - 1:+.1%} vs the 30% bar" if ytd0 else ""))
    gate = pay.get("gate") or {}
    margin = (f"{float(gate['spx_close']) / float(gate['sma30']) - 1:+.1%} from the flip line"
              if gate.get("spx_close") and gate.get("sma30") else "margin not stored")
    return "\n\n".join([
        f"**Freshness:** {freshness_line}",
        f"**Gate:** {gate.get('state', 'unknown')} · {margin}",
        "**Groups (top/bottom 5, week-over-week):**\n"
        + _table(latest[:5] + latest[-5:], ["industry", "ret_6m", "pct", "wow"],
                 ["group", "6-mo return", "percentile", "WoW Δ"]),
        "**The week's rulings (each with its evidence block in `rulings`):**\n"
        + _table(week_rulings, ["on", "kind", "ticker", "verdict", "blind"],
                 ["date", "kind", "name", "verdict", "blind"]),
        "**Queue:**\n" + _table((pay.get("queue") or [])[:20],
                                ["rank", "ticker", "state", "trigger_price", "mcn", "away_pct"],
                                ["#", "name", "state", "trigger", "MCN", "away %"]),
        f"**Performance:** {perf}",
    ])


# --------------------------------------------------------------------------- write

# §5.2's reader looks back three hours, and that is the tightest window any session uses. A
# composed row is a no-op only while it is still the row a session would actually find: past that
# the night has no receipt, and §4.7's "a missing message is itself the alarm" fires on words that
# exist and cannot be delivered.
RECOMPOSE_AFTER_HOURS = 3


def publish(cur, hb, kind, session_date, freshness_line, body, *, meta=None):
    """One composed row per kind per session date — unless the words have changed, or aged out.

    The guard used to be "already composed for this date, skip", which was right while this ran
    once a night on a cron. Off the `needs:` chain it runs after EVERY ingest, and that turned the
    first version of the day into the final one: the 2026-08-05 stop sheet composed at 14:18
    described a world without that day's four fills, a fresh score at 22:52 recomputed everything,
    and compose skipped rather than correcting it. `notify` went red and was right to — the words a
    session would find were eight hours stale and outside its window.

    So the key is the CONTENT, and it expires. Same body, still inside the reader's window, skip —
    a chained retry forty minutes later has nothing to add. Different numbers, or a row too old for
    any session to find, new row; `briefs` is an append ledger (§4.3) and every reader takes the
    newest.

    The expiry half is the stop sheet's doing. Its body is often byte-identical night to night —
    "✓ stops all placed correctly" — and §5.2 makes that line the pipeline's **nightly receipt**.
    Content-only dedupe skipped it, and `notify` went red on a sheet that existed and was eight
    hours stale. The receipt is owed to the run, not to the prose.
    """
    sha = hashlib.sha256(body.encode()).hexdigest()[:12]
    cur.execute("""select detail->>'sha', at > now() - make_interval(hours => %s)
                     from briefs
                    where kind=%s and session_date=%s and detail->>'composed'='true'
                    order by at desc limit 1""", (RECOMPOSE_AFTER_HOURS, kind, session_date))
    row = cur.fetchone()
    if row and row[0] == sha and row[1]:
        hb.detail.setdefault("skipped", []).append(f"{kind} unchanged and still deliverable")
        return False
    summary = next((l for l in body.splitlines() if l.strip()), "")[:300]
    if dry():
        hb.detail.setdefault("dry_run_would_write", []).append(kind)
        return False
    cur.execute("""insert into briefs (kind, session_date, freshness, summary, body, detail)
                   values (%s,%s,%s,%s,%s,%s)""",
                (kind, session_date, freshness_line, summary, body,
                 jsonb(dict(composed=True, sha=sha, recomposed=bool(row), **(meta or {})))))
    hb.rows += 1
    return True


def main():
    # `or`, not a default argument: the chain passes this in from a job output, and an upstream
    # job that died hands down an empty string rather than an absent variable. Nightly is the
    # ordinary night, and a brief written on the wrong day is a smaller failure than no brief.
    slot = os.environ.get("COMPOSE_SLOT") or "nightly"
    with connect() as conn:
        with Heartbeat(conn, "compose",
                       scheduled_utc=os.environ.get("SCHEDULED_UTC")) as hb:
            with conn.cursor() as cur:
                pay = payload(cur)
                check_report = pay.get("check_report") or {}
                freshness_line = check_report.get("freshness") or "no check row"
                reason = stale(check_report)
                if reason:
                    hb.amber(f"stale dispatch — {reason}; stale banner and protective lines only")
                today = dt.date.today()
                # §4.2's clock convention: the chain has no clock, so neither does its output. Both
                # nightly products describe the SAME upcoming session — the stop sheet says what to
                # place before it opens, the brief says what to do in it — so both carry its date.
                # `now()::date` in UTC is an evening in New York, and stamped the brief a session
                # ahead of the market it was written for (WO-6).
                session = session_date_for(cur)
                hb.detail.update(session_date=str(session), data_date=str(data_date(cur)),
                                 slot=slot)
                meta = dict(slot=slot, stale=bool(reason), session_date=str(session))
                if slot == "nightly":
                    publish(cur, hb, "stopsheet", session, freshness_line,
                            stopsheet_body(pay, reason), meta=meta)
                    # the morning brief is composed tonight and waits for the chat's single read
                    if reason:
                        brief = (f"⚠️ {freshness_line}\n\nstale data ⇒ no new tickets (§5.6). "
                                 f"Protective instructions only:\n\n"
                                 + (stopsheet_body(pay, None)))
                    else:
                        brief = brief_skeleton(pay, freshness_line)
                    publish(cur, hb, "preopen", session, freshness_line, brief, meta=meta)
                elif slot == "saturday":
                    if reason:
                        letter = f"⚠️ {freshness_line}\n\nthe weekly rank did not prove itself — " \
                                 f"no letter tonight beyond this banner."
                    else:
                        letter = saturday_skeleton(cur, pay, freshness_line)
                    publish(cur, hb, "deepdive", today, freshness_line, letter, meta=meta)
                else:
                    raise SystemExit(f"unknown COMPOSE_SLOT {slot!r}")
            conn.commit()
            print(f"compose: slot={slot} · {hb.rows} brief(s) written · {freshness_line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
