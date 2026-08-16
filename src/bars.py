"""§2.5 statistical bars — the formal definition of "finding" (E-series v2.0).

A number is a *result*. It becomes a *finding* only after clearing all of §2.5, and the point of
this module is that the bar is applied mechanically rather than argued. Four of the five clauses
live here; (e) costs is an engine concern and already lands in `backtest.py`'s spread curve.

Deliberately pure — every function takes arrays and returns numbers, with no database and no clock,
so the bars can be unit-tested against hand-built inputs the way `signals.py` is. The driver that
reads a run and writes a verdict lives elsewhere.

**No new dependencies.** `requirements.txt` pins are load-bearing here (the worst backtest bug in
this repo came from a pandas default moving), so the normal CDF and its inverse are implemented
below rather than imported from scipy.
"""
import math

import numpy as np

# Blocks of ~63 sessions ≈ one quarter, per §2.5(c). Momentum returns are autocorrelated in runs —
# a trend either persists for weeks or it does not — so an iid bootstrap would resample away the
# very serial structure the strategy exists to harvest and report far tighter intervals than the
# data supports.
BLOCK_SESSIONS = 63
DRAWS = 10_000
SESSIONS_PER_YEAR = 252.0

# §2.5(d): "using the logged configuration count for the whole programme (>= 50 trials; log the
# exact number)". Zak ruled 2026-08-12 that the count runs FORWARD ONLY — the 53 runs predating the
# E-series are not counted. The floor keeps the deflation honest anyway: an E-series of ~15-20
# configurations would otherwise deflate against a smaller multiple-testing burden than the
# selection actually carried, since E0's arms were themselves chosen out of that earlier history.
MIN_TRIALS = 50

EULER_GAMMA = 0.5772156649015329


