-- 014_isrg_cost.sql — ISRG cost basis supplied by Zak, 2026-07-31.
-- 352.45 blended across all 26 shares, superseding the journal's partial 11 @ 345.00.

update book set avg_cost = 352.450,
  note = 'blended avg cost 352.45 for 26 sh — Zak, 2026-07-31; supersedes the journal''s partial 11 @ 345.00'
  where ticker = 'ISRG.US' and status = 'open';

insert into observations (kind, ticker, body, detail) values
 ('note', 'ISRG.US',
  'Cost basis CLOSED: 352.45 blended over 26 shares. The journal''s 11 @ 345.00 covered only the '
  '2026-07-21 lot; the later 15 shares are now inside the blend.',
  '{"avg_cost":352.45,"qty":26,"source":"zak","supersedes":"journal 11 @ 345.00"}');
