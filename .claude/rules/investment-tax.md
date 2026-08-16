---
paths:
  - "src/**/*.py"
  - "docs/yuna_plan.md"
---

# Investment tax in Yuna

The general domain is in the `market-domain` plugin from the [`dq-investing`](https://github.com/dailyquest-ca/dq-investing) marketplace — `account-types`, `investment-tax-canada`, `investment-tax-us`, `market-mechanics`. This file records how those rules bind *here*, and where the plan already depends on them.

## The plan encodes tax rules as strategy

`docs/yuna_plan.md` §2.6 makes account placement a tax decision:

- **Momentum lives in the TFSA only.** Tax-free turnover is the edge. The accepted cost is stated in the plan: TFSA losses burn contribution room permanently, and there is no capital loss to claim
- **RRSP is the compounder satellite**, preferred for US names with a trailing-12-month dividend yield at or above the plan's threshold, because **US dividend withholding is treaty-exempt in an RRSP and is not in a TFSA**
- **Non-registered carries the levered layer**, and every swap there carries a tax flag because the disposition is real

These are the plan's rulings, not defaults to re-derive. **Do not change placement logic as a side effect of another task.** If a tax rule appears to contradict the plan, raise it — the plan is the law, and a conflict means either the plan needs a ruling or the reading is wrong.

## Three rules this system is specifically exposed to

**Business income recharacterization.** Momentum is high-turnover by design, which is squarely within the factors CRA weighs when deciding whether trading is business income rather than capital gains. Never model or state after-tax return as if capital treatment is certain. Where after-tax figures are produced, the characterization is a stated assumption, not a silent constant.

**Superficial loss across accounts.** The rule reaches into your own registered accounts. Selling at a loss in non-registered and acquiring the same security in the TFSA or RRSP within the 30-day window denies the loss **permanently** — it is added to the ACB of shares in an account where ACB is meaningless. Yuna runs one strategy across three account types, so any cross-account move near a loss is exposed. Flag it; do not net it away.

**ACB in CAD for USD positions.** Every transaction converts at its own transaction-date rate. A US position flat in USD still produces a CAD capital gain or loss from the currency alone, and it is taxable. NAV is already converted to CAD per the plan; **tax basis is a separate calculation and must not reuse a NAV conversion rate.**

## Constants

`dq-finance` is the constants library, and it has a Python reader — `from dq_finance import resolve`.

**It is not yet a dependency of this repo, deliberately.** Every entry in it is currently unverified, so it cannot return a value; adding it to `requirements.txt` would risk the workflows without buying anything. Add it once entries are verified, and note that a private-repo git dependency needs a token available to CI — all thirteen workflows install with a plain `pip install -r requirements.txt` today.

Until then: **any tax rate, limit, or threshold needed here is an unverified value and the calculation fails closed.** Do not inline a number from the plan, from a search, or from memory. See the `no-assumed-values` skill.

## Corporate actions

The plan already flags that splits and large buybacks change share counts between filings and require re-deriving effective shares. That is a `market-mechanics` concern with a tax dimension too: a split changes per-share ACB without a trade occurring, and any position or basis tracking that only reconciles on trades will drift.
