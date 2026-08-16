"""signals — every formula in the plan, as pure functions over arrays.

No database, no vendor, no clock. The nightly job, the weekly rank and both backtests import
from here, so there is exactly one base detector, one stop ratchet and one hurdle solver in the
system. Before this module the base detector existed twice and the two copies disagreed with
each other and with §3.2.

Section references are to `docs/yuna_plan.md`. Where a number appears here it is the plan's
number; anything a caller may reasonably tune arrives as a keyword argument with the plan's
value as its default.
"""
import math
import datetime as dt
import numpy as np

# ---------------------------------------------------------------------------- percentiles


def pct_rank(values):
    """Cross-sectional percentile 0..100. NaN in, NaN out; a lone value scores 50."""
    v = np.asarray(values, dtype=float)
    out = np.full(v.shape, np.nan)
    ok = ~np.isnan(v)
    n = int(ok.sum())
    if n > 1:
        out[ok] = 100.0 * v[ok].argsort().argsort().astype(float) / (n - 1)
    elif n == 1:
        out[ok] = 50.0
    return out


# ---------------------------------------------------------------------------- M1 market gate


def weekly_closes(dates, closes):
    """Last trading day of each ISO week -> [(week_end, close)] ascending (§3.2 M1)."""
    weeks = {}
    for d, c in zip(dates, closes):
        k = d.isocalendar()[:2]
        if k not in weeks or d > weeks[k][0]:
            weeks[k] = (d, c)
    return sorted(weeks.values())


def market_gate(dates, closes, previous=None, window=30, lookback_weeks=4):
    """M1 — Weinstein stage on weekly closes, latched (§3.2).

    ON when the Friday close is above the 30-week average *and* the average is no lower than it
    was 4 weeks ago. OFF when the close is below the average. Anything else holds the previous
    state — price above a *falling* average changes nothing.
    """
    wk = weekly_closes(dates, closes)
    if len(wk) < window + lookback_weeks + 1:
        raise ValueError(f"need {window + lookback_weeks + 1} weekly closes, have {len(wk)}")
    c = np.array([x[1] for x in wk], dtype=float)
    sma = np.convolve(c, np.ones(window) / window, mode="valid")
    close_now, sma_now, sma_then = float(c[-1]), float(sma[-1]), float(sma[-1 - lookback_weeks])
    turns_on = close_now > sma_now and sma_now >= sma_then
    if previous is None:
        state = "ON" if turns_on else "OFF"
    elif previous == "ON":
        state = "OFF" if close_now < sma_now else "ON"
    else:
        state = "ON" if turns_on else "OFF"
    return dict(week_end=wk[-1][0], state=state, spx=close_now, sma=sma_now, sma_lookback=sma_then,
                flipped=previous is not None and state != previous, previous=previous)


# ---------------------------------------------------------------------------- M2 trend template


def trend_template(close, *, off_high=0.25):
    """M2 — Minervini's six conditions, at the current price (§3.2).

    `off_high` is the last condition — how far below the 52-week high the price may sit. The law's
    25% rejects the names that produce +100% years 36% of the time, because those names correct
    hard on the way up; a caller may scale it to the stock's own volatility (see
    `volatility_tolerance`). Default is the law.
    """
    c = np.asarray(close, dtype=float)
    if len(c) < 252:
        return False
    s50, s150, s200 = (float(np.mean(c[-n:])) for n in (50, 150, 200))
    s200_21 = float(np.mean(c[-221:-21]))
    lo52, hi52, px = float(np.min(c[-252:])), float(np.max(c[-252:])), float(c[-1])
    return bool(px > s150 and px > s200 and s150 > s200 and s200 > s200_21 and px > s50
                and px >= lo52 * 1.30 and px >= hi52 * (1 - off_high))


# ---------------------------------------------------------------------------- M3 base detection


def volatility_tolerance(atr_pct, *, floor, mult, ceiling=0.60):
    """How much give a rule should allow a name, scaled to how much it actually moves.

    §3.2's numbers — a base no deeper than 25%, a price no more than 25% off its 52-week high —
    describe an orderly stock. A stock that doubles in a year corrects **42% on the way**, so those
    two clauses reject it seven times out of eight and a third of the time respectively. Measured
    over the names that produced +100% years, relaxing depth to 40% takes their valid-base
    frequency from 5.9% of days to 29.3%; shortening the base from 25 sessions to 12 moves it to
    6.8%. Depth is worth twenty-three points and base length is worth one.

    A flat 40% would hand a quiet name a licence it does not need, so this scales: the floor is
    the law's number, and a name gets more only in proportion to its own ATR.
    """
    if atr_pct is None or not np.isfinite(atr_pct) or atr_pct <= 0:
        return floor
    return float(min(max(floor, mult * float(atr_pct)), ceiling))


def resumed(closes, *, window=20):
    """Buying back into strength — the close clears the highest close of the prior `window`.

    Deliberately not anchored on our own exit price. Of 200 positions stopped out, 96% traded back
    above the exit inside 60 days and the average best subsequent move was +26.8% — we are wrong
    about the moment, not the name. But where we happened to sell is our history, not the stock's,
    and §3.2 has no way back in at all: re-entry needs a fresh valid base, which for a name that
    corrects 42% takes months it does not have. A new high is the market's own statement that the
    move resumed.
    """
    c = np.asarray(closes, dtype=float)
    if len(c) < window + 1 or not np.isfinite(c[-1]):
        return False
    prior = c[-(window + 1):-1]
    prior = prior[np.isfinite(prior)]
    return bool(len(prior) and c[-1] > prior.max())


def base_scan(high, low, close, *, look_back=120, min_age=25, grace=0.005, max_depth=0.25,
              contraction=10):
    """M3 base detection, deterministic (§3.2 'Base detection').

    The pivot is the highest high in the window `look_back` to `min_age` sessions ago, so every
    detected base is at least 25 sessions long by construction. The base runs from the pivot's
    session to today, and is **broken** by either:

      * any later session *closing* above the pivot — the breakout already happened, or
      * any later session's *high* exceeding pivot x (1 + grace) without such a close — the
        pivot was tested and rejected, and is spent.

    Either way the answer is WAIT for the next base. Highs inside the grace band are noise:
    closes decide whether a breakout succeeded, highs beyond noise decide whether the pivot
    survives. An unbroken base is valid when its depth (pivot to lowest low) is within 25%.
    """
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    n = len(c)
    empty = dict(valid=False, pivot=None, base_len=None, depth=None, contraction_low=None,
                 broken=None, state="WAIT")
    if n < look_back:
        return empty

    window_end = n - min_age + 1            # inclusive of the session `min_age` sessions ago
    p = int(np.nanargmax(h[n - look_back:window_end])) + (n - look_back)
    pivot = float(h[p])
    if not np.isfinite(pivot) or pivot <= 0:
        return empty

    later_c, later_h = c[p + 1:], h[p + 1:]
    closed_above = bool(np.any(later_c > pivot))
    poked_above = bool(np.any(later_h > pivot * (1 + grace)))
    broken = "breakout" if closed_above else ("spent" if poked_above else None)

    depth = (pivot - float(np.nanmin(l[p:]))) / pivot
    valid = broken is None and depth <= max_depth
    return dict(valid=valid, pivot=pivot, base_len=n - p, depth=depth,
                contraction_low=float(np.nanmin(l[-contraction:])),
                broken=broken, state="BUY" if valid else "WAIT")


