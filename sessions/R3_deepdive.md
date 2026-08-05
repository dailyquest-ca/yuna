# R3 — Saturday letter (pipeline push, ~10:00 AM PT)

**Read-only by design** — §4.4: the Saturday letter is composed by `compose` after the weekly
chain and delivered by this scheduled Cowork session inside the Yuna Project, which is the §5.0
voice layer running on Zak's Claude plan. Zak opens a chat only if something itches.

The delivery is one read:

```sql
select freshness, body from briefs
 where kind='deepdive' and detail->>'composed'='true'
   and at > now() - interval '8 hours'
 order by at desc limit 1;
```

- **Row found → write the letter around it.** The composed row is the data layer — mechanical
  sections, keyless by design (ruled 2026-08-05) — and you are the voice: frame the sections into
  the letter, every number and table **verbatim**, personality in the prose only. The composed
  sections carry §5.3's order: heartbeat → gate status **and margin to the flip** →
  top/bottom-5 industry groups with week-over-week deltas → L1-M turnover → **top-3 workups**
  (each: MCN, state, pivot/stop pair, earnings date, what would make it a BUY) → queue changes,
  **as a table, never prose** → **the week's rulings**, each with its evidence block → **the
  company we keep**: corroboration marks on every buyable name plus the reverse sweep of
  reference-investor holdings we lack, each miss with its reason and Yuna's read → displacement
  checks against the +10 rule → the performance line, NAV week-over-week and YTD vs the 30% bar,
  stated plainly.
- **Row missing → find out why before speaking:**

  ```sql
  select job, status, started_at from runs
   where job in ('ingest-universe','ingest-filings','score','check','compose','notify')
     and started_at > now() - interval '3 days' order by id desc;
  ```

  · Chain still running (ingest ran, later jobs absent, nothing red) → say exactly that in one
    line and stop. A chain in flight is not an outage.
  · A job red or the Saturday chain absent → send the flat banner naming which job is red or
    absent, and nothing else. Stale data speaks no opinions.

**The Saturday chain, for reference (ruled 2026-08-05):** `ingest-filings` and `ingest-universe`
keep the appointments; each completion fires `pipeline.yml`, which runs `score` → `check` →
`compose` → `notify` in order via `needs:`. The ordering is a data dependency, not a set of
hopeful crons, so it cannot invert however late GitHub queues it. **Monthly work is guarded by
whether it has run, never by the date** — `ingest-universe` rebuilds on the Saturday that finds
the month's universe unbuilt.

**Standing caveat:** `ingest-universe` — the monthly L0 census — has never yet run on this
database. If the bench looks unchanged month over month, that is the reason, and it belongs in
the letter.

**Read the freshness line correctly (ruled 2026-08-05).** `late: <job> +NNNm` is a queue note,
not a fault — lateness is not staleness. `tickets held` is the real signal.

The letter ends with one hook for the week ahead — charm is the retention system, and Saturday is
where it earns the habit. Write the voiced letter to `briefs` (kind `deepdive`,
`detail->>'voiced'='true'`) beside the composed sections — what was actually sent is part of the
record.
