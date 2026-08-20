"""arming — everything `score` derives about the book, and the night's conclusions (§3.0, §4.2).

Runs after the bars land, and does everything that must be true before the open:

  fills applied -> bases re-scanned -> breakouts classified -> stops ratcheted -> the book revalued
  against the latest bars -> NAV -> exits, adds and entries armed -> caps applied -> shadow book.

**A library, not a job.** §4.2 gives every derived number one writer and names it `score`, which
calls `run()` below. Two of these numbers used to have two writers between them, which is the
whole reason the architecture was rewritten.

It writes no tickets. §2.2 and §4.3 both say jobs arm and only sessions write tickets, because a
ticket carries a theme and a theme is judgment. So every conclusion lands in `armed`, priced and
cap-checked, and R1/R2 turn those into tickets. Protective conclusions are marked urgency
'protective': they survive a stale-data night, and nothing else does.
"""
import datetime as dt

import numpy as np

from db import (cash_by_account, config, dry, freshness, jsonb, load_bars, nav_cad, observe,
                session_date_for, valuation_canary, quantity_canary)
import signals as sg


class ValuationMismatch(RuntimeError):
    """§4.2: a holding priced off anything but its latest bar fails the run, red."""


# --------------------------------------------------------------------------- fills (§4.5)
def apply_fills(conn, hb):
    """Fold confirmed fills into the book, exactly once each.

    A buy on a name we do not hold opens a position; a buy on one we do is an add and moves the
    average cost and the pyramid step; a sell reduces or closes. Provisional rows are included on
    purpose — §4.5 says weekday NAV runs on provisionals and Sunday trues them up.
    """
    applied = []
    with conn.cursor() as cur:
        cur.execute("""select t.id, t.ticker, t.account, t.side, t.qty, t.price, t.currency,
                              t.trade_date, t.pyramid_step, t.ticket_id, k.sleeve, k.theme,
                              k.stop, k.stop_limit_price, k.trigger_price, k.target_qty
                       from transactions t
                       left join tickets k on k.id = t.ticket_id
                       where t.applied_at is null and t.superseded_by is null
                       order by t.trade_date, t.id""")
        rows = cur.fetchall()
        if dry():
            # §4.2: every job carries DRY_RUN, and DRY_RUN means compute everything and write
            # nothing. This pass wrote the book regardless — so a rehearsal moved real positions,
            # and the one job whose whole purpose is to be rehearsed (`fills`) inherited it.
            hb.detail["fills_would_apply"] = [f"{r[3]} {float(r[4]):g} {r[1]} @ {float(r[5]):g}"
                                              for r in rows]
            return []
        for (tid, tk, acct, side, qty, price, ccy, tdate, step, ticket_id, sleeve, theme,
             stop, stop_limit, pivot, target_qty) in rows:
            qty, price = float(qty), float(price)
            if side == "confirm":
                # A `confirm` row restates a share count the book already holds — R4's opening
                # balances, and since migration 059 the way a position older than the ledger enters
                # it. It moves nothing. Without this it fell through to the `else` below and was
                # folded as a SELL, closing the position it existed to establish. `cash_by_account`
                # has always excluded it for the same reason; this loop never learned.
                cur.execute("update transactions set applied_at=now() where id=%s", (tid,))
                continue
            # **Quantity is no longer this loop's business.** Since migration 059 the ledger owns
            # it: `ledger_moves_the_book` recomputed the position the moment the transaction was
            # inserted, so by the time this runs the book already holds the right number of shares
            # and the position is already open or already closed. Adding the same fill again here
            # doubled a buy and subtracted a sell twice.
            #
            # What is left is the metadata the ledger cannot know — a stop is not a fact about a
            # trade — and that is what this loop now does. It belongs to §3.2's retired apparatus
            # (v1.0 has no stops and no pyramids), which is why it survives here and nowhere newer.
            cur.execute("""select id, qty, trail_mode from book
                           where ticker=%s and account=%s and status='open'""", (tk, acct))
            held = cur.fetchone()
            if side == "buy" and held:
                bid, bqty, trail = held
                if trail is None:
                    # A bare row: the ledger opened it and knows nothing about stops. §3.2:
                    # "Initial: higher of the base's final-contraction low, or entry − 8%. Never
                    # wider than 8%." A ticket the machine armed carries that stop already; a fill
                    # with no ticket behind it — Zak's own trade, reconciled later (R4) — carries
                    # none, and the ratchet only ever moves an EXISTING stop upward, so the position
                    # would have opened unprotected and stayed that way.
                    if stop is None and (sleeve or "momentum") == "momentum":
                        cur.execute("select base_low from candidates where ticker=%s", (tk,))
                        base = cur.fetchone()
                        max_stop = float(config(cur, "momentum_max_stop", 0.08))
                        stop = sg.initial_stop(price,
                                               float(base[0]) if base and base[0] else None,
                                               max_stop=max_stop)
                        stop_limit = stop * (1 - float(config(cur, "stop_limit_buffer", 0.03)))
                    # the stall clock starts at entry: §3.2 gives a pyramid four weeks to reach full
                    # size, and nothing was starting it before
                    cur.execute("""update book set sleeve=%s, lot='core', stop=%s, stop_limit=%s,
                                     highest_close=%s, trail_mode='initial', pyramid_step=%s,
                                     theme=%s, pivot=%s, target_qty=%s, opened_at=%s,
                                     pyramid_stalled_since=%s, updated_at=now() where id=%s""",
                                (sleeve or "momentum", stop, stop_limit, price, step or 1, theme,
                                 pivot, target_qty, tdate,
                                 tdate if (sleeve or "momentum") == "momentum" else None, bid))
                else:
                    cur.execute("""update book set
                                     pyramid_step=greatest(pyramid_step, coalesce(%s, pyramid_step)),
                                     pyramid_stalled_since = case
                                       when greatest(pyramid_step, coalesce(%s, pyramid_step)) >= 3
                                       then null else pyramid_stalled_since end,
                                     adds_12m = adds_12m + case when %s then 1 else 0 end,
                                     last_add_at = case when %s then %s else last_add_at end,
                                     updated_at=now() where id=%s""",
                                (step, step, sleeve == "compounders", sleeve == "compounders",
                                 tdate, bid))
            cur.execute("update transactions set applied_at=now() where id=%s", (tid,))
            if ticket_id:
                cur.execute("""update tickets set state='provisional', updated_at=now()
                               where id=%s and state in ('proposed','approved')""", (ticket_id,))
            applied.append(f"{side} {qty:g} {tk} @ {price:g}")
    conn.commit()
    hb.detail["fills_applied"] = applied
    return applied


def sync_fills_from_tickets(conn, hb):
    """§4.5 fill loop under the 2026-08-04 write list: a fill travels as ticket state — chat or
    flip writes `fill_*` on the ticket and marks it provisional — and THIS job derives the
    transactions row, because the 2026-08-04 §4.3 did not let a session touch the ledger. (059
    reversed that — sessions write `transactions` directly now; this path stays only for the
    retired dispatch jobs.) Sunday's
    confirmation flips the ticket to confirmed with trued numbers; the same pass here trues the
    transaction. Both directions are idempotent: one transaction per ticket, updates by delta.

    A ticket written straight to `confirmed` is derived too. R4 step 2 routes a fill with no
    ticket behind it — Zak's own discretionary trade — through exactly that shape, "so the nightly
    job can carry it into the book". It could not: this pass only read `provisional`, and the
    trueing pass below only UPDATES rows that already exist, so a settled discretionary fill
    landed in no ledger and no book at all. Four of them did, on 2026-08-04.
    """
    made, trued = [], []
    with conn.cursor() as cur:
        cur.execute("""select k.id, k.ticker, k.account, k.action, k.fill_qty, k.fill_price,
                              coalesce(k.currency, 'USD'), k.fill_fx, k.fill_fees,
                              coalesce(k.fill_date, current_date), k.state
                       from tickets k
                       where k.state in ('provisional', 'confirmed') and k.fill_price is not null
                         and k.fill_qty is not null and k.account is not null
                         and not exists (select 1 from transactions t where t.ticket_id = k.id)
                       order by k.fill_date, k.id""")
        pending = cur.fetchall()
        if dry():
            hb.detail["fills_would_derive"] = [f"{r[1]} {float(r[4]):g} @ {float(r[5]):g}"
                                               for r in pending]
            return []
        for tid, tk, acct, action, qty, price, ccy, fxr, fees, tdate, state in pending:
            side = "sell" if action in ("sell", "exit") else "buy"
            settled = state == "confirmed"
            cur.execute("""insert into transactions (ticket_id, ticker, account, side, qty,
                             price, currency, fx_rate, fees, trade_date, confirmed, confirmed_at)
                           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                   case when %s then now() else null end)""",
                        (tid, tk, acct, side, qty, price, ccy, fxr, fees or 0, tdate,
                         settled, settled))
            made.append(f"{side} {float(qty):g} {tk} @ {float(price):g} (ticket {tid}"
                        + (", settled)" if settled else ")"))
        cur.execute("""select k.id, k.fill_qty, k.fill_price, k.fill_fx, k.fill_fees, k.fill_date
                       from tickets k join transactions t on t.ticket_id = k.id
                       where k.state = 'confirmed' and not t.confirmed""")
        for tid, qty, price, fxr, fees, tdate in cur.fetchall():
            cur.execute("""update transactions set
                             qty = coalesce(%s, qty), price = coalesce(%s, price),
                             fx_rate = coalesce(%s, fx_rate), fees = coalesce(%s, fees),
                             trade_date = coalesce(%s, trade_date),
                             confirmed = true, confirmed_at = now()
                           where ticket_id = %s""", (qty, price, fxr, fees, tdate, tid))
            trued.append(tid)
    conn.commit()
    if made:
        hb.detail["fills_derived_from_tickets"] = made
    if trued:
        hb.detail["fills_confirmed_from_tickets"] = trued
    return made


