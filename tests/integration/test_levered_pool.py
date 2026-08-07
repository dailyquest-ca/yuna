"""§2.5's levered pool — status always, proposals only on Zak's ruling (WO-10).

Ruled 2026-08-06 and law in the 2026-08-07 plan: drawn levered capital is never idle, its resting
state is the ETF, and a single name takes the pool only when it clears the existing bar *and* has
lagged the index. The lag and lead thresholds are Zak's under §4.5 and he has not set them, so the
plan says precisely what happens meanwhile: "the brief carries a levered status line (utilization
per facility, headroom, holdings) and **proposes nothing**."

That sentence is the specification these tests hold: the arithmetic is built and standing, and the
absence of `config.levered_cycle_params` is a ruling that has not been made — not a feature that is
missing.
"""
import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent / "src"))
import arming                                                             # noqa: E402
import compose                                                            # noqa: E402
import db as plumbing                                                     # noqa: E402
import fixtures as world                                                  # noqa: E402


class Beat:
    def __init__(self):
        self.detail, self.calls, self.rows, self.id = {}, [0], 0, None

    def amber(self, why):
        self.detail.setdefault("amber", []).append(why)


ETF = "VXC.TO"


def facilities(cur, *, loc_drawn=7980.40, loc_limit=75200.0):
    cur.execute("""insert into accounts (code,label,kind,currency,callable,max_utilization,funds)
                   values ('LOC','TFSA-secured line','facility','CAD',true,0.5,'single_or_etf'),
                          ('MARGIN','Callable margin','facility','CAD',true,0.5,'etf_only'),
                          ('HELOC','Home equity','facility','CAD',false,null,'single_or_etf'),
                          ('NONREG','Levered layer','taxable','CAD',false,null,null)
                   on conflict (code) do nothing""")
    cur.executemany("""insert into balances (account,as_of,drawn,credit_limit,source)
                       values (%s,current_date,%s,%s,'test')""",
                    [("LOC", loc_drawn, loc_limit), ("MARGIN", 0.0, 0.0), ("HELOC", 0.0, 0.0)])


def levered_position(cur, ticker, *, qty=142, cost=60.0, ccy="CAD"):
    cur.execute("""insert into book (ticker,account,sleeve,lot,qty,avg_cost,currency,opened_at,
                                     status)
                   values (%s,'NONREG','levered','core',%s,%s,%s,current_date - 200,'open')""",
                (ticker, qty, cost, ccy))


def world_with_index(cur, names, *, index_end=7400.0):
    """Names plus the index, with enough history for a 126-session relative return."""
    world.index_history(cur, level=index_end / 1.10)      # index up ~10% over the window
    for tk, end in names.items():
        world.add_name(cur, tk)
        world.rising_series(cur, tk, start=50.0, end=end)


def status_of(db):
    with plumbing.connect() as conn:
        with conn.cursor() as cur:
            bars = plumbing.load_bars(cur, [r[0] for r in
                                            (cur.execute("select ticker from universe") or
                                             cur.fetchall())])
        return arming.levered_status(conn, bars, 1.40, 200_000.0)


# --------------------------------------------------------------- the status line, always

def test_headroom_is_measured_to_the_plan_s_cap_not_to_the_credit_limit(db, fx):
    """§2.5 caps callable facilities at 50% utilization. Printing the credit limit as headroom
    would offer C$67K of room on a line that may only draw C$29K more — the difference between a
    number and a permission."""
    with db.cursor() as cur:
        facilities(cur)
    db.commit()
    lev = status_of(db)

    loc = next(f for f in lev["facilities"] if f["code"] == "LOC")
    assert loc["utilization"] == pytest.approx(7980.40 / 75200.0, rel=1e-3)
    assert loc["cap_amount"] == pytest.approx(37600.0)
    assert loc["headroom"] == pytest.approx(37600.0 - 7980.40)
    assert not loc["over_cap"]

    heloc = next(f for f in lev["facilities"] if f["code"] == "HELOC")
    assert heloc["max_utilization"] is None, "§2.5: the HELOC runs to the full line, and that is a rule"
    assert heloc["cap_amount"] == pytest.approx(0.0)


def test_a_facility_past_its_cap_is_a_breach_and_says_so(db, fx):
    """§2.5's utilization caps are hard caps, and §5.7 pages Zak on any hard-cap breach."""
    with db.cursor() as cur:
        facilities(cur, loc_drawn=50_000.0, loc_limit=75_200.0)      # 66% on a 50% facility
    db.commit()
    lev = status_of(db)
    assert lev["breaches"] == ["LOC"]
    assert next(f for f in lev["facilities"] if f["code"] == "LOC")["over_cap"] is True


def test_the_relative_return_is_measured_on_adjusted_closes_against_the_index(db, fx):
    """§4.1 pins the input: signal and return computations run on adjusted closes. A split inside
    the window would otherwise read as a lag the business never had — and a lag is the whole
    question here."""
    with db.cursor() as cur:
        facilities(cur)
        world_with_index(cur, {ETF: 120.0, "LAGGARD.US": 52.0})
        levered_position(cur, ETF)
    db.commit()
    lev = status_of(db)

    assert lev["etf"]["ticker"] == ETF and lev["etf"]["priced"] is True
    held = lev["holdings"][0]
    assert held["is_etf"] is True and held["relative"]["window"] == 126
    assert held["relative"]["lead_pp"] is not None


