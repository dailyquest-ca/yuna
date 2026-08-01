"""monthly-funnel — Stage 1 (L0 census). Cron runs weekly Sat; in-job guard keeps it to the 1st Sat.
Census: US exchange symbol list (common stock, NYSE/NASDAQ/AMEX) x screener (cap >= $300M, +industry).
Bar-dependent filters (price >= $5, ADDV >= $10M, listed >= 6 mo) are re-applied from our own bars
inside weekly-rank, so L0 stays honest between censuses. Stages 1.5 and 2 of the same workflow are
fundamentals.py (the sweep) and score.py (Gate C1 -> CCN -> hurdle -> bench).
FORCE=true skips the 1st-Saturday guard (manual runs)."""
import os, sys, json, time, traceback, datetime as dt, urllib.request, urllib.error
import psycopg
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from db import db_url, key

DRY = os.environ.get("DRY_RUN","false").lower() in ("1","true","yes")
FORCE = os.environ.get("FORCE","false").lower() in ("1","true","yes")
# The vendor key is read at CALL time via db.key(), never bound as a module constant here: as a
# constant it ran the moment anything imported funnel, so the integration suite could not even
# COLLECT without a secret it has no business holding, and CI had been red on it.


def get(url, calls, tries=3):
    for a in range(tries):
        calls[0]+=1
        try:
            with urllib.request.urlopen(url, timeout=90) as r: return json.load(r)
        except Exception:
            if a<tries-1: time.sleep(4*(a+1)); continue
            raise

def main():
    today = dt.date.today()
    if not FORCE and not (today.weekday()==5 and today.day<=7):
        print("not the 1st Saturday — census skipped"); return 0
    calls=[0]
    with psycopg.connect(db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("insert into runs(job,status,dry_run) values ('monthly-funnel','running',%s) returning id",(DRY,))
            run_id=cur.fetchone()[0]; conn.commit()
        try:
            # 1) listing census: common stocks on NYSE / NASDAQ / AMEX only
            syms = get(f"https://eodhd.com/api/exchange-symbol-list/US?api_token={key()}&fmt=json", calls)
            common = {s["Code"] for s in syms
                      if s.get("Type")=="Common Stock" and s.get("Exchange") in {"NYSE","NASDAQ","AMEX","NYSE MKT"}}
            print(f"listing census: {len(common)} common stocks on NYSE/NASDAQ/AMEX")
            # 1b) liquidity census: bulk last-day bars for the whole US tape (cheap)
            bulk = get(f"https://eodhd.com/api/eod-bulk-last-day/US?api_token={key()}&fmt=json", calls)
            liquid = {}
            for b in bulk:
                code=b.get("code"); px=float(b.get("close") or 0); vol=float(b.get("volume") or 0)
                if code in common and px>=4 and px*vol>=5_000_000:
                    liquid[code]=px
            print(f"liquidity census: {len(liquid)} names with price>=$4 and ~$5M day volume")
            # 2) screener sweep: cap >= $300M, descending, harvest industry/sector/cap
            rows={}
            ceiling=None            # screener offset caps at 999 -> descend in market-cap bands
            for sweep in range(30):
                added=0; prev_ceiling=ceiling
                for offset in range(0,1000,100):
                    f=[["exchange","=","us"]]
                    f.append(["market_capitalization","<",ceiling] if ceiling is not None
                             else ["market_capitalization",">",300000000])
                    filt=json.dumps(f)
                    data=get(f"https://eodhd.com/api/screener?api_token={key()}&sort=market_capitalization.desc&filters={urllib.request.quote(filt)}&limit=100&offset={offset}", calls)
                    batch=(data or {}).get("data",[])
                    if not batch: break
                    for b in batch:
                        code=b.get("code"); cap=float(b.get("market_capitalization") or 0)
                        if cap>0:                       # null caps must not poison the descent
                            ceiling = cap+1 if ceiling is None else min(ceiling, cap+1)
                        if cap>=300000000 and code in liquid and code not in rows:
                            rows[code]=(b.get("name"), b.get("sector"), b.get("industry"), cap)
                            added+=1
                    if len(batch)<100: break
                print(f"  sweep {sweep+1}: +{added} names, floor now ${(ceiling or 0)/1e9:.2f}B")
                if ceiling is not None and ceiling<=300000001: break
                if prev_ceiling is not None and ceiling is not None and ceiling>=prev_ceiling: break  # no progress
            print(f"screener decorations: {len(rows)} names carry cap/industry")
            for code in liquid:
                if code not in rows: rows[code]=(None,None,None,None)   # cap/industry arrive in Phase D
            # 3) upsert universe: coarse L0 membership
            if not DRY:
                with conn.cursor() as cur:
                    cur.execute("update universe set in_l0=false where kind='stock'")
                    # §3.0 / §3.3: delisted names are RETAINED, and marked. A name that was in the
                    # last census and is absent from this exchange listing has stopped trading; its
                    # bars stay, its status changes, and it keeps counting in every backtest. This
                    # is the survivorship bias that flatters every number we have — the two classic
                    # sins §4.8 names are using data before its filing date and forgetting the dead.
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
                    # COALESCE, not assignment. Line ~75 gives every liquid name the screener did
                    # not decorate a row of (None,None,None,None) — so a bare assignment wiped
                    # sector, industry and market cap off 2,108 of 2,762 L0 names every census, and
                    # only the handful re-swept that month got them back. The damage was silent and
                    # large: MCN's industry-group component scored a flat neutral 50 for ~76% of the
                    # field (one of three equal weights, constant), and §2.2's two-per-group cap
                    # filed every wiped name under the same 'unknown' bucket. A census that learns
                    # nothing new must not forget what it knew.
                    cur.executemany("""insert into universe(ticker,name,kind,exchange,currency,in_l0,sector,industry,market_cap_usd)
                        values (%s,%s,'stock','US','USD',true,%s,%s,%s)
                        on conflict (ticker) do update set name=coalesce(excluded.name,universe.name),
                          in_l0=true, sector=coalesce(excluded.sector,universe.sector),
                          industry=coalesce(excluded.industry,universe.industry),
                          market_cap_usd=coalesce(excluded.market_cap_usd,universe.market_cap_usd),
                          status='active'""",
                        [(c+".US", n, se, ind, cap) for c,(n,se,ind,cap) in rows.items()])
                conn.commit()
            with conn.cursor() as cur:
                cur.execute("update runs set finished_at=now(), status='green', calls_used=%s, rows_written=%s, detail=%s where id=%s",
                            (calls[0], 0 if DRY else len(rows), json.dumps({"stage":"census","listing":len(common),"cap_pass":len(rows)}), run_id))
            conn.commit()
            print(f"monthly-funnel: green — {len(rows)} coarse-L0 names, {calls[0]} calls")
            return 0
        except Exception as e:
            with conn.cursor() as cur:
                cur.execute("update runs set finished_at=now(), status='red', calls_used=%s, detail=%s where id=%s",
                            (calls[0], json.dumps({"fatal":f"{type(e).__name__}: {e}","trace":traceback.format_exc()[-900:]}), run_id))
            conn.commit(); raise

if __name__=="__main__": sys.exit(main())