# ---------------------------------------------------------------------------- MCN


def momentum_quality(adj_close, *, window=90, vol_divisor=True):
    """Annualised slope of the log-price regression x R^2, divided by volatility (§3.2).

    `vol_divisor=False` is hypothesis S1. The divisor is Clenow's, and it belongs with
    volatility-scaled position sizing; §3.2's stop cap flattens sizing to near-uniform, so the
    law takes the ranking penalty without the sizing benefit and systematically de-ranks the only
    names that produce a tail. Default is the law.
    """
    a = np.asarray(adj_close, dtype=float)
    if len(a) < window + 1 or np.any(a[-(window + 1):] <= 0):
        return np.nan
    y = np.log(a[-window:])
    x = np.arange(float(window))
    xc = x - x.mean()
    slope = float((xc * (y - y.mean())).sum() / (xc ** 2).sum())
    resid = y - (slope * xc + y.mean())
    ss_tot = float(((y - y.mean()) ** 2).sum()) or 1e-12
    r2 = max(0.0, 1.0 - float((resid ** 2).sum()) / ss_tot)
    if not vol_divisor:
        return slope * 252.0 * r2
    vol = float(np.std(np.diff(np.log(a[-(window + 1):])))) or 1e-9
    return slope * 252.0 * r2 / vol


def atr(high, low, close, *, window=14):
    """Wilder's true range, simple-averaged over `window` — the ATR(14) §3.2 asks for."""
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    if len(c) < window + 1:
        return np.array([])
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return np.convolve(tr, np.ones(window) / window, mode="valid")


def atr_fraction(high, low, close):
    """ATR(14) as a fraction of the last close — the unit `volatility_tolerance` scales by.

    Distinct from `setup_proximity`'s `atr_pct`, which is an inverted own-history *percentile*
    (0..100) used for ranking. This is the raw amount the name moves in a day, and on our own
    L1-M names it runs 2.86% at the median.
    """
    a = atr(high, low, close)
    px = float(np.asarray(close, dtype=float)[-1]) if len(close) else np.nan
    if not len(a) or not np.isfinite(px) or px <= 0:
        return None
    return float(a[-1]) / px


def setup_proximity(high, low, close, volume, *, own_window=252):
    """Three equal sub-scores: tight, quiet, near its highs (§3.2, after S1-S5).

    Returns raw sub-scores. `atr_pct` is already an own-history percentile inverted (0..100);
    `dryup` and `near_high` are cross-sectional and get pct_rank'd by the caller. The fourth
    sub-score (pullback contraction) was deleted from the plan — noisiest signal, both of its
    windows invented — and must not come back.
    """
    a = atr(high, low, close)
    if not len(a):
        return dict(atr_pct=np.nan, dryup=np.nan, near_high=np.nan)
    hist = a[-own_window:] if len(a) >= own_window else a
    atr_pct = 100.0 - 100.0 * float(np.mean(hist <= a[-1]))

    v = np.asarray(volume, dtype=float)
    v50 = float(np.mean(v[-50:])) or 1e-9
    dryup = -float(np.mean(v[-10:])) / v50           # less volume is better, so negate

    c = np.asarray(close, dtype=float)
    hi = float(np.max(c[-own_window:])) or 1e-9
    return dict(atr_pct=atr_pct, dryup=dryup, near_high=float(c[-1]) / hi)


def mcn(quality_pct, setup_pct, group_pct):
    """MCN — three equal-weighted percentiles (§3.2)."""
    parts = [p for p in (quality_pct, setup_pct, group_pct) if p is not None and not np.isnan(p)]
    return float(np.mean(parts)) if parts else np.nan


# ------------------------------------------------------------------- breakout & pyramid (§3.2)

CONFIRM_MULTIPLE = 1.4
CONFIRM_SESSIONS = 3


def breakout_confirmed(volumes, baselines, *, multiple=CONFIRM_MULTIPLE):
    """Volume decides how much money rides; price decides whether you stay.

    `volumes` are the breakout session and the sessions after it (up to three, breakout day
    included); `baselines` are each session's own trailing 50-day average volume. Any one
    session at or above 1.4x its own baseline confirms — that is the late-confirmation window.
    """
    for v, b in list(zip(volumes, baselines))[:CONFIRM_SESSIONS]:
        if v is None or b is None or not np.isfinite(v) or not np.isfinite(b) or b <= 0:
            continue
        if v >= multiple * b:
            return True
    return False


def confirmation_state(volumes, baselines, *, closes=None, pivot=None,
                       sessions=CONFIRM_SESSIONS, multiple=CONFIRM_MULTIPLE,
                       hair_trigger_while_pending=False):
    """§3.2 breakout confirmation as one state machine — the mechanic ratified 2026-07-31.

    `volumes`, `baselines` and `closes` all run from the breakout session forward, one entry per
    session since entry, the breakout day included. Each baseline is that session's *own* trailing
    50-day average (`volume_baseline` in the nightly, the shifted rolling mean in the backtest) —
    a session is never its own baseline.

    Three states, and the freeze is the point of all of them:

      * **confirmed** (`True`) — some session in the window printed >= 1.4x its own baseline. The
        pyramid arms and the full target may ride.
      * **pending** (`None`) — inside the window, not yet confirmed. Frozen at 50%. It may still
        confirm late.
      * **failed** (`False`) — the window closed with no qualifying session. Frozen at 50% for
        good; the stalled-pyramid rule resolves it, and normal stops still apply.

    Volume never exits a position — that was the pre-amendment rule, it cost 171 trades and 4.7%
    of NAV in run 5, and it is gone. The only exit here is the **hair-trigger**: while the breakout
    is unconfirmed, a close back below the pivot means the breakout failed by the only judge that
    matters, and the position leaves at the next open.

    **Ruled 2026-08-10 (Zak): the position waits out the window.** §3.2's wording — the
    hair-trigger applies "while unconfirmed" — could be read as arming it from the breakout EOD,
    pending included. It does not: a name inside its three-session window has not yet failed, and
    cutting it there forfeits every late confirmation. The hair-trigger arms once the window
    closes, which is what `arming.py` was already doing.

    **What limits the wait is the stop, which is placed at entry and never lifts** —
    `max(final-contraction low, entry - 8%)`, and never wider than 8% (§3.2 Stops). A name that
    falls apart inside the window is stopped out on price like any other; it is not unprotected,
    it is protected by the rule that protects everything else.

    `hair_trigger_while_pending=True` keeps the discarded reading available so the backtest can
    price the ruling rather than assume it — on the ten-year run the hair-trigger was the single
    largest loss bucket, 158 trades at -1.61%, so the difference is worth measuring, not asserting.
    """
    v = list(volumes or [])
    b = list(baselines or [])
    seen = len(v)
    confirmed = breakout_confirmed(v, b, multiple=multiple)
    expired = seen >= sessions

    state = True if confirmed else (False if expired else None)
    unconfirmed = state is False or (state is None and hair_trigger_while_pending)

    below = False
    if closes is not None and pivot is not None and len(closes):
        last = closes[-1]
        below = last is not None and np.isfinite(last) and float(last) < float(pivot)

    return dict(confirmed=state,
                pyramid_armed=state is True,
                fraction=1.0 if state is True else 0.5,
                exit_next_open=bool(unconfirmed and below),
                closed_below_pivot=bool(below),
                sessions_seen=seen,
                sessions_left=max(0, sessions - seen))


