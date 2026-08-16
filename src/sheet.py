"""The nightly sheet, written down. §4.1's `score` job for v1.0's engine.

`desk.py` decides; this persists the decision. The split is deliberate and it is the same split
§6.4 depends on: the shadow runs ten sessions producing "order sheets nobody trades", and the only
way that record means anything is if the thing that computes a sheet cannot also be the thing that
quietly fixes one.

    DATABASE_URL=... ENGINE_NAV=200000 python src/sheet.py
    DATABASE_URL=... ENGINE_MODE=shadow AS_OF=2026-08-14 python src/sheet.py

Three tables, one per question the record has to answer later:

  `engine_sessions`  what the gate and the counts were on that close
  `engine_ranks`     §3.3's ordering, score included, for the whole pool
  `tickets`          §4.3's proposals, one per order, state `proposed`

**Nothing here places, modifies or cancels an order** (§0.2). It writes rows in state `proposed`.
Zak approves and executes; `reconcile.py` closes the loop against the broker's receipt.

On NAV. §3.5 sizes at engine NAV / 5 and the store does not hold engine NAV — `nav_snapshots`
carries household NAV in CAD, which is a different number in a different currency. So it is
supplied (env, then a logged `config` row) and never inferred. When it is missing the job still
writes the session, the ranks and every SELL, leaves the buy quantities null, and goes amber:
§5.4 makes exits unblockable and §4.3 already forbids new buy tickets under amber, so an unsized
buy sheet under an amber run is what the plan says this state looks like.
"""
import datetime as dt
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import desk                                                                # noqa: E402
import engine                                                              # noqa: E402
from db import config, connect, dry, Heartbeat                             # noqa: E402

# §2.1 houses the engine in the TFSA and nowhere else, so every ticket it writes names that account
# and that sleeve. Not a default — a placement ruling, quoted.
ACCOUNT = "TFSA"
SLEEVE = "momentum"


def engine_nav(cur):
    """§3.5's "engine NAV", from the two places allowed to state it. None means unknown.

    `ENGINE_NAV` is the dispatch override. `config.engine_nav` is the durable one, and it is a
    logged row with a timestamp — which is what makes a change to it auditable rather than a number
    that moved. Household NAV is deliberately NOT a fallback: `nav_snapshots.nav_cad` is every
    account converted to CAD, and sizing a USD sleeve off it would be wrong by both the FX rate and
    the other two accounts. That is precisely the kind of plausible wrong number that does not
    throw.
    """
    raw = (os.environ.get("ENGINE_NAV") or "").strip()
    if not raw:
        raw = str(config(cur, "engine_nav") or "").strip()
    if not raw:
        return None
    nav = float(raw)
    if nav <= 0:
        raise ValueError(f"engine NAV must be positive; got {nav}")
    return nav


def write_session(cur, s, mode, digest):
    cur.execute("""
        insert into engine_sessions (session_date, gate_on, gate_green, index_close, index_sma,
                                     universe_count, ranked_count, screen_count, marked_equity,
                                     nav, param_digest, mode, detail)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (session_date, mode) do update set
            gate_on = excluded.gate_on, gate_green = excluded.gate_green,
            index_close = excluded.index_close, index_sma = excluded.index_sma,
            universe_count = excluded.universe_count, ranked_count = excluded.ranked_count,
            screen_count = excluded.screen_count, marked_equity = excluded.marked_equity,
            nav = excluded.nav, param_digest = excluded.param_digest,
            detail = excluded.detail, created_at = now()
        returning id""",
        (s["session"], s["gate_on"], s["gate_green"], s["index_close"], s["index_sma"],
         s["universe"], s["ranked"], s["screened"], s["marked_equity"], s["nav"], digest, mode,
         json.dumps({"top": s["top"], "held": s["held"], "unranked": s["unranked"],
                     "unpriced": s["unpriced"]})))
    return cur.fetchone()[0]


def write_ranks(cur, s, mode):
    """§3.3's ordering for the close. Upserted, then the stale tail is deleted.

    The delete matters. A re-run on a session whose universe shrank would otherwise leave the
    dropped names behind at their old ranks, and a rank table with a name the engine no longer
    ranks is worse than no rank table — it reads as a decision.
    """
    rows = [(s["session"], mode, r["ticker"], r["rank"], r["score"], r["mark"], r["addv"])
            for r in s["ranks"] if r["score"] is not None]
    cur.executemany("""
        insert into engine_ranks (session_date, mode, ticker, rank, score, mark, addv)
        values (%s,%s,%s,%s,%s,%s,%s)
        on conflict (session_date, mode, ticker) do update set
            rank = excluded.rank, score = excluded.score, mark = excluded.mark,
            addv = excluded.addv, created_at = now()""", rows)
    cur.execute("""delete from engine_ranks
                    where session_date = %s and mode = %s and not (ticker = any(%s))""",
                (s["session"], mode, [r[2] for r in rows]))
    return len(rows)


