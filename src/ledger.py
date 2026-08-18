"""ledger — the two ways a transaction enters the system, and the one place it lands.

Zak, 2026-08-18: *"There are a list of transactions... those will always come in with a transaction
ledger csv from Wealthsimple or another bank... Those are law... That's our actual history. And
then additionally sometimes those transactions are lagged... by days... so I will just tell the
chat other sales so it can process the books correctly... those are true to me... but they might
change or be tweaked by the transactions later. Maybe the pennies are different.... But the engine
should run assuming both."*

Three entry points, one ledger, one book:

  `import`   a bank export. Grade `broker` — **law**. It supersedes any `stated` row describing the
             same trade, which is how the pennies get corrected without losing what Zak believed on
             the day.
  `state`    Zak's word, ahead of the export. Grade `stated` — true, and provisional. It moves the
             book immediately, because a book that ignores what he already knows is wrong for as
             many days as the export lags. That is the ghost-book failure, and it proposed a sell
             he had already made.
  `confirm`  an opening position, for a holding older than this ledger. Not a trade — a statement
             that the position exists and what it cost, so the sells that follow it have something
             to net against.

**Both grades move the book**, through the same door as everything else: the row lands in
`transactions` and `yuna_book_from_ledger` recomputes the position. A trigger calls it, so a chat
session writing plain SQL gets exactly what this file gets — which is the point, because Zak uploads
the CSV to the chat and the chat has no shell.

    DATABASE_URL=... python src/ledger.py import data/ledger/ws-2026-08-18.csv
    DATABASE_URL=... python src/ledger.py state   --ticker NUE.US --side sell --qty 32 \\
                                                  --price 266.81 --date 2026-08-17
    DATABASE_URL=... python src/ledger.py confirm --ticker SPMO.US --qty 810 --price 155.50 \\
                                                  --date 2026-08-17
    DATABASE_URL=... python src/ledger.py check           # ledger vs book, read-only

**Nothing here places an order** (§0.2). Every row describes something that already happened.
"""
import argparse
import csv
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from db import connect, dry, Heartbeat                                     # noqa: E402

# A stated row and a broker row describe the same trade when they agree on account, ticker, side
# and the day. Quantity and price are deliberately NOT part of the match: the whole reason a broker
# row supersedes a stated one is that the numbers differ slightly — "maybe the pennies are
# different" — so matching on them would never match the case the rule exists for.
MATCH = ("account", "ticker", "side", "trade_date")

# Column names seen on Wealthsimple exports, lowercased. Extended rather than guessed: an unknown
# header is reported and the row is skipped, never mapped by position.
HEADERS = {
    "date": ("date", "transaction date", "trade date", "settlement date", "process date"),
    "ticker": ("symbol", "ticker", "security", "description"),
    "side": ("transaction", "type", "activity", "action"),
    "qty": ("quantity", "shares", "qty"),
    "price": ("price", "average price", "unit price"),
    "amount": ("amount", "net amount", "value"),
    "account": ("account", "account type", "account name"),
    "ref": ("id", "reference", "transaction id", "confirmation"),
}
BUY_WORDS = ("buy", "purchase", "bought")
SELL_WORDS = ("sell", "sale", "sold")


def _pick(row, field):
    for name in HEADERS[field]:
        for key, value in row.items():
            if key and key.strip().lower() == name:
                return (value or "").strip()
    return ""


def parse_csv(path):
    """Bank export -> [fill dicts]. Returns (rows, skipped) — never guesses at a column.

    A row whose side cannot be read as a buy or a sell is SKIPPED and reported, not assumed. A bank
    export carries dividends, interest, contributions and journal entries beside the trades, and
    every one of those folded in as a trade would move a position that never moved.
    """
    rows, skipped = [], []
    with open(path, newline="") as fh:
        for n, raw in enumerate(csv.DictReader(fh), start=2):
            side_text = _pick(raw, "side").lower()
            side = ("buy" if any(w in side_text for w in BUY_WORDS) else
                    "sell" if any(w in side_text for w in SELL_WORDS) else None)
            ticker, qty, price = _pick(raw, "ticker"), _pick(raw, "qty"), _pick(raw, "price")
            if side is None:
                skipped.append(f"line {n}: {side_text or '(no type column)'} — not a trade")
                continue
            if not (ticker and qty):
                skipped.append(f"line {n}: {side_text} with no ticker or quantity")
                continue
            try:
                q = abs(float(qty.replace(",", "")))
                p = abs(float((price or "0").replace(",", "").lstrip("$")))
            except ValueError:
                skipped.append(f"line {n}: {ticker} qty={qty!r} price={price!r} — unparseable")
                continue
            if p == 0:
                # Some exports carry only a net amount. Deriving the unit price is arithmetic, not
                # a guess — but if neither is present the row cannot be priced and is skipped.
                amount = _pick(raw, "amount").replace(",", "").lstrip("$").replace("(", "-")
                try:
                    p = abs(float(amount)) / q if amount and q else 0
                except ValueError:
                    p = 0
            if p == 0:
                skipped.append(f"line {n}: {ticker} has neither a price nor an amount")
                continue
            rows.append(dict(ticker=ticker.upper(), side=side, qty=q, price=p,
                             trade_date=_pick(raw, "date")[:10],
                             account=(_pick(raw, "account") or "TFSA").upper(),
                             external_ref=_pick(raw, "ref") or None))
    return rows, skipped


