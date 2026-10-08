"""reconcile — §4.1's fifth job. The broker's receipt against the book, post-execution.

§4.3: "Yuna writes rows; Zak's execution is the event; reconcile closes the loop with the receipt."
This is the loop closing. A receipt reaches the system by two routes and this job walks both:

  0. **The chat route, and it is the ORDINARY one.** §4.3's write list makes a session the routine
     way a fill enters: Zak reports it, the session writes `fill_*` onto the ticket, and a JOB
     derives the ledger row and folds it into the book. `derive_ticket_fills` and `apply_unapplied`
     are those two halves — restored 2026-08-18 after the ghost-book morning, when a full
     liquidation reported in chat on the 17th never reached `book` and the next brief proposed a
     sell Zak had already executed. §6.3 had retired the only jobs that walked this path (the
     legacy `score` and `fills`, via `arming.sync_fills_from_tickets` / `apply_fills`) and this job
     replaced only the manifest half.
  1. **Folds the manifest fills.** Each receipt in a `data/reconcile/` export becomes a
     `transactions` row and moves the book. The ticket it settles advances `approved -> executed`.
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

A fill may also carry `"ticket_id"`: the receipt naming the order it executed, which outranks the
match `ticket_for` would otherwise make.

**Nothing here places, modifies or cancels an order** (§0.2). Every row it writes describes
something that has already happened.
"""
import datetime as dt
import glob
import json
import os
import pathlib
import sys

import psycopg

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from db import connect, dry, Heartbeat                                     # noqa: E402

DEFAULT_GLOB = str(pathlib.Path(__file__).resolve().parent.parent / "data" / "reconcile" / "*.json")

# A share count is a float in this schema, and floats do not compare equal. The tolerance is a
# thousandth of a share: fractional shares are real (§3.7(4) permits them where the broker supports
# them) but no broker reports a position to four decimal places, so anything above this is a
# genuine disagreement rather than a representation artefact.
QTY_TOL = 1e-3

# The ticket states that come BEFORE a receipt: §4.3's first two, and the two ways a proposal stops
# being an order. A receipt is the event (§4.3: "Zak's execution is the event"), so a receipt that
# names one of these advances it to `executed` — a proposal a later sheet superseded included,
# because Zak may have executed it in its own window and only told the system afterwards (A57).
AWAITING = ("proposed", "approved", "cancelled", "expired")


def refusal(e):
    """The ledger's own words for a refused receipt: what it refused, and the repair it names."""
    hint = e.diag.message_hint
    return e.diag.message_primary + (f" (hint: {hint})" if hint else "")


def manifests(pattern=None):
    """[(name, document)] in filename order — the order the sessions happened in."""
    out = []
    for path in sorted(glob.glob(pattern or os.environ.get("RECONCILE_GLOB") or DEFAULT_GLOB)):
        out.append((pathlib.Path(path).name, json.loads(pathlib.Path(path).read_text())))
    return out


