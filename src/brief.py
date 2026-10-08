"""brief — §4.1's `compose`. The morning brief, rendered from the one payload read.

§5.1: "The morning brief renders: freshness · gate & latch · the order sheet · book with ranks &
P/L · DD status vs milestones · tranche schedule status. Judgment happens in chat; arithmetic
happens in the pipeline."

That division is the whole design of this file. It renders and it does not decide: every number
here was computed by `sheet`, checked by `gauges` and read back through `v_session_payload`. If a
figure appears in the brief that no other job wrote, this file has overstepped.

Two reads go past the payload, both information and neither a decision: the accounts' cash
(`db.cash_by_account`, the same anchor-plus-ledger arithmetic the engine's NAV is made of, §2.4)
and the Saturday letter's household NAV against §1's destination (§4.1). Neither sizes, holds or
releases anything.

    DATABASE_URL=... python src/brief.py
    DATABASE_URL=... DRY_RUN=true python src/brief.py     # render, print, write nothing

**Nothing here places an order** (§0.2). The sheet is a proposal; Zak executes at the open.
"""
import datetime as dt
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import desk                                                                # noqa: E402
import engine                                                              # noqa: E402
from db import cash_by_account, connect, dry, freeze_state, Heartbeat      # noqa: E402

# §4.3's ticket states. The payload's `order_sheet` carries only the two a ticket can be acted on
# in — proposed, approved — and everything else on the session arrives as `not_orders` (migration
# 068). Of those, these two are WITHDRAWN: the engine or Zak took the proposal back, so its side of
# the sheet never happens. `executed` and `reconciled` are done, which is a different thing.
WITHDRAWN = ("cancelled", "expired")

# §5.2, verbatim: "Pager at −10% engine DD; informational lines at −20 / −30 / −40 / −50. **No
# mechanical intervention exists at any level.**" The pager threshold and the informational ladder
# are the plan's, and the absence of any action at any of them is also the plan's — chosen, in the
# plan's own words, "with the three numbers in view".
DD_PAGER = -0.10
DD_MILESTONES = (-0.20, -0.30, -0.40, -0.50)

# §5.2's drawdown record (2026-09-02), quoted from the plan and never derived here — §0.4 gives
# the brief a payload and no cursor. Run 624 is the cell of record on 2007-01-12 → 2026-09-01
# with the SPY park, 4,940 sessions: the share of them that sat at or below each milestone, and
# how its two worst troughs ended. Zak: "the most important piece is having something to tell me
# and remind me... that's likely what you're gonna experience sixty percent of the time."
DD_RECORD_RUN = 624
DD_RECORD_SESSIONS = 4940
DD_RECORD_SHARE = {-0.10: 0.684, -0.20: 0.476, -0.30: 0.262, -0.40: 0.111, -0.50: 0.015}
DD_RECORD_TROUGHS = (
    dict(depth=-0.603, trough="2009-03-09", new_high="2013-09-10", took="four and a half years"),
    dict(depth=-0.459, trough="2025-11-21", new_high="2026-04-30", took="five months"),
)


def payload(cur):
    cur.execute("select * from v_session_payload")
    cols = [d[0] for d in cur.description]
    p = dict(zip(cols, cur.fetchone()))
    # The payload view predates the derived NAV (2026-08-19): its nav block only knows
    # `config.engine_nav`, so when the engine DERIVED tonight's number the block reads unknown
    # while the sheet upstairs is fully sized — a brief contradicting its own order sheet. The
    # number the engine actually used is stored on the session row, so it is read from there.
    # This is the pipeline reading its own stored output, not chat-side arithmetic (§0.4); folding
    # it into v_session_payload proper is a later migration.
    #
    # The session it came from rides with it: when tonight's NAV is unknown this is an EARLIER
    # session's number, and the brief says so rather than printing it as tonight's.
    nav = p.get("nav") or {}
    if not nav.get("engine_nav"):
        cur.execute("""select nav, session_date from engine_sessions
                        where mode = 'live' and nav is not null
                        order by session_date desc limit 1""")
        row = cur.fetchone()
        if row and row[0]:
            p["nav"] = dict(nav, engine_nav=float(row[0]),
                            engine_nav_source=f"session {row[1]}")
    # §3.5 (R2): held names the newest live sheet found with no bar on its session. Each keeps its
    # slot and its quantity, so its missing rank is not "outside §3.2's universe" (`book_lines`).
    cur.execute("""select detail->'unbarred' from engine_sessions where mode = 'live'
                    order by session_date desc limit 1""")
    row = cur.fetchone()
    p["unbarred"] = list((row[0] if row else None) or [])
    return p


def _pct(x, places=1):
    return "—" if x is None else f"{100.0 * float(x):+.{places}f}%"


