"""Coverage the machine has to have, and the slot it should only fill once (WO-4, WO-5, WO-6).

Three defects the desk found on 2026-08-07, none of them a formula:

  * obs 114 — Arcosa reported on 2026-08-05, the `earnings` table never carried the date, so the
    blackout wall showed nothing and the pipeline armed an ACA entry straight through its own print
    on the 6th and the 7th. **Absence of a date is not absence of an event.**
  * obs 116 — VRT closed on the 5th and still printed a HOLD seat, while NUE and RS, the two live
    momentum positions, had none. §3.0: *membership lists never drop a name the book owns.*
  * obs 115 — the 03:00 retry correctly skipped `ingest-daily` and the chain recomputed the whole
    world anyway, leaving two `preopen` rows for one session — and stamping that session a day
    ahead of the market it served.
"""
import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import arming                                                             # noqa: E402
import compose                                                            # noqa: E402
import db as plumbing                                                     # noqa: E402
import rank                                                               # noqa: E402
import score                                                              # noqa: E402
import fixtures as world                                                  # noqa: E402


class Beat:
    def __init__(self):
        self.detail, self.calls, self.rows, self.id = {}, [0], 0, None

    def amber(self, why):
        self.detail.setdefault("amber", []).append(why)


def armed(conn, ticker, kind="entry"):
    with conn.cursor() as cur:
        cur.execute("select blocked_by, note from armed where ticker=%s and kind=%s",
                    (ticker, kind))
        return [dict(zip(("blocked_by", "note"), r)) for r in cur.fetchall()]


# --------------------------------------------------------------- WO-4 · the blackout wall's dates

@pytest.fixture
def arming_only(monkeypatch):
    """Stub the two thirds of `score` these tests are not about. NOT autouse on purpose: the queue
    tests below drive `rank` directly, and a stub reaching them would have made them assert on a
    function that never ran — which it briefly did, and passed the wrong way round."""
    monkeypatch.setattr(score, "score_bench", lambda conn, hb: None)
    monkeypatch.setattr(score.rank, "run", lambda conn, hb: None)


def test_a_name_with_no_report_date_inside_a_quarter_never_arms_clean(db, fx, arming_only):
    """The ACA case, reconstructed. A listed company reports roughly quarterly; a calendar that has
    said nothing about one for 110 days has a hole in it, and a hole is not a clean bill of health.
    """
    with db.cursor() as cur:
        world.add_name(cur, "ACA.US", last_reported_days_ago=None)     # the calendar knows nothing
        world.flat_then_base(cur, "ACA.US")
        world.gate(cur)
        world.candidate(cur, "ACA.US", mcn=82.0)
        world.queued(cur, "ACA.US", trigger=110.0, stop=101.2, mcn=82.0)
        world.balances(cur)
    db.commit()
    assert score.main() == 0

    row = armed(db, "ACA.US")[0]
    assert row["blocked_by"] == "calendar unverified"
    assert "cannot enforce a date it never had" in row["note"]


def test_a_stale_report_date_is_as_blind_as_no_date_at_all(db, fx, arming_only):
    """A date from two quarters ago means a print has plausibly been missed since."""
    with db.cursor() as cur:
        world.add_name(cur, "OLD.US", last_reported_days_ago=200)
        world.flat_then_base(cur, "OLD.US")
        world.gate(cur)
        world.candidate(cur, "OLD.US", mcn=82.0)
        world.queued(cur, "OLD.US", trigger=110.0, stop=101.2, mcn=82.0)
        world.balances(cur)
    db.commit()
    assert score.main() == 0
    assert armed(db, "OLD.US")[0]["blocked_by"] == "calendar unverified"


def test_the_date_being_present_is_what_makes_the_blackout_fire(db, fx, arming_only):
    """WO-4's acceptance, stated the way it reads: with the 8/5 date present, the arming runs on
    the 6th and 7th must produce a blackout block — not a clean entry, and not merely an
    'unverified' one."""
    with db.cursor() as cur:
        world.add_name(cur, "ACA.US", last_reported_days_ago=None)
        world.flat_then_base(cur, "ACA.US")
        world.gate(cur)
        world.candidate(cur, "ACA.US", mcn=82.0)
        world.queued(cur, "ACA.US", trigger=110.0, stop=101.2, mcn=82.0)
        world.balances(cur)
        world.earnings_on(cur, "ACA.US", dt.date.today() + dt.timedelta(days=2))
    db.commit()
    assert score.main() == 0
    assert "blackout" in armed(db, "ACA.US")[0]["blocked_by"]


