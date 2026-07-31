"""daily — the nightly duties that run after the bars land (plan §4.2).

Earnings calendar → stops & trails → hurdle gaps → queue proximity → event scan
(gaps ±7%, blackout ≤5 trading days) → NAV snapshot → a structured `briefs` row the
pre-open session reads instead of recomputing anything by hand.

Everything here reads the database. The only vendor call is the earnings calendar.
"""
import os, sys, json, datetime as dt
import psycopg
from db import connect, config, get, dry, nav_cad, Heartbeat

CAL_DAYS = 45


# ---------------------------------------------------------------- earnings calendar
def sync_earnings(conn, hb):
    today = dt.date.today()
    data = get("calendar/earnings", hb.calls,
               **{"from": today.isoformat(), "to": (today + dt.timedelta(days=CAL_DAYS)).isoformat()})
    rows = (data or {}).get("earnings", []) if isinstance(data, dict) else (data or [])
    with conn.cursor() as cur:
        cur.execute("select ticker from universe where status='active'")
        ours = {r[0] for r in cur.fetchall()}
    keep = []
    for e in rows:                      # pull broad, filter locally — the vendor's symbol filter lies
        code = e.get("code")
        if code not in ours:
            continue
        rd = e.get("report_date") or e.get("date")
        if not rd:
            continue
        keep.append((code, rd, e.get("before_after_market"),
                     e.get("estimate"), e.get("actual"), None, None))
    if keep and not dry():
        with conn.cursor() as cur:
            cur.executemany("""insert into earnings(ticker,report_date,report_when,eps_est,eps_actual,
                                 revenue_est,revenue_actual)
                               values (%s,%s,%s,%s,%s,%s,%s)
                               on conflict (ticker,report_date) do update set
                                 report_when=excluded.report_when, eps_est=excluded.eps_est,
                                 eps_actual=excluded.eps_actual, updated_at=now()""", keep)
        conn.commit()
    hb.detail["earnings_rows"] = len(keep)
    hb.detail["earnings_scanned"] = len(rows)
    return len(keep)


# ---------------------------------------------------------------- stops & trails (§3.2)
def ratchet(conn, hb, buffer_pct):
    """Momentum trails only. Compounders carry no stops — hurdle alerts only (§3.1)."""
    moves = []
    with conn.cursor() as cur:
        cur.execute("""select b.id, b.ticker, b.avg_cost, b.stop, b.highest_close, b.trail_mode,
                              b.pyramid_step, b.opened_at
                       from book b where b.status='open' and b.sleeve='momentum'""")
        positions = cur.fetchall()
        for pid, tk, cost, stop, hc, mode, step, opened in positions:
            cur.execute("""select d, close from prices where ticker=%s and d >= %s order by d""",
                        (tk, opened or dt.date(1990, 1, 1)))
            bars = cur.fetchall()
            if not bars:
                continue
            closes = [float(c) for _, c in bars]
            px = closes[-1]
            new_hc = max(closes) if hc is None else max(float(hc), max(closes))

            # euphoria (§3.2): >2 sd above own 50-day, or the largest single-day gain since entry
            euphoric = False
            if len(closes) >= 50:
                w = closes[-50:]
                mean = sum(w) / 50.0
                sd = (sum((x - mean) ** 2 for x in w) / 50.0) ** 0.5
                euphoric = sd > 0 and px > mean + 2 * sd
            if len(closes) >= 2:
                gains = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
                if gains and gains[-1] >= max(gains):
                    euphoric = True

            up = px / float(cost) - 1 if cost else 0.0
            if euphoric:
                cand, new_mode = new_hc * 0.95, "trail5"
            elif up >= 0.15:
                cand, new_mode = new_hc * 0.90, "trail10"
            elif step >= 3:
                cand, new_mode = float(cost), "breakeven"
            else:
                cand, new_mode = (float(stop) if stop is not None else None), (mode or "initial")

            if cand is None:
                continue
            cur_stop = float(stop) if stop is not None else None
            new_stop = cand if cur_stop is None else max(cur_stop, cand)   # ratchets up, never down
            if cur_stop is None or new_stop > cur_stop + 1e-9 or new_hc != (float(hc) if hc else None):
                if not dry():
                    cur.execute("""update book set stop=%s, stop_limit=%s, highest_close=%s,
                                     trail_mode=%s, updated_at=now() where id=%s""",
                                (new_stop, new_stop * (1 - buffer_pct), new_hc, new_mode, pid))
                if cur_stop is None or new_stop > cur_stop + 1e-9:
                    moves.append({"ticker": tk, "stop": round(new_stop, 2),
                                  "limit": round(new_stop * (1 - buffer_pct), 2),
                                  "mode": new_mode, "from": round(cur_stop, 2) if cur_stop else None})
    conn.commit()
    hb.detail["stop_moves"] = moves
    return moves


