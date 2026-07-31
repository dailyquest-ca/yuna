"""The plan's rules as pure functions.

Everything here takes numbers and returns numbers. No database, no vendor calls, no
clock. That is the point: a rule that needs a live Postgres to exercise is a rule
nobody exercises, and the defects this build has actually shipped were all rule
defects wearing green — a microcap topping the bench, a volume baseline silently
reading NaN as "unconfirmed", a foreign issuer priced against the wrong currency.

Each function names the plan clause it comes from. The job modules are plumbing:
they fetch rows, call in here, and write the answer back.
"""
from __future__ import annotations

import math

from yuna.rules import implements

# ---------------------------------------------------------------------------
# §3.3 — composite scores and data confidence
# ---------------------------------------------------------------------------

BUSINESS_COMPONENTS = ("engine", "cash_conv")


@implements("3.3/renormalize-one-missing",
            "drops a missing component and renormalizes the rest to equal weight")
@implements("3.3/data-confidence",
            "refuses to score a name whose business measures are all missing")
def composite(parts: dict[str, float | None]) -> tuple[float | None, str]:
    """Equal-weight composite over the components we actually have.

    Returns (score, confidence) — score is None when the name cannot be scored.

    §3.3 says to drop a missing component and renormalize. Taken literally that
    lets a name score on *size* alone, and size is available to almost everything:
    a $4 ethanol microcap once topped the compounder bench with no measurable
    engine and no measurable cash conversion, because smallness scored 99th
    percentile and nothing else was there to argue. So the floor: two components,
    at least one of them a business measure, or the name is not ranked at all.
    That is §3.3's own "never assume a missing value" applied to the case where
    what is missing is the entire business.
    """
    have = {k: v for k, v in parts.items() if v is not None}
    if len(have) < 2 or not any(k in BUSINESS_COMPONENTS for k in have):
        return None, "unscorable"
    score = sum(have.values()) / len(have)
    return score, ("full" if len(have) == len(parts) else f"{len(have)}of{len(parts)}")


def pct_rank(pairs: list[tuple[str, float | None]]) -> dict[str, float]:
    """[(key, value)] -> {key: percentile 0..100}. None values are skipped entirely.

    A lone observation is 50, not 100 — one name is not the best of anything.
    """
    got = [(k, v) for k, v in pairs if v is not None]
    if not got:
        return {}
    if len(got) == 1:
        return {got[0][0]: 50.0}
    got.sort(key=lambda kv: kv[1])
    n = len(got) - 1
    return {k: 100.0 * i / n for i, (k, _v) in enumerate(got)}


# ---------------------------------------------------------------------------
# §3.1 — compounder underwriting
# ---------------------------------------------------------------------------

ENGINE_TOLERANCE = 0.05
GROWTH_CAP = 0.25


@implements("3.1/engine-reliability",
            "agreement within 5 percentage points of observed 3-yr revenue growth; beyond "
            "that the engine component routes down the data-confidence path")
def engine_agrees(engine: float | None, revenue_cagr: float | None,
                  tolerance: float = ENGINE_TOLERANCE) -> bool | None:
    """Does the ROIC x reinvestment identity show up in revenue?

    §3.1 states the tolerance outright: five percentage points, flat. Not a
    relative band — an engine of 16.3% against observed 7.1% is a 9.2pp gap and
    fails, which is the case that motivated the number. None when the comparison
    cannot be made at all.
    """
    if engine is None or revenue_cagr is None:
        return None
    return abs(engine - revenue_cagr) <= tolerance