# --------------------------------------------------------------------------- splits (§4.1)
def rebase_for_splits(conn, hb):
    """Re-base a held position's stored prices when its stock splits.

    The bars get re-pulled by `ingest`; these numbers do not, and they are all nominal: avg cost,
    stop, stop-limit, highest close, pivot. Because stops ratchet up and never down (§3.2), an
    unadjusted stop after a 4:1 split sits four times above the market and can never come back —
    the position reads as stopped out every night for the rest of its life.
    """
    done = []
    with conn.cursor() as cur:
        cur.execute("""select a.ticker, a.d, a.detail, b.id
                       from corporate_actions a
                       join book b on b.ticker = a.ticker and b.status = 'open'
                       where a.kind = 'split' and a.applied_to_book_at is null""")
        for tk, d, payload, bid in cur.fetchall():
            ratio = sg.split_ratio(payload)
            if not ratio or ratio <= 0:
                hb.amber(f"{tk} split on {d} could not be parsed — position prices NOT re-based")
                continue
            if not dry():
                cur.execute("""update book set qty = qty * %s, avg_cost = avg_cost / %s,
                                 stop = stop / %s, stop_limit = stop_limit / %s,
                                 highest_close = highest_close / %s, pivot = pivot / %s,
                                 target_qty = target_qty * %s, updated_at = now()
                               where id = %s""",
                            (ratio, ratio, ratio, ratio, ratio, ratio, ratio, bid))
                cur.execute("""update corporate_actions set applied_to_book_at = now()
                               where ticker=%s and d=%s and kind='split'""", (tk, d))
                observe(cur, "note",
                        f"{tk} split {ratio:g}:1 on {d} — position re-based: quantity x{ratio:g}, "
                        f"cost, stop and pivot / {ratio:g}. Without this the stop stays above the "
                        f"market and the ratchet can never bring it down (§3.2).",
                        ticker=tk, detail=dict(ratio=ratio, d=str(d)))
            done.append(dict(ticker=tk, ratio=ratio, d=str(d)))
    conn.commit()
    hb.detail["splits_applied"] = done
    return done


# --------------------------------------------------------------------------- bars in memory
def series(bars, field):
    return np.array([b[field] if b[field] is not None else np.nan for b in bars], dtype=float)


# --------------------------------------------------------------------------- nightly base rescan
def rescan_bases(conn, hb, bars, max_stop, limit_over):
    """§3.2: WAIT names are re-scanned nightly. The Saturday rank is calm; this is what makes a
    trigger real, and it is why the queue's prices are worth placing on Monday morning."""
    moved = 0
    with conn.cursor() as cur:
        cur.execute("select ticker, state, pivot from candidates")
        for tk, state, pivot in cur.fetchall():
            b = bars.get(tk)
            if not b or len(b) < 120:
                continue
            scan = sg.base_scan(series(b, "high"), series(b, "low"), series(b, "close"))
            stop = (sg.initial_stop(scan["pivot"], scan["contraction_low"], max_stop=max_stop)
                    if scan["valid"] else None)
            if scan["state"] != state or (scan["pivot"] or 0) != (float(pivot) if pivot else 0):
                moved += 1
            if not dry():
                cur.execute("""update candidates set state=%s, pivot=%s, base_len=%s,
                                 base_depth=%s, base_low=%s, stop_suggest=%s,
                                 last_close=%s where ticker=%s""",
                            (scan["state"], scan["pivot"], scan["base_len"], scan["depth"],
                             scan["contraction_low"], stop, float(b[-1]["close"]), tk))
                cur.execute("""update queue q set state=%s, trigger_price=%s, limit_price=%s,
                                 stop_suggest=%s,
                                 proximity = case when %s is null then null
                                             else abs(%s - %s)/nullif(%s,0) end
                               where q.ticker=%s and q.source='momentum'""",
                            (scan["state"], scan["pivot"],
                             scan["pivot"] * (1 + limit_over) if scan["pivot"] else None, stop,
                             scan["pivot"], float(b[-1]["close"]), scan["pivot"] or 0,
                             float(b[-1]["close"]), tk))
    conn.commit()
    hb.detail["bases_restated"] = moved
    return moved


# --------------------------------------------------------------------------- the book, nightly
def volume_baseline(bars, idx):
    """The 50 sessions *before* `idx` — the breakout day is the test, never its own baseline."""
    lo = max(0, idx - 50)
    window = [b["vol"] for b in bars[lo:idx] if b["vol"]]
    return float(np.mean(window)) if len(window) >= 25 else None


def classify_breakouts(conn, hb, bars, sessions, multiple):
    """§3.2 breakout confirmation. Entry is mechanical; volume decides how much money rides.

    Confirmed -> the pyramid arms. Unconfirmed -> it freezes at 50%, with three sessions from the
    breakout to confirm late, each measured against its own trailing 50-day. While unconfirmed one
    hair-trigger applies: a close back below the pivot exits next morning.
    """
    states = []
    with conn.cursor() as cur:
        cur.execute("""select id, ticker, opened_at, confirmed, confirm_deadline, pivot
                       from book where status='open' and sleeve='momentum'""")
        for bid, tk, opened, confirmed, deadline, pivot in cur.fetchall():
            b = bars.get(tk)
            if not b or confirmed is True or not opened:
                continue
            idx = next((i for i, bar in enumerate(b) if bar["d"] >= opened), None)
            if idx is None:
                continue
            window = b[idx:idx + sessions]
            # One state machine, shared with the backtest (§3.2). The hair-trigger arms when the
            # window closes, not while the name is still pending (ruled 2026-08-10) — which is the
            # timing `arm_exits` already used, now written down in one place instead of two.
            state = sg.confirmation_state([w["vol"] for w in window],
                                          [volume_baseline(b, idx + j) for j in range(len(window))],
                                          sessions=sessions, multiple=multiple)
            new_state = state["confirmed"]
            if not dry():
                cur.execute("""update book set confirmed=%s, confirm_deadline=%s, updated_at=now()
                               where id=%s""",
                            (new_state, b[min(idx + sessions - 1, len(b) - 1)]["d"], bid))
            states.append(dict(ticker=tk, confirmed=new_state,
                               sessions_seen=len(b) - idx, pivot=pivot))
    conn.commit()
    hb.detail["breakout_states"] = states
    return states


def ratchet(conn, hb, bars, buffer_pct):
    """Momentum trails only — compounders carry no stops, hurdle alerts only (§3.1)."""
    moves = []
    with conn.cursor() as cur:
        cur.execute("""select id, ticker, avg_cost, stop, highest_close, trail_mode, pyramid_step,
                              opened_at from book
                       where status='open' and sleeve='momentum'""")
        for bid, tk, cost, stop, hc, mode, step, opened in cur.fetchall():
            b = [x for x in bars.get(tk, []) if not opened or x["d"] >= opened]
            if not b:
                continue
            out = sg.ratchet_stop(closes=series(b, "close"),
                                  avg_cost=float(cost) if cost else None,
                                  current_stop=float(stop) if stop is not None else None,
                                  highest_close=float(hc) if hc is not None else None,
                                  pyramid_step=step or 0)
            if out["stop"] is None:
                continue
            new_stop, limit = float(out["stop"]), float(out["stop"]) * (1 - buffer_pct)
            changed = stop is None or new_stop > float(stop) + 1e-9
            if not dry():
                cur.execute("""update book set stop=%s, stop_limit=%s, highest_close=%s,
                                 trail_mode=%s, updated_at=now() where id=%s""",
                            (new_stop, limit, out["highest_close"], out["mode"], bid))
            if changed:
                moves.append(dict(ticker=tk, stop=round(new_stop, 2), limit=round(limit, 2),
                                  mode=out["mode"],
                                  was=round(float(stop), 2) if stop is not None else None,
                                  euphoric=out["euphoric"]))
    conn.commit()
    hb.detail["stop_moves"] = moves
    return moves


# --------------------------------------------------------------------------- the gates rulings open
#
# §3.3's data-confidence path caps an incompletely-scored name at the bottom of its size band and
# "requires manual sign-off". Until 2026-08-06 nothing in the system could ever grant that sign-off,
# so every growth-derived compounder — 13 of the 19 rows armed on the 6th — sat behind a gate with
# no key. Zak ruled it: **for a growth-derived name the blind C2 PASS ruling IS the §3.3 sign-off**;
# a name on the data-confidence route (2-of-3, or a statement currency we cannot resolve) still
# needs an explicit `signoff` ruling, logged after the filing it is being scored on.
#
# Both readings are the same sentence — the sign-off is a judgment, and judgments live in `rulings`.

CALENDAR_UNVERIFIED = "calendar unverified"


def signoff_gate(*, confidence, provenance, verdict_canon, decides, blind, signoff_current,
                 filing_date):
    """The §3.3 sign-off, read out of the rulings ledger. Returns a blocked_by string, or None.

    §3.3, as amended 2026-08-06: "the sign-off is a logged ruling … for a growth-derived name the
    blind C2 PASS ruling itself is the sign-off; for a name scored on 2 of 3 it is an explicit
    sign-off ruling by the session that writes or arms its ticket. The pipeline arms a flagged name
    unblocked only when its sign-off exists in `rulings`."

    Three states, and the plan gives each a different key:

      * `full` confidence — no sign-off is owed at all.
      * a growth-derived engine — §3.1 attaches §3.3's guardrails to the fallback, and the **blind**
        C2 PASS is what satisfies them. `blind` is load-bearing rather than decorative: §3.1's whole
        rulings law is that the business verdict is recorded before price, gap or CCN is revealed,
        and a verdict the number got to argue with is not the one §3.3 accepts as a guardrail
        waiver. Anything else — a FAIL, a quarantine, an escalation, silence — keeps it shut.
      * the data-confidence route (2-of-3, unresolved statement currency) — an explicit `signoff`
        ruling, dated on or after the filing date of the fundamentals row being scored. An older
        sign-off signed off on older numbers.
    """
    if confidence in ("full", None):
        return None
    if provenance == "growth-derived":
        if decides and verdict_canon == "pass" and blind:
            return None
        state = ("ruled " + (verdict_canon or "?") + ("" if blind else ", not blind")) \
            if verdict_canon else "never ruled"
        return ("§3.3 — growth-derived engine needs its manual sign-off, and for a growth-derived "
                "name the blind C2 PASS ruling IS that sign-off (§3.1, ruled 2026-08-06): "
                f"{state}")
    if signoff_current:
        return None
    since = f" dated on or after the filing {filing_date}" if filing_date else ""
    return (f"§3.3 — scored {confidence}: manual sign-off before sizing — no `signoff` ruling"
            f"{since}")


def calendar_unverified(last_report, *, stale_days):
    """§3.3 / WO-4: the blackout wall cannot enforce a date it never had (obs 114).

    Arcosa reported on 2026-08-05 and the calendar carried nothing, so the wall showed nothing and
    the nightly armed an entry straight through the print on the 6th and the 7th. A name whose
    latest *known* report date is older than a quarter has plausibly missed one, and absence of a
    date is not absence of an event — so it arms blocked rather than clean.
    """
    if last_report is None:
        return True
    return (dt.date.today() - last_report).days > stale_days