def check_hold(p):
    """Does tonight's check hold the buys? Returns (holds, why); `why` is None when it does not.

    §4.4: "Any red holds buys; nothing holds exits." §4.3: "Red pipeline: no new buy tickets." The
    check is the one job that PROVES tonight's numbers, so only a completed verdict on tonight's
    session can let a buy through, and anything short of one holds the buys the way a red does:
    no check for this session at all, a check still `running`, or a check that crashed (Heartbeat's
    red) or died before its heartbeat (report_fail's row) and so never wrote a verdict. Keyed on
    `blocks_buys` alone, those last three printed a bare "check RED" over sized buys and compose
    closed green (A20) — `blocks_buys` is written only by a check that finished.

    `check_report` arrives anchored to tonight's live session (migration 068: live, not dry, begun
    after the session row was written). The session is compared here as well, so a payload that is
    not anchored can only ever hold the buys, never release them.
    """
    session = (p.get("gate") or {}).get("session_date")
    c = p.get("check_report")
    if not c:
        if session is None:
            return True, "no engine session has been scored, so no check can have proved one"
        return True, f"no check for session {session}"
    status = str(c.get("status") or "").lower()
    verdict = str(c.get("verdict") or "").lower()
    if status == "running":
        return True, "the check is still running, so it has proved nothing yet"
    if verdict not in ("green", "amber", "red"):
        return True, "the check did not complete, so it proved nothing" + (
            f" ({c['fatal']})" if c.get("fatal") else "")
    if c.get("session") and session and str(c["session"]) != str(session):
        return True, f"the newest check proved session {c['session']}, not {session}"
    if verdict == "red":
        return True, "check is red"
    if status == "red":
        return True, f"the check job ended red after a {verdict} verdict" + (
            f" ({c['fatal']})" if c.get("fatal") else "")
    if c.get("blocks_buys"):
        return True, "the check says its verdict blocks buys"
    return False, None


def freshness_line(p):
    """§5.1's first line. A red check holds BUYS; §5.4 makes exits unblockable, so the sheet still
    ships and the banner says which half of it may be acted on. A check that did not deliver a
    verdict on this session holds them the same way, and says why (`check_hold`)."""
    c = p.get("check_report")
    holds, why = check_hold(p)
    if not c:
        return (f"✗ {why} — **buys held; exits stand** (§0.4, §4.4, §5.4)\n"
                f"    · nothing has proved tonight's numbers")
    status = str(c.get("status") or "").lower()
    if "red" in (status, str(c.get("verdict") or "").lower()):
        word = "RED"
    else:
        word = str(c.get("verdict") or c.get("status") or "?").upper()
    if holds:
        # A green mark over held buys would contradict its own banner, so a hold is never ✓/⚠.
        mark = "?" if status == "running" else "✗"
    else:
        mark = {"GREEN": "✓", "AMBER": "⚠", "RED": "✗"}.get(word, "?")
    line = f"{mark} check {word}"
    if holds:
        line += " — **buys held; exits stand** (§4.4, §5.4)"
        if why != "check is red":
            line += f"\n    · {why}"
    for reason in (c.get("red") or []) + (c.get("amber") or []):
        line += f"\n    · {reason}"
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


BELOW_WEIGHT = re.compile(r"below §3\.5 weight: [\d,]+ of [\d,]+ shares")


def sheet_lines(p):
    """§4.3's sheet. Sells first — §3.5 executes them first, and the order on the page is the
    order at the open.

    Only tickets that can still be acted on reach this function: the payload's `order_sheet` is
    proposed and approved, nothing else (migration 068). A withdrawn proposal is not an order
    (learning 57) and an executed one is not one any more; both print in `not_order_lines`, below
    the sheet and never on it."""
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
            # §3.5 (v1.1): a fill below slot weight counts as filled and is never topped up, so the
            # page says which buys are short of their slot. The desk writes it into the note.
            below = BELOW_WEIGHT.search(r.get("note") or "")
            tag = f"   ({below.group(0)}; never topped up)" if below else ""
            out.append(f"  BUY  {r['ticker']:<10} qty {qty}   "
                       f"rank {r['rank']}   mark {mark}   [{r['state']}]{tag}")
    out.append("")
    out.append("  Zak executes at the open: sells first, then buys (§3.5). Market orders; no GTC "
               "orders exist anywhere in this system (§4.3).")
    return out


