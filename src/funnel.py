"""ingest-universe — the L0 census. Fires weekly (Sat); rebuilds only if the month is unbuilt.

Census: US exchange symbol list (common stock, NYSE/NASDAQ/AMEX) x the bulk last-day tape (price
and dollar volume). §3.2 defines the universe as `.US` common stocks minus the delisted, and §4.5
names the exchange symbol lists and delisted lines as the data — so membership is this job's whole
mandate: who is listed, who is liquid, who has gone. §3.2's own price and ADDV floors are applied
nightly from our own bars inside the score, so L0 stays honest between censuses.

**The screener is gone (2026-09-13).** The census used to end with a sweep of the vendor's screener
to decorate each name with sector, industry and market cap. §4.5 names the product this system
runs on — EOD Historical Data, All World — and the screener is not in it: the vendor lists it under
All-In-One and EOD+Intraday All World Extended only. Zak completed the downgrade the roadmap asked
for, and the sweep answered `HTTP 403 Forbidden` on its first call, twice (2026-09-05, 09-12). Both
Saturdays the census died before writing a row, the Saturday `check` read the red as an ingest
failure and held the buys, and September's universe stayed unbuilt. Nothing on the schedule reads
the three columns — the engine loads every stock (`desk.TAPE`), ingest fetches every active
one, and sector, industry and market cap were the retired engine's — so the census carried a
dependency the plan had already cancelled (learning 63). The columns stay on `universe`, and the
upsert coalesces, so what the retired machine learned is never erased; it is simply never fetched.

**The guard is work-keyed, never date-keyed** (ruled 2026-08-05). It used to read "the 1st
Saturday" as `weekday==5 and day<=7`, and it read it BEFORE opening the runs row — so a firing that
missed the window skipped the month in silence and left no trace at all. This job had never once
produced a runs row and L0 had never been rebuilt. Now every firing writes its heartbeat and asks
one question instead: has this calendar month's universe been built? Unbuilt -> rebuild. Built ->
exit green, saying so. A missed Saturday is picked up the following week rather than lost.

FORCE=true rebuilds regardless (manual runs).

**Every firing also re-reads the duplicate-listing exclusions against the tape** (QC 2026-10-07,
A51). An exclusion is membership too, and §3.2 decides each one by a fact that can change after the
row is written: "keep the line still printing". Nothing else re-asks it — `dedupe_scan.py` guards
only the rows it proposes, and both it and `exchange_census.py` are dispatch-only — so a row that
keeps a dead line used to sit there for good: SGI.US was out of the universe for eight weeks behind
a row keeping TPX.US, a line with no bar since 2025-02-14. Read-only, no vendor call, amber only."""
import os, re, sys, json, time, urllib.request
import psycopg
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
import engine                                                             # noqa: E402
from db import db_url, key, Heartbeat, scheduled_run

DRY = os.environ.get("DRY_RUN","false").lower() in ("1","true","yes")
FORCE = os.environ.get("FORCE","false").lower() in ("1","true","yes")
# The vendor key is read at CALL time via db.key(), never bound as a module constant here: as a
# constant it ran the moment anything imported funnel, so the integration suite could not even
# COLLECT without a secret it has no business holding, and CI had been red on it.

LISTED_ON = {"NYSE", "NASDAQ", "AMEX", "NYSE MKT"}


def get(url, calls, tries=3):
    for a in range(tries):
        calls[0]+=1
        try:
            with urllib.request.urlopen(url, timeout=90) as r: return json.load(r)
        except Exception:
            if a<tries-1: time.sleep(4*(a+1)); continue
            raise

def month_built_at(cur):
    """The work key (ruled 2026-08-05): the timestamp of this calendar month's rebuild, or None if
    it is unbuilt.

    The ledger is the key. A rebuild is a run that finished and actually wrote rows, so a dry run,
    a crash and this job's own skip rows all leave the month unbuilt — which is the whole point:
    the guard asks whether the WORK happened, not whether a job ran on a particular date.

    Green or AMBER. The only amber this job writes is the exclusion re-check's, which is a finding
    about `universe_excluded` and says nothing against the rebuild beside it — counting only green
    would make a standing flag rebuild the universe every Saturday until Zak rules on it.
    """
    cur.execute("""select started_at from runs
                    where job = 'ingest-universe' and status in ('green', 'amber') and not dry_run
                      and coalesce(rows_written, 0) > 0
                      and date_trunc('month', started_at at time zone 'utc')
                          = date_trunc('month', now() at time zone 'utc')
                    order by id desc limit 1""")
    row = cur.fetchone()
    return row[0] if row else None


