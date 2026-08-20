-- 062_a_file_uploaded_twice_lands_once.sql — 2026-08-20. Hardening from the first real import.
--
-- Zak uploaded the first real Wealthsimple export tonight (activitiesexport20260819.csv) and the
-- chat did everything the contract asked: three broker rows, both SPMO opening balances superseded
-- by the purchases that explain them, the book's cost basis recomputed to the broker's pennies.
-- Verifying it end to end found exactly one gap, and it is the one §4.2's idempotence discipline
-- exists for:
--
--   **Nothing stops the same file landing twice.** The export carries no per-row id, so the chat
--   put the filename in `external_ref` — on all three rows, the same string. `broker_ref` (052's
--   unique key) is only set by the manifest path, so a re-upload of the same CSV inserts three
--   more rows, the trigger doubles the positions, and NOTHING catches it: the ledger and the book
--   AGREE on the doubled number, so `v_ledger_vs_book` is empty, and the openings/staleness views
--   have nothing to say either. A silent 1,620-share SPMO book is the ghost book with the sign
--   flipped, reachable by an ordinary mistake — uploading a file twice.
--
-- Two changes:
--
-- 1. `external_ref` becomes UNIQUE (partial, like broker_ref), so a re-import COLLIDES instead of
--    doubling. Tonight's three rows share one value, so they are first rewritten to be row-unique
--    — the filename stays (provenance is the point of the field), a #n suffix disambiguates. The
--    contract now tells sessions to synthesize exactly that shape when the bank supplies no id.
--
-- 2. §4.4's reconciliation gauge learns that a chat-imported export IS a receipt. 052 keyed
--    `last_receipt` on `broker_ref`, which only the manifest path sets — so the gauge's "newest
--    broker fill folded in" would read null forever on a desk whose receipts all arrive through
--    chat. It now reads the newest live `grade = 'broker'` trade date, which is the definition in
--    words: the last day the bank's own record moved this ledger.

-- ---- 1. per-row refs, then the uniqueness that makes re-imports collide -------------------------
with numbered as (
  select id, external_ref,
         row_number() over (partition by external_ref order by id) as n,
         count(*)     over (partition by external_ref)             as dupes
    from transactions
   where external_ref is not null)
update transactions t
   set external_ref = t.external_ref || '#' || n.n
  from numbered n
 where n.id = t.id and n.dupes > 1;

create unique index if not exists transactions_external_ref_key
  on transactions(external_ref) where external_ref is not null;

comment on column transactions.external_ref is
  'The bank''s own identifier for the row when the export carries one; when it does not, the '
  'importing session synthesizes <filename>#<row>. UNIQUE among non-null, so the same export '
  'uploaded twice collides on insert instead of doubling every position it touches.';

-- ---- 2. a chat-imported export is a receipt ------------------------------------------------------
create or replace view v_reconciliation_age as
select
  (select max(trade_date) from transactions
    where grade = 'broker' and superseded_by is null)                          as last_receipt,
  (select max(finished_at) from runs
    where job = 'reconcile' and status in ('green','amber'))                   as last_attested,
  (select count(*) from tickets
    where session_date is not null and state = 'approved')                     as awaiting_receipt,
  (select min(session_date) from tickets
    where session_date is not null and state = 'approved')                     as oldest_awaiting;

comment on view v_reconciliation_age is
  'S4.4 book-vs-broker reconciliation age. last_receipt is the newest day the bank''s own record '
  '(grade = broker, any route - manifest or chat import) moved this ledger; last_attested is when '
  'the position comparison last RAN. They differ on purpose - a quiet week has no fills and still '
  'needs the comparison to have happened.';
