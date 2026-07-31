"""nightly-ingest: pull new daily bars for every active universe ticker.
Incremental (from last stored date + 1); doubles as backfill when a ticker has no bars.
Heartbeat: every run writes a runs row — green | amber | red. DRY_RUN fetches but never writes prices.
"""
import os, sys, json, time, datetime as dt, urllib.request, urllib.error
import psycopg

API = "https://eodhd.com/api/eod/{t}?api_token={k}&fmt=json&from={f}"
JOB = os.environ.get("JOB_NAME", "nightly-ingest")
DRY = os.environ.get("DRY_RUN", "false").lower() in ("1", "true", "yes")

def db_url():
    url = os.environ["DATABASE_URL"]
    if "sslmode" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url

def get_config(cur, key, default):
    cur.execute("select value from config where key=%s order by set_at desc limit 1", (key,))
    row = cur.fetchone()
    return row[0] if row else default

def fetch(ticker, frm, calls):
    url = API.format(t=ticker, k=os.environ["EODHD_API_KEY"], f=frm.isoformat())
    for attempt in range(3):
        calls[0] += 1
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1)); continue
            raise
        except Exception:
            if attempt < 2:
                time.sleep(5 * (attempt + 1)); continue
            raise

def main():
    today = dt.date.today()
    calls = [0]; rows_written = 0; errors = {}; per = {}
    with psycopg.connect(db_url()) as conn:
        with conn.cursor() as cur:
            # retry job: skip if the primary already ran green today
            if JOB == "nightly-retry":
                cur.execute("""select 1 from runs where job='nightly-ingest' and status='green'
                               and dry_run=false and started_at::date = current_date limit 1""")
                if cur.fetchone():
                    cur.execute("insert into runs(job,finished_at,status,dry_run,calls_used,rows_written,detail) values (%s,now(),'green',%s,0,0,%s)",
                                (JOB, DRY, json.dumps({"skipped": "primary already green"})))
                    conn.commit(); print("retry: primary already green — skipping"); return 0
            cur.execute("insert into runs(job,status,dry_run) values (%s,'running',%s) returning id", (JOB, DRY))
            run_id = cur.fetchone()[0]; conn.commit()
            years = int(get_config(cur, "bars_retention_years", 3))
            backfill_from = today - dt.timedelta(days=365 * years)
            cur.execute("select ticker from universe where status='active' order by ticker")
            tickers = [r[0] for r in cur.fetchall()]
        try:
            for t in tickers:
                with conn.cursor() as cur:
                    cur.execute("select max(d) from prices where ticker=%s", (t,))
                    last = cur.fetchone()[0]
                frm = (last + dt.timedelta(days=1)) if last else backfill_from
                if frm > today:
                    per[t] = "up-to-date"; continue
                try:
                    bars = fetch(t, frm, calls)
                except Exception as e:
                    errors[t] = f"{type(e).__name__}: {e}"; continue
                if not isinstance(bars, list):
                    errors[t] = f"unexpected payload: {str(bars)[:80]}"; continue
                if not DRY and bars:
                    with conn.cursor() as cur:
                        cur.executemany(
                            """insert into prices(ticker,d,open,high,low,close,adj_close,volume)
                               values (%s,%s,%s,%s,%s,%s,%s,%s)
                               on conflict (ticker,d) do update set open=excluded.open,high=excluded.high,
                                 low=excluded.low,close=excluded.close,adj_close=excluded.adj_close,
                                 volume=excluded.volume,ingested_at=now()""",
                            [(t, b["date"], b.get("open"), b.get("high"), b.get("low"),
                              b.get("close"), b.get("adjusted_close"), int(b.get("volume") or 0)) for b in bars])
                    conn.commit()
                rows_written += len(bars); per[t] = len(bars)
            status = "green" if not errors else ("amber" if rows_written or per else "red")
            detail = {"per_ticker": per, "errors": errors, "dry_run": DRY}
            with conn.cursor() as cur:
                cur.execute("update runs set finished_at=now(), status=%s, calls_used=%s, rows_written=%s, detail=%s where id=%s",
                            (status, calls[0], 0 if DRY else rows_written, json.dumps(detail), run_id))
            conn.commit()
            print(f"{JOB}: {status} — {rows_written} bars ({'dry' if DRY else 'live'}), {calls[0]} calls, {len(errors)} errors")
            for t, e in errors.items(): print("  ERR", t, e)
            return 0 if status != "red" else 1
        except Exception as e:
            with conn.cursor() as cur:
                cur.execute("update runs set finished_at=now(), status='red', calls_used=%s, detail=%s where id=%s",
                            (calls[0], json.dumps({"fatal": f"{type(e).__name__}: {e}"}), run_id))
            conn.commit(); raise

if __name__ == "__main__":
    sys.exit(main())