# --------------------------------------------------------------------------- arming
class Arm:
    """Collects the night's conclusions, then writes them as one overwrite set."""

    def __init__(self):
        self.rows = []

    def add(self, kind, ticker, reason, **kw):
        # urgency is NOT NULL in the schema and most callers do not pass it: protective is the
        # exception, normal is the rule, and the default belongs here rather than at every call.
        kw.setdefault("urgency", "normal")
        self.rows.append(dict(kind=kind, ticker=ticker, reason=reason, **kw))
        return self.rows[-1]

    def flush(self, conn, run_id):
        if dry():
            return len(self.rows)
        cols = ("run_id kind ticker sleeve account reason urgency order_type trigger_price "
                "limit_price stop stop_limit_price qty size_pct score blocked_by note detail "
                "currency fx_estimate risk_cad risk_pct_nav").split()
        with conn.cursor() as cur:
            # §4.3 legislates `armed` as an append ledger stamped with run ids. It used to be
            # truncated here, so the machine's own record of what it proposed lasted exactly one
            # night — which is why armed rows carrying scores the queue disagreed with (RS at 79.9
            # against a queue reading 69.7) could only be caught by looking on the right day.
            # Sessions read `v_armed_latest`; the history stays for the shadow book to mark.
            cur.executemany(
                f"insert into armed({','.join(cols)}) values ({','.join('%s' for _ in cols)})",
                [tuple([run_id] + [jsonb(r.get(c)) if c == "detail" else r.get(c)
                                   for c in cols[1:]]) for r in self.rows])
        conn.commit()
        return len(self.rows)


def exit_order(bars, ticker, *, inside, urgent):
    """How a sell ships (§4.5, ruled 2026-08-06): a **marketable limit**, unless it is urgent.

    "0.3% inside the last print, recomputed at placement — gap drills stay market-at-open." A
    marketable limit fills like a market order in any normal tape and refuses one bad print on a
    thin open; a market order accepts whatever the book offers. So the question per exit is only
    ever *how much does one more minute cost*.

    Urgent, and therefore market: a gap through the stop-limit (§4.6 names market-at-open in so
    many words), the market gate shutting (§3.3's crash protocol — the sleeve goes to cash), and
    the unconfirmed-breakout hair-trigger. Everything else is a conclusion drawn from a weekly
    ranking and acted on the next morning; a name that failed its trend template last Friday is
    not getting worse in the ninety seconds a limit costs.

    The price is computed from the last close so the ticket carries a number, and the note says to
    recompute at placement — which is what the ruling asks for and what Zak actually does.
    """
    if urgent:
        return dict(order_type="market", limit_price=None, note=None)
    b = bars.get(ticker) or []
    px = float(b[-1]["close"]) if b and b[-1]["close"] is not None else None
    if px is None:
        return dict(order_type="market", limit_price=None,
                    note="no last print to price a limit against — market")
    return dict(order_type="limit", limit_price=round(px * (1 - inside), 2),
                note=f"marketable limit — {inside:.1%} inside the last print {px:.2f}; "
                     f"recompute at placement (§4.5, ruled 2026-08-06)")


def arm_exits(conn, arm, bars, gate, breakouts, cushion, holidays, held=(), exit_inside=0.003):
    """Every exit §3.2 and §3.3 name, in the order they can fire.

    Protective conclusions carry urgency='protective' so a stale night cannot suppress them.
    """
    confirmed_by_ticker = {b["ticker"]: b for b in breakouts}
    with conn.cursor() as cur:
        cur.execute("""select b.id, b.ticker, b.account, b.sleeve, b.qty, b.avg_cost, b.stop,
                              b.stop_limit, b.pyramid_step, b.opened_at, b.confirmed,
                              b.pyramid_stalled_since, c.mcn, c.m2, b.pivot,
                              e.report_date, c.state, c.pivot as base_pivot, c.stop_suggest,
                              b.target_qty, b.pyramid_step
                       from book b
                       left join candidates c on c.ticker = b.ticker
                       left join lateral (select report_date from earnings
                                          where ticker=b.ticker and report_date >= current_date
                                          order by report_date limit 1) e on true
                       where b.status='open' and b.sleeve <> 'levered'""")
        for (bid, tk, acct, sleeve, qty, cost, stop, stop_limit, step, opened, confirmed,
             stalled, mcn, m2, pivot, report, base_state, base_pivot, base_stop, target,
             cur_step) in cur.fetchall():
            b = bars.get(tk)
            if not b:
                continue
            last, prev = b[-1], (b[-2] if len(b) > 1 else b[-1])
            px = float(last["close"])
            if tk in held:
                # §4.1: a quarantined print may not fire a sell. The position keeps its broker stop,
                # and the brief names the name — suspended, not silently traded on.
                arm.add("check", tk, "quarantine", sleeve=sleeve, account=acct,
                        urgency="protective", qty=float(qty),
                        note="print quarantined — two sources do not yet agree, so no exit is "
                             "armed tonight. The broker stop stands as placed (§4.1).",
                        detail=dict(close=px))
                continue
            common = dict(sleeve=sleeve, account=acct, qty=float(qty), score=float(mcn) if mcn else None)

            # ---- the stop fired. The broker GTC should have filled; a gap past the limit did not.
            if stop is not None and last["low"] is not None and float(last["low"]) <= float(stop):
                gapped = last["open"] is not None and float(last["open"]) < float(stop_limit or stop)
                arm.add("exit", tk, "gap" if gapped else "stop", urgency="protective",
                        order_type="market" if gapped else None, stop=float(stop),
                        note=("gapped below the stop-limit — the sell did not fill; if the "
                              "position is still in the account, market sell at open (§4.6)")
                        if gapped else "stop crossed — confirm the GTC filled",
                        detail=dict(low=float(last["low"]), open=last["open"],
                                    stop_limit=stop_limit), **common)
                continue

            # ---- market gate OFF: the momentum sleeve goes to cash (§3.3 crash protocol)
            if sleeve == "momentum" and gate == "OFF":
                arm.add("exit", tk, "gate_off", urgency="protective", order_type="market",
                        note="M1 is OFF — the momentum sleeve goes to cash", **common)
                continue

            if sleeve == "momentum":
                # ---- unconfirmed breakout, close back below the pivot (§3.2 hair-trigger)
                state = confirmed_by_ticker.get(tk, {})
                if confirmed is False or state.get("confirmed") is False:
                    if pivot and px < float(pivot):
                        arm.add("exit", tk, "unconfirmed", urgency="protective",
                                order_type="market",
                                note="unconfirmed breakout closed back below the pivot — "
                                     "a failed breakout by the only judge that matters",
                                detail=dict(pivot=float(pivot), close=px), **common)
                        continue

                # ---- relative exits (§3.2). Weekly numbers, acted on nightly.
                if m2 is False:
                    o = exit_order(bars, tk, inside=exit_inside, urgent=False)
                    arm.add("exit", tk, "template", order_type=o["order_type"],
                            limit_price=o["limit_price"],
                            note="trend template failed"
                                 + (f" · {o['note']}" if o["note"] else ""), **common)
                    continue
                if mcn is not None and float(mcn) < 55:
                    o = exit_order(bars, tk, inside=exit_inside, urgent=False)
                    arm.add("exit", tk, "score", order_type=o["order_type"],
                            limit_price=o["limit_price"],
                            note=f"MCN {float(mcn):.1f} — others got stronger, which is the "
                                 f"thesis decaying" + (f" · {o['note']}" if o["note"] else ""),
                            **common)
                    continue

                # ---- holding through a print needs a cushion (§3.3)
                if report and sg.trading_days_between(dt.date.today(), report,
                                                      holidays=holidays) <= 1:
                    if sg.holds_through_earnings(px, cost, cushion=cushion) is False:
                        o = exit_order(bars, tk, inside=exit_inside, urgent=False)
                        arm.add("exit", tk, "earnings", order_type=o["order_type"],
                                limit_price=o["limit_price"],
                                note=f"reports {report} without the {cushion:.2f}x cushion — "
                                     f"exit this evening, stops stay placed either way"
                                     + (f" · {o['note']}" if o["note"] else ""),
                                detail=dict(report=str(report), close=px,
                                            avg_cost=float(cost) if cost else None), **common)
                        continue

                # ---- a pyramid stalled below full size for 4 weeks resolves (§3.2)
                if stalled and (dt.date.today() - stalled).days >= 28 and (step or 0) < 3:
                    # §3.2: it "either completes on the next base or exits". A fresh valid base is
                    # the completion path, so offer that first and exit only when there is none.
                    if base_state == "BUY" and base_pivot:
                        remaining = (float(target) - float(qty)) if target else None
                        arm.add("add", tk, "stall", sleeve=sleeve, account=acct,
                                order_type="stop_limit", trigger_price=float(base_pivot),
                                limit_price=float(base_pivot) * 1.02, qty=remaining,
                                score=float(mcn) if mcn else None,
                                note="pyramid stalled four weeks — a new valid base completes it "
                                     "to full size rather than exiting (§3.2)")
                    else:
                        o = exit_order(bars, tk, inside=exit_inside, urgent=False)
                        arm.add("exit", tk, "stall", order_type=o["order_type"],
                                limit_price=o["limit_price"],
                                note="pyramid stalled below full size for 4 weeks and no new base "
                                     "— no permanent sub-scale positions"
                                     + (f" · {o['note']}" if o["note"] else ""), **common)


def arm_pyramid(conn, arm, bars, ceiling):
    """Steps 2 and 3 as resting add stop-limits, once the breakout confirms (§3.2)."""
    with conn.cursor() as cur:
        # the pivot is the one this position was entered on, stored on the book row. Reading it
        # from `queue` broke the moment a name left the queue or its base re-scanned to a new pivot.
        cur.execute("""select ticker, account, qty, avg_cost, pyramid_step, confirmed,
                              target_qty, pivot
                       from book
                       where status='open' and sleeve='momentum' and confirmed is true
                         and pyramid_step < 3 and pivot is not null""")
        for tk, acct, qty, cost, step, confirmed, target, pivot in cur.fetchall():
            if not pivot:
                continue
            for order in sg.pyramid_orders(float(pivot), ceiling=ceiling):
                if order["step"] <= (step or 1):
                    continue
                add_qty = (float(target) * order["fraction"]) if target else None
                arm.add("add", tk, "trigger", sleeve="momentum", account=acct,
                        order_type="stop_limit", trigger_price=order["trigger"],
                        limit_price=order["limit"], qty=add_qty,
                        note=f"pyramid step {order['step']} — {order['fraction']:.0%} of full size, "
                             f"limit at the schedule's ceiling",
                        detail=dict(step=order["step"], pivot=float(pivot)))


