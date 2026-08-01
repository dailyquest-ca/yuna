"""Shared plumbing every job leans on: connection, config, heartbeat, vendor fetch.

Kept deliberately thin — the jobs stay readable, and the heartbeat contract (one runs row
per job, green | amber | red, tracebacks embedded on death) lives in exactly one place.
"""
import os, sys, json, time, traceback, urllib.request, urllib.error
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
        per_ticker[tk] = cad
        per_account[acct] = per_account.get(acct, 0.0) + cad
    book_equities = sum(per_account.values())

    cur.execute("""select distinct on (b.account) b.account, a.kind, b.cash, b.cash_cad,
                          b.cash_usd, b.drawn, b.credit_limit, b.total_value, b.as_of
                   from balances b join accounts a on a.code=b.account
                   order by b.account, b.as_of desc, b.id desc""")
    bal = {r[0]: dict(kind=r[1], cash=r[2], cad=r[3], usd=r[4], drawn=r[5], limit=r[6],
                      total=r[7], as_of=r[8]) for r in cur.fetchall()}

    assets = cash = debt = 0.0
    accounts = {}
    for acct in set(list(per_account) + list(bal)):
        b = bal.get(acct, {})
        if b.get("kind") == "facility":
            debt += float(b.get("drawn") or 0)      # facilities are CAD always
            continue
        # cash per currency is the anchored truth; the USD sleeve reprices with FX daily.
        # Falling back to the deprecated single `cash` column keeps older rows readable.
        if b.get("cad") is not None or b.get("usd") is not None:
            c_cad, c_usd = float(b.get("cad") or 0), float(b.get("usd") or 0)
            c = c_cad + c_usd * fx
        else:
            c_cad, c_usd = float(b.get("cash") or 0), 0.0
            c = c_cad
        value = c + per_account.get(acct, 0.0)      # §2.0: balances anchor, prices extrapolate
        stated = b.get("total")
        accounts[acct] = dict(value_cad=round(value, 2), cash_cad=round(c, 2),
                              cash_native={"CAD": round(c_cad, 2), "USD": round(c_usd, 2)},
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


class Heartbeat:
    """with Heartbeat(conn, 'daily') as hb: ...  — opens a running row, closes it green,
    or red with the traceback if the body raises. hb.detail / hb.calls / hb.rows are yours."""

    DRIFT_AMBER = dt.timedelta(minutes=30)

    def __init__(self, conn, job, dry_run=None, scheduled_utc=None):
        self.conn, self.job = conn, job
        self.dry_run = dry() if dry_run is None else dry_run
        self.scheduled_utc = scheduled_utc
        self.detail, self.calls, self.rows, self.status = {}, [0], 0, "green"

    def _drift(self):
        """§4.2 gives each job a time; Actions gives it a queue. Record what was asked for against
        what happened, and go amber past half an hour.

        A run late enough matters: `nightly-retry` fires an hour after the primary and the evening
        stop sheet reads both windows, so a 3-hour slip silently inverts the ordering the plan
        assumes. Production drifted to 05:23 UTC against an 02:00 spec and nothing said so — the
        cron was right the whole time. Only scheduled runs are judged; a manual dispatch has no
        appointment to be late for.
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
        drift = now - due
        self.detail["schedule"] = dict(due_utc=due.isoformat(), started_utc=now.isoformat(),
                                       drift_minutes=round(drift.total_seconds() / 60, 1))
        if drift > self.DRIFT_AMBER:
            self.amber(f"started {drift.total_seconds() / 60:.0f} min after its "
                       f"{self.scheduled_utc} UTC slot — Actions queueing, not a bad cron")

    def __enter__(self):
        with self.conn.cursor() as cur:
            cur.execute("insert into runs(job,status,dry_run) values (%s,'running',%s) returning id",
                        (self.job, self.dry_run))
            self.id = cur.fetchone()[0]
        self.conn.commit()
        self._drift()
        return self

    def amber(self, why):
        self.status = "amber"
        self.detail.setdefault("amber", []).append(why)

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
