"""Shared plumbing every job leans on: connection, config, heartbeat, vendor fetch.

Kept deliberately thin — the jobs stay readable, and the heartbeat contract (one runs row
per job, green | amber | red, tracebacks embedded on death) lives in exactly one place.
"""
import bisect, os, sys, json, hashlib, time, traceback, urllib.request, urllib.error
import datetime as dt
import psycopg

EODHD = "https://eodhd.com/api"


def db_url():
    """The connection string, with TLS required unless told otherwise.

    Handles both shapes Postgres accepts: a URI (`postgresql://…`) and a keyword/value DSN
    (`host=… dbname=…`). The old version appended `?sslmode=require` unconditionally, which turns
    a keyword/value DSN's database name into `postgres?sslmode=require` — found the first time a
    job was pointed at a local test database. `DB_SSLMODE` exists for exactly that case; production
    sets nothing and gets `require`.
    """
    u = os.environ["DATABASE_URL"]
    mode = os.environ.get("DB_SSLMODE", "require")
    if not mode or "sslmode" in u:
        return u
    if "://" in u:
        return u + ("&" if "?" in u else "?") + f"sslmode={mode}"
    return f"{u} sslmode={mode}"


def connect():
    return psycopg.connect(db_url())


def dry():
    return os.environ.get("DRY_RUN", "false").lower() in ("1", "true", "yes")


def config(cur, key, default=None):
    cur.execute("select value from config where key=%s order by set_at desc limit 1", (key,))
    row = cur.fetchone()
    return row[0] if row else default


# The config rows that decide what the machine *does*, as opposed to how it talks or how often it
# fetches. A backtest is only evidence about the machine these describe.
DECISION_KEYS = ("score_thresholds", "sleeve_ceiling", "momentum_max_names",
                 "holdthrough_cushion", "blackout_trading_days", "entry_limit_over_pivot",
                 "mcn_risk_budget", "max_positions")