def arm_entries(conn, arm, bars, nav, fx, gate, caps, holidays):
    """Momentum triggers and compounder hurdles, with §2 and §3.3 checked before anything is
    offered. Nothing here writes a ticket — the session does, and assigns the theme."""
    blocked_note = None
    with conn.cursor() as cur:
        cur.execute("""select count(*) from book where status='open' and sleeve <> 'levered'""")
        positions = cur.fetchone()[0]
        cur.execute("""select sleeve, coalesce(sum(qty * p.close * case when b.currency='USD'
                              then %s else 1 end),0)
                       from book b join lateral (select close from prices where ticker=b.ticker
                                                 order by d desc limit 1) p on true
                       where b.status='open' group by sleeve""", (fx,))
        exposure = {r[0]: float(r[1]) for r in cur.fetchall()}
        cur.execute("""select ticker, coalesce(theme,'unassigned'), qty * p.close *
                              case when currency='USD' then %s else 1 end
                       from book b join lateral (select close from prices where ticker=b.ticker
                                                 order by d desc limit 1) p on true
                       where b.status='open'""", (fx,))
        theme_weight = {}
        for tk, theme, value in cur.fetchall():
            theme_weight[theme] = theme_weight.get(theme, 0.0) + (float(value) / nav if nav else 0)
        cur.execute("""select coalesce(u.industry,'unknown'), count(*) from book b
                       join universe u on u.ticker=b.ticker where b.status='open'
                       group by 1""")
        group_count = {r[0]: r[1] for r in cur.fetchall()}

        # A name the LEDGER has bought and not sold is a name we own, whatever the book says.
        #
        # The book is the book's opinion, and it is only as current as the last fill anyone told
        # it about. On 2026-08-04 Zak filled RS.US at 419.83; no ticket carried the fill, so the
        # book never saw it — and the next four briefs armed RS.US as a fresh momentum entry at
        # trigger 419.83, offering him a position he already held. `already_owned` is derived from
        # `transactions` instead, so a book that has fallen behind cannot manufacture an entry.
        # R1's runbook carries the session-side check; this is the job side refusing to arm it.
        cur.execute("""select ticker from transactions where superseded_by is null group by ticker
                        having sum(case when side='buy' then qty
                                        when side='sell' then -qty else 0 end) > 1e-6""")
        ledger_owned = {r[0] for r in cur.fetchall()}

        def already_owned(tk, sleeve, account=None):
            """True when the ledger holds it and the book does not — armed as a `check` so the
            discrepancy reaches the session rather than disappearing into a `continue`."""
            if tk not in ledger_owned:
                return False
            arm.add("check", tk, "already_owned", sleeve=sleeve, account=account,
                    note="the ledger holds this name and the book does not — a fill the book "
                         "never digested. No entry is armed for a position we own (§4.5); "
                         "reconcile the fill before anything is offered here.")
            return True

        # incumbents and their current scores, per sleeve — §3.3 displacement is within-sleeve only
        cur.execute("""select b.ticker, c.mcn from book b left join candidates c on c.ticker=b.ticker
                       where b.status='open' and b.sleeve='momentum'""")
        momentum_incumbents = [(r[0], r[1]) for r in cur.fetchall()]
        cur.execute("""select b.ticker, e.ccn from book b left join bench e on e.ticker=b.ticker
                       where b.status='open' and b.sleeve='compounders'""")
        compounder_incumbents = [(r[0], r[1]) for r in cur.fetchall()]

        # ---- momentum: a live trigger in BUY state, gate permitting
        if gate == "ON":
            cur.execute("""select q.ticker, q.trigger_price, q.limit_price, q.stop_suggest, q.mcn,
                                  u.industry, e.report_date, b.id, le.last_report
                           from queue q
                           join universe u on u.ticker=q.ticker
                           left join book b on b.ticker=q.ticker and b.status='open'
                           left join lateral (select report_date from earnings
                                              where ticker=q.ticker and report_date >= current_date
                                              order by report_date limit 1) e on true
                           left join lateral (select max(report_date) as last_report
                                                from earnings where ticker=q.ticker) le on true
                           where q.source='momentum' and q.state='BUY'
                             and q.trigger_price is not null
                           order by q.mcn desc nulls last""")
            for tk, trig, lim, stop, mcn, industry, report, held, last_report in cur.fetchall():
                if held or already_owned(tk, "momentum", "TFSA"):
                    continue
                # §3.2: "MCN < 70 never tickets — BUY-state names below 70 stay queued." Not a
                # blocked_by, which still prints a ticket the session must reason about: the row is
                # never armed at all. Production armed RS at 63.9 and four more below 70.
                if mcn is None or float(mcn) < caps["min_mcn"]:
                    continue
                trig = float(trig)
                stop = float(stop) if stop is not None else trig * (1 - caps["max_stop"])
                dist = max((trig - stop) / trig, 1e-4)
                size = sg.momentum_size(nav=nav, mcn_score=float(mcn) if mcn else None,
                                        stop_distance=min(dist, caps["max_stop"]),
                                        start_low=caps["start_low"])
                if not size:
                    continue
                room = caps["ceilings"]["momentum"] * nav - exposure.get("momentum", 0.0)
                score = float(mcn) if mcn is not None else None
                full_qty = int(size["cad"] / (trig * fx)) if size["cad"] and fx else None
                blocked, swap = None, None
                if size["size_pct"] > caps["single_cap"]:
                    blocked = f"§2.3 — {size['size_pct']:.0%} exceeds the {caps['single_cap']:.0%} single-name entry cap"
                elif size["below_floor"]:
                    blocked = (f"§2.3 — {size['size_pct']:.1%} is below the "
                               f"{caps['floor_pct']:.0%} minimum; too small to matter")
                elif positions >= caps["max_positions"] or (size["cad"] and size["cad"] > room):
                    # §3.3: the sleeve is full, so the challenger needs +10 over the weakest
                    # incumbent. If it clears, both legs are armed and Zak executes the swap.
                    swap = sg.displaceable(score, momentum_incumbents,
                                           margin=caps["displace_margin"])
                    if swap:
                        o = exit_order(bars, swap["ticker"], inside=caps["exit_inside"],
                                       urgent=False)
                        arm.add("exit", swap["ticker"], "swap", sleeve="momentum",
                                order_type=o["order_type"], limit_price=o["limit_price"],
                                score=swap["score"],
                                note=f"displaced by {tk} — {score:.1f} vs {swap['score']:.1f}, "
                                     f"+{swap['margin']:.1f} clears the §3.3 margin"
                                     + (f" · {o['note']}" if o["note"] else ""))
                    else:
                        full = (f"§2.1 — {positions} positions open"
                                if positions >= caps["max_positions"]
                                else "§2.1 — momentum sleeve has no room")
                        blocked = (f"{full}; no incumbent is "
                                   f"{caps['displace_margin']:.0f} points weaker (§3.3)")
                elif group_count.get(industry or "unknown", 0) >= caps["per_group"]:
                    blocked = f"§2.2 — already {caps['per_group']} names in {industry}"
                elif sg.in_blackout(dt.date.today(), report, holidays=holidays):
                    blocked = f"§3.3 — earnings blackout ({report})"
                elif calendar_unverified(last_report, stale_days=caps["calendar_stale_days"]):
                    blocked = CALENDAR_UNVERIFIED
                # §3.2: the first position is 50% of full size and pyramids to full. The ticket
                # buys half; `target_qty` on the resulting book row is what steps 2 and 3 size off.
                first = sg.entry_order(trig, stop, limit_over=caps["limit_over"],
                                       max_stop=caps["max_stop"])
                # §5.1: risk in C$ AND % of NAV, converted to CAD *before* the percentage. Dividing
                # a USD risk by a CAD NAV understates it by the whole FX rate — the trial printed
                # 0.16% where the truth was 0.24%.
                entry_qty = int(full_qty * first["fraction"]) if full_qty else None
                risk_cad = (entry_qty * (trig - stop) * fx) if entry_qty and fx else None
                arm.add("entry", tk, "trigger", sleeve="momentum", account="TFSA",
                        order_type="stop_limit", trigger_price=trig,
                        limit_price=float(lim) if lim else first["limit"], stop=stop,
                        stop_limit_price=stop * (1 - caps["buffer"]),
                        size_pct=size["size_pct"] * first["fraction"], score=score,
                        qty=entry_qty,
                        currency="USD", fx_estimate=fx, risk_cad=risk_cad,
                        risk_pct_nav=(risk_cad / nav) if risk_cad and nav else None,
                        blocked_by=blocked,
                        note=(f"MCN {score:.1f} · stop {dist:.1%} away · "
                              f"{first['fraction']:.0%} of a {size['size_pct']:.1%} full position"
                              + (f" · swap out {swap['ticker']}" if swap else "")
                              + (f" · latest known report {last_report or 'never'} — the blackout "
                                 f"wall cannot enforce a date it never had (§3.3, obs 114)"
                                 if blocked == CALENDAR_UNVERIFIED else ""))
                        if score is not None else None,
                        detail=dict(theme_weights=theme_weight, industry=industry,
                                    full_size_pct=size["size_pct"], target_qty=full_qty,
                                    pivot=trig, swap_out=swap["ticker"] if swap else None,
                                    last_known_report=str(last_report) if last_report else None))

        # ---- compounders: price at or below an approved bench name's hurdle
        # adds are counted from the ledger inside a rolling 12 months, never from a stored counter:
        # a counter that only increments quietly becomes a permanent block after two adds ever.
        # per-account investable cash — §2.6's "one position, one account, one order" needs to know
        # which account can fund a whole position before it names one. §2.0 says a ticket "is only
        # written if that account holds the cash", so this is the anchor carried forward by the
        # ledger, not the anchor alone: money the account spent on Tuesday is not available again
        # on Wednesday because Sunday has not been round yet.
        account_cash = {a: float(c["cad"]) + float(c["usd"]) * fx
                        for a, c in cash_by_account(cur).items() if c["kind"] != "facility"}

        # §3.1's rulings law, read the way the desk writes it. Verdicts are prose — `PASS`,
        # `QUARANTINE — owner-cash (§3.1) …` — so `v_rulings_latest_c2` canonicalises them and
        # resolves latest-wins (migration 034); this query used to ask for `verdict in
        # ('pass','fail')` and matched none of the sixty-eight rulings in the ledger.
        cur.execute("""select b.ticker, b.ccn, b.hurdle_price, b.last_close, b.gap_to_hurdle,
                              b.data_confidence, u.industry, e.report_date, k.id, k.qty,
                              k.avg_cost, b.engine_provenance, d.dps_ttm, k.entry_fill,
                              b.owner_fcf_suspect,
                              (select count(*) from transactions t
                                 where t.ticker = b.ticker and t.side='buy'
                                   and t.trade_date > current_date - interval '12 months'
                                   and t.trade_date > k.opened_at) as adds_12m,
                              k.account, r.verdict_canon, r.cooldown_until, r.decides,
                              r.ruling_id, r.blind,
                              -- §3.3's sign-off for the data-confidence route: a `signoff` ruling
                              -- logged on or after the filing whose numbers we are scoring.
                              -- Compared as UTC dates, explicitly: `timestamptz >= date` casts the
                              -- date at midnight in the SESSION timezone, and the store's tzdata is
                              -- a known limitation now — it still models the pre-2026 B.C. rule.
                              -- §4.7 makes every stamp UTC, so the comparison says UTC out loud.
                              (sg.at is not null
                               and (f.filing_date is null
                                    or (sg.at at time zone 'UTC')::date >= f.filing_date))
                                as signoff_now,
                              f.filing_date, le.last_report
                       from bench b
                       left join v_rulings_latest_c2 r on r.ticker = b.ticker
                       left join lateral (select max(r2.at) as at from rulings r2
                                           where r2.ticker = b.ticker and r2.kind = 'signoff'
                                             and not exists (select 1 from rulings x
                                                              where x.reverses = r2.id)) sg on true
                       left join v_fundamentals_latest f on f.ticker = b.ticker
                       join universe u on u.ticker=b.ticker
                       left join book k on k.ticker=b.ticker and k.status='open'
                       left join v_dividend_ttm d on d.ticker=b.ticker
                       left join lateral (select report_date from earnings
                                          where ticker=b.ticker and report_date >= current_date
                                          order by report_date limit 1) e on true
                       left join lateral (select max(report_date) as last_report
                                            from earnings where ticker=b.ticker) le on true
                       where b.approved and b.c1_pass and b.hurdle_price is not null
                         and b.last_close is not null and b.last_close <= b.hurdle_price
                       order by b.ccn desc""")
        for (tk, ccn_score, hurdle, px, gap, confidence, industry, report, held, hqty, hcost,
             provenance, dps_ttm, entry_fill, owner_suspect, adds, hacct,
             ruling, cooldown_until, decides, ruling_id, ruling_blind, signoff_now, filing_date,
             last_report) in cur.fetchall():
            ccn_score = float(ccn_score) if ccn_score is not None else None
            px, hurdle = float(px), float(hurdle)
            in_bo = sg.in_blackout(dt.date.today(), report, holidays=holidays)
            price_cad = px * fx if fx else px

            # §3.1 owner-cash quarantine (obs 97, ruling 66): "scored, ranked, watched, **never
            # ticketed**". Never means never — not blocked-but-printed, which is a row a session
            # still has to reason about, and not only for entries: an add is a ticket too. Ruling 66
            # quarantined DLO on 2026-08-06 and the nightly armed it as an entry the same night,
            # because the ledger read asked for a verdict vocabulary the desk does not use.
            if owner_suspect or (decides and ruling == "quarantine"):
                arm.add("check", tk, "owner_cash_quarantine", sleeve="compounders", account=hacct,
                        score=ccn_score,
                        note="§3.1 owner-cash quarantine — reported FCF is materially customer "
                             "float or credit-book funding. Scored, ranked, watched, never "
                             "ticketed: no entry and no add is armed until the balance-sheet "
                             "treatment prices it on cash the owners actually keep."
                             + (f" Latest c2 ruling {ruling_id}." if ruling_id else ""),
                        detail=dict(ruling_id=ruling_id, verdict=ruling,
                                    owner_fcf_suspect=bool(owner_suspect)))
                continue
            # §3.1 marks growth-derived engines on every memo and ticket that cites them; the flag
            # rides on the armed row so no session has to remember, or free-text it wrong.
            engine_note = ("engine growth-derived (observed 3-yr revenue growth, capped) — measured "
                           "engine failed the ±5pp cross-check; §3.3 guardrails apply"
                           if provenance == "growth-derived" else None)
            if held:
                add = sg.compounder_add(ccn_score=ccn_score, price=px, hurdle=hurdle,
                                        entry_fill=float(entry_fill) if entry_fill else None,
                                        adds_this_year=adds or 0, max_adds=caps["max_adds"])
                if not add:
                    continue
                # §3.3's blackout covers "no new entries and no adds", so the calendar guard covers
                # adds too — an add through an unseen print is the same mistake in a smaller size.
                blocked = (add["blocked"] or ("§3.3 — earnings blackout" if in_bo else None)
                           or (CALENDAR_UNVERIFIED
                               if calendar_unverified(last_report,
                                                      stale_days=caps["calendar_stale_days"])
                               else None))
                add_pct = caps["flat"] * (add["fraction"] or 0)
                arm.add("add", tk, "hurdle", sleeve="compounders", account=hacct,
                        order_type="limit", limit_price=px, score=ccn_score,
                        size_pct=add_pct,
                        qty=int(add_pct * nav / price_cad) if nav and price_cad else None,
                        blocked_by=blocked,
                        note=f"{add['below']:.0%} below the entry fill — §3.1 adds "
                             f"{(add['fraction'] or 0):.0%} of original size"
                             + (f" · {engine_note}" if engine_note else ""),
                        detail=dict(entry_fill=float(entry_fill) if entry_fill else None,
                                    engine_provenance=provenance,
                                    last_known_report=str(last_report) if last_report else None))
                continue
            if already_owned(tk, "compounders", hacct):
                # not held by the book, so the add path above never ran — and an entry for a name
                # the ledger owns would be a second full position, not an add
                continue
            size_pct = caps["flat"]
            room = caps["ceilings"]["compounders"] * nav - exposure.get("compounders", 0.0)
            blocked, swap = None, None
            # §3.3's thresholds, which this path had never read: **55–69 is the hold zone — no new
            # money** — and §3.1 gives no size band below 70 at all, so a sub-70 entry has no
            # legislated size to be written at. Momentum enforces the same line (`min_mcn`) and so
            # does the compounder ADD path (`compounder_add(enter=70)`); only the entry escaped,
            # and it escaped invisibly because until 2026-08-07 every one of these rows was already
            # blocked by a sign-off gate nothing could open. The night the gate opened, LMAT armed
            # offerable at CCN 69.2.
            if ccn_score is not None and ccn_score < caps["min_ccn"]:
                blocked = (f"§3.3 — CCN {ccn_score:.1f} is in the hold zone (55–69): no new money. "
                           f"Enterable starts at {caps['min_ccn']:.0f}")
            elif size_pct > caps["single_cap"]:
                blocked = f"§2.3 — exceeds the {caps['single_cap']:.0%} single-name entry cap"
            elif size_pct < caps["floor_pct"]:
                blocked = f"§2.3 — below the {caps['floor_pct']:.0%} minimum position"
            elif positions >= caps["max_positions"] or size_pct * nav > room:
                swap = sg.displaceable(ccn_score, compounder_incumbents,
                                       margin=caps["displace_margin"])
                if swap:
                    o = exit_order(bars, swap["ticker"], inside=caps["exit_inside"], urgent=False)
                    arm.add("exit", swap["ticker"], "swap", sleeve="compounders",
                            order_type=o["order_type"], limit_price=o["limit_price"],
                            score=swap["score"],
                            note=f"displaced by {tk} — CCN {ccn_score:.1f} vs "
                                 f"{swap['score']:.1f}, +{swap['margin']:.1f} clears §3.3"
                                 + (f" · {o['note']}" if o["note"] else ""))
                else:
                    full = (f"§2.1 — {positions} positions open"
                            if positions >= caps["max_positions"]
                            else "§2.1 — compounder sleeve has no room")
                    blocked = (f"{full}; no incumbent is "
                               f"{caps['displace_margin']:.0f} points weaker (§3.3)")
            elif group_count.get(industry or "unknown", 0) >= caps["per_group"]:
                blocked = f"§2.2 — already {caps['per_group']} names in {industry}"
            elif in_bo:
                blocked = f"§3.3 — earnings blackout ({report})"
            elif calendar_unverified(last_report, stale_days=caps["calendar_stale_days"]):
                blocked = CALENDAR_UNVERIFIED
            else:
                # §3.3's sign-off, now a gate the ledger can actually open (WO-1, ruled 2026-08-06)
                blocked = signoff_gate(confidence=confidence, provenance=provenance,
                                       verdict_canon=ruling, decides=decides,
                                       blind=bool(ruling_blind),
                                       signoff_current=bool(signoff_now), filing_date=filing_date)
            # §4.3: jobs read the rulings ledger — only ruled names ship entry tickets. A live
            # FAIL blocks outright (the 12-month cooldown, §3.1); a name never ruled still arms,
            # flagged, because §3.1's law is that the NEXT SESSION rules it blind before its GTC
            # is placed — a row the session cannot see is a ruling that never happens. An
            # ESCALATE is a question for Zak (§5.6), so it leaves the name unruled too.
            unruled = ruling_id is None or not decides
            if decides and ruling == "fail" and not blocked:
                until = f" until {cooldown_until}" if cooldown_until else ""
                blocked = (f"§3.1 — ruled FAIL, 12-month cooldown{until} "
                           f"(escape: new filing + CCN at rejection +10)")

            # §3.1 sizing: whole shares that CEIL into the band — flooring lands the position below
            # its own target weight, which is outside the 12-15 band the plan sets.
            qty = sg.whole_shares(target_pct=size_pct, nav=nav, price_cad=price_cad,
                                  band=caps["band"]) if nav and price_cad else None
            cost_cad = qty * price_cad if qty else None

            # §2.6 placement. Momentum owns the TFSA outright and compounders take everything else,
            # so the TFSA is the default home; a US name yielding >= 1% trailing prefers the RRSP,
            # where US dividend withholding is treaty-exempt instead of leaking 15%. Then
            # "one position, one account, one order": the first account in preference order whose
            # cash funds the WHOLE position gets it. Never split, never assume a top-up — the trial
            # routed C$24,698 at RRSP holding C$22,747 and simply asserted the difference.
            yield_ttm = (float(dps_ttm) / px) if dps_ttm and px else None
            prefers_rrsp = yield_ttm is not None and yield_ttm >= caps["rrsp_yield"]
            order = ["RRSP", "TFSA"] if prefers_rrsp else ["TFSA", "RRSP"]
            account = next((a for a in order if cost_cad and account_cash.get(a, 0) >= cost_cad),
                           None)
            if account is None and not blocked:
                short = ", ".join(f"{a} C${account_cash.get(a, 0):,.0f}" for a in order)
                blocked = (f"§2.6 — no account can fund the whole C${cost_cad or 0:,.0f} position "
                           f"({short}); one position, one account, one order")

            arm.add("entry", tk, "hurdle", sleeve="compounders", account=account or order[0],
                    # §3.1: a GTC buy LIMIT at the hurdle. It fills anywhere at or below, waits
                    # above, and is cancelled and replaced only when a filing moves the hurdle —
                    # never on a quote move. A day limit could miss while the name sat below.
                    order_type="gtc_limit", limit_price=hurdle, score=ccn_score, size_pct=size_pct,
                    qty=qty, blocked_by=blocked,
                    # compounders carry no stop (§3.1), so there is no stop-distance risk to print;
                    # the currency and the FX the share count was struck at still belong on the row
                    currency=("CAD" if tk.endswith(".TO") else "USD"), fx_estimate=fx,
                    note=(f"CCN {ccn_score:.1f} · GTC limit at the hurdle {hurdle:.2f} · "
                          f"{abs(gap or 0):.0%} below"
                          + (" · ESCALATED — awaiting Zak, not a ruling Yuna may make (§5.6)"
                             if ruling_id and not decides else
                             " · UNRULED — rule blind before the GTC ships (§3.1)" if unruled else
                             f" · c2 {(ruling or '').upper()} · ruling {ruling_id}")
                          + (f" · swap out {swap['ticker']}" if swap else "")
                          + (f" · {engine_note}" if engine_note else "")
                          + (f" · latest known report {last_report or 'never'} — the blackout wall "
                             f"cannot enforce a date it never had (§3.3, obs 114)"
                             if blocked == CALENDAR_UNVERIFIED else ""))
                    if ccn_score else None,
                    detail=dict(theme_weights=theme_weight, industry=industry,
                                needs_ruling=unruled,
                                # the ruling that opened (or held) §3.3's sign-off, cited on the row
                                # so a session never has to go looking for it — §5.6's one read
                                ruling_id=ruling_id, verdict=ruling, ruling_decides=decides,
                                ruling_blind=ruling_blind,
                                signoff_current=bool(signoff_now),
                                fundamentals_filing_date=str(filing_date) if filing_date else None,
                                last_known_report=str(last_report) if last_report else None,
                                swap_out=swap["ticker"] if swap else None,
                                engine_provenance=provenance,
                                dividend_yield_ttm=yield_ttm, prefers_rrsp=prefers_rrsp,
                                account_cash={a: account_cash.get(a) for a in order},
                                cost_cad=cost_cad, fx=fx))
    return blocked_note


