# R3 — Saturday letter (pipeline push, ~08:00 PT)

**Read-only by design** — §4.4 (2026-08-04): the Saturday letter is composed by `compose` after
the weekly chain (`ingest-universe` 10:00 UTC on 1st Saturdays · `ingest-filings` 11:00 · `score`
12:00, the full weekly rank · `check` 12:30 · `compose` 13:00 · `notify` 13:15) and delivered by
the Routine in the Yuna project. Zak opens a chat only if something itches.

The delivery is one read:

```sql
select freshness, body from briefs
 where kind='deepdive' and detail->>'composed'='true'
   and at > now() - interval '8 hours'
 order by at desc limit 1;
```

- **Row found → write the letter around it.** The composed row is the data layer — mechanical
  sections, keyless by design (ruled 2026-08-05) — and the Routine is the §5.0 voice layer,
  running on Zak's Claude plan: frame the sections into the letter, every number and table
  **verbatim**, personality in the prose only. The composed sections carry §5.3's order: heartbeat →
  gate status **and margin to the flip** → top/bottom-5 industry groups with week-over-week
  deltas → L1-M turnover → **top-3 workups** (each: MCN, state, pivot/stop pair, earnings date,
  what would make it a BUY) → queue changes, **as a table, never prose** → **the week's
  rulings**, each with its evidence block → **the company we keep**: corroboration marks on
  every buyable name plus the reverse sweep of reference-investor holdings we lack, each miss
  with its reason and Yuna's read → displacement checks against the +10 rule → the performance
  line, NAV week-over-week and YTD vs the 30% bar, stated plainly.
- **Row missing → send the flat banner** naming which job in the Saturday chain is red or
  absent, and nothing else. Stale data speaks no opinions.

The letter ends with one hook for the week ahead — charm is the retention system, and Saturday
is where it earns the habit. Write the voiced letter to `briefs` (kind `deepdive`,
`detail->>'voiced'='true'`) beside the composed sections — what was actually sent is part of
the record.
