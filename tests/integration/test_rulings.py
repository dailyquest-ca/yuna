"""The rulings ledger, read the way the desk writes it (WO-1, WO-3, WO-7 · 2026-08-07).

One defect underlies all three, and it is small enough to be embarrassing: verdicts are prose —
`PASS`, `ESCALATE`, `QUARANTINE — owner-cash (§3.1), not entry-eligible; PASS/FAIL deferred to R5` —
and every reader in the system asked `verdict in ('pass','fail')`. Sixty-eight logged rulings were
therefore invisible. The payload called 44 already-ruled names unruled, the nightly armed a name
ruling 66 had quarantined, and every growth-derived candidate sat behind a §3.3 sign-off the ledger
had already granted.

So these tests write verdicts the way a session writes them — capitalised, with prose after them —
because a test that writes `'pass'` would have passed against the broken code.
"""
import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import score                                                              # noqa: E402
import fixtures as world                                                  # noqa: E402


@pytest.fixture(autouse=True)
def only_the_arming_half(monkeypatch):
    monkeypatch.setattr(score, "score_bench", lambda conn, hb: None)
    monkeypatch.setattr(score.rank, "run", lambda conn, hb: None)


def run():
    assert score.main() == 0


def rule(cur, ticker, verdict, *, kind="c2", at=None, blind=True, reverses=None, memo=None):
    """A ruling, written the way R1 and R5 actually write one."""
    cur.execute("""insert into rulings (ticker, kind, verdict, blind, memo, at, reverses)
                   values (%s,%s,%s,%s,%s,coalesce(%s, now()),%s) returning id""",
                (ticker, kind, verdict, blind, memo, at, reverses))
    return cur.fetchone()[0]


def bench_row(cur, ticker, *, ccn=78.0, hurdle=100.0, close=95.0, approved=False,
              provenance="growth-derived", confidence="flagged", suspect=False):
    """A bench row. `approved` is seeded only so a test can prove the job CORRECTS it — the live
    value is derived from the ruling every run (migration 036), so a test that wants an armable
    name logs a blind PASS rather than setting a flag."""
    cur.execute("""insert into bench (ticker, rank, cohort, ccn, engine, cash_conv, durability,
                                      engine_provenance, hurdle_price, last_close, gap_to_hurdle,
                                      fcf_yield, engine_growth, fair_multiple, c1_pass, approved,
                                      data_confidence, owner_fcf_suspect)
                   values (%s,1,'large',%s,70,80,84,%s,%s,%s,%s,0.05,0.08,25,true,%s,%s,%s)
                   on conflict (ticker) do update set approved=excluded.approved,
                     data_confidence=excluded.data_confidence,
                     engine_provenance=excluded.engine_provenance,
                     owner_fcf_suspect=excluded.owner_fcf_suspect""",
                (ticker, ccn, provenance, hurdle, close, (close - hurdle) / hurdle,
                 approved, confidence, suspect))


def filing(cur, ticker, *, filed="2026-05-01", confidence="flagged"):
    """A fundamentals row, because §3.3's sign-off is dated against the filing it signs off on."""
    cur.execute("""insert into fundamentals (ticker, filing_date, period_end, statement_currency,
                                             quote_ok, data_confidence, market_cap, fcf_ttm,
                                             c1_pass, fiscal_years)
                   values (%s,%s,%s,'USD',true,%s,1e10,5e8,true,6)
                   on conflict (ticker, filing_date) do nothing""",
                (ticker, filed, filed, confidence))


def armed(conn, ticker, kind=None):
    q = "select kind, blocked_by, note, detail from armed where ticker=%s"
    args = [ticker]
    if kind:
        q += " and kind=%s"; args.append(kind)
    with conn.cursor() as cur:
        cur.execute(q, args)
        return [dict(zip(("kind", "blocked_by", "note", "detail"), r)) for r in cur.fetchall()]


def payload(conn, field):
    with conn.cursor() as cur:
        cur.execute(f"select {field} from v_session_payload")
        return cur.fetchone()[0] or []


# --------------------------------------------------------------- the canonical verdict (034)

