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
  * **The delisted census** (added 2026-08-10). §3.3 says "delisted names retained in the universe"
    and the universe held two of them, so every backtest to date measured the companies that
    survived. The nightly cannot produce this retroactively either: a name that stopped trading in
    2019 will never appear in a listings sweep run today.

Per-ticker history calls are the §4.1 cold-start exception, not the routine. Budget is metered
against the vendor's own usage endpoint before spending, and the run truncates rather than dying
two-thirds through — the same discipline the fundamentals sweep learned the hard way.

    WHAT=bars,dividends,fundamentals   which passes to run (default all three)
    WHAT=delisted                      the dead census + their bars, screened to L0's own floor
    YEARS=10                           bar depth
    TICKERS=A.US,B.US                  limit the target set
    SWEEP_LIMIT=200                    largest N by market cap
    DELISTED_ONLY=true                 target the dead census (their filings, for M4)
"""
import os, sys, json, datetime as dt
import numpy as np
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from db import connect, dry, get, wal_bytes, wait_for_wal, Heartbeat
import fundamentals as fu

WORKERS = int(os.environ.get("WORKERS", "8"))
YEARS = int(os.environ.get("YEARS", "10"))
RESERVE = int(os.environ.get("QUOTA_RESERVE", "3000"))
SWEEP_LIMIT = int(os.environ.get("SWEEP_LIMIT", "0"))
WHAT = {w.strip() for w in os.environ.get("WHAT", "bars,dividends,fundamentals").split(",") if w.strip()}
BATCH = 500
# §4.1 tooling discipline, added after the 2026-08-03 outage: a bulk writer must pace itself.
# The database was under 1 GB when it died; what filled the volume was pg_wal, generated faster
# than checkpoints could recycle it. Pause when the WAL directory passes this, and stop cleanly
# rather than run the disk to zero — a truncated backfill is resumable, a dead database is not.
WAL_CEILING = int(os.environ.get("WAL_CEILING_MB", "1500")) * 1024 * 1024
WAL_MAX_WAIT = int(os.environ.get("WAL_MAX_WAIT_S", "180"))
RESWEEP = os.environ.get("RESWEEP", "false").lower() in ("1", "true", "yes")
DELISTED_ONLY = os.environ.get("DELISTED_ONLY", "false").lower() in ("1", "true", "yes")
# WO-A9: the window the delisted census is screened FOR, quarterly-probed. Blank keeps the original
# behaviour — fetch every name in the census and screen it from its own history.
PROBE_FROM = os.environ.get("PROBE_FROM", "").strip()
PROBE_TO = os.environ.get("PROBE_TO", "").strip()


def targets(cur, since=None):
    """The names to deepen, largest first — minus the ones already deep enough.

    Resumability matters more than it looks. The 2026-08-03 run died two thirds of the way in and
    a naive re-run would have rewritten the 923 names it had finished, generating the same WAL
    burst that killed it. Skipping them makes the retry strictly smaller than the attempt.
    """
    only = [t.strip() for t in os.environ.get("TICKERS", "").split(",") if t.strip()]
    if only:
        return only
    if DELISTED_ONLY:
        # The other half of the survivorship fix. The delisted pass stored bars but no filings, so
        # M4 is unknown for all 2,031 of them — and an unknown M4 is not a pass, so not one of them
        # could ever be entered. The dead were in the census and still unbuyable, which corrects the
        # ranking pool and leaves the bias that matters untouched.
        cur.execute("""select u.ticker from universe u
                        where u.kind='stock' and u.status='delisted'
                          and not exists (select 1 from fundamentals f where f.ticker = u.ticker)
                        order by u.ticker""")
        dead = [r[0] for r in cur.fetchall()]
        return dead[:SWEEP_LIMIT] if SWEEP_LIMIT else dead
    cur.execute("""select ticker from universe
                   where kind='stock' and (in_l0 or is_holding)
                   order by market_cap_usd desc nulls last""")
    got = [r[0] for r in cur.fetchall()]
    if since is not None and not RESWEEP:
        cur.execute("""select ticker from prices where d <= %s group by ticker""",
                    (since + dt.timedelta(days=40),))
        deep = {r[0] for r in cur.fetchall()}
        got = [t for t in got if t not in deep]
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
                if not wait_for_wal(conn, ceiling_bytes=WAL_CEILING, max_wait_s=WAL_MAX_WAIT):
                    with conn.cursor() as cur:
                        stuck = wal_bytes(cur)
                    hb.amber(f"stopped early: pg_wal held {stuck / 1e9:.1f} GB after waiting "
                             f"{WAL_MAX_WAIT}s for checkpoints. {written} bars written and "
                             f"committed; re-run to continue from here.")
                    hb.detail["stopped_on_wal_pressure"] = dict(
                        wal_bytes=stuck, ceiling=WAL_CEILING, written=written)
                    break
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


def census_delisted(conn, hb, exchange="US"):
    """Every US common stock that has stopped trading — the half of the tape we never stored.

    §3.3 says "Delisted names retained in the universe" and the census held **two** of them, so
    every backtest ran on the companies that survived. Momentum buys names printing new highs and
    a fraction of those crash and delist; testing on survivors deletes that tail from the sample
    and flatters every number. One vendor call returns the list.
    """
    rows = get(f"exchange-symbol-list/{exchange}", hb.calls, tries=2, timeout=240, delisted=1)
    out = []
    for r in rows if isinstance(rows, list) else []:
        code, kind = r.get("Code"), (r.get("Type") or "")
        if not code or kind != "Common Stock":
            continue                       # ETFs, funds, preferreds and notes are not L0 (§3.0)
        out.append((f"{code}.{exchange}", r.get("Name"), r.get("Currency") or "USD"))
    hb.detail["delisted_census"] = len(out)
    return out


def probe_dates(lo, hi, every_days=89):
    """Roughly-quarterly probes across the window, snapped off weekends.

    `every_days` is deliberately NOT a multiple of seven. At 91 — the obvious "13 weeks" — every
    probe lands on the same weekday as the start, and 2006-01-01 is a Sunday: all 34 probes would
    have queried a day the market was shut and the union would have come back empty, silently.
    89 drifts the weekday, and the weekend snap catches the rest. A probe that still lands on a
    holiday returns nothing and is visible as a zero in the heartbeat's `probe` map.
    """
    a, b = dt.date.fromisoformat(lo), dt.date.fromisoformat(hi)
    out, d = [], a
    while d <= b:
        s = d + dt.timedelta(days=(7 - d.weekday()) if d.weekday() >= 5 else 0)
        if s <= b and (not out or s != out[-1]):
            out.append(s)
        d += dt.timedelta(days=every_days)
    if out and out[-1] != b:
        last = b - dt.timedelta(days=max(0, b.weekday() - 4))
        if last != out[-1]:
            out.append(last)
    return out


def liquid_in_window(hb, lo, hi, min_dollar=10_000_000.0, min_price=5.0):
    """Which tickers were ever liquid enough for L0 between `lo` and `hi` — from BULK bars.

    The delisted census is the whole graveyard — **32,611 US common stocks**, most of them dead
    penny listings from decades before this window. Fetching each one's history to discard 97% of
    them costs the better part of a day, and because only the KEPT names are written to `universe`
    a re-run repeats nearly all of it: the pass is not meaningfully resumable at that scale. Run
    388 proved it, managing 88 names in three minutes before the WAL guard stopped it.

    The bulk endpoint answers the same question one date at a time instead of one name at a time.
    `eod-bulk-last-day` returns every US ticker's close and volume for a single session — delisted
    names included, because on that date they were still trading — so a quarterly probe across the
    window costs ~33 calls and returns the union of everything that ever cleared the floor.

    **The approximation is stated rather than hidden:** a name liquid only BETWEEN two probes is
    missed. At a $10M floor that is a name whose entire liquid life was under a quarter, which the
    210-bar minimum would have excluded from L0 anyway. Erring the other way — a name liquid on one
    probe date and nowhere else — is harmless, since it is only admitted to the fetch list and its
    own history is still screened by the caller.
    """
    keep = set()
    for d in probe_dates(lo, hi):
        try:
            rows = get("eod-bulk-last-day/US", hb.calls, tries=2, timeout=240,
                       date=d.isoformat())
        except Exception as e:
            hb.detail.setdefault("probe_errors", {})[d.isoformat()] = f"{type(e).__name__}: {e}"
            continue
        n = 0
        for r in rows if isinstance(rows, list) else []:
            code, close, vol = r.get("code"), r.get("close"), r.get("volume")
            if not code or close is None or vol is None:
                continue
            try:
                c, v = float(close), float(vol)
            except (TypeError, ValueError):
                continue
            if c >= min_price and c * v >= min_dollar:
                keep.add(f"{code}.US")
                n += 1
        hb.detail.setdefault("probe", {})[d.isoformat()] = n
    hb.detail["probe_union"] = len(keep)
    print(f"  probe {lo}..{hi}: {len(keep)} names ever cleared "
          f"${min_dollar:,.0f}/day at a probe date")
    return keep


def backfill_delisted(conn, hb, since, min_addv=10_000_000.0, min_price=5.0, min_bars=210):
    """Bars for the dead — but only for the dead that could ever have been L0.

    Storage is the constraint, not quota: ten years for every delisted ticker would be tens of
    millions of rows for companies §3.0's liquidity floor would never have let us buy. So each
    name's history is fetched, screened in memory against the same floor L0 applies — 210 sessions,
    a $5 price and a 50-session median dollar volume of $10M, at any point in its life — and only
    the qualifiers are stored. The rest are counted and dropped, so the discard is a number in the
    heartbeat rather than a silent omission.

    Written with `status='delisted'` and `in_l0=false`: the backtest's census is rebuilt from bars
    at each date, so a dead name is in the universe until the day its bars stop and out of it after
    — which is what "retained" has to mean for a point-in-time test.
    """
    census = census_delisted(conn, hb)
    with conn.cursor() as cur:
        cur.execute("select ticker from universe")
        known = {r[0] for r in cur.fetchall()}
    todo = [(t, n, c) for t, n, c in census if t not in known]
    # WO-A9: screen the graveyard to the window BEFORE spending a call per name. Without this the
    # pass is 32,611 fetches to keep a few thousand, and since only the keepers are recorded a
    # re-run repeats it. With it the fetch list is what could actually have been bought.
    if PROBE_FROM and PROBE_TO:
        liquid = liquid_in_window(hb, PROBE_FROM, PROBE_TO, min_addv, min_price)
        before = len(todo)
        todo = [e for e in todo if e[0] in liquid]
        hb.detail.update(probe_window=f"{PROBE_FROM}..{PROBE_TO}",
                         census_before_probe=before, census_after_probe=len(todo))
        print(f"  census {before} -> {len(todo)} after the liquidity probe")
    afford = budget(hb, 1)
    if len(todo) > afford:
        hb.amber(f"quota allows {afford} of {len(todo)} delisted names today — re-run to continue")
        todo = todo[:afford]

    def one(entry):
        t, name, ccy = entry
        try:
            rows = get(f"eod/{t}", hb.calls, tries=2, timeout=120,
                       **{"from": since.isoformat(), "period": "d"})
            return entry, (rows if isinstance(rows, list) else []), None
        except Exception as e:
            return entry, [], f"{type(e).__name__}: {e}"

    kept, dropped, written, errors = 0, 0, 0, {}
    buf, rows_to_add = [], []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for entry, rows, err in pool.map(one, todo):
            t, name, ccy = entry
            if err:
                if len(errors) < 40:
                    errors[t] = err
                continue
            bars = [b for b in rows if b.get("date") and b.get("close") is not None]
            if len(bars) < min_bars:
                dropped += 1
                continue
            close = np.array([float(b["close"]) for b in bars])
            vol = np.array([float(b.get("volume") or 0) for b in bars])
            dollar = close * vol
            # the best 50-session stretch it ever had — err toward keeping
            best = max((float(np.median(dollar[i:i + 50])) for i in range(0, len(dollar) - 49, 10)),
                       default=0.0)
            if best < min_addv or float(np.nanmax(close)) < min_price:
                dropped += 1
                continue
            kept += 1
            rows_to_add.append((t, name, ccy))
            for b in bars:
                buf.append((t, b["date"], b.get("open"), b.get("high"), b.get("low"),
                            b.get("close"), b.get("adjusted_close"), b.get("volume")))
            if len(buf) >= BATCH * 20:
                written += _flush_delisted(conn, rows_to_add, buf)
                rows_to_add, buf = [], []
                if not wait_for_wal(conn, ceiling_bytes=WAL_CEILING, max_wait_s=WAL_MAX_WAIT):
                    hb.amber(f"stopped early on WAL pressure; {written} bars committed, re-run "
                             f"to continue — the census skips what is already stored")
                    break
    written += _flush_delisted(conn, rows_to_add, buf)
    hb.detail.update(delisted_kept=kept, delisted_dropped_illiquid=dropped,
                     delisted_errors=errors)
    print(f"  delisted: {kept} kept, {dropped} never liquid enough for L0, {written} bars")
    return written


def _flush_delisted(conn, universe_rows, bars):
    """Universe rows first — `prices.ticker` is a foreign key, so the name must exist to hold bars."""
    if dry() or not universe_rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany("""insert into universe(ticker,name,kind,exchange,currency,status,in_l0,note)
                           values (%s,%s,'stock','US',%s,'delisted',false,
                                   'delisted census — §3.3 retains the dead so the backtest is not
                                    measured on survivors only')
                           on conflict (ticker) do nothing""", universe_rows)
    conn.commit()
    return _flush_bars(conn, bars)


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
                names = targets(cur, since_bars if "bars" in WHAT else None)

            # units per name: bars 1, dividends 1, fundamentals 10 (§4.1 — the vendor bills a
            # fundamentals request at ten)
            per_name = (1 if "bars" in WHAT else 0) + (1 if "dividends" in WHAT else 0) \
                       + (10 if "fundamentals" in WHAT else 0)
            if WHAT == {"delisted"}:
                names, per_name = [], 0        # the delisted pass builds its own target list
            afford = budget(hb, per_name)
            if len(names) > afford:
                hb.amber(f"quota allows {afford} of {len(names)} names today — truncated, re-run tomorrow")
                names = names[:afford]
            hb.detail.update(targets=len(names), what=sorted(WHAT), years=YEARS,
                             units_per_name=per_name)
            print(f"backfill: {len(names)} names · {sorted(WHAT)} · ~{len(names) * per_name} units")

            counts = {}
            if "delisted" in WHAT:
                counts["delisted"] = backfill_delisted(conn, hb, since_bars)
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
