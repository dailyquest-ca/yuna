"""closeout — §6.2's system close-out. The old engine's state, retired in one pass.

    "**6.2 System close-out (Yuna, at score-green).** Sell rows for all seven; void all open
     tickets; retire all armed rows; close the book table to zero with a paper trail reconcile can
     read; close the six brewing learnings as *retired with engine*."

Five actions, one per clause, and one of them is deliberately NOT what it first reads as.

**"Close the book table to zero" is not this job zeroing the book.** §0.2 makes Zak the executor:
until he sells, the broker still holds those shares, and a book zeroed ahead of him would put
`reconcile` in the state it exists to detect — the book saying nothing where the broker says seven
positions. So this writes the SELL TICKETS and the book goes to zero through `reconcile`, when the
receipts land. That path — ticket → transaction → position closed — *is* "a paper trail reconcile
can read". Any other reading requires the system to act before Zak does.

    DATABASE_URL=... python src/closeout.py             # report what it would do
    DATABASE_URL=... CLOSEOUT_APPLY=true python src/closeout.py

Guarded rather than idempotent-by-upsert, because this runs once: a second pass with the book
already sold would write sell tickets for positions that no longer exist.

**Nothing here places an order** (§0.2). Every row it writes is a proposal in state `proposed`.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from db import connect, dry, Heartbeat                                     # noqa: E402

# §6.1(2), verbatim: "Sell at market: ANET 40 · NVDA 40.0437 · TSM 15.1647 · NUE 32 · ISRG 26 ·
# AVGO 30.0964 · CNQ.TO 142. (Names appear here as positions-to-liquidate only.)"
#
# Held as the PLAN's record of the position set, and cross-checked against the book rather than
# substituted for it. Where the two disagree, that is a finding — the plan was written on a date
# and the book has been maintained since, and neither is automatically the truth.
LIQUIDATE = {"ANET.US": 40.0, "NVDA.US": 40.0437, "TSM.US": 15.1647, "NUE.US": 32.0,
             "ISRG.US": 26.0, "AVGO.US": 30.0964, "CNQ.TO": 142.0}

# §6.2: "close the six brewing learnings as *retired with engine*."
RETIRED_WITH_ENGINE = "retired with engine"


def open_positions(cur):
    cur.execute("""select ticker, account, sleeve, qty from book
                    where status = 'open' order by ticker""")
    return [dict(ticker=t, account=a, sleeve=s, qty=float(q)) for t, a, s, q in cur.fetchall()]


def reconcile_against_the_plan(positions):
    """§6.1's list against the book. Returns (agreed, findings) — never a silent merge.

    Quantities are compared exactly as stated. §6.1 writes NVDA to four decimal places and AVGO to
    four, which is a DRIP'd position rather than a rounding artefact, so a mismatch at the fourth
    decimal is a real difference in shares and is reported as one.
    """
    held = {p["ticker"]: p["qty"] for p in positions}
    findings = []
    for tk, qty in sorted(LIQUIDATE.items()):
        if tk not in held:
            findings.append(f"{tk}: §6.1 lists {qty:g} shares and the book holds no open position")
        elif abs(held[tk] - qty) > 1e-6:
            findings.append(f"{tk}: §6.1 lists {qty:g}, the book holds {held[tk]:g} "
                            f"({held[tk] - qty:+g})")
    for tk in sorted(held):
        if tk not in LIQUIDATE:
            findings.append(f"{tk}: the book holds {held[tk]:g} and §6.1 does not list it")
    return not findings, findings


def sell_rows(cur, positions):
    """Clause one: "Sell rows for all seven". Every OPEN position, not §6.1's seven names.

    The book is what the system will still be reasoning from tomorrow, so a position the plan did
    not anticipate still has to leave — and it is named in the findings above rather than sold
    quietly. `clause = 'phase0'` marks these as close-out rows and not §3.5 decisions; §4.4's sheet
    gauge accepts it as a named clause for exactly this reason.
    """
    ids = []
    for p in positions:
        cur.execute("""insert into tickets (ticker, account, sleeve, action, reason, clause,
                                            order_type, qty, state, note)
                       values (%s,%s,%s,'sell','phase0','phase0','market',%s,'proposed',%s)
                       returning id""",
                    (p["ticker"], p["account"], p["sleeve"], p["qty"],
                     "§6.2 close-out: liquidate at market, sells before buys (§6.1)"))
        ids.append(cur.fetchone()[0])
    return ids


def void_open_tickets(cur, keep):
    """Clause two: "void all open tickets". Everything the old engine proposed and never filled.

    `keep` is the close-out's own rows, which are open by definition and must survive their own
    clause. Voided by state, never deleted — what the retired engine last proposed is part of the
    record §6.2 is closing.
    """
    cur.execute("""update tickets set state = 'cancelled', updated_at = now(),
                          note = coalesce(note,'') || ' | voided by §6.2 close-out'
                    where state in ('proposed','approved','provisional')
                      and not (id = any(%s))
                    returning id""", (keep,))
    return [r[0] for r in cur.fetchall()]


def retire_armed(cur):
    """Clause three: "retire all armed rows". §3.3 has no arming stage; nothing may stay armed."""
    cur.execute("select count(*) from armed")
    before = cur.fetchone()[0]
    cur.execute("delete from armed")
    return before


def close_learnings(cur):
    """Clause four: "close the six brewing learnings as *retired with engine*".

    `learnings` is an append ledger read latest-wins, so closing one means appending its closure
    rather than editing the row that raised it. Editing would erase the observation that produced
    it, which §5.3 makes the first step of the loop.

    The STATUS is `expired`, not a new word. §5.3's ladder ends in "promotion or expiry" and 033's
    column comment lists the five states; "retired with engine" is §6.2's REASON for the expiry,
    not a sixth state, and inventing one would extend a documented vocabulary without a ruling.
    The plan's exact words go where they belong — on the row, as the verdict.
    """
    cur.execute("""select key, lane, hypothesis, falsifier from v_learnings_current
                    where status in ('learning','proposal') order by key""")
    brewing = cur.fetchall()
    for key, lane, hypothesis, falsifier in brewing:
        cur.execute("""insert into learnings (key, status, lane, hypothesis, falsifier, detail)
                       values (%s, 'expired', %s, %s, %s, %s)""",
                    (key, lane, hypothesis, falsifier,
                     json.dumps({"closed_by": "§6.2 close-out", "verdict": RETIRED_WITH_ENGINE})))
    return [r[0] for r in brewing]


def main():
    apply = os.environ.get("CLOSEOUT_APPLY", "false").lower() in ("1", "true", "yes")
    with connect() as conn, Heartbeat(conn, "closeout", dry_run=dry() or not apply) as hb:
        with conn.cursor() as cur:
            # §6.2 runs once. A second pass over an already-closed book would propose sells for
            # positions that are gone, and §4.4's sheet gauge would then read a sell with no
            # position behind it as a completeness failure for as long as the row existed.
            cur.execute("""select count(*) from tickets
                            where clause = 'phase0' and action = 'sell'""")
            already = cur.fetchone()[0]

            positions = open_positions(cur)
            agreed, findings = reconcile_against_the_plan(positions)

            if already:
                hb.detail["skipped"] = f"{already} close-out sell row(s) already exist"
                print(f"closeout: already run — {already} sell row(s) on record. Nothing written.")
            elif not apply:
                print("closeout: DRY — set CLOSEOUT_APPLY=true to write")
            else:
                ids = sell_rows(cur, positions)
                voided = void_open_tickets(cur, ids)
                armed = retire_armed(cur)
                closed = close_learnings(cur)
                conn.commit()
                hb.rows = len(ids) + len(voided) + armed + len(closed)
                hb.detail.update(sell_rows=len(ids), voided_tickets=len(voided),
                                 armed_retired=armed, learnings_closed=closed)
                print(f"closeout: {len(ids)} sell row(s) · {len(voided)} ticket(s) voided · "
                      f"{armed} armed row(s) retired · {len(closed)} learning(s) "
                      f"{RETIRED_WITH_ENGINE}")

            hb.detail.update(positions=[f"{p['ticker']} {p['qty']:g} ({p['sleeve']})"
                                        for p in positions],
                             plan_agrees=agreed, plan_findings=findings)
            for p in positions:
                print(f"  SELL {p['ticker']:<10} {p['qty']:>12,.4f}   {p['account']:<7} "
                      f"{p['sleeve'] or '-'}")
            if findings:
                # Never merged silently. §6.1's list was written on a date and the book has been
                # maintained since; neither is automatically the truth, and the difference is the
                # one thing a close-out must not decide by itself.
                hb.amber(f"the book and §6.1's list disagree on {len(findings)} name(s)")
                print("\n  §6.1 vs the book:")
                for f in findings:
                    print(f"    · {f}")
            print("\nZak executes at the open (§0.2, §6.1). Nothing here has been ordered.\n"
                  "The book reaches zero through `reconcile`, when the receipts land — that path "
                  "is §6.2's paper trail.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