def engine_growth(engine: float | None, revenue_cagr: float | None,
                  cap: float = GROWTH_CAP, tolerance: float = ENGINE_TOLERANCE,
                  prior_agrees: bool | None = None) -> tuple[float, bool | None]:
    """The growth number the hurdle uses, and the agreement verdict.

    §3.1 is explicit about what divergence does to the *CCN*: the engine component
    routes down the data-confidence path, so it drops out of the score entirely
    (see `ccn` below). It says nothing about what the *hurdle* should then use for
    "engine growth" — and underwriting at a growth rate the system has just
    declared untrustworthy would contradict "never silently score".

    So this holds an interim, deliberately conservative reading: on divergence the
    growth input is capped at the number we can actually observe. That is not in
    the plan, it is recorded as a deviation in the ledger, and it is raised in
    docs/open-questions.md as Q7. It moves hurdle prices, so it needs a ruling.

    `prior_agrees` is the verdict already recorded on the row. It is consulted only
    when the comparison cannot be recomputed here — a row with no revenue CAGR but
    a stored `False` is still a row the system has judged untrustworthy, and
    silently promoting it back to full engine growth because the input went missing
    is precisely the failure this check exists to prevent.

    No floor at zero on the agreeing branch: a business whose engine is genuinely
    negative is shrinking, and §3.1's expected return should say so. Flooring would
    raise its hurdle price, which flatters exactly the name that deserves it least.
    """
    if engine is None:
        return 0.0, None
    g = min(cap, engine)
    agrees = engine_agrees(engine, revenue_cagr, tolerance)
    if agrees is None:
        agrees = prior_agrees
    if agrees is False:
        # cap at what we can observe; with nothing observable, no growth is claimed
        g = max(0.0, min(g, revenue_cagr if revenue_cagr is not None else 0.0))
    return g, agrees


@implements("3.1/hurdle",
            "solves for the highest price at which FCF yield + growth - derating drag "
            "still clears the 15% floor")
def hurdle_price(fcf_ttm: float | None, shares: float | None, growth: float,
                 fair: float | None, floor: float = 0.15) -> float | None:
    """Hurdle v1.0. None when the inputs cannot support an estimate.

    Expected return falls monotonically in price — a higher price is a lower yield
    and a bigger slide back to the fair multiple — so a bisection is exact enough
    at 80 iterations, and far more legible than solving the quintic.
    """
    if not fcf_ttm or fcf_ttm <= 0 or not shares or shares <= 0 or not fair or fair <= 0:
        return None

    def er(mcap: float) -> float:
        drag = max(0.0, 1.0 - (fair * fcf_ttm / mcap) ** 0.2)   # 5-yr slide, never a credit
        return fcf_ttm / mcap + growth - drag

    lo, hi = fcf_ttm * 0.01, fcf_ttm * 5000.0
    if er(hi) >= floor:
        return hi / shares
    if er(lo) < floor:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if er(mid) >= floor:
            lo = mid
        else:
            hi = mid
    return lo / shares


@implements("3.1/hurdle-within-10pct",
            "'within 10% of the hurdle' is price <= 1.10 x hurdle, everywhere it appears")
def within_hurdle(price: float | None, hurdle: float | None, margin: float = 0.10) -> bool:
    """Zak's reading, 2026-07-31: the band is above the hurdle, not either side of it.

    A name 30% *below* its hurdle is not "within 10%" — it is a screaming buy, and
    the eviction seatbelt has no business treating it as marginal. Same test at
    both call sites, which is why it lives here and not inline twice.
    """
    if price is None or hurdle is None or hurdle <= 0:
        return False
    return price <= hurdle * (1.0 + margin)


SIZE_BOUNDARY_USD = 10_000_000_000
BENCH_TAKE_PER_COHORT = 30


@implements("3.1/bench-cohorts",
            "top 30 by CCN from each size cohort, split at a $10B market cap")
def size_cohort(market_cap: float | None, boundary: float = SIZE_BOUNDARY_USD) -> str:
    """Which half of the bench a name competes in.

    §3.1 builds the bench *half smaller-cap, half larger-cap by mechanism* — the
    split is how a small compounder gets a seat at all, since size is one of three
    CCN components and the large names would otherwise be outranked wholesale. The
    final picks are still pure number: the book may end up all-small or all-large.
    A name with no market cap is treated as small, which is the side where an
    unknown deserves less benefit of the doubt.
    """
    return "large" if (market_cap or 0) >= boundary else "small"


@implements("3.1/compounder-sizing",
            "CCN 70-84 sizes 12% of NAV and 85+ sizes 15%, but flat 12% until Zak unlocks "
            "the upper tier at a monthly approval")
def compounder_size(ccn_score: float, tier_unlocked: bool = False) -> float:
    """Flat 12% is the default and stays the default absent a ruling.

    §3.1 makes the 15% tier conditional on a shadow-book comparison presented at a
    monthly approval, at least two full calendar quarters after cutover — and
    explicitly says that absent a ruling, flat 12% continues. So the unlock is a
    parameter someone has to turn on, never something the code infers from a date.
    """
    if tier_unlocked and ccn_score >= 85.0:
        return 0.15
    return 0.12