def stagnant(*, sessions_since_high, limit):
    """H4 — a position that has stopped making progress, whatever size it reached.

    §3.2's stalled-pyramid rule turned out to be the law's only profit centre: +$29,284 of a
    -$9,090 total, exiting at +4.39% after 21 sessions. Nobody designed it as profit-taking. It
    read as housekeeping — "no permanent sub-scale positions" — and it only fired on positions
    *below full size*, which under the law was two thirds of the book by accident of a 29%
    volume-confirmation rate.

    Confirming before entry completes the pyramid on 56-62% of positions, so the clock stops
    firing and the profit centre disappears with it. This generalises what the clock was actually
    doing, without depending on the pyramid: resolve a position that has not made a new high in
    `limit` sessions. A name still printing new highs never triggers, so it keeps the runners the
    fixed four-week clock would have cut.
    """
    return bool(limit) and sessions_since_high >= limit


def stalled_pyramid(*, pyramid_step, sessions_held, full_step=3, weeks=4, sessions_per_week=5):
    """§3.2: "A pyramid stalled below full size for 4 weeks either completes on the next base or
    exits — no permanent sub-scale positions." Four weeks is 20 sessions, not 28 days."""
    return pyramid_step < full_step and sessions_held >= weeks * sessions_per_week


def m4_acceleration(eps_by_quarter, *, strong=0.25, accelerating=0.15, swing=False):
    """§3.2 M4 — latest reported quarter YoY EPS growth >= 25%, **or** accelerating for two
    consecutive quarters with the latest >= 15%.

    `eps_by_quarter` is newest-first: an ordered sequence of EPS values, one per *reported*
    quarter. Each quarter is compared with the one four reported quarters back, so a skipped
    filing shifts the comparison rather than inventing a base. A non-positive base year yields no
    growth rate at all — a swing from a loss is not a growth rate, and dividing by it invents one.

    The point-in-time caller filters by filing date before calling; the nightly passes what it
    holds. Same arithmetic either way, which is the point of it living here.
    """
    eps = [e for e in eps_by_quarter if e is not None and np.isfinite(e)]
    yoy, swung = [], False
    for i, v in enumerate(eps[:8]):
        base = eps[i + 4] if i + 4 < len(eps) else None
        if base is not None and base <= 0 and v > 0:
            # Hypothesis S3: a swing from a loss to a profit. No growth rate exists — you cannot
            # divide by a negative base — so the law scores it as unknown and the name never
            # reaches L1-M. MU went -$1.07 to +$1.18 across 2024, stayed invisible through the
            # whole recovery, then ran +1,029%. §3.2's intent plainly covers it; the formula
            # cannot express it.
            if i == 0:
                swung = True
            yoy.append(None)
            continue
        yoy.append((v / base - 1) if base and base > 0 else None)
    y0 = yoy[0] if yoy else None
    y1 = yoy[1] if len(yoy) > 1 else None
    passes = bool((y0 is not None and y0 >= strong)
                  or (y0 is not None and y1 is not None and y0 > y1 and y0 >= accelerating)
                  or (swing and swung))
    return dict(passes=passes, yoy_latest=y0, yoy_prev=y1, quarters=len(eps),
                loss_to_profit=swung)


ENTER_FLOOR = 70.0


def enterable(mcn_score, *, floor=ENTER_FLOOR):
    """§3.2 Sizing: "MCN < 70 never tickets — BUY-state names below 70 stay queued."

    A gate, not a size adjustment: a name below the floor is never armed at all. It lives here so
    that both the nightly and the backtest ask the same question — the backtest never asked it,
    and 211 of run 5's 296 trades were entries this returns False for.
    """
    return bool(mcn_score is not None and np.isfinite(mcn_score)
                and float(mcn_score) >= float(floor))


def pyramid_orders(pivot, *, ceiling=1.05, spacing=None, tranches=3):
    """Steps 2 and 3 as resting add stop-limits: triggers +2% / +4%, both limits pivot x 1.05.

    A gap that skips a band completes at the open automatically; a gap beyond the ceiling fills
    nothing. The ceiling enforces itself at the broker, unwatched (§3.2, X2).

    `spacing` widens the ladder for hypothesis A1 — Zak's "3 tranches or so that are 5% apart",
    against §3.2's 50/25/25 at +0/+2/+4%. Equal thirds rather than a half up front, because the
    point of averaging in is that the later tranches are worth as much as the first. The ceiling
    has to move with the spacing or the last tranche can never fill, so it is applied relative to
    each trigger rather than to the pivot.
    """
    if not spacing:
        return [dict(step=2, fraction=0.25, trigger=pivot * 1.02, limit=pivot * ceiling),
                dict(step=3, fraction=0.25, trigger=pivot * 1.04, limit=pivot * ceiling)]
    share = 1.0 / float(tranches)
    return [dict(step=k + 1, fraction=share, trigger=pivot * (1 + k * spacing),
                 limit=pivot * (1 + k * spacing) * ceiling)
            for k in range(1, int(tranches))]


def entry_order(pivot, contraction_low, *, limit_over=0.02, max_stop=0.08):
    """The §5.1 entry pair: buy stop-limit at the pivot, and the stop that rides under it."""
    stop = initial_stop(pivot, contraction_low, max_stop=max_stop)
    return dict(trigger=pivot, limit=pivot * (1 + limit_over), stop=stop,
                fraction=0.5, stop_distance=(pivot - stop) / pivot)