# How a `duplicate_listing` row names the line kept in its place. The table has no column for the
# keeper, so it lives in `detail`, and these are every phrasing the table holds: 041/050/056 by
# hand ("same series as", "share-class spelling of", "same company as"), the 2026-08-13 pass
# ("same series as", "pre-merger line of") and `dedupe_scan.py`'s writer ("same daily returns
# as"). The first `.US` symbol after the phrase is the keeper. A row in none of these shapes is not
# skipped: if its line prints, the re-check names it as a row it cannot read (see below).
KEPT_LINE = re.compile(r"(?:same series as|same daily returns as|share-class spelling of|"
                       r"same company as|pre-merger line of) ([A-Za-z0-9_.-]+?\.US)\b")


def kept_line(detail):
    """The line a duplicate-listing row says it keeps, or None when the row does not say."""
    m = KEPT_LINE.search(detail or "")
    return m.group(1) if m else None


def reverify_exclusions(cur):
    """§3.2, asked again of every duplicate-listing row: "keep the line still printing" (A51).

    Returns (session, rows, flags): the session the question was asked on, the (excluded, kept)
    pairs read, and one sentence per row that fails it. A row fails when its excluded line printed
    on the session and the line it keeps did not — the shape of 041's SGI.US row, which kept TPX.US
    eighteen months after TPX's last bar. A printing line whose row names no keeper fails too: the
    question cannot be asked of it, and that is said rather than passed over.

    No number is chosen. "Printing" is a bar ON the benchmark's newest session — the session the
    desk ranks, on the calendar `desk.load` takes from §3.6's regime source — so the test is the
    rule's own words, read on the night it would bite. A line that did not print cannot be the line
    still printing, so a dead excluded line is never flagged, whatever its keeper did: when neither
    line prints the clause does not reach the pair (056 says so of the `Q` continuations), and the
    both-dead rows (BBBY/BYON, CWEN-A/CWENA) stay quiet. Spelling twins that print side by side
    (GEFB/GEF-B) pass, because their keeper prints too.
    """
    cur.execute("select max(d) from prices where ticker = %s", (engine.REGIME_SOURCE,))
    session = cur.fetchone()[0]
    cur.execute("""select ticker, detail from universe_excluded
                    where reason = 'duplicate_listing' order by ticker""")
    rows = [(t, kept_line(detail)) for t, detail in cur.fetchall()]
    if not rows or session is None:
        return session, rows, []
    names = sorted({t for t, _ in rows} | {k for _, k in rows if k})
    # one index probe per line rather than a scan of `prices`: its newest bar, and whether it
    # carries one on the session
    cur.execute("""select t, (select max(d) from prices where ticker = t),
                          exists (select 1 from prices where ticker = t and d = %s)
                     from unnest(%s::text[]) as t""", (session, names))
    last, printed = {}, set()
    for t, newest, on_session in cur.fetchall():
        last[t] = newest
        if on_session:
            printed.add(t)
    flags = []
    for excluded, kept in rows:
        if excluded not in printed:
            continue
        if kept is None:
            flags.append(f"{excluded} printed on {session} and is excluded as a duplicate listing, "
                         f"but its row names no kept line the census can read — §3.2's 'keep the "
                         f"line still printing' cannot be checked")
        elif kept not in printed:
            flags.append(f"{excluded} printed on {session} and is excluded as a duplicate of "
                         f"{kept}, which did not (last bar {last.get(kept) or 'none'}) — §3.2 "
                         f"keeps the line still printing; the exclusion needs Zak's ruling")
    return session, rows, flags


def main():
    calls=[0]
    with psycopg.connect(db_url()) as conn:
        with Heartbeat(conn, "ingest-universe", dry_run=DRY, scheduled_utc="10:23") as hb:
            hb.calls = calls
            with conn.cursor() as cur:
                # Every firing, before the month guard: it reads the store and calls no vendor, so
                # a Saturday that rebuilds nothing still re-asks the question. AMBER and never red —
                # the census writes no price and its colour holds nothing (§5.6, 2026-09-13); the
                # flag is a defect report for a ruling, not a reason to stop the desk.
                session, rows, flags = reverify_exclusions(cur)
                hb.detail["exclusions"] = dict(session=str(session) if session else None,
                                               duplicate_listings=len(rows), flagged=len(flags))
                print(f"exclusions: {len(rows)} duplicate listings re-read against the {session} "
                      f"tape — {len(flags)} flagged")
                for why in flags:
                    print(f"  ⚠ {why}")
                    hb.amber(why)
                if rows and session is None:
                    hb.amber(f"no {engine.REGIME_SOURCE} bar on the tape — {len(rows)} "
                             f"duplicate-listing exclusions were not re-checked against §3.2")
                # a hand dispatch is never guarded (the guard is against a duplicate SCHEDULED
                # firing, never against a person — see db.scheduled_run)
                built = month_built_at(cur) if scheduled_run() and not FORCE else None
            if built:
                # exits clean, and says which run did the work — a silent skip is what hid this
                # job's absence for a month
                hb.detail.update(stage="guard", rebuilt=False, month_built_at=str(built))
                print(f"ingest-universe: the month's universe was built {built}; nothing to "
                      f"rebuild")
                return 0
            hb.detail["stage"] = "census"
            hb.rows = census(conn, hb, calls)
            print(f"ingest-universe: {hb.rows} coarse-L0 names, {calls[0]} calls")
    return 0


