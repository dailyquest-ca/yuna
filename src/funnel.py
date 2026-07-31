"""monthly-funnel — Stage 1 (L0 census). Cron runs weekly Sat; in-job guard keeps it to the 1st Sat.
Census: US exchange symbol list (common stock, NYSE/NASDAQ/AMEX) x screener (cap >= $300M, +industry).
Bar-dependent filters (price >= $5, ADDV >= $10M, listed >= 6 mo) are re-applied from our own bars
inside weekly-rank, so L0 stays honest between censuses. Stage 2 (Gate C1 -> CCN funnel) arrives in Phase D.
FORCE=true skips the 1st-Saturday guard (manual runs)."""
import os, sys, json, time, traceback, datetime as dt, urllib.request, urllib.error
import psycopg

DRY = os.environ.get("DRY_RUN","false").lower() in ("1","true","yes")
FORCE = os.environ.get("FORCE","false").lower() in ("1","true","yes")
K = os.environ["EODHD_API_KEY"]

def db_url():
    u=os.environ["DATABASE_URL"]
    return u + ("" if "sslmode" in u else ("&" if "?" in u else "?")+"sslmode=require")

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
            syms = get(f"https://eodhd.com/api/exchange-symbol-list/US?api_token={K}&fmt=json", calls)
            ok_ex = {"NYSE","NASDAQ","AMEX","NYSE MKT","NYSE ARCA"}  # ARCA excluded below via type
    
            common = {s["Code"] for s in syms
                      if s.get("Type")=="Common Stock" and s.get("Exchange") in {"NYSE","NASDAQ","AMEX","NYSE MKT"}}
            print(f"listing census: {len(common)} common stocks on NYSE/NASDAQ/AMEX")
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
                    data=get(f"https://eodhd.com/api/screener?api_token={K}&sort=market_capitalization.desc&filters={urllib.request.quote(filt)}&limit=100&offset={offset}", calls)
                    batch=(data or {}).get("data",[])
                    if not batch: break
                    for b in batch:
                        code=b.get("code"); cap=float(b.get("market_capitalization") or 0)
                        if cap>0:                       # null caps must not poison the descent
                            ceiling = cap+1 if ceiling is None else min(ceiling, cap+1)
                        if cap>=300000000 and code in common and code not in rows:
                            rows[code]=(b.get("name"), b.get("sector") or "Unknown", b.get("industry") or "Unknown", cap)
                            added+=1
                    if len(batch)<100: break
                print(f"  sweep {sweep+1}: +{added} names, floor now ${(ceiling or 0)/1e9:.2f}B")
                if ceiling is not None and ceiling<=300000001: break
                if prev_ceiling is not None and ceiling is not None and ceiling>=prev_ceiling: break  # no progress
            print(f"screener census: {len(rows)} names >= $300M cap")
            # 3) upsert universe: coarse L0 membership
            if not DRY:
                with conn.cursor() as cur:
                    cur.execute("update universe set in_l0=false where kind='stock'")
                    cur.executemany("""insert into universe(ticker,name,kind,exchange,currency,in_l0,sector,industry,market_cap_usd)
                        values (%s,%s,'stock','US','USD',true,%s,%s,%s)
                        on conflict (ticker) do update set name=coalesce(excluded.name,universe.name),
                          in_l0=true, sector=excluded.sector, industry=excluded.industry,
                          market_cap_usd=excluded.market_cap_usd, status='active'""",
                        [(c+".US", n, se, ind, cap) for c,(n,se,ind,cap) in rows.items()])
                conn.commit()
            with conn.cursor() as cur:
                cur.execute("update runs set finished_at=now(), status='green', calls_used=%s, rows_written=%s, detail=%s where id=%s",
                            (calls[0], 0 if DRY else len(rows), json.dumps({"stage":"census","listing":len(common),"cap_pass":len(rows),"funnel":"awaiting Phase D"}), run_id))
            conn.commit()
            print(f"monthly-funnel: green — {len(rows)} coarse-L0 names, {calls[0]} calls")
            return 0
        except Exception as e:
            with conn.cursor() as cur:
                cur.execute("update runs set finished_at=now(), status='red', calls_used=%s, detail=%s where id=%s",
                            (calls[0], json.dumps({"fatal":f"{type(e).__name__}: {e}","trace":traceback.format_exc()[-900:]}), run_id))
            conn.commit(); raise

if __name__=="__main__": sys.exit(main())
