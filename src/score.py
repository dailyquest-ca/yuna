"""score — §4.2's second verb, and the one writer of every derived number in the system.

  Gate C1 -> CCN -> the fair multiple -> hurdles -> market gate -> group RS -> L1-M -> MCN ->
  queue re-rank -> triggers -> stops and trails -> the book revalued -> NAV -> arming.

A pure function of the database: it reads what `ingest` wrote and calls no vendor. Every number a
session reads was written here, which is only a true sentence while this remains the only job that
writes them — so the ranking half (`rank.py`) and the book half (`arming.py`) are libraries this
module drives, not jobs of their own.

Deviation, announced and awaiting ratification (roadmap Part 4): the hurdle's "fair multiple"
wants the stock's own 5-year median P/FCF. We hold a 3-year bar window, so the median is taken
over the quarters we can price. §3.1 sets the short-history rule at **fewer than 12 priced
quarters** — those names get fair = flat 25x, never the stock's own current multiple. The
threshold is config (`hurdle_fair_history_min_quarters`), so moving it is a logged row.
"""
import os, sys, json, math, statistics as st, datetime as dt
import psycopg
from db import chain_already_current, connect, config, dry, Heartbeat
import signals as sg
import rank
import arming

# §4.2: the Saturday appointment is this job in its weekly slot, not a separate one.
SCHEDULED_UTC = os.environ.get("SCHEDULED_UTC") or None

SIZE_BOUNDARY_DEFAULT = 10_000_000_000


def pct_rank(pairs):
    """[(key, value)] -> {key: percentile 0..100}; None values are skipped entirely."""
    got = [(k, v) for k, v in pairs if v is not None]
    if not got:
        return {}
    if len(got) == 1:
        return {got[0][0]: 50.0}
    got.sort(key=lambda kv: kv[1])
    n = len(got) - 1
    return {k: 100.0 * i / n for i, (k, v) in enumerate(got)}


def month_closes(cur, tickers):
    """{ticker: {YYYY-MM: last close of that month}} over our bar window."""
    cur.execute("""select distinct on (ticker, date_trunc('month', d))
                          ticker, to_char(d,'YYYY-MM') as m, close
                   from prices where ticker = any(%s)
                   order by ticker, date_trunc('month', d), d desc""", (tickers,))
    out = {}
    for t, m, c in cur.fetchall():
        out.setdefault(t, {})[m] = float(c)
    return out


FAIR_WINDOW_QUARTERS = 20        # §3.1: the stock's own *5-year* median P/FCF


def pfcf_history(raw, closes, window=FAIR_WINDOW_QUARTERS):
    """Median P/FCF over the quarters we can price, and the observation count.

    §3.1 says the FIVE-year median, so the window is bounded at both ends: the most recent 20
    priceable quarters, newest first. It was unbounded while the bar window held only three years,
    which made the bound invisible — with ten years stored it is the difference between "what this
    business has been worth lately" and an average across a whole cycle and a half.
    """
    obs = []
    for q in sorted((raw or {}).get("quarterly_fcf", []),
                    key=lambda q: str(q[0]) if q else "", reverse=True):
        try:
            qdate, ttm_fcf, shares = q[0], float(q[1]), float(q[2])
        except (TypeError, ValueError, IndexError):
            continue
        if ttm_fcf <= 0 or shares <= 0:
            continue
        px = closes.get(str(qdate)[:7])
        if px:
            obs.append(px * shares / ttm_fcf)
        if len(obs) >= window:
            break
    return (st.median(obs) if obs else None), len(obs)