def write_tickets(cur, s, mode="live"):
    """§4.3's proposals. One row per order, state `proposed`, idempotent on (close, ticker, action).

    A ticket is only ever written in `proposed`. Nothing in this job may advance a ticket to
    `approved` — that is Zak's word (§0.2, §4.3) — and nothing may advance one to `executed`, which
    is a fact about the broker rather than about the engine.

    Withdrawal is by state, never by delete: a re-run whose decision changed cancels the tickets
    the previous pass proposed and no longer stands behind. The row stays, because "the engine
    proposed this and then withdrew it" is a fact §6.4's shadow has to be able to read.

    **Shadow mode writes no tickets at all**, and that is a correctness fix rather than a policy.
    `engine_sessions` and `engine_ranks` are keyed by (session, mode); tickets are keyed by
    (session, ticker, action) because §4.3 makes the sheet "the only source of engine orders" and a
    ticket carries no mode — Zak either executes it or he does not. A shadow pass over the same
    close would therefore overwrite the live sheet's rows and, worse, WITHDRAW every live ticket
    its own decision did not reproduce. §6.4's shadow is meant to produce "order sheets nobody
    trades"; a proposal sitting in the same queue as ones that should be traded is the opposite.
    """
    if mode != "live":
        return 0, 0
    written = []
    for o in s["orders"]:
        cur.execute("""
            insert into tickets (session_date, ticker, account, sleeve, action, reason, clause,
                                 order_type, qty, mark, rank, state, note)
            values (%s,%s,%s,%s,%s,%s,%s,'market',%s,%s,%s,'proposed',%s)
            on conflict (session_date, ticker, action) where session_date is not null
            do update set qty = excluded.qty, mark = excluded.mark, rank = excluded.rank,
                          clause = excluded.clause, reason = excluded.reason,
                          note = excluded.note, updated_at = now(),
                          -- a ticket Zak has already acted on is not rewritten by a re-run
                          state = case when tickets.state in ('proposed','cancelled')
                                       then 'proposed' else tickets.state end
            returning id""",
            (s["session"], o["ticker"], ACCOUNT, SLEEVE, o["action"], o["clause"], o["clause"],
             o["qty"], o["mark"], o["rank"],
             f"§3.5 {o['clause']}; rank {o['rank'] or '—'} on {s['session']}"))
        written.append(cur.fetchone()[0])

    # §4.3: the sheet is the only source of engine orders, so a proposal this pass did not make is
    # not an order. Withdraw, don't delete.
    cur.execute("""update tickets set state = 'cancelled', updated_at = now(),
                          note = coalesce(note,'') || ' | withdrawn: not on the re-scored sheet'
                    where session_date = %s and state = 'proposed' and not (id = any(%s))""",
                (s["session"], written))
    return len(written), cur.rowcount


def main():
    as_of = os.environ.get("AS_OF", "").strip()
    as_of = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    mode = (os.environ.get("ENGINE_MODE") or "live").strip().lower()
    if mode not in ("live", "shadow"):
        raise SystemExit(f"ENGINE_MODE must be live or shadow; got {mode!r}")

    with connect() as conn, Heartbeat(conn, "score", dry_run=dry()) as hb:
        with conn.cursor() as cur:
            nav = engine_nav(cur)
            s = desk.sheet(cur, as_of, nav)
            digest = engine.digest()
            report = desk.render(s)
            print(report)

            hb.detail.update(session=str(s["session"]), mode=mode, gate=s["gate"],
                             gate_green=s["gate_green"], universe=s["universe"],
                             ranked=s["ranked"], nav=nav, param_digest=digest, top=s["top"],
                             sells=[o["ticker"] for o in s["orders"] if o["action"] == "sell"],
                             buys=[o["ticker"] for o in s["orders"] if o["action"] == "buy"])
            if dry():
                hb.detail["skipped"] = "computed, wrote nothing (DRY_RUN)"
            else:
                write_session(cur, s, mode, digest)
                ranks = write_ranks(cur, s, mode)
                proposed, withdrawn = write_tickets(cur, s, mode)
                conn.commit()
                hb.rows = ranks + proposed
                hb.detail.update(ranks=ranks, proposed=proposed, withdrawn=withdrawn)
            if nav is None:
                # §4.3's amber: no new buy tickets. The rows exist and are unsized, the sells
                # stand (§5.4), and the reason is stated rather than inferred from a null.
                hb.amber("engine NAV unknown — buys written unsized and must not be executed; "
                         "set config.engine_nav or ENGINE_NAV")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
