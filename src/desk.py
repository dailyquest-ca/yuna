"""Tonight's engine decision, from the live tape. §6.3's `score` job and §6.4's shadow, one file.

It loads the universe and the tape, applies `engine.py` — which is §3 and nothing else — and prints
the order sheet Zak executes at the open. **It writes nothing.** Persisting the sheet as tickets is
a separate step, deliberately: §6.4 runs this for ten sessions producing "order sheets nobody
trades", and a job that cannot write cannot contaminate that record.

**Nothing here places, modifies or cancels an order** (§0.2, and `.claude/rules/trading-code.md`).
It proposes; Zak executes; `reconcile` closes the loop against the broker's receipt.

Two things it deliberately does NOT do, because §3.3 forbids them: consult earnings, themes,
fundamentals or news, and second-guess the rank. *"The rank is the entire opinion."*

    DATABASE_URL=... python src/desk.py
    DATABASE_URL=... AS_OF=2026-08-14 python src/desk.py      # any past session, for the shadow
"""
import datetime as dt
import os
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bars                                                               # noqa: E402
import engine                                                             # noqa: E402
from db import STALE_DAYS, cash_by_account, connect                        # noqa: E402

# §3.2: the universe is `.US` common stocks from `universe`, minus `universe_excluded`, minus
# delisted. Every clause of that sentence is in the query below and none of it is inferred.
TAPE = """
    select p.ticker, p.d, coalesce(p.adj_close, p.close), p.close, p.volume
      from prices p
      join universe u on u.ticker = p.ticker
     where u.kind = 'stock'
       and u.ticker like '%%.US'
       and u.status <> 'delisted'
       and not exists (select 1 from universe_excluded e where e.ticker = p.ticker)
       and p.d <= %s
     order by p.ticker, p.d
"""


def load(cur, as_of):
    """The tape as (sessions, tickers, adj, raw, dollar-volume), on the benchmark's own calendar.

    The calendar comes from `SPY.US` rather than from the union of every name's dates. Taking it
    from the union is what put New Year's Day into a research grid, because a handful of junk
    listings print on a day the market is shut — and on a session where nothing real prints, a book
    sells everything (selling carries the last mark) and buys nothing (buying refuses a stale one).
    """
    cur.execute("""select d, coalesce(adj_close, close) from prices
                    where ticker = %s and d <= %s order by d""", (engine.REGIME_SOURCE, as_of))
    bench = cur.fetchall()
    if not bench:
        raise SystemExit(f"no {engine.REGIME_SOURCE} bars at or before {as_of} — no calendar, no run")
    sessions = [r[0] for r in bench]
    index_px = np.array([float(r[1]) for r in bench])
    at = {d: i for i, d in enumerate(sessions)}

    cur.execute(TAPE, (as_of,))
    rows = cur.fetchall()
    tickers = sorted({r[0] for r in rows})
    col = {t: j for j, t in enumerate(tickers)}
    shape = (len(sessions), len(tickers))
    adj, raw, dv = (np.full(shape, np.nan) for _ in range(3))
    for tk, d, a, c, v in rows:
        i = at.get(d)
        if i is None:                       # a print on a day the benchmark did not trade
            continue
        j = col[tk]
        adj[i, j] = float(a)
        raw[i, j] = float(c)
        dv[i, j] = float(c) * float(v) if c is not None and v is not None else np.nan
    return sessions, tickers, adj, raw, dv, index_px


# §2.1's table, verbatim: "TFSA | **The engine** | The engine's five names (+ park when gated
# off)". The account IS the allocation — "there are no percentage targets".
#
# **But the account is a PROXY, not the thing itself.** Zak, 2026-08-18:
#
#   "The sleeve is the purpose of the money. We just set the boundaries as the account for
#    simplicity but one day some of the RRSP may be used for Momentum and maybe some of the TFSA
#    will be used for something else."
#
# So the engine's true set is the momentum SLEEVE, and reading the account works only for as long
# as the two coincide. They coincide today, and §2.1 is why. The day they stop, an account filter
# fails in the direction this repository has already paid for: money whose purpose is momentum,
# sitting in the RRSP, is invisible to the engine — which is exactly the AXTI/MU defect with the
# label swapped for the wrapper. `sleeve_divergence` below is what refuses to let that be silent.
ENGINE_ACCOUNT = "TFSA"
ENGINE_SLEEVE = "momentum"

# §2.1's table read as purpose-per-wrapper: which sleeves the plan currently places in which
# account. NONREG carries two because the plan gives it two — "Reserve + levered layer".
SLEEVES_BY_ACCOUNT = {"TFSA": ("momentum",), "RRSP": ("reserve",), "NONREG": ("reserve", "levered")}

# The two instruments that hold engine capital WITHOUT being an engine slot, each named by the plan
# and neither inferred:
#
#   SPY.US   §8, glossary: "Park — SPY.US, where engine capital sits while gated off." §3.4 sends
#            every exit's proceeds here while the gate reads OFF.
#   SPMO.US  §6.1(3): "TFSA proceeds → SPMO (bridge)", and §6.5: "capital holds in SPMO until the
#            first ON latch, then seeds." A Phase-0 instrument with an end date, not a park.
#
# The distinction is not cosmetic. Both sit in the TFSA, so the account filter above picks them up;
# neither is a `.US` common stock in §3.2's universe, so neither can ever be ranked; and §3.5 sells
# what it cannot rank. Left in the ranked book, the engine proposes selling 810 shares of the
# Phase-0 bridge every single night — moving the capital §6.5 is holding for the seed into cash,
# for the reason that it failed to appear in a stock screen it was never eligible for.
PARKED = (engine.PARK, "SPMO.US")


