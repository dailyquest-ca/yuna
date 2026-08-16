"""reconcile — §4.1's fifth job. The broker's receipt against the book, post-execution.

§4.3: "Yuna writes rows; Zak's execution is the event; reconcile closes the loop with the receipt."
This is the loop closing. It reads a manifest Zak exports from Wealthsimple and does two separate
things that are easy to confuse:

  1. **Folds the fills.** Each receipt becomes a `transactions` row and moves the book. The ticket
     it settles advances `approved -> executed`.
  2. **Compares the positions.** The manifest's position block is what the broker says is there.
     Where it agrees with `book`, the executed tickets advance to `reconciled`. Where it does not,
     the run goes RED and says which name and by how much.

Only (2) is reconciliation. Folding a fill and then trusting the arithmetic that folded it proves
nothing — the whole point is an outside witness. A run that folds three fills and skips the
position block is a run that has not reconciled anything, and it says so.

    DATABASE_URL=... python src/reconcile.py
    RECONCILE_GLOB='data/reconcile/2026-08-17.json' python src/reconcile.py
    DRY_RUN=true python src/reconcile.py         # read, report, write nothing

Manifest shape — the same fill record `data/fills/` already uses, plus a positions block:

    {"as_of": "2026-08-17", "account": "TFSA",
     "fills":     [{"ref": "ws-1", "ticker": "SNDK.US", "side": "buy", "qty": 24,
                    "price": 1650.10, "trade_date": "2026-08-17", "fees": 0}],
     "positions": [{"ticker": "SNDK.US", "qty": 24}]}

**Nothing here places, modifies or cancels an order** (§0.2). Every row it writes describes
something that has already happened.
"""
import glob
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from db import connect, dry, Heartbeat                                     # noqa: E402

DEFAULT_GLOB = str(pathlib.Path(__file__).resolve().parent.parent / "data" / "reconcile" / "*.json")

# A share count is a float in this schema, and floats do not compare equal. The tolerance is a
# thousandth of a share: fractional shares are real (§3.7(4) permits them where the broker supports
# them) but no broker reports a position to four decimal places, so anything above this is a
# genuine disagreement rather than a representation artefact.
QTY_TOL = 1e-3


def manifests(pattern=None):
    """[(name, document)] in filename order — the order the sessions happened in."""
    out = []
    for path in sorted(glob.glob(pattern or os.environ.get("RECONCILE_GLOB") or DEFAULT_GLOB)):
        out.append((pathlib.Path(path).name, json.loads(pathlib.Path(path).read_text())))
    return out


def fold_fill(cur, source, account, f):
    """One receipt -> one transaction -> the book moved. Returns (transaction_id | None, note).

    Returns None when the ref is already recorded. That is the idempotence contract and it is
    checked by INSERT rather than by SELECT-then-INSERT: two chain passes can overlap, and a
    check-then-write race would double a position.
    """
    for field in ("ref", "ticker", "side", "qty", "price", "trade_date"):
        if f.get(field) is None:
            raise SystemExit(f"a fill in {source} is missing {field!r} — refusing to fold a "
                             f"receipt that cannot be recognised on a re-run or checked against "
                             f"the book")
    if f["side"] not in ("buy", "sell"):
        raise SystemExit(f"a fill in {source} has side {f['side']!r}; expected buy or sell")
    if float(f["qty"]) <= 0:
        raise SystemExit(f"a fill in {source} has qty {f['qty']!r} — a receipt for no shares is "
                         f"not a receipt")

    cur.execute("""insert into transactions (ticker, account, side, qty, price, currency, fx_rate,
                                             fees, trade_date, confirmed, confirmed_at,
                                             broker_ref, source, note)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,true,now(),%s,%s,%s)
                   on conflict (broker_ref) where broker_ref is not null do nothing
                   returning id""",
                (f["ticker"], f.get("account", account), f["side"], float(f["qty"]),
                 float(f["price"]), f.get("currency", "USD"), f.get("fx"), float(f.get("fees", 0)),
                 f["trade_date"], f["ref"], source, f.get("note")))
    row = cur.fetchone()
    if row is None:
        return None, "already folded"
    apply_to_book(cur, f.get("account", account), f)
    return row[0], "folded"


