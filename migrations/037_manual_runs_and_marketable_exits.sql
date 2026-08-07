-- 037 — the two things Zak asked for on 2026-08-07, as config.
--
-- "I want to be able to manually run everything, and allow it to work OK? I don't want a manual
-- run to be thwarted by the day." Handled in code (`db.scheduled_run`) rather than here: every
-- work-guard now applies only to a SCHEDULED firing. A guard exists to stop a duplicate cron, not
-- to argue with a person, and having to remember a `force` checkbox first is the guard defeating
-- the human it was built for.
--
-- "I just want to make sure if there is merit to a limit sell instead… the machine does that.
-- Sometimes it seems like it always just says market sell." It did — six of its eight exits were
-- market orders. Zak's own 2026-08-06 mechanics ruling already set the answer for the exits he
-- rules; this extends it to the ones the machine concludes on its own, which are the *unhurried*
-- ones: a name that failed its trend template last Friday is not getting worse in the ninety
-- seconds a limit costs.
--
-- Still market, and each for a stated reason: a gap through the stop-limit (§4.6 says
-- market-at-open in so many words), the market gate shutting (§3.3's crash protocol takes the
-- sleeve to cash), and the unconfirmed-breakout hair-trigger. Urgency is the only thing that buys
-- a market order.
insert into config (key, value, note, set_by)
select 'exit_limit_inside', '0.003'::jsonb,
       '§4.5 (ruled 2026-08-06) — a non-urgent exit ships as a marketable limit this far inside '
       'the last print, recomputed at placement. Gap drills, gate-off exits and the unconfirmed '
       'hair-trigger stay market: urgency is what buys a market order.', 'zak'
 where not exists (select 1 from config where key = 'exit_limit_inside');