def config_digest(cur, keys=DECISION_KEYS):
    """A short, stable digest of the config a decision was made under.

    Behaviour lives in the database as well as in git: change a threshold and the machine behaves
    differently with no commit, no diff and nothing for a paths-filtered CI trigger to notice.
    Every backtest run stamps this, and `check` ambers when the newest run's stamp no longer
    matches today's — so "the rules moved and nothing re-tested them" is a line in the brief
    rather than a silence. One function, so the stamp and the comparison cannot drift apart.
    """
    values = {k: config(cur, k, None) for k in keys}
    blob = json.dumps(values, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def key():
    return os.environ["EODHD_API_KEY"]


def jsonb(obj):
    """Anything -> a jsonb-safe string. Dates and Decimals are stringified rather than crashing."""
    return json.dumps(obj, default=str)


def observe(cur, kind, body, *, ticker=None, score=None, price=None, detail=None, once=False):
    """Append an observation (§4.3). `once=True` makes a re-run idempotent by exact body match —
    the shadow book and gate flips want a row per event, breaches want a row per condition."""
    if once:
        cur.execute("select 1 from observations where kind=%s and body=%s limit 1", (kind, body))
        if cur.fetchone():
            return False
    cur.execute("""insert into observations(kind,ticker,score,price,body,detail)
                   values (%s,%s,%s,%s,%s,%s)""",
                (kind, ticker, score, price, body, jsonb(detail or {})))
    return True


def get(path, calls, tries=3, timeout=90, **params):
    """GET an EODHD endpoint. `calls` is a one-element list used as a shared counter."""
    params.setdefault("api_token", key())
    params.setdefault("fmt", "json")
    qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
    url = f"{EODHD}/{path}?{qs}"
    for attempt in range(tries):
        calls[0] += 1
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(5 * (attempt + 1)); continue
            raise
        except Exception:
            if attempt < tries - 1:
                time.sleep(5 * (attempt + 1)); continue
            raise


def cash_by_account(cur):
    """Per-account cash by currency: Sunday's anchor, carried forward by the ledger.

    §2.0 — **balances are truth, prices are the extrapolation** — and §2.0 again, on the other
    side of the same coin: a ticket "is only written if that account holds the cash", and cash
    "includes unsettled proceeds of same-account sells". Money moves when a fill happens. The
    anchor is a Sunday reading, so a fill after it has already moved the real cash and the anchor
    has not caught up: the ledger is what carries it forward.

    Found the day four 2026-08-04 fills were reconciled. The book gained NUE and RS while the cash
    that bought them sat untouched in an anchor dated the 3rd, and NAV read 8.1% high — C$17,937
    of stock the account was credited with owning and with still having the money for. Before the
    reconciliation the two errors cancelled, which is the least comfortable way for a number to be
    right.

    A buy takes its own currency out, a sell puts it back, fees on both. Nothing else is modelled:
    deposits, dividends and interest keep being absorbed at the next anchor, exactly as §2.0 says.
    A levered buy can drive an account's cash negative between anchors — that is the undrawn
    facility showing through, and NAV lands in the same place either way, because borrowing is
    NAV-neutral at the moment of use.
    """
    cur.execute("""select distinct on (b.account) b.account, a.kind, b.cash, b.cash_cad,
                          b.cash_usd, b.drawn, b.credit_limit, b.total_value, b.as_of
                   from balances b join accounts a on a.code=b.account
                   order by b.account, b.as_of desc, b.id desc""")
    bal = {r[0]: dict(kind=r[1], cash=r[2], cad=r[3], usd=r[4], drawn=r[5], limit=r[6],
                      total=r[7], as_of=r[8]) for r in cur.fetchall()}

    # only movement the anchor cannot already contain — strictly after its date, and only the two
    # sides that are cash. `confirm` rows are R4 restating a share count and move no money.
    cur.execute("""with anchor as (
                     select distinct on (account) account, as_of from balances
                      order by account, as_of desc, id desc)
                   select t.account, coalesce(t.currency, 'USD'),
                          sum(case when t.side = 'sell'
                                     then  t.qty * t.price - coalesce(t.fees, 0)
                                   when t.side = 'buy'
                                     then -t.qty * t.price - coalesce(t.fees, 0)
                                   else 0 end)
                     from transactions t
                     join anchor a on a.account = t.account
                    where t.trade_date > a.as_of
                    group by 1, 2""")
    since = {}
    for acct, ccy, delta in cur.fetchall():
        since.setdefault(acct, {})[ccy] = float(delta or 0)

    out = {}
    for acct, b in bal.items():
        moved = since.get(acct, {})
        if b.get("cad") is not None or b.get("usd") is not None:
            cad, usd = float(b.get("cad") or 0), float(b.get("usd") or 0)
        else:
            # the deprecated single column, kept readable for rows written before migration 016
            cad, usd = float(b.get("cash") or 0), 0.0
        out[acct] = dict(kind=b["kind"], as_of=b["as_of"], drawn=b["drawn"], limit=b["limit"],
                         total=b["total"],
                         cad=cad + moved.get("CAD", 0.0), usd=usd + moved.get("USD", 0.0),
                         anchored_cad=cad, anchored_usd=usd,
                         moved_since_anchor={k: round(v, 2) for k, v in moved.items() if v})
    return out


def nav_cad(cur):
    """NAV per §2.0 — balances are truth, prices are the extrapolation.

    An account's stated total wins when we have one; otherwise we build it from recorded cash
    plus what the book says it holds. Facilities contribute their drawn balance as debt only —
    undrawn credit is capacity, not a liability. The book-derived equity total comes back
    alongside so the caller can see, and report, any gap between the two."""
    cur.execute("select close from prices where ticker='USDCAD.FOREX' order by d desc limit 1")
    row = cur.fetchone()
    fx = float(row[0]) if row else 1.0

    cur.execute("""select b.account, b.ticker, b.currency, b.qty, p.close
                   from book b
                   join lateral (select close from prices where ticker=b.ticker
                                 order by d desc limit 1) p on true
                   where b.status='open'""")
    per_ticker, per_account = {}, {}
    for acct, tk, ccy, qty, close in cur.fetchall():
        cad = float(qty) * float(close) * (fx if ccy == "USD" else 1.0)
        # accumulate, never assign. §2.6's one-position-one-account rule should make a ticker in two
        # accounts impossible, but NAV must report what the book actually holds rather than what the
        # rules say it should — an assignment silently dropped every lot but the last.
        per_ticker[tk] = per_ticker.get(tk, 0.0) + cad
        per_account[acct] = per_account.get(acct, 0.0) + cad
    book_equities = sum(per_account.values())

    bal = cash_by_account(cur)          # the anchor, carried forward by the ledger (§2.0)

    assets = cash = debt = 0.0
    accounts = {}
    for acct in set(list(per_account) + list(bal)):
        b = bal.get(acct, {})
        if b.get("kind") == "facility":
            debt += float(b.get("drawn") or 0)      # facilities are CAD always
            continue
        # cash per currency, so the USD sleeve reprices with FX daily
        c_cad, c_usd = float(b.get("cad") or 0), float(b.get("usd") or 0)
        c = c_cad + c_usd * fx
        value = c + per_account.get(acct, 0.0)      # §2.0: balances anchor, prices extrapolate
        stated = b.get("total")
        accounts[acct] = dict(value_cad=round(value, 2), cash_cad=round(c, 2),
                              cash_native={"CAD": round(c_cad, 2), "USD": round(c_usd, 2)},
                              # what the anchor said, and what the ledger has done since — a
                              # variance against a stated total is unreadable without both
                              cash_anchored={"CAD": round(float(b.get("anchored_cad") or 0), 2),
                                             "USD": round(float(b.get("anchored_usd") or 0), 2)},
                              cash_moved_since_anchor=b.get("moved_since_anchor") or {},
                              book_equities_cad=round(per_account.get(acct, 0.0), 2),
                              stated_total=float(stated) if stated is not None else None,
                              variance_cad=(round(value - float(stated), 2)
                                            if stated is not None else None))
        assets += value
        cash += c
    for acct, b in bal.items():
        if b.get("kind") == "facility":
            accounts[acct] = dict(drawn=float(b.get("drawn") or 0),
                                  limit=float(b.get("limit") or 0) or None)

    anchored = max((b["as_of"] for b in bal.values() if b.get("as_of")), default=None)
    return dict(nav=assets - debt, assets=assets, cash=cash, debt=debt, fx=fx,
                book_equities=book_equities, per_ticker=per_ticker, accounts=accounts,
                anchored=anchored, balances_captured=bool(bal))


VALUATION_TOLERANCE = 0.005          # half a cent


def valuation_canary(cur, *, tolerance=VALUATION_TOLERANCE):
    """§4.2, new law: every holding's valuation price must equal its latest `prices` bar.

    Returns the mismatches. The caller fails the run on any — **red, not amber**: a NAV built on a
    stale price is not a degraded number, it is a wrong one, and every weight, cap check and share
    count downstream inherits it.

    Deliberately re-derived rather than trusted. `nav_cad` already joins the latest bar, so this can
    only fire if the join changes, a cache appears, or a snapshot date creeps in — which is exactly
    the class of change nobody notices until a brief prints the wrong number.
    """
    cur.execute("""select b.ticker, b.qty, p.close, p.d
                     from book b
                     join lateral (select close, d from prices where ticker = b.ticker
                                    order by d desc limit 1) p on true
                    where b.status = 'open'""")
    latest = {r[0]: (float(r[2]), r[3]) for r in cur.fetchall()}

    cur.execute("""select b.ticker, p.close
                     from book b
                     join lateral (select close from prices where ticker = b.ticker
                                    order by d desc limit 1) p on true
                    where b.status = 'open'""")
    bad = []
    for ticker, used in cur.fetchall():
        want, bar_date = latest.get(ticker, (None, None))
        if want is None or used is None or abs(float(used) - want) > tolerance:
            bad.append(dict(ticker=ticker, valued_at=float(used) if used is not None else None,
                            latest_bar=want, bar_date=str(bar_date) if bar_date else None))
    return bad


def quantity_canary(cur, *, stale_days=9):
    """The canary §4.2's price check cannot provide — a share count nobody has confirmed.

    The AVGO alarm that started this work was reported as a stale price. It was not: the price was
    correct to the penny and the *quantity* in the report was wrong. A price check would have passed
    it, and would pass it again. §4.5 step 5 has Zak confirm settled positions every Sunday, so a
    book quantity whose last confirmation is older than that is the thing to name.

    Returns positions with no confirming transaction inside the window. Amber, not red: an
    unconfirmed quantity is a reason to distrust NAV, not a reason to stop protecting the book.
    """
    cur.execute("""select b.ticker, b.account, b.qty, b.updated_at::date,
                          (select max(t.trade_date) from transactions t
                            where t.ticker = b.ticker and t.account = b.account) as last_confirmed
                     from book b
                    where b.status = 'open'""")
    stale = []
    for ticker, account, qty, updated, confirmed in cur.fetchall():
        age = (dt.date.today() - confirmed).days if confirmed else None
        if age is None or age > stale_days:
            stale.append(dict(ticker=ticker, account=account, qty=float(qty),
                              last_confirmed=str(confirmed) if confirmed else None,
                              days_since=age))
    return stale


def wal_bytes(cur):
    """Bytes currently sitting in pg_wal, or None where the role cannot look.

    This is the number that took production down on 2026-08-03. The database was under 1 GB and
    the fatal error was `could not write to file "pg_wal/xlogtemp...": No space left on device` —
    a sustained bulk upsert generated write-ahead log faster than checkpoints could recycle it,
    and the WAL directory, not the data, filled the volume. `max_wal_size` is 4 GB here, so
    Postgres is *permitted* to let that happen; nothing but the writer can pace itself.
    """
    try:
        cur.execute("select coalesce(sum(size), 0) from pg_ls_waldir()")
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        return None                      # never let a diagnostic break the job it protects


def wal_ceiling_floor(cur):
    """The lowest ceiling that is not permanently tripped, derived from Postgres's own settings.

    **A ceiling below `min_wal_size` can never be satisfied.** Postgres retains at least
    `min_wal_size` of recycled segments by design and is permitted to run to `max_wal_size` between
    checkpoints — here 1 GB and 4 GB. A guard set under that range does not protect anything; it
    reports the database's normal resting state as an emergency and stops every bulk job a few
    minutes in, no matter how long the caller waits.

    That is exactly what happened to WO-A9's delisted census: four separate passes, each stopping
    after ~4 minutes against ceilings of 900-1500 MB while pg_wal sat at its normal 1,776 MB. The
    census was never blocked by the database.

    The number that means "the checkpointer is genuinely losing" is therefore ABOVE `max_wal_size`,
    not below it — that is the level Postgres itself starts forcing checkpoints to hold. Returns
    `max_wal_size` plus a margin; callers should treat it as the minimum sane ceiling, not a target.
    """
    try:
        cur.execute("select setting::bigint from pg_settings where name = 'max_wal_size'")
        row = cur.fetchone()
        if not row:
            return None
        return int(row[0]) * 1024 * 1024 * 5 // 4        # max_wal_size + 25%
    except Exception:
        return None


def wait_for_wal(conn, *, ceiling_bytes, max_wait_s=180, poll_s=10):
    """Let the checkpointer catch up before writing more. Returns True if it is safe to continue.

    A bulk writer that never pauses will out-run checkpointing on any disk; the only question is
    how long it takes. Pausing costs minutes. Not pausing cost a night.
    """
    waited = 0
    with conn.cursor() as cur:
        floor = wal_ceiling_floor(cur)
    if floor and ceiling_bytes < floor:
        # Refuse to enforce a ceiling the database can never satisfy. Silently honouring it makes
        # every bulk job stop a few minutes in and report WAL pressure that is not there.
        print(f"  wal guard: ceiling {ceiling_bytes / 1048576:.0f} MB is below max_wal_size + 25% "
              f"({floor / 1048576:.0f} MB) — Postgres rests in that range by design; raising to it")
        ceiling_bytes = floor
    while True:
        with conn.cursor() as cur:
            now = wal_bytes(cur)
        if now is None or now < ceiling_bytes:
            return True
        if waited >= max_wait_s:
            return False
        time.sleep(poll_s)
        waited += poll_s


def load_bars(cur, tickers):
    """{ticker: [{d, open, high, low, close, adj, vol}, ...]} in date order, for the names asked.

    `adj` falls back to the raw close when the vendor gives no adjusted figure. §4.1 pins which
    one a caller wants: signals read `adj`, valuation reads `close`.
    """
    cur.execute("""select ticker, d, open, high, low, close, adj_close, volume
                   from prices where ticker = any(%s) order by ticker, d""", (list(tickers),))
    out = {}
    for t, d, op, hi, lo, cl, ac, vol in cur.fetchall():
        out.setdefault(t, []).append(dict(d=d, open=op, high=hi, low=lo, close=cl,
                                          adj=ac if ac is not None else cl, vol=vol or 0))
    return out


# --------------------------------------------------------------------------- FX (§4.1, §3.0)
# The vendor's convention, in one place: majors quote as XXXUSD, everything else as USDXXX. Both
# carry the same fact and only the direction differs, so `fx_pair` and `fx_pair_currency` are
# inverses of each other and nothing else in the system has to know which way round a pair reads.
BASE_QUOTED = frozenset({"EUR", "GBP", "AUD", "NZD", "IEP"})


def fx_pair(currency):
    """(ticker, invert) for a currency, or None. `invert` means the close is units per USD."""
    c = (currency or "").strip().upper()
    if len(c) != 3 or not c.isalpha() or c == "USD":
        return None
    return (f"{c}USD.FOREX", False) if c in BASE_QUOTED else (f"USD{c}.FOREX", True)


def fx_pair_currency(ticker):
    """(currency, invert) for a FOREX ticker, or (None, False) for anything else."""
    code = str(ticker or "").split(".")[0].upper()
    if len(code) != 6 or not code.isalpha():
        return None, False
    base, quote = code[:3], code[3:]
    if quote == "USD" and base != "USD":
        return base, False              # close is USD per unit of base
    if base == "USD" and quote != "USD":
        return quote, True              # close is units of quote per USD
    return None, False


class FxRates:
    """Fiscal-period-end FX, read out of our own bars (§3.0, §4.1).

    §3.0 makes a foreign issuer compounder-eligible "only when FCF and market cap are expressed in
    one currency — financials converted at **fiscal-period-end FX**". So the rate a statement gets
    is the last bar at or before the day that period closed, never tonight's: a five-year-old
    income statement restated at today's rate is a number about today's currency, not about that
    year's business.
    """

    def __init__(self, series=None):
        # sorted per currency, because two tickers can legitimately map to one — and because the
        # lookup below bisects. A full re-extract does tens of thousands of these.
        self.series = {c: sorted(rows) for c, rows in (series or {}).items()}

    @classmethod
    def load(cls, cur):
        cur.execute("""select u.ticker, p.d, p.close from prices p
                       join universe u on u.ticker = p.ticker
                       where u.kind = 'fx' and p.close is not null and p.close > 0
                       order by u.ticker, p.d""")
        out = {}
        for tk, d, close in cur.fetchall():
            ccy, invert = fx_pair_currency(tk)
            if not ccy:
                continue
            out.setdefault(ccy, []).append((d, (1.0 / float(close)) if invert else float(close)))
        return cls(out)

    def usd_per(self, ccy, on):
        """(rate, as_of, exact) — USD per unit of `ccy` on `on`. `exact` is False when the date
        predates every bar we hold and the oldest observation stood in for it."""
        c, on = (ccy or "").upper(), _as_date(on)
        if on is None:
            return None, None, False
        if c == "USD":
            return 1.0, on, True
        rows = self.series.get(c)
        if not rows:
            return None, None, False
        i = bisect.bisect_right(rows, (on, float("inf")))
        if i == 0:
            # older than anything we hold. The closest observation is the honest substitute and it
            # travels marked, so a name whose LATEST period needed one is flagged rather than used.
            d, rate = rows[0]
            return rate, d, False
        d, rate = rows[i - 1]
        return rate, d, True

    def convert(self, frm, to, on):
        """(rate, as_of, exact) to restate a figure from `frm` into `to` on `on`."""
        a, a_on, a_ok = self.usd_per(frm, on)
        b, b_on, b_ok = self.usd_per(to, on)
        if not a or not b:
            return None, None, False
        newest = max(x for x in (a_on, b_on) if x is not None)
        return a / b, newest, (a_ok and b_ok)


def _as_date(value):
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def stops_breached(cur, bars):
    """Names whose standing stop was touched by tonight's bar (§4.1 sell-side quarantine trigger).

    Read from the stops already in the book, which is the right grain: the quarantine asks whether
    tonight's PRINT can be trusted to sell, and the print is judged against the protection that was
    standing when it arrived.
    """
    cur.execute("select ticker, stop from book where status='open' and stop is not null")
    hit = set()
    for tk, stop in cur.fetchall():
        b = bars.get(tk)
        if b and b[-1]["low"] is not None and stop is not None \
           and float(b[-1]["low"]) <= float(stop):
            hit.add(tk)
    return hit


# §4.2's three verbs, newest names first. The `runs` ledger keeps the old job names on purpose —
# the record stays the record — so freshness has to recognise both vocabularies or every brief
# written after the migration would read as a system with no history.
VERBS = {
    "ingest": ("ingest-daily", "ingest-filings", "ingest-universe",
               "nightly-ingest", "nightly-retry", "fundamentals", "monthly-funnel"),
    "score":  ("score", "weekly-rank", "duties"),
    "check":  ("check", "verify"),
}
# a red or amber in these domains means the prices themselves are suspect, so §4.4's
# "stale data ⇒ no new tickets, protective moves only" applies
PRICE_CRITICAL = VERBS["ingest"] + VERBS["score"]

# §4.7 (ruled 2026-08-05): schedule drift is not a half-failure and never turns a job amber. It
# prints as `late: <job> +NNNm` and decides nothing. Below this many minutes it isn't worth the
# ink — the floor is the old amber threshold, so exactly the drift that used to gag the desk is
# now the drift that gets named and ignored.
LATE_MINUTES_FLOOR = 30


def late_minutes(detail):
    """Minutes past slot recorded on a runs row, or None. Reads both shapes: `late_minutes` as
    written today, and the `schedule.drift_minutes` older rows carry. Early starts are not late."""
    if not isinstance(detail, dict):
        return None
    raw = detail.get("late_minutes")
    if raw is None:
        raw = (detail.get("schedule") or {}).get("drift_minutes")
    try:
        m = float(raw)
    except (TypeError, ValueError):
        return None
    return m if m > 0 else None


def freshness(conn, *, stale_days=4):
    """The one-line answer to "is it safe to speak" (§4.2): `ingest ✓ score ✓ check ✓`.

    Returns (line, tickets_allowed). §5.6, ruled 2026-08-05 — **stale means the bars, not the
    clock**. Tickets are held on exactly three conditions:

      * the bars are old,
      * a price-critical job failed (red, or the half-failure §4.7 calls amber),
      * the chain ran **out of order** — an ingest landed rows after the `score` beside it, so the
        derived numbers ranked yesterday's world.

    **Lateness alone holds nothing.** It rides the line as `late: <job> +NNNm` and decides nothing:
    a job queued three hours behind its slot with current bars is a punctuality note, not a data
    fault, and the whole desk used to go silent on it.
    """
    with conn.cursor() as cur:
        # stock bars only. FX and the index come from the same nightly pull, so in a clean run this
        # is the same date — but a half-failed ingest that landed USDCAD and no equities would
        # otherwise read as fresh, and "stale data ⇒ no new tickets" would quietly not apply.
        cur.execute("""select max(p.d) from prices p join universe u on u.ticker = p.ticker
                       where u.kind = 'stock'""")
        last_bar = cur.fetchone()[0]
        cur.execute("""select distinct on (job) job, status, detail from runs
                       where started_at > now() - interval '36 hours' order by job, id desc""")
        recent = [(j, s, d) for j, s, d in cur.fetchall()]
        # every non-dry run in the window — the ordering question is about runs, not jobs
        cur.execute("""select job, started_at, finished_at, coalesce(rows_written, 0) from runs
                       where started_at > now() - interval '36 hours' and not dry_run""")
        timeline = cur.fetchall()

    status = {j: s for j, s, _ in recent}
    marks = []
    for verb, jobs in VERBS.items():
        seen = [status[j] for j in jobs if j in status]
        if not seen:
            marks.append(f"{verb} —")
        elif any(s == "red" for s in seen):
            marks.append(f"{verb} ✗")
        elif any(s == "amber" for s in seen):
            marks.append(f"{verb} ⚠")
        else:
            marks.append(f"{verb} ✓")
    line = " · ".join(marks)

    late = sorted(f"late: {j} +{m:.0f}m" for j, _, d in recent
                  if (m := late_minutes(d)) and m >= LATE_MINUTES_FLOOR)
    if late:
        line += " · " + " · ".join(late)

    # §5.6's third condition: order. The chain is a data dependency (§4.2's `needs:`), so this
    # should be impossible — which is exactly why it is asserted rather than assumed.
    #
    # Two asymmetries, both learned the hard way on the first night this ran. An ingest counts only
    # once it has FINISHED and landed rows: the monthly guard's exit-clean run and the retry that
    # finds the night already green both finish having written nothing, and neither makes a derived
    # number older than its source. A score counts from the moment it STARTS, run in progress
    # included — because the caller asking this question is usually that very run, and comparing
    # against the previous score made every chained run report itself out of order.
    ingest_end = max((f for j, _, f, n in timeline if j in VERBS["ingest"] and f and n > 0),
                     default=None)
    score_start = max((s for j, s, _, _ in timeline if j in VERBS["score"]), default=None)
    out_of_order = bool(ingest_end and score_start and ingest_end > score_start)

    bad = [f"{j} {s}" for j, s, _ in recent if s in ("red", "amber")]
    price_bad = [x for x in bad if x.split()[0] in PRICE_CRITICAL]
    stale = (dt.date.today() - last_bar).days if last_bar else 999
    if stale > stale_days:
        return f"⚠️ bars stale — last close {last_bar} ({stale}d) · {line}", False
    if price_bad:
        return (f"⚠️ {', '.join(sorted(set(price_bad)))} — data {last_bar}, tickets held · {line}",
                False)
    if out_of_order:
        return (f"⚠️ chain out of order — an ingest landed rows after the score beside it "
                f"({ingest_end.astimezone(dt.timezone.utc):%H:%M} > "
                f"{score_start.astimezone(dt.timezone.utc):%H:%M} UTC); data {last_bar}, "
                f"tickets held · {line}", False)
    if bad:
        return (f"data {last_bar} close · {line} · {', '.join(sorted(set(bad)))} "
                f"(that domain only)", True)
    return f"data {last_bar} close · {line}", True


def data_date(cur):
    """The date the world is on — the newest stock bar (§5.6: stale means the bars, not the clock).

    Stock bars only, for the same reason `freshness` reads them: FX and the index ride the same
    nightly pull, so a half-failed ingest that landed USDCAD and no equities would otherwise report
    a date the equities never reached.
    """
    cur.execute("""select max(p.d) from prices p join universe u on u.ticker = p.ticker
                   where u.kind = 'stock'""")
    return cur.fetchone()[0]


def next_session(after):
    """The next NYSE session strictly after `after`, weekends removed.

    Deliberately weekend-only, exactly like `signals.trading_days_between`: we hold no holiday
    calendar, and inventing one here would silently narrow §3.3's blackout somewhere else. Naming a
    market holiday as the served session is cosmetic — the next chain re-derives it — while a
    narrowed blackout is real money.
    """
    d = after + dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def session_date_for(cur):
    """The market session an output composed now actually serves (§4.2 clock convention, WO-6).

    `now()::date` in UTC is not that session. The chain runs at 02:00–03:00 UTC, which is the
    previous evening in New York and in Vancouver: on 2026-08-06 at 05:22 UTC the last close was
    2026-08-05 and the brief served the 2026-08-06 open — and it was stamped 2026-08-07, one
    session ahead of the market it was written for. The data date knows what the brief serves; the
    wall clock does not.
    """
    dd = data_date(cur)
    return next_session(dd) if dd is not None else dt.date.today()


def scheduled_run():
    """True only when GitHub's clock started this run.

    Every work-guard in the system exists for one reason: to stop a *scheduled* firing from
    redoing work that is already done. None of them exists to argue with a person. So a hand
    dispatch is never guarded — pressing "Run workflow" means run it, and having to remember a
    `force` checkbox first is the guard thwarting the human it was built to serve.

    Local runs and tests report no event at all, and they are hand runs too.
    """
    return os.environ.get("GITHUB_EVENT_NAME") == "schedule"


def chain_already_current(conn, hb, job, *, must_match=()):
    """§4.2 / WO-6 — a chained job verifies and exits when its own last word still stands.

    The 03:00 ingest correctly reads the runs table and exits when the night is already green
    (§4.2), and then the chain behind it recomputed the whole world anyway: a second full `score`
    and a second `preopen` row, 17 minutes apart, describing an identical universe. Idempotent is
    not the same as free.

    The test is the one §4.2 already uses, one level down: this job has a green non-dry run whose
    **data date** is the data date now, and no ingest has landed a row since that run began. Either
    condition failing means the world moved and the recompute is owed — which is what keeps the
    Saturday chain honest, where `ingest-filings` lands fundamentals against yesterday's bars.

    Only fires on a chained run (`workflow_run`). A human dispatching the chain by hand wants it
    to run; so does a local test, so does the scheduled ingest itself.
    """
    with conn.cursor() as cur:
        today = data_date(cur)
    hb.detail["data_date"] = str(today) if today else None
    if dry() or today is None:
        return False
    forced = os.environ.get("CHAIN_SKIP_IF_CURRENT", "").lower() in ("1", "true", "yes")
    if not forced and os.environ.get("GITHUB_EVENT_NAME") != "workflow_run":
        return False
    with conn.cursor() as cur:
        cur.execute("""select id, started_at, detail from runs
                        where job=%s and status='green' and not dry_run
                          and finished_at is not null and id <> %s
                        order by id desc limit 1""", (job, hb.id))
        row = cur.fetchone()
        if not row:
            return False
        prev_id, prev_started, detail = row
        detail = detail if isinstance(detail, dict) else {}
        if detail.get("data_date") != str(today):
            return False
        if any(detail.get(k) != v for k, v in dict(must_match).items()):
            return False
        cur.execute("""select count(*) from runs
                        where job = any(%s) and not dry_run and finished_at is not null
                          and coalesce(rows_written, 0) > 0 and finished_at > %s""",
                    (list(VERBS["ingest"]), prev_started))
        if cur.fetchone()[0]:
            return False
    hb.detail["skipped"] = (f"data {today} was already scored by run {prev_id}, and no ingest has "
                            f"landed a row since — verified and exited rather than recomputing an "
                            f"unchanged world (§4.2, WO-6)")
    hb.detail["verified_against_run"] = prev_id
    # Carry the previous run's answers forward. `v_session_payload` reads the NEWEST row of a job,
    # so a skip row that says nothing would blank the freshness line and the pre-flight for every
    # reader downstream — a quiet exit must not be quieter than the run it stands in for.
    for k in ("freshness", "blocks_dispatch", "preflight", "amber", "session_date"):
        if k in detail:
            hb.detail.setdefault(k, detail[k])
    print(f"{job}: green — data {today} already current (run {prev_id}); nothing to redo")
    return True


class Heartbeat:
    """with Heartbeat(conn, 'daily') as hb: ...  — opens a running row, closes it green,
    or red with the traceback if the body raises. hb.detail / hb.calls / hb.rows are yours."""

    def __init__(self, conn, job, dry_run=None, scheduled_utc=None):
        self.conn, self.job = conn, job
        self.dry_run = dry() if dry_run is None else dry_run
        self.scheduled_utc = scheduled_utc
        self.detail, self.calls, self.rows, self.status = {}, [0], 0, "green"

    def _drift(self):
        """§4.2 gives each job a time; Actions gives it a queue. Record the gap and nothing else.

        §4.7, ruled 2026-08-05: **schedule drift is not a half-failure and never turns a job
        amber.** This used to amber past half an hour, and that one line gagged the desk: an
        `ingest-daily` that started 194 minutes late with the bars perfectly current wrote amber,
        `score` inherited it through `freshness()`, and every brief that day carried "tickets
        held" while RS.US and CTS.US sat armed behind a clock. Order is guaranteed by the `needs:`
        chain (§4.2) and currency by the bars; punctuality is guaranteed by nobody, so it is
        recorded as `late_minutes`, printed as `late: <job> +NNNm`, and decides nothing.

        Only scheduled runs are judged; a manual dispatch has no appointment to be late for.
        """
        if not self.scheduled_utc or os.environ.get("GITHUB_EVENT_NAME") != "schedule":
            return
        try:
            hh, mm = (int(x) for x in self.scheduled_utc.split(":"))
        except (TypeError, ValueError):
            return
        now = dt.datetime.now(dt.timezone.utc)
        due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now - due > dt.timedelta(hours=12):        # fired just before midnight for a morning slot
            due += dt.timedelta(days=1)
        elif due - now > dt.timedelta(hours=12):
            due -= dt.timedelta(days=1)
        drift = round((now - due).total_seconds() / 60, 1)
        self.detail["schedule"] = dict(due_utc=due.isoformat(), started_utc=now.isoformat(),
                                       drift_minutes=drift)
        if drift > 0:
            self.detail["late_minutes"] = drift

    def __enter__(self):
        with self.conn.cursor() as cur:
            cur.execute("insert into runs(job,status,dry_run) values (%s,'running',%s) returning id",
                        (self.job, self.dry_run))
            self.id = cur.fetchone()[0]
        self.conn.commit()
        self._drift()
        return self

    def amber(self, why):
        if self.status != "red":
            self.status = "amber"
        self.detail.setdefault("amber", []).append(why)

    def red(self, why):
        """A finding severe enough to stop the desk, without pretending the job crashed.

        §4.2 (2026-08-02) gives `check` the power to block a dispatch. A blocking finding is a
        RESULT — the job ran perfectly and the answer was "do not speak" — so it must not be
        reported as a traceback. Red always wins; a later amber cannot downgrade it.
        """
        self.status = "red"
        self.detail.setdefault("red", []).append(why)

    def __exit__(self, et, ev, tb):
        if et is None:
            self.detail["dry_run"] = self.dry_run
            with self.conn.cursor() as cur:
                cur.execute("""update runs set finished_at=now(), status=%s, calls_used=%s,
                               rows_written=%s, detail=%s where id=%s""",
                            (self.status, self.calls[0], 0 if self.dry_run else self.rows,
                             json.dumps(self.detail, default=str), self.id))
            self.conn.commit()
            print(f"{self.job}: {self.status} — {self.rows} rows, {self.calls[0]} calls")
        else:
            self.detail["fatal"] = f"{et.__name__}: {ev}"
            self.detail["trace"] = "".join(traceback.format_exception(et, ev, tb))[-1200:]
            try:
                with self.conn.cursor() as cur:
                    cur.execute("""update runs set finished_at=now(), status='red', calls_used=%s,
                                   detail=%s where id=%s""",
                                (self.calls[0], json.dumps(self.detail, default=str), self.id))
                self.conn.commit()
            except Exception:
                pass
        return False