def sleeve_divergence(cur):
    """Positions whose PURPOSE is not the one §2.1 puts in their account. Returns [dict].

    This is the expiry date on `held_book`'s account filter, made observable. The engine reads the
    account because account and sleeve coincide today; the moment they stop, the filter is wrong
    and nothing about the sheet looks different — the RRSP momentum money is simply absent, and a
    position the engine cannot see is one it can never sell.

    A guard for a condition that has not happened yet is easy to write and easy to write uselessly,
    so this one is checked against today's book rather than imagined: it fires on all three TFSA
    positions right now, because `preseed` and `reserve` are not statements of purpose and Zak's
    own description of that account is "a large Momentum Sleeve". That is a true finding, and the
    fix is Zak relabelling — assigning purpose to money is not a thing this file may infer (§0.3).
    """
    cur.execute("""select account, ticker, sleeve, qty from book
                    where status = 'open' order by account, ticker""")
    return diverging(dict(account=a, ticker=t, sleeve=s, qty=q) for a, t, s, q in cur.fetchall())


def diverging(rows):
    """The same rule over already-read rows, so §0.4's one-read law holds in the brief.

    `brief.render` has a payload and no cursor, deliberately — a session reads `v_session_payload`
    once and then judges, and it never goes back to the tables. The payload's book already carries
    `account` and `sleeve`, so the divergence is derivable from what has been read.
    """
    out = []
    for r in rows:
        expected = SLEEVES_BY_ACCOUNT.get(r["account"])
        if expected is None or r["sleeve"] in expected:
            continue
        out.append(dict(account=r["account"], ticker=r["ticker"], sleeve=r["sleeve"],
                        qty=float(r["qty"]), expected=expected,
                        engine_sees_it=(r["account"] == ENGINE_ACCOUNT),
                        engine_would_see_it=(r["sleeve"] == ENGINE_SLEEVE)))
    return out


def held_book(cur, account=ENGINE_ACCOUNT):
    """Everything the engine holds. §2.1 puts it in the TFSA and gives it the whole account.

    Filtered by ACCOUNT, and that is deliberate, current, and temporary — see the constants above.
    Zak, 2026-08-18: *"We just set the boundaries as the account for simplicity."* The sleeve is
    the purpose of the money and the account is where it happens to sit; today §2.1 makes them the
    same set, and this filter is that coincidence spent knowingly rather than by accident.

    It replaced a `sleeve = 'momentum'` filter, and the reason is worth keeping: 20 shares of AXTI
    and 2 of MU sat in the TFSA tagged `preseed`, invisible to an engine that ranked them 2nd and
    3rd, and the seed would have sized a full NAV/5 slot in each as though none were held. A
    position the engine cannot see is one it can never sell, never count against §3.5's five slots,
    and never net against a buy. The label was not describing purpose, so it could not be trusted
    to select on — and it still is not.

    **Moving this back to the sleeve needs the labels corrected first**, and `sleeve_divergence`
    reports how far off they are. Until then the account is the safer of two imperfect keys,
    because a wrapper cannot be mislabelled.

    Zak, 2026-08-18: *"the momentum play should view the whole book and make a plan for how to
    adjust it to meet the goal portfolio."* This is the whole account; `sheet` splits the park off.
    """
    cur.execute("""select ticker, sum(qty) from book
                    where status = 'open' and account = %s
                    group by ticker having sum(qty) > 0 order by ticker""", (account,))
    return {r[0]: float(r[1]) for r in cur.fetchall()}


def holding_mark(cur, ticker, as_of):
    """One holding's mark: its newest close on or before `as_of`. Returns (close, None), or
    (None, why) when it has none — and says which none, because each is a different repair.

    A close at or below zero is not a mark. The vendor pads a delisting tail with `0.0000` after an
    acquisition (learning 33), and production stores those rows as the last bars of AEL, CONN, HIBB
    and PACW. Read as a price, the padding marked a held name at nothing — a number, so it passed
    the unpriced fail-closed, and NAV lost a whole slot without a word (A15).
    """
    cur.execute("""select d, close from prices where ticker = %s and d <= %s
                    order by d desc limit 1""", (ticker, as_of))
    row = cur.fetchone()
    if row is None:
        return None, f"no bar on or before {as_of}"
    d, close = row
    if close is None:
        return None, f"no close on {d}"
    if float(close) <= 0:
        return None, (f"newest close {float(close):g} on {d} is not a price"
                      + (" — the vendor's delisting padding (learning 33)"
                         if float(close) == 0 else ""))
    return float(close), None


def marked_equity(cur, held, as_of):
    """The sleeve marked at the decision close. Returns (value, [names with no mark]).

    Priced by its own query rather than off the loaded tape, deliberately: a holding that has left
    §3.2's universe — excluded, or delisted — has no column there, and marking it at zero would
    read as a drawdown when it is a data boundary. §5.2's milestones are computed off this number.

    A name with no mark — no bar at all, or a close at or below zero (`holding_mark`) — is NOT
    counted and IS named. Understating the sleeve silently would manufacture a drawdown;
    understating it loudly is a line in the brief.

    A name whose newest bar is merely OLD is still counted at it, and that is deliberate: a halted
    or delisted holding is a data boundary to §5.2's drawdown record, not a loss. Sizing is a
    different question with a stricter answer — `stale_holdings`.
    """
    total, unpriced = 0.0, []
    for tk, qty in held.items():
        px, _ = holding_mark(cur, tk, as_of)
        if px is None:
            unpriced.append(tk)
            continue
        total += qty * px
    return total, unpriced


def stale_holdings(cur, held, as_of, session):
    """Held names whose newest bar is older than `session` though their own exchange printed it.
    Returns [(ticker, newest bar date)].

    §3.5 sizes at "engine NAV ÷ 5, marked at the decision close", and a holding with no bar on the
    decision session has no decision close — only an older one. Marking it there anyway is how a
    halted name, a vendor omission or a cash-merged line kept a full slot of NAV at a price that no
    longer existed, every night, with every gauge quiet (A15).

    "Its own exchange printed it" is read off the tape, never off a holiday calendar: did any OTHER
    name with the same EODHD exchange suffix (`SYMBOL.EXCHANGE`) print that session? The decision
    calendar is SPY's, and the TSX keeps holidays the NYSE does not — on 2025-10-13 and 2026-08-03
    SPY.US printed and no `.TO` name in the store did. A `.TO` holding without a bar on such a day
    is on its own exchange's calendar, not stale. Where the store holds no other name from the
    exchange it cannot say the exchange printed, and the name keeps its newest close, as before.
    """
    out = []
    for tk in held:
        cur.execute("select max(d) from prices where ticker = %s and d <= %s", (tk, as_of))
        newest = cur.fetchone()[0]
        if newest is None or newest >= session or "." not in tk:
            continue
        suffix = tk[tk.rindex("."):]
        cur.execute("""select exists (select 1 from prices
                                       where d = %s and ticker <> %s and right(ticker, %s) = %s)""",
                    (session, tk, len(suffix), suffix))
        if cur.fetchone()[0]:
            out.append((tk, newest))
    return out


