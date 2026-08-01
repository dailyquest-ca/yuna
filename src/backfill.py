"""backfill — the one-time deepening §4.1 sanctions, run as dispatch-only tooling (§4.2).

Three things the 2026-08-01 law needs that the nightly feeds cannot produce retroactively:

  * **Ten years of bars.** The window moved 3 → 10 so §3.1's fair multiple — the stock's own 5-year
    median P/FCF — computes from stored bars instead of falling back to the short-history rule. That
    fallback was a declared deviation from the plan; this removes it rather than documenting it again.
  * **A year of dividends.** §2.6 routes US compounders with a trailing-12-month yield ≥ 1% to the
    RRSP. The nightly bulk feed accumulates from the day it started — production held exactly one
    day, 40 names — so the trailing year has to be fetched once. After this, the nightly keeps it
    current for nothing.
  * **The raw filing documents.** §4.1 moved them into the database. Only the derived extract was
    ever stored, so the archive has to be re-served once.

Per-ticker history calls are the §4.1 cold-start exception, not the routine. Budget is metered
against the vendor's own usage endpoint before spending, and the run truncates rather than dying
two-thirds through — the same discipline the fundamentals sweep learned the hard way.

    WHAT=bars,dividends,fundamentals   which passes to run (default all three)
    YEARS=10                           bar depth
    TICKERS=A.US,B.US                  limit the target set
    SWEEP_LIMIT=200                    largest N by market cap
"""
import os, sys, json, datetime as dt
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from db import connect, dry, get, Heartbeat
import fundamentals as fu

WORKERS = int(os.environ.get("WORKERS", "8"))
YEARS = int(os.environ.get("YEARS", "10"))
RESERVE = int(os.environ.get("QUOTA_RESERVE", "3000"))
SWEEP_LIMIT = int(os.environ.get("SWEEP_LIMIT", "0"))
WHAT = {w.strip() for w in os.environ.get("WHAT", "bars,dividends,fundamentals").split(",") if w.strip()}
BATCH = 500


def targets(cur):
    only = [t.strip() for t in os.environ.get("TICKERS", "").split(",") if t.strip()]
    if only:
        return only
    cur.execute("""select ticker from universe
                   where kind='stock' and (in_l0 or is_holding)
                   order by market_cap_usd desc nulls last""")
    got = [r[0] for r in cur.fetchall()]
    return got[:SWEEP_LIMIT] if SWEEP_LIMIT else got


