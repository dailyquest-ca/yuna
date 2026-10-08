"""§6.4's attestation, against a real database.

§6.5 gates the seed on this record, which makes its failure mode unusual: the dangerous outcome is
not a crash but an attestation that says "match" more readily than the evidence supports. So these
tests check both directions — that a genuine agreement is recorded as one, and that a planted
disagreement is recorded as a divergence and keeps the shadow from passing until it is ruled.
"""
import pathlib
import subprocess
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
import desk                                                               # noqa: E402
import shadow                                                             # noqa: E402
from test_desk import _split, _world                                      # noqa: E402


def test_the_live_engine_and_the_sim_agree_on_real_arrays(db, migrated):
    """The claim `engine.py` exists to make: it IS the rule the cell of record was measured under.
    `test_engine_parity.py` pins it over adversarial synthetic tapes; this pins it end to end,
    through the same tape loader the nightly job uses."""
    with db.cursor() as cur:
        days = _world(cur)
        db.commit()
        rows = shadow.compare(cur, days[-1])

    got = {c: m for c, m, _, _, _ in rows}
    assert got == {"gate": True, "rank": True}
    rank = next(r for r in rows if r[0] == "rank")
    assert rank[4]["first_disagreement_at"] is None
    assert rank[4]["ranked_live"] == rank[4]["ranked_sim"] == 20


def test_a_live_loader_on_another_dollar_volume_basis_is_a_divergence(db, migrated, monkeypatch):
    """QC 2026-10-07, A7. Both sides used to rank on `desk.load`'s dollar volume, so for seven
    weeks live priced §3.2's ADDV as the raw close times split-adjusted volume, the sim's grid as
    the adjusted close times volume, and this comparison attested a match every night: it could
    not see the difference by construction. The sim side now builds its dollar volume from the bars
    the way `concentrated.build_grid` does, so the same defect put back on the live side alone is
    a divergence — named, at rank 1 — and on the code of record's basis the two agree on every
    name's ADDV, not merely on the order."""
    with db.cursor() as cur:
        days = _world(cur)
        # $7M a day through a 2:1 split ten sessions back: below §3.2's $10M floor in truth, $14M
        # under the raw close — which ranks it first
        _split(cur, days, "SPL.US", ratio=2.0, at=len(days) - 10, turnover=7_000_000.0)
        db.commit()

        def raw_close_basis(sessions, tickers, rows):
            """The live loader as it stood until 2026-10-07: dollar volume on the raw close."""
            at = {d: i for i, d in enumerate(sessions)}
            col = {t: j for j, t in enumerate(tickers)}
            adj, raw, dv = (np.full((len(sessions), len(tickers)), np.nan) for _ in range(3))
            for tk, d, a, c, v in rows:
                if d in at:
                    adj[at[d], col[tk]], raw[at[d], col[tk]] = a, c
                    dv[at[d], col[tk]] = c * v if v is not None else np.nan
            return adj, raw, dv

        with monkeypatch.context() as m:
            m.setattr(desk, "grid", raw_close_basis, raising=False)
            broken = next(r for r in shadow.compare(cur, days[-1]) if r[0] == "rank")
        fixed = next(r for r in shadow.compare(cur, days[-1]) if r[0] == "rank")

    assert broken[1] is False, "a live loader on another ADDV basis must read as a divergence"
    assert broken[2][0] == "SPL.US" and "SPL.US" not in broken[3]
    assert broken[4]["first_disagreement_at"] == 1
    assert broken[4]["addv_differs"] >= 1 and "SPL.US" in broken[4]["addv_differs_first"]

    assert fixed[1] is True and "SPL.US" not in fixed[2]
    assert fixed[4]["addv_differs"] == 0, "one basis: every name's ADDV agrees, not only the order"


def test_the_gate_comparison_walks_the_latch_rather_than_reading_a_point(db, migrated):
    """A latch has memory. Asking the sim about session i with a fresh state gives the answer for a
    book that started today — which agrees with the engine by accident on a rising tape and
    disagrees on every recovery."""
    with db.cursor() as cur:
        days = _world(cur, rising=False)
        db.commit()
        rows = shadow.compare(cur, days[-1])
    gate = next(r for r in rows if r[0] == "gate")
    assert gate[1] is True and gate[2] is False and gate[3] is False, "both read OFF, together"


