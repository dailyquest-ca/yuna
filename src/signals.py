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
    """M1 v1.0 — Weinstein stage on weekly closes, latched (§3.2).

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


def trend_template(close):
    """M2 — Minervini's six conditions, at the current price (§3.2)."""
    c = np.asarray(close, dtype=float)
    if len(c) < 252:
        return False
    s50, s150, s200 = (float(np.mean(c[-n:])) for n in (50, 150, 200))
    s200_21 = float(np.mean(c[-221:-21]))
    lo52, hi52, px = float(np.min(c[-252:])), float(np.max(c[-252:])), float(c[-1])
    return bool(px > s150 and px > s200 and s150 > s200 and s200 > s200_21 and px > s50
                and px >= lo52 * 1.30 and px >= hi52 * 0.75)


# ---------------------------------------------------------------------------- M3 base detection


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


def momentum_quality(adj_close, *, window=90):
    """Annualised slope of the log-price regression x R^2, divided by volatility (§3.2)."""
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
    vol = float(np.std(np.diff(np.log(a[-(window + 1):])))) or 1e-9
    return slope * 252.0 * r2 / vol


def atr(high, low, close, *, window=14):
    """Wilder's true range, simple-averaged over `window` — the ATR(14) §3.2 asks for."""
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    if len(c) < window + 1:
        return np.array([])
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return np.convolve(tr, np.ones(window) / window, mode="valid")


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
    """MCN v1.0 — three equal-weighted percentiles (§3.2)."""
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


def pyramid_orders(pivot, *, ceiling=1.05):
    """Steps 2 and 3 as resting add stop-limits: triggers +2% / +4%, both limits pivot x 1.05.

    A gap that skips a band completes at the open automatically; a gap beyond the ceiling fills
    nothing. The ceiling enforces itself at the broker, unwatched (§3.2, X2).
    """
    return [dict(step=2, fraction=0.25, trigger=pivot * 1.02, limit=pivot * ceiling),
            dict(step=3, fraction=0.25, trigger=pivot * 1.04, limit=pivot * ceiling)]


def entry_order(pivot, contraction_low, *, limit_over=0.02, max_stop=0.08):
    """The §5.1 entry pair: buy stop-limit at the pivot, and the stop that rides under it."""
    stop = initial_stop(pivot, contraction_low, max_stop=max_stop)
    return dict(trigger=pivot, limit=pivot * (1 + limit_over), stop=stop,
                fraction=0.5, stop_distance=(pivot - stop) / pivot)


def initial_stop(entry, contraction_low, *, max_stop=0.08):
    """Higher of the base's final-contraction low or entry - 8%. Never wider than 8% (§3.2)."""
    floor = entry * (1 - max_stop)
    if contraction_low is None or not np.isfinite(contraction_low):
        return floor
    return max(float(contraction_low), floor)


def ratchet_stop(*, closes, avg_cost, current_stop, highest_close=None, pyramid_step=0,
                 full_step=3, trail10_from=0.15, trail10=0.10, euphoria_trail=0.05,
                 euphoria_sd=2.0, sd_window=50):
    """The stop ladder (§3.2 Stops) — ratchets up, never down.

    Full size moves the stop to breakeven; +15% from average cost starts a 10% trail below the
    highest close since entry; a close more than 2 standard deviations above its own 50-day
    tightens that trail to 5%. The euphoria rule tightens, it never sells, and it has exactly
    one trigger — the second one was deleted from the plan in the S1-S5 round.
    """
    c = np.asarray(closes, dtype=float)
    if not len(c):
        return dict(stop=current_stop, mode=None, highest_close=highest_close, euphoric=False)
    px = float(c[-1])
    hc = float(np.max(c)) if highest_close is None else max(float(highest_close), float(np.max(c)))

    euphoric = False
    if len(c) >= sd_window:
        w = c[-sd_window:]
        sd = float(np.std(w))
        euphoric = sd > 0 and px > float(np.mean(w)) + euphoria_sd * sd

    if euphoric:
        candidate, mode = hc * (1 - euphoria_trail), "trail5"
    elif avg_cost and px / float(avg_cost) - 1 >= trail10_from:
        candidate, mode = hc * (1 - trail10), "trail10"
    elif pyramid_step >= full_step and avg_cost:
        candidate, mode = float(avg_cost), "breakeven"
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
    pct = budget / stop_distance
    pct = min(pct, band[1])
    if not start_low:
        pct = max(pct, band[0]) if pct >= floor_nav else pct
    return dict(size_pct=pct, budget=budget, cad=pct * nav if nav else None,
                below_floor=pct < floor_nav)


