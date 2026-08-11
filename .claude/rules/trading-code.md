---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Trading code

Loads when working in `src/` or `tests/`. This repository moves real money; these are the constraints that make a wrong number expensive rather than merely wrong.

## Every constant traces to the plan

Scoring thresholds, position sizes, stop distances, universe filters, freshness windows — each needs a source in [`docs/yuna_plan.md`](../../docs/yuna_plan.md). Not "this looked reasonable in the backtest," not a value carried over from a prior version.

If the plan does not specify it, **that is a plan gap**. Raise it. Do not fill it with a plausible default — see the `no-assumed-values` skill.

## Silent failure is the enemy

An exception is a good outcome here: it stops the pipeline and someone looks. The bad outcome is a job that completes, writes a number, and is wrong.

- Never swallow an exception. No bare `except:`, no `except Exception: pass`
- Fail loudly on missing or stale data rather than proceeding with a partial set
- A guard that detects a bad state must halt, not warn and continue
- Freshness checks exist because stale data looks exactly like fresh data downstream

## pandas and numpy

The pinned versions are load-bearing. The worst backtest bug in this repo came from a `rolling()` default changing between versions.

- **Pass window, `min_periods`, and `closed` explicitly** on every rolling and expanding operation. Never rely on a default
- Be explicit about NaN handling. `skipna` defaults differ across operations and versions
- Beware silent dtype coercion, and index alignment quietly producing NaN on arithmetic between misaligned series
- Never chain assignment; it may or may not write through

## Look-ahead bias

Backtests are the mechanism by which a wrong idea looks correct. Fundamentals are point-in-time for a reason.

- Never use a value that would not have been knowable at the bar being scored
- Filing dates, not period-end dates, gate fundamental availability
- A backtest result that improves sharply after a change to data handling is a look-ahead bug until proven otherwise

## Idempotence

Jobs are chained by `needs:` and re-run on failure. Every write upserts by a stable key. A re-run must not double-count a fill, a position, or a ledger entry.

## Tests

`tests/` is unit, `tests/integration/` runs against local Postgres.

Test the documented rule, not the current output. A test written by reading the implementation agrees with the implementation and catches nothing — see the `testing-standards` skill on silent regression. Guard tests such as `test_backfill_guard.py` exist to prove a guard *fires*; changing one so it passes defeats its purpose.

## Never place an order

Nothing in this repository places, modifies, or cancels an order. Zak executes. A change moving the system toward autonomous execution needs an explicit plan amendment, not an inference from a task.