def ticket_for(cur, account, f, source):
    """The engine ticket a manifest receipt executed, or None (A57).

    A `ticket_id` on the fill is the receipt naming its own order, and it wins — checked, not
    trusted: a ticket for another name, side or account is not this receipt's order, and linking it
    would settle the wrong row, so the fold stops.

    Otherwise the order is on the sheet that was in force when the trade printed. §3.5 decides at a
    close and fills "at the next open", so a trade on day T executed the newest sheet decided BEFORE
    T — never one decided at T's own close or later, which did not exist yet when Zak traded, and
    never an older one: §4.3 makes the nightly sheet "the only source of engine orders", so a sheet
    a later one replaced was no longer an order on T. This used to take the OLDEST ticket still
    awaiting a receipt for the (ticker, action), and with August's never-withdrawn proposals in the
    table that was a receipt linked to a sheet three weeks stale.

    "The newest sheet" counts every close the engine decided, including the quiet ones that wrote
    no ticket (`engine_sessions`), and every close a ticket names, so a ticket is never orphaned by
    a missing session row. The sheet holds at most one ticket per (ticker, action) — the
    `tickets_engine_key` index — so the match is unambiguous. It accepts every state that comes
    before a receipt, a superseded proposal included: the session restriction is what keeps a stale
    sheet out, and a receipt that arrives a night late still belongs to the order it executed.
    """
    action = "buy" if f["side"] == "buy" else "sell"
    if f.get("ticket_id") is not None:
        cur.execute("""select id from tickets
                        where id = %s and ticker = %s and action = %s and account = %s""",
                    (f["ticket_id"], f["ticker"], action, account))
        row = cur.fetchone()
        if row is None:
            raise SystemExit(f"a fill in {source} names ticket {f['ticket_id']}, which is not a "
                             f"{action} of {f['ticker']} in {account} — refusing to link a receipt "
                             f"to an order it does not describe")
        return row[0]
    cur.execute("""select id from tickets
                    where ticker = %s and action = %s and account = %s
                      and state = any(%s)
                      and session_date = (select max(d) from (
                                            select session_date as d from engine_sessions
                                             where mode = 'live'
                                            union all
                                            select session_date from tickets
                                             where session_date is not null) closes
                                           where d < %s::date)""",
                (f["ticker"], action, account, list(AWAITING), f["trade_date"]))
    row = cur.fetchone()
    return row[0] if row else None


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

    # Link the transaction to the ticket it settles. Nothing did this before, and it is the door a
    # second receipt route walks straight through: `derive_ticket_fills` skips a ticket that
    # already has a transaction, so an unlinked manifest row would let the SAME fill be derived a
    # second time from the ticket's own `fill_*` fields and folded into the book twice.
    # `settle_tickets` then advances exactly the ticket this row links, so the two can never name
    # different orders.
    ticket_id = ticket_for(cur, f.get("account", account), f, source)

    cur.execute("""insert into transactions (ticket_id, ticker, account, side, qty, price,
                                             currency, fx_rate, fees, trade_date, confirmed,
                                             confirmed_at, broker_ref, source, note)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,now(),%s,%s,%s)
                   on conflict (broker_ref) where broker_ref is not null do nothing
                   returning id""",
                (ticket_id, f["ticker"], f.get("account", account), f["side"], float(f["qty"]),
                 float(f["price"]), f.get("currency", "USD"), f.get("fx"), float(f.get("fees", 0)),
                 f["trade_date"], f["ref"], source, f.get("note")))
    row = cur.fetchone()
    if row is None:
        return None, "already folded"
    apply_to_book(cur, f.get("account", account), f["ticker"])
    return row[0], "folded"


def apply_to_book(cur, account, ticker):
    """Make the book say what the ledger says about one position (migration 059).

    This used to move the book INCREMENTALLY — read the position, add or subtract the receipt, write
    it back — and that is now wrong twice over. Zak, 2026-08-18: *"You keep them in the transaction
    ledger and they should all match. That's our actual history."* The ledger is the history, so the
    position is a **sum over it**, not a running total that happens to have been nudged correctly
    every time since the beginning.

    The arithmetic lives in `yuna_book_from_ledger` and this is a call to it. That matters because
    there are now three ways a row reaches the ledger — a manifest, a ticket fill, and a chat
    session writing plain SQL — and the third one cannot call Python. A trigger calls the same
    function, so every route lands identically and a fill that reaches the ledger cannot fail to
    reach the book. That failure is the one Zak reported.

    The guards did not go away, they moved and got a better basis. A sell of something never bought
    used to be caught by "the book holds no open position"; it is now caught by the ledger driving
    the position negative, which is the same event measured against the history rather than against
    whatever the book happened to say.
    """
    cur.execute("select yuna_book_from_ledger(%s, %s)", (account, ticker))