@implements("3.1/averaging-down",
            "below hurdle by 5-15% adds 50% of original size; more than 15% below adds 100%")
def averaging_down_add(price: float, hurdle: float) -> float:
    """The add, as a multiple of the original position size. 0.0 means no add.

    Fixed tiers, not ranges — the 2026-07-31 pass replaced "25-50%" and "up to
    100%" with single numbers, because a range in a mechanical rule is a decision
    nobody made. The 5% band immediately below the hurdle adds nothing: at-hurdle
    is an entry price, not a discount.

    Caller still owes the two conditions this cannot see: CCN >= 70, and at most
    two adds per name per twelve months.
    """
    if hurdle <= 0 or price <= 0:
        return 0.0
    below = (hurdle - price) / hurdle
    if below > 0.15:
        return 1.00
    if below >= 0.05:
        return 0.50
    return 0.0


@implements("3.1/c1-excludes-financials",
            "excludes banks and insurers by vendor industry prefix, not by sector")
def is_excluded_financial(industry: str | None) -> bool:
    """Banks and insurers are out of the compounder universe.

    By industry, not sector: the Financial Services *sector* also holds exchanges,
    ratings agencies and payment networks, which are exactly the kind of toll-booth
    compounder this sleeve wants. The point-in-time backtest proved the cost of
    getting this wrong in the other direction — rebuilding C1 from filings alone
    carried no sector at all, and a reinsurer and an asset manager took two of six
    slots, one of them a +110% winner that flattered the whole result.

    §3.1 names the test exactly: vendor industries called `Banks - ...` or
    `Insurance - ...`. Insurance Brokers, Credit Services, Capital Markets and the
    rest of Financial Services stay eligible — EBITDA is meaningless for
    underwriters and deposit-takers, not for fee businesses. A name with no vendor
    industry is not excludable by this test; the gap is named on its C2 memo.
    """
    if not industry:
        return False
    i = industry.strip().lower()
    return i.startswith("banks - ") or i.startswith("insurance - ")


# ---------------------------------------------------------------------------
# §3.2 — momentum stops and sizing
# ---------------------------------------------------------------------------

MAX_STOP = 0.08


@implements("3.2/stop-8pct",
            "initial stop is the higher of the final-contraction low or entry - 8%, "
            "and never wider than 8%")
def initial_stop(entry: float, contraction_low: float | None = None) -> float:
    """Higher of the base's final-contraction low or entry - 8%.

    "Higher" is what makes 8% a ceiling on the risk rather than the stop itself:
    a tight base gives a tighter stop and therefore a bigger position, which is
    the whole point of sizing on risk.
    """
    floor = entry * (1.0 - MAX_STOP)
    if contraction_low is not None and contraction_low > floor:
        return contraction_low
    return floor


@implements("3.2/euphoria-ratchet",
            "a close more than 2 standard deviations above the own 50-day tightens the "
            "trail to 5% below the highest close")
def is_euphoric(closes: list[float]) -> bool:
    """Euphoria tightens the trail; it never sells.

    One trigger, not two. The plan's 2026-07-31 simplification pass removed the
    largest-single-day-gain test on the grounds that the 2 sigma test carries the
    rule without needing per-position running-max state — and that state was real
    complexity: it meant the ratchet could not be recomputed from bars alone.

    The standard deviation is the population form over exactly the last 50 closes,
    matching "std dev of closes, 50-day window". Under 50 bars the test is simply
    unavailable, and a position that young has not had time to get euphoric.
    """
    if len(closes) < 50:
        return False
    w = closes[-50:]
    mean = sum(w) / 50.0
    sd = (sum((x - mean) ** 2 for x in w) / 50.0) ** 0.5
    return sd > 0 and closes[-1] > mean + 2 * sd