def arm_housekeeping(conn, arm, holidays):
    """Blackout cancels live entry and add orders at the broker; protective stops always stay
    (§3.3). Compounder invalidators and sub-55 CCNs are flagged for judgment, never auto-sold."""
    with conn.cursor() as cur:
        cur.execute("""select k.id, k.ticker, k.action, k.trigger_price, e.report_date
                       from tickets k
                       join lateral (select report_date from earnings
                                     where ticker=k.ticker and report_date >= current_date
                                     order by report_date limit 1) e on true
                       where k.state in ('proposed','approved') and k.action in ('buy','add')""")
        for kid, tk, action, trig, report in cur.fetchall():
            if sg.in_blackout(dt.date.today(), report, holidays=holidays):
                arm.add("cancel", tk, "blackout", urgency="protective",
                        note=f"reports {report} — cancel the live {action} order at the broker; "
                             f"protective stops remain, always",
                        detail=dict(ticket_id=kid, trigger=float(trig) if trig else None))

        cur.execute("""select b.ticker, b.invalidators, b.thesis, b.sleeve, e.ccn
                       from book b
                       left join bench e on e.ticker=b.ticker
                       where b.status='open' and b.sleeve='compounders'""")
        for tk, invalidators, thesis, sleeve, ccn_score in cur.fetchall():
            if ccn_score is not None and float(ccn_score) < 55:
                arm.add("check", tk, "score", sleeve=sleeve, score=float(ccn_score),
                        note="CCN below 55 — §3.1 wants a review memo within 48h: raw-vs-snapshot, "
                             "invalidator check, recommendation. Never an auto-sell.")
            if invalidators:
                arm.add("check", tk, "invalidator", sleeve=sleeve,
                        note="daily invalidator read", detail=dict(invalidators=invalidators))


