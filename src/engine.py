"""§3 of `docs/yuna_plan.md`, as functions. The one definition of what the engine decides.

The nightly `score` job and the `concentrated` backtest both call this. That is the whole point of
the file existing: for most of this programme the rule lived in the research engine and the live
machine had a different rule entirely, and the only reason that never cost money is that the live
machine was never pointed at momentum. §6.3 changes that, and two copies of a rule become two rules
the moment one is edited — which this repo has now paid for three times (M4, breakout confirmation,
and the duplicate-pair test that lived in SQL and numpy at once).

**Every constant here is §3.6's, and §3.6 is the whole table.** Nothing is inferred, tuned, or
carried over from a prior version. Where the plan states no number the function takes an argument
and the caller must supply one — it does not invent a default.

Deliberately pure: arrays in, decisions out, no database and no clock. The job that reads the tape
and writes the order sheet lives in `score.py`; what it may not do is decide anything this file
does not.

**Nothing here places an order.** §0.2 — Yuna rules names inside the plan's gates, Zak executes.
These functions return proposals.
"""
import hashlib
import json
import warnings

import numpy as np


def median_addv(dv, i, window=None):
    """§3.2's "50-session median ADDV", NaN where a name has no dollar volume in the window.

    NaN is the CORRECT answer for a name with no bars, and it is load-bearing: every comparison
    against NaN is False, so an unpriced name fails the liquidity gate rather than passing it. The
    warning numpy raises for an all-NaN slice is therefore expected on every session that carries a
    delisted or newly-quarantined name, and it is silenced here rather than in the caller so the
    reason travels with the arithmetic. Warnings nobody can act on are how real ones get ignored.
    """
    lo = max(0, i - (window or ADDV_WINDOW) + 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(dv[lo:i + 1], axis=0)

# ---- §3.6, the constants of record ------------------------------------------------------------
# Quoted from the table verbatim. A change to any of these is a plan amendment (§0.3), not a code
# change, and `param_digest` is what makes a run's constants auditable after the fact.
SLOTS = 5                    # §3.5 "Slots: 5, equal weight"
EXIT_RANK = 12               # §3.5 "a holding ranked below 12 queues that night"
FILL_BAND = 12               # §3.5 "Free slots: fill from the top 12 by rank"
DISPLACE_BAND = 2            # §3.5 "the best unheld name in the top 2 ranks strictly better"
GATE_SMA = 200               # §3.4 "the mean of its last 200 adjusted closes (inclusive of today)"
LATCH_OUT = 1                # §3.4 "1 red session -> OFF"
LATCH_IN = 3                 # §3.4 "3rd consecutive green session -> ON"
SCREEN_MIN_BARS = 210        # §3.2 ">=210 finite bars in the last 252"
SCREEN_WINDOW = 252          # §3.2 "in the last 252"
SCREEN_MIN_PRICE = 5.0       # §3.2 "raw close >= $5"
SCREEN_MIN_ADDV = 10_000_000.0   # §3.2 "50-session median ADDV >= $10M"
ADDV_WINDOW = 50             # §3.2 "50-session median"
POOL = 500                   # §3.2 "Pool: top 500 survivors by ADDV"
FORMATION = 252              # §3.3 "adj[i-252]"
SKIP = 21                    # §3.3 "adj[i-21]"
VOL_WINDOW = 252             # §3.3 "stdev(daily returns, 252)"
MAX_PARTICIPATION = 0.98     # §3.6 "Participation: <=0.98 ADDV"
PARK = "SPY.US"              # §3.6
REGIME_SOURCE = "SPY.US"     # §3.6


def constants():
    """§3.6 as a dict — every number this file decides under, and nothing else.

    Built by NAME rather than by scanning the module, so a constant added here without being added
    to this list is invisible to the digest. That is the safe direction: a stamp that silently
    grows is a stamp that cannot be compared across two builds.
    """
    return {"SLOTS": SLOTS, "EXIT_RANK": EXIT_RANK, "FILL_BAND": FILL_BAND,
            "DISPLACE_BAND": DISPLACE_BAND, "GATE_SMA": GATE_SMA, "LATCH_OUT": LATCH_OUT,
            "LATCH_IN": LATCH_IN, "SCREEN_MIN_BARS": SCREEN_MIN_BARS,
            "SCREEN_WINDOW": SCREEN_WINDOW, "SCREEN_MIN_PRICE": SCREEN_MIN_PRICE,
            "SCREEN_MIN_ADDV": SCREEN_MIN_ADDV, "ADDV_WINDOW": ADDV_WINDOW, "POOL": POOL,
            "FORMATION": FORMATION, "SKIP": SKIP, "VOL_WINDOW": VOL_WINDOW,
            "MAX_PARTICIPATION": MAX_PARTICIPATION, "PARK": PARK,
            "REGIME_SOURCE": REGIME_SOURCE}


def digest():
    """A short stable hash of §3.6, stamped on every decision the engine records.

    §0.3 makes a constant change a plan amendment, and this is what makes the amendment visible
    after the fact: two sessions that disagree while carrying the same digest disagree about the
    DATA, and two that carry different digests disagree about the LAW. Without the stamp those two
    failures look identical in the record, and they need opposite responses.
    """
    payload = json.dumps(constants(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def screen(i, adj, raw, dv, *, pool=POOL):
    """§3.2 — who is eligible to be ranked at session `i`. Uses bars <= i only.

    Returns column indices, narrowed to the top `pool` by ADDV. `pool=None` skips the cap and
    returns every survivor, which is what §4.4's second gauge measures — the capped count is
    exactly 500 on any ordinary session and therefore cannot move when the tape breaks.

    The pool cap is not decoration. Ranking over all ~3,000 liquid US names rather than the largest
    500 reaches deep into small caps where 12-1 momentum is mostly volatility that mean-reverts;
    the first concentrated grid measured the cost at 16.66% / -56.5% against SPMO's 21.12% / -31.0%.
    Dollar volume is the point-in-time proxy for size, because a real index-membership series is not
    in the store and reconstructing one from today's index would be look-ahead.
    """
    if i < FORMATION + 1:
        return np.array([], dtype=int)
    past, recent = adj[i - FORMATION], adj[i - SKIP]
    live = np.isfinite(past) & np.isfinite(recent) & (past > 0)
    bars = np.isfinite(adj[max(0, i - SCREEN_WINDOW + 1):i + 1]).sum(axis=0)
    addv = median_addv(dv, i)
    with np.errstate(invalid="ignore"):
        ok = (live & (bars >= SCREEN_MIN_BARS) & (raw[i] >= SCREEN_MIN_PRICE)
              & (addv >= SCREEN_MIN_ADDV))
    idx = np.where(ok)[0]
    if pool is not None and len(idx) > pool:
        # Stable, because this sort decides WHO IS IN THE POOL — a tie at the 500th place silently
        # swaps one company for another and the whole book differs downstream.
        idx = idx[np.argsort(-addv[idx], kind="stable")[:pool]]
    return idx


def rank(i, adj, raw, dv):
    """§3.3 — `(adj[i-21] / adj[i-252] - 1) / stdev(daily returns, 252)`, descending.

    Returns column indices best-first. **The rank is the entire opinion** (§3.3): no earnings, no
    themes, no fundamentals, no news.

    `kind="stable"` is not about ties being common — it is about the book being reproducible.
    numpy's default quicksort is unstable, so two names on an identical score land in whichever
    order the implementation happens to produce, and that can differ between builds. The tape loads
    in ticker order, so a stable sort breaks a tie ticker-ascending, identically on every machine.
    Exact ties are rare on real prices and completely reliable on the case we know exists: a
    duplicate listing carries an identical series and therefore an identical score.
    """
    idx = screen(i, adj, raw, dv)
    if not len(idx):
        return []
    score = adj[i - SKIP][idx] / adj[i - FORMATION][idx] - 1.0
    window = adj[max(0, i - VOL_WINDOW):i + 1, idx]
    rets = np.diff(window, axis=0) / window[:-1]
    vol = np.nanstd(rets, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        score = np.where(vol > 0, score / vol, np.nan)
    ok = np.isfinite(score)
    idx, score = idx[ok], score[ok]
    return [int(j) for j in idx[np.argsort(-score, kind="stable")]]


def gate_green(i, index_px):
    """§3.4's signal: SPY's adjusted close **strictly above** the mean of its last 200, today included."""
    if i < GATE_SMA - 1:
        return False
    window = index_px[i - GATE_SMA + 1:i + 1]
    if not np.isfinite(window).all():
        return False                     # §3.4: "If the gate cannot be evaluated on fresh data, it reads OFF"
    return bool(index_px[i] > window.mean())


def gate_state(i, index_px, previous):
    """§3.4's latch: 1 red session turns the book OFF, the 3rd consecutive green turns it ON.

    Asymmetric on purpose, and the asymmetry is the whole design. Leaving late costs money once;
    returning early costs money at every dead-cat bounce, and 2008-09 had several.

    `previous` is the state carried from the last session — True for ON, False for OFF. The
    caller persists it, because a latch with no memory is not a latch. On the first evaluation
    pass None means "unknown", and an unknown gate reads OFF: §3.4 says a gate that cannot be
    evaluated is off, and not knowing counts.
    """
    if previous is None:
        previous = False
    if not gate_green(i, index_px):
        return False                     # LATCH_OUT = 1: one red session is enough
    if previous:
        return True
    greens = 0
    for k in range(i, max(-1, i - LATCH_IN), -1):
        if gate_green(k, index_px):
            greens += 1
        else:
            break
    return greens >= LATCH_IN


def gate_history(index_px):
    """Every session's gate state, walked forward from the first evaluable one.

    The latch is DERIVED rather than stored, and that is deliberate. A persisted flag is one more
    thing that can be stale, and §3.4 already says an unevaluable gate reads OFF — a stored row
    that survives a failed ingest would say ON while the data behind it is missing, which is
    precisely the state the clause exists to forbid. Walking it forward from the tape makes tonight's
    answer a function of the tape and nothing else, so it is identical in the backtest, in the
    shadow, and on the morning Zak reads it.

    Returns an array of bools the same length as `index_px`; sessions before the 200-day window can
    be evaluated are OFF, which is the same answer §3.4 gives for any gate it cannot evaluate.
    """
    state = np.zeros(len(index_px), dtype=bool)
    prev = False
    for i in range(len(index_px)):
        prev = gate_state(i, index_px, prev)
        state[i] = prev
    return state


def orders(ranked, held, *, gate_on, twin_of=None, slots=SLOTS, exit_rank=EXIT_RANK,
           fill_band=FILL_BAND, displace_band=DISPLACE_BAND):
    """§3.5 — what the book does tonight, given tonight's rank and what it holds.

    Returns `(sells, buys)` as column indices. **Exits are obligations; entries are options**
    (§3.5), which is why a sell is never conditional on a buy being fillable.

    Gate OFF sells everything and buys nothing — §3.4, "the entire book sells at the next
    executable open; queued exits clear; all proceeds to park. No buys of any kind while OFF."

    `twin_of(a, b)` answers "are these two columns the same security under two symbols", and it
    enforces §3.7(3): *"Dual-listed / share-class twins inside the top 12: hold at most one of a
    pair; prefer the higher-ADDV line."* It is a CALLABLE rather than a precomputed set because the
    test needs the tape and this module never touches one — the caller supplies the relation, this
    function supplies the rule.

    Without it the book can hold one company in two of five slots at 1.25x the intended weight,
    with every cap counting it twice. That is not hypothetical: `verify_run.py` B7 found exactly
    that in run 589, seven times. `ranked` arrives best-first, so skipping any candidate that twins
    something already kept or already queued prefers the better-ranked line — and §3.2's pool is
    ordered by ADDV, so on a genuine dual listing the better-ranked line is the higher-ADDV one.
    """
    rank_of = {j: r for r, j in enumerate(ranked, start=1)}
    if not gate_on:
        return list(held), []

    # §3.5 exit: "a holding ranked below 12 queues that night". A name that has fallen out of the
    # ranking entirely is below 12 by definition — it did not survive the screen.
    sells = [j for j in held if rank_of.get(j, 10 ** 9) > exit_rank]
    keeping = [j for j in held if j not in sells]

    # §3.5 displacement: "if the best unheld name in the top 2 ranks strictly better than the worst
    # holding — swap. At most one displacement per session."
    if len(keeping) >= slots:
        worst = max(keeping, key=lambda j: rank_of.get(j, 10 ** 9))
        for j in ranked[:displace_band]:
            if j in held:
                continue
            if rank_of.get(j, 10 ** 9) < rank_of.get(worst, 10 ** 9):
                sells.append(worst)
                keeping.remove(worst)
            break                        # only the best candidate is ever considered

    # §3.5 free slots: "fill from the top 12 by rank. Multiple slots may fill in one session."
    buys, room = [], slots - len(keeping)
    for j in ranked[:fill_band]:
        if room <= 0:
            break
        if j in keeping or j in buys:
            continue
        # §3.7(3): at most one of a twin pair. Checked against what is being KEPT and what is
        # already queued this session — a pair that arrives together in the top 12 would otherwise
        # both fill, which is the case the register was written for.
        if twin_of and any(twin_of(j, k) for k in keeping + buys):
            continue
        buys.append(j)
        room -= 1
    return sells, buys


def position_size(nav, price, *, slots=SLOTS):
    """§3.5 — "Position size = engine NAV / 5, marked at the decision close".

    Whole shares, rounded DOWN. §3.7(4) accepts fractional shares where the broker supports them
    and rounds down otherwise, with the residue parking; rounding down is the conservative half and
    the only one that cannot overspend the slot.
    """
    if price is None or price <= 0:
        raise ValueError("cannot size a position on a missing or non-positive price")
    return int(nav / slots // price)


def participation_ok(qty, price, addv, *, cap=MAX_PARTICIPATION):
    """§3.5 — "an order may not exceed 0.98 of the name's ADDV".

    §3.5 calls this "a correctness check, not a live constraint at current size", which is exactly
    why it is worth having: a check that never fires at $200k is the one that will fire silently
    at $2M if nobody wrote it.
    """
    if not addv or addv <= 0:
        return False                     # unknown liquidity is not permission
    return (qty * price) <= cap * addv