def apply_to_book(cur, account, f):
    """Move the book by one receipt. §3.5's book is five equal slots — no lots, no pyramids.

    A buy into an open position averages the cost; §029 fixes `entry_fill` at the FIRST buy and
    never rewrites it, because an add band that measured from `avg_cost` would measure from a base
    the previous add had already moved.
    """
    tk, qty, px = f["ticker"], float(f["qty"]), float(f["price"])
    cur.execute("""select id, qty, avg_cost from book
                    where ticker = %s and account = %s and status = 'open'""", (tk, account))
    row = cur.fetchone()

    if f["side"] == "buy":
        if row is None:
            cur.execute("""insert into book (ticker, account, sleeve, qty, avg_cost, currency,
                                             opened_at, entry_fill, status)
                           values (%s,%s,%s,%s,%s,%s,%s,%s,'open')""",
                        (tk, account, f.get("sleeve", "momentum"), qty, px,
                         f.get("currency", "USD"), f["trade_date"], px))
        else:
            bid, held, cost = row
            total = held + qty
            cur.execute("""update book set qty = %s, avg_cost = %s, updated_at = now()
                            where id = %s""", (total, (held * cost + qty * px) / total, bid))
        return

    if row is None:
        # A sell of something the book does not hold. Not fixable here and not silently ignorable:
        # the book is wrong in a direction that matters, and `positions` will say so as red.
        raise SystemExit(f"receipt sells {qty:g} {tk} in {account} and the book holds no open "
                         f"position — the book and the broker disagree about what exists")
    bid, held, _ = row
    left = held - qty
    if left < -QTY_TOL:
        raise SystemExit(f"receipt sells {qty:g} {tk} and the book holds {held:g} — refusing to "
                         f"drive a position negative")
    if abs(left) <= QTY_TOL:
        cur.execute("""update book set qty = 0, status = 'closed', closed_at = %s,
                              updated_at = now() where id = %s""", (f["trade_date"], bid))
    else:
        cur.execute("update book set qty = %s, updated_at = now() where id = %s", (left, bid))


def settle_tickets(cur, account, fills):
    """Advance the ticket a receipt settles: `approved` -> `executed` (§4.3).

    Matched on (ticker, action) against the oldest ticket still awaiting a receipt, because that is
    the order they were proposed in and a two-day-old approval settles before today's. A receipt
    with no ticket behind it is not an error — Zak may act outside the sheet, and §0.2 makes that
    his prerogative — but it IS reported, because an engine position nobody proposed is a position
    the engine will not manage.
    """
    settled, orphans = [], []
    for f in fills:
        action = "buy" if f["side"] == "buy" else "sell"
        cur.execute("""update tickets set state = 'executed', executed_at = now(),
                              updated_at = now()
                        where id = (select id from tickets
                                     where ticker = %s and action = %s and account = %s
                                       and session_date is not null
                                       and state in ('proposed','approved')
                                     order by session_date, id limit 1)
                        returning id, session_date, state""",
                    (f["ticker"], action, f.get("account", account)))
        row = cur.fetchone()
        if row:
            settled.append(f"{action} {f['ticker']} -> ticket {row[0]} ({row[1]})")
        else:
            orphans.append(f"{action} {f['qty']:g} {f['ticker']} @ {f['price']:g} "
                           f"({f['trade_date']}) — no engine ticket proposed it")
    return settled, orphans


def compare_positions(cur, account, positions):
    """The outside witness. Broker positions vs `book`, both directions. Returns a list of breaks.

    Both directions matter and they fail differently. A name the broker holds and the book does not
    is a position the engine will never sell — it is not in the book, so it is not in `held`, so no
    rank exit can ever queue it. A name the book holds and the broker does not is a phantom the
    engine counts against its five slots, so it blocks a real entry for ever.
    """
    said = {p["ticker"]: float(p["qty"]) for p in positions}
    cur.execute("""select ticker, qty, sleeve from book
                    where account = %s and status = 'open' order by ticker""", (account,))
    ours = {t: (float(q), s) for t, q, s in cur.fetchall()}

    breaks = []
    for tk in sorted(set(said) | set(ours)):
        broker = said.get(tk)
        book_qty = ours[tk][0] if tk in ours else None
        if broker is not None and book_qty is None:
            breaks.append(dict(ticker=tk, broker=broker, book=None,
                               why="the broker holds it and the book does not — the engine can "
                                   "never queue an exit for a position it cannot see"))
        elif book_qty is not None and broker is None:
            breaks.append(dict(ticker=tk, broker=None, book=book_qty, sleeve=ours[tk][1],
                               why="the book holds it and the broker does not — a phantom "
                                   "position occupies one of §3.5's five slots"))
        elif abs(broker - book_qty) > QTY_TOL:
            breaks.append(dict(ticker=tk, broker=broker, book=book_qty, sleeve=ours[tk][1],
                               why=f"quantities differ by {broker - book_qty:+g} shares"))
    return breaks


