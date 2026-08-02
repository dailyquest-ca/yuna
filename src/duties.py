"""duties — the nightly half of the machine (§3.0 daily row, §4.2 nightly-ingest duties).

Runs after the bars land, and does everything that must be true before the open:

  fills applied -> earnings synced -> bases re-scanned -> breakouts classified -> stops ratcheted
  -> exits armed -> entries and adds armed -> caps applied -> NAV -> brief.

It writes no tickets. §2.2 and §4.3 both say jobs arm and only sessions write tickets, because a
ticket carries a theme and a theme is judgment. So every conclusion lands in `armed`, priced and
cap-checked, and R1/R2 turn those into tickets. Protective conclusions are marked urgency
'protective': they survive a stale-data night, and nothing else does.
"""
import datetime as dt
import sys

import numpy as np

from db import (connect, config, dry, get, jsonb, nav_cad, observe, Heartbeat,
                valuation_canary, quantity_canary)


class ValuationMismatch(RuntimeError):
    """§4.2: a holding priced off anything but its latest bar fails the run, red."""
import signals as sg

CAL_DAYS = 45
CAL_BACK = 400          # a full reporting year behind, so "already reported" is a fact, not a guess


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
                       where t.applied_at is null
                       order by t.trade_date, t.id""")
        rows = cur.fetchall()
        for (tid, tk, acct, side, qty, price, ccy, tdate, step, ticket_id, sleeve, theme,
             stop, stop_limit, pivot, target_qty) in rows:
            qty, price = float(qty), float(price)
            cur.execute("""select id, qty, avg_cost, pyramid_step from book
                           where ticker=%s and account=%s and status='open'""", (tk, acct))
            held = cur.fetchone()
            if side == "buy":
                if held:
                    bid, bqty, bcost, bstep = held
                    new_qty = float(bqty) + qty
                    new_cost = (float(bqty) * float(bcost) + qty * price) / new_qty
                    cur.execute("""update book set qty=%s, avg_cost=%s,
                                     pyramid_step=greatest(pyramid_step, coalesce(%s, pyramid_step)),
                                     pyramid_stalled_since = case
                                       when greatest(pyramid_step, coalesce(%s, pyramid_step)) >= 3
                                       then null else pyramid_stalled_since end,
                                     adds_12m = adds_12m + case when %s then 1 else 0 end,
                                     last_add_at = case when %s then %s else last_add_at end,
                                     updated_at=now() where id=%s""",
                                (new_qty, new_cost, step, step, sleeve == "compounders",
                                 sleeve == "compounders", tdate, bid))
                else:
                    cur.execute("""insert into book(ticker,account,sleeve,lot,qty,avg_cost,currency,
                                     opened_at,stop,stop_limit,highest_close,trail_mode,
                                     pyramid_step,theme,pivot,target_qty,
                                     pyramid_stalled_since,status)
                                   values (%s,%s,%s,'core',%s,%s,%s,%s,%s,%s,%s,'initial',%s,%s,
                                           %s,%s,%s,'open')""",
                                # the stall clock starts at entry: §3.2 gives a pyramid four weeks
                                # to reach full size, and nothing was starting it before
                                (tk, acct, sleeve or "momentum", qty, price, ccy or "USD", tdate,
                                 stop, stop_limit, price, step or 1, theme, pivot, target_qty,
                                 tdate if (sleeve or "momentum") == "momentum" else None))
            else:
                if held:
                    bid, bqty, _, _ = held
                    left = float(bqty) - qty
                    if left <= 1e-6:
                        cur.execute("""update book set qty=0, status='closed', closed_at=%s,
                                       updated_at=now() where id=%s""", (tdate, bid))
                    else:
                        cur.execute("update book set qty=%s, updated_at=now() where id=%s",
                                    (left, bid))
            cur.execute("update transactions set applied_at=now() where id=%s", (tid,))
            if ticket_id:
                cur.execute("""update tickets set state='provisional', updated_at=now()
                               where id=%s and state in ('proposed','approved')""", (ticket_id,))
            applied.append(f"{side} {qty:g} {tk} @ {price:g}")
    conn.commit()
    hb.detail["fills_applied"] = applied
    return applied


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


# --------------------------------------------------------------------------- earnings (§4.1)
def sync_earnings(conn, hb):
    today = dt.date.today()
    # Forward-only left the system unable to tell "already reported, next print is beyond the window"
    # from "the calendar has a hole" — MEDP, a July reporter, simply had no row at all. The window now
    # reaches back a full reporting year, so `v_earnings_state` can answer both questions from the
    # ledger: last_reported_date and next_report_date, per ticker, with no denormalized column to
    # drift. One extra call on a job that already spends 46.
    data = get("calendar/earnings", hb.calls,
               **{"from": (today - dt.timedelta(days=CAL_BACK)).isoformat(),
                  "to": (today + dt.timedelta(days=CAL_DAYS)).isoformat()})
    rows = (data or {}).get("earnings", []) if isinstance(data, dict) else (data or [])
    with conn.cursor() as cur:
        cur.execute("select ticker from universe where status='active'")
        ours = {r[0] for r in cur.fetchall()}
    keep = []
    for e in rows:                      # pull broad, filter locally — the vendor's filter lies
        code, rd = e.get("code"), (e.get("report_date") or e.get("date"))
        if code in ours and rd:
            keep.append((code, rd, e.get("before_after_market"), e.get("estimate"),
                         e.get("actual"), None, None))
    if keep and not dry():
        with conn.cursor() as cur:
            cur.executemany("""insert into earnings(ticker,report_date,report_when,eps_est,
                                 eps_actual,revenue_est,revenue_actual)
                               values (%s,%s,%s,%s,%s,%s,%s)
                               on conflict (ticker,report_date) do update set
                                 report_when=excluded.report_when, eps_est=excluded.eps_est,
                                 eps_actual=excluded.eps_actual, updated_at=now()""", keep)
        conn.commit()
    hb.detail["earnings_rows"] = len(keep)
    return len(keep)


# --------------------------------------------------------------------------- bars in memory
def load_bars(cur, tickers):
    cur.execute("""select ticker, d, open, high, low, close, adj_close, volume
                   from prices where ticker = any(%s) order by ticker, d""", (list(tickers),))
    out = {}
    for t, d, op, hi, lo, cl, ac, vol in cur.fetchall():
        out.setdefault(t, []).append(dict(d=d, open=op, high=hi, low=lo, close=cl,
                                          adj=ac if ac is not None else cl, vol=vol or 0))
    return out


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


# --------------------------------------------------------------------------- quarantine (§4.1)
def quarantine_pass(conn, hb, bars, threshold, tolerance, watched_exits):
    """Hold suspicious prints out of use until two sources agree (§4.1).

    Two triggers: a print moving more than 40% with no corporate action logged for that session,
    and any print that would fire a sell-side action. The second source is a live vendor quote —
    the job's own re-fetch is the first. Neither source alone may sell a position.
    """
    raised, resolved = [], []
    with conn.cursor() as cur:
        cur.execute("""select ticker, d from corporate_actions
                       where d > current_date - interval '10 days'""")
        actions = {(t_, d_) for t_, d_ in cur.fetchall()}

        for tk, b in bars.items():
            if len(b) < 2:
                continue
            last, prev = b[-1], b[-2]
            why = None
            if sg.suspicious_move(last["close"], prev["close"], threshold=threshold) \
                    and (tk, last["d"]) not in actions:
                why = "move"
            elif tk in watched_exits:
                why = "sell_side"
            if not why:
                continue
            move = ((float(last["close"]) / float(prev["close"]) - 1.0)
                    if prev["close"] else None)
            if not dry():
                cur.execute("""insert into quarantine(ticker,d,close,prev_close,move_pct,reason)
                               values (%s,%s,%s,%s,%s,%s)
                               on conflict (ticker,d) where status='held' do nothing""",
                            (tk, last["d"], last["close"], prev["close"], move, why))
            raised.append(dict(ticker=tk, d=str(last["d"]), reason=why, move_pct=move))

        # verify everything still held, against a live quote
        cur.execute("select id, ticker, d, close from quarantine where status='held'")
        for qid, tk, d, close in cur.fetchall():
            try:
                quote = get(f"real-time/{tk}", hb.calls)
                second = float((quote or {}).get("close") or 0) or None
            except Exception as e:
                hb.detail.setdefault("quarantine_quote_failed", []).append(f"{tk}: {e}")
                continue
            agrees = sg.sources_agree(close, second, tolerance=tolerance)
            status = "confirmed" if agrees else "cleared"
            if not dry():
                cur.execute("""update quarantine set status=%s, second_source=%s, checked_at=now(),
                                 resolved_at=now(),
                                 note = case when %s then 'two sources agree — the move is real'
                                        else 'sources disagree — the print is not to be trusted' end
                               where id=%s""", (status, second, agrees, qid))
            resolved.append(dict(ticker=tk, d=str(d), status=status, ours=close, theirs=second))
    conn.commit()
    hb.detail.update(quarantine_raised=raised, quarantine_resolved=resolved)
    # a name whose print could not be verified stays held, and stays out of sell-side action
    with conn.cursor() as cur:
        cur.execute("select ticker from quarantine where status='held'")
        held = {r[0] for r in cur.fetchall()}
    # What still blocks a sell, and what does not:
    #   * a print that LOOKS WRONG (>40% with no corporate action) blocks until verified — acting on
    #     garbage is the risk §4.1 was written for;
    #   * a print that merely happens to fire a stop does NOT block when the second source is
    #     unreachable. Taken literally the rule would let a vendor outage disarm every stop in the
    #     book, and §4.6 is explicit that protection is the thing that survives everything.
    #   * either kind blocks when the second source actively DISAGREES.
    with conn.cursor() as cur:
        cur.execute("""select ticker from quarantine
                       where (status='held' and reason='move')
                          or (status='cleared' and resolved_at::date = current_date)""")
        blocking = {r[0] for r in cur.fetchall()}
        cur.execute("""select count(*) from quarantine where status='held' and reason='sell_side'""")
        unverified_ordinary = cur.fetchone()[0]
    if blocking:
        hb.amber(f"{len(blocking)} print(s) quarantined — sell-side action held on {sorted(blocking)}")
    if unverified_ordinary:
        hb.detail["quarantine_unverified_ordinary"] = unverified_ordinary
    return blocking


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
            ok = sg.breakout_confirmed([w["vol"] for w in window],
                                       [volume_baseline(b, idx + j) for j in range(len(window))],
                                       multiple=multiple)
            expired = len(b) - idx >= sessions
            new_state = True if ok else (False if expired else None)
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


def arm_exits(conn, arm, bars, gate, breakouts, cushion, holidays, held=()):
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
                    arm.add("exit", tk, "template", order_type="market",
                            note="trend template failed", **common)
                    continue
                if mcn is not None and float(mcn) < 55:
                    arm.add("exit", tk, "score", order_type="market",
                            note=f"MCN {float(mcn):.1f} — others got stronger, which is the "
                                 f"thesis decaying", **common)
                    continue

                # ---- holding through a print needs a cushion (§3.3)
                if report and sg.trading_days_between(dt.date.today(), report,
                                                      holidays=holidays) <= 1:
                    if sg.holds_through_earnings(px, cost, cushion=cushion) is False:
                        arm.add("exit", tk, "earnings", order_type="market",
                                note=f"reports {report} without the {cushion:.2f}x cushion — "
                                     f"exit this evening, stops stay placed either way",
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
                        arm.add("exit", tk, "stall", order_type="market",
                                note="pyramid stalled below full size for 4 weeks and no new base "
                                     "— no permanent sub-scale positions", **common)


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
                                  u.industry, e.report_date, b.id
                           from queue q
                           join universe u on u.ticker=q.ticker
                           left join book b on b.ticker=q.ticker and b.status='open'
                           left join lateral (select report_date from earnings
                                              where ticker=q.ticker and report_date >= current_date
                                              order by report_date limit 1) e on true
                           where q.source='momentum' and q.state='BUY'
                             and q.trigger_price is not null
                           order by q.mcn desc nulls last""")
            for tk, trig, lim, stop, mcn, industry, report, held in cur.fetchall():
                if held:
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
                        arm.add("exit", swap["ticker"], "swap", sleeve="momentum",
                                order_type="market", score=swap["score"],
                                note=f"displaced by {tk} — {score:.1f} vs {swap['score']:.1f}, "
                                     f"+{swap['margin']:.1f} clears the §3.3 margin")
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
                              + (f" · swap out {swap['ticker']}" if swap else ""))
                        if score is not None else None,
                        detail=dict(theme_weights=theme_weight, industry=industry,
                                    full_size_pct=size["size_pct"], target_qty=full_qty,
                                    pivot=trig, swap_out=swap["ticker"] if swap else None))

        # ---- compounders: price at or below an approved bench name's hurdle
        # adds are counted from the ledger inside a rolling 12 months, never from a stored counter:
        # a counter that only increments quietly becomes a permanent block after two adds ever.
        # per-account investable cash — §2.6's "one position, one account, one order" needs to know
        # which account can fund a whole position before it names one
        cur.execute("""select distinct on (b.account) b.account, a.kind,
                              coalesce(b.cash_cad,0) + coalesce(b.cash_usd,0) * %s
                         from balances b join accounts a on a.code=b.account
                        order by b.account, b.as_of desc, b.id desc""", (fx,))
        account_cash = {r[0]: float(r[2]) for r in cur.fetchall() if r[1] != "facility"}

        cur.execute("""select b.ticker, b.ccn, b.hurdle_price, b.last_close, b.gap_to_hurdle,
                              b.data_confidence, u.industry, e.report_date, k.id, k.qty,
                              k.avg_cost, b.engine_provenance, d.dps_ttm, k.entry_fill,
                              b.owner_fcf_suspect,
                              (select count(*) from transactions t
                                 where t.ticker = b.ticker and t.side='buy'
                                   and t.trade_date > current_date - interval '12 months'
                                   and t.trade_date > k.opened_at) as adds_12m,
                              k.account
                       from bench b
                       join universe u on u.ticker=b.ticker
                       left join book k on k.ticker=b.ticker and k.status='open'
                       left join v_dividend_ttm d on d.ticker=b.ticker
                       left join lateral (select report_date from earnings
                                          where ticker=b.ticker and report_date >= current_date
                                          order by report_date limit 1) e on true
                       where b.approved and b.c1_pass and b.hurdle_price is not null
                         and b.last_close is not null and b.last_close <= b.hurdle_price
                       order by b.ccn desc""")
        for (tk, ccn_score, hurdle, px, gap, confidence, industry, report, held, hqty, hcost,
             provenance, dps_ttm, entry_fill, owner_suspect, adds, hacct) in cur.fetchall():
            ccn_score = float(ccn_score) if ccn_score is not None else None
            px, hurdle = float(px), float(hurdle)
            in_bo = sg.in_blackout(dt.date.today(), report, holidays=holidays)
            price_cad = px * fx if fx else px
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
                blocked = add["blocked"] or ("§3.3 — earnings blackout" if in_bo else None)
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
                                    engine_provenance=provenance))
                continue
            size_pct = caps["flat"]
            room = caps["ceilings"]["compounders"] * nav - exposure.get("compounders", 0.0)
            blocked, swap = None, None
            if size_pct > caps["single_cap"]:
                blocked = f"§2.3 — exceeds the {caps['single_cap']:.0%} single-name entry cap"
            elif size_pct < caps["floor_pct"]:
                blocked = f"§2.3 — below the {caps['floor_pct']:.0%} minimum position"
            elif positions >= caps["max_positions"] or size_pct * nav > room:
                swap = sg.displaceable(ccn_score, compounder_incumbents,
                                       margin=caps["displace_margin"])
                if swap:
                    arm.add("exit", swap["ticker"], "swap", sleeve="compounders",
                            order_type="market", score=swap["score"],
                            note=f"displaced by {tk} — CCN {ccn_score:.1f} vs "
                                 f"{swap['score']:.1f}, +{swap['margin']:.1f} clears §3.3")
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
            elif confidence not in ("full", None):
                blocked = f"§3.3 — scored {confidence}: manual sign-off before sizing"
            if owner_suspect and not blocked:
                # §3.1 owner-cash quarantine (2026-08-02): scored, ranked, watched — never
                # ticketed. Reported FCF here is materially customer money, and no growth cap
                # repairs a numerator.
                blocked = ("§3.1 — owner-cash quarantine: reported FCF is materially customer "
                           "float or credit-book funding; not entry-eligible until the "
                           "balance-sheet treatment prices it on owner cash")

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
                          + (f" · swap out {swap['ticker']}" if swap else "")
                          + (f" · {engine_note}" if engine_note else ""))
                    if ccn_score else None,
                    detail=dict(theme_weights=theme_weight, industry=industry,
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


def freshness(conn):
    with conn.cursor() as cur:
        # stock bars only. FX and the index come from the same nightly pull, so in a clean run this
        # is the same date — but a half-failed ingest that landed USDCAD and no equities would
        # otherwise read as fresh, and "stale data ⇒ no new tickets" would quietly not apply.
        cur.execute("""select max(p.d) from prices p join universe u on u.ticker = p.ticker
                       where u.kind = 'stock'""")
        last_bar = cur.fetchone()[0]
        cur.execute("""select distinct on (job) job, status from runs
                       where started_at > now() - interval '36 hours' order by job, id desc""")
        recent = cur.fetchall()
    bad = [f"{j} {s}" for j, s in recent if s in ("red", "amber")]
    price_bad = [x for x in bad if x.split()[0] in ("nightly-ingest", "nightly-retry", "duties")]
    stale = (dt.date.today() - last_bar).days if last_bar else 999
    if stale > 4:
        return f"⚠️ bars stale — last close {last_bar} ({stale}d)", False
    if price_bad:
        return f"⚠️ {', '.join(sorted(set(price_bad)))} — data {last_bar}, tickets held", False
    if bad:
        return f"data {last_bar} close ✓ · {', '.join(sorted(set(bad)))} (that domain only)", True
    return f"data {last_bar} close ✓ all green", True


def main():
    with connect() as conn:
        with Heartbeat(conn, "duties") as hb:
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
                    # §3.2: BUY-state names under 70 stay queued and never ticket.
                    min_mcn=float((config(cur, "score_thresholds", {}) or {}).get("enterable", 70)),
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
                    quarantine_move=float(config(cur, "quarantine_move_threshold", 0.40)),
                    quarantine_tolerance=float(config(cur, "quarantine_source_tolerance", 0.02)),
                    quota_alarm=float(config(cur, "api_alarm_fraction", 0.70)),
                )
                cur.execute("select state from gate_state order by id desc limit 1")
                gate = (cur.fetchone() or ["OFF"])[0]
                cur.execute("""select min(trade_date) from transactions t join tickets k
                                 on k.id=t.ticket_id where k.sleeve='momentum' and t.side='buy'""")
                first_fill = cur.fetchone()[0]
            caps["start_low"] = not first_fill or (dt.date.today() - first_fill).days <= 90

            apply_fills(conn, hb)
            rebase_for_splits(conn, hb)
            sync_earnings(conn, hb)

            with conn.cursor() as cur:
                cur.execute("""select ticker from universe
                               where is_holding or ticker in (select ticker from queue)
                                  or ticker in (select ticker from candidates)
                                  or ticker in (select ticker from bench)
                                  or ticker in (select ticker from book where status='open')""")
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

            # who *would* be sold tonight — those prints need a second source before they act
            with conn.cursor() as cur:
                cur.execute("""select b.ticker from book b
                               where b.status='open' and b.stop is not null""")
                watched_exits = set()
                for (tk,) in cur.fetchall():
                    bb = bars.get(tk)
                    if bb and bb[-1]["low"] is not None:
                        cur.execute("select stop from book where ticker=%s and status='open'", (tk,))
                        stop = cur.fetchone()[0]
                        if stop is not None and float(bb[-1]["low"]) <= float(stop):
                            watched_exits.add(tk)
            held = quarantine_pass(conn, hb, bars, caps["quarantine_move"],
                                   caps["quarantine_tolerance"], watched_exits)

            arm = Arm()
            for m in moves:
                was = f" (was {m['was']})" if m["was"] else ""
                euphoria = " · euphoria" if m["euphoric"] else ""
                arm.add("stop_move", m["ticker"], "trail", urgency="protective",
                        stop=m["stop"], stop_limit_price=m["limit"],
                        note=f"{m['mode']}{euphoria}{was}")
            arm_exits(conn, arm, bars, gate, breakouts, caps["cushion"], (), held=held)
            arm_pyramid(conn, arm, bars, caps["ceiling"])
            arm_entries(conn, arm, bars, nav, fx, gate, caps, ())
            arm_housekeeping(conn, arm, ())
            armed_n = arm.flush(conn, hb.id)

            shadow_book(conn, hb, bars)

            # §4.1: "the brief alarms past ~70% of daily quota". The check itself costs one call.
            quota = None
            try:
                usage = get("user", hb.calls)
                used, limit = float(usage.get("apiRequests") or 0), float(usage.get("dailyRateLimit") or 1)
                quota = dict(used=used, limit=limit, fraction=round(used / limit, 3) if limit else None)
                if quota["fraction"] and quota["fraction"] >= caps["quota_alarm"]:
                    hb.amber(f"API quota at {quota['fraction']:.0%} of the daily budget")
            except Exception as e:
                hb.detail["quota_check_failed"] = f"{type(e).__name__}: {e}"

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
                          quarantined=sorted(held), api_quota=quota,
                          effective_bets_warn=bets is not None and bets < caps["warn_bets"],
                          armed=arm.rows, protective=len(protective), offerable=len(offerable),
                          bench_at_hurdle=dict(approved=approved, total=any_hurdle),
                          tickets_allowed=ok, start_low=caps["start_low"],
                          balances_as_of=str(n["anchored"]) if n["anchored"] else None)
            if not dry():
                with conn.cursor() as cur:
                    cur.execute("""insert into briefs(kind,session_date,freshness,summary,detail)
                                   values ('nightly',current_date,%s,%s,%s)""",
                                (fresh, summary, jsonb(detail)))
                    if bets is not None and bets < caps["warn_bets"]:
                        observe(cur, "breach",
                                f"Effective bets {bets:.2f} — below the §2.2 band of 4. "
                                f"Guardrail only: the hard caps are the blockers.",
                                detail=dict(effective_bets=bets), once=True)
                conn.commit()

            hb.rows = armed_n
            hb.detail.update(armed=armed_n, protective=len(protective), offerable=len(offerable),
                             effective_bets=bets, gate=gate, start_low=caps["start_low"])
            print(f"duties: {fresh} | {summary} | armed {armed_n} "
                  f"({len(protective)} protective) | bets "
                  f"{f'{bets:.2f}' if bets else 'n/a'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
