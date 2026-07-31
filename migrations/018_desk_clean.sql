-- 018_desk_clean.sql — clear the desk before the build resumes (roadmap 2026-07-31).
--
-- Three jobs, all data hygiene, no schema change and no plan-stated number moved:
--   1. Cancel the stale proposed tickets. Three phase0 runs appended 45 rows encoding 15
--      decisions, because tickets have no identity yet (roadmap A3 gives them one). Leaving them
--      proposed means the first R1 session would publish a ticket set computed against a plan
--      that has since been amended. The ledger keeps every row — §4.3 says append, never edit —
--      so they move to `cancelled` with a reason rather than being deleted.
--   2. Correct two config notes whose wording quotes repealed law. Values are untouched; the
--      note text is the only change, so plan-over-config supremacy is not in play.
--   3. Record Zak's 2026-07-31 rulings as observations, so the next session reads them from the
--      database rather than from chat.
--
-- Deliberately NOT done here: seeding the config keys the amended plan names (pivot window,
-- pyramid triggers, confirmation volume, hold-through cushion, effective-bets warn level). A rule
-- stored is not a rule enforced — learnings #21. Each key ships in the commit that reads it.

-- ---------- 1. stale tickets ----------
update tickets
   set state = 'cancelled',
       note = coalesce(note || ' · ', '') ||
              'superseded 2026-07-31: phase0 re-runs at cutover under the amended plan (roadmap Phase L)',
       updated_at = now()
 where state = 'proposed'
   and reason = 'phase0';

-- the momentum/compounder entry tickets from the same runs, same reasoning
update tickets
   set state = 'cancelled',
       note = coalesce(note || ' · ', '') ||
              'superseded 2026-07-31: re-armed by the nightly job once arming exists (roadmap Phase I)',
       updated_at = now()
 where state = 'proposed';

-- ---------- 2. config notes that quote repealed law ----------
insert into config (key, value, note, set_by)
select 'ccn_flat_size', value,
       '§3.1 flat 12% for at least the first two full calendar quarters after cutover; 15% unlocks '
       'only by an R5 ruling on the shadow-book cohort comparison, and absent a ruling flat 12% continues',
       'yuna'
  from config where key = 'ccn_flat_size'
 order by set_at desc limit 1;

insert into config (key, value, note, set_by)
select 'mcn_risk_budget_validation', value,
       '§3.2 start-low budgets: the first 90 calendar days from the system''s first momentum entry '
       'fill run 0.5% / 0.7%. Key name predates the plan retiring the "validation quarter" wording; '
       'renamed when the sizing code is rewritten (roadmap Phase I)',
       'yuna'
  from config where key = 'mcn_risk_budget_validation'
 order by set_at desc limit 1;

-- ---------- 3. Zak's rulings, 2026-07-31 ----------
insert into observations (kind, ticker, body, detail)
select 'note', null,
       'RULED by Zak 2026-07-31: no position carries a stop at the broker, and all seven holdings '
       'are up for rotation — every one must earn its keep. §6 Step 2b therefore applies at full '
       'strength: nothing is grandfathered and no stop reconstruction is needed. The book is '
       'unprotected between now and cutover by choice, not oversight.',
       '{"positions":7,"stops_at_broker":0,"phase0_verdicts":{"keep":0,"exit":6,"step5":1},'
       '"open":"CNQ vs VXC.TO at Step 5"}'::jsonb
 where not exists (select 1 from observations where body like 'RULED by Zak 2026-07-31: no position%');

insert into observations (kind, ticker, body, detail)
select 'note', null,
       'RULED by Zak 2026-07-31: bench approvals happen as C2 memos arrive, so the compounder '
       'sleeve unlocks with the first R5 session (roadmap Phase K). The roadmap of 2026-07-31 is '
       'the build order we follow.',
       '{"bench_rows":67,"approved":0,"unlocks":"Phase K first R5"}'::jsonb
 where not exists (select 1 from observations where body like 'RULED by Zak 2026-07-31: bench approvals%');
