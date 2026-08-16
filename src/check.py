"""check — §4.2's third verb: prove it is safe to speak, then say so and write nothing else.

Runs after every `score` and at every session dispatch. It answers "is this number real" rather
than "did the job run" — green is not a result, every serious defect in this build shipped green,
and the habit that actually worked was cross-checking the model's output against an independent
computation on the raw data.

**It writes nothing but its own report row.** That is the law (§4.2, 2026-08-02) and it is also
what makes the answer trustworthy: a checker that can edit the thing it checks is a participant,
not a witness. Every finding lands in the `runs` row, where the sessions read it — ambers print at
the top of the brief, and a red blocks the dispatch entirely.

What it checks, per §3.1 and §3.0:

  1. every stored hurdle re-derives from its own stored components — the 15%-floor solve
     capped at the fair multiple
  2. gap_to_hurdle agrees with the last_close and hurdle_price beside it
  3. the CCN equals the mean of the component percentiles actually stored on the row
  4. what carries each top score — reported, so a bench topped by names with no measurable
     compounding engine cannot pass unnoticed
  5. every bench name resolves to exactly one fundamentals row
  6. the pre-flight: gate, offerable count against the caps, start-low, protective orders
     outstanding, and how much of the book carries a confirmed share count (§4.5 step 5)
"""
import datetime as dt
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from db import connect, config, config_digest, dry, freshness, get, Heartbeat
import signals as sg

HURDLE_TOLERANCE = 0.005      # half a percent of price between stored and re-derived hurdle
GAP_TOLERANCE = 1e-4
CCN_TOLERANCE = 0.05

# The checks whose failure means a session must not speak (§4.2). Deliberately short: each one
# says a published number cannot be rebuilt from the row it sits on, which makes every conclusion
# drawn from it unsafe. Everything else is reported loudly and lets the desk open.
BLOCKING = {"hurdle_reproduces_floor", "gap_matches_close_and_hurdle",
            "ccn_is_mean_of_components", "hurdle_is_price_invariant",
            "one_fundamentals_row_per_bench_name"}


def check_hurdles(cur, floor):
    """§3.1: the hurdle is min(the highest price whose expected return clears the floor,
    fair multiple x FCF/share). Re-run the one solver on the row's own numbers; the stored
    hurdle must come back. When the fair-multiple cap binds, the ER at the stored hurdle sits
    lawfully ABOVE the floor — cheaper than required is never a defect, dearer always is.

    The market cap cancels out of the arithmetic — only FCF per share, growth and the fair multiple
    matter — which is what makes this independent of whichever cap the vendor served."""
    cur.execute("""select ticker, hurdle_price, last_close, fcf_yield, engine_growth, fair_multiple
                   from bench
                   where hurdle_price is not null and last_close is not null
                     and fcf_yield is not null and fair_multiple is not null""")
    bad = []
    for ticker, hurdle, px, yield_, growth, fair in cur.fetchall():
        hurdle, px, yield_ = float(hurdle), float(px), float(yield_)
        growth, fair = float(growth or 0), float(fair)
        if px <= 0 or yield_ <= 0 or fair <= 0:
            continue
        implied = sg.hurdle_price(fcf_ttm=yield_ * px, shares=1.0, growth=growth,
                                  fair_multiple=fair, floor=floor)
        if implied is None or implied <= 0 or abs(hurdle / implied - 1) > HURDLE_TOLERANCE:
            er = sg.expected_return(hurdle, fcf_ttm=yield_ * px, shares=1.0, growth=growth,
                                    fair_multiple=fair)
            bad.append(dict(ticker=ticker, stored_hurdle=round(hurdle, 2),
                            er_at_stored=round(er, 4) if er is not None else None,
                            hurdle_that_clears_the_floor=round(implied, 2) if implied else None,
                            overstated_by=(round(hurdle / implied - 1, 4) if implied else None)))
    return bad