def census(conn, hb, calls):
        # 1) listing census: common stocks on NYSE / NASDAQ / AMEX only, with the vendor's name
        syms = get(f"https://eodhd.com/api/exchange-symbol-list/US?api_token={key()}&fmt=json", calls)
        common = {s["Code"]: s.get("Name") for s in syms
                  if s.get("Type")=="Common Stock" and s.get("Exchange") in LISTED_ON}
        print(f"listing census: {len(common)} common stocks on NYSE/NASDAQ/AMEX")
        # 2) liquidity census: bulk last-day bars for the whole US tape — one call, and the last
        #    call the census makes. Two calls a census, three retries each, and that is the whole
        #    vendor budget of the job.
        bulk = get(f"https://eodhd.com/api/eod-bulk-last-day/US?api_token={key()}&fmt=json", calls)
        # Admission floors of record (§5.6, ratified 2026-09-13): close ≥ $4 and ≥ $5M traded on
        # the census day. Looser than §3.2's $5 / $10M on purpose — these decide only whether a
        # newly listed name gets a `universe` row at all, and one day's volume is a noisier test
        # than §3.2's 50-session median, which the nightly screen applies from our own bars. On
        # the data (2026-09-13): 2 of the 18 names the live engine had ever ranked top-12 (AXTI,
        # MXL) printed days under $10M in the prior year; §3.2's numbers on a census day would have
        # kept them out, so the looser floors stand.
        liquid = {}
        for b in bulk:
            code=b.get("code"); px=float(b.get("close") or 0); vol=float(b.get("volume") or 0)
            if code in common and px>=4 and px*vol>=5_000_000:
                liquid[code]=px
        print(f"liquidity census: {len(liquid)} names with price>=$4 and ~$5M day volume")
        # 3) upsert universe: coarse L0 membership
        if not DRY:
            with conn.cursor() as cur:
                cur.execute("update universe set in_l0=false where kind='stock'")
                # §3.0 / §3.3: delisted names are RETAINED, and marked. A name that was in the
                # last census and is absent from this exchange listing has stopped trading; its
                # bars stay, its status changes, and it keeps counting in every backtest. This
                # is the survivorship bias that flatters every number we have — the two classic
                # sins are using data before its filing date and forgetting the dead.
                cur.execute("""update universe set status='delisted',
                                 delisted_at = coalesce(delisted_at, current_date),
                                 note = coalesce(note,'') ||
                                   case when note is null then '' else ' · ' end ||
                                   'absent from the ' || current_date || ' exchange listing'
                               where kind='stock' and status='active'
                                 and not is_holding
                                 and ticker like '%%.US'
                                 and ticker <> all(%s)""",
                            ([c + ".US" for c in common],))
                # COALESCE, not assignment. Sector, industry and market cap arrive from nowhere
                # now (see the module docstring) and every row below carries None for them — so a
                # bare assignment would wipe all three off every L0 name each census. It did
                # exactly that once, when only the handful the screener re-swept that month got
                # them back: MCN's industry-group component scored a flat neutral 50 for ~76% of
                # the field, and the retired engine's two-per-group cap filed every wiped name under 'unknown'.
                # A census that learns nothing new must not forget what it knew.
                cur.executemany("""insert into universe(ticker,name,kind,exchange,currency,in_l0,sector,industry,market_cap_usd)
                    values (%s,%s,'stock','US','USD',true,%s,%s,%s)
                    on conflict (ticker) do update set name=coalesce(excluded.name,universe.name),
                      in_l0=true, sector=coalesce(excluded.sector,universe.sector),
                      industry=coalesce(excluded.industry,universe.industry),
                      market_cap_usd=coalesce(excluded.market_cap_usd,universe.market_cap_usd),
                      status='active'""",
                    [(c+".US", common.get(c), None, None, None) for c in liquid])
            conn.commit()
        hb.detail.update(rebuilt=True, listing=len(common), liquid=len(liquid))
        return len(liquid)


if __name__=="__main__": sys.exit(main())