def not_order_lines(p):
    """Tonight's tickets that are NOT orders, in a block of their own (A10).

    §4.3: "The nightly sheet is the only source of engine orders." A re-score withdraws what it no
    longer stands behind (`sheet.write_tickets` cancels, never deletes), Zak can cancel one in
    chat, and a ticket he has executed is done. On 2026-08-17 all of them printed as SELL and BUY
    lines under the sheet, one of them a sell whose own note said "already executed ... do not
    execute", under a banner that told him the exits stand.

    They still print — the brief is refreshed in place, so a buy the first chain proposed and the
    retry withdrew is one Zak may already have read — but ticker first, never in the order line's
    shape, under a heading that says what they are.
    """
    rows = p.get("not_orders") or []
    if not rows:
        return []
    out = ["", "## Not orders — withdrawn or already done; do not execute (§4.3)", ""]
    for r in rows:
        qty = _qty(r["qty"]) if r.get("qty") is not None else "—"
        what = "withdrawn" if r["state"] in WITHDRAWN else "already done"
        out.append(f"  {r['ticker']:<10} {r['action']} {qty} — {what} [{r['state']}]")
    return out


def _qty(q):
    """A share count as the ledger holds it: whole shares plain, fractional ones to four places."""
    q = float(q)
    return f"{q:,.0f}" if q == int(q) else f"{q:,.4f}".rstrip("0").rstrip(".")


def tonight_sells(p):
    """Every ticker tonight's sheet sells: the live sells, and any already executed. A withdrawn
    sell is not one — the engine took it back, so the name stays."""
    rows = (p.get("order_sheet") or []) + (p.get("not_orders") or [])
    return {r["ticker"] for r in rows if r["action"] == "sell" and r["state"] not in WITHDRAWN}


def book_lines(p):
    """The book, and what the engine intends to do about each line.

    Two notes hang off an unranked holding and they mean opposite things, which is why the brief
    has to tell them apart. A `.US` common stock that has left §3.2's universe — delisted, or newly
    excluded — is queued to sell, because §3.5 queues anything below rank 12 and "not ranked at all"
    is below it. The PARK is unranked for a different reason: it was never eligible, it is where
    §3.4 puts the money while the gate is off, and it is never sold for failing to rank.

    Printing the first note against the park is not a cosmetic slip. It reads as "this 810-share
    position is queued to sell", which is the opposite of what §6.5 is holding it for.

    The ACCOUNT is read before the instrument (A69). `desk.PARKED` names SPMO.US because §6.1(3)
    parked the engine's capital in it inside the TFSA; the same instrument in the RRSP is §2.2's
    Reserve — "SPMO in the RRSP" — and §8 defines the park as SPY.US, where ENGINE capital sits.
    Checked instrument-first, every brief since the bridge was sold told Zak his RRSP reserve was
    engine capital.
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
                   f"   last {last} {b.get('currency') or '?'}   P/L {pnl}   rank {rank}"
                   f"   {b.get('account') or '?'}/{b['sleeve']}")
        if b.get("last_close") is None:
            out.append("      ** no mark: this position is not priced in this store, so it is NOT "
                       "in the marked equity below **")
        if b.get("rank") is not None:
            continue
        # Three reasons a holding has no rank, and they mean three different things. Printing one
        # note for all of them told Zak the engine was about to sell 810 shares of the Phase-0
        # bridge and 140 of the levered layer, neither of which it has any authority over.
        account = b.get("account") or desk.ENGINE_ACCOUNT
        if account != desk.ENGINE_ACCOUNT:
            # §2.1's table names the wrapper's purpose; `desk.SLEEVES_BY_ACCOUNT` is that table.
            role = " + ".join(desk.SLEEVES_BY_ACCOUNT.get(account, ())) or "outside §2.1's table"
            out.append(f"      {account} — {role} per §2.1's table, not engine capital. §2.1 puts "
                       f"the engine in the {desk.ENGINE_ACCOUNT} and nowhere else; the engine "
                       f"neither ranks nor trades this")
        elif b["ticker"] in desk.PARKED:
            out.append("      park — engine capital, never a slot and never sold for failing to "
                       "rank (§3.4, §6.1(3))")
        elif b["ticker"] in (p.get("unbarred") or []):
            # R2 (Zak's ruling of 2026-10-07): no bar on the decision session is not a bad rank.
            out.append("      ** no bar on the decision session: it keeps its slot and its"
                       " quantity, not a rank exit, and buys are held until Zak records what"
                       " happened **")
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
    occupies a whole slot and the capital that slot was meant to carry stays parked. §3.5, as v1.1
    amended it: "A slot filled below weight counts as filled and is reported; it is never topped
    up." So nothing here is ordered, and nothing waits on a ruling: this is the report.

    It belongs in the BRIEF and not only on the sheet, because the sheet says what to execute and
    this is the thing there is nothing to execute about: at the seed it decides how much of the
    account actually gets deployed, and a line nobody sees is a decision nobody makes.

    A name tonight's sheet SELLS is not kept, so it occupies no slot after the open and is left
    out (A25): a rank exit, the displaced name, the whole book on a gate-off. Counted, it asked Zak
    to rule on topping up a position the same page told him to sell — 2026-10-05, WDC.US at rank
    14 — and overstated the parked shortfall by 108%.
    """
    selling = tonight_sells(p)
    ranked = [b for b in p["book"] or []
              if b.get("rank") is not None and b["ticker"] not in desk.PARKED
              and b["ticker"] not in selling
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
                "  rest of that capital stays parked. §3.5 (v1.1): counted as filled, reported,",
                "  never topped up."]
    slot, short = float(nav) / engine.SLOTS, []
    for b in ranked:
        value = float(b["qty"]) * float(b["last_close"])
        if value < slot:
            short.append((b["ticker"], b["rank"], value, slot - value, value / slot))
    if not short:
        return []
    out = ["", "## Held below §3.5's equal weight — reported, NOT ordered"]
    for tk, rank, value, gap, pct in short:
        out.append(f"  {tk:<10} rank {rank:<3} {value:>12,.2f} of a {slot:,.2f} USD slot "
                   f"({pct:.0%}) — short {gap:,.2f}")
    out.append(f"  {len(short)} slot(s) count as filled while holding {sum(s[3] for s in short):,.2f}"
               f" USD less than their weight, so that much capital stays parked.")
    out.append("  §3.5 (v1.1): a slot filled below weight counts as filled and is reported; it is")
    out.append("  never topped up. Topping one up would be a rebalance, which on a momentum book")
    out.append("  means trimming winners.")
    return out


