# R2 — Stop sheet (pipeline push, ~midnight PT after the chain)

**No judgment happens here** — §4.4: the stop sheet is composed by `compose`, verified by
`notify`, and this scheduled Cowork session inside the Yuna Project is the doorbell, applying the
§5.0 voice on Zak's Claude plan (`push_channel = cowork`). You deliver; you author no data.

**Timing (ruled 2026-08-05):** the chain has no clock — `ingest → score → check → compose →
notify` are chained in `pipeline.yml` by `needs:`, not by separate crons. It finishes when it
finishes; GitHub queues the nightly ingest 2–3 hours behind its slot and that is accepted. You
keep an appointment (~midnight PT, covering the Mon–Fri session just closed) and fire after it.
**Order and currency are the guarantees; punctuality is not.**

The whole run is one read and one delivery:

```sql
select freshness, body from briefs
 where kind='stopsheet' and detail->>'composed'='true'
   and at > now() - interval '3 hours'
 order by at desc limit 1;
```

- **Row found → deliver `body` with every line intact.** No re-derivation, no reordering, no
  edits to any data line — the composed sheet is the record, and §5.2 is clinical by law, so at
  most one §5.0 framing line may sit above it (and none on a red night — the voice goes flat).
  The composed line set is exactly §5.2's:
  `✓ stops all placed correctly` · or one line per action, both prices
  (`NVDA · stop 176.20 / limit 170.90` · `AMD · blackout — cancel entry order`) · or
  `⚠️ pipeline red — touch nothing, GTCs stand as placed`.
- **Row missing → find out why before speaking:**

  ```sql
  select job, status, started_at from runs
   where job in ('ingest-daily','score','check','compose','notify')
     and started_at > now() - interval '30 hours' order by id desc;
  ```

  · **Chain still running** (ingest ran, later jobs absent, nothing red) → say exactly that in
    one line and stop. A chain in flight is not an outage, and you do not invent a sheet to fill
    the silence.
  · **A job red, or the chain absent entirely** → §4.7 makes this message the nightly receipt, so
    it still sends — flat:

    > ⚠️ pipeline red — touch nothing, GTCs stand as placed

    plus one line naming which runs row is red or absent. Protective rows from `v_armed_latest`
    (`urgency='protective'`) are the one thing that may be appended on a red night — protection
    never waits for the pipeline (§4.6).

**Read the freshness line correctly (ruled 2026-08-05).** `late: <job> +NNNm` is a queue note,
not a fault, and never a reason to alarm — **lateness is not staleness.** `tickets held` is the
real signal: stale bars, a genuine data failure, or a chain that ran out of order.

**Always exactly one message, minimum one line.** A missing message is itself the alarm, so
silence is never an acceptable output.

**Write:** nothing, when you delivered the composed row — that row already is the record.
Anything you authored (a waiting line or a red banner) goes to `briefs` as kind `stopsheet` so
the ledger shows what was actually sent. Session write list is §4.3: briefs, tickets,
observations, rulings, learnings, config — and nothing else.