def derived_engine_nav(cur, as_of):
    """Engine NAV, derived from the store's own numbers. Returns (nav_usd, breakdown) or
    (None, why).

    Zak, 2026-08-19: *"You have the balances of all the accounts... What do you mean I have to tell
    you what the NAV is? You know the NAV..."* He is right, and the refusal this replaces was
    calibrated for a book that could not be trusted. Post-059 the book is right by construction —
    the ledger drives it — and §2.0 already names the doctrine this arithmetic follows: **balances
    are truth, prices are the extrapolation.**

    engine NAV = the engine's marked equity (every TFSA position, park included, at its last close)
               + TFSA cash (the newest anchor, carried forward by the ledger), CAD converted at the
                 latest USDCAD close on or before the session.

    The park counts because it is the capital that funds the slots — at seed, NAV/5 sized off a
    number that excluded the bridge would deploy a fifth of nothing.

    Fails closed, loudly, on every state where a derived number would be a plausible lie, and the
    reason names which, because each is a different repair:

      * an unpriced TFSA position — no bar, or no mark (`holding_mark`): equity would understate;
      * a stale one (`stale_holdings`): it has no decision close to be marked at (§3.5);
      * no cash anchor: §2.0 makes balances the truth and there is none;
      * CAD cash with no FX row to convert it;
      * TFSA cash that derives below zero (A52). A TFSA cannot borrow — §2.3's facility is a
        separate account whose draws buy VXC.TO in the NONREG — so negative cash is not a state the
        account can be in. It is a credit the store never heard of (a dividend, a deposit, a
        conversion) or a row on the wrong side of the anchor, and from here its size is unknown.
        The test reads the account's TOTAL in USD, not one currency: a USD buy paid out of CAD
        drives the USD leg negative with NAV still right, because the ledger has no row for the
        conversion. Cash is held in cents, so it is negative once it rounds below zero to the cent.

    The anchor's date and age ride in the breakdown (`cash_as_of`, `cash_age_days`, days from the
    anchor's date to `as_of`) so they reach `engine_sessions.detail` and the score run beside the
    number they underwrite, and so do any same-day fills the anchor is taken to contain
    (`cash_same_day_assumed_inside`, from `db.cash_by_account`). No age fails: the plan rules no
    refresh cadence, and a limit would be a constant nobody ruled.
    """
    held = held_book(cur)
    equity, unpriced = marked_equity(cur, held, as_of)
    why = []
    if unpriced:
        why.append("unpriced TFSA position(s): "
                   + "; ".join(f"{tk} ({holding_mark(cur, tk, as_of)[1]})" for tk in unpriced)
                   + " — equity would understate")
    priced = [tk for tk in held if tk not in unpriced]
    if priced:
        # The decision session is the benchmark's newest bar, the same calendar `load` takes, so
        # the NAV and the sheet sized off it agree on which close is "the decision close".
        cur.execute("select max(d) from prices where ticker = %s and d <= %s",
                    (engine.REGIME_SOURCE, as_of))
        session = cur.fetchone()[0]
        if session is None:
            why.append(f"no {engine.REGIME_SOURCE} bar on or before {as_of} — no decision close "
                       "to mark the book at")
        else:
            stale = stale_holdings(cur, priced, as_of, session)
            if stale:
                why.append("stale TFSA position(s): "
                           + "; ".join(f"{tk} (newest bar {d}; its exchange printed {session})"
                                       for tk, d in stale)
                           + " — §3.5 marks NAV at the decision close")
    if why:
        return None, " · ".join(why)
    cash = cash_by_account(cur).get(ENGINE_ACCOUNT)
    if cash is None:
        return None, f"no balances anchor for {ENGINE_ACCOUNT} — §2.0 makes balances the truth"
    anchored = cash.get("as_of")
    age = (as_of - anchored).days if anchored is not None else None
    cad, usd = float(cash.get("cad") or 0), float(cash.get("usd") or 0)
    cad_in_usd = 0.0
    fx = None
    if cad:
        cur.execute("""select close from prices where ticker = 'USDCAD.FOREX' and d <= %s
                        order by d desc limit 1""", (as_of,))
        row = cur.fetchone()
        if not row or not row[0]:
            return None, f"{cad:,.2f} CAD cash and no USDCAD close on or before {as_of}"
        fx = float(row[0])
        cad_in_usd = cad / fx
    in_cash = usd + cad_in_usd
    if round(in_cash, 2) < 0:
        moved = ", ".join(f"{v:+,.2f} {k}"
                          for k, v in sorted((cash.get("moved_since_anchor") or {}).items()))
        return None, (f"{ENGINE_ACCOUNT} cash derives to {in_cash:,.2f} USD ({usd:,.2f} USD"
                      + (f" + {cad:,.2f} CAD @ {fx:,.4f}" if cad else "")
                      + f") from the anchor of {anchored} ({age} day{'' if age == 1 else 's'})"
                      + (f", moved {moved} by the ledger since" if moved else "")
                      + " — a TFSA cannot hold negative cash, so a credit is missing or a row is"
                        " on the wrong side of the anchor")
    nav = equity + in_cash
    if nav <= 0:
        return None, f"derived NAV {nav:,.2f} is not positive — nothing to size against"
    detail = dict(source="derived", marked_equity=round(equity, 2), cash_usd=round(usd, 2),
                  cash_cad=round(cad, 2), usdcad=fx, cash_as_of=str(anchored or ""),
                  cash_age_days=age,
                  cash_recorded_at=(cash["recorded_at"].isoformat()
                                    if cash.get("recorded_at") is not None else None))
    if cash.get("same_day_assumed_inside"):
        detail["cash_same_day_assumed_inside"] = cash["same_day_assumed_inside"]
    return nav, detail


