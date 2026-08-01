"""nightly-ingest — the day's bars, in bulk, plus the corporate actions that rewrite history.

§4.1 is explicit: "Prices in bulk — a few hundred calls nightly regardless of universe size, never
1,500 per-ticker pulls as the routine. Per-ticker calls remain the tool for exactly four things:
cold start, corporate-action refreshes, gap repair, and names entering L0."

So one bulk call carries the whole US tape, two more carry the day's splits and dividends, and
per-ticker pulls are reserved for those four cases — capped per night, because a split touching two
hundred names must not spend the day's quota.

Why corporate actions matter this much: a split rewrites a stock's entire adjusted history. Without
the re-pull a 4:1 split reads as a −75% crash and fires false alarms through the whole stop layer.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from db import connect, config, dry, get, jsonb, Heartbeat

JOB = os.environ.get("JOB_NAME", "nightly-ingest")
# §4.2: each scheduled job has an appointment. The heartbeat compares arrival to it.
SCHEDULE = {"nightly-ingest": "02:00", "nightly-retry": "03:00"}
REPAIR_CAP = int(os.environ.get("REPAIR_CAP", "250"))     # per-ticker pulls allowed per night
GAP_DAYS = 5


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
        with Heartbeat(conn, JOB, scheduled_utc=SCHEDULE.get(JOB)) as hb:
            if JOB == "nightly-retry":            # §4.2: exit if the night is already green
                with conn.cursor() as cur:
                    cur.execute("""select 1 from runs where job='nightly-ingest' and status='green'
                                   and dry_run=false and started_at::date = current_date limit 1""")
                    if cur.fetchone():
                        hb.detail["skipped"] = "primary already green"
                        print("retry: primary already green — skipping")
                        return 0

            with conn.cursor() as cur:
                years = int(config(cur, "bars_retention_years", 3))
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
                    why = "corporate action"        # adjusted history must be rewritten wholesale
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
            repairs.sort(key=lambda r: (r[1] != "corporate action", r[1] != "non-US listing"))
            skipped = repairs[REPAIR_CAP:]
            repairs = repairs[:REPAIR_CAP]

            errors, per_name = {}, {}
            with conn.cursor() as cur:
                for ticker, why, have in repairs:
                    frm = (backfill_from if why in ("cold start", "corporate action")
                           else (have + dt.timedelta(days=1) if have else backfill_from))
                    try:
                        bars = per_ticker(ticker, frm, hb.calls)
                    except Exception as e:
                        errors[ticker] = f"{type(e).__name__}: {e}"
                        continue
                    if not dry():
                        if why == "corporate action" and bars:
                            cur.execute("delete from prices where ticker=%s and d >= %s",
                                        (ticker, frm))
                        written += upsert(cur, ticker, bars)
                    per_name[ticker] = f"{why}: {len(bars)}"
                conn.commit()

            hb.rows = 0 if dry() else written
            hb.detail.update(tape=dict(rows=len(tape), as_of=as_of),
                             corporate_actions={k: len(v) for k, v in actions.items()},
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
