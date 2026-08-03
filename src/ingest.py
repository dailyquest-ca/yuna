"""ingest-daily — write the world down: the day's bars in bulk, the corporate actions that
rewrite history, the earnings calendar, and the quarantine that holds prints nobody can confirm.

§4.1 is explicit: "Prices in bulk — a few hundred calls nightly regardless of universe size, never
1,500 per-ticker pulls as the routine. Per-ticker calls remain the tool for exactly four things:
cold start, corporate-action refreshes, gap repair, and names entering L0."

So one bulk call carries the whole US tape, two more carry the day's splits and dividends, and
per-ticker pulls are reserved for those four cases — capped per night, because a split touching two
hundred names must not spend the day's quota.

Why corporate actions matter this much: a split rewrites a stock's entire adjusted history. Without
the re-pull a 4:1 split reads as a −75% crash and fires false alarms through the whole stop layer.

§4.2, 2026-08-02: this job touches source-of-truth tables ONLY and derives nothing. Everything
computed from these rows — stops, NAV, scores, arming — belongs to `score`, which runs after.
The 03:00 appointment is this same job scheduled twice; it reads `runs` and exits if the night
is already green.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from db import (connect, config, dry, get, jsonb, load_bars, observe,
                stops_breached, Heartbeat)
import signals as sg

JOB = "ingest-daily"
# §4.2: each scheduled job has an appointment. The heartbeat compares arrival to it; the second
# run of the night keeps the same job name and the same row shape, so `runs` reads as one job
# with two appointments rather than two jobs with one duty.
SCHEDULE_UTC = os.environ.get("SCHEDULED_UTC", "02:00")
SECOND_RUN = os.environ.get("SKIP_IF_GREEN", "false").lower() in ("1", "true", "yes")
REPAIR_CAP = int(os.environ.get("REPAIR_CAP", "250"))     # per-ticker pulls allowed per night
GAP_DAYS = 5
CAL_DAYS = 45
CAL_BACK = 400          # a full reporting year behind, so "already reported" is a fact, not a guess


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



def describe_action(kind, row):
    """"split 4:1" / "dividend $0.24" — what happened, not how many rows it touched."""
    if kind == "split":
        ratio = sg.split_ratio(row)
        return f"split {ratio:g}:1" if ratio else "split (unparsed)"
    amount = (row or {}).get("dividend") or (row or {}).get("value")
    try:
        return f"dividend ${float(amount):g}"
    except (TypeError, ValueError):
        return "dividend"


def bulk_day(calls, date=None, kind=None):
    """One call for the whole US tape. `kind` fetches splits or dividends instead of bars."""
    params = {}
    if date:
        params["date"] = date.isoformat()
    if kind:
        params["type"] = kind
    rows = get("eod-bulk-last-day/US", calls, **params)
    return rows if isinstance(rows, list) else []


def per_ticker(ticker, frm, calls):
    rows = get(f"eod/{ticker}", calls, **{"from": frm.isoformat()})
    return rows if isinstance(rows, list) else []


def upsert(cur, ticker, bars):
    rows = [(ticker, b.get("date"), b.get("open"), b.get("high"), b.get("low"), b.get("close"),
             b.get("adjusted_close"), int(b.get("volume") or 0)) for b in bars if b.get("date")]
    if rows:
        cur.executemany("""insert into prices(ticker,d,open,high,low,close,adj_close,volume)
                           values (%s,%s,%s,%s,%s,%s,%s,%s)
                           on conflict (ticker,d) do update set open=excluded.open,
                             high=excluded.high, low=excluded.low, close=excluded.close,
                             adj_close=excluded.adj_close, volume=excluded.volume,
                             ingested_at=now()""", rows)
    return len(rows)


def main():
    with connect() as conn:
        with Heartbeat(conn, JOB, scheduled_utc=SCHEDULE_UTC) as hb:
            if SECOND_RUN:                        # §4.2: exit if the night is already green
                with conn.cursor() as cur:
                    cur.execute("""select 1 from runs where job=%s and status='green'
                                   and dry_run=false and started_at::date = current_date
                                   and id <> %s limit 1""", (JOB, hb.id))
                    if cur.fetchone():
                        hb.detail["skipped"] = "the night is already green"
                        print("ingest-daily (03:00): already green — nothing to redo")
                        return 0

            with conn.cursor() as cur:
                years = int(config(cur, "bars_retention_years", 10))
                threshold = float(config(cur, "quarantine_move_threshold", 0.40))
                tolerance = float(config(cur, "quarantine_source_tolerance", 0.02))
                cur.execute("select ticker, kind from universe where status='active'")
                names = {r[0]: r[1] for r in cur.fetchall()}
                cur.execute("select ticker, max(d) from prices group by ticker")
                last_bar = dict(cur.fetchall())
            backfill_from = dt.date.today() - dt.timedelta(days=365 * years)

            # ---- 1. the whole US tape, in one call
            tape = {b["code"]: b for b in bulk_day(hb.calls) if b.get("code")}
            as_of = next((b.get("date") for b in tape.values()), None)

            written = 0
            if not dry():
                with conn.cursor() as cur:
                    for ticker in names:
                        if ticker.endswith(".US") and ticker[:-3] in tape:
                            written += upsert(cur, ticker, [tape[ticker[:-3]]])
                conn.commit()

            # ---- 2. corporate actions
            actions = {}
            for kind in ("splits", "dividends"):
                for row in bulk_day(hb.calls, kind=kind):
                    code = row.get("code")
                    tk = code if str(code).endswith(".US") else f"{code}.US"
                    if tk in names:
                        actions.setdefault(tk, []).append((kind[:-1], row))
            if actions and not dry():
                with conn.cursor() as cur:
                    cur.executemany("""insert into corporate_actions(ticker,d,kind,detail)
                                       values (%s,%s,%s,%s)
                                       on conflict (ticker,d,kind) do nothing""",
                                    [(tk, r.get("date") or as_of, kind, jsonb(r))
                                     for tk, rows in actions.items() for kind, r in rows])
                conn.commit()

            # ---- 3. per-ticker work, for the four cases §4.1 allows and no others
            repairs = []
            for ticker in names:
                have = last_bar.get(ticker)
                if ticker in actions:
                    # Name the action and its size. "corporate action: 751" told a reader the row
                    # count and nothing about what happened; a 4:1 split and a 2c dividend need
                    # very different amounts of attention.
                    why = "corporate action (" + ", ".join(sorted({
                        describe_action(kind, row) for kind, row in actions[ticker]})) + ")"
                elif not have:
                    why = "cold start"
                elif not ticker.endswith(".US"):
                    why = "non-US listing"          # bulk is per-exchange; index and FX land here
                elif (dt.date.today() - have).days > GAP_DAYS and ticker[:-3] not in tape:
                    why = "gap repair"
                else:
                    continue
                repairs.append((ticker, why, have))

            # corporate actions first: a stale split is the one that invents a crash
            repairs.sort(key=lambda r: (not r[1].startswith("corporate action"),
                                        r[1] != "non-US listing"))
            skipped = repairs[REPAIR_CAP:]
            repairs = repairs[:REPAIR_CAP]

            errors, per_name = {}, {}
            with conn.cursor() as cur:
                for ticker, why, have in repairs:
                    frm = (backfill_from if why == "cold start"
                                        or why.startswith("corporate action")
                           else (have + dt.timedelta(days=1) if have else backfill_from))
                    try:
                        bars = per_ticker(ticker, frm, hb.calls)
                    except Exception as e:
                        errors[ticker] = f"{type(e).__name__}: {e}"
                        continue
                    if not dry():
                        if why.startswith("corporate action") and bars:
                            cur.execute("delete from prices where ticker=%s and d >= %s",
                                        (ticker, frm))
                        written += upsert(cur, ticker, bars)
                    per_name[ticker] = f"{why}: {len(bars)}"
                conn.commit()

            # ---- 4. the earnings calendar (source data, so it belongs here, not in score)
            sync_earnings(conn, hb)

            # ---- 5. quarantine: a print no second source will confirm must not drive a sell (§4.1)
            with conn.cursor() as cur:
                cur.execute("""select ticker from universe
                               where is_holding or ticker in (select ticker from queue)
                                  or ticker in (select ticker from bench)
                                  or ticker in (select ticker from book where status='open')""")
                watched = [r[0] for r in cur.fetchall()]
                bars = load_bars(cur, watched)
                # judged against the protection standing when the print arrived — `score` ratchets
                # stops afterwards, and §4.1 is explicit that an unverified sell-side print must
                # never disarm protection, so the later stop cannot be the trigger here
                watched_exits = stops_breached(cur, bars)
            held = quarantine_pass(conn, hb, bars, threshold, tolerance, watched_exits)

            hb.rows = 0 if dry() else written
            hb.detail.update(tape=dict(rows=len(tape), as_of=as_of),
                             quarantine_blocking=sorted(held),
                             corporate_actions={k: [describe_action(kd, r) for kd, r in v]
                                                for k, v in actions.items()},
                             repairs=per_name, repair_errors=errors,
                             repairs_skipped=[r[0] for r in skipped])
            if errors:
                hb.amber(f"{len(errors)} per-ticker pull(s) failed")
            if skipped:
                # never a silent cap — §4.1's budget is real, so the brief has to hear about it
                hb.amber(f"{len(skipped)} repair(s) deferred past tonight's cap of {REPAIR_CAP}")
            print(f"{JOB}: {written} bars from {len(tape)} tape rows · {len(repairs)} per-ticker "
                  f"· {len(actions)} corporate actions · {hb.calls[0]} calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