def sheet(cur, as_of, nav):
    """Tonight's decision. Returns a dict; prints nothing, writes nothing.

    `nav` may be None. §3.5 sizes buys at NAV/5 and there is no defensible default, so an unknown
    NAV leaves every buy quantity None — but it does NOT suppress the sells. §5.4: "Gate-off exits
    and rank-exit sells are protective-direction and are never blocked." A sell's quantity comes
    from the book, not from NAV, so the protective half of the sheet is always complete.

    **A buy is sized by v1.1's §3.5** (promoted 2026-10-06): "the lesser of slot weight and
    deployable TFSA cash — TFSA cash on the book plus the same session's sell proceeds, marked at
    the decision close", shared equally when several buys share the session (`size_buys`). NAV
    alone no longer sizes a buy, whatever its source: the cash is the store's (`engine_cash`), and
    when the store cannot state it the buys are written unsized and the sheet says why. The
    arithmetic and its inputs ride out in `sizing`, which `score` attests and §4.4's sheet gauge
    re-derives.

    Two holds from Zak's rulings of 2026-10-07, ahead of the plan's text (drafted as P4 and P6):

      R1  §3.4's gate cannot be evaluated on fresh data (`gate_unevaluable`). He chose "hold buys,
          sell nothing": nothing new is proposed — no buy, and no gate-off sell either, because a
          vendor outage alone never liquidates the book.
      R2  A held name has no bar on the decision session — a rename, merger, takeover, halt or
          vendor omission. He ruled that ticker changes and takeovers fail closed until he records
          them, and on the tape the other two look the same: the name is never turned into a rank
          exit or a refill by inference, it keeps its quantity and its slot, the buys are held, and
          it is named until Zak records what happened. A gate-off still lists it to sell (§5.4),
          marked unpriced.

    Each arrives as a sentence in `hold`, and `score` makes a hold its amber: a price-critical
    amber holds the buys (§4.3), and nothing holds the exits.
    """
    sessions, tickers, adj, raw, dv, index_px = load(cur, as_of)
    i = len(sessions) - 1

    gate_on = bool(engine.gate_history(index_px)[i])
    green = engine.gate_green(i, index_px)
    window = index_px[max(0, i - engine.GATE_SMA + 1):i + 1]
    sma = float(window.mean()) if len(window) == engine.GATE_SMA and np.isfinite(window).all() else None

    ranked = engine.rank(i, adj, raw, dv)
    rank_of = {tickers[j]: r for r, j in enumerate(ranked, start=1)}
    addv_row = engine.median_addv(dv, i)
    # §3.2's survivors BEFORE the top-500 cap. §4.4 gauges this rather than the ranked count,
    # which is censored at 500 on any ordinary session and cannot move when the tape breaks.
    screened = len(engine.screen(i, adj, raw, dv, pool=None))

    # §3.3's score, recomputed for the record. `engine.rank` returns the ORDER and deliberately
    # keeps the arithmetic private; the store wants the number too, so §4.4 can re-derive a rank
    # from stored scores and §6.4 can say how far apart two rankings were, not merely that they
    # differed. Same expression, same window, same clause.
    scores = {}
    for j in [tickers.index(t) for t in rank_of]:
        w = adj[max(0, i - engine.VOL_WINDOW):i + 1, j]
        rets = np.diff(w) / w[:-1]
        vol = float(np.nanstd(rets))
        base = float(adj[i - engine.SKIP, j] / adj[i - engine.FORMATION, j] - 1.0)
        scores[tickers[j]] = base / vol if vol > 0 else None

    # R1, Zak's ruling of 2026-10-07: a gate read off stale bars is unevaluated, and an unevaluated
    # gate proposes nothing — see `gate_unevaluable` for what "fresh" is measured against.
    stale = gate_unevaluable(cur, as_of, sessions[i], [tickers[j] for j in ranked])
    hold = [stale["why"]] if stale else []

    book = held_book(cur)
    # The park comes out of the ranked book before anything else looks at it. It is engine capital
    # and it is not an engine slot: it never counts against §3.5's five, never displaces a name, and
    # above all is never sold for failing to rank — see PARKED for why that last one is not a
    # hypothetical. What it IS, when the gate is ON, is what pays a shortfall the cash cannot.
    parked = {t: q for t, q in book.items() if t in PARKED}
    held = {t: q for t, q in book.items() if t not in PARKED}
    col = {t: j for j, t in enumerate(tickers)}
    # Every holding's close ON the decision session, which is what a sell is marked at and what
    # its proceeds are counted at (§3.5). None is a name that did not print there — R2's case.
    mark_of = {t: decision_close(cur, t, sessions[i], raw[i, col[t]] if t in col else None)
               for t in held}
    unbarred = [] if stale else [t for t in held if mark_of[t] is None]
    # A holding that has left the universe entirely — delisted, or newly excluded — has no column
    # and cannot be ranked. §3.5 queues anything below rank 12, and "not ranked at all" is below it.
    # That holds for a name that PRINTED tonight and failed the screen; a name with no print at all
    # is R2's, and is not ranked below anything — its rank is unknown, not bad.
    held_cols = [col[t] for t in held if t in rank_of]
    unranked = [t for t in held if t not in rank_of and t not in unbarred]

    # §3.7(3)'s twin relation, computed from the tape and handed to `engine.orders` as a callable.
    # `bars.same_security` is the one definition — daily returns at 1e-4 with the variation floor —
    # and it is the same function migration 050's exclusions and `concentrated.py`'s `twin_held`
    # use. TWIN_WINDOW mirrors the sim's lookback so the live rule and the backtested rule see the
    # same span; a shorter window would call two lines twins on a quiet fortnight.
    lo = max(1, i - bars.TWIN_WINDOW + 1)

    def _ret(j):
        return adj[lo:i + 1, j] / adj[lo - 1:i, j] - 1.0

    def twin_of(a, b):
        return bars.same_security(_ret(a), _ret(b))

    # R2: a held name with no print keeps its slot, so the free slots are counted without it. Only
    # the slot COUNT moves; the name itself never reaches `engine.orders`, which could otherwise
    # only read "no rank" as "below 12".
    room = engine.SLOTS - len(unbarred)
    if stale:
        sells, buys, unranked = [], [], []
    elif gate_on and room < 1:
        # Every slot is held by a name that did not print tonight: nothing can be bought, so
        # nothing is displaced. A holding the rank still covers exits by §3.5's rule alone — the
        # slot count passed here is one more than the book, so no swap can be computed.
        sells, _ = engine.orders(ranked, held_cols, gate_on=True, twin_of=twin_of,
                                 slots=len(held_cols) + 1)
        buys = []
    else:
        sells, buys = engine.orders(ranked, held_cols, gate_on=gate_on, twin_of=twin_of,
                                    slots=room)
    if unbarred:
        hold.append(f"no bar on {sessions[i]} for held "
                    + ", ".join(f"{t} ({held[t]:g} sh, newest bar {newest_bar(cur, t, as_of)})"
                                for t in unbarred)
                    + (" — not a rank exit and not a refill: it keeps its slot and its quantity,"
                       " and buys are held" if gate_on else
                       " — the gate is OFF, so it is listed to sell at the book's quantity,"
                       " unpriced (§5.4)")
                    + " until Zak records what happened (a rename, merger, takeover, halt or"
                      " vendor omission)")
    # A gate-off still sells it (§5.4), at the book's quantity and with no decision close.
    sell_tk = [tickers[j] for j in sells] + unranked + ([] if gate_on else unbarred)

    orders = []
    for tk in sell_tk:
        o = dict(action="sell", ticker=tk, qty=held[tk], rank=rank_of.get(tk), mark=mark_of[tk],
                 clause="gate_off" if not gate_on else "rank_exit",
                 why="gate off" if not gate_on else "rank")
        if o["mark"] is None:
            o["why"] = f"gate off — unpriced: no bar on {sessions[i]}"
            o["note"] = f"unpriced: no bar on {sessions[i]}"
        orders.append(o)

    # §6.5 gates the park draw on the shadow having passed. `passes` is §6.4's condition verbatim
    # and it clears itself, so this needs no ruling to remove. No attestations at all reads as
    # not-passed: "no record" is not "passed" (§4.4's habit).
    cur.execute("select coalesce((select passes from v_shadow_progress), false)")
    phase0_done = bool(cur.fetchone()[0])

    # The buys. §3.5 fills FREE slots and `engine.orders` keeps a held name in the top 12 rather
    # than returning it as a buy, so no buy is ever a name the account holds — and v1.1 makes that
    # a rule rather than a property: "a slot filled below weight counts as filled and is reported;
    # it is never topped up". The belt below holds it if the property ever breaks.
    held_below, wants = [], []
    for j in buys:
        tk = tickers[j]
        if held.get(tk, 0.0) > 0:
            held_below.append(dict(ticker=tk, rank=rank_of.get(tk), mark=float(raw[i, j]),
                                   why=f"already held ({held[tk]:g} sh) — §3.5 never tops a slot"
                                       f" up (v1.1)"))
            continue
        wants.append((tk, float(raw[i, j])))
    sizing, funding = None, []
    if wants:
        sizing, qty_of, draws = size_buys(
            cur, as_of, sessions[i], nav, wants,
            [(o["ticker"], o["qty"], o["mark"]) for o in orders], parked,
            # The park pays a shortfall only for buys that can be acted on: never while the shadow
            # runs (§6.5), and never beside a hold — A23's fund sell, shipped with held buys,
            # emptied the park into cash for orders nobody could place.
            may_draw=gate_on and phase0_done and not hold)
        for tk, px in wants:
            j = col[tk]
            addv = float(addv_row[j])
            o = dict(action="buy", ticker=tk, rank=rank_of.get(tk), mark=px, addv=addv,
                     clause="fill", why="fill", already_held=0.0)
            if sizing.get("alloc") is None:
                o.update(qty=None, participation_ok=None,
                         why=f"fill — unsized: {sizing['unsized']}")
                orders.append(o)
                continue
            want, qty = engine.position_size(nav, px), qty_of[tk]
            if qty < 1:
                held_below.append(dict(
                    ticker=tk, rank=rank_of.get(tk), mark=px, slot_qty=want,
                    why=(f"its equal share of deployable TFSA cash, {sizing['alloc']:,.2f} USD,"
                         f" buys no whole share at {px:,.2f}" if want >= 1 else
                         f"the {sizing['slot']:,.2f} slot buys no whole share at {px:,.2f}")
                        + " — held below weight, not funded (§3.5, v1.1)"))
                continue
            o.update(qty=qty, slot_qty=want, below_weight=qty < want,
                     participation_ok=engine.participation_ok(qty, px, addv))
            if qty < want:
                o["why"] = o["note"] = (
                    f"fill below §3.5 weight: {qty:,} of {want:,} shares — deployable TFSA cash"
                    f" {sizing['deployable']:,.2f} USD over {sizing['buys']} buy(s) is"
                    f" {sizing['alloc']:,.2f} each (v1.1)")
            orders.append(o)
        # Sells before buys (§3.5), and the park's draw is the first of them: the cash has to
        # exist before the buys it pays for. Only the SHORTFALL is drawn — never the lot because
        # a lot exists (A6) — and only for buys that were sized (A23).
        funding = [dict(action="sell", ticker=d["ticker"], qty=d["qty"], rank=None,
                        mark=d["mark"], clause="fund",
                        why=f"the park's draw: {d['qty']:g} of {d['lot']:g} sh cover the buys'"
                            f" shortfall beyond cash and proceeds (§3.5, v1.1)")
                   for d in draws]
        orders = funding + orders

    # §3.5's slot is a WEIGHT — "Slots: 5, equal weight" — and v1.1 settles what a slot held at a
    # fraction of it is: "A slot filled below weight counts as filled and is reported; it is never
    # topped up." So it is reported here and ordered nowhere. A name the sheet is selling tonight is
    # not reported: its slot is being vacated, not held short (A25's shape on the sheet).
    underweight = []
    if nav and not stale:
        for tk in sorted(held):
            if tk not in rank_of or tk in sell_tk:
                continue
            j = col[tk]
            if not np.isfinite(raw[i, j]):
                continue
            value = held[tk] * float(raw[i, j])
            slot = nav / engine.SLOTS
            if value < slot:
                underweight.append(dict(ticker=tk, rank=rank_of[tk], value=value, slot=slot,
                                        short=slot - value, pct_of_slot=value / slot))

    equity, unpriced = marked_equity(cur, book, sessions[i])
    return dict(session=sessions[i], gate="ON" if gate_on else "OFF", gate_on=gate_on,
                gate_green=bool(green), index_close=float(index_px[i]), index_sma=sma, nav=nav,
                universe=len(tickers), ranked=len(ranked), screened=screened,
                marked_equity=equity, unpriced=unpriced, underweight=underweight,
                parked=sorted(parked), parked_qty=parked, phase0_done=phase0_done,
                held=sorted(held), unranked=unranked, unbarred=unbarred,
                hold=hold, stale=stale, sizing=sizing, held_below=held_below,
                top=[tickers[j] for j in ranked[:engine.FILL_BAND]], orders=orders,
                ranks=[dict(ticker=tickers[j], rank=r, score=scores.get(tickers[j]),
                            mark=float(raw[i, j]) if np.isfinite(raw[i, j]) else None,
                            addv=float(addv_row[j]) if np.isfinite(addv_row[j]) else None)
                       for r, j in enumerate(ranked, start=1)])