def nav_source_note(n):
    """Where tonight's engine NAV came from, in words. §3.5 sizes USD orders off it whatever its
    source, so an override is named as one: a CAD figure typed into `config.engine_nav` would size
    every buy too large by the whole USDCAD rate, and the brief is where Zak would see it (A55)."""
    if n.get("engine_nav_source"):           # brief.payload's fallback: an earlier session's NAV
        return f" — from {n['engine_nav_source']}; tonight's is unknown"
    source = (n.get("nav_source") or {}).get("source")
    return {"derived": " (derived: positions + TFSA cash)",
            "config": " (config.engine_nav — Zak's override, sized as USD)",
            "env": " (ENGINE_NAV — a dispatch override, sized as USD)"}.get(source, "")


def dd_lines(p):
    """§5.2 — information, never action. The milestones are printed as milestones, and the sentence
    that says nothing happens at them is printed with them, every time.

    "Pager at −10% engine DD": the drawdown is measured on engine NAV — positions plus TFSA cash,
    the number §3.5 sizes against — and not on the positions alone (migration 068, A28). Cash
    between a sell and its buy is not a loss. On the positions-only series an exit whose buy is
    held reads about −18% for a night and a gate-off whose proceeds sit in cash reads −100%; on
    2026-09-16 US$1,459 of residue cash fired the pager at an engine-NAV drawdown of −9.89%.

    Every figure here is USD, and says so (A55). Engine NAV is the TFSA sleeve priced in USD
    (`desk.derived_engine_nav`); the household, in CAD, is the Saturday letter's.
    """
    n = p["nav"] or {}
    dd = n.get("drawdown")
    nav = (f"{float(n['engine_nav']):,.2f} USD{nav_source_note(n)}"
           if n.get("engine_nav") is not None else "**unknown**")
    marked = (f" · positions marked {float(n['marked_equity']):,.2f} USD"
              if n.get("marked_equity") is not None else "")
    out = [f"  engine NAV {nav}{marked}"]
    if dd is None:
        out.append("  drawdown — not measurable: this session has no engine NAV to measure it on")
        return out + record_lines(None)
    hit = [m for m in DD_MILESTONES if dd <= m]
    out.append(f"  drawdown {_pct(dd)} from an engine-NAV peak of {float(n['peak']):,.2f} USD")
    if dd <= DD_PAGER:
        out.append("  ** −10% pager reached (§5.2) **")
    if hit:
        out.append("  milestones passed: " + ", ".join(f"{int(100 * m)}%" for m in hit))
    out.append("  §5.2: milestones are information. No mechanical intervention exists at any "
               "level; any intervention is Zak's explicit ruling in chat.")
    return out + record_lines(dd)