def score_bench(conn, hb):
    """Gate C1 -> CCN -> the fair multiple -> the hurdle -> the bench (§3.1).

    Reads `v_fundamentals_latest` and `prices`; calls no API. Percentiles are cross-sectional
    within L0 at run time, exactly as §3.0 says, so scores move when the field moves.
    """
    with conn.cursor() as cur:
        boundary = float(config(cur, "small_large_boundary_usd", SIZE_BOUNDARY_DEFAULT))
        take = int(config(cur, "bench_cohort_take", 30))
        growth_cap = float(config(cur, "hurdle_growth_cap", 0.25))
        fair_cap = float(config(cur, "hurdle_fair_multiple_cap", 30))
        fair_cap_short = float(config(cur, "hurdle_fair_multiple_cap_short", 25))
        min_q = int(config(cur, "hurdle_fair_history_min_quarters", 12))
        floor = float(config(cur, "hurdle_min_return", 0.15))
        tol = float(config(cur, "engine_agreement_tolerance", 0.05))

        cur.execute("""select f.ticker, f.engine, f.cash_conversion, f.market_cap, f.shares_out,
                              f.fcf_ttm, f.c1_pass, f.c1_fail_reason, f.roic, f.reinvest_rate,
                              f.pfcf_current, f.data_confidence, f.goodwill_jump,
                              f.engine_agrees, f.revenue_cagr_3y, f.quote_ok, f.raw, u.is_holding,
                              f.growth_consistency, f.roic_worst_year, f.roic_years_reported,
                              f.effective_shares, f.cap_as_of,
                              f.fcf_ttm_reported, f.sbc_ttm, f.dwc_ttm
                       from v_fundamentals_latest f
                       join universe u on u.ticker=f.ticker
                       where u.kind='stock' and u.status='active' and (u.in_l0 or u.is_holding)""")
        rows = cur.fetchall()
        if not rows:
            hb.amber("no fundamentals yet — nothing to score")
            print("score/bench: fundamentals table empty; run the filings sweep first")
            return

        names = [r[0] for r in rows]
        closes = month_closes(cur, names)
        cur.execute("""select distinct on (ticker) ticker, close from prices
                       where ticker = any(%s) order by ticker, d desc""", (names,))
        last = {t: float(c) for t, c in cur.fetchall()}

    # ---- the engine waterfall, before any percentile (§3.1) ----
    # The percentile field has to be built from the value each name is actually SCORED on,
    # not from the raw computation — a measured 20% and a growth-derived 20% are the same
    # rank. Provenance travels with the value so the bench row and every memo can say which
    # it was, which §3.1 requires in words.
    final_engine, provenance = {}, {}
    for r in rows:
        tk, engine, rev_cagr = r[0], r[1], r[14]
        value, how = sg.engine_waterfall(engine, rev_cagr, tolerance=tol, cap=growth_cap)
        final_engine[tk], provenance[tk] = value, how

    # ---- percentiles across all of L0 (§3.0) ----
    eng_p = pct_rank([(tk, v) for tk, v in final_engine.items()])
    cc_p = pct_rank([(r[0], r[2]) for r in rows])
    # Durability: the ROIC floor is percentiled across L0, blended equally with growth
    # consistency (already 0-100), and the BLEND is percentiled again — that last step is
    # what makes this component an L0 percentile like the other two (§3.1).
    floor_p = pct_rank([(r[0], r[19]) for r in rows])
    blend = {}
    for r in rows:
        tk, gc = r[0], r[18]
        d = sg.durability(float(gc) if gc is not None else None, floor_p.get(tk))
        if d is not None:
            blend[tk] = d
    dur_p = pct_rank(list(blend.items()))

    out, unscored = [], []
    for (tk, engine, cc, mcap, shares, fcf, c1, c1why, roic, reinv,
         pfcf_cur, conf, gw_jump, agrees, rev_cagr, quote_ok, raw, is_hold,
         growth_cons, roic_worst, roic_years, eff_shares, cap_as_of,
         fcf_rep, sbc_ttm, dwc_ttm) in rows:
        px = last.get(tk)
        agrees = sg.engine_agrees(engine, rev_cagr, tolerance=tol)
        how = provenance[tk]

        components = dict(engine=eng_p.get(tk), cash_conv=cc_p.get(tk),
                          durability=dur_p.get(tk))
        scored = sg.ccn(components)
        if scored["score"] is None:
            # §3.1: no engine by either method, or under three reported ROIC years — the
            # plan makes both **not bench-eligible**, never silently scored on what remains.
            unscored.append(tk)
            continue
        ccn = scored["score"]
        confidence = scored["confidence"] if scored["confidence"] != "full" else conf

        # statements in one currency divided by a market cap in another is not a
        # multiple, it is a category error — so it produces no hurdle at all (§009)
        raw_d = {} if quote_ok is False else (raw if isinstance(raw, dict) else (json.loads(raw) if raw else {}))
        pfcf_med, obs = pfcf_history(raw_d, closes.get(tk, {}))
        # §3.1: the stock's own median, ceilinged — or the flat short-history multiple when
        # we cannot price enough quarters. One home for the rule (signals.fair_multiple_of);
        # a currency-mismatched name gets no multiple at all.
        fair = None if quote_ok is False else sg.fair_multiple_of(
            pfcf_med, obs, cap=fair_cap, short_cap=fair_cap_short, min_quarters=min_q)
        # The hurdle underwrites the same engine the CCN scores — the waterfall's value,
        # capped, whichever side of the identity it came from. Growth-derived names carry
        # §3.3's guardrails instead of a silent zero.
        # §3.1 (2026-08-02): growth is additionally capped at the rate the fair multiple
        # can support (0.15 − 1/fair). signals.hurdle_price applies the same clamp
        # internally; g is clamped here too so the STORED engine_growth is the growth the
        # hurdle actually used — verify re-derives the floor from the row's own numbers,
        # and a stored growth the solve ignored would flag every capped name.
        g = final_engine[tk] if final_engine[tk] is not None else 0.0
        ceil_g = sg.hurdle_growth_ceiling(fair) if fair else None
        if ceil_g is not None:
            g = min(g, ceil_g)
        # §3.1: effective shares are FROZEN at the filing — cap / the close on the cap's
        # `as_of` date, stored by the sweep. Re-deriving them from tonight's close made the
        # hurdle a function of the quote and it decayed every night.
        hp = sg.hurdle_price(fcf_ttm=fcf, shares=eff_shares, growth=g,
                             fair_multiple=fair, floor=floor) if eff_shares else None
        gap = ((px - hp) / hp) if px and hp else None

        out.append(dict(
            ticker=tk, ccn=ccn,
            # the engine percentile is stored as *used* — null when the cross-check
            # dropped it, so a reader can never mistake a 2-of-3 score for a full one
            engine=components["engine"], cash_conv=cc_p.get(tk),
            durability=dur_p.get(tk), engine_provenance=how,
            growth_consistency=float(growth_cons) if growth_cons is not None else None,
            roic_floor_pct=floor_p.get(tk), roic_years=roic_years,
            engine_used=final_engine[tk],
            # §5.5 owner-FCF disclosure: the three figures the memo must cite, on the row
            fcf_ttm_reported=float(fcf_rep) if fcf_rep is not None else None,
            sbc_share=(float(sbc_ttm) / float(fcf_rep)
                       if sbc_ttm is not None and fcf_rep and float(fcf_rep) > 0 else None),
            dwc_share=(float(dwc_ttm) / float(fcf_rep)
                       if dwc_ttm is not None and fcf_rep and float(fcf_rep) > 0 else None),
            engine_raw=engine, cash_conv_raw=cc, roic=roic, reinvest_rate=reinv,
            c1_pass=(c1 and quote_ok is True),
            # the reason belongs on the row that FAILED. The previous form kept it when the
            # gate passed (where it is always null) and threw it away when the gate failed,
            # so every C1 rejection reached the bench mute: AVGO's fundamentals row read
            # "net issuance 4.7%/yr" while its bench row read nothing at all. §3.1 requires
            # the gap to be named on the C2 memo, and a memo cannot name what was discarded.
            # §3.0's one-currency test, now that the conversion exists: a name is only unpriceable
            # when we do not know what currency it reports in, or hold no fiscal-period-end rate to
            # restate it with. "Reports in a foreign currency" stopped being a reason on 2026-08-07
            # — that is what the FX pass converts.
            c1_fail_reason=(None if c1 else c1why) if quote_ok is True else
                ((c1why + " · " if c1why else "") +
                 "statements and market cap are not in one currency — the statement currency is "
                 "unknown, or no fiscal-period-end FX rate was available to convert it (§3.0 "
                 "data-confidence path)"),
            cohort=("large" if (mcap or 0) >= boundary else "small"),
            # §3.1: "FCF yield = TTM FCF ÷ market cap at P" — and the cap at P uses the FROZEN
            # effective shares, so the yield stored beside last_close must be priced AT last_close.
            # fcf/mcap was the yield at the filing's as_of close wearing today's date: `check`
            # reconstructs FCF/share as fcf_yield x last_close, so every name whose quote had
            # drifted 0.5% off its as_of close flagged as a hurdle mismatch — 106 of them, 11
            # apparently overstated, on 2026-08-05. The vendor cap remains the fallback only
            # where the frozen share count never got derived.
            hurdle_price=hp,
            fcf_yield=(fcf / (eff_shares * px) if fcf and eff_shares and px
                       else (fcf / mcap if fcf and mcap else None)),
            engine_growth=g, fair_multiple=fair,
            derating_drag=(max(0.0, 1 - (fair / pfcf_cur) ** 0.2) if fair and pfcf_cur else None),
            last_close=px, gap_to_hurdle=gap,
            # §3.1: growth-derived names carry §3.3's guardrails — bottom of the band and
            # manual sign-off — so the flag must survive onto the row that sizes them.
            data_confidence=("flagged" if (how == "growth-derived" or quote_ok is False)
                             else confidence),
            serial_acquirer=bool(gw_jump),
            is_holding=is_hold))

    # ---- bench: top-N by CCN from each size cohort (§3.1) ----
    eligible = [o for o in out if o["c1_pass"]]
    bench = []
    for cohort in ("small", "large"):
        pool = sorted([o for o in eligible if o["cohort"] == cohort],
                      key=lambda o: -o["ccn"])[:take]
        bench.extend(pool)
    # holdings always carry a score, whether or not they make the bench
    held = [o for o in out if o["is_holding"] and o["ticker"] not in {b["ticker"] for b in bench}]
    bench.extend(held)
    bench.sort(key=lambda o: -o["ccn"])
    for i, o in enumerate(bench):
        o["rank"] = i + 1

    # §3.1's rank seatbelt keeps a name's ROW alive for two consecutive months outside the
    # top 60 — but the row has to carry that name's CURRENT numbers, not the ones it held
    # the month it was last ranked. Writing only the top 60 left 43 rows from the previous
    # scoring sitting in the table with their old CCNs and old ranks, so the bench displayed
    # two different laws at once and `v_bench` sorted them together. A re-score that leaves
    # half the table behind is not a re-score.
    #
    # So every still-scored name that already has a row is refreshed too — unranked, because
    # rank belongs to bench membership. Duplicate ranks become impossible by construction.
    ranked = {o["ticker"] for o in bench}
    with conn.cursor() as cur:
        cur.execute("select ticker from bench where ticker <> all(%s)", (sorted(ranked),))
        lingering = {r[0] for r in cur.fetchall()}
    unranked = [dict(o, rank=None) for o in out if o["ticker"] in lingering]
    writes = bench + unranked

    if not dry():
        with conn.cursor() as cur:
            # §3.1: gate failure evicts immediately — no two-month seatbelt. Without
            # this a name that later fails C1 keeps its stale row, and Phase 0 reads it
            # as a live candidate (Karooooo survived the currency gate exactly this way).
            failed = unscored + [o["ticker"] for o in out if not o["c1_pass"]]
            cur.execute("""delete from bench where ticker = any(%s)
                           and ticker not in (select ticker from universe where is_holding)""",
                        (failed,))
            cur.execute("""update bench set months_outside_top60 = months_outside_top60 + 1
                           where ticker <> all(%s)""", (sorted(ranked),))
            cur.execute("""update bench set months_outside_top60 = 0
                           where ticker = any(%s)""", (sorted(ranked),))
            cur.execute("""delete from bench where months_outside_top60 >= 2
                           and not approved and ticker not in
                             (select ticker from universe where is_holding)""")
            # A rebuilt bench orphans the queue's compounder seats: their hurdles, gaps and
            # CCNs were copied from bench rows that no longer exist, and nothing re-seats
            # them until Saturday's rank. ZM / VEON / HRMY sat in production quoting a
            # superseded bench for exactly this reason. Purge on rebuild; the weekly rank
            # re-seats whatever is still within 10% of a hurdle (§3.0 L2).
            cur.execute("delete from queue where source='compounder'")
            cur.executemany("""insert into bench(ticker,rank,cohort,ccn,engine,cash_conv,durability,
                    engine_provenance,growth_consistency,roic_floor_pct,roic_years,engine_used,
                    fcf_ttm_reported,sbc_share,dwc_share,
                    engine_raw,cash_conv_raw,roic,reinvest_rate,c1_pass,c1_fail_reason,
                    hurdle_price,fcf_yield,engine_growth,derating_drag,fair_multiple,
                    last_close,gap_to_hurdle,data_confidence,serial_acquirer,computed_at)
                  values (%(ticker)s,%(rank)s,%(cohort)s,%(ccn)s,%(engine)s,%(cash_conv)s,%(durability)s,
                    %(engine_provenance)s,%(growth_consistency)s,%(roic_floor_pct)s,%(roic_years)s,%(engine_used)s,
                    %(fcf_ttm_reported)s,%(sbc_share)s,%(dwc_share)s,
                    %(engine_raw)s,%(cash_conv_raw)s,%(roic)s,%(reinvest_rate)s,%(c1_pass)s,%(c1_fail_reason)s,
                    %(hurdle_price)s,%(fcf_yield)s,%(engine_growth)s,%(derating_drag)s,%(fair_multiple)s,
                    %(last_close)s,%(gap_to_hurdle)s,%(data_confidence)s,%(serial_acquirer)s,now())
                  on conflict (ticker) do update set rank=excluded.rank, cohort=excluded.cohort,
                    ccn=excluded.ccn, engine=excluded.engine, cash_conv=excluded.cash_conv,
                    durability=excluded.durability, engine_provenance=excluded.engine_provenance,
                    growth_consistency=excluded.growth_consistency,
                    roic_floor_pct=excluded.roic_floor_pct, roic_years=excluded.roic_years,
                    engine_used=excluded.engine_used,
                    fcf_ttm_reported=excluded.fcf_ttm_reported,
                    sbc_share=excluded.sbc_share, dwc_share=excluded.dwc_share,
                    engine_raw=excluded.engine_raw,
                    cash_conv_raw=excluded.cash_conv_raw, roic=excluded.roic,
                    reinvest_rate=excluded.reinvest_rate, c1_pass=excluded.c1_pass,
                    c1_fail_reason=excluded.c1_fail_reason, hurdle_price=excluded.hurdle_price,
                    fcf_yield=excluded.fcf_yield, engine_growth=excluded.engine_growth,
                    derating_drag=excluded.derating_drag, fair_multiple=excluded.fair_multiple,
                    last_close=excluded.last_close, gap_to_hurdle=excluded.gap_to_hurdle,
                    data_confidence=excluded.data_confidence, serial_acquirer=excluded.serial_acquirer,
                    computed_at=now()""", writes)
        conn.commit()

    buyable = [o["ticker"] for o in bench if o["gap_to_hurdle"] is not None and o["gap_to_hurdle"] <= 0]
    hb.rows = (hb.rows or 0) + len(bench)
    hb.detail.update(scored=len(out), unscored=len(unscored),
                     c1_pass=len(eligible), bench=len(bench),
                     buyable=len(buyable), buyable_names=buyable[:20],
                     flagged=sum(1 for o in out if o["data_confidence"] != "full"))
    print(f"score/bench: {len(out)} scored ({len(unscored)} unscorable) | C1 pass {len(eligible)} "
          f"| bench {len(bench)} | at-or-below hurdle {len(buyable)}")