def derive_ticket_fills(cur, refused=None):
    """Tickets carrying a fill but no ledger row -> the `transactions` row they imply.

    **This is the step that went missing, and it is the reason chat-reported trades stopped
    sticking.** §4.3's write list (2026-08-04) says a session writes TICKETS and never the ledger:
    it hears a fill from Zak, writes `fill_price`/`fill_qty`/`fill_date` onto the ticket, and a JOB
    derives the transaction. That job was `arming.sync_fills_from_tickets`, called by the legacy
    `score` and by `fills` — and §6.3 retired both from the schedule. `reconcile` replaced only the
    MANIFEST half of the path, so from 2026-08-16 a fill reported in chat landed on a ticket and
    stopped there: no ledger row, no book movement, and the next morning's brief proposed a sell
    Zak had already executed.

    Idempotent by the same guard the old pass used: one transaction per ticket, and a ticket that
    already has one is skipped.

    **Each ticket is derived under its own savepoint, and checked there** (A21). The ledger trigger
    is deferred to COMMIT (059), so an insert proves nothing on its own: a reported sell larger than
    the ledger's history — the true post-split sale, or a mistyped quantity — used to raise at the
    first recompute and take the whole night down with it, every unrelated receipt included, and
    then again every night after. The recompute is now forced inside the savepoint, so a refusal
    is that ticket's alone: it is rolled back, the ticket keeps its fill for the next night, and the
    refusal goes into `refused` with the ledger's own words, for the caller to put in the run's red.

    With no `refused` list the refusal is raised, exactly as before — a caller that cannot report
    it does not get to swallow it.

    Within a day buys are derived before sells. The ledger's rule is the END state (migration 059:
    the book is what the ledger says at commit), so a sell must not be refused for the one instant
    before a same-day purchase that covers it has been written.
    """
    cur.execute("""select k.id, k.ticker, k.account, k.action, k.fill_qty, k.fill_price,
                          coalesce(k.currency, 'USD'), k.fill_fx, k.fill_fees,
                          coalesce(k.fill_date, current_date), k.state, k.sleeve
                     from tickets k
                    where k.fill_price is not null and k.fill_qty is not null
                      and k.account is not null
                      and k.state in ('executed', 'confirmed', 'provisional')
                      and not exists (select 1 from transactions t where t.ticket_id = k.id)
                    order by coalesce(k.fill_date, current_date),
                             case when k.action = 'sell' then 1 else 0 end, k.id""")
    made = []
    for tid, tk, acct, action, qty, price, ccy, fx, fees, when, state, sleeve in cur.fetchall():
        # Grade `stated` — always, whatever the ticket's state. A ticket fill reaches this table
        # because Zak said a number in chat, and Zak's word is exactly what `stated` means: true,
        # and provisional until the bank's export says the same thing to the penny (migration 059).
        # The export supersedes it on arrival, so the difference is recorded rather than argued.
        #
        # It MOVES THE BOOK, including from a `provisional` ticket, and that reverses the rule this
        # function shipped with two days ago. Zak, 2026-08-18: *"sometimes those transactions are
        # lagged... by days... so I will just tell the chat other sales so it can process the books
        # correctly... **But the engine should run assuming both.**"* The old rule made the book
        # wait for a confirmation that arrives days later, which is the ghost-book failure written
        # down as policy: for those days the engine reasons from a position Zak has already sold.
        cur.execute("savepoint ticket_fill")
        try:
            cur.execute("""insert into transactions (ticket_id, ticker, account, side, qty, price,
                                                     currency, fx_rate, fees, trade_date,
                                                     confirmed, confirmed_at, grade, source)
                           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,now(),'stated',%s)
                           returning id""",
                        (tid, tk, acct, "sell" if action == "sell" else "buy", float(qty),
                         float(price), ccy, fx, float(fees or 0), when, f"ticket {tid} ({state})"))
            apply_to_book(cur, acct, tk)
        except psycopg.errors.RaiseException as e:
            cur.execute("rollback to savepoint ticket_fill")
            if refused is None:
                raise
            refused.append(dict(account=acct, ticker=tk, ticket=tid,
                                receipt=f"{action} {float(qty):g} @ {float(price):g} on {when}",
                                why=refusal(e)))
            continue
        cur.execute("release savepoint ticket_fill")
        made.append(f"{action} {float(qty):g} {tk} @ {float(price):g} ({acct}, {when}) — "
                    f"derived from ticket {tid} as `stated`"
                    + ("  (provisional ticket — the export will true the pennies)"
                       if state == "provisional" else ""))
    return made


