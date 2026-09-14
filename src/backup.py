"""backup — dump the decisions, compressed, into the repo.

A standing design decision rather than a clause: v1.0 names no backup, the way it names no
heartbeat (README). What it protects is the record nothing else can regenerate — the book, tickets,
transactions, rulings, learnings, briefs, sessions, ranks and the runs ledger. The commit doubles
as GitHub's 60-day schedule keep-alive, so the crons never fall asleep.

**The work is the commit, so the commit happens inside the heartbeat** (2026-09-13). On 2026-09-05
the dump ran, the heartbeat closed green with 3,753,011 rows, and the workflow's separate commit
step was refused by GitHub's pre-receive hook a minute later: 385 MB against a 100 MB file limit.
For the rest of September the ledger then said "backed up" about a file that existed nowhere — the
09-12 firing read that row and exited clean. Now a refused push is the job's own red, with the
server's words in the runs row, and the guard asks the checkout as well as the ledger (learning 64).
"""
import os, sys, glob, gzip, json, subprocess, datetime as dt
from db import connect, scheduled_run, Heartbeat

# What the dump leaves out, and why. Three kinds of table are not decisions:
#   prices           the vendor's bars — re-pullable under §4.5's product (learning 9)
#   the research     every row is reproducible from the bars and the pre-registered work order;
#   grid             `backtest_runs`, the registry of what was run and what it found, is KEPT
#   fundamentals     the retired engine's vendor cache: 6,096 rows of statements, 2.9 GB as JSON.
#                    It alone put the 2026-09-05 dump past GitHub's limit, and §4.5 says no
#                    decision reads it. It cannot be re-pulled since the plan downgrade, so its
#                    absence from the backup is accepted here in the open rather than by a
#                    refused push in silence.
SKIP = {"prices", "fundamentals",
        "backtest_equity", "backtest_trades", "push_study",
        "research_eps", "research_monthly_adj", "research_monthly_raw_contaminated"}
OUT = "backups"
# GitHub refuses any single file over 100 MiB at push time (docs: "About large files on GitHub").
# The 09-05 dump learned that from the pre-receive hook after eight minutes of work; the job now
# learns it here, before it commits anything.
GITHUB_FILE_LIMIT = 100 * 2**20

FORCE = os.environ.get("FORCE", "false").lower() in ("1", "true", "yes")


def utc_today():
    """The runner's clock is UTC and the ledger is compared in UTC; say so rather than assume it."""
    return dt.datetime.now(dt.timezone.utc).date()


def month_file():
    """This calendar month's dump in the checkout, or None. The file is the work; the ledger only
    describes it."""
    files = sorted(glob.glob(f"{OUT}/yuna-{utc_today():%Y-%m}-*.json.gz"))
    return files[-1] if files else None


def month_backed_up(cur):
    """Ruled 2026-08-05: monthly work is guarded by whether it has RUN, never by the date.

    Returns `(ledger_at, path)`: when this month's backup closed green with rows on the runs
    ledger (or None), and the month's file in the checkout (or None). Only both together mean the
    work happened — 2026-09-05 left a green row and no file, and a guard that read the ledger
    alone skipped the next Saturday on the strength of it.
    """
    cur.execute("""select started_at from runs
                    where job in ('backup', 'monthly-backup') and status = 'green'
                      and not dry_run and coalesce(rows_written, 0) > 0
                      and date_trunc('month', started_at at time zone 'utc')
                          = date_trunc('month', now() at time zone 'utc')
                    order by id desc limit 1""")
    row = cur.fetchone()
    return (row[0] if row else None), month_file()