def check_gaps(cur):
    cur.execute("""select ticker, gap_to_hurdle, last_close, hurdle_price from bench
                   where gap_to_hurdle is not null and hurdle_price is not null
                     and last_close is not null and hurdle_price <> 0""")
    return [dict(ticker=t, stored=round(float(g), 5),
                 computed=round((float(px) - float(h)) / float(h), 5))
            for t, g, px, h in cur.fetchall()
            if abs(float(g) - (float(px) - float(h)) / float(h)) > GAP_TOLERANCE]


def check_ccn(cur):
    """The CCN must be the mean of the percentiles the row actually stores (§3.1, §3.3)."""
    cur.execute("""select ticker, ccn, engine, cash_conv, durability, data_confidence
                   from bench where ccn is not null""")
    bad = []
    for ticker, ccn, eng, cc, dur, conf in cur.fetchall():
        parts = [float(x) for x in (eng, cc, dur) if x is not None]
        if not parts:
            continue
        expect = sum(parts) / len(parts)
        if abs(float(ccn) - expect) > CCN_TOLERANCE:
            bad.append(dict(ticker=ticker, stored_ccn=round(float(ccn), 2),
                            mean_of_stored_components=round(expect, 2),
                            components_present=len(parts), confidence=conf))
    return bad


def what_carries_the_scores(cur, top=15):
    """§3.1 calls the engine "the compounding engine" and weights it a third. If the top of the bench
    is carried by cash conversion and smallness, with no measurable engine at all, the score has
    stopped measuring what it is named after — and that is a plan question, not a bug."""
    cur.execute("""select ticker, round(ccn::numeric,1), engine, cash_conv, durability,
                          data_confidence, round((100*engine_used)::numeric,1), engine_provenance
                   from bench order by ccn desc limit %s""", (top,))
    rows = []
    engineless = 0
    for ticker, ccn, eng, cc, dur, conf, used, how in cur.fetchall():
        has_engine = eng is not None
        engineless += 0 if has_engine else 1
        rows.append(dict(ticker=ticker, ccn=float(ccn), engine_pct=float(eng) if eng else None,
                         cash_conv_pct=float(cc) if cc else None,
                         durability_pct=float(dur) if dur else None,
                         engine_used_pct=float(used) if used is not None else None,
                         provenance=how, confidence=conf))
    return rows, engineless


def check_provenance(cur):
    """§3.1: every bench name has an engine by one method or the other, and says which.

    A null provenance on a scored row means something reached the bench without going through the
    waterfall — which is precisely the state the waterfall exists to make impossible.
    """
    cur.execute("""select ticker, ccn, engine, engine_provenance, durability, data_confidence
                     from bench where ccn is not null""")
    bad = []
    for ticker, ccn, eng, how, dur, conf in cur.fetchall():
        if how not in ("measured", "growth-derived") or eng is None or dur is None:
            bad.append(dict(ticker=ticker, ccn=round(float(ccn), 1), engine_pct=eng,
                            provenance=how, durability=dur,
                            why="scored without an engine, a durability or a provenance"))
        elif how == "growth-derived" and conf != "flagged":
            # §3.1 attaches §3.3's guardrails to growth-derived names — bottom of the band and
            # manual sign-off. Those only bite if the row is marked.
            bad.append(dict(ticker=ticker, ccn=round(float(ccn), 1), provenance=how,
                            confidence=conf, why="growth-derived but not flagged for guardrails"))
    return bad


