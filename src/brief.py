"""brief — §4.1's `compose`. The morning brief, rendered from the one payload read.

§5.1: "The morning brief renders: freshness · gate & latch · the order sheet · book with ranks &
P/L · DD status vs milestones · tranche schedule status. Judgment happens in chat; arithmetic
happens in the pipeline."

That division is the whole design of this file. It renders and it does not decide: every number
here was computed by `sheet`, checked by `gauges` and read back through `v_session_payload`. If a
figure appears in the brief that no other job wrote, this file has overstepped.

    DATABASE_URL=... python src/brief.py
    DATABASE_URL=... DRY_RUN=true python src/brief.py     # render, print, write nothing

**Nothing here places an order** (§0.2). The sheet is a proposal; Zak executes at the open.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import desk                                                                # noqa: E402
import engine                                                              # noqa: E402
from db import connect, dry, freeze_state, Heartbeat                       # noqa: E402

# §5.2, verbatim: "Pager at −10% engine DD; informational lines at −20 / −30 / −40 / −50. **No
# mechanical intervention exists at any level.**" The pager threshold and the informational ladder
# are the plan's, and the absence of any action at any of them is also the plan's — chosen, in the
# plan's own words, "with the three numbers in view".
DD_PAGER = -0.10
DD_MILESTONES = (-0.20, -0.30, -0.40, -0.50)


def payload(cur):
    cur.execute("select * from v_session_payload")
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, cur.fetchone()))


def _pct(x, places=1):
    return "—" if x is None else f"{100.0 * float(x):+.{places}f}%"


def freshness_line(p):
    """§5.1's first line. A red check holds BUYS; §5.4 makes exits unblockable, so the sheet still
    ships and the banner says which half of it may be acted on."""
    c = p["check_report"]
    if not c:
        return "⚠️ no check has run — nothing has been proved about tonight's numbers"
    verdict = (c.get("verdict") or c.get("status") or "?").upper()
    mark = {"GREEN": "✓", "AMBER": "⚠", "RED": "✗"}.get(verdict, "?")
    line = f"{mark} check {verdict}"
    if c.get("blocks_buys"):
        line += " — **buys held; exits stand** (§4.4, §5.4)"
    for why in (c.get("red") or []) + (c.get("amber") or []):
        line += f"\n    · {why}"
    return line


def gate_line(p):
    g = p["gate"]
    if not g:
        return "gate — no session has been scored"
    state = "ON" if g["gate_on"] else "OFF"
    signal = "green" if g["gate_green"] else "red"
    px, sma = g.get("index_close"), g.get("index_sma")
    where = ""
    if px and sma:
        where = f" · SPY {px:,.2f} vs 200-day {sma:,.2f} ({100.0 * (px / sma - 1):+.2f}%)"
    latch = ("1 red session turns it OFF" if g["gate_on"]
             else "3 consecutive greens turn it ON")
    return (f"gate **{state}** · today's signal {signal}{where}\n"
            f"    latch: {latch} (§3.4)")


def sheet_lines(p):
    """§4.3's sheet. Sells first — §3.5 executes them first, and the order on the page is the
    order at the open."""
    rows = p["order_sheet"] or []
    if not rows:
        return ["**no orders** — the book already matches the rank"]
    out = []
    for r in rows:
        if r["action"] == "sell":
            out.append(f"  SELL {r['ticker']:<10} qty {float(r['qty'] or 0):>10,.0f}   "
                       f"rank {r['rank'] or '—'}   ({r['clause']})   [{r['state']}]")
        else:
            qty = f"{float(r['qty']):>10,.0f}" if r["qty"] is not None else "         —"
            mark = f"{float(r['mark']):,.2f}" if r["mark"] is not None else "—"
            out.append(f"  BUY  {r['ticker']:<10} qty {qty}   "
                       f"rank {r['rank']}   mark {mark}   [{r['state']}]")
    out.append("")
    out.append("  Zak executes at the open: sells first, then buys (§3.5). Market orders; no GTC "
               "orders exist anywhere in this system (§4.3).")
    return out


def book_lines(p):
    """The book, and what the engine intends to do about each line.

    Two notes hang off an unranked holding and they mean opposite things, which is why the brief
    has to tell them apart. A `.US` common stock that has left §3.2's universe — delisted, or newly
    excluded — is queued to sell, because §3.5 queues anything below rank 12 and "not ranked at all"
    is below it. The PARK is unranked for a different reason: it was never eligible, it is where
    §3.4 puts the money while the gate is off, and it is never sold for failing to rank.

    Printing the first note against the park is not a cosmetic slip. It reads as "this 810-share
    position is queued to sell", which is the opposite of what §6.5 is holding it for.
    """
    rows = p["book"] or []
    if not rows:
        return ["  (nothing held)"]
    out = []
    for b in rows:
        rank = f"{b['rank']:>3}" if b.get("rank") is not None else "  —"
        # A missing mark is printed as MISSING, not as zero. `last_close` is null for VXC.TO — the
        # TSX line has no bars in this store — and `float(None or 0)` rendered that as "last 0.00
        # P/L +0.0%": a price the position does not have and a return it has not earned, in the one
        # document Zak reads numbers off. A dash cannot be mistaken for a fact.
        last = f"{float(b['last_close']):>10,.2f}" if b.get("last_close") is not None else "         —"
        pnl = f"{float(b['pnl_pct']):>+6.1f}%" if b.get("pnl_pct") is not None else "      —"
        out.append(f"  {b['ticker']:<10} {float(b['qty']):>8,.0f} @ {float(b['avg_cost']):>10,.2f}"
                   f"   last {last}   P/L {pnl}   rank {rank}"
                   f"   {b.get('account') or '?'}/{b['sleeve']}")
        if b.get("last_close") is None:
            out.append("      ** no mark: this position is not priced in this store, so it is NOT "
                       "in the marked equity below **")
        if b.get("rank") is not None:
            continue
        # Three reasons a holding has no rank, and they mean three different things. Printing one
        # note for all of them told Zak the engine was about to sell 810 shares of the Phase-0
        # bridge and 140 of the levered layer, neither of which it has any authority over.
        if b["ticker"] in desk.PARKED:
            out.append("      park — engine capital, never a slot and never sold for failing to "
                       "rank (§3.4, §6.1(3))")
        elif (b.get("account") or desk.ENGINE_ACCOUNT) != desk.ENGINE_ACCOUNT:
            out.append(f"      {b.get('account')} — §2.1 puts the engine in the "
                       f"{desk.ENGINE_ACCOUNT} and nowhere else; the engine neither ranks nor "
                       f"trades this")
        else:
            out.append("      ** no rank: this holding is outside §3.2's universe, which §3.5 "
                       "treats as below 12 **")
    return out


def sleeve_lines(p):
    """Where purpose and wrapper have stopped agreeing, from the one payload read (§0.4).

    Zak, 2026-08-18: *"The sleeve is the purpose of the money. We just set the boundaries as the
    account for simplicity but one day some of the RRSP may be used for Momentum and maybe some of
    the TFSA will be used for something else."*

    The engine reads the ACCOUNT, which is right only while the two coincide. This section is the
    expiry notice: the day momentum money sits in the RRSP, the engine cannot see it and nothing
    else about the sheet looks any different — a position it cannot see is one it can never sell.
    """
    rows = desk.diverging(p["book"] or [])
    if not rows:
        return []
    out = ["", "## Sleeve vs account — the engine reads the account (§2.1)"]
    for r in rows:
        out.append(f"  {r['account']}/{r['ticker']:<10} labelled `{r['sleeve']}` — §2.1 puts "
                   + " or ".join(f"`{s}`" for s in r["expected"]) + " here")
        if r["engine_sees_it"] and not r["engine_would_see_it"]:
            out.append("      the engine trades it today (it is in the TFSA) and would NOT if the "
                       "filter were the sleeve")
        elif r["engine_would_see_it"] and not r["engine_sees_it"]:
            out.append("      ** the engine does NOT see this and its purpose says it should — "
                       "it can never be sold while the filter is the account **")
    out.append("  The sleeve is the purpose of the money; the account is where it sits. They agree")
    out.append("  today, which is the only reason reading the account is safe. Correcting a label")
    out.append("  is assigning purpose to money — Zak's, never inferred here (§0.3).")
    return out


def underweight_lines(p):
    """§3.5's slot is a WEIGHT, and a slot held at a fraction of it is not equal weight.

    `engine.orders` KEEPS a held name in the top 12 rather than re-buying it, so a partial line
    occupies a whole slot and the capital that slot was meant to carry stays parked. §3.5 has no
    top-up rule — a name is bought once, at weight, and never bought again — so nothing here is
    ordered and §0.3 leaves the ruling with Zak.

    It belongs in the BRIEF and not only on the sheet, because the sheet says what to execute and
    this is the thing there is nothing to execute about: at the seed it decides how much of the
    account actually gets deployed, and a line nobody sees is a decision nobody makes.
    """
    ranked = [b for b in p["book"] or []
              if b.get("rank") is not None and b["ticker"] not in desk.PARKED
              and b.get("last_close") is not None
              and (b.get("account") or desk.ENGINE_ACCOUNT) == desk.ENGINE_ACCOUNT]
    nav = (p.get("nav") or {}).get("engine_nav")
    if not nav:
        # The shortfall needs a slot size and the slot size needs the NAV, so the arithmetic waits.
        # The FACT does not: a ranked holding at a fraction of a slot occupies that slot whatever
        # the NAV turns out to be, and saying nothing until the NAV lands hides the ruling behind
        # the thing it is waiting on.
        if not ranked:
            return []
        return ["", "## Held below §3.5's equal weight — pending an engine NAV",
                "  " + ", ".join(f"{b['ticker']} ({float(b['qty']):g} sh, rank {b['rank']})"
                                 for b in ranked),
                "  These occupy §3.5 slots. Whether each is AT its weight cannot be computed until",
                "  `config.engine_nav` is set — the slot is NAV/5. §3.5 fills FREE slots and keeps a",
                "  held name rather than re-buying it, so a partial line holds a whole slot and the",
                "  rest of that capital stays parked. **The ruling is Zak's (§0.3).**"]
    slot, short = float(nav) / engine.SLOTS, []
    for b in ranked:
        value = float(b["qty"]) * float(b["last_close"])
        if value < slot:
            short.append((b["ticker"], b["rank"], value, slot - value, value / slot))
    if not short:
        return []
    out = ["", "## Held below §3.5's equal weight — reported, NOT ordered"]
    for tk, rank, value, gap, pct in short:
        out.append(f"  {tk:<10} rank {rank:<3} {value:>12,.2f} of a {slot:,.2f} slot "
                   f"({pct:.0%}) — short {gap:,.2f}")
    out.append(f"  {len(short)} slot(s) count as filled while holding {sum(s[3] for s in short):,.2f}"
               f" less than their weight, so that much capital stays parked.")
    out.append("  §3.5 fills FREE slots and keeps a held name rather than re-buying it; it carries")
    out.append("  no top-up rule. Topping one up is a rebalance, which on a momentum book means")
    out.append("  trimming winners. **This one is Zak's (§0.3).**")
    return out


def dd_lines(p):
    """§5.2 — information, never action. The milestones are printed as milestones, and the sentence
    that says nothing happens at them is printed with them, every time."""
    n = p["nav"] or {}
    dd = n.get("drawdown")
    nav = f"{float(n['engine_nav']):,.2f}" if n.get("engine_nav") is not None else "**unknown**"
    marked = (f" · marked {float(n['marked_equity']):,.2f}"
              if n.get("marked_equity") is not None else "")
    out = [f"  engine NAV {nav}{marked}"]
    if dd is None:
        out.append("  drawdown — not yet measurable (no marked equity recorded)")
        return out
    hit = [m for m in DD_MILESTONES if dd <= m]
    out.append(f"  drawdown {_pct(dd)} from a peak of {float(n['peak']):,.2f}")
    if dd <= DD_PAGER:
        out.append("  ** −10% pager reached (§5.2) **")
    if hit:
        out.append("  milestones passed: " + ", ".join(f"{int(100 * m)}%" for m in hit))
    out.append("  §5.2: milestones are information. No mechanical intervention exists at any "
               "level; any intervention is Zak's explicit ruling in chat.")
    return out


def tranche_lines(p, frozen=False):
    """§2.3's ramp. Eligibility is stated, never acted on — every draw is Zak's (§0.2)."""
    out = []
    # Headroom across the OPEN facilities only. The first version took whichever row iterated last
    # — which is MARGIN, unopened, limit zero — and so reported 0.00 of headroom against a live
    # $37,500. §2.3: "the TFSA-secured LOC is the only live facility... HELOC and margin are not
    # opened; opening either is a law change." A facility with no limit is not open, so summing the
    # ones with a limit is the plan's own definition rather than a hardcoded account code, and it
    # stays right on the day a second one is opened.
    headroom = None
    for f in (p["facilities"] or []):
        head = f.get("headroom_to_cap")
        if head is not None and float(f.get("credit_limit") or 0) > 0:
            headroom = (headroom or 0.0) + float(head)
        out.append(f"  {f['account']}: drawn {float(f['drawn'] or 0):,.2f} of a "
                   f"{float(f['credit_limit'] or 0):,.2f} limit · cap {float(f['cap'] or 0):,.2f} "
                   f"(§2.3, 50%) · headroom to cap {float(head or 0):,.2f}")
    if not out:
        out.append("  no facility balance recorded — §2.3's cap is 50% of the LIMIT, and the "
                   "limit is Zak's to state (a `balances` row)")

    # §2.3's cap is HARD, and a ramp is a plan of draws — so the two can disagree arithmetically
    # without either being wrong on its own. Nothing else in the system compares them, and a $100
    # overshoot discovered at tranche three is discovered at the worst possible moment.
    remaining = [t for t in (p["tranches"] or []) if t["status"] == "planned"]
    planned = sum(float(t["amount_cad"]) for t in remaining)
    if headroom is not None and planned > headroom:
        out.append(f"  ** §2.3 BREACH AHEAD: {len(remaining)} planned tranche(s) total "
                   f"{planned:,.2f} against {headroom:,.2f} of headroom to the cap — over by "
                   f"{planned - headroom:,.2f}. The cap is hard; the ramp is a plan. One of them "
                   f"needs Zak's ruling before the last tranche. **")

    gate_on = (p["gate"] or {}).get("gate_on")
    for t in (p["tranches"] or []):
        when = f"{'~' if t['approximate'] else ''}{t['planned_on']}"
        if t["status"] == "drawn":
            out.append(f"  tranche {t['seq']}: ${float(t['amount_cad']):,.0f} — drawn {t['drawn_on']}")
        elif t["status"] == "skipped":
            out.append(f"  tranche {t['seq']}: ${float(t['amount_cad']):,.0f} — skipped; §2.3 "
                       f"shifts it one month, and never two tranches in one month")
        else:
            # §5.5 names levered tranches explicitly among the buys a freeze halts, so the freeze
            # is checked before the gate — a frozen tranche is held whatever the gate says.
            if frozen:
                why = "**held: FROZEN — §5.5 halts levered tranches with every other buy**"
            elif gate_on:
                why = "gate ON this week"
            else:
                why = "**held: §2.3 requires the gate ON that week**"
            out.append(f"  tranche {t['seq']}: ${float(t['amount_cad']):,.0f} planned {when} — {why}")
    return out


# §1, Zak's words: "Get to $5M as fast as possible, so I can retire and do whatever work I want —
# with no risk." §1 names the number and not the currency. NAV is reported in CAD everywhere in
# this system (`nav_snapshots.nav_cad`, §4.1's FX row), so the comparison is made in CAD and the
# assumption is PRINTED beside it rather than buried — at today's rates the two readings differ by
# about a third of the distance.
DESTINATION = 5_000_000.0
DESTINATION_CURRENCY = "CAD"


def saturday_lines(cur, p):
    """§4.1's weekly letter: "clinical: gate, rank stability, DD status, divergences, learnings,
    NAV vs the §1 destination"."""
    out = []
    g = p["gate"] or {}

    # Over the WHOLE record, not a window. §2.5's review checkpoint is "the first completed gate
    # cycle (ON→OFF→ON) or 12 months, whichever comes first", so the count that matters is the one
    # since the engine started — a rolling window would reset the very thing the checkpoint waits
    # for, and the window length would be a number nobody ruled.
    cur.execute("""select count(*) from (
                     select gate_on, lag(gate_on) over (order by session_date) as prev
                       from engine_sessions where mode='live') f
                    where prev is not null and gate_on is distinct from prev""")
    flips = cur.fetchone()[0]
    out.append(f"  gate {'ON' if g.get('gate_on') else 'OFF'} · {flips} flip(s) on record")

    # Rank stability across §3.5's fill band. Five sessions because a trading week is five
    # sessions and this is the weekly letter — the length of a week, not a tuned lookback.
    cur.execute("""select session_date, array_agg(ticker order by rank) as top
                     from engine_ranks where mode='live' and rank <= 12
                    group by session_date order by session_date desc limit 5""")
    week = cur.fetchall()
    if len(week) >= 2:
        newest, oldest = set(week[0][1]), set(week[-1][1])
        out.append(f"  rank stability: {len(newest & oldest)} of 12 names held the band from "
                   f"{week[-1][0]} to {week[0][0]} · in {sorted(newest - oldest)} · "
                   f"out {sorted(oldest - newest)}")
    else:
        out.append("  rank stability: fewer than two scored sessions — nothing to compare yet")

    n = p["nav"] or {}
    dd = n.get("drawdown")
    out.append(f"  drawdown {_pct(dd) if dd is not None else 'not yet measurable'}")

    # §6.4's divergences: the shadow scored the same close, and where the two disagree is the
    # attestation the shadow exists to produce. Every one on record, with no window — §6.4's pass
    # condition is "10/10 matches, or **every** divergence named and ruled", and a divergence that
    # aged off the bottom of a window would be one that was never named.
    cur.execute("""select l.session_date, l.gate_on, s.gate_on
                     from engine_sessions l join engine_sessions s
                       on s.session_date = l.session_date and s.mode = 'shadow'
                    where l.mode = 'live' and l.gate_on is distinct from s.gate_on
                    order by l.session_date""")
    diverged = cur.fetchall()
    out.append("  divergences (live vs shadow, on record): "
               + (", ".join(f"{d[0]} gate {d[1]}/{d[2]}" for d in diverged) if diverged
                  else "none on the gate"))

    household = (n.get("household") or {}).get("nav_cad")
    if household:
        pct = 100.0 * float(household) / DESTINATION
        out.append(f"  NAV vs the §1 destination: {float(household):,.0f} of "
                   f"{DESTINATION:,.0f} {DESTINATION_CURRENCY} ({pct:.1f}%)")
        out.append(f"    §1 names the number and not the currency; NAV is reported in "
                   f"{DESTINATION_CURRENCY} throughout this system, so the comparison is made there.")
    else:
        out.append("  NAV vs the §1 destination: no NAV snapshot recorded")
    return out