def decision_close(cur, ticker, session, tape_close=None):
    """A holding's close ON the decision session, or None when it did not print there.

    Read off the loaded tape when the name has a column on it (`tape_close`), and by its own query
    when it does not: a holding excluded or delisted since it was bought has no column, and it
    still sells at its close if it printed one. A close at or below zero is no print — the vendor
    pads a delisting tail with 0.0000 after an acquisition (learning 33), and a mark of zero would
    count a takeover's proceeds as nothing.
    """
    if tape_close is None:
        cur.execute("select close from prices where ticker = %s and d = %s", (ticker, session))
        row = cur.fetchone()
        tape_close = row[0] if row and row[0] is not None else float("nan")
    px = float(tape_close)
    return px if np.isfinite(px) and px > 0 else None


def newest_bar(cur, ticker, as_of):
    """The date of a name's newest bar on or before `as_of` — what a hold names it by."""
    cur.execute("select max(d) from prices where ticker = %s and d <= %s", (ticker, as_of))
    return cur.fetchone()[0]


def gate_unevaluable(cur, as_of, session, pool):
    """Can §3.4's gate be evaluated on fresh data tonight? None when it can; when it cannot, a dict
    whose `why` names the benchmark's bar and the tape's.

    §3.4 says a gate that cannot be evaluated on fresh data "reads OFF", and OFF sells the book.
    Zak ruled how that clause runs on 2026-10-07 (R1), choosing "hold buys, sell nothing": stale
    data holds the buys, the brief says the gate could not be evaluated, and a vendor outage alone
    never liquidates the book. What stale means here — SPY missing from the newest session's tape,
    or the tape older than §5.6's 4 days — is the reading drafted for the plan as P4, not yet
    ruled. Before it, nothing here asked: `load` takes its
    calendar from SPY's own bars, so a missing SPY bar silently re-scored the session before and a
    dead tape re-scored its last good one, gate and all (QC A39).

    The two tests, both measured from `as_of` — the session asked about, today in production:

      * SPY missing from the newest session: the names the engine RANKS tonight (`pool`, §3.2's
        survivors) printed a session SPY did not. That is db.data_date's question — the newest
        stock bar — asked of the names that decide the sheet rather than of every stock row, and
        the narrowing is not cosmetic: the vendor ships thin files for US market holidays, and
        the store holds stock bars dated 2026-05-25, 06-19, 07-03 and 09-07 (the 311-row Labor Day
        file of QC A47) from OTC lines and dead tickers no live session ever ranked. Asked of the
        whole store, the question names each holiday as the newest session and holds every buy
        on the morning after it. The liquid names §3.2 admits print exactly when the exchange
        does.
      * The tape older than §5.6's constant: the benchmark's newest bar more than `STALE_DAYS`
        days before `as_of`.

    Each name in the pool costs one index probe on (ticker, d), backwards from `as_of`.
    """
    tape = None
    if pool:
        cur.execute("""select max(newest.d) from unnest(%s::text[]) as p(ticker)
                       cross join lateral (select x.d from prices x
                                            where x.ticker = p.ticker and x.d <= %s
                                            order by x.d desc limit 1) newest""",
                    (list(pool), as_of))
        tape = cur.fetchone()[0]
    src, why = engine.REGIME_SOURCE, []
    if tape is not None and tape > session:
        why.append(f"{src}'s newest bar is {session}, but the names the engine ranks printed {tape}"
                   f" — {src} is missing from the newest session's tape")
    age = (as_of - session).days
    if age > STALE_DAYS:
        why.append(f"{src}'s newest bar, {session}, is {age} days before {as_of} — older than"
                   f" §5.6's {STALE_DAYS}")
    if not why:
        return None
    return dict(why="the gate cannot be evaluated on fresh data: " + "; ".join(why)
                    + ". Nothing new is proposed and the buys are held; a data outage alone never"
                      " sells the book (§3.4; Zak's ruling, 2026-10-07)",
                index_bar=str(session), tape_bar=str(tape) if tape else None, age_days=age)