def apply_rulings_to_bench(conn, hb):
    """§3.1's rulings law, written onto the rows the arming stage reads (WO-7, obs 97).

    Ruling 66 quarantined DLO's owner cash on 2026-08-06 — §3.1: *scored, ranked, watched, never
    ticketed* — and `bench.owner_fcf_suspect` went on reading false, because nothing in the system
    ever wrote it. The flag was legislated in migration 031 and left for a session to set by hand,
    which §4.0 does not allow: sessions judge, jobs compute, and a judgment the jobs never read is
    a judgment that did not happen.

    Five columns on `bench` used to be kept by hand and read by the machine — `c2_status`,
    `c2_memo`, `c2_confidence`, `approved`, `owner_fcf_suspect`. Every one is a copy of something
    already in `rulings`, and every one is destroyed the moment this job rebuilds that row, which
    it does whenever a name fails C1 for a quarter. A hand-kept copy of a ledger is a countdown.

    So all five are derived here, every run, in two plain sentences:

      * **A name is approved when the desk's most recent C2 verdict on it is a blind PASS.**
      * **A name is quarantined while a live quarantine ruling stands on it.**

    The two are deliberately separate questions, because the desk's own DLO ruling says they are:
    "QUARANTINE — owner-cash (§3.1) … **PASS/FAIL deferred to R5**". A card issuer can be a
    wonderful business and still report other people's money as free cash flow, which is why AXP,
    HQY, PCTY and SCHW sit quarantined today with a live PASS beside them. Reading both facts out
    of one verdict slot would have quietly un-quarantined all four.

    `blind` is load-bearing on the approval side. §3.1's whole rulings law is that the business
    verdict is recorded before price, gap or CCN is revealed — a verdict the number got to argue
    with does not open the gate.
    """
    if dry():
        return {}
    with conn.cursor() as cur:
        # §3.1: approved ⇔ the latest live c2 verdict is a blind PASS. Both directions, every run —
        # a withdrawal is as automatic as a grant, and the 12-month cooldown on a FAIL is simply
        # the absence of a newer PASS.
        cur.execute("""update bench b
                          set approved = coalesce(r.verdict_canon = 'pass' and r.blind, false),
                              approved_at = case
                                when coalesce(r.verdict_canon = 'pass' and r.blind, false)
                                then coalesce(b.approved_at, now()) else null end,
                              c2_status = coalesce(r.verdict_canon, 'pending'),
                              c2_confidence = r.confidence,
                              c2_memo = coalesce(r.memo, b.c2_memo)
                         from (select b2.ticker, r2.verdict_canon, r2.blind, r2.confidence, r2.memo
                                 from bench b2
                                 left join v_rulings_latest_c2 r2
                                        on r2.ticker = b2.ticker and r2.decides) r
                        where r.ticker = b.ticker
                          and (b.approved is distinct from
                               coalesce(r.verdict_canon = 'pass' and r.blind, false)
                            or b.c2_status is distinct from coalesce(r.verdict_canon, 'pending'))
                    returning b.ticker, b.approved""")
        approval = [dict(ticker=t, approved=a) for t, a in cur.fetchall()]
        # §3.1 owner-cash quarantine, from its own ledger (migration 036). Lifting one is a logged
        # reversal — §3.1's only route for overturning a verdict — so there is no second vocabulary.
        cur.execute("""update bench b
                          set owner_fcf_suspect = exists (select 1 from v_quarantine_live q
                                                           where q.ticker = b.ticker)
                        where b.owner_fcf_suspect is distinct from
                              exists (select 1 from v_quarantine_live q where q.ticker = b.ticker)
                    returning b.ticker, b.owner_fcf_suspect""")
        quarantine = [dict(ticker=t, quarantined=q) for t, q in cur.fetchall()]
    conn.commit()
    granted = sorted(a["ticker"] for a in approval if a["approved"])
    withdrawn = sorted(a["ticker"] for a in approval if not a["approved"])
    marked = sorted(q["ticker"] for q in quarantine if q["quarantined"])
    lifted = sorted(q["ticker"] for q in quarantine if not q["quarantined"])
    hb.detail["rulings_applied"] = dict(approved=granted, approval_withdrawn=withdrawn,
                                        quarantined=marked, quarantine_lifted=lifted)
    if approval or quarantine:
        print(f"score/rulings: approved {len(granted)}, withdrew {len(withdrawn)}, "
              f"quarantined {len(marked)}, lifted {len(lifted)}")
    return dict(approved=granted, withdrawn=withdrawn, quarantined=marked, lifted=lifted)