def check_hurdle_is_price_invariant(cur):
    """§3.1: the hurdle moves when a filing moves it, never because the quote moved.

    The share count must come from the FILING — cap over the close on the cap's `as_of` date. If a
    bench row's hurdle implies a share count that matches today's close instead, the divisor is
    travelling with price again, which is what produced eleven two-way mismatches.
    """
    cur.execute("""select b.ticker, f.effective_shares, f.market_cap, f.cap_close, b.last_close
                     from bench b join v_fundamentals_latest f on f.ticker = b.ticker
                    where b.hurdle_price is not null and f.effective_shares is not null
                      and f.market_cap is not null and b.last_close is not null
                      and f.cap_close is not null""")
    bad = []
    for ticker, eff, cap, cap_close, last in cur.fetchall():
        frozen = float(cap) / float(cap_close)
        drifting = float(cap) / float(last)
        # only interesting when the two answers differ — an unmoved quote makes them identical
        if abs(frozen - drifting) / max(frozen, 1e-9) > 0.005 \
           and abs(float(eff) - drifting) < abs(float(eff) - frozen):
            bad.append(dict(ticker=ticker, stored_shares=float(eff),
                            frozen_at_filing=frozen, implied_by_todays_close=drifting,
                            why="share count tracks the quote, not the filing"))
    return bad


def check_one_row_per_name(cur):
    """§4.3: every bench name must resolve to exactly one fundamentals row.

    `fundamentals` is a point-in-time asset keyed (ticker, filing_date), so a name that has filed
    twice legitimately holds two rows and any join that forgets `v_fundamentals_latest` counts it
    twice. That is how CI.US came to sit at rank 10 twice in one listing. The uniqueness this
    system actually needs is not a constraint on the table — it would destroy the history — it is
    this assertion on the resolution.
    """
    cur.execute("""select b.ticker, count(*) from bench b
                     join v_fundamentals_latest f on f.ticker = b.ticker
                    group by b.ticker having count(*) <> 1""")
    doubled = [dict(ticker=t, rows=n) for t, n in cur.fetchall()]
    cur.execute("""select b.ticker from bench b
                    where not exists (select 1 from v_fundamentals_latest f
                                       where f.ticker = b.ticker)""")
    orphans = [dict(ticker=r[0], rows=0) for r in cur.fetchall()]
    return doubled + orphans


def check_rulings_are_honoured(cur):
    """§3.1's rulings law, asserted against what the machine actually armed (WO-7, obs 97).

    Ruling 66 quarantined DLO's owner cash and the nightly armed it as an entry the same night, and
    nothing in the system noticed — the acceptance query that would have caught it existed only in
    a work order. It runs every night now: a name whose newest live c2 ruling is a quarantine is
    *scored, ranked, watched, never ticketed*, and a name ruled FAIL is inside its cooldown.
    """
    cur.execute("""select a.ticker, r.verdict_canon, r.ruling_id, a.kind
                     from v_armed_latest a
                     join v_rulings_latest_c2 r on r.ticker = a.ticker and r.decides
                    where a.kind in ('entry', 'add')
                      and r.verdict_canon in ('quarantine', 'fail')
                      and a.blocked_by is null""")
    return [dict(ticker=t, verdict=v, ruling_id=i, kind=k) for t, v, i, k in cur.fetchall()]


def check_blackout_wall_has_its_dates(cur, stale_days):
    """§3.3 / WO-4: the wall cannot enforce a date it never had (obs 114).

    Every offerable entry must sit behind a report date inside a plausible quarter. This is the
    work order's own acceptance SQL, standing — because ACA's case was invisible until R1 caught it
    by hand and voided the ticket.
    """
    cur.execute("""select a.ticker from v_armed_latest a
                    where a.kind = 'entry' and a.blocked_by is null
                      and not exists (select 1 from earnings e where e.ticker = a.ticker
                                        and e.report_date > current_date - %s)""", (stale_days,))
    return [r[0] for r in cur.fetchall()]


