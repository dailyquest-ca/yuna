-- 042_the_obvious_name_is_the_safe_name.sql — 2026-08-12.
--
-- `research_monthly` was built from `prices.close`, which is the raw print. On a split, the raw
-- print collapses, so the table's month-over-month returns include a **6,474,999x** move. It was
-- rebuilt correctly as `research_monthly_adj` on `prices.adj_close`, and the census lifts were
-- re-derived from the adjusted table — but the contaminated table was left in place under the
-- shorter, more obvious name.
--
-- That is the same shape of defect as the one that invalidated runs 18-44: not a missing fact, but
-- a correct fact sitting next to an incorrect one with nothing to tell a reader which is which.
-- `docs/learnings.md` records the rule this migration enforces: **the unqualified name must be the
-- safe one.** A future session that reaches for `research_monthly` should not have to know this
-- history to get the right answer.
--
-- So:
--   * the contaminated table is renamed to say what it is, and kept — it is the evidence, and
--     `docs/backtest-findings-2026-08-10.md` cites figures derived from it
--   * `research_monthly` becomes a read-only view onto the adjusted table, so the obvious name
--     now resolves to correct data
--
-- Both tables carry identical column shapes (ticker, m, close, hi, lo, addv, bars), so the view is
-- a drop-in for any query written against the old table.

-- Both tables were built by a research session rather than by a migration, so NEITHER exists on a
-- fresh database — not in the integration suite, not in a rebuild, not in a new environment. The
-- first cut of this migration assumed production: `alter table if exists` no-opped, and then the
-- unguarded `comment on table` hit a table that had never been created and took the whole
-- migration run down with it. That is why `tests.yml` went red and stayed red.
--
-- So the rename is conditional on there being something to rename, and the view on there being
-- something to point at. On production both branches fire and the outcome is unchanged. On a fresh
-- database this is a clean no-op, which is the honest answer — there is no contaminated table to
-- rename and no adjusted table to alias, so there is nothing here to protect a reader from.
do $$
begin
  if to_regclass('research_monthly_raw_contaminated') is null
     and to_regclass('research_monthly') is not null then
    alter table research_monthly rename to research_monthly_raw_contaminated;
  end if;

  if to_regclass('research_monthly_raw_contaminated') is not null then
    comment on table research_monthly_raw_contaminated is
      'DO NOT USE for analysis. Built from prices.close (the raw, split-unadjusted print), so '
      'returns across a split are meaningless — the worst is +6,474,999%. Retained as the evidence '
      'behind the census figures in docs/backtest-findings-2026-08-10.md. Use research_monthly_adj, '
      'or the research_monthly view, which points at it.';
  end if;

  if to_regclass('research_monthly_adj') is not null then
    create or replace view research_monthly as
      select ticker, m, close, hi, lo, addv, bars from research_monthly_adj;
    comment on view research_monthly is
      'The adjusted monthly research series (research_monthly_adj). This name used to be a base '
      'table built on raw closes; it is a view now so that the unqualified name resolves to correct '
      'data regardless of what a reader knows about migration 042.';
  end if;
end $$;
