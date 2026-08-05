"""compose — §4.2's fourth verb, first half: the pipeline writes the words.

Dispatch is a sequence, not a moment: score → check → compose → notify. This job reads the same
one-read payload the sessions read (`v_session_payload`), renders every number mechanically —
§5.0: personality lives in the prose, never in the data — and only then asks the model for the
voice layer. A red `check` ships nothing but the stale banner and the protective lines; that rule
is enforced here, before any prose exists to argue with.

Products by slot:
  nightly  (weekdays, after the 03:50 check) — the stop sheet (§5.2) and the next morning's brief
           (§5.1), pre-composed. Nothing writes to the database between tonight's check and the
           open, so composing the morning's words now is the same words, earlier — they wait in
           `briefs` for the morning chat's single read.
  saturday (after the 12:30 weekly check)    — the Saturday letter (§5.3).

The monthly letter is deliberately NOT composed here: §5.5 makes it Yuna's letter — rulings first,
then the words — and rulings are judgment, which belongs to a session, not a job (§4.0). The R5
session writes it and `briefs` stores it like everything else.

Voice: ANTHROPIC_API_KEY missing or the call failing is an amber, never a silence — the mechanical
rendering ships as the brief. A plainer message beats a missing one; §4.7 says the missing message
is the alarm, so this job's duty is to never be the reason for one.
"""
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from db import connect, config, dry, jsonb, Heartbeat

ANTHROPIC = "https://api.anthropic.com/v1/messages"

VOICE = """You are Yuna, Zak's research desk, writing in the voice plan §5.0 sets:
smart, fun, warm, feminine; first person, plain English, a little playfully dry. He is Zak
(Z or boss when playful). Personality lives in the prose, never in the data — every number,
ticker, price and table below must appear VERBATIM; you frame them, you never restate or round
them. Wit is seasoning, not filler: one good line beats three cute ones. When something is
wrong the voice goes flat — clarity first. Charm never manufactures urgency. Emoji sparingly
(☀️ 🌙 ⚠️), only when they earn their place. Format law: summary first, context second."""


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
        "**Unruled at the line (§3.1 — rule blind before any GTC ships):**\n"
        + _table(pay.get("unruled_at_the_line") or [],
                 ["ticker", "ccn", "hurdle_price", "last_close"],
                 ["name", "CCN", "hurdle", "close"]),
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


# --------------------------------------------------------------------------- voice layer

def voice(cur, hb, kind, skeleton):
    """Ask the model to frame the mechanical sections. Any failure returns None and the
    skeleton ships as-is — plainer, never silent."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        hb.amber("ANTHROPIC_API_KEY not set — briefs ship mechanical, voiceless (§5.0 waits)")
        return None
    model = config(cur, "compose_model", "claude-sonnet-5")
    if isinstance(model, str):
        model = model.strip('"')
    ask = {"stopsheet": "Render this stop sheet exactly — §5.2 allows one framing line at most; "
                        "if the data lines say all is well, the whole message may be one line.",
           "preopen": "Write tomorrow morning's brief around these sections: snapshot first, "
                      "context second, and close with a one-line '**You:** …' naming exactly "
                      "what Zak must do (or that nothing needs him).",
           "deepdive": "Write the Saturday letter around these sections — read-only by design; "
                       "end with one hook for the week ahead."}[kind]
    body = json.dumps({
        "model": model, "max_tokens": 2500,
        "system": VOICE,
        "messages": [{"role": "user", "content": f"{ask}\n\n---\n\n{skeleton}"}],
    }).encode()
    req = urllib.request.Request(ANTHROPIC, data=body, headers={
        "x-api-key": api_key, "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.load(r)
        hb.calls[0] += 1
        text = "".join(c.get("text", "") for c in out.get("content", []))
        return text.strip() or None
    except Exception as e:
        hb.amber(f"voice layer failed ({type(e).__name__}: {e}) — mechanical text ships")
        return None


# --------------------------------------------------------------------------- write

def publish(cur, hb, kind, session_date, freshness_line, body, *, meta=None):
    """One composed row per kind per session date — a re-run is a no-op, not a duplicate."""
    cur.execute("""select 1 from briefs where kind=%s and session_date=%s
                   and detail->>'composed'='true' limit 1""", (kind, session_date))
    if cur.fetchone():
        hb.detail.setdefault("skipped", []).append(f"{kind} already composed for {session_date}")
        return False
    summary = next((l for l in body.splitlines() if l.strip()), "")[:300]
    if dry():
        hb.detail.setdefault("dry_run_would_write", []).append(kind)
        return False
    cur.execute("""insert into briefs (kind, session_date, freshness, summary, body, detail)
                   values (%s,%s,%s,%s,%s,%s)""",
                (kind, session_date, freshness_line, summary, body,
                 jsonb(dict(composed=True, sha=hashlib.sha256(body.encode()).hexdigest()[:12],
                            **(meta or {})))))
    hb.rows += 1
    return True


def main():
    slot = os.environ.get("COMPOSE_SLOT", "nightly")
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
                meta = dict(slot=slot, stale=bool(reason))
                if slot == "nightly":
                    sheet = stopsheet_body(pay, reason)
                    styled = None if reason else voice(cur, hb, "stopsheet", sheet)
                    publish(cur, hb, "stopsheet", today, freshness_line, styled or sheet,
                            meta=meta)
                    # the morning brief is composed tonight and waits for the chat's single read
                    session = today + dt.timedelta(days=1)
                    if reason:
                        brief = (f"⚠️ {freshness_line}\n\nstale data ⇒ no new tickets (§5.6). "
                                 f"Protective instructions only:\n\n"
                                 + (stopsheet_body(pay, None)))
                    else:
                        skel = brief_skeleton(pay, freshness_line)
                        brief = voice(cur, hb, "preopen", skel) or skel
                    publish(cur, hb, "preopen", session, freshness_line, brief, meta=meta)
                elif slot == "saturday":
                    if reason:
                        letter = f"⚠️ {freshness_line}\n\nthe weekly rank did not prove itself — " \
                                 f"no letter tonight beyond this banner."
                    else:
                        skel = saturday_skeleton(cur, pay, freshness_line)
                        letter = voice(cur, hb, "deepdive", skel) or skel
                    publish(cur, hb, "deepdive", today, freshness_line, letter, meta=meta)
                else:
                    raise SystemExit(f"unknown COMPOSE_SLOT {slot!r}")
            conn.commit()
            print(f"compose: slot={slot} · {hb.rows} brief(s) written · {freshness_line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