# --------------------------------------------------------------------------- the levered pool (§2.5)
#
# Ruled 2026-08-06 and law since the 08-07 plan: **drawn levered capital is never idle — its
# resting state is the ETF.** In one sentence: borrowed dollars buy the qualified name when it is
# trading behind the market, and hand it back to the ETF when it has run well ahead of it.
#
# The lag and lead thresholds are Zak's and he has not set them, so §2.5 is explicit about what
# happens until he does: "the brief carries a levered status line (utilization per facility,
# headroom, holdings) and **proposes nothing**." That is the whole shape of this function — the
# arithmetic is built and standing, and `config.levered_cycle_params` is the only thing between it
# and a proposal. A missing key is not a missing feature; it is a ruling that has not been made.

LEVERED_WINDOW = 126        # sessions — §2.2's correlation window, and §2.5's relative-value window


def relative_return(bars, ticker, *, index="GSPC.INDX", window=LEVERED_WINDOW):
    """(name, index, lead in percentage points) over `window` sessions, or None.

    §4.1 pins the input: signal and return computations run on **adjusted** closes. A dividend or a
    split inside the window would otherwise read as a lag the business never had — and a lag is the
    thing this number exists to measure.
    """
    a, b = bars.get(ticker) or [], bars.get(index) or []
    if len(a) < window + 1 or len(b) < window + 1:
        return None

    def leg(rows):
        first, last = rows[-(window + 1)]["adj"], rows[-1]["adj"]
        return (float(last) / float(first) - 1.0) if first and float(first) > 0 else None

    ra, rb = leg(a), leg(b)
    if ra is None or rb is None:
        return None
    return dict(ret=round(ra, 4), index_ret=round(rb, 4),
                lead_pp=round(100.0 * (ra - rb), 1), window=window)


def levered_status(conn, bars, fx, nav, *, window=LEVERED_WINDOW):
    """§2.5's levered pool, as numbers: utilization per facility, headroom, holdings, and how far
    each name has run against the index.

    Headroom is measured to the **utilization cap**, not to the credit limit, because the cap is
    what §2.5 actually permits: callable facilities stop at 50% and the HELOC runs to the full line
    ("it isn't callable, and a readvanceable mortgage grows by design"). Reporting the limit as
    headroom would print C$67K of room on a facility that may only draw C$29K more.

    Qualification is the bar §2.5 already sets and nothing new: a **blind** C2 PASS, CCN ≥ 85,
    at or below its hurdle — plus a facility whose `funds` permits single names, which is a property
    of the money rather than of the name and is reported per facility. The lag test is the only part
    that needs Zak's numbers.
    """
    with conn.cursor() as cur:
        params = config(cur, "levered_cycle_params", None)
        etf = config(cur, "levered_etf", None)
        if isinstance(etf, str):
            etf = etf.strip('"') or None
        thresholds = config(cur, "score_thresholds", {}) or {}
        # the config row spells this `full`; `full_conviction` is read too so a rename cannot
        # silently fall back to the default and look like it worked (learnings #21)
        full = float(thresholds.get("full", thresholds.get("full_conviction", 85)))
        balances = cash_by_account(cur)
        cur.execute("""select code, label, callable, max_utilization, funds
                         from accounts where kind = 'facility' order by code""")
        register = cur.fetchall()

        facilities = []
        for code, label, callable_, max_util, funds in register:
            b = balances.get(code, {})
            drawn = float(b.get("drawn") or 0.0)
            limit = float(b.get("limit") or 0.0)
            # §2.5: "Callable margin 50% · Secured LOC 50% · HELOC full". A null max_utilization is
            # the HELOC's "full", not an absent rule.
            cap_frac = float(max_util) if max_util is not None else 1.0
            cap_amount = limit * cap_frac
            facilities.append(dict(
                code=code, label=label, callable=bool(callable_), funds=funds,
                drawn=round(drawn, 2), limit=round(limit, 2),
                max_utilization=float(max_util) if max_util is not None else None,
                utilization=round(drawn / limit, 4) if limit > 0 else None,
                cap_amount=round(cap_amount, 2),
                headroom=round(cap_amount - drawn, 2),
                over_cap=bool(limit > 0 and drawn > cap_amount + 1e-9),
                as_of=str(b.get("as_of")) if b.get("as_of") else None))

        cur.execute("""select b.ticker, b.account, b.qty, b.currency, p.close, e.ccn,
                              r.verdict_canon, r.decides
                         from book b
                         join lateral (select close from prices where ticker = b.ticker
                                        order by d desc limit 1) p on true
                         left join bench e on e.ticker = b.ticker
                         left join v_rulings_latest_c2 r on r.ticker = b.ticker
                        where b.status = 'open' and b.sleeve = 'levered'
                        order by b.ticker""")
        held = cur.fetchall()

        # §2.5's bar for a single name taking the pool, minus the lag test that needs Zak's numbers
        cur.execute("""select b.ticker, b.ccn, b.hurdle_price, b.last_close, b.gap_to_hurdle
                         from bench b
                         join v_rulings_latest_c2 r on r.ticker = b.ticker
                        where r.decides and r.verdict_canon = 'pass' and r.blind
                          and b.ccn >= %s and b.approved and b.c1_pass
                          and b.hurdle_price is not null and b.last_close is not null
                          and b.last_close <= b.hurdle_price
                          and not b.owner_fcf_suspect
                        order by b.ccn desc""", (full,))
        qualified_rows = cur.fetchall()

    holdings, disqualified = [], []
    for tk, acct, qty, ccy, close, ccn, verdict, decides in held:
        value = float(qty) * float(close) * (fx if ccy == "USD" else 1.0)
        holdings.append(dict(ticker=tk, account=acct, qty=float(qty),
                             value_cad=round(value, 2),
                             weight_nav=round(value / nav, 4) if nav else None,
                             is_etf=(tk == etf), ccn=float(ccn) if ccn is not None else None,
                             relative=relative_return(bars, tk, window=window)))
        # §2.5: a single name "reverts when it runs well ahead, **or stops qualifying** (CCN < 70 at
        # a filing recompute, or an exit ruling) — the score-break revert applies regardless of
        # relative position". Stating the disqualification is not proposing anything, so it is said
        # out loud even while the cycle is locked.
        if tk != etf:
            why = None
            if ccn is not None and float(ccn) < float(thresholds.get("enter",
                                                                     thresholds.get("enterable", 70))):
                why = f"CCN {float(ccn):.1f} — below the §2.5 qualifying floor"
            elif decides and verdict in ("fail", "exit", "quarantine"):
                why = f"latest c2 ruling is {str(verdict).upper()}"
            if why:
                disqualified.append(dict(ticker=tk, why=why))

    qualified = [dict(ticker=t, ccn=float(c), hurdle_price=float(h), last_close=float(p),
                      gap_to_hurdle=float(g) if g is not None else None,
                      relative=relative_return(bars, t, window=window))
                 for t, c, h, p, g in qualified_rows]

    single_name_facilities = [f["code"] for f in facilities
                              if f["funds"] == "single_or_etf" and (f["headroom"] or 0) > 0]

    status = dict(
        etf=dict(ticker=etf, priced=bool(etf and bars.get(etf)),
                 relative=relative_return(bars, etf, window=window) if etf else None),
        facilities=facilities, holdings=holdings, qualified=qualified,
        disqualified=disqualified, single_name_facilities=single_name_facilities,
        window=window, params=params, proposals=[],
        breaches=[f["code"] for f in facilities if f["over_cap"]])

    if not params:
        status["note"] = ("§2.5 — cycle thresholds unset (`config.levered_cycle_params`): status "
                          "only, no proposals. Zak's ruling sets lag to enter, lead to revert, "
                          "and the window.")
        return status

    # ---- the cycle, once Zak has ruled. Both legs are proposals; he places them (§2.5, §4.5).
    lag = float(params.get("enter_lag_pp", 0) or 0)
    lead = float(params.get("revert_lead_pp", 0) or 0)
    status["note"] = (f"§2.5 cycle armed — enter on a lag of {lag:g}pp, revert on a lead of "
                      f"{lead:g}pp, over {window} sessions.")
    for h in holdings:
        if h["is_etf"] or not h["relative"]:
            continue
        broke = next((d["why"] for d in disqualified if d["ticker"] == h["ticker"]), None)
        if broke:
            status["proposals"].append(dict(kind="revert", ticker=h["ticker"], to=etf,
                                            reason="score break", detail=broke))
        elif h["relative"]["lead_pp"] >= lead:
            status["proposals"].append(dict(
                kind="revert", ticker=h["ticker"], to=etf, reason="ran ahead",
                detail=f"{h['relative']['lead_pp']:+.1f}pp vs the index over {window} sessions"))
    if not any(p["kind"] == "revert" for p in status["proposals"]):
        for q in qualified:
            if q["relative"] and q["relative"]["lead_pp"] <= -lag and single_name_facilities:
                status["proposals"].append(dict(
                    kind="enter", ticker=q["ticker"], from_=etf, reason="lagging the index",
                    facilities=single_name_facilities,
                    detail=f"CCN {q['ccn']:.1f} · at/below hurdle · "
                           f"{q['relative']['lead_pp']:+.1f}pp vs the index over {window} sessions"))
                break
    return status