# ---------------------------------------------------------------- event scan
def event_scan(conn, hb, gap_threshold, blackout_days):
    fired, gaps, blackout = [], [], []
    with conn.cursor() as cur:
        # stops crossed — the broker GTC should have filled; the brief asks Zak to confirm
        cur.execute("""select b.ticker, b.stop, p.d, p.open, p.low, p.close, prev.close
                       from book b
                       join lateral (select d,open,low,close from prices where ticker=b.ticker
                                     order by d desc limit 1) p on true
                       join lateral (select close from prices where ticker=b.ticker and d < p.d
                                     order by d desc limit 1) prev on true
                       where b.status='open' and b.stop is not null""")
        for tk, stop, d, op, lo, cl, prev in cur.fetchall():
            if lo is not None and float(lo) <= float(stop):
                fired.append({"ticker": tk, "stop": float(stop), "low": float(lo), "date": str(d),
                              "gapped_through": float(op) < float(stop)})

        # gaps ±7% on anything we hold or have queued
        cur.execute("""select u.ticker, p.d, p.open, prev.close
                       from universe u
                       join lateral (select d,open from prices where ticker=u.ticker
                                     order by d desc limit 1) p on true
                       join lateral (select close from prices where ticker=u.ticker and d < p.d
                                     order by d desc limit 1) prev on true
                       where u.is_holding
                          or u.ticker in (select ticker from queue)""")
        for tk, d, op, prev in cur.fetchall():
            if not op or not prev:
                continue
            move = float(op) / float(prev) - 1
            if abs(move) >= gap_threshold:
                gaps.append({"ticker": tk, "date": str(d), "gap_pct": round(100 * move, 1)})

        # earnings blackout — no new entries, no adds (§3.3)
        cur.execute("""select e.ticker, e.report_date, e.report_when
                       from earnings e
                       where e.report_date >= current_date
                         and e.report_date <= current_date + %s
                         and (e.ticker in (select ticker from queue)
                              or e.ticker in (select ticker from book where status='open'))
                       order by e.report_date""", (int(blackout_days * 1.6) + 1,))  # cal days ≈ trading days
        for tk, rd, when in cur.fetchall():
            blackout.append({"ticker": tk, "report_date": str(rd), "when": when})
    hb.detail.update(stops_fired=fired, gaps=gaps, blackout=blackout)
    return fired, gaps, blackout


# ---------------------------------------------------------------- hurdles & queue proximity
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
            cur.execute("""update queue q set proximity = abs(p.close - q.trigger_price)/nullif(p.close,0)
                           from (select distinct on (ticker) ticker, close from prices
                                 order by ticker, d desc) p
                           where p.ticker = q.ticker and q.trigger_price is not null""")
        cur.execute("select count(*) from bench where gap_to_hurdle <= 0 and approved")
        buyable = cur.fetchone()[0]
    conn.commit()
    hb.detail["bench_buyable"] = buyable
    return buyable


# ---------------------------------------------------------------- NAV (§2.0)
def nav_snapshot(conn, hb):
    with conn.cursor() as cur:
        n = nav_cad(cur)
        detail = {"accounts": n["accounts"], "per_ticker": n["per_ticker"],
                  "balances_as_of": str(n["anchored"]) if n["anchored"] else None,
                  "book_equities_cad": round(n["book_equities"], 2)}
        if not dry():
            cur.execute("""insert into nav_snapshots(d,nav_cad,equities_cad,cash_cad,debt_cad,
                             usdcad,provisional,detail)
                           values (current_date,%s,%s,%s,%s,%s,true,%s)""",
                        (n["nav"], n["book_equities"], n["cash"], n["debt"], n["fx"],
                         json.dumps(detail, default=str)))
    conn.commit()
    hb.detail["nav_cad"] = round(n["nav"], 2)
    hb.detail["nav_balances_captured"] = n["balances_captured"]
    return n["nav"], n["anchored"]