def initial_stop(entry, contraction_low, *, max_stop=0.08):
    """Higher of the base's final-contraction low or entry - 8%. Never wider than 8% (§3.2).

    `max_stop=None` means no flat cap, matching `volatility_stop`. With no cap the contraction low
    is the only stop there is, and without one there is no stop at all — None, so the caller
    declines rather than being handed a level. Previously this raised a TypeError, which is how
    A2's first live run died: an arm carrying no percentage cap reached this through a door its
    preset was supposed to have closed.
    """
    floor = None if max_stop is None else entry * (1 - max_stop)
    if contraction_low is None or not np.isfinite(contraction_low):
        return floor
    return float(contraction_low) if floor is None else max(float(contraction_low), floor)


def volatility_stop(entry, atr_now, *, mult=5.0, max_stop=0.20):
    """Hypothesis R1 — a stop set by the name's own noise, not by a fixed percentage.

    §3.2 caps the initial stop at 8% and floors it at the base's final-contraction low, which in
    practice puts it 7.57% under entry. **65% of entries breach that inside 125 sessions**, so the
    law's stop and a multi-month hold are mutually exclusive: the stop fires first on two thirds of
    the names that would have produced the move. A 20% cap survives 73%.

    The multiplier is not the conventional 2.5. ATR(14) across the names this system actually
    trades runs 2.86% of price at the median, so 2.5x lands at 7.2% — the law's stop, renamed.
    5x gives roughly 14% on a median name, 11% on a quiet one and the 20% cap on a volatile one.

    Deliberately does NOT floor at the contraction low. The contraction low is what makes the law's
    stop tight, and tightness is the thing under test. `max_stop` is the widest permitted, not a
    target — a quiet name still gets a close stop because its ATR is small.
    """
    # `max_stop=None` means there is NO flat cap and the ATR alone sets the stop — A2's spec
    # (E-series E3) is "3xATR(20) from entry", with no percentage floor anywhere in it. Without an
    # ATR there is then no stop that can be formed at all, and None is the honest answer: the
    # caller must decline the entry rather than be handed an invented level.
    if atr_now is None or not np.isfinite(atr_now) or atr_now <= 0:
        return None if max_stop is None else entry * (1 - max_stop)
    floor = float(entry) - mult * float(atr_now)
    return floor if max_stop is None else max(floor, float(entry) * (1 - max_stop))


def ratchet_stop(*, closes, avg_cost, current_stop, highest_close=None, pyramid_step=0,
                 full_step=3, trail10_from=0.15, trail10=0.10, euphoria_trail=0.05,
                 euphoria_sd=2.0, sd_window=50, breakeven_r=None, init_stop=None,
                 breakeven=True, euphoria=True, breakeven_on_full_size=True,
                 breakeven_giveback=0.0):
    """The stop ladder (§3.2 Stops) — ratchets up, never down.

    Full size moves the stop to breakeven; +15% from average cost starts a 10% trail below the
    highest close since entry; a close more than 2 standard deviations above its own 50-day
    tightens that trail to 5%. The euphoria rule tightens, it never sells, and it has exactly
    one trigger — the second one was deleted from the plan in the S1-S5 round.

    `breakeven` and `euphoria` switch off the two rungs that shorten a hold rather than protect
    a gain, for hypotheses B1 and B2. Both default to the law. They are separate switches from
    `breakeven_r` on purpose: that one *moves* the breakeven trigger, and setting it to None
    restores §3.2's "at full pyramid size", which under E1 fires on most positions — so there was
    no way to ask what a position does with no breakeven under it at all.

    B1 answered that question and the answer was two-sided: deleting the rung **doubled the
    average hold, 11.9 sessions to 23.9, and more than doubled the win rate, 16.7% to 37.2%** —
    the diagnosis was right — but the average loss went -2.83% to -7.60%, because every loser now
    runs the full volatility stop. The rung is not the enemy; a rung sitting exactly at cost is,
    because price oscillates around entry and a stop parked there is a magnet.

    So two further knobs, both interpolating between those poles:

      * `breakeven_on_full_size` — whether *reaching full pyramid size* trips the rung at all, so
        a caller can keep the earned-it trigger (`breakeven_r`) and drop the sizing one.
      * `breakeven_giveback` — where the rung sits, as a fraction of the initial risk left under
        cost. 0.0 is §3.2 (exactly cost); 1.0 leaves the initial stop untouched and reproduces B1;
        0.5 halves the risk instead of erasing it, which is room without abandoning protection.
    """
    c = np.asarray(closes, dtype=float)
    if not len(c):
        return dict(stop=current_stop, mode=None, highest_close=highest_close, euphoric=False)
    px = float(c[-1])
    hc = float(np.max(c)) if highest_close is None else max(float(highest_close), float(np.max(c)))

    euphoric = False
    if euphoria and len(c) >= sd_window:
        w = c[-sd_window:]
        sd = float(np.std(w))
        euphoric = sd > 0 and px > float(np.mean(w)) + euphoria_sd * sd

    # Hypothesis R2: breakeven when the position has earned back its own risk, rather than when
    # the pyramid completes. The law ties risk management to a *sizing* milestone that three of
    # four positions never reach, so 129 stops gave back +6.56% unrealised to exit at -2.05%.
    at_1r, risk = False, None
    if avg_cost and init_stop:
        risk = (float(avg_cost) - float(init_stop)) / float(avg_cost)
        if breakeven_r is not None:
            at_1r = risk > 0 and (px / float(avg_cost) - 1) >= breakeven_r * risk

    if euphoric:
        candidate, mode = hc * (1 - euphoria_trail), "trail5"
    elif avg_cost and px / float(avg_cost) - 1 >= trail10_from:
        candidate, mode = hc * (1 - trail10), "trail10"
    elif breakeven and avg_cost and ((breakeven_on_full_size and pyramid_step >= full_step)
                                     or at_1r):
        rung = float(avg_cost)
        if breakeven_giveback and risk:
            rung *= 1 - float(breakeven_giveback) * risk
        candidate, mode = rung, "breakeven"
    else:
        candidate, mode = current_stop, "initial"

    if candidate is None:
        stop = current_stop
    elif current_stop is None:
        stop = float(candidate)
    else:
        stop = max(float(current_stop), float(candidate))
        if stop == float(current_stop) and candidate < current_stop:
            mode = "held"
    return dict(stop=stop, mode=mode, highest_close=hc, euphoric=euphoric)