def engine_cash(cur, as_of):
    """§3.5's "TFSA cash on the book" (v1.1), in USD. Returns (usd, breakdown) or (None, why).

    The number `derived_engine_nav` adds to the marked equity, by the same arithmetic: the newest
    `balances` anchor carried forward by the ledger (`db.cash_by_account`, §2.0's "balances are
    truth"), CAD converted at the latest USDCAD close on or before `as_of`. Where NAV came from does
    not move where this comes from — a NAV overridden in `config` or the environment is a ruling
    about the slot, not about the money in the account, so the cash is the store's or nothing.

    None, and the buys go unsized with the reason, on the states where the store cannot state it:
    no anchor; CAD with no USDCAD row to convert it; and a total below zero, which a TFSA cannot
    hold — it cannot borrow, and §2.3's facility is a separate account. A negative total is a
    credit the ledger never heard of or a row on the wrong side of the anchor, and its size is
    unknown from here. The test reads the account's total in USD, not one currency: a USD buy paid
    out of CAD drives the USD leg negative with the total right, because the ledger has no row for
    the conversion. Failing closed matters more here than it does for NAV, because v1.1 never tops
    a slot up: a buy sized to an understated cash stays short for as long as the name is held.
    """
    cash = cash_by_account(cur).get(ENGINE_ACCOUNT)
    if cash is None:
        return None, (f"no balances anchor for {ENGINE_ACCOUNT} — §3.5 (v1.1) sizes a buy to"
                      f" deployable {ENGINE_ACCOUNT} cash, and the store cannot state it")
    cad, usd = float(cash.get("cad") or 0), float(cash.get("usd") or 0)
    fx, cad_in_usd = None, 0.0
    if cad:
        cur.execute("""select close from prices where ticker = 'USDCAD.FOREX' and d <= %s
                        order by d desc limit 1""", (as_of,))
        row = cur.fetchone()
        if not row or not row[0]:
            return None, f"{cad:,.2f} CAD cash and no USDCAD close on or before {as_of}"
        fx = float(row[0])
        cad_in_usd = cad / fx
    total = usd + cad_in_usd
    if round(total, 2) < 0:
        return None, (f"{ENGINE_ACCOUNT} cash derives to {total:,.2f} USD ({usd:,.2f} USD"
                      + (f" + {cad:,.2f} CAD @ {fx:,.4f}" if cad else "")
                      + f") from the anchor of {cash.get('as_of')} — a TFSA cannot hold negative"
                        " cash, so a credit is missing or a row is on the wrong side of the anchor")
    # Money is counted in cents, so a total that rounds to 0.00 from below IS zero — and a share of
    # cash a fraction of a cent below zero is not a quantity anything can be sized against.
    total = max(total, 0.0)
    return total, dict(usd=usd, cad=cad, usdcad=fx, in_usd=total,
                       as_of=str(cash.get("as_of") or ""))


