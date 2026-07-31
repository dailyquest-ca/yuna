"""weekly-rank — the momentum brain (plan section 3.2, implemented verbatim).
Effective L0 (bar filters) -> M1 latch -> M2 template -> MCN (3x33%, windows end t-10)
-> L1-M top 150 -> base/pivot scan (M3 constraints) -> candidates + queue (cap 20).
"""
import os, sys, json, math, datetime as dt
import numpy as np
import psycopg

DRY = os.environ.get("DRY_RUN","false").lower() in ("1","true","yes")

def db_url():
    u=os.environ["DATABASE_URL"]
    return u + ("" if "sslmode" in u else ("&" if "?" in u else "?")+"sslmode=require")

def pct_rank(values):
    """Cross-sectional percentile 0..100 (NaN-safe: NaN stays NaN)."""
    v=np.asarray(values,dtype=float)
    out=np.full(v.shape,np.nan)
    ok=~np.isnan(v)
    if ok.sum()>1:
        order=v[ok].argsort().argsort().astype(float)
        out[ok]=100.0*order/(ok.sum()-1)
    elif ok.sum()==1:
        out[ok]=50.0
    return out

def weekly_closes(dates, closes):
    """Last trading day per ISO week -> (week_end_date, close)."""
    weeks={}
    for d,c in zip(dates,closes):
        key=d.isocalendar()[:2]
        if key not in weeks or d>weeks[key][0]: weeks[key]=(d,c)
    return sorted(weeks.values())

def compute_m1(cur):
    cur.execute("select d, close from prices where ticker='GSPC.INDX' order by d")
    rows=cur.fetchall()
    wk=weekly_closes([r[0] for r in rows],[float(r[1]) for r in rows])
    closes=np.array([c for _,c in wk]); dates=[d for d,_ in wk]
    if len(closes)<35: raise RuntimeError("not enough weekly history for M1")
    sma=np.convolve(closes,np.ones(30)/30,mode='valid')      # sma[i] ~ week i+29
    spx=closes[-1]; sma_now=sma[-1]; sma_4w=sma[-5]
    cur.execute("select state from gate_state order by id desc limit 1")
    prev=(cur.fetchone() or [None])[0]
    if prev is None:
        state="ON" if (spx>sma_now and sma_now>=sma_4w) else "OFF"
    elif prev=="ON":
        state="OFF" if spx<sma_now else "ON"                  # latch: only the opposite trigger flips
    else:
        state="ON" if (spx>sma_now and sma_now>=sma_4w) else "OFF"
    flipped = prev is not None and state!=prev
    return dict(week_end=dates[-1], state=state, spx=float(spx), sma=float(sma_now),
                sma4=float(sma_4w), flipped=flipped, prev=prev)

def base_scan(h,l,c):
    """v1 deterministic base detection under plan constraints:
    peak = highest high of the trailing 120 sessions; base = peak..today.
    valid if len>=25, depth<=25%, and price hasn't broken out past the pivot.
    pivot = highest high of the base (= peak). final-contraction low = min low of last 10."""
    look=min(len(h),120)
    hh=h[-look:]; ll=l[-look:]; cc=c[-look:]
    p=int(np.argmax(hh))
    pivot=float(hh[p]); seg_l=ll[p:]; seg_c=cc[p:]
    blen=len(seg_c)
    depth=(pivot-float(np.min(seg_l)))/pivot if blen else 1.0
    contraction_low=float(np.min(ll[-10:]))
    price=float(cc[-1])
    valid = blen>=25 and depth<=0.25 and price<=pivot*1.005
    return valid, pivot, blen, depth, contraction_low