def apply_unapplied(cur, refused=None):
    """Ledger rows nobody has stamped -> stamped, their tickets advanced. Returns [labels].

    Since migration 059 this no longer moves the book, because **the book has already moved**: the
    `ledger_moves_the_book` trigger recomputes the position on the write itself, so by the time any
    job looks, the ledger and the book already agree. What is left here is the paperwork that a
    trigger has no business doing — stamping `applied_at`, and advancing the ticket a receipt
    settles.

    That is a real simplification rather than a shuffle. The fold was a SECOND place the book could
    be moved, reachable only by a job, on a schedule; a fill that arrived by any other door sat in
    the ledger until a job ran, and if no job read that door it sat there forever. It did. The
    recompute is called by every door, so the question "did it fold?" stops existing.

    Sleeve no longer appears here either. Zak, 2026-08-18: *"As for tagging as pre-seed or momentum
    etc... I'm not so certain why we would do either. That's just the book."* §2.1 makes the account
    the allocation, `desk.held_book` reads the account, and nothing in the live path branches on the
    label — so there is no longer a wrong value to guess at. Since migration 064 the label is not
    guessed at all: `yuna_book_from_ledger` transcribes the sleeve the newest ticketed transaction
    names, and a ticket-less history stays `unassigned` (learning 61).

    `applied_at` stays the idempotence stamp for the ticket advance, so a re-run finds nothing and
    advances nothing twice.

    One row at a time, under its own savepoint, for the reason `derive_ticket_fills` gives (A21): a
    position the ledger refuses to move — a row committed while the trigger was missing, or a
    position split across book rows wherever migration 069's index is not — keeps its row
    unstamped and goes into `refused`, and every other receipt still lands.
    """
    cur.execute("""select t.id, t.ticket_id, t.ticker, t.account, t.side, t.qty, t.price,
                          t.trade_date
                     from transactions t
                    where t.applied_at is null and t.side in ('buy','sell')
                      and t.superseded_by is null
                    order by t.trade_date, t.id""")
    applied = []
    for txn, ticket, tk, acct, side, qty, price, when in cur.fetchall():
        # Belt and braces: the trigger has already done this, and calling it again costs one query
        # and cannot produce a different answer — it is a recompute, not an increment. If the
        # trigger is ever missing (a database restored from before 059), this is what still holds.
        cur.execute("savepoint receipt")
        try:
            apply_to_book(cur, acct, tk)
        except psycopg.errors.RaiseException as e:
            cur.execute("rollback to savepoint receipt")
            if refused is None:
                raise
            refused.append(dict(account=acct, ticker=tk, ticket=ticket, transaction=txn,
                                receipt=f"{side} {float(qty):g} @ {float(price):g} on {when}",
                                why=refusal(e)))
            continue
        cur.execute("release savepoint receipt")
        cur.execute("update transactions set applied_at = now() where id = %s", (txn,))
        if ticket is not None:
            # `-> executed` is a fact about the broker and this receipt states it. The advance to
            # `reconciled` stays with the position block — only the outside witness attests.
            # A receipt that NAMES its ticket advances it from any state before a receipt: a
            # proposal the next sheet superseded (`sheet.write_tickets`, A57) was still the order
            # Zak executed, when the report of it arrives after that sheet was scored.
            cur.execute("""update tickets set state = 'executed',
                                  executed_at = coalesce(executed_at, now()), updated_at = now()
                            where id = %s and state = any(%s)""", (ticket, list(AWAITING)))
        applied.append(f"{side} {float(qty):g} {tk} @ {float(price):g} ({acct}, {when}) "
                       f"— in the book, ticket advanced")
    return applied


def settle_tickets(cur, account, fills):
    """Advance the ticket each receipt settles: -> `executed` (§4.3).

    The ticket is the one `fold_fill` linked the receipt's own transaction to — the fill's explicit
    `ticket_id`, or the sheet in force on the trade date (`ticket_for`). It used to re-match on its
    own, against the OLDEST ticket still awaiting a receipt for the (ticker, action), and that is
    three defects in one query (A57): two partial fills of one order advanced two different
    tickets; a manifest left in `data/reconcile/` advanced another, unrelated ticket every night it
    was re-read, because its own was no longer awaiting; and with August's never-withdrawn
    proposals in the table, the ticket advanced was weeks stale while the one Zak executed stayed
    `proposed`. Following the link makes the settle say what the fold recorded, and a re-read
    manifest settles nothing twice.

    A receipt with no ticket behind it is not an error — Zak may act outside the sheet, and §0.2
    makes that his prerogative — but it IS reported, because an engine position nobody proposed is
    a position the engine will not manage.
    """
    settled, orphans = [], []
    for f in fills:
        action = "buy" if f["side"] == "buy" else "sell"
        cur.execute("""select k.id, k.session_date, k.state
                         from transactions t join tickets k on k.id = t.ticket_id
                        where t.broker_ref = %s""", (f["ref"],))
        row = cur.fetchone()
        if row is None:
            orphans.append(f"{action} {float(f['qty']):g} {f['ticker']} @ {float(f['price']):g} "
                           f"({f['trade_date']}) — no engine ticket proposed it")
            continue
        tid, session, state = row
        if state in AWAITING:
            cur.execute("""update tickets set state = 'executed',
                                  executed_at = coalesce(executed_at, now()), updated_at = now()
                            where id = %s""", (tid,))
            settled.append(f"{action} {f['ticker']} -> ticket {tid} ({session})")
    return settled, orphans