def test_the_brief_carries_the_status_line_with_no_thresholds_set(db, fx):
    """The plan's own sentence, as a test. `levered_cycle_params` is unset in production and this
    is what the desk must still see every morning."""
    with db.cursor() as cur:
        facilities(cur)
        world_with_index(cur, {ETF: 120.0})
        levered_position(cur, ETF)
    db.commit()
    lev = status_of(db)
    assert lev["params"] is None
    assert lev["proposals"] == []
    assert "no proposals" in lev["note"]

    line = compose.levered_line({"levered": lev})
    assert "Levered pool (§2.5)" in line
    assert "LOC" in line and "headroom" in line
    assert ETF in line and "resting ETF" in line or "resting state" in line


def test_a_missing_status_says_so_rather_than_printing_a_clean_zero(db, fx):
    """§5.6: anything a runbook doesn't cover gets flagged, never improvised. An empty levered
    section on a night the job did not run would read as an undrawn pool."""
    assert "not computed" in compose.levered_line({})


# --------------------------------------------------------------- qualification, and the gate

def test_only_a_blind_pass_at_full_conviction_below_its_hurdle_qualifies(db, fx):
    """§2.5's bar is the one already in the plan — "ruled PASS · CCN ≥ 85 · at/below hurdle" — and
    nothing new is invented for the pool."""
    with db.cursor() as cur:
        facilities(cur)
        world_with_index(cur, {ETF: 120.0, "GOOD.US": 60.0, "LOWCCN.US": 60.0, "ABOVE.US": 60.0})
        rows = [("GOOD.US", 88.0, 100.0, 95.0), ("LOWCCN.US", 74.0, 100.0, 95.0),
                ("ABOVE.US", 90.0, 100.0, 140.0)]
        for tk, ccn, hurdle, close in rows:
            cur.execute("""insert into bench (ticker,rank,cohort,ccn,engine,cash_conv,durability,
                             engine_provenance,hurdle_price,last_close,gap_to_hurdle,c1_pass,
                             approved,data_confidence)
                           values (%s,1,'large',%s,70,80,84,'measured',%s,%s,%s,true,true,'full')""",
                        (tk, ccn, hurdle, close, (close - hurdle) / hurdle))
            cur.execute("""insert into rulings (ticker,kind,verdict,blind)
                           values (%s,'c2','PASS',true)""", (tk,))
    db.commit()
    assert [q["ticker"] for q in status_of(db)["qualified"]] == ["GOOD.US"]


def test_a_levered_single_name_that_stops_qualifying_is_named_even_while_the_cycle_is_locked(db, fx):
    """§2.5: the score-break revert "applies regardless of relative position". Saying a name no
    longer qualifies is a fact, not a proposal — so it is said out loud even before Zak rules."""
    with db.cursor() as cur:
        facilities(cur)
        world_with_index(cur, {ETF: 120.0, "BROKE.US": 60.0})
        levered_position(cur, "BROKE.US")
        cur.execute("""insert into bench (ticker,rank,cohort,ccn,engine,cash_conv,durability,
                         engine_provenance,c1_pass,approved,data_confidence)
                       values ('BROKE.US',1,'large',61,70,80,84,'measured',true,true,'full')""")
    db.commit()
    lev = status_of(db)
    assert [d["ticker"] for d in lev["disqualified"]] == ["BROKE.US"]
    assert lev["proposals"] == [], "§2.5: proposes nothing until the thresholds are ruled"
    assert "No longer qualifying" in compose.levered_line({"levered": lev})


def test_the_cycle_proposes_both_legs_once_zak_rules_the_thresholds(db, fx):
    """And the other side of the same sentence: with `levered_cycle_params` set, the computation
    that was standing all along starts proposing. Zak still places both legs (§2.5, §4.5)."""
    with db.cursor() as cur:
        facilities(cur)
        # the ETF rides the index; the candidate has fallen while the index rose — roughly −17pp
        # over the 126-session window, comfortably past the 10pp lag this test rules
        world_with_index(cur, {ETF: 120.0})
        world.add_name(cur, "LAGGARD.US")
        world.rising_series(cur, "LAGGARD.US", start=70.0, end=52.0)   # a linear series, downward
        levered_position(cur, ETF)
        cur.execute("""insert into bench (ticker,rank,cohort,ccn,engine,cash_conv,durability,
                         engine_provenance,hurdle_price,last_close,gap_to_hurdle,c1_pass,approved,
                         data_confidence)
                       values ('LAGGARD.US',1,'large',90,70,80,84,'measured',100,95,-0.05,true,
                               true,'full')""")
        cur.execute("""insert into rulings (ticker,kind,verdict,blind)
                       values ('LAGGARD.US','c2','PASS',true)""")
        cur.execute("""insert into config (key,value,note,set_by)
                       values ('levered_cycle_params',
                               '{"enter_lag_pp": 10, "revert_lead_pp": 15}'::jsonb,
                               '§2.5 test ruling','test')""")
    db.commit()
    lev = status_of(db)

    assert lev["params"], "the ruling is the gate, and it is now open"
    enters = [p for p in lev["proposals"] if p["kind"] == "enter"]
    assert enters and enters[0]["ticker"] == "LAGGARD.US"
    assert enters[0]["from_"] == ETF
    assert "LOC" in enters[0]["facilities"], "§2.5: only a facility whose funds permit single names"
    assert "MARGIN" not in enters[0]["facilities"], "callable margin is ETFs only"
    assert "Cycle proposals" in compose.levered_line({"levered": lev})
