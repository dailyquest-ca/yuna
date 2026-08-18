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
from db import connect                                                    # noqa: E402

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
# off)". The account IS the allocation — "there are no percentage targets" — so everything in the
# TFSA is the engine's to manage, and nothing outside it ever is.
ENGINE_ACCOUNT = "TFSA"

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


def held_book(cur, account=ENGINE_ACCOUNT):
    """Everything the engine holds. §2.1 puts it in the TFSA and gives it the whole account.

    Filtered by ACCOUNT, not by sleeve, and that is a correction. The sleeve filter was inherited
    from the machine v1.0 replaced, which ran three sleeves side by side and had to tell them
    apart. v1.0 has one engine and §2.1 hands it one account, so a sleeve label decides nothing —
    and while it did, it decided something badly: 20 shares of AXTI and 2 of MU sat in the TFSA
    tagged `preseed`, invisible to the engine, while AXTI and MU ranked 2nd and 3rd in its own top
    twelve. The seed would have sized a full NAV/5 slot in each as though none were held.

    A position the engine cannot see is one it can never sell, never count against §3.5's five
    slots, and never net against a buy. There is no label that makes that safe.

    Zak, 2026-08-18: *"the momentum play should view the whole book and make a plan for how to
    adjust it to meet the goal portfolio."* This is the whole book; `sheet` splits the park off it.
    """
    cur.execute("""select ticker, sum(qty) from book
                    where status = 'open' and account = %s
                    group by ticker having sum(qty) > 0 order by ticker""", (account,))
    return {r[0]: float(r[1]) for r in cur.fetchall()}


def marked_equity(cur, held, as_of):
    """The sleeve marked at the decision close. Returns (value, [names with no mark]).

    Priced by its own query rather than off the loaded tape, deliberately: a holding that has left
    §3.2's universe — excluded, or delisted — has no column there, and marking it at zero would
    read as a drawdown when it is a data boundary. §5.2's milestones are computed off this number.

    A name with no bar at all is NOT counted and IS named. Understating the sleeve silently would
    manufacture a drawdown; understating it loudly is a line in the brief.
    """
    total, unpriced = 0.0, []
    for tk, qty in held.items():
        cur.execute("""select close from prices where ticker = %s and d <= %s
                        order by d desc limit 1""", (tk, as_of))
        row = cur.fetchone()
        if row is None or row[0] is None:
            unpriced.append(tk)
            continue
        total += qty * float(row[0])
    return total, unpriced