@implements("3.2/breakeven-ratchet", "full size moves the stop to breakeven")
@implements("3.2/trail-10", "+15% from average cost trails 10% below the highest close")
def ratchet_stop(closes: list[float], avg_cost: float | None, pyramid_step: int,
                 current_stop: float | None, highest_close: float | None
                 ) -> tuple[float | None, str, float]:
    """The stop after tonight's close, its mode, and the new highest close.

    Precedence is euphoria, then the +15% trail, then breakeven at full size —
    tightest first, because these are protection rules and the tighter one is
    always the one that binds. The result is clamped upward against the existing
    stop: §3.2 says stops ratchet up, never down, and that clamp is the only
    reason a trail can be safely recomputed from scratch every night.

    `avg_cost` is nullable because `book.avg_cost` is: the seed migrations left
    rows without a cost basis. A full-size position with no cost basis cannot move
    to breakeven, so rather than crash on the arithmetic or silently skip, it comes
    back labeled `no-cost-basis` — the caller ambers on it, because a momentum
    position at step 3 with no cost is a data defect that should be visible rather
    than either fatal or invisible.

    Mode `initial` means the fall-through fired: no rule applied tonight. The
    caller keeps whatever mode the row already carried, since this reports the
    branch, not the row.
    """
    if not closes:
        return current_stop, "initial", (highest_close or 0.0)
    px = closes[-1]
    new_high = max(closes) if highest_close is None else max(highest_close, max(closes))

    if is_euphoric(closes):
        cand, mode = new_high * 0.95, "trail5"
    elif avg_cost and px / avg_cost - 1 >= 0.15:
        cand, mode = new_high * 0.90, "trail10"
    elif pyramid_step >= 3:
        if avg_cost is None:
            return current_stop, "no-cost-basis", new_high
        cand, mode = avg_cost, "breakeven"
    else:
        return current_stop, "initial", new_high

    if current_stop is not None and current_stop >= cand:
        return current_stop, mode, new_high        # ratchets up, never down
    return cand, mode, new_high


@implements("3.2/momentum-sizing",
            "size = risk budget / stop distance, capped by the sleeve band")
@implements("2.3/risk-not-dollars",
            "sizes on risk — position size x distance to stop — rather than on dollars")
def momentum_size(entry: float, stop: float, mcn: float, budgets: dict[str, float],
                  band_cap: float = 0.12) -> tuple[float, float, float]:
    """(position weight, stop distance, risk budget) for a momentum entry.

    Conviction sets what we are willing to lose; the stop sets how far away that
    loss is; the position is the quotient. A stop wider than 8% is not sized down,
    it is *moved* to 8% — §3.2 makes 8% a hard ceiling on the width, so a wider
    base low is simply not honoured.
    """
    budget = float(budgets["85" if mcn >= 85.0 else "70"])
    dist = max((entry - stop) / entry, 1e-4)
    if dist > MAX_STOP:
        dist = MAX_STOP
    return min(budget / dist, band_cap), dist, budget


# ---------------------------------------------------------------------------
# §2 — portfolio architecture
# ---------------------------------------------------------------------------

SLEEVES = {
    "compounders": {"weight": 0.60, "min_names": 4, "max_names": 5,
                    "entry_low": 0.12, "entry_high": 0.15},
    "momentum": {"weight": 0.40, "min_names": 3, "max_names": 4,
                 "entry_low": 0.08, "entry_high": 0.12},
}
POSITION_FLOOR = 0.04
SINGLE_NAME_CAP = 0.25
MAX_NAMES_PER_GROUP = 2
THEME_ENTRY_CAP = 0.35


@implements("2.1/sleeve-counts", "sleeve name counts and the weight each sleeve may occupy")
def sleeve_has_room(sleeve: str, held: int, used_weight: float, new_weight: float) -> bool:
    """Whether one more name fits, on both the count and the weight.

    The momentum 40% is a ceiling and not a quota — three names at 10% is a
    complete sleeve — so this only ever refuses; it never demands another name.
    """
    s = SLEEVES[sleeve]
    return held < int(s["max_names"]) and used_weight + new_weight <= float(s["weight"]) + 1e-9


@implements("2.2/max-2-per-group", "at most two names per vendor industry group")
def group_has_room(industry: str | None, counts: dict[str, int]) -> bool:
    return counts.get(industry or "unknown", 0) < MAX_NAMES_PER_GROUP


@implements("2.3/position-floor", "minimum position 4% of NAV, on intended full size")
@implements("2.3/single-name-cap", "single-name ceiling 25% of NAV, entry only")
def size_is_admissible(weight: float) -> tuple[bool, str | None]:
    """Both §2.3 bounds are entry-only: a winner that outgrows 25% is not trimmed.

    So this is asked about an *intended* size, never about a position we hold.
    """
    if weight < POSITION_FLOOR:
        return False, f"below the {POSITION_FLOOR:.0%} position floor"
    if weight > SINGLE_NAME_CAP:
        return False, f"above the {SINGLE_NAME_CAP:.0%} single-name ceiling"
    return True, None