def record_lines(dd):
    """§5.2's drawdown record, printed beside the number every session (2026-09-02).

    Zak asked for the thing that has comforted him before — not that the names held today come
    back, which the record does not say, but how often the cell of record sat this deep and how
    its worst troughs ended. The shares and dates are the plan's (§5.2, run 624); nothing here is
    computed from the store.
    """
    ten = DD_RECORD_SHARE[-0.10]
    passed = [m for m in sorted(DD_RECORD_SHARE) if dd is not None and dd <= m]
    if passed:
        deepest = passed[0]
        first = (f"  the record (§5.2, run {DD_RECORD_RUN}): a book at least "
                 f"{abs(int(round(deepest * 100)))}% below its high is {DD_RECORD_SHARE[deepest]:.1%} "
                 f"of the cell of record's {DD_RECORD_SESSIONS:,} sessions; at least 10% below "
                 f"is {ten:.1%}")
    else:
        first = (f"  the record (§5.2, run {DD_RECORD_RUN}): the cell of record sat at least 10% "
                 f"below its high in {ten:.1%} of its {DD_RECORD_SESSIONS:,} sessions; today is "
                 f"one of the other {1 - ten:.1%}")
    worst, since = DD_RECORD_TROUGHS
    return [first,
            f"  its worst trough, {worst['depth']:.1%} on {worst['trough']}, made a new high on "
            f"{worst['new_high']}, {worst['took']} later; the worst since, {since['depth']:.1%} on "
            f"{since['trough']}, made one on {since['new_high']}, {since['took']} later",
            "  the bet is the rotation, not the name: the record says the book recovered every "
            "time, and says nothing about the names it held at the trough"]


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

    # §2.3, verbatim: "Each tranche requires the gate (§3.4) ON that week; a skipped tranche shifts
    # one month; never two tranches in one month." THAT week is the tranche's own — the week of its
    # planned date — so tonight's gate is stated beside the tranche and never read as permission
    # outside it (A71): "gate ON this week" printed against a tranche planned a month out, and would
    # have printed against one whose week had passed with the gate OFF, which §2.3 has already
    # moved a month on. The week is the calendar week of the planned date; whether a passed week
    # was a skip, and where the shifted tranche lands, are Zak's to record — the ladder is his
    # ledger and nothing here writes it.
    g = p["gate"] or {}
    gate_on = g.get("gate_on")
    session = _date(g.get("session_date"))
    tranches = p["tranches"] or []
    drawn = [(t["seq"], _date(t["drawn_on"])) for t in tranches
             if t["status"] == "drawn" and t.get("drawn_on")]
    for t in tranches:
        amount = f"${float(t['amount_cad']):,.0f}"
        when = f"{'~' if t['approximate'] else ''}{t['planned_on']}"
        if t["status"] == "drawn":
            # `amount_cad` is the PLAN's figure; the ladder has no column for what was drawn, and
            # the facility line above is the balance. Printed as drawn, two C$12,000 draws read as
            # C$25,000 one line below a facility drawn 24,000.00.
            out.append(f"  tranche {t['seq']}: drawn {t['drawn_on']} against a planned {amount} — "
                       f"the amount drawn is the facility's balance above, not this line's")
            continue
        if t["status"] == "skipped":
            out.append(f"  tranche {t['seq']}: {amount} — skipped; §2.3 shifts it one month, and "
                       f"never two tranches in one month")
            continue
        planned = _date(t["planned_on"])
        week = planned - dt.timedelta(days=planned.weekday())
        twin = [(seq, d) for seq, d in drawn if (d.year, d.month) == (planned.year, planned.month)]
        # §5.5 names levered tranches explicitly among the buys a freeze halts, so the freeze is
        # checked before the gate — a frozen tranche is held whatever the gate says.
        if frozen:
            why = "**held: FROZEN — §5.5 halts levered tranches with every other buy**"
        elif twin:
            why = (f"**held: §2.3 — never two tranches in one month; tranche {twin[0][0]} was "
                   f"drawn {twin[0][1]}**")
        elif session is None:
            why = "no session has been scored, so the gate is unread"
        elif session < week:
            why = (f"its week (of {week}) has not come; tonight the gate reads "
                   f"{'ON' if gate_on else 'OFF'}, and §2.3 needs it ON that week")
        elif session <= week + dt.timedelta(days=6):
            why = ("this is its planned week and the gate is ON (§2.3)" if gate_on
                   else "**held: §2.3 requires the gate ON that week — it is OFF**")
        else:
            why = (f"**its planned week (of {week}) has passed undrawn — §2.3: a skipped tranche "
                   f"shifts one month; whether this one was skipped, and its new date, are "
                   f"Zak's to record**")
        out.append(f"  tranche {t['seq']}: {amount} planned {when} — {why}")
    return out


def _date(x):
    """A date from the payload, which carries dates as ISO strings inside its JSON items."""
    if x is None or isinstance(x, dt.date):
        return x
    return dt.date.fromisoformat(str(x)[:10])


# §2.3: "Every draw purchases VXC.TO in the NONREG the same day — one draw, one purchase." The
# account a facility draw lands in, quoted rather than inferred.
LEVERED_ACCOUNT = "NONREG"


