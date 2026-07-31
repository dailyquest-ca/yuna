"""Shared plumbing every job leans on: connection, config, heartbeat, vendor fetch.

Kept deliberately thin — the jobs stay readable, and the heartbeat contract (one runs row
per job, green | amber | red, tracebacks embedded on death) lives in exactly one place.
"""
import os, sys, json, time, traceback, urllib.request, urllib.error
import psycopg

EODHD = "https://eodhd.com/api"


def db_url():
    u = os.environ["DATABASE_URL"]
    return u + ("" if "sslmode" in u else ("&" if "?" in u else "?") + "sslmode=require")


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


class Heartbeat:
    """with Heartbeat(conn, 'daily') as hb: ...  — opens a running row, closes it green,
    or red with the traceback if the body raises. hb.detail / hb.calls / hb.rows are yours."""

    def __init__(self, conn, job, dry_run=None):
        self.conn, self.job = conn, job
        self.dry_run = dry() if dry_run is None else dry_run
        self.detail, self.calls, self.rows, self.status = {}, [0], 0, "green"

    def __enter__(self):
        with self.conn.cursor() as cur:
            cur.execute("insert into runs(job,status,dry_run) values (%s,'running',%s) returning id",
                        (self.job, self.dry_run))
            self.id = cur.fetchone()[0]
        self.conn.commit()
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