@implements("2.2/effective-bets", "effective independent bets = 1 / sum(wi wj rho_ij)")
def effective_bets(weights: dict[str, float], rho: dict[tuple[str, str], float]) -> float | None:
    """The concentration number R1 prints on every draft ticket.

    Weights are normalized across the whole book, levered included (§2.0) —
    correlation doesn't care whose money paid. A missing pair is read as perfectly
    correlated, which is the conservative direction: unknown correlation should
    make the book look more concentrated, never less. Worked check from the plan:
    four equal names at 0.85 correlation returns 1.1.
    """
    names = [n for n, w in weights.items() if w]
    if not names:
        return None
    total = sum(weights[n] for n in names)
    if total <= 0:
        return None
    w = {n: weights[n] / total for n in names}
    denom = 0.0
    for a in names:
        for b in names:
            if a == b:
                r = 1.0
            else:
                r = rho.get((a, b), rho.get((b, a), 1.0))
            denom += w[a] * w[b] * r
    if denom <= 0:
        return None
    return 1.0 / denom


# ---------------------------------------------------------------------------
# §2.0 — NAV
# ---------------------------------------------------------------------------

@implements("2.0/cash-per-currency",
            "an investing account's cash is held per currency and converted at the daily rate")
def account_cash_cad(cash_cad: float | None, cash_usd: float | None, fx: float,
                     legacy_cash: float | None = None) -> tuple[float, float, float]:
    """(total CAD, native CAD, native USD) for one investing account.

    Zak holds both currencies inside a single Wealthsimple account, so a single
    "cash" number cannot be repriced — the USD sleeve moves with FX every day and
    the CAD sleeve does not. The legacy single-column value is read as CAD so
    older rows stay meaningful.
    """
    if cash_cad is not None or cash_usd is not None:
        c_cad, c_usd = float(cash_cad or 0.0), float(cash_usd or 0.0)
    else:
        c_cad, c_usd = float(legacy_cash or 0.0), 0.0
    return c_cad + c_usd * fx, c_cad, c_usd


# ---------------------------------------------------------------------------
# §5.6 — performance
# ---------------------------------------------------------------------------

@implements("5.6/performance-twr",
            "the 30% bar is time-weighted, so deposits neither flatter nor penalize it")
def time_weighted_return(navs: list[float], flows: list[float]) -> float | None:
    """Chain-linked return over a series of NAV observations.

    `navs[i]` is NAV at observation i; `flows[i]` is external money added between
    i-1 and i (negative for a withdrawal). Each sub-period earns
    NAV_i / (NAV_{i-1} + flow_i) - 1, so a $5,000 deposit raises NAV by $5,000 and
    the return by nothing — which is the entire reason Zak ruled TWR: the 30% bar
    has to measure the machine, not his paycheque.

    The flow is treated as arriving at the *start* of the sub-period. Wealthsimple
    gives us no intra-period timing, and start-of-period is the conservative
    assumption: it credits the deposit with a full period of the return it did not
    necessarily earn, so the reported number understates rather than flatters.
    """
    if len(navs) < 2:
        return None
    if len(flows) != len(navs):
        raise ValueError("flows must align with navs, one entry per observation")
    growth = 1.0
    for i in range(1, len(navs)):
        base = navs[i - 1] + flows[i]
        if base <= 0:
            return None          # a fully-withdrawn period has no meaningful return
        growth *= navs[i] / base
    return growth - 1.0


# ---------------------------------------------------------------------------
# §3.3 — blackout
# ---------------------------------------------------------------------------

BLACKOUT_SESSIONS = 5


@implements("3.3/blackout",
            "no new entries and no adds within 5 trading days of a scheduled report")
@implements("3.3/blackout-trading-days",
            "the window is counted in trading days from the session calendar, not calendar days")
def in_blackout(sessions_until_report: int | None) -> bool:
    """Trading days, counted once, here.

    The window used to be approximated as `calendar_days * 1.6` in one place and
    counted exactly in another, which meant two parts of the same nightly could
    disagree about whether a name was enterable. The caller resolves the report
    date against the actual session calendar and passes the count; a report that
    has already happened passes a negative and is not in blackout — §3.3 lifts the
    window the first session after the report session.
    """
    if sessions_until_report is None:
        return False
    return 0 <= sessions_until_report <= BLACKOUT_SESSIONS