def close_the_loop(cur, account):
    """`executed` -> `reconciled`, for an account whose positions ALL verified.

    Called only when `compare_positions` returned no breaks, and the scope is the whole account on
    purpose. A per-name attestation would be the weaker claim: a book can agree with the broker on
    every name it lists and still be wrong, by holding a name the broker does not — which is a
    break with no ticket attached to fail. The account either reconciles or it does not.

    The state IS the attestation. Advancing a ticket whose account did not verify would record
    "the broker's receipt matched the book" where it demonstrably did not, and §4.4's
    reconciliation-age gauge would then read green off a lie.
    """
    cur.execute("""update tickets t set state = 'reconciled', reconciled_at = now(),
                          updated_at = now()
                    where t.state = 'executed' and t.account = %s
                    returning t.id, t.ticker, t.action""", (account,))
    return [f"{a} {tk} -> ticket {i} reconciled" for i, tk, a in cur.fetchall()]


def main():
    docs = manifests()
    with connect() as conn, Heartbeat(conn, "reconcile", dry_run=dry()) as hb:
        if not docs:
            # Not a failure. §4.4 gauges the AGE of the last reconciliation, and a night with no
            # export is an ordinary night — the gauge, not this job, is what notices a stale one.
            hb.detail["manifests"] = 0
            print("reconcile: no manifest to read — the book stands as it was")
            with conn.cursor() as cur:
                cur.execute("select * from v_reconciliation_age")
                cols = [d[0] for d in cur.description]
                hb.detail["age"] = {c: str(v) for c, v in zip(cols, cur.fetchone())}
            return 0

        folded, settled, orphans, breaks, closed = [], [], [], [], []
        with conn.cursor() as cur:
            for name, doc in docs:
                account = doc.get("account", "TFSA")
                fills = doc.get("fills", [])
                if dry():
                    # "compute everything, write nothing" — so the comparison still runs. It is
                    # read-only, and a dry run that skipped it would answer the least useful
                    # question: whether the file parses, rather than whether the book agrees.
                    folded.append(f"{name}: {len(fills)} fill(s) — DRY_RUN, nothing written")
                else:
                    for f in fills:
                        _, what = fold_fill(cur, name, account, f)
                        folded.append(f"{f['side']} {float(f['qty']):g} {f['ticker']} @ "
                                      f"{float(f['price']):g} — {what}")
                    s, o = settle_tickets(cur, account, fills)
                    settled += s
                    orphans += o

                if "positions" not in doc:
                    # Stated, not inferred. A manifest with no position block folded fills and
                    # reconciled nothing, and the run must not read as though it had.
                    hb.amber(f"{name} carries no `positions` block — fills folded, but nothing "
                             f"was reconciled against the broker")
                    continue
                found = compare_positions(cur, account, doc["positions"])
                breaks += [dict(b, manifest=name, account=account) for b in found]
                if not found and not dry():
                    closed += close_the_loop(cur, account)

            if not dry():
                conn.commit()

        hb.rows = len(folded)
        hb.detail.update(manifests=[n for n, _ in docs], folded=folded, settled=settled,
                         orphan_fills=orphans, breaks=breaks, reconciled=closed)
        with conn.cursor() as cur:
            cur.execute("select * from v_reconciliation_age")
            cols = [d[0] for d in cur.description]
            hb.detail["age"] = {c: str(v) for c, v in zip(cols, cur.fetchone())}

        if orphans:
            hb.amber(f"{len(orphans)} fill(s) with no engine ticket behind them — an engine "
                     f"position nobody proposed is one the engine will not manage")
        if breaks:
            # §4.4: any red holds buys; nothing holds exits. A book that disagrees with the broker
            # cannot be sized against, and every §3.5 decision is a function of what is held.
            hb.red(f"{len(breaks)} position(s) disagree between the broker and the book: "
                   + "; ".join(f"{b['ticker']} broker={b['broker']} book={b['book']}"
                               for b in breaks))

        print(f"reconcile: {len(folded)} receipt(s) · {len(settled)} ticket(s) executed · "
              f"{len(closed)} reconciled · {len(breaks)} break(s)")
        for line in folded + settled + orphans + closed:
            print(f"  {line}")
        for b in breaks:
            print(f"  BREAK {b['ticker']:<10} broker={b['broker']} book={b['book']} — {b['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