def test_a_written_verdict_canonicalises_to_its_leading_word(db):
    """The leading word decides. "QUARANTINE — … PASS/FAIL deferred to R5" is a quarantine, which
    is exactly why a substring scan is the wrong tool and the first token is the right one."""
    with db.cursor() as cur:
        cur.execute("""select yuna_verdict('PASS'),
                              yuna_verdict('QUARANTINE — owner-cash (§3.1), not entry-eligible; '
                                           'PASS/FAIL deferred to R5'),
                              yuna_verdict('ESCALATE'), yuna_verdict('fail'),
                              yuna_verdict('KEEP — assigned to compounders'),
                              yuna_verdict(null)""")
        assert cur.fetchone() == ("pass", "quarantine", "escalate", "fail", "keep", None)


def test_latest_ruling_wins_and_a_reversal_is_not_the_latest_word(db):
    """§3.1: a logged verdict is overturned only by the cooldown escape clause or a logged reversal.
    So the live ruling is the newest row nothing has reversed — and a later QUARANTINE beats an
    earlier PASS by being later, which is the whole of WO-1's third clause."""
    with db.cursor() as cur:
        world.add_name(cur, "QQQ.US")
        rule(cur, "QQQ.US", "PASS", at="2026-08-01")
        rule(cur, "QQQ.US", "QUARANTINE — owner-cash (§3.1)", at="2026-08-06")
        cur.execute("select verdict_canon, decides from v_rulings_latest_c2 where ticker='QQQ.US'")
        assert cur.fetchone() == ("quarantine", True)

        bad = rule(cur, "QQQ.US", "FAIL", at="2026-08-07")
        rule(cur, "QQQ.US", "REVERSAL — wrong name", at="2026-08-07", reverses=bad)
        cur.execute("select verdict_canon from v_rulings_latest_c2 where ticker='QQQ.US'")
        assert cur.fetchone()[0] == "quarantine", "a reversed row is not anybody's latest word"


def test_an_escalation_is_a_question_not_a_ruling(db):
    """§5.6: 'when Yuna's confidence is genuinely low, she asks Zak instead of ruling'. TSM has sat
    in exactly this state since 2026-08-06 — escalated and held unruled."""
    with db.cursor() as cur:
        world.add_name(cur, "EEE.US")
        rule(cur, "EEE.US", "ESCALATE")
        cur.execute("select verdict_canon, decides from v_rulings_latest_c2 where ticker='EEE.US'")
        assert cur.fetchone() == ("escalate", False)


# --------------------------------------------------------------- WO-1 · the sign-off lives in rulings

def test_a_growth_derived_name_with_a_blind_c2_pass_arms_unblocked(db, fx):
    """Ruled by Zak 2026-08-06: for a growth-derived name the blind C2 PASS ruling IS §3.3's manual
    sign-off. Before this, `score` armed every growth-derived entry behind a gate nothing could
    open — 13 of the 19 rows armed that night were stuck on it."""
    with db.cursor() as cur:
        world.add_name(cur, "BKNG.US")
        world.flat_then_base(cur, "BKNG.US", level=95.0)
        world.gate(cur)
        world.balances(cur)
        filing(cur, "BKNG.US")
        bench_row(cur, "BKNG.US")
        rule(cur, "BKNG.US", "PASS", memo="scale strengthens it; the next dollar earns >20%")
    db.commit()
    run()

    entry = armed(db, "BKNG.US", "entry")
    assert entry, "an approved name below its hurdle must reach the desk"
    assert entry[0]["blocked_by"] is None, entry[0]["blocked_by"]
    assert "sign-off" not in (entry[0]["blocked_by"] or "")
    assert entry[0]["detail"]["ruling_id"] is not None, "the row cites the ruling that opened it"


def test_only_a_blind_pass_counts(db, fx):
    """§3.3 (2026-08-06) says the **blind** C2 PASS ruling is the sign-off, and the adjective is
    load-bearing. §3.1's rulings law exists so the business verdict is recorded before price, gap
    or CCN is revealed — a verdict the number got to argue with is not one the machine acts on.

    Since migration 036 that bites a level earlier than the sign-off: a non-blind PASS does not
    approve the name at all, so it never reaches the arming stage. One rule, enforced once."""
    with db.cursor() as cur:
        world.add_name(cur, "SGT.US")
        world.flat_then_base(cur, "SGT.US", level=95.0)
        world.gate(cur)
        world.balances(cur)
        filing(cur, "SGT.US")
        bench_row(cur, "SGT.US")
        rule(cur, "SGT.US", "PASS", blind=False)
    db.commit()
    run()
    assert armed(db, "SGT.US", "entry") == []
    with db.cursor() as cur:
        cur.execute("select approved, c2_status from bench where ticker='SGT.US'")
        assert cur.fetchone() == (False, "pass"), (
            "the verdict is recorded faithfully; it just does not open the gate")