def render(p, frozen=False, words=None):
    g = p["gate"] or {}
    out = [f"# Yuna · {g.get('session_date') or 'no session'}", ""]
    if frozen:
        # Above the freshness line, because it governs everything below it. §5.5 is Zak's word and
        # the brief repeats it back to him rather than paraphrasing — a freeze lifted "only by
        # Zak's word" needs the original words legible to compare against.
        out.append("## ❄ FROZEN — buys halted (§5.5)")
        out.append(f"> {words}" if words else "> (no words recorded)")
        out.append("")
        out.append("Entries, refills, displacement buys and levered tranches are all halted. "
                   "**Exits fire normally and proceeds park** (§5.4, §5.5). Lifted only by "
                   "Zak's word.")
        out.append("")
    out.append(freshness_line(p))
    out += ["", gate_line(p), "", "## Order sheet (§4.3)", ""]
    out += sheet_lines(p)
    out += ["", "## Book (§4.2)", ""] + book_lines(p) + underweight_lines(p) + sleeve_lines(p)
    out += ["", "## NAV & drawdown (§5.2)", ""] + dd_lines(p)
    out += ["", "## Levered layer (§2.3)", ""] + tranche_lines(p, frozen=frozen)

    top = p["top12"] or []
    if top:
        out += ["", "## Top 12 (§3.3 — the rank is the entire opinion)", ""]
        out.append("  " + ", ".join(f"{t['ticker']}" for t in top))

    rec = p["reconciliation"] or {}
    out += ["", "## Reconciliation (§4.4)", "",
            f"  last receipt {rec.get('last_receipt') or '—'} · "
            f"last attested {rec.get('last_attested') or 'never'} · "
            f"{rec.get('awaiting_receipt') or 0} approved ticket(s) awaiting a receipt"]

    learn = p["learnings"] or []
    if learn:
        out += ["", "## Learnings in flight (§5.3)", ""]
        for l in learn:
            out.append(f"  [{l['status']}] {l['key']} — {l.get('hypothesis') or ''}")

    out += ["", "---", "Yuna proposes; Zak decides (§0.2). Nothing in this brief has been ordered."]
    return "\n".join(out)