# --------------------------------------------------------------------------- shadow book (§3.3)
def shadow_book(conn, hb, bars):
    """Every pass and every exit, snapshotted and marked at 30 / 60 / 90 days (§3.3).

    This is the only forward validation the compounder side will ever have — §4.8 says the backtest
    there is indicative-only, and the shadow book is what converts a formula from "a reasoned prior"
    into evidence. It costs nothing to record and cannot be reconstructed later, so it records
    everything the machine declined as well as everything it left.

    A pass is a name the machine armed and a rule held back; an exit is a position it let go. Both
    carry the score and the price at the moment of the decision.
    """
    written, marked = 0, 0
    with conn.cursor() as cur:
        # tonight's arming only — `armed` is a ledger now (§4.3), so an unqualified read would
        # re-mark every pass the machine has ever made, every night.
        cur.execute("""select kind, ticker, reason, score, blocked_by, note from armed
                       where kind in ('entry', 'exit') and run_id = %s""", (hb.id,))
        for kind, tk, reason, score, blocked, note in cur.fetchall():
            b = bars.get(tk)
            price = float(b[-1]["close"]) if b and b[-1]["close"] is not None else None
            if kind == "entry" and not blocked:
                continue                      # taken, not passed — the book will carry it
            shadow_kind = "pass" if kind == "entry" else "exit"
            body = (f"{shadow_kind}: {tk} at {price} — {blocked or reason}")
            if dry():
                continue
            # one row per name per day per kind: the nightly job re-arms the same conclusion every
            # night a rule keeps holding, and 60 identical rows would drown the marks
            cur.execute("""select 1 from observations where kind=%s and ticker=%s
                           and at::date = current_date limit 1""", (shadow_kind, tk))
            if cur.fetchone():
                continue
            observe(cur, shadow_kind, body, ticker=tk, score=score, price=price,
                    detail=dict(reason=reason, blocked_by=blocked, note=note))
            written += 1

        # the marks: 30, 60 and 90 sessions later, what did the decision turn out to be worth?
        for horizon, column in ((30, "mark_30"), (60, "mark_60"), (90, "mark_90")):
            cur.execute(f"""select o.id, o.ticker, o.at::date from observations o
                            where o.kind in ('pass','exit') and o.{column} is null
                              and o.at < now() - make_interval(days => %s)""", (horizon,))
            for oid, tk, at in cur.fetchall():
                cur.execute("""select close from prices where ticker=%s and d >= %s
                               order by d limit 1""", (tk, at + dt.timedelta(days=horizon)))
                row = cur.fetchone()
                if not row or dry():
                    continue
                cur.execute(f"update observations set {column}=%s, marked_at=now() where id=%s",
                            (float(row[0]), oid))
                marked += 1
    conn.commit()
    hb.detail.update(shadow_written=written, shadow_marked=marked)
    return written, marked


# --------------------------------------------------------------------------- marks, NAV, brief
def refresh_marks(conn, hb):
    with conn.cursor() as cur:
        if not dry():
            cur.execute("""update bench b set last_close = p.close,
                             gap_to_hurdle = case when b.hurdle_price is null or b.hurdle_price=0
                                                  then null
                                             else (p.close - b.hurdle_price)/b.hurdle_price end
                           from (select distinct on (ticker) ticker, close from prices
                                 order by ticker, d desc) p
                           where p.ticker = b.ticker""")
        cur.execute("select count(*) from bench where gap_to_hurdle <= 0 and approved")
        approved = cur.fetchone()[0]
        cur.execute("select count(*) from bench where gap_to_hurdle <= 0")
        any_hurdle = cur.fetchone()[0]
    conn.commit()
    hb.detail["bench_at_hurdle"] = dict(approved=approved, total=any_hurdle)
    return approved, any_hurdle


def book_effective_bets(conn, bars, fx):
    with conn.cursor() as cur:
        cur.execute("""select b.ticker, b.qty * p.close * case when b.currency='USD' then %s
                              else 1 end
                       from book b join lateral (select close from prices where ticker=b.ticker
                                                 order by d desc limit 1) p on true
                       where b.status='open'""", (fx,))
        weights = {t: float(v) for t, v in cur.fetchall() if v}
    returns = {}
    for tk in weights:
        b = bars.get(tk, [])
        adj = series(b, "adj")[-127:]
        if len(adj) >= 61:
            returns[tk] = np.diff(np.log(adj))
    return sg.effective_bets(weights, returns)


def apply_ledger(conn, hb):
    """Fills, then splits — everything that changes what the book *is*, before anything derives
    from it.

    §4.2 orders the night "ingest → score", and inside `score` the same logic applies one level
    down: a queue built before tonight's fills are folded in describes a book that no longer
    exists. That is how VRT — closed on the 5th — kept a HOLD seat while NUE and RS, filled the
    same week, had none (obs 116). `score` calls this first; every pass here is idempotent by
    design, so `run()` calling it again below is a no-op and a direct caller still gets a complete
    job.
    """
    sync_fills_from_tickets(conn, hb)
    apply_fills(conn, hb)
    rebase_for_splits(conn, hb)
    if not dry():
        with conn.cursor() as cur:
            # §3.0: "membership lists never drop a name the book owns." `universe.is_holding` is
            # that membership list for score, ingest and the census, and nothing was maintaining
            # it — so it still said VRT and had never heard of NUE or RS. Derived from the book,
            # it cannot drift from it.
            cur.execute("""update universe u
                              set is_holding = exists (select 1 from book b
                                                        where b.ticker = u.ticker
                                                          and b.status = 'open' and b.qty > 0)
                            where u.kind = 'stock'
                              and u.is_holding <> exists (select 1 from book b
                                                           where b.ticker = u.ticker
                                                             and b.status='open' and b.qty > 0)""")
            changed = cur.rowcount
        conn.commit()
        if changed:
            hb.detail["is_holding_resynced"] = changed
    return True