def test_a_name_with_no_ruling_never_reaches_the_arming_stage(db, fx):
    """§3.1: "No ticket ever ships for an unruled name." Approval is derived from the ruling now
    (migration 036), so an unruled name is not approved and never arms — it reaches the desk on
    the docket instead, which is the route §3.1 actually names."""
    with db.cursor() as cur:
        world.add_name(cur, "NRL.US")
        world.flat_then_base(cur, "NRL.US", level=95.0)
        world.gate(cur)
        world.balances(cur)
        filing(cur, "NRL.US")
        bench_row(cur, "NRL.US")
    db.commit()
    run()

    assert armed(db, "NRL.US", "entry") == []
    assert {u["ticker"] for u in payload(db, "unruled_at_the_line")} == {"NRL.US"}
    with db.cursor() as cur:
        cur.execute("select approved from bench where ticker='NRL.US'")
        assert cur.fetchone()[0] is False, "no ruling, no approval — the job derives it"


def test_a_growth_derived_name_ruled_escalate_is_not_signed_off(db, fx):
    """An escalation is a question for Zak (§5.6). A question does not open a gate."""
    with db.cursor() as cur:
        world.add_name(cur, "ESC.US")
        world.flat_then_base(cur, "ESC.US", level=95.0)
        world.gate(cur)
        world.balances(cur)
        filing(cur, "ESC.US")
        bench_row(cur, "ESC.US")
        rule(cur, "ESC.US", "ESCALATE — statement currency unresolved")
    db.commit()
    run()

    assert armed(db, "ESC.US", "entry") == [], "a question is not a PASS, so nothing is approved"
    assert {u["ticker"] for u in payload(db, "escalated_awaiting_zak")} == {"ESC.US"}


def test_a_two_of_three_name_needs_an_explicit_signoff_ruling(db, fx):
    """WO-1 clause 2: the data-confidence route is not the growth-derived route. A name scored on
    2 of 3 needs a logged `signoff`, dated on or after the filing whose numbers it signs off on —
    an older sign-off signed off on older numbers."""
    with db.cursor() as cur:
        world.add_name(cur, "TOT.US")
        world.flat_then_base(cur, "TOT.US", level=95.0)
        world.gate(cur)
        world.balances(cur)
        filing(cur, "TOT.US", filed="2026-05-01")
        bench_row(cur, "TOT.US", provenance="measured", confidence="2of3")
        rule(cur, "TOT.US", "PASS")     # approves the name — but a C2 pass is not THIS sign-off
        rule(cur, "TOT.US", "SIGNOFF", kind="signoff", at="2026-04-01")   # and this one is stale
    db.commit()
    run()
    entry = armed(db, "TOT.US", "entry")[0]
    assert "sign-off" in entry["blocked_by"] and "2026-05-01" in entry["blocked_by"]

    with db.cursor() as cur:
        cur.execute("truncate armed")
        rule(cur, "TOT.US", "SIGNOFF — checked the two components by hand", kind="signoff",
             at="2026-05-02")
    db.commit()
    run()
    assert armed(db, "TOT.US", "entry")[0]["blocked_by"] is None


# --------------------------------------------------------------- WO-7 · quarantine binds the machine

def test_a_quarantined_name_arms_no_entry_and_no_add(db, fx):
    """Ruling 66 (2026-08-06) quarantines DLO's owner cash — §3.1: scored, ranked, watched, **never
    ticketed**. Never means never: not blocked-but-printed, which is still a row a session has to
    reason about, and not only entries, because an add is a ticket too."""
    with db.cursor() as cur:
        world.add_name(cur, "DLO.US")
        world.flat_then_base(cur, "DLO.US", level=95.0)
        world.gate(cur)
        world.balances(cur)
        filing(cur, "DLO.US")
        bench_row(cur, "DLO.US", ccn=86.0)
        rule(cur, "DLO.US", "PASS")                        # a fine business…
        rule(cur, "DLO.US", "QUARANTINE — owner-cash (§3.1): reported FCF is customer float",
             kind="quarantine", blind=False)               # …whose cash is not the owners'
    db.commit()
    run()

    assert armed(db, "DLO.US", "entry") == [], "§3.1: scored, ranked, watched, never ticketed"
    assert armed(db, "DLO.US", "add") == []
    # …and watched means listed, because a name that never arms is otherwise just absent
    assert {w["ticker"] for w in payload(db, "quarantined_watchlist")} == {"DLO.US"}


