"""Synthetic worlds for the integration tests — bars, candidates, positions, tickets.

Deliberately hand-built rather than copied from production: a test whose data came from the live
database stops being a test the moment the market moves.
"""
import datetime as dt

SESSIONS = 300


def trading_days(n=SESSIONS, end=None):
    """`n` weekday sessions ending today (or `end`), oldest first."""
    end = end or dt.date.today()
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    return list(reversed(days))


def add_name(cur, ticker, *, industry="Semiconductors", in_l0=True, holding=False, cap=5e9):
    cur.execute("""insert into universe (ticker,name,kind,exchange,currency,status,in_l0,
                                         is_holding,sector,industry,market_cap_usd)
                   values (%s,%s,'stock','US','USD','active',%s,%s,'Technology',%s,%s)
                   on conflict (ticker) do update set in_l0=excluded.in_l0,
                     is_holding=excluded.is_holding, industry=excluded.industry""",
                (ticker, ticker.split(".")[0], in_l0, holding, industry, cap))


def flat_then_base(cur, ticker, *, level=100.0, pivot=110.0, pivot_ago=40, volume=2_000_000,
                   wobble=0.02,
                   last_close=None, last_high=None, last_low=None, last_open=None,
                   last_volume=None, days=None):
    """A quiet series with one deliberate high `pivot_ago` sessions back — a valid base by §3.2,
    with the final session's bar overridable so a test can stage a breakout, a gap or a stop hit."""
    days = days or trading_days()
    rows = []
    for i, d in enumerate(days):
        # a real base breathes. A dead-flat series has zero standard deviation, so any up-day at
        # all reads as a 2-sigma euphoria move — an artefact of the fixture, not of §3.2.
        c = level * (1 + wobble * ((i % 7) - 3) / 3.0)
        h, lo, o, v = c * 1.005, c * 0.995, c, volume
        if i == len(days) - 1 - pivot_ago:
            h = pivot
        if i == len(days) - 1:
            c = last_close if last_close is not None else c
            h = last_high if last_high is not None else max(h, c)
            lo = last_low if last_low is not None else min(lo, c)
            o = last_open if last_open is not None else c
            v = last_volume if last_volume is not None else v
        rows.append((ticker, d, o, h, lo, c, c, int(v)))
    cur.executemany("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                       values (%s,%s,%s,%s,%s,%s,%s,%s)
                       on conflict (ticker,d) do update set open=excluded.open, high=excluded.high,
                         low=excluded.low, close=excluded.close, adj_close=excluded.adj_close,
                         volume=excluded.volume""", rows)
    return days


def rising_series(cur, ticker, *, start=50.0, end=120.0, days=None, volume=2_000_000):
    """A clean uptrend that passes M2 — used where a test needs the trend template to hold."""
    days = days or trading_days()
    step = (end - start) / (len(days) - 1)
    rows = []
    for i, d in enumerate(days):
        c = start + step * i
        rows.append((ticker, d, c, c * 1.004, c * 0.996, c, c, int(volume)))
    cur.executemany("""insert into prices (ticker,d,open,high,low,close,adj_close,volume)
                       values (%s,%s,%s,%s,%s,%s,%s,%s)
                       on conflict (ticker,d) do update set close=excluded.close""", rows)
    return days


def gate(cur, state="ON"):
    cur.execute("""insert into gate_state (week_end,state,spx_close,sma30,sma30_4w_ago,flipped)
                   values (current_date,%s,7400,7100,7000,false)""", (state,))


def candidate(cur, ticker, *, mcn=80.0, state="BUY", pivot=110.0, stop=101.2, m2=True, m4=True,
              rank=1, last_close=100.0):
    cur.execute("""insert into candidates (ticker,rank,mcn,mq,setup,grp,m2,m4,state,pivot,
                                           base_len,base_depth,base_low,stop_suggest,last_close)
                   values (%s,%s,%s,80,80,80,%s,%s,%s,%s,40,0.05,%s,%s,%s)""",
                (ticker, rank, mcn, m2, m4, state, pivot, stop, stop, last_close))


def queued(cur, ticker, *, source="momentum", state="BUY", trigger=110.0, stop=101.2, mcn=80.0,
           rank=1):
    cur.execute("""insert into queue (ticker,rank,source,state,trigger_price,limit_price,
                                      stop_suggest,proximity,mcn,note)
                   values (%s,%s,%s,%s,%s,%s,%s,0.05,%s,'test')""",
                (ticker, rank, source, state, trigger, trigger * 1.02 if trigger else None,
                 stop, mcn))


def position(cur, ticker, *, account="TFSA", sleeve="momentum", qty=100, cost=110.0, stop=101.2,
             step=1, pivot=110.0, target=200, opened_days_ago=3, confirmed=None, theme="test theme",
             stalled_days_ago=None):
    # counted in TRADING days from the last session, not calendar days from today. A position
    # "opened today" on a Saturday has no bar on or after its opening date, so the breakout
    # classifier finds nothing and the suite fails every weekend — which is how a suite teaches
    # people to ignore it.
    sessions = trading_days()
    opened = sessions[-1 - min(opened_days_ago, len(sessions) - 1)]
    stalled = (dt.date.today() - dt.timedelta(days=stalled_days_ago)
               if stalled_days_ago is not None else None)
    cur.execute("""insert into book (ticker,account,sleeve,lot,qty,avg_cost,currency,opened_at,
                                     stop,stop_limit,highest_close,trail_mode,pyramid_step,theme,
                                     pivot,target_qty,confirmed,pyramid_stalled_since,status)
                   values (%s,%s,%s,'core',%s,%s,'USD',%s,%s,%s,%s,'initial',%s,%s,%s,%s,%s,%s,
                           'open') returning id""",
                (ticker, account, sleeve, qty, cost, opened, stop,
                 stop * 0.97 if stop is not None else None, cost, step, theme,
                 pivot, target, confirmed, stalled))
    return cur.fetchone()[0]


def ticket(cur, ticker, *, action="buy", state="approved", trigger=110.0, qty=100, stop=101.2,
           sleeve="momentum", account="TFSA", target=200, theme="test theme"):
    cur.execute("""insert into tickets (ticker,account,sleeve,action,reason,order_type,
                                        trigger_price,limit_price,qty,stop,stop_limit_price,
                                        target_qty,theme,state)
                   values (%s,%s,%s,%s,'trigger','stop_limit',%s,%s,%s,%s,%s,%s,%s,%s)
                   returning id""",
                (ticker, account, sleeve, action, trigger, trigger * 1.02 if trigger else None,
                 qty, stop, stop * 0.97, target, theme, state))
    return cur.fetchone()[0]


def fill(cur, ticket_id, ticker, *, side="buy", qty=100, price=110.0, account="TFSA",
         days_ago=0, step=None):
    cur.execute("""insert into transactions (ticket_id,ticker,account,side,qty,price,currency,
                                             fx_rate,trade_date,confirmed,pyramid_step)
                   values (%s,%s,%s,%s,%s,%s,'USD',1.40,%s,true,%s)""",
                (ticket_id, ticker, account, side, qty, price,
                 dt.date.today() - dt.timedelta(days=days_ago), step))


def balances(cur, *, tfsa_cash=100_000.0, total=200_000.0):
    cur.execute("""insert into balances (account,as_of,cash_cad,cash_usd,total_value,source)
                   values ('TFSA',current_date,%s,0,%s,'test')""", (tfsa_cash, total))


def earnings_on(cur, ticker, when):
    cur.execute("""insert into earnings (ticker,report_date,report_when)
                   values (%s,%s,'AfterMarketClose')
                   on conflict (ticker,report_date) do nothing""", (ticker, when))