@implements("3.3/blackout-beats-pyramid",
            "a breakout confirming inside a blackout arms no adds")
def pyramid_may_arm(confirmed: bool, sessions_until_report: int | None) -> bool:
    """Zak's reading, 2026-07-31: "no adds" is unconditional inside the window.

    Confirmation and blackout are independent questions and the blackout wins.
    A name can confirm on volume, unlock its pyramid in principle, and still arm
    nothing — the adds wait for the window to lift.
    """
    return confirmed and not in_blackout(sessions_until_report)


@implements("3.3/earnings-cushion",
            "a momentum position holds through a print only at last close >= 1.08 x average cost")
def holds_through_earnings(last_close: float, avg_cost: float) -> bool:
    """One full stop-width of profit is what absorbs the gap.

    Below the cushion, §3.3 wants an exit ticket that evening — the position is
    risking a full stop on a coin flip it was never underwritten for.
    """
    if avg_cost <= 0:
        return False
    return last_close >= 1.08 * avg_cost


# ---------------------------------------------------------------------------
# §3.2 — base detection
# ---------------------------------------------------------------------------

BASE_LOOKBACK = 120
BASE_MIN_AGE = 25
BASE_MAX_DEPTH = 0.25
PIVOT_GRACE = 0.005
CONTRACTION_WINDOW = 10


@implements("3.2/base-detection",
            "pivot = highest high 120 to 25 sessions back; valid when unbroken and <=25% deep")
@implements("3.2/pivot-grace",
            "a later high beyond pivot x 1.005 spends the pivot; highs inside the grace are noise")
def scan_base(highs: list[float], lows: list[float], closes: list[float]) -> dict[str, object]:
    """One deterministic scan. Newest bar last.

    Every detected base is at least 25 sessions old *by construction* — the window
    ends 25 sessions back, so a pivot cannot be younger than that and there is no
    age test to apply afterwards. The 2026-07-31 simplification pass removed the
    forming state and the age partition on exactly this ground: validity was being
    checked twice, once by the window and once by an invented threshold.

    Two ways to break a base, and they answer different questions:

      * a later session **closing** above the pivot — the breakout happened, so
        this base is spent and the next one has to form;
      * a later session's **high** beyond pivot x 1.005 without such a close — the
        pivot was tested and rejected. Spent either way.

    Highs inside the 0.5% band are noise and break nothing, which is what lets a
    sub-noise shakeout exit through the hair-trigger while the base itself
    survives — the classic same-pivot re-entry. Anything beyond the band spends
    the pivot and forces a new base, which is what stops the exit-and-instantly-
    re-arm churn loop.

    Returns state in {'none','valid','broken'} with the pivot, depth and
    final-contraction low that §5.1's entry mechanic needs. 'none' means no pivot
    could be established at all, or the base is unbroken but deeper than 25%.
    """
    n = len(closes)
    out: dict[str, object] = {"state": "none", "pivot": None, "age": None,
                              "depth": None, "contraction_low": None, "why": None}
    if n < BASE_MIN_AGE + 1 or len(highs) != n or len(lows) != n:
        out["why"] = "not enough history"
        return out

    window_end = n - BASE_MIN_AGE                # exclusive: the last 25 sessions can hold no pivot
    window_start = max(0, n - BASE_LOOKBACK)
    if window_end <= window_start:
        out["why"] = "no pivot window"
        return out

    idx = max(range(window_start, window_end), key=lambda i: highs[i])
    pivot = highs[idx]
    out["pivot"], out["age"] = pivot, n - 1 - idx

    later = slice(idx + 1, n)
    if any(c > pivot for c in closes[later]):
        out["state"] = "broken"
        out["why"] = "a later close cleared the pivot — the breakout already happened"
        return out
    if any(h > pivot * (1.0 + PIVOT_GRACE) for h in highs[later]):
        out["state"] = "broken"
        out["why"] = "a later high pierced the pivot beyond the 0.5% grace — pivot spent"
        return out

    trough = min(lows[idx:])
    depth = (pivot - trough) / pivot if pivot > 0 else None
    out["depth"] = depth
    out["contraction_low"] = (min(lows[-CONTRACTION_WINDOW:]) if n >= CONTRACTION_WINDOW
                              else min(lows))

    if depth is not None and depth <= BASE_MAX_DEPTH:
        out["state"] = "valid"
    else:
        out["why"] = "deeper than 25%"
    return out