def record(cur, f, grade, source):
    """One row into the ledger. Returns (id, note). Supersedes on the way in when it is law.

    Idempotence differs by grade and that is deliberate. A broker row carries the bank's own
    identifier where the export has one, so re-importing the same file writes nothing. A stated row
    has no such identifier — Zak saying it twice is two statements — so it is matched on the trade
    itself, and a repeat updates rather than doubles.
    """
    when = f["trade_date"]
    if f.get("external_ref") and grade == "broker":
        cur.execute("select id from transactions where external_ref = %s", (f["external_ref"],))
        if cur.fetchone():
            return None, "already imported"

    superseded = []
    if grade == "broker":
        # §0.6 keeps the record: the stated row stays and stops counting, so the history shows both
        # what Zak believed on the day and what the bank confirmed after.
        cur.execute("""select id from transactions
                        where grade = 'stated' and superseded_by is null
                          and account = %s and ticker = %s and side = %s and trade_date = %s""",
                    (f["account"], f["ticker"], f["side"], when))
        superseded = [r[0] for r in cur.fetchall()]

    if grade == "stated":
        cur.execute("""select id from transactions
                        where grade = 'stated' and superseded_by is null
                          and account = %s and ticker = %s and side = %s and trade_date = %s""",
                    (f["account"], f["ticker"], f["side"], when))
        existing = cur.fetchone()
        if existing:
            cur.execute("""update transactions set qty = %s, price = %s, source = %s,
                                  confirmed_at = now() where id = %s""",
                        (f["qty"], f["price"], source, existing[0]))
            return existing[0], "restated"

    cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                             trade_date, confirmed, confirmed_at, grade,
                                             external_ref, source)
                   values (%s,%s,%s,%s,%s,%s,%s,true,now(),%s,%s,%s) returning id""",
                (f["ticker"], f["account"], f["side"], f["qty"], f["price"],
                 f.get("currency", "USD"), when, grade, f.get("external_ref"), source))
    new_id = cur.fetchone()[0]
    for old in superseded:
        cur.execute("update transactions set superseded_by = %s where id = %s", (new_id, old))
    note = "recorded" + (f", superseding {len(superseded)} stated row(s)" if superseded else "")
    return new_id, note


def rebuild_book(cur, account=None):
    """Make `book` say what the live ledger says, everywhere. Returns [changes].

    The per-position arithmetic is `yuna_book_from_ledger` (migration 059), which is also what the
    `ledger_moves_the_book` trigger calls on every write and what `reconcile.apply_to_book` calls.
    One definition, three callers. This one is the SWEEP: it walks every position the ledger knows
    about rather than the one that just changed, which is what you want after restoring a backup,
    after a bulk import, or any time the question is "is the whole book right" rather than "is this
    row right".

    On a healthy database it changes nothing, and that is the point — a repair tool whose no-op
    case is silent is a repair tool you can run to find out whether you needed it.

    A position with no transactions behind it is left exactly alone and named. It predates the
    ledger, and deleting a real holding because one table cannot explain it is not a repair.
    """
    changes = []
    where, args = ("where account = %s", (account,)) if account else ("", ())
    cur.execute(f"select account, ticker, qty from v_ledger_positions {where}", args)
    for acct, tk, qty in cur.fetchall():
        cur.execute("""select coalesce(sum(qty), 0) from book
                        where account = %s and ticker = %s and status = 'open'""", (acct, tk))
        was = float(cur.fetchone()[0])
        cur.execute("select yuna_book_from_ledger(%s, %s)", (acct, tk))
        now = float(cur.fetchone()[0] or 0)
        if abs(was - now) > 1e-6:
            changes.append(f"{acct} {tk}: {was:g} -> {'closed' if now <= 1e-9 else f'{now:g}'}")

    # A book position the ledger has no rows for at all. Not touched, and named — see the docstring.
    cur.execute("""select b.account, b.ticker, b.qty from book b
                    where b.status = 'open'
                      and not exists (select 1 from transactions t
                                       where t.account = b.account and t.ticker = b.ticker
                                         and t.superseded_by is null)
                    order by b.account, b.ticker""")
    for acct, tk, qty in cur.fetchall():
        changes.append(f"{acct} {tk}: {float(qty):g} held with NO ledger history — left untouched")
    return changes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="a bank export CSV — grade `broker`, law")
    imp.add_argument("path")
    st = sub.add_parser("state", help="Zak's word ahead of the export — grade `stated`")
    for flag in ("--ticker", "--side", "--qty", "--price", "--date"):
        st.add_argument(flag, required=True)
    st.add_argument("--account", default="TFSA")
    # The opening balance. A position bought before this ledger existed has no rows to net a sell
    # against, so the sell drives it negative and `yuna_book_from_ledger` refuses — correctly, since
    # the alternative is a book quietly holding minus 810 shares. This is the row that fixes it, and
    # it is how the seven §6.1 positions entered on 2026-08-03.
    op = sub.add_parser("confirm", help="an opening position that predates the ledger")
    for flag in ("--ticker", "--qty", "--price", "--date"):
        op.add_argument(flag, required=True)
    op.add_argument("--account", default="TFSA")
    op.add_argument("--grade", default="stated", choices=("stated", "broker"))
    sub.add_parser("check", help="ledger against book, read-only")
    args = ap.parse_args()

    with connect() as conn, Heartbeat(conn, "ledger", dry_run=dry()) as hb:
        with conn.cursor() as cur:
            if args.cmd == "check":
                cur.execute("""select account, ticker, ledger_qty, book_qty, difference,
                                      stated_rows, predates_the_ledger
                                 from v_ledger_vs_book order by predates_the_ledger, account,
                                      ticker""")
                rows = cur.fetchall()
                print("ledger vs book:" + (" they match" if not rows else ""))
                breaks, older = [], []
                for acct, tk, lq, bq, diff, stated, predates in rows:
                    (older if predates else breaks).append(f"{acct} {tk}")
                    tail = ("held since before the ledger — the export has not landed yet"
                            if predates else f"diff {diff:+,.4f}  stated_rows={stated or 0}")
                    print(f"  {acct:<7} {tk:<10} ledger {lq or 0:>12,.4f}  book "
                          f"{bq or 0:>12,.4f}  {tail}")
                hb.detail.update(breaks=breaks, predates_the_ledger=older)
                # The two rows in this view are not the same kind of thing and must not carry the
                # same colour. A genuine disagreement is a defect — something wrote one side and not
                # the other, which is the ghost book. A position older than its own history is
                # merely incomplete, it is TRUE of the book today, and it heals itself the moment
                # the bank's export arrives. Red on the first would make the second cry wolf every
                # night until then, and a gauge that is always red stops being read.
                if breaks:
                    hb.red(f"{len(breaks)} position(s) disagree between the ledger and the book: "
                           + ", ".join(breaks))
                elif older:
                    hb.amber(f"{len(older)} position(s) predate the ledger and have no history "
                             f"behind them: " + ", ".join(older))
                return 0

            if args.cmd == "import":
                fills, skipped = parse_csv(args.path)
                source = f"csv {pathlib.Path(args.path).name}"
                grade = "broker"
                print(f"{len(fills)} trade(s) read, {len(skipped)} row(s) skipped")
                for line in skipped:
                    print(f"  skipped: {line}")
            elif args.cmd == "confirm":
                fills = [dict(ticker=args.ticker.upper(), side="confirm",
                              qty=abs(float(args.qty)), price=abs(float(args.price)),
                              trade_date=args.date, account=args.account.upper())]
                source = f"opening position, recorded {dt.date.today()}"
                grade = args.grade
            else:
                fills = [dict(ticker=args.ticker.upper(), side=args.side.lower(),
                              qty=abs(float(args.qty)), price=abs(float(args.price)),
                              trade_date=args.date, account=args.account.upper())]
                source = f"stated in chat {dt.date.today()}"
                grade = "stated"

            if dry():
                hb.detail["would_record"] = len(fills)
                print(f"DRY_RUN — {len(fills)} row(s) would be recorded, nothing written")
                return 0

            noted = []
            for f in fills:
                _, note = record(cur, f, grade, source)
                noted.append(f"{f['side']} {f['qty']:g} {f['ticker']} @ {f['price']:g} "
                             f"({f['account']}, {f['trade_date']}) — {note}")
            changes = rebuild_book(cur)
            conn.commit()

            hb.rows = len(noted)
            hb.detail.update(grade=grade, recorded=noted, book_changes=changes)
            print(f"ledger: {len(noted)} row(s) recorded as `{grade}` · "
                  f"{len(changes)} book change(s)")
            for line in noted + changes:
                print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
