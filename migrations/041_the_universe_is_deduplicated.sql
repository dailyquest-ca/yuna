-- 041_the_universe_is_deduplicated.sql — 2026-08-11.
--
-- The backtest universe is `universe.kind='stock' and ticker like '%.US'`, and that let four
-- things in that are not tradeable equity lines for this sleeve:
--
--   * the SAME security under two ticker spellings — GEF-B/GEFB, HPE-P-C/HPE-PC, FOUR-P-A/FOUR-PA
--   * the SAME company after a rename — TPX -> SGI, PENG_old -> SGH. Runs 29/32/34/35/36 held
--     BOTH TPX and SGI: one company, two positions, and max_names / the sleeve cap / the heat cap
--     each counted it as two names' worth of diversification it did not have
--   * preferred shares and warrants classified as `stock` — VGNT-W, HPE-P-C, FOUR-P-A. §3.2 is a
--     common-equity momentum rule; a preferred does not have a trend template
--   * at least one pair of UNRELATED companies sharing an identical price series (APPS/BDN, 653
--     identical bars). That is vendor corruption, not a naming question, and it is quarantined
--     here pending a re-pull rather than silently traded
--
-- An exclusion table rather than a delete: the bars stay, the reason is on the record, and a name
-- can be readmitted by deleting one row once the vendor data is re-verified.

create table if not exists universe_excluded (
  ticker text primary key,
  reason text not null,
  detail text,
  excluded_at timestamptz not null default now()
);

insert into universe_excluded (ticker, reason, detail) values
  ('SGI.US',      'duplicate_listing', 'same series as TPX.US (Tempur Sealy renamed); keep TPX'),
  ('PENG_old.US', 'duplicate_listing', 'same series as SGH.US; keep SGH'),
  ('GEFB.US',     'duplicate_listing', 'share-class spelling of GEF-B.US'),
  ('HPE-PC.US',   'duplicate_listing', 'share-class spelling of HPE-P-C.US'),
  ('FOUR-PA.US',  'duplicate_listing', 'share-class spelling of FOUR-P-A.US'),
  ('HPE-P-C.US',  'not_common_equity', 'preferred share'),
  ('FOUR-P-A.US', 'not_common_equity', 'preferred share'),
  ('GEF-B.US',    'not_common_equity', 'class B share line, thin secondary listing'),
  ('VGNT-W.US',   'not_common_equity', 'warrant'),
  ('VGNT.US',     'quarantine',        'warrant/common pair share an identical series — re-pull'),
  ('APPS.US',     'quarantine',        'identical 653-bar series to BDN.US, unrelated companies'),
  ('BDN.US',      'quarantine',        'identical 653-bar series to APPS.US, unrelated companies')
on conflict (ticker) do nothing;

alter table universe_excluded enable row level security;
drop trigger if exists guard_universe_excluded on universe_excluded;
create trigger guard_universe_excluded before insert or update or delete on universe_excluded
  for each row execute function yuna_jobs_only();
