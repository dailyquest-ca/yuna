"""fills — dispatch-only tooling: fold a broker export into the ledger (§4.2, §4.5, R4 step 2).

Sunday's reconciliation is the routine path for this: Zak reads his settled activity out, and the
session writes each fill onto a ticket. This job exists for the case that path missed — a fill
nobody wrote down, discovered later, whose absence the book has been reasoning from ever since.
On 2026-08-04 four of them went unrecorded, and the next four briefs armed RS.US as a new
momentum entry at the very price Zak had already paid for it.

It takes the same route a session would, and nothing more:

    manifest -> tickets (settled, reason 'discretionary') -> transactions -> book

`tickets` is where a fill lives (§4.5), `transactions` is derived from it by
`arming.sync_fills_from_tickets`, and the book is folded by `arming.apply_fills` — the same two
functions the nightly `score` calls, so this repairs the book through the machinery rather than
around it. §4.3 keeps `book` and `transactions` job-written, which is why this is a job.

Every fill carries a `ref`, and a ref already on a ticket is skipped, so re-running applies
nothing twice. DRY_RUN=true reads the manifests, reports exactly what it would write, and writes
nothing.

    FILLS_GLOB   which manifests to read (default `data/fills/*.json`)
"""
import glob
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from db import connect, dry, Heartbeat
import arming

DEFAULT_GLOB = str(pathlib.Path(__file__).resolve().parent.parent / "data" / "fills" / "*.json")


def manifests(pattern=None):
    """[(path, fill dict), ...] in file then manifest order — the order they were traded in."""
    out = []
    for path in sorted(glob.glob(pattern or os.environ.get("FILLS_GLOB") or DEFAULT_GLOB)):
        doc = json.loads(pathlib.Path(path).read_text())
        for f in doc.get("fills", []):
            out.append((pathlib.Path(path).name, f))
    return out


def already_recorded(cur, ref):
    cur.execute("select id from tickets where arm_key = %s", (ref,))
    row = cur.fetchone()
    return row[0] if row else None


def write_ticket(cur, source, f):
    """One settled ticket per fill — the shape R4 step 2 gives a fill with no ticket behind it."""
    side = f["side"]
    action = "sell" if side == "sell" else "buy"
    cur.execute("""insert into tickets (ticker, account, sleeve, action, reason, order_type,
                     limit_price, qty, state, arm_key, currency, fx_estimate,
                     fill_price, fill_qty, fill_date, fill_fx, fill_fees, note)
                   values (%s,%s,%s,%s,'discretionary','market',
                           %s,%s,'confirmed',%s,%s,%s,
                           %s,%s,%s,%s,%s,%s) returning id""",
                (f["ticker"], f.get("account", "TFSA"), f.get("sleeve"), action,
                 f["price"], f["qty"], f["ref"], f.get("currency", "USD"), f.get("fx"),
                 f["price"], f["qty"], f["trade_date"], f.get("fx"), f.get("fees", 0),
                 f"broker fill reconciled from {source}"
                 + (f" — {f['note']}" if f.get("note") else "")))
    return cur.fetchone()[0]


def main():
    rows = manifests()
    with connect() as conn:
        with Heartbeat(conn, "fills") as hb:
            written, skipped = [], []
            with conn.cursor() as cur:
                for source, f in rows:
                    ref = f.get("ref")
                    if not ref:
                        raise SystemExit(f"a fill in {source} carries no ref — refusing to write "
                                         f"a row that cannot be recognised on a re-run")
                    existing = already_recorded(cur, ref)
                    label = (f"{f['side']} {f['qty']:g} {f['ticker']} @ {f['price']:g} "
                             f"({f['trade_date']})")
                    if existing:
                        skipped.append(f"{label} — already ticket {existing}")
                        continue
                    if dry():
                        skipped.append(f"{label} — DRY_RUN, nothing written")
                        continue
                    write_ticket(cur, source, f)
                    written.append(label)
            conn.commit()

            # the same two passes the nightly `score` makes, so the book is repaired by the
            # machinery rather than beside it
            made = arming.sync_fills_from_tickets(conn, hb)
            applied = arming.apply_fills(conn, hb)

            hb.rows = len(written)
            hb.detail.update(manifest_fills=len(rows), tickets_written=written,
                             skipped=skipped, ledger_rows=made, book_applied=applied)
            print(f"fills: {len(written)} ticket(s) written, {len(skipped)} skipped · "
                  f"{len(made)} ledger row(s) derived · {len(applied)} folded into the book")
            for line in written + skipped:
                print(f"  {line}")
            with conn.cursor() as cur:
                cur.execute("""select ticker, account, sleeve, qty, round(avg_cost::numeric,4),
                                      status from book order by ticker""")
                for tk, acct, sleeve, qty, cost, status in cur.fetchall():
                    print(f"  book  {tk:<9} {acct:<7} {sleeve or '-':<12} "
                          f"{float(qty):>10g} @ {cost} · {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
