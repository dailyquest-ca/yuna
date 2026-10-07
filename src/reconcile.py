"""reconcile — §4.1's fifth job. The broker's receipt against the book, post-execution.

§4.3: "Yuna writes rows; Zak's execution is the event; reconcile closes the loop with the receipt."
This is the loop closing. A receipt reaches the system by two routes and this job walks both —
after one step that comes before any receipt:

  S. **A split on a held name enters the ledger first.** Zak's ruling of 2026-10-07 ("Pipeline
     records splits"): a vendor-reported split on a held name is written to the ledger, quantity
     only and no cash, before score runs, and the brief shows it; ticker changes and takeovers
     still fail closed until he records them. `record_splits` writes one `split` row per
     position (migration 075) — the shares restated by the ratio, the cost basis carried, no cash
     — so the book `score` reads holds the post-split count, and a post-split sale reported the
     same night lands after it rather than being refused (A21).
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
import math
import os
import pathlib
import sys

import psycopg

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import signals as sg                                                       # noqa: E402
from db import connect, dry, Heartbeat                                     # noqa: E402
from desk import ENGINE_ACCOUNT                                            # noqa: E402

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


# ---- a split on a held name (Zak's ruling, 2026-10-07; migration 075) ----------------------------

def ratio_text(ratio):
    """A split the way it is spoken of: 2.0 -> "2:1", 0.1 -> "1:10", 6.665 -> "6.665:1"."""
    return f"{ratio:g}:1" if ratio >= 1 else f"1:{1 / ratio:g}"


def tape_on_split(cur, ticker, d, ratio):
    """What the raw closes either side of a split's date say about it. Returns (verdict, seen).

    Two facts of the market, and no tolerance of this file's own. A split restates the price on
    its ex-date by its ratio — the vendor's date is the ex-date, the first session on the new basis
    (APH 160.08 -> 82.07 on 2026-09-03, TOP 2.06 -> 10.52 on 08-03) — and a past raw close never
    changes after it: `prices.close` is the print, `adj_close` is what the vendor restates. So the
    last close before `d` over the first close on or after it is the ratio, give or take a
    session's move, if the split happened there, and 1, give or take the same move, if it did not.
    The tape is read as whichever of the two it is NEARER to, in log terms — the midpoint between
    "split" and "no split" is the geometric one, and it comes from the two hypotheses, not from a
    number anyone chose.

    It is needed because the vendor posts splits that did not happen on the date posted: RUSHA.US
    and RUSHB.US carry a 3:2 on 2026-08-11, when the raw close went 80.20 -> 81.59, and the real
    one on 09-01 (76.83 -> 48.75). Applied to a held name, the August posting would have restated
    the position three weeks early and the real one would have restated it again.

      agrees       nearer the split: record it
      contradicts  nearer no split: the posting is not what the tape did on that date
      pending      no bar on or after `d` yet — the tape has not reached the split, and the book's
                   pre-split count agrees with the newest close it is marked at
      unreadable   no bar before `d`, or a close that is not a price
    """
    cur.execute("""select d, close from prices where ticker = %s and d < %s
                    order by d desc limit 1""", (ticker, d))
    before = cur.fetchone()
    cur.execute("""select d, close from prices where ticker = %s and d >= %s
                    order by d limit 1""", (ticker, d))
    after = cur.fetchone()
    if after is None:
        return "pending", f"no {ticker} bar on or after {d} yet"
    if before is None or before[1] is None or after[1] is None:
        return "unreadable", f"no {ticker} close before {d} to measure the split against"
    was, now = float(before[1]), float(after[1])
    if not (was > 0 and now > 0 and math.isfinite(was) and math.isfinite(now)):
        return "unreadable", f"{ticker} closed {was:g} on {before[0]} and {now:g} on {after[0]}"
    moved = was / now
    seen = f"raw close {was:g} on {before[0]} -> {now:g} on {after[0]}, x{moved:.4g}"
    if abs(math.log(moved) - math.log(ratio)) < abs(math.log(moved)):
        return "agrees", seen
    return "contradicts", seen


def record_splits(cur, refused, write=True):
    """Every vendor-reported split on a held name, into the ledger before `score` reads the book.

    Zak's ruling of 2026-10-07 ("Pipeline records splits"): a vendor-reported split on a held name
    is written to the ledger, quantity only and no cash, before score runs, and the brief shows it.
    One `split` row per position (migration 075 says why it is a verb of its own and not a
    `confirm`): qty is the ratio, price 0, dated the vendor's ex-date. It restates every earlier row
    of the position — shares x ratio, money unchanged — and `yuna_book_from_ledger` moves the book.
    That is A1 (an exit sells the post-split count), A2 (engine NAV marks the right count at the new
    close) and A32 (the session's marked equity is not inflated by a reverse split) closed at
    source, and A21's root: tonight's post-split sale lands after the split instead of being
    refused.

    A position is a candidate for every split posted for its ticker that it does not already carry
    a `split` row for — superseded rows included, so a row Zak voided is never written again (and
    `transactions_one_split_per_position` refuses a second regardless). Then, in order:

      * no ledger history at all: a split cannot restate rows that do not exist. Refused when the
        holding may predate the split — record its opening position as a `confirm` first.
      * nothing held at the start of the split's date (bought after it, or sold out before it):
        nothing to restate, silently — "a split dated before the position opened is not applied".
      * a ratio the vendor's detail does not read as: refused.
      * **the ledger already reflects it** — quantity-only rows (price 0: a `confirm` the way
        Zak's ruling words it, or a buy or sell a session wrote for the shares) on or after the
        split's date, which is how his report of a post-split count may already be in. Rows that
        ARE the split's arithmetic (the shares it adds, net, within QTY_TOL) are left as the
        record; any others are refused, because which number is right is the broker's fact (§0.2).
      * the tape (`tape_on_split`): pending waits silently, unreadable is refused, a contradiction
        is reported and not recorded — quietly once a later split row restates the position, the
        shape of the vendor's early posting of a split it posts again on its real date.
      * **the same split under another date**: a split row of the same ratio with no position row
        between its date and this one restates the same shares. Recording the vendor's would apply
        the ratio twice, so it is refused for Zak to say which date is the split.

    Each write is under its own savepoint with the recompute forced inside it, as the receipts are
    (A21): a refusal is that split's alone. Refusals go into `refused` (account, ticker, split,
    why) — the caller turns them red, because a split that could not be recorded may leave the book
    holding the pre-split count, and §4.4 holds the buys on exactly that. Returns
    dict(recorded, already, contradicted, pending) as lines for the run's detail; with `write`
    false nothing is written and `recorded` says what would be.
    """
    out = dict(recorded=[], already=[], contradicted=[], pending=[])

    def refuse(account, ticker, split, why):
        refused.append(dict(account=account, ticker=ticker, split=split, why=why))

    cur.execute("""select b.account, b.ticker, b.qty, b.opened_at, b.currency, a.d, a.detail
                     from book b
                     join corporate_actions a on a.ticker = b.ticker and a.kind = 'split'
                    where b.status = 'open'
                      and not exists (select 1 from transactions t
                                       where t.account = b.account and t.ticker = b.ticker
                                         and t.side = 'split' and t.trade_date = a.d)
                    order by a.d, b.account, b.ticker""")
    for acct, tk, held, opened_at, book_ccy, d, detail in cur.fetchall():
        raw = (detail or {}).get("split") if isinstance(detail, dict) else detail
        posted = f"{raw} on {d}"

        cur.execute("select rows_seen, currency from yuna_ledger_position(%s, %s)", (acct, tk))
        rows_seen, ccy = cur.fetchone()
        if not rows_seen:
            if opened_at is None or opened_at < d:
                refuse(acct, tk, posted,
                       f"the book holds {float(held):g} with no ledger history, so a split dated "
                       f"{d} has nothing to restate — record the opening position as a `confirm` "
                       f"dated before {d}, with the count and cost the book holds (they are "
                       f"pre-split: nothing has restated them), and the next reconcile records "
                       f"the split")
            continue

        cur.execute("select qty from yuna_ledger_position(%s, %s, %s)", (acct, tk, d))
        before = cur.fetchone()[0]
        if before is None or before <= 1e-9:      # yuna_book_from_ledger's own "nothing held"
            continue

        ratio = sg.split_ratio(detail)
        if not ratio or not math.isfinite(ratio) or ratio <= 0 or ratio == 1:
            refuse(acct, tk, posted, f"the vendor's split detail {raw!r} does not read as a ratio")
            continue
        said = f"{ratio_text(ratio)} split, ex {d}"
        adds = before * (ratio - 1)

        # Quantity-only rows — shares with no money, price 0 — on or after the split's date: the
        # way the ruling words a split, and so the way a session may already have written this one
        # down when Zak reported his post-split count. A confirm or buy adds, a sell takes away.
        cur.execute("""select id, case when side = 'sell' then -qty else qty end from transactions
                        where account = %s and ticker = %s and side in ('buy', 'confirm', 'sell')
                          and price = 0 and superseded_by is null and trade_date >= %s
                        order by trade_date, id""", (acct, tk, d))
        by_hand = cur.fetchall()
        if by_hand:
            rows = ", ".join(f"#{i} ({float(q):+g})" for i, q in by_hand)
            net = sum(float(q) for _, q in by_hand)
            if abs(net - adds) <= QTY_TOL:
                # The shares agree, so it is not recorded twice. The cost per share is whatever
                # those rows make it — a `split` row restates it exactly, a confirm or a sell only
                # when no sell precedes it (075's header) — and they are Zak's rows to keep or void.
                out["already"].append(f"{acct} {tk} {said}: already in the ledger as quantity-only "
                                      f"row(s) {rows}, no cash — not recorded again (the shares "
                                      f"agree; the cost per share is as those rows leave it)")
            else:
                refuse(acct, tk, said,
                       f"quantity-only row(s) {rows} on or after {d} restate the position, and "
                       f"not as this split does ({adds:+g} shares on the {before:g} held) — which "
                       f"is right is the broker's fact: if they are the split, void them and the "
                       f"next reconcile records it; if not, ask Zak")
            continue

        verdict, seen = tape_on_split(cur, tk, d, ratio)
        if verdict == "pending":
            out["pending"].append(f"{acct} {tk} {said}: {seen}")
            continue
        if verdict == "unreadable":
            refuse(acct, tk, said, f"cannot be checked against the tape — {seen}")
            continue
        if verdict == "contradicts":
            cur.execute("""select min(trade_date) from transactions
                            where account = %s and ticker = %s and side = 'split'
                              and superseded_by is null and trade_date > %s""", (acct, tk, d))
            later = cur.fetchone()[0]
            if later is None:
                out["contradicted"].append(f"{acct} {tk} {said}: the tape says no split — {seen}"
                                           f" — not recorded")
            else:
                out["already"].append(f"{acct} {tk} {said}: the tape says no split ({seen}), "
                                      f"and the split recorded {later} already restates the "
                                      f"position — not recorded")
            continue

        cur.execute("""select s.id, s.trade_date from transactions s
                        where s.account = %(a)s and s.ticker = %(t)s and s.side = 'split'
                          and s.superseded_by is null and s.qty = %(r)s and s.trade_date <> %(d)s
                          and not exists (select 1 from transactions p
                                           where p.account = s.account and p.ticker = s.ticker
                                             and p.superseded_by is null and p.side <> 'split'
                                             and p.trade_date >= least(s.trade_date, %(d)s)
                                             and p.trade_date <  greatest(s.trade_date, %(d)s))
                        order by s.trade_date limit 1""",
                    dict(a=acct, t=tk, r=ratio, d=d))
        twin = cur.fetchone()
        if twin:
            refuse(acct, tk, said,
                   f"split #{twin[0]} already restates the same shares by the same ratio, dated "
                   f"{twin[1]} — recording the vendor's {d} too would apply it twice; if they "
                   f"are one split, re-date #{twin[0]} to {d}, and if two, ask Zak")
            continue

        if not write:
            out["recorded"].append(f"{acct} {tk} {said}: would restate {before:g} pre-split "
                                   f"shares to {before * ratio:g}, no cash ({seen})")
            continue

        cur.execute("savepoint split")
        try:
            cur.execute("""select qty, avg_cost from book
                            where account = %s and ticker = %s and status = 'open'""", (acct, tk))
            was_qty, was_cost = cur.fetchone()
            cur.execute("""insert into transactions (ticker, account, side, qty, price, currency,
                                                     fees, trade_date, confirmed, confirmed_at,
                                                     applied_at, grade, source, note)
                           values (%s, %s, 'split', %s, 0, %s, 0, %s, true, now(), now(),
                                   'stated', %s, %s)
                           on conflict (account, ticker, trade_date) where side = 'split'
                           do nothing returning id""",
                        (tk, acct, ratio, ccy or book_ccy or "USD", d,
                         f"vendor split {raw} (corporate_actions), recorded by reconcile on "
                         f"Zak's ruling of 2026-10-07",
                         f"{said} — the tape agrees: {seen}"))
            row = cur.fetchone()
            if row is None:                       # written meanwhile: one row per split, ever
                cur.execute("rollback to savepoint split")
                continue
            apply_to_book(cur, acct, tk)
            cur.execute("""select qty, avg_cost from book
                            where account = %s and ticker = %s and status = 'open'""", (acct, tk))
            now_qty, now_cost = cur.fetchone()
            line = (f"{acct} {tk} {said}: {float(was_qty):g} -> {float(now_qty):g} shares, "
                    f"cost/share {float(was_cost):.4f} -> {float(now_cost):.4f}, no cash moved "
                    f"(the tape agrees: {seen})")
            # Recorded late — the vendor posted it after its ex-date night — the sessions scored
            # in between were marked on the pre-split count, and their stored marked equity and
            # NAV keep it (§0.6 keeps the record; a restatement is Zak's to rule). Named, because
            # a reverse split's is a peak `v_engine_drawdown` keeps (A32). On time there are none:
            # this runs before tonight's `score` writes the ex-date's session.
            cur.execute("""select count(*), min(session_date), max(session_date)
                             from engine_sessions where mode = 'live' and session_date >= %s""",
                        (d,))
            stale, first, last = cur.fetchone()
            if stale and acct == ENGINE_ACCOUNT:
                line += (f" — recorded late: {stale} live session(s) {first}..{last} were scored "
                         f"on the pre-split count and keep those marks; tonight's score re-marks "
                         f"only its own session (A32)")
            # The note IS the line — "and the brief shows it": the brief prints the row as it is.
            cur.execute("update transactions set note = %s where id = %s", (line, row[0]))
        except psycopg.errors.RaiseException as e:
            cur.execute("rollback to savepoint split")
            refuse(acct, tk, said, refusal(e))
            continue
        cur.execute("release savepoint split")
        out["recorded"].append(line)
    return out


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
    """One refused receipt or split, as the run's red and the log name it: the position, what was
    refused, and the reason with the repair it points at."""
    if r.get("split"):
        return f"{r['account']} {r['ticker']} ({r['split']}): {r['why']}"
    by = (f"ticket {r['ticket']}" if r.get("ticket") is not None
          else f"transaction {r['transaction']}")
    return f"{r['account']} {r['ticker']} ({by}, {r['receipt']}): {r['why']}"


def main():
    docs = manifests()
    with connect() as conn, Heartbeat(conn, "reconcile", dry_run=dry()) as hb:
        folded, settled, orphans, breaks, closed, refused = [], [], [], [], [], []
        with conn.cursor() as cur:
            # A split on a held name goes in before any receipt (Zak's ruling, 2026-10-07): `score`
            # reads the book next, and a post-split sale reported tonight must find the post-split
            # count to net against, not be refused for exceeding the pre-split one (A21). The
            # dry run reads the same verdicts and writes nothing. Committed on its own, like the
            # receipts below, so a manifest that dies later cannot take the split with it.
            splits = record_splits(cur, refused, write=not dry())
            if not dry():
                conn.commit()

            # The chat route runs next and on manifest-less nights too, because it is the ordinary
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
                # Committed on its own: the ordinary route's receipts are not hostage to a manifest
                # that dies below.
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

        recorded = [] if dry() else splits["recorded"]
        hb.rows = len(folded) + len(derived) + len(chat) + len(recorded)
        hb.detail.update(manifests=[n for n, _ in docs], folded=folded, settled=settled,
                         orphan_fills=orphans, breaks=breaks, reconciled=closed,
                         ticket_fills_derived=derived, book_folds=chat, refused=refused,
                         splits=splits)
        with conn.cursor() as cur:
            cur.execute("select * from v_reconciliation_age")
            cols = [d[0] for d in cur.description]
            hb.detail["age"] = {c: str(v) for c, v in zip(cols, cur.fetchone())}

        if recorded:
            # Amber, and only to be SEEN: a split recorded is the system working, and it holds
            # nothing — §4.3 holds buys on an amber from `ingest-daily` or `score` alone, so this
            # rides the freshness line as "(that domain only)" and the reconciliation gauge reads
            # only a red. Zak's ruling has the brief show it; the ledger row carries the same line.
            hb.amber(f"{len(recorded)} split(s) recorded in the ledger before score — the shares "
                     f"restated, the cost basis carried, no cash moved: " + "; ".join(recorded))
        if splits["contradicted"]:
            # Not recorded, and not red: the tape is the evidence that the book is right. A
            # vendor's claim about a held name that the tape refutes is still worth Zak's eyes.
            hb.amber(f"{len(splits['contradicted'])} vendor split(s) on a held name the tape "
                     f"contradicts — not recorded: " + "; ".join(splits["contradicted"]))
        if orphans:
            hb.amber(f"{len(orphans)} fill(s) with no engine ticket behind them — an engine "
                     f"position nobody proposed is one the engine will not manage")
        receipts = [r for r in refused if not r.get("split")]
        held_back = [r for r in refused if r.get("split")]
        if held_back:
            # Red, because a split that could not be recorded may leave the book holding the
            # pre-split count: §3.5 would size buys off NAV marked at the wrong count and the exit
            # would sell the wrong number (A1, A2). §4.4 holds the buys; exits stand. Each split is
            # tried again every night until it lands or the line's repair is made.
            hb.red(f"{len(held_back)} split(s) on a held name not recorded — the book may hold the "
                   f"pre-split count: " + "; ".join(named(r) for r in held_back))
        if receipts:
            # Red for the reason a break is red: the receipt Zak reported has not reached the book,
            # so the book still holds what he no longer does and §3.5 would size against it. §4.4
            # holds the buys; the refused ticket keeps its fill and is tried again every night
            # until the history is repaired, and this line says which one and why.
            hb.red(f"{len(receipts)} receipt(s) refused by the ledger — every other receipt "
                   f"landed: " + "; ".join(named(r) for r in receipts))
        if breaks:
            # §4.4: any red holds buys; nothing holds exits. A book that disagrees with the broker
            # cannot be sized against, and every §3.5 decision is a function of what is held.
            hb.red(f"{len(breaks)} position(s) disagree between the broker and the book: "
                   + "; ".join(f"{b['ticker']} broker={b['broker']} book={b['book']}"
                               for b in breaks))

        split_lines = (splits["recorded"] + splits["already"] + splits["contradicted"]
                       + splits["pending"])
        if not docs and not derived and not chat and not refused and not split_lines:
            # Not a failure. §4.4 gauges the AGE of the last reconciliation, and a night with no
            # export and nothing reported in chat is an ordinary night — the gauge, not this job,
            # is what notices a stale one.
            print("reconcile: nothing to fold — no manifest, no ticket fill, no unapplied "
                  "receipt, no split on a held name. The book stands as it was.")
            return 0

        print(f"reconcile: {len(splits['recorded'])} split(s) "
              f"{'would be ' if dry() else ''}recorded · {len(derived)} ticket fill(s) derived · "
              f"{len(chat)} folded into the book · {len(folded)} manifest receipt(s) · "
              f"{len(settled)} ticket(s) executed · {len(closed)} reconciled · "
              f"{len(refused)} refused · {len(breaks)} break(s)")
        for line in splits["recorded"]:
            print(f"  SPLIT {line}")
        for line in splits["already"] + splits["contradicted"] + splits["pending"]:
            print(f"  split not recorded: {line}")
        for line in derived + chat + folded + settled + orphans + closed:
            print(f"  {line}")
        for r in refused:
            print(f"  REFUSED {named(r)}")
        for b in breaks:
            print(f"  BREAK {b['ticker']:<10} broker={b['broker']} book={b['book']} — {b['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