def size_buys(cur, as_of, session, nav, wants, sold, parked, *, may_draw):
    """§3.5 as amended by v1.1: tonight's buys, sized to the lesser of slot weight and deployable
    TFSA cash. Returns (sizing, qty_of, draws).

    `wants` is [(ticker, decision close)] — the free slots `engine.orders` fills, in rank order;
    `sold` is tonight's sells as [(ticker, qty, decision close)]; `parked` the account's non-cash
    park lots (PARKED), which v1.1's cash park leaves behind as a legacy.

      deployable = TFSA cash (`engine_cash`) + every sell's qty × its decision close
                   (+ the park's draw, below)
      share      = deployable ÷ the number of buys          "divides equally among them"
      qty        = min(NAV ÷ 5 // close, share // close)   `engine.capped_size`

    **The park pays the shortfall, and only the shortfall.** "A shortfall beyond TFSA park and cash
    is reported as held-below-weight, not funded": the buys need a slot each, and what cash and
    proceeds do not cover is drawn from a park lot in whole shares, enough to cover it and never
    more than the lot (`engine.park_draw`). It used to sell every park lot whenever anything
    bought (A6), and beside buys that were unsized or held (A23); `may_draw` is false for those.

    `qty_of[ticker]` below one is a buy the cash cannot reach. It is no ticket: the sheet reports it
    as held below weight, with the reason. `sizing` carries every input and the result, for the
    attestation §4.4's gauge re-derives from — or, when there is nothing to size against, `unsized`
    and the reason.
    """
    n = len(wants)
    sizing = dict(buys=n, nav=nav)
    if not nav:
        sizing["unsized"] = "engine NAV unknown — §3.5 sizes the slot at NAV ÷ 5"
        return sizing, {}, []
    cash, cash_detail = engine_cash(cur, as_of)
    if cash is None:
        sizing["unsized"] = cash_detail
        return sizing, {}, []
    dark = [tk for tk, _, px in sold if px is None]
    if dark:
        sizing["unsized"] = (f"tonight's sell of {', '.join(dark)} has no decision close, so its"
                             f" proceeds — part of deployable cash (§3.5) — cannot be stated")
        return sizing, {}, []
    slot = nav / engine.SLOTS
    proceeds = sum(q * px for _, q, px in sold)
    base = cash + proceeds
    draws, shortfall, unpriced_park = [], None, []
    if may_draw and parked:
        shortfall = n * slot - base
        left = shortfall
        for tk, lot in sorted(parked.items()):
            if left <= 0:
                break
            # Priced by its own query, like `marked_equity`: the park is not in §3.2's universe,
            # so it has no column on the loaded tape and never will.
            cur.execute("""select close from prices where ticker = %s and d <= %s
                            order by d desc limit 1""", (tk, session))
            row = cur.fetchone()
            px = float(row[0]) if row and row[0] is not None else None
            if not px or px <= 0:
                unpriced_park.append(tk)        # no mark, no draw: what it cannot cover is short
                continue
            q = engine.park_draw(left, lot, px)
            if q > 0:
                draws.append(dict(ticker=tk, lot=lot, mark=px, qty=q))
                left -= q * px

    def share(of):
        drawn = sum(d["qty"] * d["mark"] for d in of)
        return drawn, base + drawn, (base + drawn) / n

    drawn, deployable, alloc = share(draws)
    qty_of = {tk: engine.capped_size(nav, px, alloc) for tk, px in wants}
    if draws and not any(q >= 1 for q in qty_of.values()):
        # The park is drawn for buys, and a draw that still buys nothing is not made.
        draws = []
        drawn, deployable, alloc = share(draws)
        qty_of = {tk: engine.capped_size(nav, px, alloc) for tk, px in wants}
    sizing.update(slot=slot, cash=cash_detail,
                  sold=[dict(ticker=tk, qty=q, mark=px) for tk, q, px in sold],
                  proceeds=proceeds, shortfall=shortfall, park=draws, drawn=drawn,
                  deployable=deployable, alloc=alloc)
    if unpriced_park:
        sizing["park_unpriced"] = unpriced_park
    return sizing, qty_of, draws