def account_cash(cur):
    """Each account's cash: `db.cash_by_account`, with §2.3's draws put where §2.3 puts them.

    `cash_by_account` is the one definition — the newest `balances` anchor, carried forward by the
    ledger's trades, the arithmetic the engine's NAV is made of. A trade moves cash; a facility
    draw is not a trade, so the levered account's carried cash pays for every VXC.TO purchase and
    never receives the draw that funded it. Production, 2026-09-22: the second tranche bought 139
    VXC.TO for C$11,995.70 out of a NONREG anchored at C$37.01 on 08-17, and the carried figure read
    −C$11,958.69 against a real C$41.31 — while the LOC's newer reading had already taken the
    C$12,000 draw onto the debt side. §2.3 says where every draw goes, so the facilities' drawn
    balance since the levered account's own anchor is credited there: borrowing is NAV-neutral at
    the moment of use (`cash_by_account`), and this is what keeps it so when the facility has been
    read more recently than the account.

    Returns {account: dict} as `cash_by_account` does; the levered account gains
    `draws_since_anchor` (CAD), or `draws_unknown` naming a facility with no reading on or before
    its anchor, which leaves its cash uncorrected and says so. "Drawn now" is the facility's own
    `cash_by_account` entry — the same figure `household_nav` subtracts as debt.
    """
    cash = {a: dict(c) for a, c in cash_by_account(cur).items()}
    lev = cash.get(LEVERED_ACCOUNT)
    if lev is None or lev.get("as_of") is None:
        return cash
    cur.execute("""select a.code,
                          (select b.drawn from balances b
                            where b.account = a.code and b.drawn is not null and b.as_of <= %s
                            order by b.as_of desc, b.id desc limit 1)
                     from accounts a where a.kind = 'facility' order by a.code""",
                (lev["as_of"],))
    since, unknown = 0.0, []
    for code, then in cur.fetchall():
        now = (cash.get(code) or {}).get("drawn")
        if now is None:
            continue
        if then is None:
            unknown.append(code)
            continue
        since += float(now) - float(then)
    if unknown:
        lev["draws_unknown"] = unknown
    elif since:
        lev["draws_since_anchor"] = round(since, 2)
        lev["cad"] = float(lev.get("cad") or 0) + since
    return cash