def test_the_acceptance_query_returns_zero(db, fx, arming_only):
    """WO-4's own SQL, run against the machine's output rather than paraphrased."""
    with db.cursor() as cur:
        for tk, ago in (("HAS.US", 30), ("HASNT.US", None)):
            world.add_name(cur, tk, last_reported_days_ago=ago,
                           industry="Semiconductors" if tk == "HAS.US" else "Software")
            world.flat_then_base(cur, tk)
            world.candidate(cur, tk, mcn=82.0, rank=1 if tk == "HAS.US" else 2)
            world.queued(cur, tk, trigger=110.0, stop=101.2, mcn=82.0,
                         rank=1 if tk == "HAS.US" else 2)
        world.gate(cur)
        world.balances(cur)
    db.commit()
    assert score.main() == 0
    with db.cursor() as cur:
        cur.execute("""select count(*) from armed a where a.kind='entry' and a.blocked_by is null
                        and not exists (select 1 from earnings e where e.ticker=a.ticker
                                          and e.report_date > current_date - 110)""")
        assert cur.fetchone()[0] == 0
        cur.execute("select count(*) from armed where kind='entry' and blocked_by is null")
        assert cur.fetchone()[0] == 1, "and the covered name still arms — this is a guard, not a gag"


# --------------------------------------------------------------- WO-5 · the queue asks the book

def test_the_queue_seats_live_holdings_and_drops_closed_ones(db, fx):
    """§3.0: membership lists never drop a name the book owns. `universe.is_holding` had drifted in
    both directions at once, and nothing in the system was maintaining it."""
    with db.cursor() as cur:
        for tk in ("VRT.US", "NUE.US", "RS.US"):
            world.add_name(cur, tk, holding=(tk == "VRT.US"))    # the stale flag, exactly as found
            world.flat_then_base(cur, tk)
        world.position(cur, "NUE.US")
        world.position(cur, "RS.US")
        cur.execute("""insert into book (ticker,account,sleeve,lot,qty,avg_cost,currency,status,
                                         closed_at)
                       values ('VRT.US','TFSA','momentum','core',0,100,'USD','closed',
                               current_date - 2)""")
        world.index_history(cur)
        world.gate(cur)
        world.balances(cur)
    db.commit()
    with plumbing.connect() as conn:
        rank.run(conn, Beat())

    with db.cursor() as cur:
        cur.execute("select ticker from queue where note='book' order by ticker")
        assert [r[0] for r in cur.fetchall()] == ["NUE.US", "RS.US"]
        # WO-5's acceptance, both halves
        cur.execute("""select (select count(*) from book b where b.qty>0 and b.status='open'
                               and not exists (select 1 from queue q where q.ticker=b.ticker)),
                              (select count(*) from queue q where q.note='book'
                               and not exists (select 1 from book b where b.ticker=q.ticker
                                                 and b.qty>0 and b.status='open'))""")
        assert cur.fetchone() == (0, 0)


def test_the_holding_flag_is_re_derived_from_the_book(db, fx):
    """The flag stays, because score, ingest and the census all read it — but it is a copy now, and
    a copy that cannot drift, because one job rewrites it from the book every night."""
    with db.cursor() as cur:
        for tk in ("VRT.US", "NUE.US"):
            world.add_name(cur, tk, holding=(tk == "VRT.US"))
            world.flat_then_base(cur, tk)
        world.position(cur, "NUE.US")
        world.index_history(cur)
        world.gate(cur)
        world.balances(cur)
    db.commit()
    with plumbing.connect() as conn:
        arming.apply_ledger(conn, Beat())
    with db.cursor() as cur:
        cur.execute("select ticker, is_holding from universe where kind='stock' order by ticker")
        assert dict(cur.fetchall()) == {"NUE.US": True, "VRT.US": False}


# --------------------------------------------------------------- WO-6 · one canonical pass per slot

def test_the_session_date_is_the_market_session_the_brief_serves(db, fx):
    """The chain runs at 02:00–03:00 UTC, which is the previous evening in New York. On the night
    the bars close Wednesday, the brief serves Thursday — `now()::date` in UTC said Friday."""
    wed = dt.date(2026, 8, 5)
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        cur.execute("""insert into prices (ticker,d,close,adj_close,volume)
                       values ('AAA.US',%s,100,100,1000)""", (wed,))
        assert plumbing.session_date_for(cur) == dt.date(2026, 8, 6)
        # …and Friday's close serves Monday, because a weekend is not a session
        cur.execute("""insert into prices (ticker,d,close,adj_close,volume)
                       values ('AAA.US',%s,100,100,1000)""", (dt.date(2026, 8, 7),))
        assert plumbing.session_date_for(cur) == dt.date(2026, 8, 10)


