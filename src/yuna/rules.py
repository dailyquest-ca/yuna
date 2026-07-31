"""The plan-to-code ledger.

docs/yuna_plan.md is law, and the standing risk on a project like this is drift:
code that quietly does something the plan never said, or a plan clause everyone
assumed was built and nobody built. Both failure modes are invisible to ordinary
tests, because code that does the wrong thing correctly still passes.

So every rule the code enforces names the clause it comes from::

    @implements("3.2/stop-8pct", "initial stop 8% below the entry fill")
    def initial_stop(fill: float) -> float:
        return round(fill * 0.92, 2)

and every clause the plan states appears in CLAUSES below with its status. The
conformance test walks both directions:

  * a decorator naming a clause that is not in CLAUSES fails — no invented rules;
  * a clause whose section number does not exist in the plan text fails — no
    citations to nothing;
  * a clause marked BUILT with no decorator anywhere fails — no imaginary builds;
  * a clause marked OPEN or PENDING with no reason fails — no silent deferrals.

The ledger is therefore the honest answer to "what is actually implemented", and
it cannot rot without turning the build red.
"""
from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

# --- statuses --------------------------------------------------------------
BUILT = "built"        # implemented in code, decorator required
SESSION = "session"    # Yuna judges it inside a session; no job may encode it (§2.2, §4.3)
MANUAL = "manual"      # Zak's action, outside the machine entirely (§4.5)
OPEN = "open"          # not built yet; `note` says what is missing
PENDING = "pending"    # blocked on a ruling from Zak; `note` names the question

_STATUSES = frozenset({BUILT, SESSION, MANUAL, OPEN, PENDING})


@dataclasses.dataclass(frozen=True)
class Clause:
    """One rule the plan states, and where the build stands on it.

    `status` is whether the rule exists in code. `wired` is whether anything in
    the running system calls it. They are different questions and conflating them
    is how a build convinces itself it is finished: a tested rule function that no
    job invokes protects nothing.
    """

    key: str          # "3.2/stop-8pct" — section, slash, short stable name
    text: str         # what the plan says, in the plan's own terms
    status: str
    wired: bool = False
    note: str = ""

    @property
    def section(self) -> str:
        return self.key.split("/", 1)[0]


@dataclasses.dataclass(frozen=True)
class Site:
    """A place in the code that claims to implement a clause."""

    key: str
    what: str
    module: str
    qualname: str


_SITES: list[Site] = []

F = TypeVar("F", bound=Callable[..., Any])


def implements(key: str, what: str) -> Callable[[F], F]:
    """Mark a function as implementing a plan clause.

    `key` must appear in CLAUSES. `what` states, in one line, what this code does
    about it — the thing a reviewer compares against the plan text.
    """

    def deco(fn: F) -> F:
        _SITES.append(Site(key=key, what=what,
                           module=getattr(fn, "__module__", "?"),
                           qualname=getattr(fn, "__qualname__", "?")))
        fn.__yuna_clause__ = key
        return fn

    return deco


def sites() -> list[Site]:
    """Every registered implementation site, in import order."""
    return list(_SITES) + sql_sites()


_SQL_MARKER = re.compile(r"^\s*--\s*implements:\s*(\S+)\s*(?:--|—|-)\s*(.+?)\s*$", re.M)


def sql_sites(migrations: Path | None = None) -> list[Site]:
    """Rules enforced in SQL rather than Python.

    Some of the plan lives in the database and nowhere else — the guard triggers
    that refuse a write from the wrong role are the clearest case, and they are
    load-bearing precisely because no Python can bypass them. A migration claims
    a clause with a comment::

        -- implements: 4.3/guard-triggers — refuses writes from any role but the migrator

    so the ledger covers the whole system rather than only the part written in
    Python. The marker is one line: a description wrapped onto a second `--` line
    would have its tail silently dropped, and silent truncation is exactly the
    class of bug this ledger exists to prevent. Missing directory is not an error —
    the package is importable from an installed wheel with no migrations beside it.
    """
    root = migrations or (Path(__file__).resolve().parents[2] / "migrations")
    if not root.is_dir():
        return []
    found: list[Site] = []
    for path in sorted(root.glob("*.sql")):
        for key, what in _SQL_MARKER.findall(path.read_text(encoding="utf-8")):
            found.append(Site(key=key, what=what, module=f"migrations/{path.name}", qualname="sql"))
    return found