def sheet(cur, as_of, nav):
    """Tonight's decision. Returns a dict; prints nothing, writes nothing.

    `nav` may be None. §3.5 sizes buys at NAV/5 and there is no defensible default, so an unknown
    NAV leaves every buy quantity None — but it does NOT suppress the sells. §5.4: "Gate-off exits
    and rank-exit sells are protective-direction and are never blocked." A sell's quantity comes
    from the book, not from NAV, so the protective half of the sheet is always complete.
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

    book = held_book(cur)
    # The park comes out of the ranked book before anything else looks at it. It is engine capital
    # and it is not an engine slot: it never counts against §3.5's five, never displaces a name, and
    # above all is never sold for failing to rank — see PARKED for why that last one is not a
    # hypothetical. What it IS, when the gate is ON, is where the money for the buys comes from.
    parked = {t: q for t, q in book.items() if t in PARKED}
    held = {t: q for t, q in book.items() if t not in PARKED}
    # A holding that has left the universe entirely — delisted, or newly excluded — has no column
    # and cannot be ranked. §3.5 queues anything below rank 12, and "not ranked at all" is below it.
    held_cols = [tickers.index(t) for t in held if t in rank_of]
    unranked = [t for t in held if t not in rank_of]

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

    sells, buys = engine.orders(ranked, held_cols, gate_on=gate_on, twin_of=twin_of)
    sell_tk = [tickers[j] for j in sells] + unranked
    buy_tk = [tickers[j] for j in buys]

    orders = []
    for tk in sell_tk:
        j = tickers.index(tk) if tk in rank_of else None
        orders.append(dict(action="sell", ticker=tk, qty=held.get(tk), rank=rank_of.get(tk),
                           mark=float(raw[i, j]) if j is not None and np.isfinite(raw[i, j]) else None,
                           clause="gate_off" if not gate_on else "rank_exit",
                           why="gate off" if not gate_on else "rank"))
    for tk in buy_tk:
        j = tickers.index(tk)
        px = float(raw[i, j])
        addv = float(addv_row[j])
        # §3.5 sizes the SLOT at NAV/5; the ORDER is the slot less whatever the account already
        # holds of that name. Today those are the same number for every buy on the sheet, because
        # §3.5 fills FREE slots and `engine.orders` keeps a held name in the top 12 rather than
        # returning it as a buy — so `already` is zero. This is the belt: the netting is one line,
        # and the failure it prevents is buying a position the account already holds, at full
        # weight, on top of itself. `underweight` below is the case that actually arises.
        target = engine.position_size(nav, px) if nav else None
        already = held.get(tk, 0.0)
        qty = max(0, int(target - already)) if target is not None else None
        if qty == 0:
            continue                       # the slot is already at or above its §3.5 weight
        orders.append(dict(action="buy", ticker=tk, qty=qty, rank=rank_of.get(tk),
                           mark=px, addv=addv, clause="fill", why="fill", already_held=already,
                           participation_ok=engine.participation_ok(qty, px, addv) if qty else None))
    # §3.5's slot is a WEIGHT — "Slots: 5, equal weight" — and a slot held at a fraction of that
    # weight is not equal weight. The engine has no rule for it because until now a slot was only
    # ever empty or full: a name is bought at exactly NAV/5 and never bought again, so a partial
    # line can only arrive from OUTSIDE the engine. Two have — 20 shares of AXTI and 2 of MU, from
    # the pre-seed buys, ranking 2nd and 3rd.
    #
    # **This is not cosmetic and the numbers say why.** §3.5 fills FREE slots, and `engine.orders`
    # KEEPS a held name in the top 12 rather than re-buying it. So both of those slots read as
    # occupied at roughly 4% of their weight, the seed fills the other three, and about 60% of the
    # account never leaves the park — against §6.5's "all five slots fill from the first live
    # ranking in one session."
    #
    # Reported, not acted on, and the restraint is the point. Topping up a kept holding is a
    # rebalance rule, and rebalancing a momentum book trims winners — the one thing the strategy
    # must not do. §3.5 does not carry the rule and §6.5 does not name the arithmetic, so writing
    # one here would be an invented constant in a position-sizing rule, which is the failure this
    # repository is most exposed to. §0.3 makes it Zak's; the sheet's job is to put the shortfall
    # in front of him in dollars.
    underweight = []
    if nav:
        for tk in sorted(held):
            if tk not in rank_of:
                continue
            j = tickers.index(tk)
            if not np.isfinite(raw[i, j]):
                continue
            value = held[tk] * float(raw[i, j])
            slot = nav / engine.SLOTS
            if value < slot:
                underweight.append(dict(ticker=tk, rank=rank_of[tk], value=value, slot=slot,
                                        short=slot - value, pct_of_slot=value / slot))

    # The park funds the buys, and only then. §6.5: "all five slots fill from the first live
    # ranking in one session" — the capital for that is the §6.1(3) bridge, so at seed the bridge
    # is sold and the five are bought in the same session. While the gate is OFF the opposite
    # holds: §3.4 sends proceeds TO the park and buys nothing, so selling it would move the money
    # into cash to sit there. Hence the condition — sold when, and only when, something buys it.
    #
    # The condition reads the ORDERS, not `buy_tk`. A name in the fill band whose slot the account
    # already holds emits no buy — that is the top-up rule above — so a sheet can name buys and
    # order none, and funding those would sell the bridge to pay for nothing.
    funding = []
    if parked and gate_on and any(o["action"] == "buy" for o in orders):
        for tk, qty in sorted(parked.items()):
            # Priced by its own query, like `marked_equity`: the park is not in §3.2's universe, so
            # it has no column on the loaded tape and never will.
            cur.execute("""select close from prices where ticker = %s and d <= %s
                            order by d desc limit 1""", (tk, sessions[i]))
            row = cur.fetchone()
            mark = float(row[0]) if row and row[0] is not None else None
            funding.append(dict(action="sell", ticker=tk, qty=qty, rank=None, mark=mark,
                                clause="fund", why="funds the seed (§6.5)"))
        # Sells before buys (§3.5), and the funding sell is the first of them: the cash has to
        # exist before the buys it pays for.
        orders = funding + orders

    equity, unpriced = marked_equity(cur, book, sessions[i])
    return dict(session=sessions[i], gate="ON" if gate_on else "OFF", gate_on=gate_on,
                gate_green=bool(green), index_close=float(index_px[i]), index_sma=sma, nav=nav,
                universe=len(tickers), ranked=len(ranked), screened=screened,
                marked_equity=equity, unpriced=unpriced, underweight=underweight,
                parked=sorted(parked), parked_qty=parked,
                held=sorted(held), unranked=unranked,
                top=[tickers[j] for j in ranked[:engine.FILL_BAND]], orders=orders,
                ranks=[dict(ticker=tickers[j], rank=r, score=scores.get(tickers[j]),
                            mark=float(raw[i, j]) if np.isfinite(raw[i, j]) else None,
                            addv=float(addv_row[j]) if np.isfinite(addv_row[j]) else None)
                       for r, j in enumerate(ranked, start=1)])


def render(s):
    nav = f"NAV {s['nav']:,.2f}" if s["nav"] else "NAV **unknown — buys unsized**"
    out = [f"### engine · session {s['session']} · gate {s['gate']}", "",
           f"universe {s['universe']} · ranked {s['ranked']} · {nav}", ""]
    out.append("top 12: " + ", ".join(f"{t}" for t in s["top"]))
    out.append("held:   " + (", ".join(s["held"]) if s["held"] else "(nothing)"))
    if s.get("parked"):
        out.append("parked: " + ", ".join(f"{t} {s['parked_qty'][t]:,.0f}" for t in s["parked"])
                   + "   (engine capital, not a slot — never sold for failing to rank)")
    out.append("")
    if not s["orders"]:
        out.append("**no orders tonight** — the book already matches the rank")
    for o in s["orders"]:
        if o["action"] == "sell":
            out.append(f"  SELL {o['ticker']:<10} qty {o['qty'] or 0:>10,.4g}   "
                       f"rank {o['rank'] or '—'}   ({o['why']})")
        else:
            qty = f"{o['qty']:>10,.0f}" if o["qty"] else "         —"
            warn = "" if o["participation_ok"] is not False else "   ** EXCEEDS 0.98 ADDV **"
            out.append(f"  BUY  {o['ticker']:<10} qty {qty}   "
                       f"rank {o['rank']}   mark {o['mark']:,.2f}{warn}")
    if s.get("underweight"):
        short = sum(u["short"] for u in s["underweight"])
        out.append("")
        out.append("** held below §3.5's equal weight — reported, NOT ordered **")
        for u in s["underweight"]:
            out.append(f"    {u['ticker']:<10} rank {u['rank']:<3} "
                       f"{u['value']:>12,.2f} of a {u['slot']:,.2f} slot "
                       f"({u['pct_of_slot']:.0%}) — short {u['short']:,.2f}")
        out.append(f"    {len(s['underweight'])} slot(s) count as filled while holding"
                   f" {short:,.2f} less than their weight,")
        out.append("    so that much capital stays parked. §3.5 fills FREE slots and keeps a held")
        out.append("    name rather than re-buying it; it carries no top-up rule, because a name is")
        out.append("    bought once at weight and never bought again. A partial line can only come")
        out.append("    from outside the engine — and topping one up is a rebalance, which on a")
        out.append("    momentum book means trimming winners. **This one is Zak's (§0.3).**")
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