def budget(hb, needed_units):
    """Ask before spending. Returns the number of names affordable today."""
    try:
        usage = get("user", hb.calls)
        used = float(usage.get("apiRequests") or 0)
        limit = float(usage.get("dailyRateLimit") or 100000)
        spare = max(0.0, limit - RESERVE - used)
        hb.detail["quota"] = dict(used=used, limit=limit, spare=spare)
        return int(spare // needed_units) if needed_units else 0
    except Exception as e:
        hb.detail["quota_check_failed"] = f"{type(e).__name__}: {e}"
        return 10 ** 9


def backfill_bars(conn, hb, names, since):
    """One call per name returns that name's full history; we keep `since` onward (§4.1)."""
    written = 0

    def one(t):
        try:
            rows = get(f"eod/{t}", hb.calls, tries=2, timeout=120,
                       **{"from": since.isoformat(), "period": "d"})
            return t, (rows if isinstance(rows, list) else []), None
        except Exception as e:
            return t, [], f"{type(e).__name__}: {e}"

    buf, errors = [], {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for t, rows, err in pool.map(one, names):
            if err:
                if len(errors) < 40:
                    errors[t] = err
                continue
            for b in rows:
                d = b.get("date")
                if not d:
                    continue
                buf.append((t, d, b.get("open"), b.get("high"), b.get("low"),
                            b.get("close"), b.get("adjusted_close"), b.get("volume")))
            if len(buf) >= BATCH * 20:
                written += _flush_bars(conn, buf); buf = []
    written += _flush_bars(conn, buf)
    hb.detail["bar_errors"] = errors
    return written


def _flush_bars(conn, rows):
    if not rows or dry():
        return 0
    with conn.cursor() as cur:
        cur.executemany("""insert into prices(ticker,d,open,high,low,close,adj_close,volume)
                           values (%s,%s,%s,%s,%s,%s,%s,%s)
                           on conflict (ticker,d) do update set
                             open=excluded.open, high=excluded.high, low=excluded.low,
                             close=excluded.close, adj_close=excluded.adj_close,
                             volume=excluded.volume, ingested_at=now()""", rows)
    conn.commit()
    return len(rows)


def backfill_dividends(conn, hb, names, since):
    """§2.6's trailing-12-month yield needs twelve months of payments. The per-ticker history keys
    the amount as `value`; the nightly bulk feed keys it as `dividend`. `v_dividend_ttm` reads both,
    so the ledger means one thing whichever job wrote the row."""
    written, errors = 0, {}

    def one(t):
        try:
            rows = get(f"div/{t}", hb.calls, tries=2, timeout=60, **{"from": since.isoformat()})
            return t, (rows if isinstance(rows, list) else []), None
        except Exception as e:
            return t, [], f"{type(e).__name__}: {e}"

    buf = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for t, rows, err in pool.map(one, names):
            if err:
                if len(errors) < 40:
                    errors[t] = err
                continue
            for r in rows:
                if r.get("date"):
                    buf.append((t, r["date"], "dividend", json.dumps(r, default=str)))
            if len(buf) >= BATCH:
                written += _flush_actions(conn, buf); buf = []
    written += _flush_actions(conn, buf)
    hb.detail["dividend_errors"] = errors
    return written


def _flush_actions(conn, rows):
    if not rows or dry():
        return 0
    with conn.cursor() as cur:
        cur.executemany("""insert into corporate_actions(ticker,d,kind,detail)
                           values (%s,%s,%s,%s::jsonb)
                           on conflict (ticker,d,kind) do update set detail=excluded.detail""", rows)
    conn.commit()
    return len(rows)


def backfill_fundamentals(conn, hb, names):
    """Re-serve the filing documents so `raw_doc` holds what the vendor actually sent (§4.1).

    This reuses the sweep's own extractor, so the derived fields are refreshed by the same code path
    that writes them nightly — there is no second definition of a fundamentals row in the system.
    """
    with conn.cursor() as cur:
        cur.execute("select ticker, currency from universe where kind='stock'")
        quote = {r[0]: r[1] for r in cur.fetchall()}

    def one(t):
        try:
            return t, get(f"fundamentals/{t}", hb.calls, tries=2, timeout=120), None
        except Exception as e:
            return t, None, f"{type(e).__name__}: {e}"

    errors, buf, done = {}, [], 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for t, doc, err in pool.map(one, names):
            if err or not isinstance(doc, dict):
                if len(errors) < 40:
                    errors[t] = err or "unexpected payload"
                continue
            try:
                row = fu.extract(t, doc, quote.get(t))
            except Exception as e:
                if len(errors) < 40:
                    errors[t] = f"extract {type(e).__name__}: {e}"
                continue
            if row is None:
                continue
            buf.append(row)
            if len(buf) >= 100:
                done += fu.flush(conn, buf, errors); buf = []
    done += fu.flush(conn, buf, errors)
    hb.detail["fundamentals_errors"] = errors
    return done


def main():
    since_bars = dt.date.today() - dt.timedelta(days=365 * YEARS)
    since_divs = dt.date.today() - dt.timedelta(days=400)
    with connect() as conn:
        with Heartbeat(conn, "backfill") as hb:
            with conn.cursor() as cur:
                names = targets(cur)

            # units per name: bars 1, dividends 1, fundamentals 10 (§4.1 — the vendor bills a
            # fundamentals request at ten)
            per_name = (1 if "bars" in WHAT else 0) + (1 if "dividends" in WHAT else 0) \
                       + (10 if "fundamentals" in WHAT else 0)
            afford = budget(hb, per_name)
            if len(names) > afford:
                hb.amber(f"quota allows {afford} of {len(names)} names today — truncated, re-run tomorrow")
                names = names[:afford]
            hb.detail.update(targets=len(names), what=sorted(WHAT), years=YEARS,
                             units_per_name=per_name)
            print(f"backfill: {len(names)} names · {sorted(WHAT)} · ~{len(names) * per_name} units")

            counts = {}
            if "bars" in WHAT:
                counts["bars"] = backfill_bars(conn, hb, names, since_bars)
                print(f"  bars: {counts['bars']} rows since {since_bars}")
            if "dividends" in WHAT:
                counts["dividends"] = backfill_dividends(conn, hb, names, since_divs)
                print(f"  dividends: {counts['dividends']} rows since {since_divs}")
            if "fundamentals" in WHAT:
                counts["fundamentals"] = backfill_fundamentals(conn, hb, names)
                print(f"  fundamentals: {counts['fundamentals']} filings")

            # whatever arrived, freeze the share counts it implies (§3.1)
            counts["effective_shares"] = fu.freeze_effective_shares(conn, names)

            hb.rows = sum(counts.values())
            hb.detail.update(written=counts)
            print(f"backfill: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
