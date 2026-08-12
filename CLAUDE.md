# Yuna — Claude Code guide

A Python trading agent. **This repository moves real money.** Treat every change here as production-critical.

## The plan is the law

Read [`README.md`](README.md) first, then the three documents it names:

- [`docs/yuna_plan.md`](docs/yuna_plan.md) — **the law.** Where anything else disagrees with the plan, the plan wins, including this file.
- [`docs/roadmap-2026-07-31.md`](docs/roadmap-2026-07-31.md) — build order: what is done, what drifted, what comes next.
- [`docs/learnings.md`](docs/learnings.md) — scar tissue. Facts this build paid for. **Read before touching anything.**

Nothing joins the pipeline schedule without a plan edit. If a change would alter what runs when, that is a plan change first and a code change second.

## Shared doctrine comes from two marketplaces

Declared in [`.claude/settings.json`](.claude/settings.json), and they are split by what they are *about*:

- **Craft** — `dq-core` and `dq-money-code` from [`dailyquest-ca/claude-standards`](https://github.com/dailyquest-ca/claude-standards): safety hooks, operating doctrine, the no-assumed-values discipline.
- **Markets** — `market-domain` and `momentum-strategy` from [`dailyquest-ca/dq-investing`](https://github.com/dailyquest-ca/dq-investing).

`market-domain` is the one to know about for correctness: `account-types` (why RRSP and TFSA treat US dividends differently), `investment-tax-canada` (capital gain versus business income, superficial loss, ACB in CAD), `investment-tax-us` (the cross-border traps), and **`market-mechanics`** (settlement, corporate actions, look-ahead bias). How those bind to this repo's plan is in [`.claude/rules/investment-tax.md`](.claude/rules/investment-tax.md).

**Read `market-mechanics` before touching price data.** It names the defect that invalidated runs 18-44: the engine simulated on raw closes while volume was split-adjusted, so every split arrived as a crash. The doctrine existed and was not loaded. `src/backtest.py` now asserts against it on every run.

`momentum-strategy` is the one to reach for during research: `momentum-doctrine` holds
the sleeve's own strategy — sprint versus marathon, the measured lift of every selection gate, and
the risk-layer scoping — and `backtest-protocol` holds the rules that decide when a number may be
called a finding. **The strategy lives there, not in `src/signals.py`.** This repo implements it;
it does not own it. A rule change that is not Yuna-specific belongs upstream first, with the app
keeping only its own flavour — §3.2's exact thresholds, the engine, and the run history.

`dq-stack` and `dq-web` are deliberately **not** enabled — they are TypeScript and frontend. `dq-core` carries nothing language-specific, so it applies here unchanged.

**The no-assumed-values doctrine matters more here than anywhere else in the estate.** An invented constant in a scoring threshold or a position-sizing rule does not throw. It produces a plausible number, places a real order, and costs real money. Every constant needs a source in the plan.

`dq-finance` is the constants library and has a Python reader (`from dq_finance import resolve`). It is **not yet a dependency of this repo** — every entry in it is unverified, so it cannot return a value, and a private-repo git dependency would need a token in CI where all thirteen workflows currently run a plain `pip install -r requirements.txt`. Add it once entries are verified.

Destructive database and git operations are blocked by a hook; `git push`, migrations, and direct SQL prompt with an impact summary. That is intended.

## Stack

| Layer | Choice |
| --- | --- |
| Language | Python 3, `numpy` · `pandas` · `psycopg` |
| Store | Supabase Postgres — universe, book, briefs, fundamentals, rulings and learnings ledgers |
| Data | EODHD All-In-One — bulk prices, FX, fundamentals, earnings calendar |
| Compute | GitHub Actions: four scheduled jobs, four chained by `needs:` in `pipeline.yml` |
| Tests | pytest — `tests/` unit, `tests/integration/` against local Postgres |

## Dependencies are pinned on purpose

`requirements.txt` pins exact versions, and the comment there explains why: *the worst backtest bug in this repo came from a pandas `rolling()` default.* A silent minor-version bump is a real risk to real money.

**Never loosen a pin, never add an unpinned dependency, and never upgrade one as a side effect of another task.** An upgrade is its own change, with its own backtest.

## Commands

```bash
pytest                      # full suite
pytest tests/test_arming.py # single file
bash tests/integration/local_pg.sh   # integration deps
```

`src/` jobs are invoked by the workflows in `.github/workflows/`. `migrate`, `phase0`, `backfill`, `fills`, and both backtests are **dispatch-only tooling** — they are not on the schedule and must not be added to it without a plan edit.

## Division of authority

Yuna proposes; Zak decides. Zak places every order — entries, stop moves, gap exits, fill confirmations, and the monthly law-and-risk rulings. Nothing in this repo should ever place an order autonomously, and no change should move it in that direction without an explicit plan amendment.