def main():
    t10=10
    with psycopg.connect(db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("insert into runs(job,status,dry_run) values ('weekly-rank','running',%s) returning id",(DRY,))
            run_id=cur.fetchone()[0]; conn.commit()
        try:
            with conn.cursor() as cur:
                m1=compute_m1(cur)
                if not DRY:
                    cur.execute("insert into gate_state(week_end,state,spx_close,sma30,sma30_4w_ago,flipped) values (%s,%s,%s,%s,%s,%s)",
                                (m1["week_end"],m1["state"],m1["spx"],m1["sma"],m1["sma4"],m1["flipped"]))
                    conn.commit()
                # load bars for coarse-L0 + holdings (stocks only)
                cur.execute("""select p.ticker,p.d,p.high,p.low,p.close,p.adj_close,p.volume
                               from prices p join universe u on u.ticker=p.ticker
                               where u.kind='stock' and u.status='active' and (u.in_l0 or u.is_holding)
                               order by p.ticker,p.d""")
                data={}
                for t,d,hi,lo,cl,ac,vol in cur.fetchall():
                    data.setdefault(t,[]).append((d,hi,lo,cl,ac,vol))
                cur.execute("select ticker, industry, is_holding, in_l0 from universe where kind='stock' and status='active'")
                meta={r[0]:{"industry":r[1] or "Unknown","hold":r[2],"l0":r[3]} for r in cur.fetchall()}
            names=[]; feats={}
            for t,rows in data.items():
                d=[r[0] for r in rows]
                hi=np.array([r[1] for r in rows],float); lo=np.array([r[2] for r in rows],float)
                cl=np.array([r[3] for r in rows],float); ac=np.array([r[4] if r[4] is not None else r[3] for r in rows],float)
                vol=np.array([r[5] or 0 for r in rows],float)
                n=len(cl)
                # effective-L0 bar filters: listed>=6mo(126), price>=5, ADDV50 median >= $10M
                dollar=cl*vol
                addv=float(np.median(dollar[-50:])) if n>=50 else 0.0
                eff = meta[t]["l0"] and n>=126 and cl[-1]>=5 and addv>=10_000_000
                scoreable = n>=210
                feats[t]=dict(d=d,hi=hi,lo=lo,cl=cl,ac=ac,vol=vol,n=n,eff=eff,scoreable=scoreable)
                if (eff or meta[t]["hold"]): names.append(t)
            ranked=[t for t in names if feats[t]["eff"] and feats[t]["scoreable"]]
            # ---- MCN components (windows end t-10, adjusted closes for returns) ----
            mq_raw={}; sub_atr={}; sub_pull={}; sub_dry={}; sub_prox={}; grp_ret={}
            for t in ranked:
                f=feats[t]; ac=f["ac"][:-t10]; hi=f["hi"][:-t10]; lo=f["lo"][:-t10]; cl=f["cl"][:-t10]; vol=f["vol"][:-t10]
                # momentum quality: 90d exp regression of log price, annualized slope x R2 / 90d vol
                y=np.log(ac[-90:]); x=np.arange(90,dtype=float)
                slope,b=np.polyfit(x,y,1); yhat=slope*x+b
                ss_res=float(np.sum((y-yhat)**2)); ss_tot=float(np.sum((y-np.mean(y))**2)) or 1e-12
                r2=max(0.0,1-ss_res/ss_tot)
                rets=np.diff(np.log(ac[-91:])); vol90=float(np.std(rets)) or 1e-9
                mq_raw[t]=(slope*252.0)*r2/vol90
                # setup subs
                tr=np.maximum(hi[1:]-lo[1:],np.maximum(abs(hi[1:]-cl[:-1]),abs(lo[1:]-cl[:-1])))
                atr=np.convolve(tr,np.ones(14)/14,mode='valid')
                atr_hist=atr[-252:] if len(atr)>=252 else atr
                sub_atr[t]=100.0-100.0*float((atr_hist<=atr[-1]).mean())          # inverted own-percentile
                dd_recent=1-float(np.min(cl[-20:]))/float(np.max(cl[-20:]))
                dd_prior=1-float(np.min(cl[-40:-20]))/float(np.max(cl[-40:-20])) if len(cl)>=40 else dd_recent
                sub_pull[t]=dd_prior-dd_recent                                     # contraction (bigger=better)
                v50=float(np.mean(vol[-50:])) or 1e-9
                sub_dry[t]=-float(np.mean(vol[-10:]))/v50                          # dry-up (less volume = better)
                hi52=float(np.max(cl[-252:]))
                sub_prox[t]=float(cl[-1])/hi52
                grp_ret.setdefault(meta[t]["industry"],[]).append(float(ac[-1])/float(ac[-126]) - 1 if len(ac)>=126 else np.nan)
            grp_mean={g:float(np.nanmean(v)) for g,v in grp_ret.items()}
            gs=list(grp_mean); gp=pct_rank([grp_mean[g] for g in gs]); grp_pct=dict(zip(gs,gp))
            mq_p=dict(zip(ranked,pct_rank([mq_raw[t] for t in ranked])))
            a_p =dict(zip(ranked,[sub_atr[t] for t in ranked]))                    # already own-percentile
            p_p =dict(zip(ranked,pct_rank([sub_pull[t] for t in ranked])))
            d_p =dict(zip(ranked,pct_rank([sub_dry[t] for t in ranked])))
            x_p =dict(zip(ranked,pct_rank([sub_prox[t] for t in ranked])))
            out=[]
            for t in ranked:
                f=feats[t]; hi,lo,cl=f["hi"],f["lo"],f["cl"]
                # M2 at current price
                s50=float(np.mean(cl[-50:])); s150=float(np.mean(cl[-150:])); s200=float(np.mean(cl[-200:]))
                s200_21=float(np.mean(cl[-221:-21])) if f["n"]>=221 else s200
                lo52=float(np.min(cl[-252:])); hi52=float(np.max(cl[-252:])); px=float(cl[-1])
                m2 = (px>s150 and px>s200 and s150>s200 and s200>s200_21 and px>s50
                      and px>=lo52*1.30 and px>=hi52*0.75)
                setup=float(np.mean([a_p[t],p_p[t],d_p[t],x_p[t]]))
                mcn=float(np.mean([mq_p[t],setup,grp_pct[meta[t]["industry"]]]))
                valid,pivot,blen,depth,c_low=base_scan(hi,lo,cl)
                state="BUY" if (m2 and valid) else "WAIT"
                stop=max(c_low,pivot*0.92) if valid else None
                out.append(dict(t=t,mcn=mcn,mq=mq_p[t],setup=setup,grp=grp_pct[meta[t]["industry"]],m2=m2,
                                state=state,pivot=pivot if valid else None,blen=blen if valid else None,
                                depth=depth if valid else None,c_low=c_low if valid else None,stop=stop,px=px))
            l1m=sorted([o for o in out if o["m2"]],key=lambda o:-o["mcn"])[:150]
            for i,o in enumerate(l1m): o["rank"]=i+1
            # queue: holdings always + top-10 trigger-bearing L1-M by MCN; seats by proximity then score
            holds=[t for t in names if meta[t]["hold"]]
            trigged=[o for o in l1m if o["state"]=="BUY" and o["pivot"]]
            top10=sorted(trigged,key=lambda o:-o["mcn"])[:10]
            qrows=[]
            for t in holds:
                px=float(feats[t]["cl"][-1]) if t in feats and feats[t]["n"] else None
                qrows.append(dict(ticker=t,source="holding",state="HOLD",trig=None,lim=None,stop=None,prox=0.0,
                                  mcn=next((o["mcn"] for o in out if o["t"]==t),None),note="book"))
            for o in top10:
                lim=o["pivot"]*1.02; prox=abs(o["px"]-o["pivot"])/o["px"]
                qrows.append(dict(ticker=o["t"],source="momentum",state=o["state"],trig=o["pivot"],lim=lim,
                                  stop=o["stop"],prox=prox,mcn=o["mcn"],note=f"base {o['blen']}d/{o['depth']:.0%}"))
            qrows.sort(key=lambda r:(r["source"]!="holding", r["prox"] if r["prox"] is not None else 9, -(r["mcn"] or 0)))
            qrows=qrows[:20]
            if not DRY:
                with conn.cursor() as cur:
                    cur.execute("truncate candidates"); cur.execute("truncate queue")
                    cur.executemany("""insert into candidates(ticker,rank,mcn,mq,setup,grp,m2,m4,state,pivot,base_len,base_depth,base_low,stop_suggest,last_close)
                        values (%(t)s,%(rank)s,%(mcn)s,%(mq)s,%(setup)s,%(grp)s,%(m2)s,null,%(state)s,%(pivot)s,%(blen)s,%(depth)s,%(c_low)s,%(stop)s,%(px)s)""",
                        [{**o,"rank":o.get("rank")} for o in l1m])
                    cur.executemany("""insert into queue(ticker,rank,source,state,trigger_price,limit_price,stop_suggest,proximity,mcn,note)
                        values (%(ticker)s,%(rank)s,%(source)s,%(state)s,%(trig)s,%(lim)s,%(stop)s,%(prox)s,%(mcn)s,%(note)s)""",
                        [{**r,"rank":i+1} for i,r in enumerate(qrows)])
                conn.commit()
            detail=dict(gate=m1["state"],gate_flipped=m1["flipped"],eff_l0=len(ranked),l1m=len(l1m),
                        buy=len(trigged),queue=len(qrows),dry_run=DRY)
            with conn.cursor() as cur:
                cur.execute("update runs set finished_at=now(), status='green', calls_used=0, rows_written=%s, detail=%s where id=%s",
                            (0 if DRY else len(l1m)+len(qrows), json.dumps(detail), run_id))
            conn.commit()
            print(f"weekly-rank: green — gate {m1['state']} | effective L0 {len(ranked)} | L1-M {len(l1m)} | BUY {len(trigged)} | queue {len(qrows)}")
            return 0
        except Exception as e:
            with conn.cursor() as cur:
                cur.execute("update runs set finished_at=now(), status='red', detail=%s where id=%s",
                            (json.dumps({"fatal":f"{type(e).__name__}: {e}"}),run_id))
            conn.commit(); raise

if __name__=="__main__": sys.exit(main())