def test_a_chained_rerun_on_unchanged_data_verifies_and_exits(db, fx, monkeypatch, arming_only):
    """§4.2's own rule, one level down: the 03:00 ingest exits when the night is already green, so
    the chain behind it should not recompute a world that has not moved."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_run")
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur)
        world.balances(cur)
    db.commit()
    assert score.main() == 0
    assert score.main() == 0

    with db.cursor() as cur:
        cur.execute("""select status, detail->>'skipped', detail->>'data_date' from runs
                        where job='score' order by id""")
        rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[0][1] is None and rows[1][1] is not None, "the first computes, the second verifies"
    assert all(r[0] == "green" for r in rows), "a verified no-op is green, not amber"
    assert rows[0][2] == rows[1][2] and rows[0][2] is not None


def test_an_ingest_that_landed_rows_makes_the_recompute_owed(db, fx, monkeypatch, arming_only):
    """The Saturday chain is why this clause exists: `ingest-filings` lands fundamentals against
    yesterday's bars, so the data date is unchanged and the scores are not."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_run")
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur)
        world.balances(cur)
    db.commit()
    assert score.main() == 0
    with db.cursor() as cur:
        cur.execute("""insert into runs (job,status,dry_run,started_at,finished_at,rows_written)
                       values ('ingest-filings','green',false,now(),now(),412)""")
    db.commit()
    assert score.main() == 0
    with db.cursor() as cur:
        cur.execute("select count(*) from runs where job='score' and detail->>'skipped' is not null")
        assert cur.fetchone()[0] == 0, "new rows landed — the recompute is owed"


def test_a_hand_dispatched_chain_always_recomputes(db, fx, monkeypatch, arming_only):
    """A human who dispatches the chain wants it to run. The guard only fires on a chained run."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        world.flat_then_base(cur, "AAA.US")
        world.gate(cur)
        world.balances(cur)
    db.commit()
    assert score.main() == 0 and score.main() == 0
    with db.cursor() as cur:
        cur.execute("select count(*) from runs where job='score' and detail->>'skipped' is not null")
        assert cur.fetchone()[0] == 0


def test_a_skipped_run_carries_the_report_forward(db, fx, monkeypatch):
    """`v_session_payload` reads the NEWEST row of a job, so a quiet exit must not be quieter than
    the run it stands in for — otherwise the freshness line and the pre-flight blank out."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_run")
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        cur.execute("""insert into prices (ticker,d,close,adj_close,volume)
                       values ('AAA.US',current_date,100,100,1000)""")
        cur.execute("""insert into runs (job,status,dry_run,started_at,finished_at,rows_written,
                                         detail)
                       values ('check','green',false,now()-interval '1 hour',now(),0,
                               %s::jsonb)""",
                    ('{"data_date": "%s", "freshness": "data close · all green",'
                     ' "blocks_dispatch": []}' % dt.date.today(),))
    db.commit()
    with plumbing.connect() as conn:
        hb = Beat()
        hb.id = -1
        assert plumbing.chain_already_current(conn, hb, "check") is True
        assert hb.detail["freshness"] == "data close · all green"
        assert hb.detail["blocks_dispatch"] == []


def test_one_preopen_row_per_session_when_nothing_changed(db, fx):
    """WO-6's acceptance. `briefs` stays an append ledger — a correction is still a new row — but a
    second chain with nothing new to say adds nothing."""
    hb = Beat()
    with db.cursor() as cur:
        world.add_name(cur, "AAA.US")
        cur.execute("""insert into prices (ticker,d,close,adj_close,volume)
                       values ('AAA.US',current_date,100,100,1000)""")
        session = plumbing.session_date_for(cur)
        for _ in range(3):
            compose.publish(cur, hb, "preopen", session, "fresh", "**NAV:** $200,000")
        cur.execute("""select session_date, count(*) from briefs where kind='preopen'
                       group by 1 having count(*) > 1""")
        assert cur.fetchall() == []
        cur.execute("select session_date from briefs where kind='preopen'")
        assert cur.fetchone()[0] == session