# ---------------------------------------------------------------- freshness + brief
def freshness(conn):
    with conn.cursor() as cur:
        cur.execute("select max(d) from prices")
        last_bar = cur.fetchone()[0]
        # the LATEST run per job, not every run in the window — a job that failed, got fixed
        # and went green must not hold the whole machine amber for another 36 hours, because
        # "stale data ⇒ no new tickets" would then block a perfectly good Monday
        cur.execute("""select distinct on (job) job, status, finished_at from runs
                       where started_at > now() - interval '36 hours'
                       order by job, id desc""")
        recent = cur.fetchall()
    bad = [f"{j} {s}" for j, s, _ in recent if s in ("red", "amber")]
    # §4.7: an amber job makes its own domain stale, not every domain. Only the price feed
    # gates tickets — a wobble in the fundamentals sweep must not stop a momentum entry.
    price_bad = [f"{j} {s}" for j, s, _ in recent
                 if s in ("red", "amber") and j in ("nightly-ingest", "nightly-retry", "daily")]
    stale_days = (dt.date.today() - last_bar).days if last_bar else 999
    if stale_days > 4:
        return f"⚠️ bars stale — last close {last_bar} ({stale_days}d)", False
    if price_bad:
        return f"⚠️ {', '.join(sorted(set(price_bad)))} — data {last_bar}, tickets held", False
    if bad:
        return f"data {last_bar} close ✓ · {', '.join(sorted(set(bad)))} (that domain only)", True
    return f"data {last_bar} close ✓ all green", True


def write_brief(conn, hb, fresh, ok, moves, fired, gaps, blackout, nav, anchored, buyable):
    with conn.cursor() as cur:
        cur.execute("select state, week_end from gate_state order by id desc limit 1")
        g = cur.fetchone()
        cur.execute("select count(*) from queue where state='BUY'")
        buys = cur.fetchone()[0]
    bits = []
    if fired:    bits.append(f"{len(fired)} stop(s) fired")
    if gaps:     bits.append(f"{len(gaps)} gap(s) ±7%")
    if moves:    bits.append(f"{len(moves)} stop move(s)")
    if blackout: bits.append(f"{len(blackout)} in blackout")
    if buyable:  bits.append(f"{buyable} bench name(s) at or below hurdle")
    summary = "; ".join(bits) if bits else "nothing needs you"
    detail = {"gate": g[0] if g else None, "gate_week": str(g[1]) if g else None,
              "nav_cad": round(nav, 2), "nav_provisional": anchored is None,
              "queue_buy": buys, "stop_moves": moves, "stops_fired": fired,
              "gaps": gaps, "blackout": blackout, "bench_buyable": buyable,
              "tickets_allowed": ok}
    if not dry():
        with conn.cursor() as cur:
            cur.execute("""insert into briefs(kind,session_date,freshness,summary,detail)
                           values ('preopen',current_date,%s,%s,%s)""",
                        (fresh, summary, json.dumps(detail, default=str)))
        conn.commit()
    return summary


def main():
    with connect() as conn:
        with Heartbeat(conn, "daily") as hb:
            with conn.cursor() as cur:
                buf = float(config(cur, "stop_limit_buffer", 0.03))
                gap_t = float(config(cur, "gap_threshold", 0.07))
                bo = float(config(cur, "blackout_trading_days", 5))
            n = sync_earnings(conn, hb)
            moves = ratchet(conn, hb, buf)
            fired, gaps, blackout = event_scan(conn, hb, gap_t, bo)
            buyable = refresh_marks(conn, hb)
            nav, anchored = nav_snapshot(conn, hb)
            fresh, ok = freshness(conn)
            if not ok:
                hb.amber(fresh)
            summary = write_brief(conn, hb, fresh, ok, moves, fired, gaps, blackout,
                                  nav, anchored, buyable)
            hb.rows = n + len(moves) + 1
            print(f"daily: {fresh} | {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