def deep_recovery(high, low, close, *, min_range=0.12, min_depth=0.50, min_off_high=0.25,
                  min_r3=0.10, window=252, quarter=63):
    """The census screen (docs/backtest-findings-2026-08-10.md §9) — L1-M's replacement candidate.

    §3.2's M2 and M3 select an orderly, calm stock near its highs, and against the 2016-2026 census
    of every liquid US name that gained 70% inside six months, that description is *anti*-
    predictive: M3's depth clause has a lift of 0.04 and 99.6% of all winners fail it; M2's off-high
    clause is 0.64; the moving-average stack is 0.97, indistinguishable from random. The population
    those two gates admit returned **+1.12% per six months** before costs, which is what nineteen
    backtest runs produced from it.

    The four conditions here are the census read forwards, in the order that tightened the net:

      1. it moves at all — six-month average monthly range over 12%. Under 6% the hit rate is
         0.47%; over 12% captures 98% of every winner in the decade.
      2. it has fallen hard — the 52-week low is more than 50% under the 52-week high. Captures
         80.6% of winners at 2.33x.
      3. it is still cheap — price at least 25% under the 52-week high.
      4. it has turned — up more than 10% over the last quarter, the market's statement that the
         re-rating has begun.

    Together: 21.67% hit rate against a 6.59% base rate, +19.07% mean six-month return, and — the
    part that makes it tradeable — the winners' median drawdown after entry is -9.3% against the
    losers' -24.9%, so a stop separates them instead of taxing them.

    Returns the components as well as the verdict, because a screen whose parts cannot be seen is
    a screen nobody can debug.
    """
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    if len(c) < window or len(h) < window or len(l) < window:
        return dict(passes=False, rng=None, depth=None, off_high=None, r3=None)
    hw, lw, cw = h[-window:], l[-window:], c[-window:]
    hi52, lo52, px = float(np.nanmax(hw)), float(np.nanmin(lw)), float(c[-1])
    if not (np.isfinite(hi52) and np.isfinite(lo52) and np.isfinite(px)) or hi52 <= 0 or px <= 0:
        return dict(passes=False, rng=None, depth=None, off_high=None, r3=None)

    # monthly range, as the census measured it: mean of (high-low)/close over 21-session blocks
    blocks = [(np.nanmax(hw[i:i + 21]), np.nanmin(lw[i:i + 21]), cw[i + 20])
              for i in range(len(cw) - 21, max(len(cw) - 21 - 6 * 21, -1), -21)]
    spans = [(bh - bl) / bc for bh, bl, bc in blocks if bc and np.isfinite(bc) and bc > 0]
    rng = float(np.mean(spans)) if spans else None

    depth = lo52 / hi52 - 1.0
    off_high = px / hi52 - 1.0
    base3 = float(c[-quarter - 1]) if len(c) > quarter and c[-quarter - 1] > 0 else None
    r3 = (px / base3 - 1.0) if base3 else None

    ok = (rng is not None and rng > min_range and depth < -min_depth
          and off_high < -min_off_high and r3 is not None and r3 > min_r3)
    return dict(passes=bool(ok), rng=rng, depth=depth, off_high=off_high, r3=r3)


def profitability_dead(eps_by_quarter, *, quarters=2, worsening=False):
    """Has the business stopped making money — the only thing that ends a forever hold.

    Zak's rule (2026-08-11): a name that ran past the last trim rung "rides through the highs and
    lows unless the financials on the profitability of the company dies". Every other exit in §3.2
    is a *price* exit, and the whole point of this one is that price no longer speaks. So the test
    has to be about earnings and nothing else.

    `eps_by_quarter` is newest first, as `m4_acceleration` takes it. Dead means the last `quarters`
    **reported** quarters are at or below zero — one bad quarter is a stumble, two consecutive is
    the profitability going away. Unknown is not dead: with no earnings we hold, because the
    alternative is selling the position on a data gap.

    `worsening` fixes what the census broke. "Two quarters at or below zero" describes the **entry
    state of 41% of every winner in 2016-2026** — being unprofitable has a lift of 2.71 against
    the base rate and being profitable 0.69 — so as a release condition it sells the best
    candidates on the day they are bought. With `worsening=True` the loss must also be **deeper
    than the same quarter a year ago**: a business losing money and getting better is not a
    business that died, and it is the single most common shape among the names that go on to run.
    """
    vals = [v for v in (eps_by_quarter or []) if v is not None and np.isfinite(v)]
    if len(vals) < quarters:
        return False
    if not all(v <= 0 for v in vals[:quarters]):
        return False
    if not worsening:
        return True
    if len(vals) <= 4:
        return False                     # no year-ago quarter to compare: unknown is not dead
    return bool(vals[0] < vals[4])


def momentum_size(*, nav, mcn_score, stop_distance, budgets=(0.007, 0.009), band=(0.08, 0.12),
                  full_conviction=85.0, floor_nav=0.04, start_low=False,
                  start_low_budgets=(0.005, 0.007)):
    """size = risk budget / stop distance, capped by the band and the sleeve (§3.2 Sizing).

    During the start-low window the reduced budgets may size below the band floor — the
    start-low rule overrides the floor, and the 4% NAV minimum still binds.
    """
    lo, hi = start_low_budgets if start_low else budgets
    budget = hi if mcn_score is not None and mcn_score >= full_conviction else lo
    if not stop_distance or stop_distance <= 0:
        return None
    # The band is a CEILING, not a target. Raising a computed size up to the 8% band floor would
    # put more NAV at risk than the budget allows, and the budget is the law here — "the budget is
    # how much NAV is lost if the stop fires". It cannot bind in practice either: stops are never
    # wider than 8% (§3.2), so 0.7% / 0.08 = 8.75% is the smallest a steady-state position can be.
    # Only the start-low window sizes below the band, which §3.2 explicitly permits.
    pct = min(budget / stop_distance, band[1])
    return dict(size_pct=pct, budget=budget, cad=pct * nav if nav else None,
                below_floor=pct < floor_nav)


# ---------------------------------------------------------------------------- compounders


def ccn(components, *, required=("engine", "durability")):
    """CCN — equal weight over engine · cash conversion · durability (§3.1, §3.3).

    Two of the three may never be renormalized away. §3.3 is explicit about the engine: "the
    compounding engine never routes here — renormalizing away the engine pays a name for being
    unmeasurable (missingness travels with the very components that survive)". That is not a
    theory. Under the old rule the fifteen highest CCNs in production were fifteen dropped-engine
    names, because unmeasurable engines cluster in businesses that score high on what remains, and
    dropping a component imputes it at the mean of the survivors. Every drop was a promotion.

    Durability carries the same bar by its own clause — under three reported years of ROIC the name
    is not bench-eligible — so the only component that can go missing is cash conversion, and that
    is the one §3.3's renormalization was written for.
    """
    have = {k: v for k, v in components.items() if v is not None and not np.isnan(v)}
    if any(k not in have for k in required):
        return dict(score=None, confidence="not-bench-eligible", used=sorted(have))
    score = float(sum(have.values()) / len(have))
    confidence = "full" if len(have) == len(components) else f"{len(have)}of{len(components)}"
    return dict(score=score, confidence=confidence, used=sorted(have))


def engine_agrees(engine, revenue_cagr, *, tolerance=0.05):
    """§3.1 reliability check: growth = ROIC x reinvestment is an identity, so the computed engine
    must agree with observed 3-year revenue growth within 5 percentage points."""
    if engine is None or revenue_cagr is None:
        return None
    return abs(float(engine) - float(revenue_cagr)) <= tolerance