def test_the_bench_learns_the_quarantine_from_the_ledger(db, fx):
    """`bench.owner_fcf_suspect` was legislated in migration 031 and left for a session to set by
    hand — which §4.0 does not allow, since sessions cannot write the bench at all."""
    with db.cursor() as cur:
        world.add_name(cur, "MEL.US")
        world.flat_then_base(cur, "MEL.US", level=95.0)
        world.gate(cur)
        bench_row(cur, "MEL.US", suspect=False)
        rule(cur, "MEL.US", "QUARANTINE — reported FCF is materially customer float")
    db.commit()
    with score.connect() as conn:
        score.apply_rulings_to_bench(conn, _hb())
    with db.cursor() as cur:
        cur.execute("select owner_fcf_suspect from bench where ticker='MEL.US'")
        assert cur.fetchone()[0] is True


def test_a_later_pass_does_not_lift_a_quarantine_but_a_reversal_does(db, fx):
    """The asymmetry that matters, and the one that would have done damage.

    The quarantine is a finding about the balance sheet; the C2 verdict is a finding about the
    business. They are orthogonal — the desk's own DLO ruling reads "QUARANTINE … PASS/FAIL
    deferred to R5" — and four names on the live bench (a card issuer, an HSA custodian, a payroll
    processor and a broker) sit flagged today with a live PASS beside them. A rule that derived the
    flag from the latest verdict would have quietly un-quarantined all four.
    """
    with db.cursor() as cur:
        world.add_name(cur, "AXP.US")
        bench_row(cur, "AXP.US")
        quarantine = rule(cur, "AXP.US", "QUARANTINE — owner-cash: the credit book is the cash",
                          kind="quarantine", blind=False)
        rule(cur, "AXP.US", "PASS — a wonderful business that holds other people's money")
    db.commit()
    with score.connect() as conn:
        score.apply_rulings_to_bench(conn, _hb())
    with db.cursor() as cur:
        cur.execute("select owner_fcf_suspect, approved from bench where ticker='AXP.US'")
        assert cur.fetchone() == (True, True), (
            "two questions, two answers: a fine business whose cash is not the owners'")

    # §3.1's only route for overturning a verdict — no second vocabulary to remember
    with db.cursor() as cur:
        rule(cur, "AXP.US", "REVERSAL — float now priced on the balance sheet",
             kind="quarantine", blind=False, reverses=quarantine)
    db.commit()
    with score.connect() as conn:
        score.apply_rulings_to_bench(conn, _hb())
    with db.cursor() as cur:
        cur.execute("select owner_fcf_suspect from bench where ticker='AXP.US'")
        assert cur.fetchone()[0] is False


def test_approval_follows_the_ruling_in_both_directions(db, fx):
    """The bench maintains itself (migration 036). Approval is not a flag anybody keeps — it is
    "the desk's most recent verdict on this name is a blind PASS", recomputed every run. A FAIL
    withdraws it; §3.1's 12-month cooldown is simply the absence of a newer PASS."""
    with db.cursor() as cur:
        for tk in ("FLD.US", "PSD.US", "BLD.US", "NIL.US"):
            world.add_name(cur, tk)
        bench_row(cur, "FLD.US", approved=True)      # stale flag the job must correct
        bench_row(cur, "PSD.US", approved=False)     # stale flag the job must correct
        bench_row(cur, "BLD.US", approved=True)
        bench_row(cur, "NIL.US", approved=True)
        rule(cur, "FLD.US", "FAIL — the moat is a price umbrella")
        rule(cur, "PSD.US", "PASS")
        rule(cur, "BLD.US", "PASS", blind=False)     # the number got to argue with the judgment
    db.commit()
    with score.connect() as conn:
        score.apply_rulings_to_bench(conn, _hb())
    with db.cursor() as cur:
        cur.execute("select ticker, approved, c2_status from bench order by ticker")
        rows = {t: (a, s) for t, a, s in cur.fetchall()}
    assert rows["PSD.US"] == (True, "pass"), "a blind PASS approves — nobody has to remember to"
    assert rows["FLD.US"] == (False, "fail")
    assert rows["BLD.US"] == (False, "pass"), "§3.1: the verdict has to be blind"
    assert rows["NIL.US"] == (False, "pending"), "never ruled, never approved"


