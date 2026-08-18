"""Can a chat session write, and has it ever? Read-only.

Zak, 2026-08-18: *"Any changes and transactions I was communicating to the Yuna chat session wasn't
being taken in by the system."*

The first instinct was that `reconcile` never folded what the sessions wrote. That gap was real and
is fixed — but a dry run against production then reported **nothing stranded**: no ticket carrying
a fill, no unapplied receipt. Nothing to fold means nothing was written, and a fold cannot be the
reason a write is missing.

So this probes the write path itself, from the database's side, and reports four things:

  1. does the `yuna_session` role exist
  2. what may it actually write — §4.3's list is briefs, tickets, observations, rulings, learnings,
     config, and a grant that is missing is a silent refusal
  3. is row-level security going to stop it even where the grant exists
  4. **has anything a session could only have written ever appeared** — the evidence, as opposed to
     the permission

(4) is the one that settles it. Every ticket `sheet.py` writes carries a `session_date` and starts
at `proposed`; only a session advances one to `approved` and only a session puts `fill_*` on it. If
the store has never seen an approved ticket or a ticket fill, no session has ever written here —
whatever the grants say.

`docs/roadmap-2026-07-31.md` flagged this as the one step blocked on Zak: *"the current Supabase MCP
connector is read-only (`cannot execute INSERT in a read-only transaction`), so no session can write
its brief yet. Zak gives `yuna_session` a password + login in the dashboard and repoints the
connector at it."* Nothing since has recorded that being done. This job says whether it was.

READ-ONLY. No INSERT, UPDATE, DELETE or COMMIT.

    DATABASE_URL=... python src/session_probe.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from db import connect                                                     # noqa: E402

# §4.3's session write list, 2026-08-04. A session that cannot write one of these cannot do the job
# the plan gives it, and the failure is silent from the chat's side.
SESSION_WRITES = ("briefs", "tickets", "observations", "rulings", "learnings", "config")


def main():
    with connect() as conn:
        with conn.cursor() as cur:
            print("=== 1. the role ===")
            cur.execute("""select rolname, rolcanlogin, rolvaliduntil
                             from pg_roles where rolname = 'yuna_session'""")
            role = cur.fetchone()
            if not role:
                print("  yuna_session DOES NOT EXIST — no session can write anything, and every")
                print("  attempt fails on the connector rather than in this database.")
            else:
                name, can_login, until = role
                print(f"  {name}: can_login={can_login}  valid_until={until or 'never'}")
                if not can_login:
                    print("  ** the role cannot LOG IN. Grants are irrelevant until it can — this")
                    print("     is the step docs/roadmap-2026-07-31.md left with Zak. **")

            print("\n=== 2. what it may write (§4.3's list) ===")
            for t in SESSION_WRITES:
                cur.execute("""select string_agg(privilege_type, ',' order by privilege_type)
                                 from information_schema.role_table_grants
                                where grantee = 'yuna_session' and table_name = %s""", (t,))
                got = cur.fetchone()[0]
                mark = "✓" if got and "INSERT" in got else "✗"
                print(f"  {mark} {t:<14} {got or '(no grant at all)'}")

            print("\n=== 3. row-level security ===")
            cur.execute("""select c.relname, c.relrowsecurity,
                                  (select count(*) from pg_policies p
                                    where p.tablename = c.relname) as policies
                             from pg_class c join pg_namespace n on n.oid = c.relnamespace
                            where n.nspname = 'public' and c.relname = any(%s)
                            order by c.relname""", (list(SESSION_WRITES),))
            for name, rls, policies in cur.fetchall():
                note = ""
                if rls and not policies:
                    note = "  ** RLS on with NO policy — every write is refused **"
                print(f"  {name:<14} rls={rls}  policies={policies}{note}")

            print("\n=== 4. has a session ever written? (the evidence, not the permission) ===")
            # Each of these is something ONLY a session produces. `sheet.py` writes every engine
            # ticket as `proposed` with a session_date and never advances one; only Zak's word,
            # through a session, makes a ticket `approved` or puts a fill on it.
            probes = [
                ("tickets advanced past `proposed`",
                 "select count(*) from tickets where state in ('approved','executed','reconciled')"),
                ("tickets carrying a fill",
                 "select count(*) from tickets where fill_price is not null"),
                ("tickets with no session_date (hand-written, not from `sheet`)",
                 "select count(*) from tickets where session_date is null"),
                ("transactions",           "select count(*) from transactions"),
                ("observations",           "select count(*) from observations"),
                ("rulings",                "select count(*) from rulings"),
                ("config rows set_by='zak'", "select count(*) from config where set_by = 'zak'"),
            ]
            for label, sql in probes:
                cur.execute(sql)
                print(f"  {cur.fetchone()[0]:>6}  {label}")

            cur.execute("""select max(at) from (
                             select updated_at as at from tickets
                              union all select at from observations
                              union all select set_at from config where set_by = 'zak') x""")
            print(f"\n  newest write on any session-owned surface: {cur.fetchone()[0]}")

    print("\nsession_probe: read-only, nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