def run(conn, hb, *, held=frozenset(), apply_ledger_first=True):
    """Everything `score` derives about the book and the night's conclusions.

    Fills applied -> bases re-scanned -> breakouts classified -> stops ratcheted -> the book
    revalued against the latest bars -> NAV -> exits, adds and entries armed -> shadow book.

    It writes no tickets. §2.2 and §4.3 both say jobs arm and only sessions write tickets,
    because a ticket carries a theme and a theme is judgment. So every conclusion lands in
    `armed`, priced and cap-checked, and R1/R2 turn those into tickets. Protective conclusions
    are marked urgency 'protective': they survive a stale-data night, and nothing else does.

    `held` is the quarantine set `ingest` resolved tonight (§4.1) — prints no second source
    would confirm, which must not drive a sell.
    """
    with conn.cursor() as cur:
        caps = dict(
            buffer=float(config(cur, "stop_limit_buffer", 0.03)),
            max_stop=float(config(cur, "momentum_max_stop", 0.08)),
            flat=float(config(cur, "ccn_flat_size", 0.12)),
            per_group=int(config(cur, "max_names_per_group", 2)),
            single_cap=float(config(cur, "single_name_entry_cap", 0.25)),
            floor_pct=float(config(cur, "position_floor_nav", 0.04)),
            displace_margin=float((config(cur, "score_thresholds", {}) or {})
                                  .get("displace_margin", 10)),
            # §2.2's theme entry cap is deliberately NOT read here. A theme is judgment
            # assigned when a ticket is written (§2.2), so the job cannot know a new name's
            # theme — it ships the current theme weights on every armed row and R1 enforces
            # the 35% cap. Reading the config here would look like enforcement and be none.
            max_adds=int(config(cur, "max_adds_per_year", 2)),
            # §3.2 / §3.3: names under the enterable threshold stay queued and never ticket. The
            # stored row spells this key `enter`; the code asked only for `enterable` and fell
            # through to the same 70 by luck, so the config row was decorative — learnings #21,
            # from the other side. One threshold, read once, applied to both sleeves.
            min_mcn=float((lambda t: t.get("enter", t.get("enterable", 70)))(
                config(cur, "score_thresholds", {}) or {})),
            min_ccn=float((lambda t: t.get("enter", t.get("enterable", 70)))(
                config(cur, "score_thresholds", {}) or {})),
            # §2.6: a US compounder with a trailing-12-month yield at or above this prefers
            # the RRSP — US dividend withholding is treaty-exempt there and leaks 15% in the
            # TFSA. Below it, placement follows the TFSA-first default.
            rrsp_yield=float(config(cur, "rrsp_yield_preference", 0.01)),
            band=tuple(config(cur, "compounder_band", [0.12, 0.15])),
            ceilings=config(cur, "sleeve_ceiling", {"compounders": 0.6, "momentum": 0.4}),
            max_positions=int((config(cur, "max_positions", {"max": 9}) or {}).get("max", 9)),
            limit_over=float(config(cur, "entry_limit_over_pivot", 0.02)),
            ceiling=float(config(cur, "pyramid_ceiling", 1.05)),
            confirm_mult=float(config(cur, "confirmation_volume", 1.4)),
            confirm_sessions=int(config(cur, "confirmation_sessions", 3)),
            cushion=float(config(cur, "holdthrough_cushion", 1.08)),
            warn_bets=float(config(cur, "effective_bets_warn", 4)),
            # §3.3 / WO-4: a name whose newest KNOWN report date is older than a quarter has
            # plausibly missed one, so the blackout wall cannot vouch for it (obs 114).
            calendar_stale_days=int(config(cur, "earnings_calendar_stale_days", 110)),
            # §4.5 (ruled 2026-08-06): a non-urgent exit ships as a marketable limit this far
            # inside the last print. Gap drills stay market-at-open (§4.6).
            exit_inside=float(config(cur, "exit_limit_inside", 0.003)),
        )
        cur.execute("select state from gate_state order by id desc limit 1")
        gate = (cur.fetchone() or ["OFF"])[0]
        cur.execute("""select min(trade_date) from transactions t join tickets k
                         on k.id=t.ticket_id where k.sleeve='momentum' and t.side='buy'""")
        first_fill = cur.fetchone()[0]
    caps["start_low"] = not first_fill or (dt.date.today() - first_fill).days <= 90

    if apply_ledger_first:
        apply_ledger(conn, hb)

    with conn.cursor() as cur:
        cur.execute("""select ticker from universe
                       where is_holding or ticker in (select ticker from queue)
                          or ticker in (select ticker from candidates)
                          or ticker in (select ticker from bench)
                          or ticker in (select ticker from book where status='open')
                          -- §2.5's levered pool is measured AGAINST the index, and its resting
                          -- state is an ETF that is in no membership list — both need bars
                          or ticker = 'GSPC.INDX'
                          or ticker = trim(both '\"' from (
                               select value::text from config where key='levered_etf'
                                order by set_at desc limit 1))""")
        watched = [r[0] for r in cur.fetchall()]
        bars = load_bars(cur, watched)

    rescan_bases(conn, hb, bars, caps["max_stop"], caps["limit_over"])
    breakouts = classify_breakouts(conn, hb, bars, caps["confirm_sessions"],
                                   caps["confirm_mult"])
    moves = ratchet(conn, hb, bars, caps["buffer"])

    with conn.cursor() as cur:
        n = nav_cad(cur)
        # §4.2: the book is revalued from the night's bars, and "every holding's valuation
        # price must equal its latest bar; any mismatch fails the run". Red, not amber —
        # a wrong NAV is not a degraded number, and everything downstream inherits it.
        mispriced = valuation_canary(cur)
        unconfirmed = quantity_canary(cur)
    if mispriced:
        raise ValuationMismatch(
            "book valuation disagrees with the latest bars (§4.2): "
            + "; ".join(f"{m['ticker']} valued {m['valued_at']} vs bar "
                        f"{m['latest_bar']} on {m['bar_date']}" for m in mispriced))
    if unconfirmed:
        hb.amber("unconfirmed book quantities (§4.5 step 5): "
                 + ", ".join(f"{u['ticker']}/{u['account']} {u['qty']:g} — last confirmed "
                             f"{u['last_confirmed'] or 'never'}" for u in unconfirmed))
        hb.detail["unconfirmed_quantities"] = unconfirmed
    nav, fx = n["nav"], n["fx"]
    bets = book_effective_bets(conn, bars, fx)
    # §2.5, ruled 2026-08-06: the brief carries a levered status line whether or not the cycle is
    # armed. Computed here because §4.2 gives `score` every derived number and `compose` none.
    levered = levered_status(conn, bars, fx, nav)

    arm = Arm()
    for m in moves:
        was = f" (was {m['was']})" if m["was"] else ""
        euphoria = " · euphoria" if m["euphoric"] else ""
        arm.add("stop_move", m["ticker"], "trail", urgency="protective",
                stop=m["stop"], stop_limit_price=m["limit"],
                note=f"{m['mode']}{euphoria}{was}")
    arm_exits(conn, arm, bars, gate, breakouts, caps["cushion"], (), held=held,
              exit_inside=caps["exit_inside"])
    arm_pyramid(conn, arm, bars, caps["ceiling"])
    arm_entries(conn, arm, bars, nav, fx, gate, caps, ())
    arm_housekeeping(conn, arm, ())
    armed_n = arm.flush(conn, hb.id)

    shadow_book(conn, hb, bars)

    # The API-quota reading moved to `check` with the rest of the pre-flight: §4.2 makes `score`
    # a pure function of the database, and a job that phones the vendor is not that.
    approved, any_hurdle = refresh_marks(conn, hb)
    if not dry():
        with conn.cursor() as cur:
            # the grain is the day, not the run (migration 025). Two runs on one date used
            # to leave two NAVs and no rule for choosing; the last computation of a date now
            # replaces the earlier one, which is what "daily NAV" meant all along.
            cur.execute("""insert into nav_snapshots(d,nav_cad,equities_cad,cash_cad,
                             debt_cad,usdcad,provisional,detail)
                           values (current_date,%s,%s,%s,%s,%s,true,%s)
                           on conflict (d) do update set
                             nav_cad=excluded.nav_cad, equities_cad=excluded.equities_cad,
                             cash_cad=excluded.cash_cad, debt_cad=excluded.debt_cad,
                             usdcad=excluded.usdcad, provisional=excluded.provisional,
                             detail=excluded.detail, computed_at=now()""",
                        (nav, n["book_equities"], n["cash"], n["debt"], fx,
                         jsonb(dict(accounts=n["accounts"], per_ticker=n["per_ticker"],
                                    effective_bets=bets,
                                    balances_as_of=n["anchored"]))))
        conn.commit()

    fresh, ok = freshness(conn)
    if not ok:
        hb.amber(fresh)

    protective = [r for r in arm.rows if r.get("urgency") == "protective"]
    offerable = [r for r in arm.rows if not r.get("blocked_by")
                 and r.get("urgency") != "protective"]
    bits = []
    for kind, label in (("exit", "exit"), ("entry", "entry"), ("add", "add"),
                        ("stop_move", "stop move"), ("cancel", "cancel"), ("check", "check")):
        k = [r for r in arm.rows if r["kind"] == kind]
        if k:
            bits.append(f"{len(k)} {label}{'s' if len(k) > 1 else ''}")
    summary = "; ".join(bits) if bits else "nothing needs you"
    detail = dict(gate=gate, nav_cad=round(nav, 2), effective_bets=bets,
                  levered=levered, quarantined=sorted(held),
                  effective_bets_warn=bets is not None and bets < caps["warn_bets"],
                  armed=arm.rows, protective=len(protective), offerable=len(offerable),
                  bench_at_hurdle=dict(approved=approved, total=any_hurdle),
                  tickets_allowed=ok, start_low=caps["start_low"],
                  balances_as_of=str(n["anchored"]) if n["anchored"] else None)
    if not dry():
        with conn.cursor() as cur:
            # §4.2 / WO-6: `briefs.session_date` means the market session this output serves, and
            # it means that in every writer — the nightly record included. `current_date` in UTC is
            # the evening after the close it describes.
            cur.execute("""insert into briefs(kind,session_date,freshness,summary,detail)
                           values ('nightly',%s,%s,%s,%s)""",
                        (session_date_for(cur), fresh, summary, jsonb(detail)))
            if bets is not None and bets < caps["warn_bets"]:
                observe(cur, "breach",
                        f"Effective bets {bets:.2f} — below the §2.2 band of 4. "
                        f"Guardrail only: the hard caps are the blockers.",
                        detail=dict(effective_bets=bets), once=True)
        conn.commit()

    hb.detail.update(armed=armed_n, protective=len(protective), offerable=len(offerable),
                     effective_bets=bets, gate=gate, start_low=caps["start_low"],
                     levered=levered)
    if levered["breaches"]:
        # §2.5's utilization caps are hard caps, and §5.7 pages Zak on any hard-cap breach
        hb.amber("facility over its §2.5 utilization cap: " + ", ".join(levered["breaches"]))
    print(f"score/arming: {fresh} | {summary} | armed {armed_n} "
          f"({len(protective)} protective) | bets "
          f"{f'{bets:.2f}' if bets else 'n/a'}")
    return dict(armed=armed_n, protective=len(protective), offerable=len(offerable),
                nav_cad=nav, effective_bets=bets, gate=gate, start_low=caps["start_low"])

