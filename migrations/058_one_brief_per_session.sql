-- 058_one_brief_per_session.sql — 2026-08-17. The key the desk's last mile was missing.
--
-- `briefs` has never had a uniqueness constraint. The retired engine composed several kinds a
-- night and deliberately APPENDS a fresh row when a re-composition differs, carrying a
-- `recomposed` flag — so a blanket unique key would break a job that still exists and still has
-- tests. The constraint is therefore partial, over v1.0's two kinds only.
--
-- For those two the pair (kind, session_date) IS the identity: §5.1 renders one brief per session
-- and §4.1 one letter per week. With the key here, `compose` upserts — the newest render of a
-- session replaces the previous one, `at` moves with it, and the desk always serves what the
-- latest `check` actually concluded.
--
-- **The bug this closes was live tonight, and it was two rules that could not both hold.**
-- `compose` skipped the write when a brief already existed for the session, and `notify` only
-- recognised a brief written in the last three hours. So the first chain pass of a session wrote
-- the brief, and from the third hour on every later pass reported the desk silent while a correct
-- brief sat in the table. On a weekend that is permanent: Friday's bar is the newest session until
-- Tuesday's ingest, so Saturday, Sunday and Monday all report a missing message that was composed
-- correctly. `notify` now anchors on the session rather than the clock, which is the same anchor
-- the rest of the system already uses.
--
-- Nothing is deleted. §0.6 keeps the record, and there is no duplicate to collapse — these two
-- kinds are new as of §6.3 and the constraint goes on before they can accumulate one.

-- Keyed on WHO WROTE THE ROW, not on the kind name. The retired `compose.py` also writes
-- `kind = 'nightly'` — a collision I assumed away and the legacy tests caught — so a predicate on
-- the kind would constrain a job that appends by design. `detail->>'engine' = 'v1'` says what is
-- actually meant: these rows belong to the new machine, and only the new machine's rows are one
-- per session.
create unique index if not exists briefs_engine_kind_session_key
  on briefs(kind, session_date)
  where (detail->>'engine') = 'v1';

comment on index briefs_engine_kind_session_key is
  'One brief per session for rows brief.py wrote, so compose upserts and the newest render of a '
  'night is what the desk serves - a re-score legitimately changes the verdict, the sheet and the '
  'banner, and the retry ingest makes a second pass the NORMAL case. Partial on detail->>engine '
  'rather than on kind, because the retired compose.py writes kind=nightly too and appends by design.';