def check_backtest_is_current(cur, max_age_days=8):
    """The verification instrument has to be testing the machine we actually run.

    Two ways it stops being true, and a paths-filtered CI trigger can only see the first:

      * the code changed — that fires a run, and `params.law_stamp` records which plan it tested;
      * a **config row** changed — no commit, no diff, nothing for git to notice, and the newest
        backtest is now evidence about a machine with different thresholds.

    So the run stamps `config_digest` and this compares it with today's. Also catches the quieter
    failure: the weekly re-run silently stopped happening.
    """
    stamp = config_digest(cur)
    cur.execute("""select id, ran_at, params->>'config_stamp', params->>'law_stamp'
                     from backtest_runs where params->>'variant' = 'law-v0'
                    order by id desc limit 1""")
    row = cur.fetchone()
    if row is None:
        return [dict(why="no law-v0 run exists", stamp=stamp)]
    rid, ran_at, ran_stamp, law_stamp = row
    out = []
    if ran_stamp != stamp:
        out.append(dict(why="config changed since the last backtest", run=rid,
                        tested=ran_stamp, now=stamp))
    cur.execute("select (now() - %s) > make_interval(days => %s)", (ran_at, max_age_days))
    if cur.fetchone()[0]:
        out.append(dict(why=f"newest law-v0 run is older than {max_age_days} days",
                        run=rid, ran_at=str(ran_at)))
    return out


def check_queue_matches_the_book(cur):
    """§3.0: membership lists never drop a name the book owns, and never keep one it has sold."""
    cur.execute("""select 'missing_holding' as why, b.ticker from book b
                    where b.status='open' and b.qty > 0
                      and not exists (select 1 from queue q where q.ticker = b.ticker)
                   union all
                   select 'ghost_row', q.ticker from queue q
                    where q.note = 'book'
                      and not exists (select 1 from book b where b.ticker = q.ticker
                                        and b.status='open' and b.qty > 0)""")
    return [dict(why=w, ticker=t) for w, t in cur.fetchall()]


def check_one_currency(cur):
    """§3.0 / WO-2: no non-USD figure feeds a score.

    A name the funnel reads must have its statements and its market cap in one currency — converted
    at fiscal-period-end FX, or excluded. TSM stored TWD statements against a USD cap and scored an
    implied P/FCF of 1.76x, which is not a multiple, it is a category error.
    """
    cur.execute("""select b.ticker, f.statement_currency, f.converted_to_usd
                     from bench b join v_fundamentals_latest f on f.ticker = b.ticker
                    where b.hurdle_price is not null
                      and (f.quote_ok is not true
                           or (upper(coalesce(f.statement_currency,'')) <> 'USD'
                               and not f.converted_to_usd
                               and upper(coalesce(f.statement_currency,''))
                                   <> upper(coalesce((select currency from universe u
                                                       where u.ticker = b.ticker), 'USD'))))""")
    return [dict(ticker=t, statement_currency=c, converted=bool(k)) for t, c, k in cur.fetchall()]


def preflight(cur, quota):
    """Everything a session must know before it speaks (§4.2, 2026-08-02).

    Not integrity — readiness. The gate, how many entries are actually offerable under the caps,
    whether the momentum sleeve is still in its start-low window, what protection is outstanding,
    and how much of the book carries a share count anybody has confirmed. `score` computed these
    on its way past; reading them back from the database is the point, because that is the copy
    the sessions will read.
    """
    cur.execute("select state from gate_state order by id desc limit 1")
    gate = (cur.fetchone() or ["OFF"])[0]

    cur.execute("""select count(*) filter (where blocked_by is null and urgency <> 'protective'),
                          count(*) filter (where urgency = 'protective'),
                          count(*)
                     from v_armed_latest""")
    offerable, protective, armed_total = cur.fetchone()

    cur.execute("""select count(*) filter (where confirmed is not null), count(*) from (
                     select b.ticker, b.account,
                            (select max(t.trade_date) from transactions t
                              where t.ticker = b.ticker and t.account = b.account) as confirmed
                       from book b where b.status = 'open') s""")
    confirmed, positions = cur.fetchone()
    coverage = (confirmed / positions) if positions else None

    cur.execute("""select min(trade_date) from transactions t join tickets k
                     on k.id = t.ticket_id where k.sleeve='momentum' and t.side='buy'""")
    first_fill = cur.fetchone()[0]
    start_low = not first_fill or (dt.date.today() - first_fill).days <= 90

    return dict(gate=gate, offerable=offerable, protective=protective, armed=armed_total,
                start_low=start_low, positions=positions, quantities_confirmed=confirmed,
                confirmation_coverage=round(coverage, 3) if coverage is not None else None,
                api_quota=quota)