PYRAMID_CEILING = 0.05


@implements("3.2/pyramid", "adds at pivot +2% and +4%, sized 25% each")
@implements("3.2/pyramid-ceiling",
            "both limits sit at pivot x 1.05, so a skipped band completes at the open and a "
            "gap beyond +5% fills nothing")
def pyramid_orders(pivot: float) -> list[dict[str, float]]:
    """The two add stop-limits that ship once a breakout confirms.

    Both limits sit at the ceiling rather than tracking their own trigger, and
    that is the whole mechanism: a gap that skips the +2% band completes at the
    open by itself, and a gap beyond +5% fills nothing at all. The schedule
    enforces itself at the broker, with nobody watching the open — which is what
    let the plan delete the gap-up market order entirely.

    The accepted residue, named in §3.2: a larger gap that fades back to +5%
    intraday fills at the ceiling. That is a price sanctioned in advance, on a
    name 5% above a confirmed breakout.
    """
    limit = round(pivot * (1.0 + PYRAMID_CEILING), 2)
    return [{"step": 2, "trigger": round(pivot * 1.02, 2), "limit": limit, "add": 0.25},
            {"step": 3, "trigger": round(pivot * 1.04, 2), "limit": limit, "add": 0.25}]


VOLUME_CONFIRMATION = 1.4
LATE_CONFIRMATION_SESSIONS = 3


@implements("3.2/breakout-confirmation",
            "volume >= 1.4x the trailing 50-day confirms; unconfirmed freezes the pyramid at "
            "50% with three sessions to confirm late, and exits only on a close below the pivot")
def classify_breakout(volumes: list[float], baselines: list[float | None]) -> dict[str, object]:
    """Confirmation state over the first sessions of a breakout, breakout day first.

    Each session is measured against *its own* trailing 50-day average, which is
    what makes late confirmation meaningful rather than a rerun of the same test.

    An unknown baseline is not a failed test. The simulation once read a NaN
    baseline as "not confirmed" and reported 2% confirmation where the raw bars
    said 29.2% — a missing denominator has to be carried as unknown, and the
    caller decides, rather than silently scoring against the position.
    """
    ratios: list[float | None] = []
    for v, b in zip(volumes[:LATE_CONFIRMATION_SESSIONS], baselines[:LATE_CONFIRMATION_SESSIONS]):
        ratios.append(v / b if b else None)
    known = [r for r in ratios if r is not None]
    confirmed = any(r >= VOLUME_CONFIRMATION for r in known)
    return {
        "confirmed": confirmed,
        "on_breakout_day": bool(ratios and ratios[0] is not None
                                and ratios[0] >= VOLUME_CONFIRMATION),
        "late": confirmed and not (ratios and ratios[0] is not None
                                   and ratios[0] >= VOLUME_CONFIRMATION),
        "unknown_baseline": len(known) < len(ratios),
        "ratios": ratios,
        "pyramid_ceiling": 1.0 if confirmed else 0.5,
    }


@implements("3.2/failed-breakout",
            "while unconfirmed, a close back below the pivot exits next morning")
def failed_breakout(confirmed: bool, last_close: float, pivot: float) -> bool:
    """The one hair-trigger that applies while a breakout is unconfirmed.

    Not a volume exit — volume decides how much money rides, price decides whether
    you stay. A confirmed name falls back to ordinary stops and this never fires.
    """
    return (not confirmed) and last_close < pivot


# ---------------------------------------------------------------------------
# §3.0 — percentile helpers shared by both pipelines
# ---------------------------------------------------------------------------

@implements("3.1/ccn-score", "CCN v1.0 — engine, cash conversion, inverted log size, equal weight")
def ccn(engine_pct: float | None, cash_conv_pct: float | None,
        size_pct: float | None) -> tuple[float | None, str]:
    return composite({"engine": engine_pct, "cash_conv": cash_conv_pct, "size": size_pct})


def inverted_log_size(market_cap: float | None) -> float | None:
    """The size component's raw input: smaller is better, on a log scale.

    Percentiled afterwards, so only the ordering matters — but the log is what
    keeps a $200M name and a $2B name meaningfully apart while $200B and $2T are
    both simply "huge".
    """
    if not market_cap or market_cap <= 0:
        return None
    return -math.log(market_cap)