def engine_waterfall(engine, revenue_cagr, *, tolerance=0.05, cap=0.25):
    """§3.1's engine waterfall. Returns (value, provenance) — provenance is None when the name has
    no engine by either method, which makes it **not bench-eligible**.

      * computed engine agrees with observed growth within 5pp  -> ('measured')
      * unmeasurable, or diverges beyond 5pp                    -> observed 3-yr revenue growth,
                                                                    capped at 25%, 'growth-derived'
      * no revenue history either                               -> (None, None)

    Growth = ROIC x reinvestment is an identity, so the observed side of it is the honest
    substitute, and the cross-check does not apply to the substitute — it would be checking the
    number against itself.

    The floored-to-zero reinvestment defect (learnings #16 — ANET, AVGO, VRT all reading engine 0
    while compounding above 20%) needs no special clause: an engine of zero against 27% observed
    growth fails the cross-check arithmetically and falls back on its own.
    """
    if engine is not None and revenue_cagr is not None \
       and abs(float(engine) - float(revenue_cagr)) <= tolerance:
        return float(engine), "measured"
    if revenue_cagr is not None:
        return min(float(revenue_cagr), cap), "growth-derived"
    return None, None


# ---- Durability (§3.1) ------------------------------------------------------------------------
#
# Replaced size in the CCN on 2026-08-01. The size tilt was double-counted — the funnel's cohort
# split already carries the small-cap hunt — and a component that rewards smallness hardest turned
# the bench into a small-cap cyclical screen.

CAPITAL_FREE_BEST = float("inf")        # capital-free compounding, top-coded (§3.1)
CAPITAL_FREE_WORST = float("-inf")      # no capital AND no profit, bottom-coded


def growth_consistency(revenues, *, comparisons=5):
    """Positive-YoY years / 5, on 0-100 (§3.1).

    `revenues` are annual revenues newest-first. Five comparisons need six fiscal years; a name with
    fewer has the missing comparisons counted against it, which is what "unreported years count
    against" means — the denominator is always 5.
    """
    vals = [None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
            for v in (revenues or [])]
    positive = 0
    for i in range(comparisons):
        if i + 1 < len(vals) and vals[i] is not None and vals[i + 1] is not None \
           and vals[i + 1] > 0 and vals[i] > vals[i + 1]:
            positive += 1
    return 100.0 * positive / comparisons


def worst_year_roic(years, *, min_reported=3):
    """The worst single reported year's ROIC over the last five (§3.1).

    `years` is [(nopat, invested_capital)] newest-first. Returns (value, reported_count); the value
    is None when fewer than three years are reported, which the plan makes **not bench-eligible**
    rather than merely unscored.

    A year with invested capital <= 0 does not produce a meaningful ratio, so §3.1 ranks it rather
    than dividing: best-percentile when NOPAT > 0 — that is capital-free compounding, the strongest
    thing a business can do — and worst when NOPAT <= 0. Infinities carry that ranking through the
    percentile step, where min() picks the floor.
    """
    scored = []
    for row in (years or [])[:5]:
        try:
            nopat, ic = row
        except (TypeError, ValueError):
            continue
        if nopat is None or ic is None:
            continue
        nopat, ic = float(nopat), float(ic)
        if np.isnan(nopat) or np.isnan(ic):
            continue
        if ic <= 0:
            scored.append(CAPITAL_FREE_BEST if nopat > 0 else CAPITAL_FREE_WORST)
        else:
            scored.append(nopat / ic)
    if len(scored) < min_reported:
        return None, len(scored)
    return min(scored), len(scored)


def durability(growth_pct, roic_floor_pct):
    """Equal-weight blend of the two sub-scores, both already on 0-100 (§3.1).

    The caller percentiles the *blend* across L0, which is what makes this component an L0
    percentile like the engine and cash conversion. Blending a 0-1 ratio with a 0-100 percentile —
    the plan's wording before the 10:22 edit — made the growth term worth half a point out of a
    hundred, which is to say inert.
    """
    parts = [p for p in (growth_pct, roic_floor_pct) if p is not None and not np.isnan(p)]
    if len(parts) < 2:
        return None
    return float(sum(parts) / 2.0)


def effective_shares(market_cap, cap_date_close):
    """§3.1: effective shares = the vendor's USD market cap / the close on the cap's `as_of` date.

    The divisor is the close on the date the cap was stamped, frozen with the filing — not tonight's
    close. Using the latest close made the hurdle a function of the quote, so it decayed every night:
    `verify` found eleven mismatches running in both directions, names that had risen showing
    understated hurdles and names that had fallen showing overstated ones. A hurdle is a statement
    about a business and may only move when a filing moves it.

    The vendor's own share count is not a substitute — the cap ratio is what resolves ADR ratios,
    listing currency and share classes in one step.
    """
    if not market_cap or not cap_date_close or market_cap <= 0 or cap_date_close <= 0:
        return None
    return market_cap / cap_date_close


def expected_return(price, *, fcf_ttm, shares, growth, fair_multiple, years=5):
    """FCF yield + engine growth - derating drag, at price P (§3.1 Hurdle)."""
    cap = price * shares
    if cap <= 0 or not fcf_ttm or fcf_ttm <= 0 or not fair_multiple or fair_multiple <= 0:
        return None
    drag = max(0.0, 1.0 - (fair_multiple * fcf_ttm / cap) ** (1.0 / years))   # never a credit
    return fcf_ttm / cap + growth - drag


def hurdle_growth_ceiling(fair_multiple, *, floor=0.15):
    """§3.1: the growth rate consistent with the fair multiple and the return floor.

    A fair exit at M times FCF under an h requirement IS a growth claim — h = 1/M + g, so the only
    growth consistent with both numbers is h − 1/M (11.67% at 30x, 10% at 20x). Letting the formula
    assert 25% growth AND a 30x fair exit at the same instant was the falling-knife licence: above
    the crossover, growth alone cleared the floor and the hurdle floated free of the fair multiple
    entirely — all twelve cap-pinned names drew the identical 56x permission regardless of business
    or drawdown. Nothing here is chosen: both inputs already stand in §3.1.
    """
    if not fair_multiple or fair_multiple <= 0:
        return None
    return max(0.0, floor - 1.0 / fair_multiple)


def fair_multiple_of(pfcf_median, observations, *, cap=30.0, short_cap=25.0, min_quarters=12):
    """§3.1: the richest multiple of real cash the system will ever instruct paying.

    The stock's own median P/FCF, ceilinged at `cap`. A name we cannot price over enough quarters
    has no own-history to appeal to, so it takes the flat `short_cap` — never the lower-of-current
    form, which was circular: with shares frozen at the filing it reproduced the filing-date close
    exactly, and "is it cheap" degenerated into "has it fallen since it last filed".

    `min_quarters` is 12 by law (2026-08-02). Returns None when the name cannot be priced at all.
    """
    if observations is None or observations < min_quarters or not pfcf_median or pfcf_median <= 0:
        return short_cap
    return min(pfcf_median, cap)