def compare_positions(cur, account, positions):
    """The outside witness. Broker positions vs `book`, both directions. Returns a list of breaks.

    Both directions matter and they fail differently. A name the broker holds and the book does not
    is a position the engine will never sell — it is not in the book, so it is not in `held`, so no
    rank exit can ever queue it. A name the book holds and the broker does not is a phantom the
    engine counts against its five slots, so it blocks a real entry for ever.

    "The book" is what the engine reads: every open row of the (account, ticker), SUMMED, exactly
    as `desk.held_book` sums them (A27). This used to key one row per ticker, so a position in two
    open rows compared whichever row Postgres happened to return last — and since the ledger's
    single-row update moves the full-quantity row to the end of the heap, a broker showing VXC.TO's
    true 279 would most likely have matched the 279 row, attested the account reconciled, and left
    the 418 the engine and the brief read unchallenged. A position held in more than one open row
    is also a break of its own, whatever the sum says: the ledger refuses to move it, and only a
    direct write to `book` where migration 069's index is not can produce it.
    """
    said = {p["ticker"]: float(p["qty"]) for p in positions}
    cur.execute("""select ticker, sum(qty), min(sleeve), count(*) from book
                    where account = %s and status = 'open'
                    group by ticker order by ticker""", (account,))
    ours = {t: (float(q), s, n) for t, q, s, n in cur.fetchall()}

    breaks = []
    for tk in sorted(set(said) | set(ours)):
        broker = said.get(tk)
        book_qty, sleeve, rows = ours.get(tk, (None, None, 0))
        if broker is not None and book_qty is None:
            breaks.append(dict(ticker=tk, broker=broker, book=None,
                               why="the broker holds it and the book does not — the engine can "
                                   "never queue an exit for a position it cannot see"))
        elif book_qty is not None and broker is None:
            breaks.append(dict(ticker=tk, broker=None, book=book_qty, sleeve=sleeve,
                               why="the book holds it and the broker does not — a phantom "
                                   "position occupies one of §3.5's five slots"))
        elif rows > 1:
            off = ("" if abs(broker - book_qty) <= QTY_TOL
                   else f"; together they differ from the broker by {broker - book_qty:+g} shares")
            breaks.append(dict(ticker=tk, broker=broker, book=book_qty, sleeve=sleeve,
                               open_rows=rows,
                               why=f"the book holds it in {rows} open rows, {book_qty:g} shares "
                                   f"between them — a position is one row, and the ledger refuses "
                                   f"to move this one until the stray row is closed{off}"))
        elif abs(broker - book_qty) > QTY_TOL:
            breaks.append(dict(ticker=tk, broker=broker, book=book_qty, sleeve=sleeve,
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


def named(r):
    """One refused receipt, as the run's red and the log name it: the position, the receipt, and
    the ledger's own reason with the repair it points at."""
    by = (f"ticket {r['ticket']}" if r.get("ticket") is not None
          else f"transaction {r['transaction']}")
    return f"{r['account']} {r['ticker']} ({by}, {r['receipt']}): {r['why']}"


def main():
    docs = manifests()
    with connect() as conn, Heartbeat(conn, "reconcile", dry_run=dry()) as hb:
        folded, settled, orphans, breaks, closed, refused = [], [], [], [], [], []
        with conn.cursor() as cur:
            # The chat route runs FIRST and on manifest-less nights too, because it is the ordinary
            # path: §4.3 makes a session's report of a fill the routine way a receipt enters the
            # system, and an export is the exception. Derive the ledger row from the ticket, then
            # fold every unapplied row into the book — the two halves the retired `score` and
            # `fills` used to walk.
            if dry():
                cur.execute("""select count(*) from tickets k
                                where k.fill_price is not null and k.fill_qty is not null
                                  and k.state in ('executed','confirmed','provisional')
                                  and not exists (select 1 from transactions t
                                                   where t.ticket_id = k.id)""")
                pending_tickets = cur.fetchone()[0]
                cur.execute("""select count(*) from transactions
                                where confirmed and applied_at is null
                                  and superseded_by is null
                                  and side in ('buy','sell')""")
                pending_txns = cur.fetchone()[0]
                derived = ([f"{pending_tickets} ticket fill(s) would derive a ledger row"]
                           if pending_tickets else [])
                chat = ([f"{pending_txns} ledger row(s) would fold into the book"]
                        if pending_txns else [])
            else:
                # A refusal is collected per receipt, not raised (A21): one sell the ledger cannot
                # take must not hold back every other fill reported that night, and it must not
                # leave the night's red without a name.
                derived = derive_ticket_fills(cur, refused)
                chat = apply_unapplied(cur, refused)
                # The chat route stands on its own, so it is committed before any manifest is
                # read. A malformed receipt below stops the job (`fold_fill`'s SystemExit) and the
                # heartbeat rolls back whatever the job had not committed (db.Heartbeat,
                # 2026-10-07): the refused manifest folds nothing, as its message says, and
                # without this line every chat-reported fill would go down with it — every night
                # until the file was fixed, which is the 2026-08-18 ghost book again.
                conn.commit()

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

        hb.rows = len(folded) + len(derived) + len(chat)
        hb.detail.update(manifests=[n for n, _ in docs], folded=folded, settled=settled,
                         orphan_fills=orphans, breaks=breaks, reconciled=closed,
                         ticket_fills_derived=derived, book_folds=chat, refused=refused)
        with conn.cursor() as cur:
            cur.execute("select * from v_reconciliation_age")
            cols = [d[0] for d in cur.description]
            hb.detail["age"] = {c: str(v) for c, v in zip(cols, cur.fetchone())}

        if orphans:
            hb.amber(f"{len(orphans)} fill(s) with no engine ticket behind them — an engine "
                     f"position nobody proposed is one the engine will not manage")
        if refused:
            # Red for the reason a break is red: the receipt Zak reported has not reached the book,
            # so the book still holds what he no longer does and §3.5 would size against it. §4.4
            # holds the buys; the refused ticket keeps its fill and is tried again every night
            # until the history is repaired, and this line says which one and why.
            hb.red(f"{len(refused)} receipt(s) refused by the ledger — every other receipt "
                   f"landed: " + "; ".join(named(r) for r in refused))
        if breaks:
            # §4.4: any red holds buys; nothing holds exits. A book that disagrees with the broker
            # cannot be sized against, and every §3.5 decision is a function of what is held.
            hb.red(f"{len(breaks)} position(s) disagree between the broker and the book: "
                   + "; ".join(f"{b['ticker']} broker={b['broker']} book={b['book']}"
                               for b in breaks))

        if not docs and not derived and not chat and not refused:
            # Not a failure. §4.4 gauges the AGE of the last reconciliation, and a night with no
            # export and nothing reported in chat is an ordinary night — the gauge, not this job,
            # is what notices a stale one.
            print("reconcile: nothing to fold — no manifest, no ticket fill, no unapplied "
                  "receipt. The book stands as it was.")
            return 0

        print(f"reconcile: {len(derived)} ticket fill(s) derived · {len(chat)} folded into the "
              f"book · {len(folded)} manifest receipt(s) · {len(settled)} ticket(s) executed · "
              f"{len(closed)} reconciled · {len(refused)} refused · {len(breaks)} break(s)")
        for line in derived + chat + folded + settled + orphans + closed:
            print(f"  {line}")
        for r in refused:
            print(f"  REFUSED {named(r)}")
        for b in breaks:
            print(f"  BREAK {b['ticker']:<10} broker={b['broker']} book={b['book']} — {b['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