def clauses() -> dict[str, Clause]:
    return dict(_BY_KEY)


def by_status(status: str) -> list[Clause]:
    return [c for c in CLAUSES if c.status == status]


# ---------------------------------------------------------------------------
# The ledger. Ordered by plan section. Adding a clause here without building it
# is fine and expected — that is what OPEN means, and the audit reads this list.
# ---------------------------------------------------------------------------
CLAUSES: tuple[Clause, ...] = (
    # --- §2.0 NAV & capital accounting -------------------------------------
    Clause("2.0/nav-from-balances",
           "NAV is all assets at market minus all debt, in CAD; recorded balances anchor it "
           "and prices extrapolate from them",
           BUILT, wired=True),
    Clause("2.0/cash-per-currency",
           "CAD and USD cash are held separately inside an investing account; facility "
           "balances are always CAD",
           BUILT, wired=True),
    Clause("2.0/facilities-are-debt",
           "a facility contributes its drawn balance as debt; undrawn credit is capacity, "
           "not a liability",
           BUILT, wired=True),
    Clause("2.0/levered-outside-sleeves",
           "the levered layer sits outside the sleeves and consumes no sleeve room, but "
           "independence and theme caps still see it",
           OPEN, note="phase0 routes levered names to Step 5; no sleeve accounting for them"),
    Clause("2.0/provisional-balances",
           "a balance Zak states mid-week is provisional and labeled, trued up Sunday",
           OPEN, note="needs the session write path (session_record_cash)"),
    Clause("2.0/ticket-names-account",
           "every ticket names an account and is written only if that account holds the cash",
           OPEN, note="phase0 assigns accounts; there is no cash check and no steady-state path"),
    Clause("2.0/t1-reuse",
           "cash from a same-account sell already filled or ticketed ahead counts as available",
           OPEN, note="reading 4, approved 2026-07-31"),

    # --- §2.1-2.6 sleeves, independence, sizing ----------------------------
    Clause("2.1/sleeve-counts",
           "compounders 60% / 4-5 names / 12-15% entries; momentum up to 40% / 3-4 names / "
           "8-12% entries; the momentum ceiling is not a quota",
           BUILT, wired=True),
    Clause("2.2/max-2-per-group",
           "at most 2 names per vendor industry group",
           BUILT, wired=True),
    Clause("2.2/theme-cap-35",
           "no new capital enters a theme above 35% of NAV; a winner that grows past is not "
           "forced out",
           OPEN, note="DEVIATION: phase0 substitutes vendor sector for theme. The plan says "
                      "theme is Yuna's judgment assigned in the ticket-writing session and "
                      "that sector is an input, never the definition"),
    Clause("2.2/effective-bets",
           "effective bets = 1 / sum(wi wj rho_ij) over the whole book; a draft that leaves "
           "the book below 4 carries a warning, and never blocks",
           BUILT, note="computed; nothing prints it yet — belongs to R1"),
    Clause("2.2/jobs-arm-sessions-write",
           "jobs arm candidates; only sessions write tickets, because theme is judgment",
           OPEN, note="phase0.py writes tickets directly"),
    Clause("2.3/position-floor", "minimum position 4% of NAV on intended full size",
           BUILT, wired=True),
    Clause("2.3/single-name-cap", "single-name ceiling 25% of NAV, entry only", BUILT),
    Clause("2.3/risk-not-dollars",
           "risk = position size x distance to stop; sizing is compared on risk",
           BUILT, wired=True, note="momentum only; compounders size flat per §3.1"),
    Clause("2.4/no-averaging-down-momentum",
           "the momentum sleeve never averages down",
           OPEN, note="not enforced anywhere"),
    Clause("2.5/leverage",
           "facility utilization caps, what each may fund, and CCN >= 85 for single names",
           OPEN, note="facilities are accounted in NAV; nothing arms or governs a draw"),
    Clause("2.6/account-placement",
           "momentum lives in TFSA only; RRSP takes compounder satellites and idle cash; "
           "the levered layer is non-registered only",
           OPEN, note="phase0 places names; the rule is not enforced as a check"),
    Clause("2.7/non-conformance",
           "inherited positions that breach the caps are named and worked down",
           BUILT, wired=True, note="phase0 §6 re-underwrite produced the breach list"),

    # --- §3.0 layers & cadence ----------------------------------------------
    Clause("3.0/l2-composition",
           "top-10 MCN in BUY state, every bench name within 10% of its hurdle, and all "
           "holdings; cap 20, holdings always seated, remaining seats by trigger proximity "
           "then score, spare seats from L1-M by MCN rank",
           OPEN, note="rank.py seats holdings and top-10 by MCN; the hurdle-proximity arm and "
                      "the spare-seat fill are not built"),

    # --- §3.1 compounder pipeline ------------------------------------------
    Clause("3.1/c1-gate", "Gate C1 eligibility on the coarse L0", BUILT, wired=True),
    Clause("3.1/c1-excludes-financials",
           "banks and insurers are out of the compounder universe",
           BUILT, wired=True,
           note="vendor industry prefix, not sector — the sector also holds exchanges and "
                "payment networks, which are exactly the toll-booth compounders this wants"),
    Clause("3.1/ccn-score",
           "CCN v1.0: engine, cash conversion, inverted log size — equal weight, L0 percentiles",
           BUILT, wired=True),
    Clause("3.1/engine-reliability",
           "agreement within 5 percentage points of observed 3-yr revenue growth; beyond that "
           "the engine component routes down the data-confidence path",
           BUILT, wired=True,
           note="DEVIATION: on divergence the code caps the hurdle's growth input at observed "
                "revenue growth. The plan routes the engine down the data-confidence path — "
                "which governs the CCN — and is silent on what growth the hurdle should then "
                "use. Raised as Q7"),
    Clause("3.1/hurdle",
           "hurdle v1.0: the highest price at which FCF yield + growth - derating drag "
           "still clears 15%",
           BUILT, wired=True),
    Clause("3.1/hurdle-within-10pct",
           "'within 10% of the hurdle' means price <= 1.10 x hurdle, everywhere it appears",
           BUILT, wired=True,
           note="reading 6, approved 2026-07-31; used by the bench eviction seatbelt. The L2 "
                "seating arm that also needs it is not built"),
    Clause("3.1/statement-currency",
           "a name is underwritten in the currency its statements are filed in",
           BUILT, wired=True,
           note="detected from Financials.*.currency_symbol; General.CurrencyCode lies, and "
                "so does the vendor's own PriceSalesTTM"),
    Clause("3.1/foreign-fx",
           "a foreign issuer is compounder-eligible when FCF and market cap are in one "
           "currency — financials converted at fiscal-period-end FX, market cap the vendor's "
           "USD figure; no conversion data routes to the data-confidence path",
           OPEN, note="DEVIATION: a currency mismatch currently fails C1 outright, which drops "
                      "TSM, Wise and Karooooo rather than converting them. The plan never "
                      "authorized exclusion"),
    Clause("3.1/effective-shares",
           "market cap at price P uses effective shares = vendor USD cap / last close, which "
           "resolves ADR ratios, listing currency and share class",
           OPEN, note="DEVIATION: the hurdle divides by reported shares outstanding. For an "
                      "ADR those are different objects and the hurdle is wrong by the ratio"),
    Clause("3.1/bench-cohorts",
           "the funnel takes the top 30 by CCN from each size cohort, boundary $10B market cap",
           BUILT, wired=True),
    Clause("3.1/bench-eviction",
           "gate failure evicts immediately; rank eviction needs two consecutive months "
           "outside the top 60 and never touches a holding or a name within 10% of its hurdle",
           BUILT, wired=True,
           note="DEVIATION: holdings are protected, the within-10%-of-hurdle protection is not"),
    Clause("3.1/rejected-cooldown",
           "a rejected name waits 12 months; early escape needs a new filing and CCN at least "
           "10 above the CCN recorded at rejection",
           OPEN),
    Clause("3.1/compounder-sizing",
           "CCN 70-84 sizes 12% of NAV and 85+ sizes 15%, flat 12% until Zak unlocks the upper "
           "tier at a monthly approval",
           BUILT, wired=True),
    Clause("3.1/averaging-down",
           "CCN >= 70 and below hurdle: 5-15% below adds 50% of original size, more than 15% "
           "below adds 100%, at most 2 adds per name per 12 months",
           BUILT, note="the add size is computed; nothing tracks the 12-month count"),

    # --- §3.2 momentum pipeline --------------------------------------------
    Clause("3.2/m1-latch",
           "M1: SPX Friday close above its 30-week average and the average no lower than "
           "4 weeks ago -> ON; below -> OFF; latched until the opposite condition fires",
           BUILT, wired=True),
    Clause("3.2/m2-trend-template",
           "above the 150 & 200-day, 150 above 200, 200 rising, above the 50-day, >=30% off "
           "the 52-week low, within 25% of the high",
           BUILT, wired=True),
    Clause("3.2/m4-earnings-acceleration",
           "latest quarter YoY EPS growth >= 25%, or accelerating two quarters with the "
           "latest >= 15%",
           BUILT, wired=True),
    Clause("3.2/mcn-score",
           "MCN v1.0: momentum quality, setup proximity, industry group strength — equal "
           "weight, windows ending 10 sessions ago",
           BUILT, wired=True,
           note="DEVIATION: setup proximity averages FOUR sub-scores in rank.py; the "
                "2026-07-31 pass dropped pullback contraction, leaving three. Every MCN in "
                "the database is computed on the superseded definition"),
    Clause("3.2/l1m-top150", "L1-M membership = M2 + M4 pass, ranked by MCN, top 150",
           BUILT, wired=True),
    Clause("3.2/base-detection",
           "pivot = highest high 120 to 25 sessions back; broken by a later close above the "
           "pivot or a later high beyond pivot x 1.005; valid when unbroken and <=25% deep",
           BUILT,
           note="NOT wired: rank.py still carries the superseded scan, which used a 15-session "
                "offset, an age partition and no high test"),
    Clause("3.2/pivot-grace",
           "a later high beyond pivot x 1.005 spends the pivot and breaks the base; highs "
           "inside the grace are noise",
           BUILT, note="X3 ruled 2026-07-31 — the two-way break test replaced the closes-only "
                       "reading; near-BUY, base age and the forming state were deleted with it"),
    Clause("3.2/pyramid-ceiling",
           "both add stop-limits carry limit pivot x 1.05, so a skipped band completes at the "
           "open and a gap beyond +5% fills nothing",
           BUILT, note="X2 dissolved 2026-07-31 — the gap-up market order was deleted rather "
                       "than bounded; the ceiling enforces itself at the broker, unwatched"),
    Clause("3.2/breakout-confirmation",
           "entry is mechanical at the pivot; volume >= 1.4x the trailing 50-day confirms at "
           "EOD, each session against its own baseline; unconfirmed freezes the pyramid at 50% "
           "with three sessions to confirm late",
           BUILT, note="not wired — the live path has no pyramid state machine"),
    Clause("3.2/failed-breakout",
           "while unconfirmed, a close back below the pivot exits next morning",
           BUILT),
    Clause("3.2/pyramid",
           "steps at the pivot, +2% and +4%, sized 50/25/25; nothing beyond +5%",
           BUILT, note="the orders are computed; no live state machine tracks which step a "
                       "position has reached"),
    Clause("3.2/stalled-pyramid",
           "a pyramid stalled below full size for 4 weeks completes on the next base or exits",
           OPEN),
    Clause("3.2/stop-8pct",
           "initial stop is the higher of the final-contraction low or entry - 8%, never wider",
           BUILT, wired=True),
    Clause("3.2/euphoria-ratchet",
           "a close more than 2 standard deviations above the own 50-day tightens the trail "
           "to 5% below the highest close",
           BUILT, wired=True,
           note="the largest-single-day-gain trigger was deleted 2026-07-31 — it needed "
                "per-position running-max state the 2 sigma test does not"),
    Clause("3.2/breakeven-ratchet", "full size moves the stop to breakeven", BUILT, wired=True),
    Clause("3.2/trail-10",
           "+15% from average cost trails 10% below the highest close since entry; stops "
           "ratchet up, never down",
           BUILT, wired=True),
    Clause("3.2/momentum-sizing",
           "risk budget 0.7% of NAV at MCN 70-84 and 0.9% at 85+, halved to 0.5%/0.7% for the "
           "first 90 days; size = budget / stop distance, capped by the band",
           BUILT, wired=True, note="running the start-low budgets"),
    Clause("3.2/momentum-exits",
           "exits are stop fired, trend template failed, or MCN < 55; a stop-out carries no "
           "cooldown and re-entry needs only a valid base and all gates",
           OPEN, note="the nightly reports fired stops; nothing acts on template failure or MCN"),

    # --- §3.3 shared rules --------------------------------------------------
    Clause("3.3/thresholds",
           "85+ full conviction, 70-84 enterable, 55-69 hold, <55 exit review, +10 to displace",
           BUILT, wired=True, note="phase0 uses 70 and 85; the +10 displacement is not built"),
    Clause("3.3/displacement",
           "a challenger needs +10 over the weakest incumbent, within sleeve only, and the "
           "swap ticket is auto-drafted",
           OPEN, note="reading 7 — R1 drafts it, not a job"),
    Clause("3.3/blackout",
           "no new entries and no adds within 5 trading days of a scheduled report, both sleeves",
           BUILT, wired=True),
    Clause("3.3/blackout-trading-days",
           "the window is counted in trading days, and lifts the first session after the report",
           BUILT, note="policy.in_blackout counts sessions; the nightly still approximates "
                       "calendar days x 1.6 and phase0 hardcodes 8"),
    Clause("3.3/blackout-cancels-orders",
           "entering the window cancels live entry and add orders at the broker; protective "
           "stops always remain",
           OPEN),
    Clause("3.3/blackout-beats-pyramid",
           "a breakout confirming inside a blackout arms no adds",
           BUILT, note="reading 3, approved 2026-07-31"),
    Clause("3.3/earnings-cushion",
           "a momentum position holds through a print only at last close >= 1.08 x average cost",
           BUILT, note="not wired — the nightly reports the blackout but not the cushion test"),
    Clause("3.3/renormalize-one-missing",
           "drop a missing component, renormalize to 100, mark the name scored on 2 of 3",
           BUILT, wired=True),
    Clause("3.3/data-confidence",
           "never assume a missing value; an incompletely-scored name is capped at the bottom "
           "of its band and requires manual sign-off",
           BUILT, wired=True,
           note="the floor — two components, one a business measure — is a deviation the audit "
                "records: taken literally the rule lets size alone score a name"),
    Clause("3.3/filing-date",
           "fundamentals are used as of filing date, never fiscal period end",
           BUILT, wired=True),
    Clause("3.3/delisted-retained",
           "delisted names are retained in the universe",
           OPEN, note="affordable since the Supabase upgrade; not ingested"),
    Clause("3.3/order-execution",
           "single decisive orders at computed levels; momentum adds on strength only; "
           "compounder adds only below the hurdle",
           OPEN),
    Clause("3.3/crash-protocol",
           "gate shuts -> momentum to cash -> compounder adds in 3 tranches >=10 sessions "
           "apart, tagged tactical; core lots never touched",
           OPEN),
    Clause("3.3/dual-qualification",
           "a name passing both screens goes to compounders; a momentum holding converts only "
           "through the monthly approval",
           OPEN),
    Clause("3.3/shadow-book",
           "every pass and every exit snapshots score + price, marked at 30 / 60 / 90 days",
           OPEN),
    Clause("3.3/versioning",
           "CCN v1.0, MCN v1.0, Hurdle v1.0, M1 v1.0 — changes increment and are logged",
           OPEN, note="versions are named in docstrings, not recorded on the rows they produce"),

    # --- §4 mechanics -------------------------------------------------------
    Clause("4.1/point-in-time",
           "every historical statement carries its filing date, so a backtest sees only what "
           "was filed",
           BUILT, wired=True),
    Clause("4.2/five-scheduled-jobs",
           "exactly five scheduled jobs",
           OPEN, note="fundamentals.yml carries a sixth cron"),
    Clause("4.3/guard-triggers",
           "the database refuses writes from anything but the migration role",
           BUILT, wired=True, note="role-based, so a pooler cannot silently drop session state"),
    Clause("4.4/sessions", "the five sessions R1 through R5", OPEN),
    Clause("4.5/zak-executes", "Zak places every order; Yuna never executes", MANUAL),
    Clause("4.6/reflex-layer", "the reflex layer", OPEN),
    Clause("4.7/heartbeat",
           "every job writes exactly one runs row — green, amber or red — with the traceback "
           "on death",
           BUILT, wired=True),
    Clause("4.7/stale-data-no-tickets",
           "stale data means no new tickets; an amber job stales its own domain only",
           BUILT, wired=True),
    Clause("4.8/backtest-grade",
           "every backtest output states its grade",
           OPEN, note="graded in prose in the findings doc, not carried in the output"),
    Clause("4.8/secrets-in-actions",
           "credentials live in GitHub Actions secrets and nowhere else",
           MANUAL, note="set by Zak in the UI, never through chat"),

    # --- §5 sessions --------------------------------------------------------
    Clause("5.1/r1-preopen", "R1 pre-open: the brief, the tickets, the entry mechanic", OPEN),
    Clause("5.1/r1-drafts-swap",
           "'the swap ticket is auto-drafted' means R1 drafts it, not a job",
           OPEN, note="reading 7, approved 2026-07-31"),
    Clause("5.2/r2-stop-sheet", "R2 evening stop sheet", OPEN),
    Clause("5.3/r3-deep-dive", "R3 Saturday deep dive", OPEN),
    Clause("5.4/r4-reconciliation", "R4 Sunday reconciliation", OPEN),
    Clause("5.5/r5-monthly", "R5 monthly approval", OPEN),
    Clause("5.6/session-laws", "the shared session laws", OPEN),
    Clause("5.6/performance-twr",
           "the 30% bar is measured time-weighted, so deposits do not flatter it",
           BUILT, note="ruled by Zak 2026-07-31; no session reports it yet"),

    # --- §6 phase 0 ---------------------------------------------------------
    Clause("6/re-underwrite",
           "every inherited position is re-underwritten as though it were a new entry today",
           BUILT, wired=True),
    Clause("6/conforming-target-book",
           "Phase 0 hands over a book that conforms to the sleeve counts, the caps and the "
           "blackout — not a raw list",
           BUILT, wired=True),
)

_BY_KEY: dict[str, Clause] = {}
for _c in CLAUSES:
    if _c.status not in _STATUSES:
        raise ValueError(f"{_c.key}: unknown status {_c.status!r}")
    if _c.key in _BY_KEY:
        raise ValueError(f"duplicate clause {_c.key!r}")
    _BY_KEY[_c.key] = _c
del _c
