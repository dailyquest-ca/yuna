# R2 — Evening stop sheet (pipeline push, weekdays ~20:30 PT)

**No session judges here** — §4.4 (2026-08-04): the stop sheet is composed by `compose` and
delivered by `notify`; under `push_channel = cowork` the scheduled Routine in the Yuna project is
the doorbell. The whole run is one read and one delivery:

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
- **Row missing → the pipeline failed to speak**, and §4.7 makes this message the nightly
  receipt, so it still sends — flat:

  > ⚠️ pipeline red — touch nothing, GTCs stand as placed

  plus one line naming which runs row is red or absent (`ingest-daily` 02:00/03:00 UTC ·
  `score` 03:30 · `check` 03:50 · `compose` 04:05 · `notify` 04:20). Protective rows from
  `v_armed_latest` (`urgency='protective'`) are the one thing that may be appended on a red
  night — protection never waits for the pipeline (§4.6).

**Always exactly one message, minimum one line.** A missing message is itself the alarm, so
silence is never an acceptable output. The delivery writes nothing new when the composed row
exists — that row already is the record; the fallback banner (the missing-row case) is written
to `briefs` as kind `stopsheet` so the ledger shows what was actually sent.