def git(*args):
    """One git command, failing with the server's words rather than an exit code."""
    out = subprocess.run(["git", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {(out.stderr or out.stdout).strip()[-600:]}")
    return out.stdout


def commit(path, stamp):
    """Add, commit and push the dump on the branch the workflow checked out."""
    git("config", "user.name", "yuna-backup[bot]")
    git("config", "user.email", "yuna-backup@users.noreply.github.com")
    git("add", path)
    git("commit", "-m", f"backup: {stamp} (bars, research grid and fundamentals excluded)")
    # the branch may have moved while the dump ran; the dump is a new file, so replaying it on
    # top is trivial, and a push that raced a session's commit is not a data fault worth a red
    git("pull", "--rebase", "--quiet")
    git("push")


def main():
    stamp = utc_today().isoformat()
    with connect() as conn:
        with Heartbeat(conn, "backup", scheduled_utc="14:23") as hb:   # the cron is 23 14 * * 6
            # Ruled 2026-08-05: **monthly work is guarded by whether it has run, never by the
            # date.** This job's guard was a shell step that ran BEFORE the heartbeat opened, so a
            # firing outside the first seven days left no trace at all — the identical shape that
            # hid `ingest-universe`'s absence for a month. Every firing writes a row and asks one
            # question: has this month been backed up? Unbacked → back it up. Backed → exit green,
            # saying which run did it. A missed Saturday is picked up the following week.
            with conn.cursor() as cur:
                # a hand dispatch is never guarded — see db.scheduled_run()
                ledger_at, path = (month_backed_up(cur) if scheduled_run() and not FORCE
                                   else (None, None))
            if ledger_at and path:
                hb.detail.update(stage="guard", backed_up=False, month_backed_up_at=str(ledger_at),
                                 file=path)
                print(f"backup: green — this month was backed up {ledger_at} ({path}); "
                      f"nothing to do")
                return 0
            if ledger_at:
                # The ledger says the month is done and the checkout says otherwise: a push that
                # was refused after a heartbeat had already closed green. The file is the work.
                hb.detail.update(ledger_said=str(ledger_at), file_missing=True)
                print(f"backup: the ledger says {ledger_at} backed this month up, but no file of "
                      f"this month is in the checkout — rebuilding")
            hb.detail["stage"] = "dump"
            with conn.cursor() as cur:
                cur.execute("""select table_name from information_schema.tables
                               where table_schema='public' and table_type='BASE TABLE'
                               order by table_name""")
                tables = [r[0] for r in cur.fetchall() if r[0] not in SKIP]
            dump, total = {}, 0
            with conn.cursor() as cur:
                for t in tables:
                    cur.execute(f'select row_to_json(x) from "{t}" x')
                    rows = [r[0] for r in cur.fetchall()]
                    dump[t] = rows
                    total += len(rows)
                cur.execute("select count(*), max(d) from prices")
                n_bars, last_bar = cur.fetchone()
            dump["_meta"] = {"taken": stamp, "tables": len(tables), "rows": total,
                             "excluded": sorted(SKIP),
                             "prices_excluded": {"rows": n_bars, "last_bar": str(last_bar)}}
            os.makedirs(OUT, exist_ok=True)
            path = f"{OUT}/yuna-{stamp}.json.gz"
            with gzip.open(path, "wt", encoding="utf-8") as f:
                json.dump(dump, f, default=str)
            size = os.path.getsize(path)
            hb.rows = total
            hb.detail.update(path=path, bytes=size, tables=len(tables), excluded=sorted(SKIP),
                             prices_rows=n_bars, prices_excluded=True)
            print(f"backup: {path} — {total} rows across {len(tables)} tables, {size/1024:.0f} KB")
            print(f"  (prices excluded: {n_bars} bars through {last_bar})")
            if size > GITHUB_FILE_LIMIT:
                os.remove(path)          # the checkout holds only dumps GitHub will accept
                raise RuntimeError(f"{path} is {size/2**20:.0f} MiB and GitHub refuses files over "
                                   f"{GITHUB_FILE_LIMIT//2**20} MiB — exclude a table or split the "
                                   f"dump; nothing was committed")
            if hb.dry_run:
                hb.detail["committed"] = False
                print("backup: dry run — the dump is written and not committed")
            elif os.environ.get("GITHUB_ACTIONS") != "true":
                hb.detail["committed"] = False
                print("backup: not in Actions — the dump is written and not committed")
            else:
                hb.detail["stage"] = "commit"
                commit(path, stamp)
                hb.detail["committed"] = True
                print(f"backup: committed and pushed {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