def test_a_divergence_is_written_and_blocks_the_pass_until_it_is_ruled(db, migrated):
    """§6.4: "Pass = 10/10 matches, or every divergence named and ruled." A divergence is not
    resolved by a later matching session — it stays until it carries a ruling."""
    with db.cursor() as cur:
        days = _world(cur)
        db.commit()
        rows = shadow.compare(cur, days[-1])
        planted = [("rank", False, ["A.US"], ["B.US"], {"session": str(days[-1])})]
        shadow.write(cur, days[-1], planted)
        db.commit()

        cur.execute("select * from v_shadow_progress")
        cols = [d[0] for d in cur.description]
        p = dict(zip(cols, cur.fetchone()))
        assert p["divergences"] == 1 and p["unruled"] == 1 and p["passes"] is False

        cur.execute("""update shadow_attestations set ruling = 'ruled: vendor restatement',
                              ruled_at = now() where compared = 'rank'""")
        db.commit()
        cur.execute("select unruled, passes, sessions from v_shadow_progress")
        unruled, passes, sessions = cur.fetchone()
        assert unruled == 0
        assert passes is False, "ruled, but §6.4 also requires ten sessions"
        assert sessions == 1


def test_the_pass_needs_ten_sessions_even_with_no_divergence(db, migrated):
    """§6.4 is "10 sessions", and nine clean nights is not the condition."""
    with db.cursor() as cur:
        days = _world(cur)
        db.commit()
        for d in days[-10:]:
            shadow.write(cur, d, [("gate", True, True, True, {}), ("rank", True, [], [], {})])
        db.commit()
        cur.execute("select sessions, divergences, passes from v_shadow_progress")
        sessions, divergences, passes = cur.fetchone()
    assert (sessions, divergences, passes) == (10, 0, True)


def test_rescoring_a_session_updates_its_attestation_rather_than_adding_one(db, migrated):
    """The chain re-fires on the retry ingest. Two attestations for one session would let a night
    be counted twice toward §6.4's ten."""
    with db.cursor() as cur:
        days = _world(cur)
        db.commit()
        for _ in range(2):
            shadow.write(cur, days[-1], shadow.compare(cur, days[-1]))
        db.commit()
        cur.execute("select count(*) from shadow_attestations where session_date = %s", (days[-1],))
        assert cur.fetchone()[0] == 2, "one row per comparison, not per run"
        cur.execute("select sessions from v_shadow_progress")
        assert cur.fetchone()[0] == 1


def test_the_report_names_what_it_did_not_compare(db, migrated):
    """An attestation that claimed more than it checked would be worse than none, because §6.5
    gates the seed on this record. §3.5's order rule has no second implementation to compare
    against, and the report has to say so where it is read."""
    with db.cursor() as cur:
        days = _world(cur)
        db.commit()
        rows = shadow.compare(cur, days[-1])
        cur.execute("select * from v_shadow_progress")
        cols = [d[0] for d in cur.description]
        p = dict(zip(cols, cur.fetchone()))
    text = shadow.render(str(days[-1]), rows, p)
    assert "NOT compared" in text
    assert "test_engine_book.py" in text and "test_engine_parity.py" in text


def test_the_job_runs_end_to_end(db, migrated):
    with db.cursor() as cur:
        days = _world(cur)
    db.commit()
    out = subprocess.run([sys.executable, str(ROOT / "src" / "shadow.py")],
                         capture_output=True, text=True,
                         env={"DATABASE_URL": migrated, "DB_SSLMODE": "disable",
                              "AS_OF": days[-1].isoformat(), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stdout + out.stderr
    assert "§6.4 progress: 1/10" in out.stdout
    with db.cursor() as cur:
        cur.execute("select status from runs where job='shadow' order by id desc limit 1")
        assert cur.fetchone()[0] == "green"
        cur.execute("select count(*) from shadow_attestations")
        assert cur.fetchone()[0] == 2