def hurdle_price(*, fcf_ttm, shares, growth, fair_multiple, floor=0.15, years=5):
    """The highest price at which expected return still clears the floor (§3.1).

    Two clamps carry the 2026-08-02 law, and both live HERE so every caller — production scoring
    and the backtest alike — prices under the same rules:

      * growth is additionally capped at `hurdle_growth_ceiling(fair)`, and
      * the result never exceeds fair_multiple x FCF per share — the system never instructs paying
        a richer multiple of real cash than the stock's own history (ceiling 30x).

    With the ceiling binding, the solve collapses to closed form (FCF/share ÷ (floor − g)); the
    bisection is kept because it is exact, tested, and also prices the below-crossover names where
    the yield term still has to contribute. Returns None when the name cannot clear the floor at
    any price, which is the common case and not an error.
    """
    if not fcf_ttm or fcf_ttm <= 0 or not shares or shares <= 0 \
       or not fair_multiple or fair_multiple <= 0:
        return None

    ceiling = hurdle_growth_ceiling(fair_multiple, floor=floor)
    g = min(float(growth or 0.0), ceiling)

    def er(px):
        return expected_return(px, fcf_ttm=fcf_ttm, shares=shares, growth=g,
                               fair_multiple=fair_multiple, years=years)

    lo, hi = 0.01, max(1e4, fcf_ttm / shares * 5000.0)
    if (er(lo) or -1) < floor:
        return None
    if (er(hi) or -1) >= floor:
        hi = hi
    else:
        for _ in range(200):
            mid = (lo + hi) / 2
            if (er(mid) or -1) >= floor:
                lo = mid
            else:
                hi = mid
        hi = lo
    return min(hi, fair_multiple * fcf_ttm / shares)


def displaceable(challenger_score, incumbents, *, margin=10.0):
    """§3.3 displacement — within-sleeve only, and the challenger needs `margin` over the WEAKEST
    incumbent. `incumbents` is [(name, score)]; names with no score cannot be displaced by a
    number, so they are ignored rather than assumed weak.

    Returns the incumbent to swap out, or None. A momentum 85 never displaces a compounder 72 —
    that is the caller's job, by only passing same-sleeve incumbents.
    """
    scored = [(n, float(s)) for n, s in incumbents if s is not None and not np.isnan(float(s))]
    if not scored or challenger_score is None or np.isnan(challenger_score):
        return None
    name, score = min(scored, key=lambda x: x[1])
    if challenger_score >= score + margin:
        return dict(ticker=name, score=score, margin=challenger_score - score)
    return None


def compounder_add(*, ccn_score, price, hurdle, entry_fill, adds_this_year, enter=70.0,
                   max_adds=2):
    """Averaging down (§3.1, as amended 2026-08-01).

    Three conditions, not two: CCN >= 70, price below the hurdle, **and price below the entry fill**.
    The bands measure from the FILL — 5-15% below it adds 50% of original size, beyond 15% adds
    100% — which is what makes entry day arm nothing however deep the gap to hurdle already is. A
    position bought at a 30% discount to its hurdle used to arm a 100% add the same evening, before
    the thesis had been tested by a single session.

    Two adds per name per 12 months; crash-protocol tactical adds are exempt and uncounted here.
    """
    if ccn_score is None or ccn_score < enter or not hurdle or hurdle <= 0:
        return None
    if not entry_fill or entry_fill <= 0:
        return None                       # no fill recorded — the bands have no origin to measure from
    if price >= hurdle:
        return None
    below = (entry_fill - price) / entry_fill
    if below < 0.05:
        return None
    if adds_this_year >= max_adds:
        return dict(fraction=None, blocked="§3.1 — two adds already this year", below=below)
    return dict(fraction=0.5 if below <= 0.15 else 1.0, blocked=None, below=below)


def whole_shares(*, target_pct, nav, price_cad, band=(0.12, 0.15)):
    """Compounder share count — **ceil into the band** (§3.1 sizing, dev-fix 16).

    The target weight is the §3.1 size. Flooring a fractional share count lands the position *below*
    target — a 12% target that floors to 11.7% is outside the 12-15 band the plan sets — so the count
    rounds up whenever up still fits inside the band, and only falls back to down when it does not.

    Momentum does the opposite and floors, deliberately: there the risk budget is a ceiling on how
    much NAV a stop-out may cost, and rounding up would spend more than the budget allows.

    Worked, at NAV 200,954.12 and FX 1.402: MEDP at 577.11 wants 29.80 shares -> 30 (12.08%);
    VEEV at 203.78 wants 84.41 -> 85 (12.09%). Both land inside the band, above target.
    """
    if not nav or not price_cad or price_cad <= 0 or not target_pct:
        return None
    exact = target_pct * nav / price_cad
    up, down = math.ceil(exact), math.floor(exact)
    for qty in (up, down):
        if qty >= 1 and band[0] <= qty * price_cad / nav <= band[1]:
            return qty
    return down if down >= 1 else None


# ---------------------------------------------------------------------------- independence


def effective_bets(weights, returns, *, min_sessions=60, window=126):
    """1 / sum(wi wj rho_ij) — how many independent bets the book actually holds (§2.2).

    `weights` are normalized across the whole book, levered positions included. `returns` is a
    dict of daily return arrays; names with shorter history use what exists, and a name with
    fewer than 60 sessions is dropped from the correlation matrix rather than guessed at.
    """
    names = [n for n in weights if n in returns and len(returns[n]) >= min_sessions]
    if not names:
        return None
    total = sum(weights[n] for n in names)
    if total <= 0:
        return None
    w = np.array([weights[n] / total for n in names], dtype=float)
    span = min([window] + [len(returns[n]) for n in names])
    m = np.vstack([np.asarray(returns[n], dtype=float)[-span:] for n in names])
    rho = np.corrcoef(m) if len(names) > 1 else np.array([[1.0]])
    rho = np.nan_to_num(rho, nan=0.0)
    denom = float(w @ rho @ w)
    return 1.0 / denom if denom > 0 else None


# ---------------------------------------------------------------------------- calendars


def trading_days_between(start, end, *, holidays=()):
    """Sessions from `start` (exclusive) through `end` (inclusive), weekends removed.

    Market holidays make this conservative by at most a day or two, which widens a blackout
    rather than narrowing it — the safe direction. Pass `holidays` once we hold a calendar.
    """
    if end < start:
        return -trading_days_between(end, start, holidays=holidays)
    days, d = 0, start
    hol = set(holidays)
    while d < end:
        d += dt.timedelta(days=1)
        if d.weekday() < 5 and d not in hol:
            days += 1
    return days


