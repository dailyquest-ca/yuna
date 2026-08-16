-- 057_the_facility_and_the_freeze.sql — 2026-08-16.
--
-- Two things: the LOC as Zak stated it, and §5.5's freeze given a place to live.

-- ---- 1. the facility, in Zak's own words ------------------------------------------------------
--
-- Zak, 2026-08-16: *"The LOC's limit is 75k. None drawn."*
--
-- `balances` is the append ledger where an account fact enters the system, `source = 'zak'` marks
-- who said it, and `as_of` dates it. Nothing derives this: §2.3's cap is 50% of the LIMIT and the
-- limit is a fact about an account only Zak can see.
--
-- **This disagrees with §2.3's text and the disagreement is recorded rather than reconciled.** The
-- plan says "limit $75,200 as of 2026-08" and "the legacy draw ($7,980) is repaid from its
-- position's own sale proceeds (§6.1)". Zak said 75,000 and none drawn while §6.1's liquidation was
-- in flight, so the repayment has either happened or is happening. The plan's figure was stamped
-- "as of 2026-08"; his is today's. For a FACT about an external account, the account wins and the
-- erratum is logged (§5.6). For a RULE, the plan wins — and the rule here is unchanged: drawn
-- balance <= 50% of the facility limit, whatever the limit is.
insert into balances (account, as_of, cash, drawn, credit_limit, source)
values ('LOC', current_date, null, 0, 75000, 'zak');

-- The consequence, computed rather than asserted, because it is a HARD cap:
--
--     limit      75,000
--     cap (50%)  37,500
--     §2.3 ramp  12,500 + 12,500 + 12,600 = 37,600
--     breach     +100 on the third tranche
--
-- §2.3's ramp was sized against the $75,200 limit, where it lands exactly on the cap. At 75,000 it
-- does not. **Nothing here changes the ramp** — the amounts are plan text and §0.3 reserves that to
-- Zak. What changes is that the system now notices: `brief.tranche_lines` compares the remaining
-- planned tranches against live headroom and prints a BREACH AHEAD line, so the overshoot is read
-- in August rather than discovered at the third draw in October.
insert into observations (kind, ticker, body, detail)
select 'note', null,
       '§2.3 arithmetic, 2026-08-16: Zak states the LOC limit at 75,000 with none drawn. The cap '
       'is therefore 37,500, and §2.3''s three-tranche ramp totals 37,600 — a 100 overshoot on the '
       'third tranche. The ramp was sized against the plan''s stated 75,200 limit, where it fits '
       'exactly. Either the limit is 75,200 or tranche 3 is 12,500; both are Zak''s to rule (§0.3). '
       'The brief now prints a BREACH AHEAD line whenever the remaining ramp exceeds live headroom.',
       '{"migration":"057_the_facility_and_the_freeze","cap":37500,"ramp":37600,"over":100}'::jsonb
 where not exists (select 1 from observations where body like '§2.3 arithmetic, 2026-08-16%');

-- ---- 2. §5.5's freeze ------------------------------------------------------------------------
--
-- "**5.5 Freeze.** Zak may halt buying at any time, in any words; that state is a freeze. A freeze
--  halts all buys (entries, refills, displacement buys, levered tranches). Exits fire normally;
--  proceeds park. Lifted only by Zak's word."
--
-- Until today nothing in this repository implemented that clause — it was law with no code behind
-- it, which is the worst state for a safety control because it reads as present.
--
-- It lives in `config` under the key `freeze`, and `config` rather than a table of its own because
-- §5.5 turns on WORDS: the freeze is a row carrying what Zak said, the lift is another row beside
-- it, and neither overwrites the other. "When was buying halted, in what words, and when was it
-- lifted" is then answerable from the ledger rather than from an absence.
--
--     -- halt
--     insert into config (key, value, note, set_by) values
--       ('freeze', '{"on": true, "words": "<Zak''s exact words>"}'::jsonb, null, 'zak');
--     -- lift
--     insert into config (key, value, note, set_by) values
--       ('freeze', '{"on": false, "words": "<Zak''s exact words>"}'::jsonb, null, 'zak');
--
-- **No row means never frozen, and that is deliberate.** §3.4's gate reads OFF when it cannot be
-- evaluated, because an unevaluable gate must SELL. A freeze only ever stops action, so an unknown
-- freeze must read off — the safe default of a control that halts is off, and the safe default of
-- a control that acts is on. The two clauses point opposite ways for that reason.
--
-- A seed row is written so the key exists, the shape is documented in the data, and the first
-- reading is an explicit "not frozen" rather than an absence.
insert into config (key, value, note, set_by)
select 'freeze', '{"on": false, "words": null}'::jsonb,
       '§5.5 — buying is not halted. Set on=true with Zak''s exact words to freeze; lifted only by '
       'his word. Exits fire normally under a freeze (§5.4).',
       'yuna'
 where not exists (select 1 from config where key = 'freeze');