def main():
    # §4.1: "Weekly: the Saturday letter." The slot comes from the chain, and `or` rather than a
    # default argument — a dead upstream job hands this down as an empty string.
    slot = (os.environ.get("COMPOSE_SLOT") or "nightly").strip().lower()
    with connect() as conn, Heartbeat(conn, "compose", dry_run=dry()) as hb:
        with conn.cursor() as cur:
            p = payload(cur)
            frozen, words, froze_at, _ = freeze_state(cur)
            report = render(p, frozen=frozen, words=words)
            if slot == "saturday":
                report += "\n\n## The week (§4.1)\n\n" + "\n".join(saturday_lines(cur, p))
        print(report)

        g = p["gate"] or {}
        session = g.get("session_date")
        hb.detail.update(session=str(session) if session else None, slot=slot,
                         gate="ON" if g.get("gate_on") else "OFF", frozen=frozen,
                         freeze_words=words, frozen_at=str(froze_at) if froze_at else None,
                         orders=len(p["order_sheet"] or []),
                         held=len(p["book"] or []))
        if session is None:
            # `briefs.session_date` is NOT NULL and there is no honest value for it here. A brief
            # dated today about a session that was never scored would be a record of a night that
            # did not happen, so the render prints and nothing is stored.
            hb.amber("no engine session has been scored — the brief was rendered but not stored, "
                     "because a brief needs the session date it describes")
        elif not dry():
            with conn.cursor() as cur:
                # One brief per (kind, session), REFRESHED rather than refused.
                #
                # The first version of this skipped the write when a brief already existed for the
                # session, which is wrong in the ordinary case and silently so: `check` runs before
                # `compose`, so a re-scored night legitimately produces a different verdict, a
                # different sheet and a different banner — and the desk would have kept serving the
                # first render of the night for ever. Worse, the retry ingest fires the whole chain
                # a second time by design, so the stale render was the NORMAL outcome, not the edge
                # case.
                #
                # Upsert on (kind, session_date): the session is the identity, the newest render
                # wins, and `at` moves with it so the ledger says when the desk last spoke.
                cur.execute("""insert into briefs (kind, session_date, freshness, summary, body,
                                                   detail)
                               values (%s, %s, %s, %s, %s, %s)
                               on conflict (kind, session_date)
                                   where (detail->>'engine') = 'v1' do update set
                                   freshness = excluded.freshness, summary = excluded.summary,
                                   body = excluded.body, detail = excluded.detail, at = now()
                               returning id""",
                            (slot, session, freshness_line(p).splitlines()[0],
                             f"gate {'ON' if g.get('gate_on') else 'OFF'} · "
                             f"{len(p['order_sheet'] or [])} order(s)",
                             report, json.dumps({"composed": True, "engine": "v1"})))
                wrote = cur.fetchone()
            conn.commit()
            hb.rows = 1 if wrote else 0

        if not p["check_report"]:
            hb.amber("no check has run — the brief carries no proof that tonight's numbers hold")
        elif p["check_report"].get("blocks_buys"):
            hb.amber("check is red: the brief ships the sheet with its buys held (§4.4, §5.4)")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