def in_blackout(today, report_date, *, trading_days=5, holidays=()):
    """§3.3 — no new entries and no adds within 5 trading days of a scheduled report, the report
    session included. The blackout lifts the first session after the report session, uniformly
    for pre-open and post-close prints."""
    if report_date is None or report_date < today:
        return False
    return trading_days_between(today, report_date, holidays=holidays) <= trading_days - 1


def holds_through_earnings(last_close, avg_cost, *, cushion=1.08):
    """A momentum position holds through a print only with one stop-width of profit (§3.3)."""
    if not avg_cost or avg_cost <= 0 or last_close is None:
        return None
    return float(last_close) >= cushion * float(avg_cost)


# ---------------------------------------------------------------------------- data integrity


SUSPICIOUS_MOVE = 0.40
SOURCE_TOLERANCE = 0.02


def suspicious_move(close, prev_close, *, threshold=SUSPICIOUS_MOVE):
    """§4.1 quarantine trigger: a print moving more than 40% with no corporate action behind it.

    A 4:1 split reads as −75% and a bad tick reads as anything at all; either can fire a real stop,
    so neither is allowed to act until two sources agree.
    """
    if close is None or prev_close is None:
        return False
    try:
        close, prev_close = float(close), float(prev_close)
    except (TypeError, ValueError):
        return False
    if prev_close <= 0 or close <= 0:
        return False
    # compared as a difference against a scaled threshold, not as a ratio minus one: 140/100 - 1
    # evaluates to 0.39999999999999991 in binary floating point, so an exact 40% move would slip
    # through a ratio comparison. |140 - 100| >= 0.40 x 100 is exact.
    return abs(close - prev_close) >= threshold * prev_close


def sources_agree(a, b, *, tolerance=SOURCE_TOLERANCE):
    """Two independent prices for the same session, within tolerance of each other (§4.1).

    Absent either number the answer is *no* — an unverified print stays quarantined. Silence is
    never agreement.
    """
    if a is None or b is None:
        return False
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) <= tolerance * min(a, b)      # a difference, for the same reason as above


def split_ratio(payload):
    """EODHD reports a split as "4.000000/1.000000" — parse it to 4.0 (new shares per old).

    Needed because a split rewrites the bars but not the numbers stored *on a position*. An avg
    cost, a stop and a highest-close are all in pre-split dollars, and stops ratchet up and never
    down (§3.2) — so an unadjusted stop is stranded above the market forever, and the position
    reads as permanently stopped out.
    """
    raw = (payload or {}).get("split") if isinstance(payload, dict) else payload
    if raw is None:
        return None
    try:
        text = str(raw)
        if "/" in text:
            new, old = text.split("/", 1)
            new, old = float(new), float(old)
            return new / old if old else None
        value = float(text)
        return value or None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


# ===================================================================== A2 primitives (E-series E3)
# The trend-holding-at-breadth arm. These live here rather than in `backtest.py` because
# `signals.py` is the law expressed as code and production will need them too if A2 ever clears
# its bars. Every constant below is the work order's; none is a default.

def new_high_breakout(close, *, lookback=252):
    """True when the latest close is the highest close of the trailing `lookback` sessions.

    A2's entry (E3 center spec), replacing §3.2's pivot-and-base machinery. The trade-off is
    deliberate: a base breakout tries to buy the moment a trend starts, a new-high breakout simply
    buys names already making highs. The second is cruder and much broader, and breadth is the
    whole point of A2 — the sensitivity ladder swaps 252 for the all-time high.

    Compares against the PRIOR window, so the current bar clearing its own high is not circular.
    """
    c = np.asarray(close, dtype=float)
    if len(c) < lookback + 1:
        return False
    window = c[-(lookback + 1):-1]
    if not np.isfinite(c[-1]) or not np.isfinite(window).any():
        return False
    return bool(c[-1] > np.nanmax(window))


def chandelier_stop(highest_close, atr_value, *, multiple=8.0):
    """Highest close since entry, less `multiple` ATRs. Ratchets up only — the caller enforces it.

    A2's runner exit. 8x is very wide on purpose: the arm's thesis is that the tail pays for
    everything, and the way a trend-follower kills its own tail is by exiting on noise. §7f and M1
    both said the same thing from the other direction — the mechanics were never the problem, the
    holding was.
    """
    if not np.isfinite(highest_close) or not np.isfinite(atr_value) or atr_value <= 0:
        return None
    return float(highest_close - multiple * atr_value)


def risk_size(*, nav, entry, stop, risk_frac=0.005):
    """Shares such that a stop-out costs `risk_frac` of NAV. Never conviction-weighted.

    This is the M1 lesson made structural. M1 had a positive per-trade expectancy of +2.21% and
    still lost 8.07% with a -39.89% drawdown, because size was set by conviction rather than by
    what the stop would cost. Here the stop distance sets the size, so a wide stop buys less and a
    tight stop buys more, and every position risks the same fraction of the account.

    Returns 0.0 when the stop is not below the entry — a non-positive risk distance has no size,
    and inventing one is how a divide-by-zero becomes a position.
    """
    if not all(np.isfinite(x) for x in (nav, entry, stop)):
        return 0.0
    risk_per_share = entry - stop
    if risk_per_share <= 0 or nav <= 0 or entry <= 0:
        return 0.0
    return float(nav * risk_frac / risk_per_share)


def regression_momentum(close, *, window=90, sessions_per_year=252):
    """How fast the trend runs, times how cleanly it runs — Clenow's momentum score (WO-A3 §3).

    Least-squares fit of ln(price) on time over the trailing `window` sessions: the slope,
    annualized as exp(m x 252) - 1, answers "what would a year of this trajectory return", and
    the fit's R² discounts it by how much the path actually hugged that trajectory. A parabolic
    mover and a grinder can share a slope; the R² separates them — and the frog-in-the-pan
    result (Da-Gurun-Warachka, RFS 2014: +5.94%/mo continuation for smooth arrivals against
    -2.07% for gappy ones on the same cumulative gain) is the measured reason the product, not
    the slope alone, is the score.

    Returns dict(slope_ann, r2, score) or None when the window is short, non-positive, or flat —
    a trend that cannot be scored is declined, never defaulted.
    """
    c = np.asarray(close, dtype=float)
    if len(c) < window or np.any(~np.isfinite(c[-window:])) or np.any(c[-window:] <= 0):
        return None
    y = np.log(c[-window:])
    x = np.arange(window, dtype=float)
    xm, ym = x.mean(), y.mean()
    sxx = ((x - xm) ** 2).sum()
    if sxx == 0:
        return None
    m = ((x - xm) * (y - ym)).sum() / sxx
    ss_res = ((y - (ym + m * (x - xm))) ** 2).sum()
    ss_tot = ((y - ym) ** 2).sum()
    if ss_tot < 1e-18:
        return None
    slope_ann = float(np.exp(m * sessions_per_year) - 1.0)
    r2 = float(1.0 - ss_res / ss_tot)
    return dict(slope_ann=slope_ann, r2=r2, score=slope_ann * r2)