# --------------------------------------------------------------------------- normal distribution
def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p):
    """Inverse normal CDF, Acklam's rational approximation (|error| < 1.15e-9).

    Written out rather than imported so this module adds no dependency. The refinement step at the
    end is what buys the last few digits; without it the approximation is ~1e-4 in the tails, and
    the tails are exactly where a deflated Sharpe lives.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"norm_ppf needs 0 < p < 1, got {p}")
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        x = (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
            ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    elif p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
             ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    else:
        q, r = p - 0.5, (p - 0.5) ** 2
        x = (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5])*q / \
            (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)
    e = norm_cdf(x) - p                                   # one Halley refinement
    u = e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


# ------------------------------------------------------------------------------- path statistics
def cagr(nav_first, nav_last, sessions):
    if nav_first <= 0 or sessions <= 0:
        raise ValueError("cagr needs positive starting NAV and at least one session")
    years = sessions / SESSIONS_PER_YEAR
    return (nav_last / nav_first) ** (1.0 / years) - 1.0


def max_drawdown(nav):
    """Peak-to-trough on the NAV path, as a negative fraction."""
    nav = np.asarray(nav, dtype=float)
    if nav.size == 0:
        raise ValueError("max_drawdown needs a path")
    peak = np.maximum.accumulate(nav)
    return float(np.min(nav / peak) - 1.0)


def daily_returns(nav):
    nav = np.asarray(nav, dtype=float)
    if nav.size < 2:
        raise ValueError("daily_returns needs at least two marks")
    if np.any(nav[:-1] <= 0):
        raise ValueError("daily_returns cannot price a non-positive NAV")
    return nav[1:] / nav[:-1] - 1.0


# ------------------------------------------------------------------- §2.5(b) winner exclusion
def jackknife_arithmetic(trade_pnls, start_nav, k_values=(1, 3, 5)):
    """Total return with the top-k winners removed, as a simple arithmetic exclusion.

    **This is an approximation and is named so.** It subtracts the excluded trades' P&L from the
    account and ignores what the freed capital would have done — the compounding of every later
    position is left untouched. A true exclusion requires re-running the simulation without the
    name, which is exactly E1's design for MU.

    The approximation errs in a knowable direction: it removes the winner's contribution but keeps
    the compounding that winner financed, so it FLATTERS the ex-top-k figure. A claim that fails
    this test would fail the honest version by more.
    """
    pnls = np.sort(np.asarray(list(trade_pnls), dtype=float))[::-1]
    total = float(pnls.sum())
    out = {"all": total / start_nav}
    for k in k_values:
        out[f"ex_top_{k}"] = float(total - pnls[:k].sum()) / start_nav
    return out


# ------------------------------------------------------------------- §2.5(c) block bootstrap
def block_bootstrap(returns, *, draws=DRAWS, block=BLOCK_SESSIONS, seed=0):
    """Circular block bootstrap over daily strategy returns.

    Returns the 5th/50th/95th percentile of CAGR and of max drawdown across `draws` resampled
    paths. Circular so that every observation has equal probability of being drawn — a plain block
    bootstrap under-samples the ends of the series, and in a nine-year window the ends are 2017 and
    2026, two periods that look nothing like each other.

    `seed` is explicit and required to default: a bootstrap that cannot be reproduced is an opinion.
    """
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < block:
        raise ValueError(f"need at least {block} returns for a {block}-session block, got {n}")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))

    starts = rng.integers(0, n, size=(draws, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n     # circular
    paths = r[idx.reshape(draws, -1)[:, :n]]

    growth = np.cumprod(1.0 + paths, axis=1)
    years = n / SESSIONS_PER_YEAR
    cagrs = growth[:, -1] ** (1.0 / years) - 1.0
    peaks = np.maximum.accumulate(growth, axis=1)
    dds = np.min(growth / peaks, axis=1) - 1.0

    pct = lambda a: {"p5": float(np.percentile(a, 5)),
                     "p50": float(np.percentile(a, 50)),
                     "p95": float(np.percentile(a, 95))}
    return {"cagr": pct(cagrs), "max_drawdown": pct(dds), "draws": draws, "block": block,
            "seed": seed}


# --------------------------------------------------------------- §2.5(d) deflated Sharpe ratio
def sharpe(returns, periods_per_year=SESSIONS_PER_YEAR):
    r = np.asarray(returns, dtype=float)
    sd = r.std(ddof=1)
    if sd == 0:
        raise ValueError("a return series with no variance has no Sharpe ratio")
    return float(r.mean() / sd * math.sqrt(periods_per_year))


def expected_max_sharpe(trial_sharpe_sd, n_trials):
    """The Sharpe you expect from the LUCKIEST of `n_trials` strategies that all have zero edge.

    This is the whole point of deflation: run enough configurations and one of them looks good by
    construction. Bailey & Lopez de Prado's expression for the expected maximum of n draws.
    """
    n = max(int(n_trials), MIN_TRIALS)
    if trial_sharpe_sd <= 0:
        raise ValueError("expected_max_sharpe needs the spread of Sharpes ACROSS trials; with a "
                         "single trial there is no multiple-testing burden to deflate against")
    return trial_sharpe_sd * ((1 - EULER_GAMMA) * norm_ppf(1 - 1.0 / n)
                              + EULER_GAMMA * norm_ppf(1 - 1.0 / (n * math.e)))


def deflated_sharpe(observed_sharpe, *, n_obs, skew, kurtosis, trial_sharpe_sd, n_trials):
    """Probability the observed Sharpe exceeds what selection alone would produce.

    `kurtosis` is NON-EXCESS (a normal distribution is 3.0). The skew and kurtosis terms matter
    enormously here and are not decoration: this family's returns are violently right-skewed and
    fat-tailed — 71% of A1's profit was one trade — and the classical Sharpe standard error assumes
    neither. Ignoring them would overstate significance precisely where this programme is weakest.

    Returns the DSR as a probability. The work order's aspiration is t ~ 3, i.e. DSR ~ 0.9987.
    """
    sr0 = expected_max_sharpe(trial_sharpe_sd, n_trials)
    denom = 1.0 - skew * observed_sharpe + (kurtosis - 1.0) / 4.0 * observed_sharpe ** 2
    if denom <= 0:
        raise ValueError(f"degenerate DSR denominator ({denom:.4f}) — the skew/kurtosis pair and "
                         f"the Sharpe are jointly implausible; check the inputs rather than the "
                         f"formula")
    z = (observed_sharpe - sr0) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return {"dsr": norm_cdf(z), "z": z, "sr0": sr0, "observed_sharpe": observed_sharpe,
            "n_trials_used": max(int(n_trials), MIN_TRIALS), "n_trials_logged": int(n_trials)}


def moments(returns):
    """Sample skew and NON-excess kurtosis of a return series."""
    r = np.asarray(returns, dtype=float)
    m = r.mean()
    sd = r.std(ddof=0)
    if sd == 0:
        raise ValueError("a return series with no variance has no shape")
    return {"skew": float(((r - m) ** 3).mean() / sd ** 3),
            "kurtosis": float(((r - m) ** 4).mean() / sd ** 4)}


# ------------------------------------------------------------------------------------ the verdict
def verdict(*, ex_top_3_beats_benchmark, bootstrap_median_cagr, benchmark_cagr, dsr,
            dd_bar=None, bootstrap_median_drawdown=None, bootstrap_p5_drawdown=None):
    """proven / unproven / dead, per §2.5 and E0's interpretation note.

    An arm whose bootstrap-median falls below the benchmark, or whose edge vanishes ex-top-3, is
    UNPROVEN — barred from scaling, explicitly *not* necessarily dead. Only a broken drawdown bar
    kills outright, because that is a risk statement rather than an evidence one.

    **The drawdown bar reads the bootstrap MEDIAN, not the 5th percentile.** The first cut used
    the p5 and it killed everything, including things that are demonstrably safer than the index:
    measured on this tape, VOO's own bootstrap p5 drawdown is **-45.7%** and the 80/20 blend's is
    -45.0%, so a -34% bar applied there is unpassable by any long-equity strategy — it fails the
    benchmark by twelve points. E3's -34% is plainly VOO's realized -33.99% rounded, which is a
    median-scale number: VOO's bootstrap p50 drawdown is -33.99% to the basis point. The p5 is
    still computed and reported, because the tail is a real question — it is simply not a
    question this bar was written to ask, and comparing it to a median-scale threshold was an
    error of statistic rather than of judgment.
    """
    reasons = []
    if dd_bar is not None and bootstrap_median_drawdown is not None \
            and bootstrap_median_drawdown < dd_bar:
        return {"verdict": "dead",
                "reasons": [f"bootstrap median drawdown {bootstrap_median_drawdown:.1%} "
                            f"breaches the {dd_bar:.0%} bar"
                            + (f" (5th percentile {bootstrap_p5_drawdown:.1%}, reported for the "
                               f"tail, not tested against a median-scale bar)"
                               if bootstrap_p5_drawdown is not None else "")]}
    if not ex_top_3_beats_benchmark:
        reasons.append("edge does not survive removing the top 3 winners")
    if bootstrap_median_cagr <= benchmark_cagr:
        reasons.append(f"bootstrap-median CAGR {bootstrap_median_cagr:.2%} does not exceed the "
                       f"benchmark's {benchmark_cagr:.2%}")
    if dsr < 0.95:
        reasons.append(f"deflated Sharpe {dsr:.3f} below 0.95")
    return {"verdict": "proven" if not reasons else "unproven", "reasons": reasons}


# ---- one company under two symbols -------------------------------------------------------------
#
# `verify_run.py` B7 asks this question in SQL, over the names a stored run traded. The engine has
# to ask the same question in numpy, before it buys, and two spellings of one rule is exactly the
# shape this repo keeps paying for — so the RULE lives here and both sides call it.
#
# The thresholds are `verify_run.py` B7's, unchanged: duplicates score 0.85-1.00 there and
# genuinely different securities 0.006-0.033, so 0.85 sits inside a gap with nothing in it.
#
# **The plan states no number.** §3.7(3) says "hold at most one of a pair; prefer the higher-ADDV
# line" and stops. These constants are the auditor's, adopted because the auditor is already the
# rule of record for what counts as a pair — not because they were chosen here. That is a plan gap
# and is recorded as one; it is not filled with a fresh invention.
TWIN_TOL = 1e-4          # a daily return, in cents-quoted vendor copies, differs in the 5th decimal
TWIN_MIN_OVERLAP = 30    # fewer shared sessions than this and agreement is not evidence
TWIN_AGREE = 0.85


def same_security(ret_a, ret_b, *, tol=TWIN_TOL, min_overlap=TWIN_MIN_OVERLAP, agree=TWIN_AGREE):
    """Do these two daily-return series belong to one company under two symbols?

    Daily RETURNS rather than closes, and a tolerance rather than equality — both are scars.
    Migration 047 compared closes with exact float equality at a 99% bar and missed BBBY_old/BBBY,
    which agrees on 98.72% of shared closes and is one company; 048 moved to returns and then kept
    a 1e-9 tolerance, which measures the vendor's rounding rather than the securities. A tolerance
    has to be looser than the noise it must survive (learnings 35).

    Sessions where either series has no finite return are not shared sessions and are excluded
    from both the numerator and the denominator, so a name that goes dark is not penalised for the
    gap and is not credited for it either.
    """
    a = np.asarray(ret_a, dtype=float)
    b = np.asarray(ret_b, dtype=float)
    if a.shape != b.shape:
        raise ValueError(f"return series must align: {a.shape} vs {b.shape}")
    shared = np.isfinite(a) & np.isfinite(b)
    n = int(shared.sum())
    if n < min_overlap:
        return False
    # Agreement is only evidence if there was something to disagree ABOUT. Two series that barely
    # move agree within any tolerance trivially — a synthetic ladder of smooth exponentials makes
    # every adjacent rung a "twin", and in live data two low-volatility names drifting at similar
    # rates would do the same and evict a real holding. So the pair must vary by more than the
    # tolerance it is being judged at.
    #
    # No new constant: the floor IS the tolerance. Below it, "these agree to within 1e-4" and
    # "neither of these moved by 1e-4" are the same sentence, and only one of them is a finding.
    if float(a[shared].std()) <= tol or float(b[shared].std()) <= tol:
        return False
    return bool(float((np.abs(a[shared] - b[shared]) < tol).sum()) / n >= agree)