def calibration_gauges(cur, knife_max, buyable_max):
    """§5.5, 2026-08-02 — the falling-knife gauge and the buyable-share gauge, as standing alarms.

    Gauge 1: Spearman rank correlation between how far a name has fallen from its stored high and
    how rich a multiple of FCF the hurdle permits. Near zero is healthy; positive means the screen
    grants its most generous licences to its biggest losers — the exact pathology of 2026-08-01,
    stated as one number. Gauge 2: the share of the ranked bench called buyable; a value screen
    calling most of its own bench cheap is describing itself, not the market.
    """
    cur.execute("""select b.ticker,
                          b.hurdle_price * f.effective_shares / f.fcf_ttm,
                          1.0 - b.last_close / mx.mx
                     from bench b
                     join v_fundamentals_latest f on f.ticker = b.ticker
                     join lateral (select max(close) mx from prices p where p.ticker = b.ticker) mx on true
                    where b.rank is not null and b.hurdle_price is not null
                      and b.last_close is not null and mx.mx > 0
                      and f.fcf_ttm is not null and f.fcf_ttm > 0
                      and f.effective_shares is not null""")
    rows = cur.fetchall()
    rho = None
    if len(rows) >= 10:
        import numpy as np
        mult = np.array([float(r[1]) for r in rows])
        draw = np.array([float(r[2]) for r in rows])
        rank = lambda a: a.argsort().argsort().astype(float)
        rm, rd = rank(mult), rank(draw)
        denom = float(np.std(rm) * np.std(rd))
        rho = float(np.mean((rm - rm.mean()) * (rd - rd.mean())) / denom) if denom else None

    cur.execute("""select count(*) filter (where gap_to_hurdle <= 0), count(*)
                     from bench where rank is not null and gap_to_hurdle is not null""")
    buyable, ranked = cur.fetchone()
    share = (buyable / ranked) if ranked else None
    return dict(knife_corr=round(rho, 3) if rho is not None else None, knife_n=len(rows),
                knife_fail=(rho is not None and rho > knife_max),
                buyable_share=round(share, 3) if share is not None else None,
                buyable_n=ranked, buyable_fail=(share is not None and share > buyable_max))