def recorded_splits(cur, session):
    """The splits `reconcile` wrote into the ledger since the sheet before `session` was scored.

    Zak's ruling of 2026-10-07 ("Pipeline records splits") has the brief show each one. `reconcile`
    runs before `score`, so a split recorded tonight was written after the previous session's row
    and before tonight's: it prints on tonight's brief, and on no brief after the next sheet. Each
    row's note is the run's own line for it (migration 075) — the shares and the cost per share
    before and after, no cash moved, and the raw closes that agree with the ratio.
    """
    cur.execute("""select t.account, t.ticker, t.qty as ratio, t.trade_date as ex_date, t.note
                     from transactions t
                    where t.side = 'split' and t.superseded_by is null
                      and t.confirmed_at > coalesce(
                            (select s.created_at from engine_sessions s
                              where s.mode = 'live' and s.session_date < %s
                              order by s.session_date desc limit 1), '-infinity')
                    order by t.trade_date, t.account, t.ticker""", (session,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def split_lines(splits):
    """One line per split recorded since the last sheet, above the book it restated."""
    out = []
    for s in splits or []:
        said = s["note"] or (f"{s['account']} {s['ticker']} split x{float(s['ratio']):g}, "
                             f"ex {s['ex_date']}")
        out.append(f"  split recorded: {said}")
    return out + [""] if out else []


def cash_lines(cash, session):
    """§2.4: "Cash that is not awaiting a same-week engine order sits in the account's designated
    holding." Information, never a ticket — §0.2 leaves every order to Zak, and §2.4 names no
    amount below which cash may sit, so none is applied here (A72).

    Nothing showed account cash before this. The C$584.87 the RRSP was anchored with on 2026-08-17
    sat seven weeks without a line in any brief, and the anchors' own age — the one thing that says
    how far to trust a carried figure — was printed nowhere.
    """
    accounts = [(a, c) for a, c in sorted(cash.items()) if c.get("kind") != "facility"]
    out = ["", "## Cash (§2.4 — information; nothing here is ordered)", ""]
    if not accounts:
        out.append("  no cash anchor on record (`balances`) — §2.4 cannot be read without one")
        return out
    day = _date(session)
    for acct, c in accounts:
        as_of = _date(c.get("as_of"))
        age = f", {(day - as_of).days} days before this session" if day and as_of else ""
        line = (f"  {acct:<8} {float(c.get('cad') or 0):>12,.2f} CAD · "
                f"{float(c.get('usd') or 0):>10,.2f} USD   anchor {as_of}{age}")
        if c.get("draws_since_anchor"):
            line += (f"; includes {c['draws_since_anchor']:,.2f} CAD drawn on the facility since "
                     f"it (§2.3)")
        if c.get("draws_unknown"):
            line += (f"; ** no {', '.join(c['draws_unknown'])} reading on or before this anchor, so "
                     f"draws since it are not counted **")
        out.append(line)
    out.append("  An anchor is a reading; the ledger carries it forward by trades only — deposits,")
    out.append("  dividends and interest wait for the next anchor. §2.4: cash not awaiting a")
    out.append("  same-week engine order sits in the account's designated holding (§2.1: RRSP SPMO,")
    out.append("  NONREG VXC.TO). Every order is Zak's (§0.2).")
    return out


def household_nav(cur, session, cash):
    """§4.1's "NAV vs the §1 destination", from the store as it stands. Returns (dict, None) or
    (None, why).

    Everything held, at its last close on or before the session; every account's cash
    (`account_cash`); less what the facilities are drawn. USD converts at the session's USDCAD.

    The letter used to print the newest `nav_snapshots` row, and the only writer of that table is
    the retired `arming.py`: seven letters, 2026-08-22 to 10-03, printed the same provisional
    2026-08-15 snapshot of the pre-liquidation book — 204,109 CAD (4.1%), its debt still the legacy
    C$7,980 — with nothing to say it was seven weeks old (A50).

    Fails closed rather than understating: a holding with no close, or a currency with no rate,
    makes the number unknown, and the letter says which.
    """
    s = str(session)
    cur.execute("""select close, d from prices where ticker = 'USDCAD.FOREX' and d <= %s
                    order by d desc limit 1""", (s,))
    row = cur.fetchone()
    fx, fx_on = (float(row[0]), row[1]) if row and row[0] else (None, None)
    rate = {"CAD": 1.0, "USD": fx}
    cur.execute("""select b.account, b.ticker, coalesce(b.currency, 'USD'), b.qty, p.close
                     from book b
                     left join lateral (select close from prices
                                         where ticker = b.ticker and d <= %s
                                         order by d desc limit 1) p on true
                    where b.status = 'open'""", (s,))
    positions = cur.fetchall()
    unpriced = sorted({tk for _, tk, _, _, close in positions if close is None})
    if unpriced:
        return None, f"no close on or before {s} for {', '.join(unpriced)}"
    accounts = {a: c for a, c in cash.items() if c.get("kind") != "facility"}
    unanchored = sorted({a for a, *_ in positions} - set(accounts))
    if unanchored:
        return None, f"no cash anchor for {', '.join(unanchored)} — its cash is unknown"
    blind = sorted({f for c in accounts.values() for f in c.get("draws_unknown") or ()})
    if blind:
        return None, (f"no {', '.join(blind)} reading on or before the {LEVERED_ACCOUNT} anchor, "
                      f"so the draws since it cannot be put against the debt")
    if not positions and not accounts:
        return None, "nothing held and no cash anchor on record"
    needs = {ccy for _, _, ccy, _, _ in positions} | (
        {"USD"} if any(float(c.get("usd") or 0) for c in accounts.values()) else set())
    missing = sorted(ccy for ccy in needs if rate.get(ccy) is None)
    if missing:
        return None, f"no {', '.join(missing)}→CAD rate on or before {s}"
    held = sum(float(q) * float(close) * rate[ccy] for _, _, ccy, q, close in positions)
    money = sum(float(c.get("cad") or 0) + float(c.get("usd") or 0) * (fx or 0.0)
                for c in accounts.values())
    debt = sum(float(c.get("drawn") or 0) for c in cash.values() if c.get("kind") == "facility")
    return dict(nav_cad=held + money - debt, held_cad=held, cash_cad=money, debt_cad=debt,
                fx=fx, fx_on=fx_on,
                anchors=sorted({str(c.get("as_of")) for c in accounts.values()})), None


# §1, Zak's words: "Get to $5M as fast as possible, so I can retire and do whatever work I want —
# with no risk." §1 names the number and not the currency. The household is measured in CAD (every
# account is Canadian, and so is the facility), so the comparison is made in CAD and the assumption
# is PRINTED beside it rather than buried — at today's rates the two readings differ by about a
# third of the distance. Engine NAV is the other measure, and it is USD (`dd_lines`).
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
                     from engine_ranks where mode='live' and rank <= %s
                    group by session_date order by session_date desc limit 5""",
                (engine.FILL_BAND,))                   # §3.5's band, from the one place it lives
    week = cur.fetchall()
    if len(week) >= 2:
        newest, oldest = set(week[0][1]), set(week[-1][1])
        out.append(f"  rank stability: {len(newest & oldest)} of {engine.FILL_BAND} names held the band from "
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

    session = (p.get("gate") or {}).get("session_date")
    house, why = (household_nav(cur, session, account_cash(cur)) if session
                  else (None, "no session has been scored"))
    if house:
        pct = 100.0 * house["nav_cad"] / DESTINATION
        out.append(f"  NAV vs the §1 destination: {house['nav_cad']:,.0f} of "
                   f"{DESTINATION:,.0f} {DESTINATION_CURRENCY} ({pct:.1f}%)")
        rate = f", USDCAD {house['fx']:.4f} of {house['fx_on']}" if house["fx"] else ""
        out.append(f"    every account at the {session} closes{rate}: holdings "
                   f"{house['held_cad']:,.0f} + cash {house['cash_cad']:,.0f} (anchored "
                   f"{', '.join(house['anchors']) or '—'}, carried by the ledger) − facility "
                   f"{house['debt_cad']:,.0f}")
        out.append(f"    §1 names the number and not the currency; the household is measured in "
                   f"{DESTINATION_CURRENCY}, so the comparison is made there. Engine NAV above is "
                   f"the TFSA alone, in USD.")
    else:
        out.append(f"  NAV vs the §1 destination: not computable — {why}")
    return out + exclusion_lines(p)


def exclusion_lines(p):
    """§3.2: "The live table is surfaced in the payload and the Saturday letter." It was in the
    payload and in no letter (A43): SGI.US — Somnigroup, a live common stock — was excluded on
    2026-08-12 to "keep TPX", a line whose last bar is 2025-02-14, and seven letters went by
    without the row appearing once.

    Every row, as the payload carries it, with the excluded line's own last bar beside its reason:
    §3.2 keeps "the line still printing", so the date is the fact a reader checks the reason
    against. Nothing is judged here — an exclusion that removes a real, tradable common stock for
    an editorial reason is a strategy change, and that ruling is Zak's (§3.2).
    """
    rows = p.get("exclusions") or []
    out = [f"  exclusions (§3.2 — the live table, {len(rows)} row(s); data hygiene only, and "
           f"excluding a real, tradable common stock for any editorial reason needs a ruling):"]
    for e in rows:
        out.append(f"    {e['ticker']:<12} {e['reason']:<18} last bar {e.get('last_bar') or '—'}"
                   f" · {e.get('detail') or ''}")
    if not rows:
        out.append("    none")
    return out


def render(p, frozen=False, words=None, cash=None, splits=None):
    """The brief. `cash` is `account_cash`'s read, passed in by `main` because the payload does not
    carry it; without it the cash section is left out rather than printed empty. `splits` is
    `recorded_splits`' read, passed in the same way."""
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
    out += sheet_lines(p) + not_order_lines(p)
    out += ["", "## Book (§4.2)", ""] + split_lines(splits) + book_lines(p)
    out += underweight_lines(p) + sleeve_lines(p)
    out += ["", "## NAV & drawdown (§5.2)", ""] + dd_lines(p)
    out += ["", "## Levered layer (§2.3) — CAD, as the draw and the purchase both are", ""]
    out += tranche_lines(p, frozen=frozen)
    if cash is not None:
        out += cash_lines(cash, g.get("session_date"))

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
            report = render(p, frozen=frozen, words=words, cash=account_cash(cur),
                            splits=recorded_splits(cur, (p["gate"] or {}).get("session_date")))
            if slot == "saturday":
                report += "\n\n## The week (§4.1)\n\n" + "\n".join(saturday_lines(cur, p))
        print(report)

        g = p["gate"] or {}
        session = g.get("session_date")
        # The count is of ORDERS: the payload's sheet is proposed and approved tickets only, so a
        # withdrawn or executed ticket is no longer "an order" in the summary notify sends (A10).
        orders = len(p["order_sheet"] or [])
        hb.detail.update(session=str(session) if session else None, slot=slot,
                         gate="ON" if g.get("gate_on") else "OFF", frozen=frozen,
                         freeze_words=words, frozen_at=str(froze_at) if froze_at else None,
                         orders=orders, not_orders=len(p.get("not_orders") or []),
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
                             f"gate {'ON' if g.get('gate_on') else 'OFF'} · {orders} order(s)",
                             report, json.dumps({"composed": True, "engine": "v1"})))
                wrote = cur.fetchone()
            conn.commit()
            hb.rows = 1 if wrote else 0

        # Amber on every hold, not only on a verdict that says red: a check that crashed, died
        # before its heartbeat, is still running or never ran for this session holds the buys
        # too, and compose closing green over it was the half of A20 nobody reads in the brief.
        holds, why = check_hold(p)
        if holds:
            hb.amber(f"{why}: the brief ships the sheet with its buys held (§4.4, §5.4)")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