# ---------------------------------------------------------------------------- compounders


def ccn(components, *, min_components=2, business=("engine", "cash_conv")):
    """CCN v1.0 — equal weight over available components, renormalized (§3.1, §3.3).

    §3.3 renormalizes around *one* missing component. Size is available to almost everything, so
    a floor is needed or a company whose engine and cash conversion are both unmeasurable scores
    on smallness alone — that is how a $4 microcap once topped the bench. Builder's rule, on the
    ratification list (roadmap Part 4).
    """
    have = {k: v for k, v in components.items() if v is not None and not np.isnan(v)}
    if len(have) < min_components or not any(k in have for k in business):
        return dict(score=None, confidence="unscorable", used=sorted(have))
    score = float(sum(have.values()) / len(have))
    confidence = "full" if len(have) == len(components) else f"{len(have)}of{len(components)}"
    return dict(score=score, confidence=confidence, used=sorted(have))


def engine_agrees(engine, revenue_cagr, *, tolerance=0.05):
    """§3.1 reliability check: growth = ROIC x reinvestment is an identity, so it must agree with
    observed 3-year revenue growth within 5 percentage points. Beyond that the engine component
    routes down the data-confidence path — it is dropped, not quietly capped."""
    if engine is None or revenue_cagr is None:
        return None
    return abs(float(engine) - float(revenue_cagr)) <= tolerance


def effective_shares(market_cap, last_close):
    """§3.1: cap at price P uses effective shares = the vendor's USD market cap / last close.

    This is what resolves ADR ratios, listing currency and share classes in one step; the
    vendor's own share count does not."""
    if not market_cap or not last_close or market_cap <= 0 or last_close <= 0:
        return None
    return market_cap / last_close


def expected_return(price, *, fcf_ttm, shares, growth, fair_multiple, years=5):
    """FCF yield + engine growth - derating drag, at price P (§3.1 Hurdle v1.0)."""
    cap = price * shares
    if cap <= 0 or not fcf_ttm or fcf_ttm <= 0 or not fair_multiple or fair_multiple <= 0:
        return None
    drag = max(0.0, 1.0 - (fair_multiple * fcf_ttm / cap) ** (1.0 / years))   # never a credit
    return fcf_ttm / cap + growth - drag


def hurdle_price(*, fcf_ttm, shares, growth, fair_multiple, floor=0.15, years=5):
    """The highest price at which expected return still clears the floor (§3.1).

    Monotone in price, so a bisection is exact to the cent. Returns None when the name cannot
    clear the floor at any price, which is the common case and not an error.
    """
    if not fcf_ttm or fcf_ttm <= 0 or not shares or shares <= 0 \
       or not fair_multiple or fair_multiple <= 0:
        return None

    def er(px):
        return expected_return(px, fcf_ttm=fcf_ttm, shares=shares, growth=growth,
                               fair_multiple=fair_multiple, years=years)

    lo, hi = 0.01, max(1e4, fcf_ttm / shares * 5000.0)
    if (er(lo) or -1) < floor:
        return None
    if (er(hi) or -1) >= floor:
        return hi
    for _ in range(200):
        mid = (lo + hi) / 2
        if (er(mid) or -1) >= floor:
            lo = mid
        else:
            hi = mid
    return lo


def compounder_add(*, ccn_score, price, hurdle, adds_this_year, enter=70.0, max_adds=2):
    """Averaging down (§3.1): 5-15% below the hurdle adds 50% of original size, more than 15%
    below adds 100%. Two adds per name per 12 months; crash-protocol tactical adds are exempt
    and are not counted by this function."""
    if ccn_score is None or ccn_score < enter or not hurdle or hurdle <= 0:
        return None
    below = (hurdle - price) / hurdle
    if below < 0.05:
        return None
    if adds_this_year >= max_adds:
        return dict(fraction=None, blocked="§3.1 — two adds already this year", below=below)
    return dict(fraction=0.5 if below <= 0.15 else 1.0, blocked=None, below=below)


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