def main():
    """§4.2: the one writer of every derived number.

    Gate C1 -> CCN -> hurdles -> market gate -> group RS -> L1-M -> MCN -> queue -> triggers
    -> stops and trails -> the book revalued -> NAV -> arming. A session reads what this job
    wrote and nothing else, which is only true while this job is the only writer.

    Runs after every ingest; the Saturday 12:00 appointment is this job, not another one.
    """
    with connect() as conn:
        with Heartbeat(conn, "score", scheduled_utc=SCHEDULED_UTC) as hb:
            # §4.2 / WO-6: the 23:23 retry exits when the night is already green, and the chain
            # behind it should verify and exit for the same reason rather than recompute a world
            # that has not moved. `check` and `notify` still run — they are the verification, and
            # they write nothing but their own rows.
            if chain_already_current(conn, hb, "score"):
                return 0
            # Fills and splits first: everything below derives from the book, and a book that has
            # not digested last night's fills describes a portfolio we do not own (obs 116).
            arming.apply_ledger(conn, hb)
            score_bench(conn, hb)
            apply_rulings_to_bench(conn, hb)
            rank.run(conn, hb)
            # §4.1: prints `ingest` could not confirm tonight must not drive a sell.
            with conn.cursor() as cur:
                cur.execute("""select ticker from quarantine
                               where (status='held' and reason='move')
                                  or (status='cleared' and resolved_at::date = current_date)""")
                held = {r[0] for r in cur.fetchall()}
            arming.run(conn, hb, held=held, apply_ledger_first=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())