# --------------------------------------------------------------- WO-3 · the docket (obs 113)

def test_a_ruled_name_leaves_the_unruled_docket_and_arrives_with_its_ruling(db, fx):
    """The 2026-08-07 payload listed 44 names as unruled while nearly all carried blind C2 rulings
    from the day before — BKNG, TW, HLNE, DOCS among them. `compose` carried the wrong table into
    the pre-open brief, and that is the "things look blocked" Zak was seeing."""
    with db.cursor() as cur:
        for tk in ("BKNG.US", "TW.US", "HLNE.US"):
            world.add_name(cur, tk)
            world.flat_then_base(cur, tk, level=95.0)
            bench_row(cur, tk)
        world.add_name(cur, "NEW.US")
        world.flat_then_base(cur, "NEW.US", level=95.0)
        bench_row(cur, "NEW.US")                       # never ruled — this one IS the docket
        for tk in ("BKNG.US", "TW.US", "HLNE.US"):
            rule(cur, tk, "PASS")
    db.commit()

    unruled = {u["ticker"] for u in payload(db, "unruled_at_the_line")}
    assert unruled == {"NEW.US"}
    ruled = {r["ticker"]: r for r in payload(db, "ruled_at_the_line")}
    assert set(ruled) == {"BKNG.US", "TW.US", "HLNE.US"}
    assert ruled["TW.US"]["verdict"] == "PASS" and ruled["TW.US"]["ruling_id"]
    assert ruled["TW.US"]["blind"] is True, "R1 cites the ruling, blind flag included"


def test_the_docket_reaches_past_the_hurdle_to_anything_armed(db, fx):
    """§3.1 rules a name before its GTC ships, and the job arms on more than proximity. A name the
    machine proposed and a rule held back still needs its ruling — the old view could only see
    names within 10% of the hurdle."""
    with db.cursor() as cur:
        world.add_name(cur, "FAR.US")
        world.flat_then_base(cur, "FAR.US", level=95.0)
        bench_row(cur, "FAR.US", hurdle=100.0, close=140.0)      # 40% above the line
        cur.execute("""insert into armed (run_id, kind, ticker, sleeve, reason, urgency)
                       values (1,'entry','FAR.US','compounders','hurdle','normal')""")
    db.commit()
    assert {u["ticker"] for u in payload(db, "unruled_at_the_line")} == {"FAR.US"}


def test_an_escalated_name_is_listed_as_a_question_for_zak(db, fx):
    """§5.6's third state, which the old view had no room for: not a ruling Yuna may make, and not
    a docket item she can clear."""
    with db.cursor() as cur:
        world.add_name(cur, "TSM.US")
        world.flat_then_base(cur, "TSM.US", level=95.0)
        bench_row(cur, "TSM.US")
        rule(cur, "TSM.US", "ESCALATE — TWD statements against a USD market cap")
    db.commit()
    assert {u["ticker"] for u in payload(db, "unruled_at_the_line")} == set()
    assert {u["ticker"] for u in payload(db, "escalated_awaiting_zak")} == {"TSM.US"}


class _HB:
    def __init__(self):
        self.detail, self.calls, self.rows, self.id = {}, [0], 0, None

    def amber(self, why):
        self.detail.setdefault("amber", []).append(why)


def _hb():
    return _HB()


def test_a_hold_zone_compounder_is_never_offered_new_money(db, fx):
    """§3.3: "55–69 Hold zone — **no new money**", and §3.1 gives no size band below 70 — a sub-70
    entry has no legislated size to be written at.

    Momentum enforced this line and so did the compounder ADD path; only the entry escaped, and it
    escaped invisibly: until 2026-08-07 every one of these rows was already blocked by a sign-off
    gate nothing could open. The night the gate opened, LMAT armed offerable at CCN 69.2.
    """
    with db.cursor() as cur:
        world.add_name(cur, "LMAT.US")
        world.flat_then_base(cur, "LMAT.US", level=95.0)
        world.gate(cur)
        world.balances(cur)
        filing(cur, "LMAT.US")
        bench_row(cur, "LMAT.US", ccn=69.2)
        rule(cur, "LMAT.US", "PASS")          # ruled, signed off, and still not buyable
    db.commit()
    run()
    entry = armed(db, "LMAT.US", "entry")[0]
    assert "hold zone" in entry["blocked_by"] and "69.2" in entry["blocked_by"]