def main():
    with connect() as conn:
        with Heartbeat(conn, "check") as hb:
            with conn.cursor() as cur:
                floor = float(config(cur, "hurdle_min_return", 0.15))
                quota_alarm = float(config(cur, "api_alarm_fraction", 0.70))
                hurdles = check_hurdles(cur, floor)
                gaps = check_gaps(cur)
                ccns = check_ccn(cur)
                prov = check_provenance(cur)
                drift = check_hurdle_is_price_invariant(cur)
                top, engineless = what_carries_the_scores(cur)
                knife_max = float(config(cur, "verify_knife_corr_max", 0.30))
                buyable_max = float(config(cur, "verify_buyable_share_max", 0.60))
                gauges = calibration_gauges(cur, knife_max, buyable_max)
                doubled = check_one_row_per_name(cur)
                calendar_stale = int(config(cur, "earnings_calendar_stale_days", 110))
                ruled = check_rulings_are_honoured(cur)
                blind = check_blackout_wall_has_its_dates(cur, calendar_stale)
                queue_gaps = check_queue_matches_the_book(cur)
                backtest_stale = check_backtest_is_current(cur)
                mixed_ccy = check_one_currency(cur)

                # §4.1: "the brief alarms past ~70% of daily quota". The reading lives here rather
                # than in `score`, which §4.2 keeps a pure function of the database.
                quota = None
                try:
                    usage = get("user", hb.calls)
                    used = float(usage.get("apiRequests") or 0)
                    limit = float(usage.get("dailyRateLimit") or 1)
                    quota = dict(used=used, limit=limit,
                                 fraction=round(used / limit, 3) if limit else None)
                    if quota["fraction"] and quota["fraction"] >= quota_alarm:
                        hb.amber(f"API quota at {quota['fraction']:.0%} of the daily budget")
                except Exception as e:
                    hb.detail["quota_check_failed"] = f"{type(e).__name__}: {e}"
                flight = preflight(cur, quota)
                line, tickets_allowed = freshness(conn)

                # §4.7: a job that half-fails goes amber — but "amber" with a count is a status, not
                # a cause. Production went amber with the reasons discoverable only by reading rows.
                # Every check now names itself, passing or failing, so the run log answers "what is
                # wrong" without an investigation.
                checks = [
                    dict(check="hurdle_reproduces_floor", failures=len(hurdles),
                         detail=f"stored hurdle does not re-derive from its own components — the "
                                f"{floor:.0%}-floor solve capped at the fair multiple (§3.1)",
                         names=[b["ticker"] for b in hurdles][:20]),
                    dict(check="gap_matches_close_and_hurdle", failures=len(gaps),
                         detail="gap_to_hurdle disagrees with the last_close and hurdle beside it",
                         names=[b["ticker"] for b in gaps][:20]),
                    dict(check="ccn_is_mean_of_components", failures=len(ccns),
                         detail="stored CCN is not the mean of the percentiles on its own row "
                                "(§3.1, §3.3)",
                         names=[b["ticker"] for b in ccns][:20]),
                    dict(check="top_bench_has_measurable_engines", failures=engineless,
                         detail="top-of-bench names carrying no measurable compounding engine — "
                                "§3.1 makes those not bench-eligible",
                         names=[r["ticker"] for r in top if r["engine_pct"] is None][:20]),
                    dict(check="every_score_declares_its_engine", failures=len(prov),
                         detail="a bench row scored without an engine, a durability or a stated "
                                "provenance — or growth-derived without §3.3's guardrail flag",
                         names=[b["ticker"] for b in prov][:20]),
                    dict(check="falling_knife_gauge",
                         failures=1 if gauges["knife_fail"] else 0,
                         detail=f"drawdown-vs-permitted-multiple rank correlation "
                                f"{gauges['knife_corr']} over {gauges['knife_n']} names "
                                f"(alarm above {knife_max}) — positive means the screen pays up "
                                f"for falling knives (§5.5)", names=[]),
                    dict(check="buyable_share_gauge",
                         failures=1 if gauges["buyable_fail"] else 0,
                         detail=f"{gauges['buyable_share']} of the ranked bench called buyable "
                                f"(alarm above {buyable_max}) — a screen calling most of its own "
                                f"bench cheap is describing itself (§5.5)", names=[]),
                    dict(check="hurdle_is_price_invariant", failures=len(drift),
                         detail="the hurdle's share count tracks today's quote rather than the "
                                "close on the cap's as_of date (§3.1)",
                         names=[b["ticker"] for b in drift][:20]),
                    dict(check="backtest_tests_the_machine_we_run",
                         failures=len(backtest_stale),
                         detail="the newest law-v0 backtest was decided under different config "
                                "rows than today's, or is more than a week old — the verification "
                                "instrument is describing a machine we no longer run",
                         names=[b["why"] for b in backtest_stale][:5]),
                    dict(check="one_fundamentals_row_per_bench_name", failures=len(doubled),
                         detail="a bench name resolves to more or fewer than one fundamentals "
                                "row — any join written against the history table instead of "
                                "v_fundamentals_latest counts it that many times (§4.3)",
                         names=[b["ticker"] for b in doubled][:20]),
                    # The four work-order acceptances from 2026-08-07, standing rather than
                    # one-off. Each of them describes something the machine did while every
                    # existing check read green, which is learnings #19 in its purest form.
                    dict(check="rulings_bind_the_arming_stage", failures=len(ruled),
                         detail="an offerable entry or add on a name whose newest live c2 ruling "
                                "is a QUARANTINE or a FAIL — §3.1: scored, ranked, watched, never "
                                "ticketed",
                         names=[f"{b['ticker']}({b['verdict']})" for b in ruled][:20]),
                    dict(check="blackout_wall_has_its_dates", failures=len(blind),
                         detail=f"an offerable entry with no report date inside {calendar_stale} "
                                f"days — the wall cannot enforce a date it never had (§3.3, obs "
                                f"114)", names=blind[:20]),
                    dict(check="queue_matches_the_book", failures=len(queue_gaps),
                         detail="a live holding missing from the queue, or a queue seat for a "
                                "position the book has closed — §3.0: membership lists never drop "
                                "a name the book owns",
                         names=[f"{g['why']}:{g['ticker']}" for g in queue_gaps][:20]),
                    dict(check="scores_read_one_currency", failures=len(mixed_ccy),
                         detail="a bench name carrying a hurdle whose statements and market cap "
                                "are not in one currency — §3.0 converts at fiscal-period-end FX "
                                "or routes to the data-confidence path, never scores raw",
                         names=[b["ticker"] for b in mixed_ccy][:20]),
                ]
                failed = [c for c in checks if c["failures"]]
                findings = dict(hurdle_mismatches=hurdles, gap_mismatches=gaps,
                                ccn_mismatches=ccns, provenance_gaps=prov, share_drift=drift,
                                top_of_bench=top, doubled_rows=doubled,
                                engineless_in_top=engineless, gauges=gauges,
                                ruled_but_armed=ruled, calendar_blind=blind,
                                queue_book_gaps=queue_gaps, mixed_currency=mixed_ccy,
                                preflight=flight, freshness=line,
                                tickets_allowed=tickets_allowed,
                                checks=checks, causes=[c["check"] for c in failed])
                hb.detail.update(findings)

            # §4.2 (2026-08-02): "ambers print at the top of the brief; a red blocks the
            # dispatch". BLOCKING is the small, named set — a number the machine cannot rebuild
            # from its own row, or a row it counts twice. Those corrupt the arithmetic a session
            # would speak from. A calibration gauge past its alarm is a finding about the SCREEN,
            # not about tonight's numbers: loud, and never a gag.
            for c in failed:
                (hb.red if c["check"] in BLOCKING else hb.amber)(
                    f"{c['check']}: {c['failures']} — {c['detail']}"
                    + (f" · {', '.join(c['names'])}" if c["names"] else ""))
            if not tickets_allowed:
                hb.amber(f"tickets held — {line}")
            blocked = [c["check"] for c in failed if c["check"] in BLOCKING]
            hb.detail["blocks_dispatch"] = blocked
            print(f"check: {line}")
            print(f"check: {len(failed)} check(s) failing — "
                  f"{', '.join(c['check'] for c in failed) or 'none'}"
                  + (f" | BLOCKING: {', '.join(blocked)}" if blocked else ""))
            print(f"check: gate {flight['gate']} · {flight['offerable']} offerable · "
                  f"{flight['protective']} protective · "
                  f"{flight['quantities_confirmed']}/{flight['positions']} quantities confirmed")
            print(f"check: {len(hurdles)} hurdle mismatches · {len(gaps)} gap · {len(ccns)} CCN · "
                  f"{engineless} of {len(top)} top-bench names have no measurable engine")
            for b in hurdles:
                print(f"  HURDLE {b['ticker']}: stored {b['stored_hurdle']} vs re-derived "
                      f"{b['hurdle_that_clears_the_floor']}")
            for row in top:
                print(f"  TOP {row['ticker']:<9} CCN {row['ccn']:>5} · engine "
                      f"{row['engine_pct'] if row['engine_pct'] is not None else 'DROPPED':>7} "
                      f"({row['provenance']}) · cash {row['cash_conv_pct']} · "
                      f"durability {row['durability_pct']} · {row['confidence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