def render(s):
    src = s.get("nav_source") or {}
    # The number's provenance is on the sheet because §3.5 sizes real orders off it: a derived NAV
    # shows its arithmetic (equity + cash), an overridden one names the override.
    if s["nav"] and src.get("source") == "derived":
        nav = (f"NAV {s['nav']:,.2f} (derived: equity {src.get('marked_equity', 0):,.2f}"
               f" + cash {src.get('cash_usd', 0):,.2f} USD"
               + (f" + {src.get('cash_cad', 0):,.2f} CAD @ {src.get('usdcad'):,.4f}"
                  if src.get("cash_cad") else "") + ")")
    elif s["nav"]:
        nav = f"NAV {s['nav']:,.2f}" + (f" ({src['source']})" if src.get("source") else "")
    else:
        nav = ("NAV **unknown — buys unsized**"
               + (f" — {src['why']}" if src.get("why") else ""))
    stale = s.get("stale")
    gate = s["gate"] + (" — **unevaluated on fresh data**" if stale else "")
    out = [f"### engine · session {s['session']} · gate {gate}", "",
           f"universe {s['universe']} · ranked {s['ranked']} · {nav}", ""]
    if s.get("hold"):
        # Above everything it governs, the way the brief puts a freeze above the freshness line.
        out.append("**HOLD — buys held" + ("; nothing new proposed" if stale else "")
                   + "; nothing holds an exit**")
        out += [f"  · {h}" for h in s["hold"]]
        out.append("")
    out.append("top 12: " + ", ".join(f"{t}" for t in s["top"]))
    out.append("held:   " + (", ".join(s["held"]) if s["held"] else "(nothing)"))
    if s.get("parked"):
        out.append("parked: " + ", ".join(f"{t} {s['parked_qty'][t]:,.0f}" for t in s["parked"])
                   + "   (engine capital, not a slot — never sold for failing to rank)")
        if not s.get("phase0_done"):
            out.append("        held: §6.5 converts this at the seed, and the shadow has not"
                       " passed yet. Not funding tonight's buys.")
    sz = s.get("sizing") or {}
    if sz.get("unsized"):
        out.append(f"sizing: **buys unsized** — {sz['unsized']}")
    elif sz.get("alloc") is not None:
        # §3.5 (v1.1) in one line: what the night can spend, where it comes from, and how it is
        # shared — so a buy below weight carries its arithmetic on the page it is read from.
        out.append(f"sizing (§3.5, v1.1): deployable TFSA cash {sz['deployable']:,.2f} USD ="
                   f" cash {sz['cash']['in_usd']:,.2f} + tonight's sells {sz['proceeds']:,.2f}"
                   + (f" + park draw {sz['drawn']:,.2f}" if sz.get("drawn") else "")
                   + f" · {sz['buys']} buy(s) at {sz['alloc']:,.2f} each, capped at the"
                     f" {sz['slot']:,.2f} slot")
    out.append("")
    if not s["orders"]:
        out.append("**no orders** — the gate could not be evaluated on fresh data, so nothing new"
                   " is proposed" if stale else
                   "**no orders tonight** — the book already matches the rank")
    for o in s["orders"]:
        if o["action"] == "sell":
            out.append(f"  SELL {o['ticker']:<10} qty {o['qty'] or 0:>10,.4g}   "
                       f"rank {o['rank'] or '—'}   ({o['why']})")
        else:
            qty = f"{o['qty']:>10,.0f}" if o["qty"] else "         —"
            warn = "" if o["participation_ok"] is not False else "   ** EXCEEDS 0.98 ADDV **"
            below = (f"   ** below §3.5 weight: {o['qty']:,} of {o['slot_qty']:,} shares **"
                     if o.get("below_weight") else "")
            out.append(f"  BUY  {o['ticker']:<10} qty {qty}   "
                       f"rank {o['rank']}   mark {o['mark']:,.2f}{warn}{below}")
    if s.get("held_below"):
        out.append("")
        out.append("** buys held below weight — no ticket (§3.5, v1.1: a shortfall is reported,"
                   " not funded) **")
        for h in s["held_below"]:
            out.append(f"    {h['ticker']:<10} rank {h['rank'] or '—':<3} {h['why']}")
    if s.get("underweight"):
        short = sum(u["short"] for u in s["underweight"])
        out.append("")
        out.append("** held below §3.5's equal weight — reported, NOT ordered **")
        for u in s["underweight"]:
            out.append(f"    {u['ticker']:<10} rank {u['rank']:<3} "
                       f"{u['value']:>12,.2f} of a {u['slot']:,.2f} slot "
                       f"({u['pct_of_slot']:.0%}) — short {u['short']:,.2f}")
        out.append(f"    {len(s['underweight'])} slot(s) count as filled while holding"
                   f" {short:,.2f} less than their weight.")
        out.append("    §3.5 (v1.1): \"A slot filled below weight counts as filled and is reported;"
                   " it is never topped up.\"")
    out += ["", "Zak executes at the open: sells first, then buys (§3.5). "
                "Nothing here has been ordered."]
    return "\n".join(out)


def main():
    as_of = os.environ.get("AS_OF", "").strip()
    as_of = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    nav = os.environ.get("ENGINE_NAV", "").strip()
    if not nav:
        # §3.5 sizes off engine NAV, and there is no defensible default for it. Failing here is
        # the correct outcome: a sheet sized on a guessed NAV is a plausible wrong number, which
        # is the failure mode this repo exists to avoid.
        raise SystemExit("ENGINE_NAV is required — §3.5 sizes at NAV/5 and it will not be invented")
    with connect() as conn:
        with conn.cursor() as cur:
            s = sheet(cur, as_of, float(nav))
    report = render(s)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
